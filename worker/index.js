/* ============================================================
   HAPPY HOUR FINDER — photo lane write path (Cloudflare Worker)

   Public:
     POST /submit           multipart: photo, lid, venue_name, note, cf_token
     GET  /health

   Admin (X-Admin-Token; driven by ingest/extract_photo_deals.py and
   ingest/review_photos.py, never by the browser):
     GET  /admin/queue?status=pending
     GET  /admin/photo/<id>
     POST /admin/extract/<id>   {extracted} | {error}
     POST /admin/review/<id>    {status: approved|rejected, note}

   The Worker stores and queues. It never publishes: a submission reaches the
   site only via the review script and a bundle rebuild.
   ============================================================ */

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
    "Access-Control-Allow-Headers": "Content-Type, X-Admin-Token",
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

async function submit(request, env, headers) {
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

  return json({ id, status: "pending" }, 201, headers);
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
    return json({ id, status: body.status }, 200, headers);
  }

  return json({ error: "not found" }, 404, headers);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const headers = cors(env, request.headers.get("Origin"));

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
    if (url.pathname === "/health") return json({ ok: true, service: "hhf-submit" }, 200, headers);

    try {
      if (url.pathname === "/submit" && request.method === "POST") {
        return await submit(request, env, headers);
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
