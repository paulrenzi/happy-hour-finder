/* worker/accounts.js against the REAL schema.

   D1 is SQLite with a promise wrapper, and Node ships SQLite, so this runs
   worker/schema.sql itself and drives the Worker's own route handler over it.
   A test with a hand-written fake database can only prove the code calls the
   fake the way the fake expects; this proves the SQL is SQL, that the columns
   the handlers name exist, and that the rules below hold on real rows.

   Run with:  node --test tests/accounts.test.mjs
*/

import test from "node:test";
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { accountRoutes } from "../worker/accounts.js";

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..");

/* The thinnest possible D1 over node:sqlite: prepare/bind/first/run/all, which
   is the whole of the surface worker/accounts.js uses. */
function fakeD1() {
  const db = new DatabaseSync(":memory:");
  const sql = readFileSync(join(REPO, "worker", "schema.sql"), "utf8");
  /* Comments come out BEFORE the split, not after: a statement can be preceded
     by a paragraph of them, and one of those paragraphs contains a semicolon
     ("extracted; waiting on a human"), which split the file mid-sentence and
     handed SQLite three English words to parse. */
  const bare = sql.split("\n").map((l) => l.replace(/--.*$/, "")).join("\n");
  for (const stmt of bare.split(";")) {
    const s = stmt.trim();
    if (!s) continue;
    try {
      db.exec(s);
    } catch (err) {
      // The ALTER at the end of schema.sql is expected to fail on a re-run;
      // on a fresh database it must not, so anything else is a real error.
      throw new Error(`schema.sql failed on:\n${s}\n${err.message}`);
    }
  }
  return {
    db,
    prepare(query) {
      let args = [];
      const api = {
        bind(...a) { args = a.map((x) => (x === undefined ? null : x)); return api; },
        async first() { return db.prepare(query).get(...args) ?? null; },
        async all() { return { results: db.prepare(query).all(...args) }; },
        async run() {
          const r = db.prepare(query).run(...args);
          return { meta: { changes: Number(r.changes) } };
        },
      };
      return api;
    },
  };
}

const env = () => ({ DB: fakeD1(), FRONTEND_ORIGIN: "https://example.test", IP_SALT: "salt" });

const call = (env, method, path, { body = null, token = null } = {}) =>
  accountRoutes(
    new Request("https://api.test" + path, {
      method,
      body: body && method !== "GET" ? JSON.stringify(body) : undefined,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }),
    env,
    new URL("https://api.test" + path),
    {}
  );

test("the schema this worker is written against actually applies", () => {
  const e = env();
  const names = e.DB.db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all()
    .map((r) => r.name);
  for (const t of ["subscribers", "sessions", "signin_tokens", "favorites", "notes"]) {
    assert.ok(names.includes(t), `${t} missing from schema.sql`);
  }
  const cols = e.DB.db.prepare("PRAGMA table_info(subscribers)").all().map((c) => c.name);
  assert.ok(cols.includes("account_at"), "the accounts ALTER never ran");
});

test("🛑 signing in NEVER puts an address on the mailing list", async () => {
  const e = env();
  await call(e, "POST", "/account/signin", { body: { email: "new@example.test" } });
  const row = e.DB.db.prepare("SELECT status, account_at FROM subscribers WHERE email = ?")
    .get("new@example.test");
  assert.equal(row.status, "none");
  assert.ok(row.account_at, "the row was not marked as an account");

  // And an address ALREADY confirmed on the list stays confirmed -- signing in
  // must not demote a subscriber either.
  e.DB.db.prepare(
    "INSERT INTO subscribers (email, status, token, created_at, ip_hash) VALUES ('old@example.test','confirmed','t','now','h')"
  ).run();
  await call(e, "POST", "/account/signin", { body: { email: "old@example.test" } });
  const old = e.DB.db.prepare("SELECT status FROM subscribers WHERE email = 'old@example.test'").get();
  assert.equal(old.status, "confirmed");
});

test("the endpoint answers the same whether or not it knows the address", async () => {
  const e = env();
  e.DB.db.prepare(
    "INSERT INTO subscribers (email, status, token, created_at, ip_hash) VALUES ('known@example.test','confirmed','t','now','h')"
  ).run();
  const a = await call(e, "POST", "/account/signin", { body: { email: "known@example.test" } });
  const b = await call(e, "POST", "/account/signin", { body: { email: "stranger@example.test" } });
  assert.equal(a.status, 202);
  assert.equal(b.status, 202);
  assert.deepEqual(await a.json(), await b.json());
});

test("a bad address is refused before anything is written", async () => {
  const e = env();
  const res = await call(e, "POST", "/account/signin", { body: { email: "not-an-email" } });
  assert.equal(res.status, 400);
  assert.equal(e.DB.db.prepare("SELECT COUNT(*) n FROM signin_tokens").get().n, 0);
});

test("no session, no data: every account route refuses", async () => {
  const e = env();
  for (const [method, path] of [["GET", "/account/me"], ["POST", "/account/favorite"], ["POST", "/account/note"]]) {
    const res = await call(e, method, path, { body: { lid: "1" }, token: "nonsense-token-that-is-long" });
    assert.equal(res.status, 401, `${path} answered ${res.status}`);
  }
});

/* Everything below needs a live session. The callback is the only thing that
   mints one, so it is driven here exactly as the mail's link would: the raw
   token is generated inside signin(), so the test reads the row and forges a
   matching one rather than pretending to read a mailbox. */
async function sessionFor(e, email = "paul@example.com") {
  const { randomToken, sha256Hex } = await import("../worker/nightout.js");
  const raw = randomToken();
  await e.DB.prepare(
    "INSERT INTO signin_tokens (token_hash, email, created_at, expires_at) VALUES (?, ?, ?, ?)"
  ).bind(await sha256Hex(`session:${raw}`), email, new Date().toISOString(),
         new Date(Date.now() + 600000).toISOString()).run();
  const res = await call(e, "GET", `/account/callback?t=${raw}`);
  assert.equal(res.status, 303);
  const loc = res.headers.get("Location");
  return { session: loc.split("#signin=")[1], raw, loc };
}

test("a sign-in link works once, and a used one is dead", async () => {
  const e = env();
  const { raw } = await sessionFor(e);
  const again = await call(e, "GET", `/account/callback?t=${raw}`);
  assert.match(again.headers.get("Location"), /#signin=expired/);
  assert.equal(e.DB.db.prepare("SELECT COUNT(*) n FROM sessions").get().n, 1);
});

test("an expired link mints nothing", async () => {
  const e = env();
  const { randomToken, sha256Hex } = await import("../worker/nightout.js");
  const raw = randomToken();
  await e.DB.prepare(
    "INSERT INTO signin_tokens (token_hash, email, created_at, expires_at) VALUES (?, ?, ?, ?)"
  ).bind(await sha256Hex(`session:${raw}`), "p@example.test", "2020-01-01T00:00:00.000Z",
         "2020-01-01T00:30:00.000Z").run();
  const res = await call(e, "GET", `/account/callback?t=${raw}`);
  assert.match(res.headers.get("Location"), /#signin=expired/);
  assert.equal(e.DB.db.prepare("SELECT COUNT(*) n FROM sessions").get().n, 0);
});

test("🔑 nothing reversible is stored: neither token is in the database", async () => {
  const e = env();
  const { session, raw } = await sessionFor(e);
  const rows = JSON.stringify([
    ...e.DB.db.prepare("SELECT * FROM sessions").all(),
    ...e.DB.db.prepare("SELECT * FROM signin_tokens").all(),
  ]);
  assert.ok(!rows.includes(session), "the session token is stored in the clear");
  assert.ok(!rows.includes(raw), "the sign-in token is stored in the clear");
});

test("saving, unsaving, and reading back what this account holds", async () => {
  const e = env();
  const { session } = await sessionFor(e);

  await call(e, "POST", "/account/favorite", { token: session, body: { lid: "17574", on: true } });
  await call(e, "POST", "/account/favorite", { token: session, body: { lid: "66143", on: true } });
  await call(e, "POST", "/account/favorite", { token: session, body: { lid: "66143", on: false } });
  // Saving the same bar twice is saving it once.
  await call(e, "POST", "/account/favorite", { token: session, body: { lid: "17574", on: true } });

  const me = await (await call(e, "GET", "/account/me", { token: session })).json();
  assert.deepEqual(me.favorites, ["17574"]);
  assert.equal(me.email, "paul@example.com");
});

test("a note is per account and per subject, and clearing it removes it", async () => {
  const e = env();
  const { session } = await sessionFor(e);
  await call(e, "POST", "/account/note", { token: session, body: { kind: "venue", id: "17574", body: "Back room" } });
  await call(e, "POST", "/account/note", { token: session, body: { kind: "event", id: "ev1", body: "Get there early" } });
  let me = await (await call(e, "GET", "/account/me", { token: session })).json();
  assert.deepEqual(
    me.notes.map((n) => [n.kind, n.id, n.body]).sort(),
    [["event", "ev1", "Get there early"], ["venue", "17574", "Back room"]]
  );

  // Rewriting replaces rather than duplicating.
  await call(e, "POST", "/account/note", { token: session, body: { kind: "venue", id: "17574", body: "Ask for the back room" } });
  me = await (await call(e, "GET", "/account/me", { token: session })).json();
  assert.equal(me.notes.filter((n) => n.kind === "venue").length, 1);

  // An empty note is a note the person deleted, not an empty row to keep.
  await call(e, "POST", "/account/note", { token: session, body: { kind: "venue", id: "17574", body: "   " } });
  me = await (await call(e, "GET", "/account/me", { token: session })).json();
  assert.deepEqual(me.notes.map((n) => n.id), ["ev1"]);
});

test("🛑 one account never sees another's list", async () => {
  const e = env();
  const mine = (await sessionFor(e, "paul@example.com")).session;
  const theirs = (await sessionFor(e, "someone@example.test")).session;
  await call(e, "POST", "/account/favorite", { token: mine, body: { lid: "17574", on: true } });
  await call(e, "POST", "/account/note", { token: mine, body: { kind: "venue", id: "17574", body: "private" } });

  const them = await (await call(e, "GET", "/account/me", { token: theirs })).json();
  assert.deepEqual(them.favorites, []);
  assert.deepEqual(them.notes, []);
});

test("signing out kills the session, and the session only", async () => {
  const e = env();
  const { session } = await sessionFor(e);
  await call(e, "POST", "/account/favorite", { token: session, body: { lid: "17574", on: true } });
  await call(e, "POST", "/account/signout", { token: session });
  assert.equal((await call(e, "GET", "/account/me", { token: session })).status, 401);
  // The saved list is the account's, not the browser's: it is still there for
  // the next sign-in.
  assert.equal(e.DB.db.prepare("SELECT COUNT(*) n FROM favorites").get().n, 1);
});

test("a path that is not ours is handed back, not swallowed", async () => {
  const e = env();
  assert.equal(await accountRoutes(new Request("https://api.test/submit"), e,
                                   new URL("https://api.test/submit"), {}), null);
});
