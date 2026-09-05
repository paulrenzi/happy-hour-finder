/* Accounts: a saved list of places, and a private note on any of them.

   Routes (all JSON, all CORS'd by index.js):

     POST /account/signin    {email}          -> 202 always. Mails a one-time link.
     GET  /account/callback?t=                -> redirects to the board with a
                                                 session token in the FRAGMENT
     GET  /account/me        Bearer session   -> {email, favorites, notes}
     POST /account/favorite  {lid, on}        -> {lid, on}
     POST /account/note      {kind, id, body} -> {kind, id, saved}
     POST /account/signout                    -> {ok:true}

   Three decisions worth knowing before changing anything here:

   1. ONE IDENTITY. An account is a row in `subscribers` -- the same table the
      email list uses -- because an address is one person either way, and two
      lists of the same addresses is two lists to reconcile. What it is NOT is
      one CONSENT: `status` still means "is this address on the digest", and
      signing in never touches it. An account-only row is `status = 'none'`,
      which no mailing query selects. Signing in must never subscribe anybody.

   2. NOTHING REVERSIBLE IS STORED. A session token and a sign-in token are
      held as SHA-256 hashes, so the table cannot be read to impersonate
      anyone. The token in the mail and the token in the browser are the only
      copies, exactly like a password.

   3. THE ENDPOINT NEVER SAYS WHETHER AN ADDRESS IS KNOWN. /account/signin
      answers 202 to every well-formed address, whether it minted a link for a
      new row or an old one. An account-lookup oracle is how a mailing list
      leaks, and this database's only personal field is the address.

   Notes are stored in plain text and are private to the account. They are the
   most personal thing this database holds; see the note on /account/note. */

import { json, nowIso, randomToken, sha256Hex } from "./nightout.js";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const MAX_SIGNIN_PER_DAY = 6;
// A link that is still good tomorrow is a link sitting in a mailbox somebody
// else can reach. Long enough to walk to a laptop, not long enough to forget.
const SIGNIN_TTL_MINUTES = 30;
const MAX_NOTE = 2000;
const MAX_FAVORITES = 500;

const hash = (t) => sha256Hex(`session:${t}`);

/* The account behind a request, or null. Bearer only -- a cookie would be sent
   on every static asset the board loads and buys nothing here. */
export async function accountFor(request, env) {
  const auth = request.headers.get("Authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  if (token.length < 20 || token.length > 200) return null;
  const row = await env.DB.prepare(
    "SELECT email FROM sessions WHERE token_hash = ?"
  ).bind(await hash(token)).first();
  if (!row) return null;
  // Cheap enough at this volume, and it is what lets a stale session be swept.
  await env.DB.prepare("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?")
    .bind(nowIso(), await hash(token)).run();
  return row.email;
}

export async function signin(request, env, headers) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Expected JSON." }, 400, headers);
  }
  const email = String(body.email || "").trim().toLowerCase().slice(0, 254);
  if (!EMAIL_RE.test(email)) {
    return json({ error: "That does not look like an email address." }, 400, headers);
  }

  const ip = request.headers.get("CF-Connecting-IP") || "";
  const ipHash = await sha256Hex(`${env.IP_SALT || "unsalted"}:acct:${ip}`);
  const day = nowIso().slice(0, 10);
  const seen = await env.DB.prepare("SELECT n FROM rate WHERE ip_hash = ? AND day = ?")
    .bind(ipHash, day).first();
  if (seen && seen.n >= MAX_SIGNIN_PER_DAY) {
    return json({ error: "Too many sign-in links today. Try again tomorrow." }, 429, headers);
  }
  await env.DB.prepare(
    "INSERT INTO rate (ip_hash, day, n) VALUES (?, ?, 1) ON CONFLICT(ip_hash, day) DO UPDATE SET n = n + 1"
  ).bind(ipHash, day).run();

  /* The row may already exist as a digest subscriber. Either way the account
     is the same address, and `status` is left exactly as it was: an account is
     not a subscription. */
  await env.DB.prepare(
    `INSERT INTO subscribers (email, status, token, created_at, ip_hash, account_at)
     VALUES (?, 'none', ?, ?, ?, ?)
     ON CONFLICT(email) DO UPDATE SET account_at = COALESCE(subscribers.account_at, excluded.account_at)`
  ).bind(email, randomToken(), nowIso(), ipHash, nowIso()).run();

  const token = randomToken();
  const expires = new Date(Date.now() + SIGNIN_TTL_MINUTES * 60000).toISOString();
  await env.DB.prepare(
    "INSERT INTO signin_tokens (token_hash, email, created_at, expires_at) VALUES (?, ?, ?, ?)"
  ).bind(await hash(token), email, nowIso(), expires).run();

  if (env.RESEND_API_KEY) await sendSigninLink(env, email, token, request.url);
  // 202 whether the address was known or not. See decision 3 at the top.
  return json({ status: "sent" }, 202, headers);
}

export function signinLink(origin, token) {
  return `${origin}/account/callback?t=${token}`;
}

async function sendSigninLink(env, email, token, requestUrl) {
  const origin = new URL(requestUrl).origin;
  const from = env.MAIL_FROM || "Happy Hour Finder <hello@happyhourfinder.example>";
  const text =
    `Here is your sign-in link for Happy Hour Finder.\n\n` +
    `${signinLink(origin, token)}\n\n` +
    `It works once and expires in ${SIGNIN_TTL_MINUTES} minutes.\n` +
    `If you didn't ask for it, ignore this -- nothing happens and you are not ` +
    `on any mailing list because of it.\n`;
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from, to: [email], subject: "Your sign-in link", text }),
  });
  if (!res.ok) console.error("resend signin", res.status, await res.text());
}

/* The board is a static page, so the session has to arrive in the URL. It goes
   in the FRAGMENT: a fragment is never sent to a server, so the token stays out
   of GitHub Pages' logs, out of any proxy's, and out of the Referer header the
   next outbound link would carry. The page consumes it and rewrites the hash. */
export async function signinCallback(env, url) {
  const t = (url.searchParams.get("t") || "").slice(0, 200);
  const site = (env.FRONTEND_ORIGIN || "https://paulrenzi.github.io") + "/happy-hour-finder/";
  const back = (frag) => new Response(null, {
    status: 303,
    headers: { Location: site + frag, "Cache-Control": "no-store" },
  });
  if (!t) return back("#signin=invalid");

  const th = await hash(t);
  const row = await env.DB.prepare(
    "SELECT email, expires_at, used_at FROM signin_tokens WHERE token_hash = ?"
  ).bind(th).first();
  // One use, and a used link is dead rather than merely old: a forwarded mail
  // must not still be a key.
  if (!row || row.used_at || row.expires_at < nowIso()) return back("#signin=expired");
  await env.DB.prepare("UPDATE signin_tokens SET used_at = ? WHERE token_hash = ?")
    .bind(nowIso(), th).run();

  const session = randomToken() + randomToken();
  await env.DB.prepare(
    "INSERT INTO sessions (token_hash, email, created_at, last_seen_at) VALUES (?, ?, ?, ?)"
  ).bind(await hash(session), row.email, nowIso(), nowIso()).run();
  return back(`#signin=${session}`);
}

export async function me(email, env, headers) {
  const favs = await env.DB.prepare(
    "SELECT lid FROM favorites WHERE email = ? ORDER BY created_at"
  ).bind(email).all();
  const notes = await env.DB.prepare(
    "SELECT kind, subject_id, body, updated_at FROM notes WHERE email = ?"
  ).bind(email).all();
  return json({
    email,
    favorites: (favs.results || []).map((r) => String(r.lid)),
    notes: (notes.results || []).map((r) => ({
      kind: r.kind, id: String(r.subject_id), body: r.body, updated_at: r.updated_at,
    })),
  }, 200, headers);
}

export async function favorite(request, email, env, headers) {
  const body = await request.json().catch(() => null);
  if (!body) return json({ error: "Expected JSON." }, 400, headers);
  const lid = String(body.lid || "").trim().slice(0, 64);
  if (!lid) return json({ error: "lid is required" }, 400, headers);
  const on = body.on !== false;
  if (on) {
    const { n } = await env.DB.prepare("SELECT COUNT(*) AS n FROM favorites WHERE email = ?")
      .bind(email).first();
    if (n >= MAX_FAVORITES) return json({ error: "That is a lot of places." }, 409, headers);
    await env.DB.prepare(
      "INSERT INTO favorites (email, lid, created_at) VALUES (?, ?, ?) ON CONFLICT(email, lid) DO NOTHING"
    ).bind(email, lid, nowIso()).run();
  } else {
    await env.DB.prepare("DELETE FROM favorites WHERE email = ? AND lid = ?").bind(email, lid).run();
  }
  return json({ lid, on }, 200, headers);
}

/* A note on a place or on one night at it.

   `kind` is 'venue' (subject_id is the licence id) or 'event' (subject_id is
   the event id). Two kinds rather than two tables because the row is identical
   and the reader wants them together.

   An EMPTY body deletes the note. A person clearing a note means to be rid of
   it, and leaving an empty row behind would keep it on the "places you have
   notes on" list forever. */
export async function note(request, email, env, headers) {
  const body = await request.json().catch(() => null);
  if (!body) return json({ error: "Expected JSON." }, 400, headers);
  const kind = String(body.kind || "venue");
  if (!["venue", "event"].includes(kind)) return json({ error: "kind" }, 400, headers);
  const id = String(body.id || "").trim().slice(0, 64);
  if (!id) return json({ error: "id is required" }, 400, headers);
  const text = String(body.body || "").trim().slice(0, MAX_NOTE);
  if (!text) {
    await env.DB.prepare("DELETE FROM notes WHERE email = ? AND kind = ? AND subject_id = ?")
      .bind(email, kind, id).run();
    return json({ kind, id, saved: false }, 200, headers);
  }
  await env.DB.prepare(
    `INSERT INTO notes (email, kind, subject_id, body, updated_at) VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(email, kind, subject_id) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at`
  ).bind(email, kind, id, text, nowIso()).run();
  return json({ kind, id, saved: true }, 200, headers);
}

export async function signout(request, env, headers) {
  const auth = request.headers.get("Authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  if (token) {
    await env.DB.prepare("DELETE FROM sessions WHERE token_hash = ?").bind(await hash(token)).run();
  }
  return json({ ok: true }, 200, headers);
}

/* ADMIN: mint a sign-in link for an address and RETURN it, instead of mailing
   it. Two reasons it exists:

   - the Worker can only send mail when RESEND_API_KEY is set, and until it is,
     this is the only way anybody can sign in at all;
   - it is how the lane is tested against the real deployment without a mailbox.

   It is behind the admin token, like every other /admin verb, and it mints
   exactly what the mail would: one link, single use, thirty minutes. */
export async function adminSigninLink(request, env, url, headers, parts) {
  if (parts[1] !== "account" || parts[2] !== "signin-link" || request.method !== "POST") return null;
  const body = await request.json().catch(() => ({}));
  const email = String(body.email || "").trim().toLowerCase().slice(0, 254);
  if (!EMAIL_RE.test(email)) return json({ error: "email" }, 400, headers);

  await env.DB.prepare(
    `INSERT INTO subscribers (email, status, token, created_at, ip_hash, account_at)
     VALUES (?, 'none', ?, ?, 'admin', ?)
     ON CONFLICT(email) DO UPDATE SET account_at = COALESCE(subscribers.account_at, excluded.account_at)`
  ).bind(email, randomToken(), nowIso(), nowIso()).run();

  const token = randomToken();
  await env.DB.prepare(
    "INSERT INTO signin_tokens (token_hash, email, created_at, expires_at) VALUES (?, ?, ?, ?)"
  ).bind(await hash(token), email, nowIso(),
         new Date(Date.now() + SIGNIN_TTL_MINUTES * 60000).toISOString()).run();
  return json({ email, link: signinLink(new URL(request.url).origin, token) }, 201, headers);
}

/* The one router entry index.js calls. Returns null when the path is not ours,
   so the caller can carry on down its own list. */
export async function accountRoutes(request, env, url, headers) {
  if (!url.pathname.startsWith("/account")) return null;

  if (url.pathname === "/account/signin" && request.method === "POST") {
    return await signin(request, env, headers);
  }
  if (url.pathname === "/account/callback" && request.method === "GET") {
    return await signinCallback(env, url);
  }
  if (url.pathname === "/account/signout" && request.method === "POST") {
    return await signout(request, env, headers);
  }

  const email = await accountFor(request, env);
  if (!email) return json({ error: "Sign in first." }, 401, headers);

  if (url.pathname === "/account/me" && request.method === "GET") {
    return await me(email, env, headers);
  }
  if (url.pathname === "/account/favorite" && request.method === "POST") {
    return await favorite(request, email, env, headers);
  }
  if (url.pathname === "/account/note" && request.method === "POST") {
    return await note(request, email, env, headers);
  }
  return json({ error: "No such account route." }, 404, headers);
}
