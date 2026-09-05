/* ============================================================
   HAPPY HOUR FINDER — the night-out layer (PLAYBOOK-NIGHT-OUT.md)

   Public:
     POST /subscribe                 {email, zone_id}        -> pending row
     GET  /subscribe/confirm?t=..    the link in the mail    -> confirmed, redirect
     GET  /subscribe/leave?t=..      the link in every mail  -> row deleted
     GET  /live/events.json[?zone=]  approved events, today + 14 days, by lid
     POST /venue/events              {token, events:[...]}   -> the venue's own
                                                                rows, published

   Admin (X-Admin-Token):
     GET  /admin/events?status=pending
     POST /admin/events              {events:[...]}  bulk insert from the reader,
                                                     status pending
     POST /admin/events/review/<id>  {status: approved|rejected, note}
     POST /admin/venue-token/<lid>   {contact}       mint the venue's magic link
     GET  /admin/subscribers?status=pending|confirmed

   Nothing here sends mail unless RESEND_API_KEY is set on the Worker. Without
   it a subscriber sits `pending` with `mailed_at` NULL and a script on Paul's
   PC can send the confirm link from this repo's own address. The row is never
   mailed twice by two senders because both set mailed_at first.
   ============================================================ */

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const CLOCK_RE = /^([01]\d|2[0-4]):[0-5]\d$/;
const KINDS = new Set(["live_music", "trivia", "dj", "comedy", "other"]);
const HORIZON_DAYS = 14;
const MAX_EVENTS_PER_POST = 60;
const MAX_SUBSCRIBES_PER_DAY = 5;

const json = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

const nowIso = () => new Date().toISOString();

function randomToken(bytes = 24) {
  const b = new Uint8Array(bytes);
  crypto.getRandomValues(b);
  return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
}

async function sha256Hex(s) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function tokenMatches(given, expected) {
  if (!given || !expected || given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < given.length; i++) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

/* The local date, Philadelphia. The Worker runs in UTC; "tonight" does not. */
function localToday(offsetDays = 0) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return d.toLocaleDateString("en-CA", { timeZone: "America/New_York" }); // YYYY-MM-DD
}

/* ---- events: validation shared by every writer ------------------------ */

/* One event row from untrusted JSON. Returns {row} or {error}. Pure. */
export function eventFrom(raw, { lid, zone_id, source_kind, status }) {
  if (!raw || typeof raw !== "object") return { error: "not an object" };
  const date = String(raw.date || "").trim();
  if (!DATE_RE.test(date)) return { error: "date must be YYYY-MM-DD" };
  const act = String(raw.act || "").trim().slice(0, 120);
  if (!act) return { error: "act is required" };
  const kind = String(raw.kind || "live_music").trim();
  if (!KINDS.has(kind)) return { error: `kind must be one of ${[...KINDS].join(", ")}` };
  const clock = (v) => {
    if (v == null || v === "") return null;
    const s = String(v).trim();
    return CLOCK_RE.test(s) ? s : undefined;
  };
  const start = clock(raw.start);
  const end = clock(raw.end);
  if (start === undefined || end === undefined) return { error: "times must be HH:MM, 24h" };
  let cover = raw.cover_usd;
  if (cover === "" || cover == null) cover = null;
  else {
    cover = Number(cover);
    if (!Number.isFinite(cover) || cover < 0 || cover > 500) return { error: "cover_usd out of range" };
  }
  let setMin = raw.set_minutes;
  if (setMin === "" || setMin == null) setMin = null;
  else {
    setMin = Number(setMin);
    if (!Number.isInteger(setMin) || setMin <= 0 || setMin > 600) return { error: "set_minutes out of range" };
  }
  let kitchen = raw.kitchen_open;
  if (kitchen === "" || kitchen == null) kitchen = null;
  else kitchen = kitchen === true || kitchen === 1 || kitchen === "1" || kitchen === "yes" ? 1 : 0;
  const sourceUrl = raw.source_url ? String(raw.source_url).slice(0, 500) : null;
  const quote = raw.quote ? String(raw.quote).slice(0, 500) : null;
  return {
    row: {
      lid: String(lid),
      zone_id: zone_id || null,
      date,
      start,
      end,
      set_minutes: setMin,
      act,
      kind,
      cover_usd: cover,
      kitchen_open: kitchen,
      source_kind,
      source_url: sourceUrl,
      quote,
      status,
    },
  };
}

/* Two rows describe the same thing when venue, date and act match. The act is
   compared loosely so "Rhythm & Blondes" and "rhythm and blondes" collide. */
export function eventFingerprint(row) {
  const act = String(row.act || "").toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]+/g, " ").trim();
  return `${row.lid}|${row.date}|${act}`;
}

async function insertEvents(env, rows) {
  const now = nowIso();
  const ids = [];
  for (const r of rows) {
    const id = await sha256Hex(eventFingerprint(r) + "|" + r.source_kind);
    ids.push(id.slice(0, 32));
  }
  // Same fingerprint from the same source kind is one row, refreshed: a
  // calendar re-read every week must not stack seven copies of Friday's band.
  const stmts = rows.map((r, i) =>
    env.DB.prepare(
      `INSERT INTO events (id, lid, zone_id, date, start, end, set_minutes, act, kind,
                           cover_usd, kitchen_open, source_kind, source_url, quote, status, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         start = excluded.start, end = excluded.end, set_minutes = excluded.set_minutes,
         cover_usd = excluded.cover_usd, kitchen_open = excluded.kitchen_open,
         source_url = excluded.source_url, quote = excluded.quote,
         -- a row a person already ruled on keeps that ruling
         status = CASE WHEN events.status = 'pending' THEN excluded.status ELSE events.status END`
    ).bind(
      ids[i], r.lid, r.zone_id, r.date, r.start, r.end, r.set_minutes, r.act, r.kind,
      r.cover_usd, r.kitchen_open, r.source_kind, r.source_url, r.quote, r.status, now
    )
  );
  if (stmts.length) await env.DB.batch(stmts);
  return ids;
}

/* ---- GET /live/events.json -------------------------------------------- */

export async function liveEvents(env, url, headers) {
  const zone = (url.searchParams.get("zone") || "").slice(0, 64);
  const from = localToday(0);
  const to = localToday(HORIZON_DAYS);
  const q = zone
    ? env.DB.prepare(
        `SELECT id, lid, zone_id, date, start, end, set_minutes, act, kind, cover_usd,
                kitchen_open, source_kind, source_url
           FROM events WHERE status = 'approved' AND date BETWEEN ? AND ? AND zone_id = ?
           ORDER BY date, start`
      ).bind(from, to, zone)
    : env.DB.prepare(
        `SELECT id, lid, zone_id, date, start, end, set_minutes, act, kind, cover_usd,
                kitchen_open, source_kind, source_url
           FROM events WHERE status = 'approved' AND date BETWEEN ? AND ?
           ORDER BY date, start`
      ).bind(from, to);
  const { results } = await q.all();
  const byLid = {};
  for (const r of results) (byLid[r.lid] ||= []).push(r);
  return json(
    { generated_at: nowIso(), today: from, horizon_days: HORIZON_DAYS, venues: byLid },
    200,
    { ...headers, "Cache-Control": "public, max-age=60" }
  );
}

/* ---- POST /venue/events ------------------------------------------------ */

export async function venueEvents(request, env, headers) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Expected JSON." }, 400, headers);
  }
  const token = String(body.token || "").trim();
  if (!token) return json({ error: "No token." }, 401, headers);
  const venue = await env.DB.prepare("SELECT lid FROM venue_tokens WHERE token = ?").bind(token).first();
  if (!venue) return json({ error: "That link is not valid any more." }, 401, headers);

  const list = Array.isArray(body.events) ? body.events.slice(0, MAX_EVENTS_PER_POST) : [];
  if (!list.length) return json({ error: "No events in the form." }, 400, headers);
  const zone = await zoneOf(env, venue.lid);
  const rows = [];
  const errors = [];
  list.forEach((raw, i) => {
    // The venue is the author of its own calendar, so its rows publish.
    const out = eventFrom(raw, { lid: venue.lid, zone_id: zone, source_kind: "venue_form", status: "approved" });
    if (out.error) errors.push({ index: i, error: out.error });
    else rows.push(out.row);
  });
  if (errors.length) return json({ error: "Some rows did not validate.", errors }, 400, headers);
  const ids = await insertEvents(env, rows);
  await env.DB.prepare("UPDATE venue_tokens SET last_used_at = ? WHERE lid = ?").bind(nowIso(), venue.lid).run();
  return json({ lid: venue.lid, published: ids.length, ids }, 201, headers);
}

/* Which zone a licence lives in, from the same static file the board uses. */
async function zoneOf(env, lid) {
  try {
    const base = env.FRONTEND_ORIGIN || "https://paulrenzi.github.io";
    const res = await fetch(base + "/happy-hour-finder/data/lid-zone.json", {
      cf: { cacheTtl: 3600, cacheEverything: true },
    });
    if (!res.ok) return null;
    const map = await res.json();
    return map[String(lid)] || null;
  } catch {
    return null;
  }
}

/* ---- subscribe ---------------------------------------------------------- */

export async function subscribe(request, env, headers) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Expected JSON." }, 400, headers);
  }
  const email = String(body.email || "").trim().toLowerCase().slice(0, 254);
  if (!EMAIL_RE.test(email)) return json({ error: "That does not look like an email address." }, 400, headers);
  const zone = String(body.zone_id || "").slice(0, 64) || null;

  const ip = request.headers.get("CF-Connecting-IP") || "";
  const ipHash = await sha256Hex(`${env.IP_SALT || "unsalted"}:sub:${ip}`);
  const day = nowIso().slice(0, 10);
  const seen = await env.DB.prepare("SELECT n FROM rate WHERE ip_hash = ? AND day = ?").bind(ipHash, day).first();
  if (seen && seen.n >= MAX_SUBSCRIBES_PER_DAY) return json({ error: "Try again tomorrow." }, 429, headers);
  await env.DB.prepare(
    "INSERT INTO rate (ip_hash, day, n) VALUES (?, ?, 1) ON CONFLICT(ip_hash, day) DO UPDATE SET n = n + 1"
  ).bind(ipHash, day).run();

  const existing = await env.DB.prepare("SELECT status, token FROM subscribers WHERE email = ?").bind(email).first();
  if (existing && existing.status === "confirmed") {
    // Same answer as a new signup: the endpoint must not say whether an
    // address is on the list.
    return json({ status: "pending" }, 202, headers);
  }
  const token = existing ? existing.token : randomToken();
  if (!existing) {
    await env.DB.prepare(
      "INSERT INTO subscribers (email, zone_id, status, token, created_at, ip_hash) VALUES (?, ?, 'pending', ?, ?, ?)"
    ).bind(email, zone, token, nowIso(), ipHash).run();
  } else if (zone) {
    await env.DB.prepare("UPDATE subscribers SET zone_id = ? WHERE email = ?").bind(zone, email).run();
  }
  if (env.RESEND_API_KEY) await sendConfirm(env, email, token, request.url);
  return json({ status: "pending" }, 202, headers);
}

export function confirmLink(origin, token) {
  return `${origin}/subscribe/confirm?t=${token}`;
}
export function leaveLink(origin, token) {
  return `${origin}/subscribe/leave?t=${token}`;
}

async function sendConfirm(env, email, token, requestUrl) {
  const origin = new URL(requestUrl).origin;
  const from = env.MAIL_FROM || "Happy Hour Finder <hello@happyhourfinder.example>";
  const site = env.FRONTEND_ORIGIN + "/happy-hour-finder/";
  const text =
    `You asked for new happy hours and nights out near you.\n\n` +
    `Confirm here: ${confirmLink(origin, token)}\n\n` +
    `If that wasn't you, ignore this and nothing more will come.\n` +
    `Board: ${site}\n`;
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from, to: [email], subject: "Confirm: happy hours near you", text }),
  });
  if (res.ok) {
    await env.DB.prepare("UPDATE subscribers SET mailed_at = ? WHERE email = ? AND mailed_at IS NULL")
      .bind(nowIso(), email)
      .run();
  } else {
    console.error("resend", res.status, await res.text());
  }
}

function redirectToSite(env, flag) {
  const to = (env.FRONTEND_ORIGIN || "https://paulrenzi.github.io") + "/happy-hour-finder/?" + flag;
  return new Response(null, { status: 303, headers: { Location: to, "Cache-Control": "no-store" } });
}

export async function subscribeConfirm(env, url) {
  const t = (url.searchParams.get("t") || "").slice(0, 64);
  if (!t) return redirectToSite(env, "subscribed=invalid");
  const res = await env.DB.prepare(
    "UPDATE subscribers SET status = 'confirmed', confirmed_at = ? WHERE token = ? AND status = 'pending'"
  ).bind(nowIso(), t).run();
  return redirectToSite(env, res.meta.changes ? "subscribed=1" : "subscribed=invalid");
}

export async function subscribeLeave(env, url) {
  const t = (url.searchParams.get("t") || "").slice(0, 64);
  if (t) await env.DB.prepare("DELETE FROM subscribers WHERE token = ?").bind(t).run();
  return redirectToSite(env, "subscribed=left");
}

/* ---- admin verbs, called from index.js's admin() after the token check --- */

export async function adminNightOut(request, env, url, headers, parts) {
  const verb = parts[1];

  if (verb === "events" && request.method === "GET" && !parts[2]) {
    const status = url.searchParams.get("status") || "pending";
    const { results } = await env.DB.prepare(
      `SELECT * FROM events WHERE status = ? ORDER BY date, lid LIMIT 500`
    ).bind(status).all();
    return json({ events: results }, 200, headers);
  }

  if (verb === "events" && request.method === "POST" && !parts[2]) {
    const body = await request.json();
    const list = Array.isArray(body.events) ? body.events : [];
    const rows = [];
    const errors = [];
    list.forEach((raw, i) => {
      const lid = String(raw.lid || "").trim();
      if (!lid) return errors.push({ index: i, error: "lid is required" });
      const kind = String(raw.source_kind || "page");
      if (!["image", "page", "ticketing", "band_claim"].includes(kind)) {
        return errors.push({ index: i, error: "source_kind" });
      }
      const out = eventFrom(raw, { lid, zone_id: raw.zone_id || null, source_kind: kind, status: "pending" });
      if (out.error) errors.push({ index: i, error: out.error });
      else rows.push(out.row);
    });
    const ids = await insertEvents(env, rows);
    return json({ inserted: ids.length, ids, errors }, errors.length && !ids.length ? 400 : 200, headers);
  }

  if (verb === "events" && parts[2] === "review" && parts[3] && request.method === "POST") {
    const body = await request.json();
    if (!["approved", "rejected"].includes(body.status)) return json({ error: "status" }, 400, headers);
    const res = await env.DB.prepare(
      "UPDATE events SET status = ?, reviewed_at = ?, review_note = ? WHERE id = ?"
    ).bind(body.status, nowIso(), (body.note || "").slice(0, 500) || null, parts[3]).run();
    if (!res.meta.changes) return json({ error: "no such event" }, 404, headers);
    return json({ id: parts[3], status: body.status }, 200, headers);
  }

  if (verb === "venue-token" && parts[2] && request.method === "POST") {
    const body = await request.json().catch(() => ({}));
    const lid = parts[2].slice(0, 64);
    const token = randomToken();
    await env.DB.prepare(
      `INSERT INTO venue_tokens (lid, token, contact, created_at) VALUES (?, ?, ?, ?)
       ON CONFLICT(lid) DO UPDATE SET token = excluded.token, contact = excluded.contact,
                                      created_at = excluded.created_at, last_used_at = NULL`
    ).bind(lid, token, (body.contact || "").slice(0, 200) || null, nowIso()).run();
    return json({ lid, token, form: `${env.FRONTEND_ORIGIN}/happy-hour-finder/venue.html#${token}` }, 201, headers);
  }

  if (verb === "subscribers" && request.method === "GET") {
    const status = url.searchParams.get("status") || "confirmed";
    const { results } = await env.DB.prepare(
      "SELECT email, zone_id, status, token, created_at, confirmed_at, mailed_at FROM subscribers WHERE status = ? ORDER BY created_at LIMIT 5000"
    ).bind(status).all();
    return json({ subscribers: results }, 200, headers);
  }

  if (verb === "subscribers" && parts[2] === "mailed" && request.method === "POST") {
    // The PC-side sender reports what it sent, so nothing is mailed twice.
    const body = await request.json();
    const emails = Array.isArray(body.emails) ? body.emails.slice(0, 500) : [];
    const now = nowIso();
    await env.DB.batch(
      emails.map((e) => env.DB.prepare("UPDATE subscribers SET mailed_at = ? WHERE email = ? AND mailed_at IS NULL").bind(now, String(e).toLowerCase()))
    );
    return json({ marked: emails.length }, 200, headers);
  }

  return null; // not ours
}

export { tokenMatches as _tokenMatches };
