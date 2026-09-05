/* ============================================================
   HAPPY HOUR FINDER — photo lane write path (Cloudflare Worker)

   Public:
     POST /submit           multipart: photo, lid, venue_name, note, cf_token
     GET  /health

   Admin (X-Admin-Token; the admin page, ingest/extract_photo_deals.py and
   ingest/review_photos.py):
     GET  /admin               the review page itself (no token; it asks)
     GET  /admin/queue?status=pending
     GET  /admin/photo/<id>
     GET  /admin/board         what is published per LID, for the reviewer
     POST /admin/extract/<id>  {extracted} | {error}
     POST /admin/read/<id>     read it here and now (needs ANTHROPIC_API_KEY)
     POST /admin/review/<id>   {status: approved|rejected, note, merge: add|replace}

   Live overlay (public):
     GET  /live/deals.json     approved deals not yet in the built bundles

   The Worker now publishes, in one narrow case: a photo for a venue with NO
   hours on the board, that the model read cleanly and the PA validators passed,
   is approved automatically and appears through the overlay within seconds.
   Anything that would CHANGE hours already published waits for a person. See
   autoApprove() for why the line is drawn there.
   ============================================================ */

import { proposalFrom, readPhoto } from "./extract.js";
import { ADMIN_HTML } from "./admin_page.js";
// The night-out layer: subscribers, events, venue magic links. Routes and
// admin verbs are listed at the top of nightout.js.
import {
  adminNightOut,
  liveEvents,
  subscribe,
  subscribeConfirm,
  subscribeLeave,
  venueEvents,
} from "./nightout.js";
// Accounts: sign-in links, saved places, private notes. Routes are listed at
// the top of accounts.js; every one of them lives under /account.
import { accountRoutes, adminSigninLink } from "./accounts.js";

const MAX_BYTES = 8 * 1024 * 1024;
const MAX_PER_DAY = 12;
const MAX_NOTE = 500;

/* Sniffed from the bytes, not trusted from the Content-Type header, which the
   client controls. An upload that isn't one of these is not an image. */
const MAGIC = [
  { type: "image/jpeg", bytes: [0xff, 0xd8, 0xff] },
  { type: "image/png", bytes: [0x89, 0x50, 0x4e, 0x47] },
  { type: "image/webp", bytes: [0x52, 0x49, 0x46, 0x46] }, // "RIFF", + WEBP at 8
];

function sniff(buf) {
  const b = new Uint8Array(buf);
  for (const m of MAGIC) {
    if (m.bytes.every((v, i) => b[i] === v)) {
      if (m.type === "image/webp") {
        const webp = [0x57, 0x45, 0x42, 0x50];
        if (!webp.every((v, i) => b[8 + i] === v)) continue;
      }
      return m.type;
    }
  }
  return null;
}

/* Drop EXIF and every other application segment from a JPEG.

   A menu photo carries GPS, a device serial, and a capture timestamp, and the
   ground rule for this project is that we never store any of it. The app also
   re-encodes through a canvas before upload, which strips metadata on its own
   -- this is the copy that runs when that didn't happen (a client with JS
   disabled, a direct POST, a browser whose canvas passed something through).

   Walks the marker chain: keep APP0 (JFIF, structural), drop APP1..APPF (EXIF,
   XMP, ICC, Photoshop) and COM, then copy everything from the start of scan
   data onward untouched. Returns the input unchanged if the chain doesn't
   parse -- a partial rewrite of a JPEG is worse than the original. */
function stripJpegMetadata(buf) {
  const b = new Uint8Array(buf);
  if (b[0] !== 0xff || b[1] !== 0xd8) return buf;
  const keep = [b.subarray(0, 2)];
  let i = 2;
  while (i + 3 < b.length) {
    if (b[i] !== 0xff) return buf; // not a marker where one must be
    const marker = b[i + 1];
    if (marker === 0xd8 || (marker >= 0xd0 && marker <= 0xd7) || marker === 0x01) {
      keep.push(b.subarray(i, i + 2));
      i += 2;
      continue;
    }
    if (marker === 0xda) {
      // Start of scan: the rest is entropy-coded data plus EOI, copied whole.
      keep.push(b.subarray(i));
      break;
    }
    const len = (b[i + 2] << 8) | b[i + 3];
    if (len < 2 || i + 2 + len > b.length) return buf;
    const drop = (marker >= 0xe1 && marker <= 0xef) || marker === 0xfe;
    if (!drop) keep.push(b.subarray(i, i + 2 + len));
    i += 2 + len;
  }
  let n = 0;
  for (const part of keep) n += part.length;
  const out = new Uint8Array(n);
  let at = 0;
  for (const part of keep) {
    out.set(part, at);
    at += part.length;
  }
  return out.buffer;
}

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

/* Compared byte-by-byte over the full length so a wrong token takes the same
   time to reject whichever character is wrong. */
function tokenMatches(given, expected) {
  if (typeof given !== "string" || typeof expected !== "string") return false;
  if (given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < given.length; i++) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

function cors(env, origin) {
  const allowed = [env.FRONTEND_ORIGIN, "http://localhost:8000", "http://127.0.0.1:8000"];
  return {
    "Access-Control-Allow-Origin": allowed.includes(origin) ? origin : allowed[0],
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    // Authorization carries the account session on every /account call. Left
    // out, the browser refuses the preflight and every saved place fails with
    // a CORS error that says nothing about what is wrong.
    "Access-Control-Allow-Headers": "Content-Type, X-Admin-Token, Authorization",
    "Access-Control-Max-Age": "86400",
  };
}

const json = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

async function verifyTurnstile(secret, token, ip) {
  const form = new FormData();
  form.append("secret", secret);
  form.append("response", token || "");
  if (ip) form.append("remoteip", ip);
  const res = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST",
    body: form,
  });
  const out = await res.json();
  return out.success === true;
}

/* ---- POST /submit ------------------------------------------------------ */

async function submit(request, env, ctx, headers) {
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const ipHash = await sha256Hex(`${env.IP_SALT || "unsalted"}:${ip}`);
  const now = new Date().toISOString();
  const day = now.slice(0, 10);

  const seen = await env.DB.prepare("SELECT n FROM rate WHERE ip_hash = ? AND day = ?")
    .bind(ipHash, day)
    .first();
  if (seen && seen.n >= MAX_PER_DAY) {
    return json({ error: "Daily limit reached. Try again tomorrow." }, 429, headers);
  }

  let form;
  try {
    form = await request.formData();
  } catch {
    return json({ error: "Expected a multipart form." }, 400, headers);
  }

  if (env.TURNSTILE_SECRET) {
    const ok = await verifyTurnstile(env.TURNSTILE_SECRET, form.get("cf_token"), ip);
    if (!ok) return json({ error: "Could not verify this came from a person." }, 403, headers);
  }

  const file = form.get("photo");
  if (!file || typeof file.arrayBuffer !== "function") {
    return json({ error: "No photo in the form." }, 400, headers);
  }

  let buf = await file.arrayBuffer();
  if (buf.byteLength > MAX_BYTES) {
    return json({ error: "That photo is too large. Keep it under 8 MB." }, 413, headers);
  }
  if (buf.byteLength < 1024) {
    return json({ error: "That file is too small to be a photo." }, 400, headers);
  }

  const contentType = sniff(buf);
  if (!contentType) {
    return json({ error: "That isn't a JPEG, PNG or WebP." }, 415, headers);
  }
  if (contentType === "image/jpeg") buf = stripJpegMetadata(buf);

  const lid = (form.get("lid") || "").toString().slice(0, 64).trim();
  const venueName = (form.get("venue_name") || "").toString().slice(0, 200).trim();
  const note = (form.get("note") || "").toString().slice(0, MAX_NOTE).trim();
  if (!lid) {
    return json({ error: "Pick which venue this menu is for." }, 400, headers);
  }

  const id = crypto.randomUUID();
  const ext = contentType === "image/png" ? "png" : contentType === "image/webp" ? "webp" : "jpg";
  const key = `submissions/${day}/${id}.${ext}`;

  await putPhoto(env, key, buf, contentType);
  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO submissions
         (id, lid, venue_name, r2_key, bytes, content_type, note, submitted_at, ip_hash, status)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')`
    ).bind(id, lid, venueName, key, buf.byteLength, contentType, note || null, now, ipHash),
    env.DB.prepare(
      `INSERT INTO rate (ip_hash, day, n) VALUES (?, ?, 1)
       ON CONFLICT(ip_hash, day) DO UPDATE SET n = n + 1`
    ).bind(ipHash, day),
    env.DB.prepare("DELETE FROM rate WHERE day < ?").bind(day),
  ]);

  // Read it now, after the response has gone out. With no API key this does
  // nothing and the row waits for the CLI pass on Paul's PC, which costs
  // nothing and is still the default.
  if (env.ANTHROPIC_API_KEY) {
    ctx.waitUntil(
      readAndMaybePublish(env, id).catch((err) => console.error("extract", String(err)))
    );
  }

  return json({ id, status: "pending" }, 201, headers);
}

/* ---- reading, and the auto-approve gate -------------------------------- */

/* What the site currently publishes, keyed by licence ID. Built by
   ingest/build_bundles.py and served with the rest of the static data. The
   Worker needs it to answer one question: does this venue already have hours?
   Cached at the edge -- it changes only when Paul rebuilds. */
async function publishedBoard(env) {
  const base = env.FRONTEND_ORIGIN || "https://paulrenzi.github.io";
  const res = await fetch(base + "/happy-hour-finder/data/board-by-lid.json", {
    cf: { cacheTtl: 300, cacheEverything: true },
  });
  if (!res.ok) throw new Error("board-by-lid " + res.status);
  return await res.json();
}

/* The line between what publishes itself and what waits for a person.

   Adding hours to a venue that has none is close to harmless, and it is where
   nearly all the value is: the site's actual problem is 2,729 venues with
   nothing published. A photo that CHANGES hours already on the board is the
   damaging case -- it can overwrite something correct -- and it is rare enough
   to look at by hand.

   The rest is about trusting the read, not the submitter. A dropped quote means
   the model reported a price the menu does not contain; one of those and the
   whole submission goes to a person, because grounding failing at all is the
   signal that this particular read cannot be trusted. */
async function autoApprove(env, sub, proposal) {
  if (!proposal.is_menu || !proposal.deals.length) return null;
  if (proposal.rejected && proposal.rejected.length) return null;
  if (proposal.legible === false) return null;

  let board;
  try {
    board = await publishedBoard(env);
  } catch (err) {
    // Not knowing what is published is not a licence to guess. A person decides.
    console.error("board", String(err));
    return null;
  }
  const already = board[String(sub.lid)];
  if (already && (already.deals || []).length) return null;

  return "auto-approved: " + proposal.deals.length + " deal(s) read cleanly for a " +
    "venue with nothing published. Grounding and the PA validators both passed.";
}

/* Read a pending submission, store the proposal, publish it if it clears the
   gate. Safe to call twice: the UPDATE only touches a row still pending. */
async function readAndMaybePublish(env, id) {
  const sub = await env.DB.prepare(
    "SELECT id, lid, venue_name, r2_key, content_type, submitted_at, status FROM submissions WHERE id = ?"
  )
    .bind(id)
    .first();
  if (!sub || sub.status !== "pending") return;

  const now = new Date().toISOString();
  let proposal;
  try {
    const body = await getPhoto(env, sub.r2_key);
    if (!body) throw new Error("photo missing from storage");
    const bytes = await new Response(body).arrayBuffer();
    const read = await readPhoto(env, bytes, sub.content_type);
    proposal = proposalFrom(read, sub, now.slice(0, 10));
  } catch (err) {
    await env.DB.prepare(
      "UPDATE submissions SET extract_error = ?, extracted_at = ? WHERE id = ? AND status = 'pending'"
    )
      .bind(String(err).slice(0, 2000), now, id)
      .run();
    return;
  }

  const res = await env.DB.prepare(
    "UPDATE submissions SET extracted = ?, extract_error = NULL, extracted_at = ?, status = 'extracted' WHERE id = ? AND status = 'pending'"
  )
    .bind(JSON.stringify(proposal), now, id)
    .run();
  if (!res.meta.changes) return;

  const note = await autoApprove(env, sub, proposal);
  if (note) {
    // Auto-approval publishes only onto a venue with nothing on the board, so
    // there is never anything to merge with: "replace" is the whole story.
    await markReviewed(env, id, "replace", "photo_auto");
    await env.DB.prepare(
      "UPDATE submissions SET status = 'approved', reviewed_at = ?, review_note = ? WHERE id = ? AND status = 'extracted'"
    )
      .bind(now, note, id)
      .run();
  }
}

/* Something looked at the photo, looked at what was read out of it, and said
   yes. That IS the confirmation, so the deal stops calling itself unconfirmed.

   The upgrade is written back into the stored extraction rather than applied at
   render time, because two things read these deals -- the live overlay and the
   nightly fold into the bundles -- and a rule applied in one of them is a rule
   the other disagrees with.

   Auto-approved deals used to be left out of this, on the reasoning that no
   person had seen them. That shipped Taku as "unconfirmed" next to a photo of
   its own menu, which reads to a customer as doubt about the hours -- when
   what actually happened is that every price was quoted verbatim off the
   menu, the PA validators passed, and the venue had nothing to overwrite.
   That is a stronger check than the one a tired reviewer does at midnight. The
   gate that let it through is the confirmation; `verified_by` records WHICH
   gate, so the two are still told apart everywhere it matters. */
async function markReviewed(env, id, merge, by = "photo_review") {
  const row = await env.DB.prepare("SELECT extracted FROM submissions WHERE id = ?")
    .bind(id)
    .first();
  if (!row?.extracted) return;
  let ex;
  try {
    ex = JSON.parse(row.extracted);
  } catch {
    return;
  }
  if (!Array.isArray(ex.deals) || !ex.deals.length) return;
  for (const deal of ex.deals) {
    deal.confidence = "verified";
    deal.verified_by = by;
    // Whether this photo is another page of the menu on the board or a menu
    // that changed. The clock cannot tell those apart once they are more than
    // a few hours apart, so the reviewer says, and the answer is stored with
    // the deal where both readers of it will find the same answer.
    deal.source = { ...(deal.source || {}), merge: merge === "add" ? "add" : "replace" };
  }
  await env.DB.prepare("UPDATE submissions SET extracted = ? WHERE id = ?")
    .bind(JSON.stringify(ex), id)
    .run();
}

/* ---- POST /confirm -----------------------------------------------------

   Somebody in the bar saying the hours are still right. It is the cheapest and
   best evidence this product can get, so the endpoint asks for nothing: no
   account, no photo, no Turnstile. The only things standing between it and
   abuse are that a confirmation is idempotent per person per deal, and that a
   day's worth of them from one address is capped.

   A confirmation for hours that do not exist is meaningless rather than
   dangerous -- deal_key is a fingerprint of the windows, so a made-up key
   matches no deal on the board and is never read back by anything. */
const MAX_CONFIRMS_PER_DAY = 40;

async function confirm(request, env, headers) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Expected JSON." }, 400, headers);
  }
  const lid = String(body.lid || "").slice(0, 64).trim();
  const key = String(body.key || "").slice(0, 300).trim();
  if (!lid || !key) return json({ error: "Need a venue and a deal." }, 400, headers);

  const ip = request.headers.get("CF-Connecting-IP") || "";
  const ipHash = await sha256Hex(`${env.IP_SALT || "unsalted"}:${ip}`);
  const now = new Date().toISOString();
  const day = now.slice(0, 10);

  const seen = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM confirmations WHERE ip_hash = ? AND confirmed_at >= ?"
  )
    .bind(ipHash, day)
    .first();
  if (seen && seen.n >= MAX_CONFIRMS_PER_DAY) {
    return json({ error: "That's plenty for one day. Thank you." }, 429, headers);
  }

  // Re-confirming refreshes the date rather than adding a second vote: the
  // count has to mean "how many people", or it is just a click counter.
  await env.DB.prepare(
    `INSERT INTO confirmations (lid, deal_key, ip_hash, confirmed_at) VALUES (?, ?, ?, ?)
     ON CONFLICT(lid, deal_key, ip_hash) DO UPDATE SET confirmed_at = excluded.confirmed_at`
  )
    .bind(lid, key, ipHash, now)
    .run();

  const tally = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM confirmations WHERE lid = ? AND deal_key = ?"
  )
    .bind(lid, key)
    .first();
  return json({ ok: true, n: (tally && tally.n) || 1 }, 200, headers);
}

/* Everything confirmed in the last CONFIRM_WINDOW_DAYS, as {"<lid>:<key>":
   {n, last}}. Old confirmations are not deleted -- they are just not counted.
   "Six people said so in March" is not evidence about tonight, and letting it
   read as though it were is exactly the failure this signal exists to fix. */
const CONFIRM_WINDOW_DAYS = 45;

async function recentConfirms(env) {
  const cutoff = new Date(Date.now() - CONFIRM_WINDOW_DAYS * 86400000)
    .toISOString()
    .slice(0, 10);
  const { results } = await env.DB.prepare(
    `SELECT lid, deal_key, COUNT(*) AS n, MAX(confirmed_at) AS last
       FROM confirmations WHERE confirmed_at >= ?
       GROUP BY lid, deal_key LIMIT 5000`
  )
    .bind(cutoff)
    .all();
  const out = {};
  for (const r of results) {
    out[`${r.lid}:${r.deal_key}`] = { n: r.n, last: String(r.last).slice(0, 10) };
  }
  return out;
}

/* ---- GET /live/deals.json ----------------------------------------------

   Everything approved, as deals ready to render. The app loads its static
   bundles first and patches these over the top, so an approval is visible in
   seconds instead of waiting for a rebuild and a Pages deploy.

   Every deal carries its photo_id, which is how the app tells that an overlay
   entry is already baked into the bundle it just loaded and skips it. That is
   why this endpoint needs to know nothing about when Paul last built. */
async function liveDeals(env, headers) {
  const { results } = await env.DB.prepare(
    "SELECT id, lid, venue_name, extracted, submitted_at FROM submissions WHERE status = 'approved' AND extracted IS NOT NULL ORDER BY submitted_at DESC LIMIT 300"
  ).all();

  // Which zone each licence ID lives in. A photo that auto-published was for a
  // venue with no hours, so it is in no deals bundle -- the app needs to be told
  // which zone base to fetch before it can show it at all.
  let zones = {};
  try {
    const base = env.FRONTEND_ORIGIN || "https://paulrenzi.github.io";
    const res = await fetch(base + "/happy-hour-finder/data/lid-zone.json", {
      cf: { cacheTtl: 3600, cacheEverything: true },
    });
    if (res.ok) zones = await res.json();
  } catch (err) {
    // Without it the overlay still applies to every venue already on the board.
    console.error("lid-zone", String(err));
  }

  const byLid = new Map();
  for (const row of results) {
    let ex;
    try {
      ex = JSON.parse(row.extracted);
    } catch {
      continue;
    }
    if (!ex.is_menu || !(ex.deals || []).length) continue;
    const lid = String(row.lid);
    if (!byLid.has(lid)) {
      byLid.set(lid, { lid, name: row.venue_name || "", zone_id: zones[lid] || "", deals: [] });
    }
    byLid.get(lid).deals.push(...ex.deals);
  }

  // Carried on the same response the board already fetches every minute: a
  // confirmation should land as fast as an approval, and a second endpoint
  // would be a second thing to be down.
  let confirms = {};
  try {
    confirms = await recentConfirms(env);
  } catch (err) {
    console.error("confirms", String(err));
  }

  return json({ venues: [...byLid.values()], confirms }, 200, {
    ...headers,
    // Short and shared: an approval should land quickly, but this must not be
    // fetched fresh by every reader on every page load.
    "Cache-Control": "public, max-age=30",
  });
}

/* ---- photo storage ------------------------------------------------------

   R2 is the intended home and the code below prefers it. It is not enabled on
   this account, so the live binding is PHOTOS_KV -- a KV namespace, private
   exactly like the bucket was: nothing here is ever served to the public, only
   read back by the admin endpoint under the bearer. A submission is a bounded
   camera image (MAX_BYTES 8 MB, and the app re-encodes to ~300 KB before it
   leaves the phone), well inside KV's 25 MB value ceiling.

   Enabling R2 later is a one-line binding change in wrangler.toml -- no code
   moves, because both paths already exist here. Old KV objects would need
   copying across; until then, whichever binding is present is the store. */
async function putPhoto(env, key, buf, contentType) {
  if (env.PHOTOS) {
    await env.PHOTOS.put(key, buf, { httpMetadata: { contentType } });
    return;
  }
  await env.PHOTOS_KV.put(key, buf, { metadata: { contentType } });
}

async function getPhoto(env, key) {
  if (env.PHOTOS) {
    const obj = await env.PHOTOS.get(key);
    return obj ? obj.body : null;
  }
  return await env.PHOTOS_KV.get(key, { type: "stream" });
}

/* ---- admin ------------------------------------------------------------- */

async function admin(request, env, url, headers) {
  if (!tokenMatches(request.headers.get("X-Admin-Token"), env.ADMIN_TOKEN)) {
    return json({ error: "unauthorized" }, 401, headers);
  }
  const parts = url.pathname.split("/").filter(Boolean); // ["admin", verb, id?]
  const verb = parts[1];
  const id = parts[2];

  if (["events", "venue-token", "subscribers"].includes(verb)) {
    const handled = await adminNightOut(request, env, url, headers, parts);
    if (handled) return handled;
  }

  if (verb === "account") {
    const handled = await adminSigninLink(request, env, url, headers, parts);
    if (handled) return handled;
  }

  if (verb === "queue" && request.method === "GET") {
    const status = url.searchParams.get("status") || "pending";
    const { results } = await env.DB.prepare(
      `SELECT id, lid, venue_name, bytes, content_type, note, submitted_at,
              status, extracted, extract_error, extracted_at, reviewed_at, review_note
         FROM submissions WHERE status = ? ORDER BY submitted_at LIMIT 200`
    )
      .bind(status)
      .all();
    return json({ submissions: results }, 200, headers);
  }

  if (verb === "photo" && request.method === "GET" && id) {
    const row = await env.DB.prepare("SELECT r2_key, content_type FROM submissions WHERE id = ?")
      .bind(id)
      .first();
    if (!row) return json({ error: "no such submission" }, 404, headers);
    const body = await getPhoto(env, row.r2_key);
    if (!body) return json({ error: "photo missing from storage" }, 404, headers);
    return new Response(body, {
      headers: { ...headers, "Content-Type": row.content_type, "Cache-Control": "private, no-store" },
    });
  }

  if (verb === "board" && request.method === "GET") {
    try {
      return json(await publishedBoard(env), 200, headers);
    } catch (err) {
      return json({ error: String(err) }, 502, headers);
    }
  }

  if (verb === "read" && request.method === "POST" && id) {
    if (!env.ANTHROPIC_API_KEY) {
      return json(
        { error: "No ANTHROPIC_API_KEY on this Worker -- reading runs on Paul's PC." },
        501,
        headers
      );
    }
    await readAndMaybePublish(env, id);
    const row = await env.DB.prepare("SELECT status, extract_error FROM submissions WHERE id = ?")
      .bind(id)
      .first();
    return json({ id, ...row }, 200, headers);
  }

  if (verb === "extract" && request.method === "POST" && id) {
    const body = await request.json();
    const now = new Date().toISOString();
    if (body.error) {
      await env.DB.prepare(
        "UPDATE submissions SET extract_error = ?, extracted_at = ? WHERE id = ? AND status = 'pending'"
      )
        .bind(String(body.error).slice(0, 2000), now, id)
        .run();
      return json({ id, status: "pending" }, 200, headers);
    }
    // Only a pending row moves to extracted. A row a human already ruled on is
    // not something a later extraction pass gets to reopen.
    const res = await env.DB.prepare(
      `UPDATE submissions SET extracted = ?, extract_error = NULL, extracted_at = ?,
                              status = 'extracted'
        WHERE id = ? AND status = 'pending'`
    )
      .bind(JSON.stringify(body.extracted), now, id)
      .run();
    if (!res.meta.changes) return json({ error: "not pending" }, 409, headers);

    // The same gate, whoever did the reading. The CLI pass on Paul's PC posts
    // its proposal here, so keeping the decision on THIS side is what stops
    // there being a second implementation of it in Python that can drift.
    const sub = await env.DB.prepare("SELECT id, lid FROM submissions WHERE id = ?")
      .bind(id)
      .first();
    const note = await autoApprove(env, sub, body.extracted);
    if (note) {
      await markReviewed(env, id, "replace", "photo_auto");
      await env.DB.prepare(
        "UPDATE submissions SET status = 'approved', reviewed_at = ?, review_note = ? WHERE id = ? AND status = 'extracted'"
      )
        .bind(now, note, id)
        .run();
      return json({ id, status: "approved", auto: note }, 200, headers);
    }
    return json({ id, status: "extracted" }, 200, headers);
  }

  if (verb === "review" && request.method === "POST" && id) {
    const body = await request.json();
    if (body.status !== "approved" && body.status !== "rejected") {
      return json({ error: "status must be approved or rejected" }, 400, headers);
    }
    const res = await env.DB.prepare(
      `UPDATE submissions SET status = ?, reviewed_at = ?, review_note = ?
        WHERE id = ? AND status IN ('pending', 'extracted')`
    )
      .bind(body.status, new Date().toISOString(), (body.note || "").slice(0, 1000) || null, id)
      .run();
    if (!res.meta.changes) return json({ error: "already reviewed" }, 409, headers);
    if (body.status === "approved") await markReviewed(env, id, body.merge);
    return json({ id, status: body.status }, 200, headers);
  }

  return json({ error: "not found" }, 404, headers);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const headers = cors(env, request.headers.get("Origin"));

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
    if (url.pathname === "/health") return json({ ok: true, service: "hhf-submit" }, 200, headers);

    // The page itself holds no submissions -- it asks for the token and sends
    // it as a header -- so it is served without one. noindex, and never linked.
    if (url.pathname === "/admin" && request.method === "GET") {
      return new Response(ADMIN_HTML, {
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "X-Robots-Tag": "noindex, nofollow",
          "Cache-Control": "no-store",
        },
      });
    }

    try {
      if (url.pathname === "/live/deals.json" && request.method === "GET") {
        return await liveDeals(env, headers);
      }
      if (url.pathname === "/confirm" && request.method === "POST") {
        return await confirm(request, env, headers);
      }
      if (url.pathname === "/live/events.json" && request.method === "GET") {
        return await liveEvents(env, url, headers);
      }
      if (url.pathname === "/subscribe" && request.method === "POST") {
        return await subscribe(request, env, headers);
      }
      if (url.pathname === "/subscribe/confirm" && request.method === "GET") {
        return await subscribeConfirm(env, url);
      }
      if (url.pathname === "/subscribe/leave" && request.method === "GET") {
        return await subscribeLeave(env, url);
      }
      if (url.pathname === "/venue/events" && request.method === "POST") {
        return await venueEvents(request, env, headers);
      }
      // One entry for the whole account surface. It answers null for a path
      // that is not its own, so nothing below is shadowed.
      const account = await accountRoutes(request, env, url, headers);
      if (account) return account;

      if (url.pathname === "/submit" && request.method === "POST") {
        return await submit(request, env, ctx, headers);
      }
      if (url.pathname.startsWith("/admin/")) {
        return await admin(request, env, url, headers);
      }
    } catch (err) {
      // The submitter gets a generic failure; the detail goes to the tail log.
      console.error(err && err.stack ? err.stack : String(err));
      return json({ error: "Something went wrong on our end." }, 500, headers);
    }

    return json({ error: "not found" }, 404, headers);
  },
};
