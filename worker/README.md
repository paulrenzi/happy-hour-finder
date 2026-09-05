# The photo lane

Everything on this site is static files except this. The Worker is the one
endpoint that writes: it takes a menu photo, strips the location data out of it,
puts it in R2, and queues a row in D1. It publishes nothing. A photo becomes a
card on the board only after a person approves it and the bundles are rebuilt.

```
phone ──POST /submit──> Worker ──> R2 (photo) + D1 (row: pending)
                                        │
        ingest/extract_photo_deals.py ──┤  `claude -p` reads the menu,
        (grounding + PA validators)     │  writes a proposal: extracted
                                        │
        ingest/review_photos.py ────────┤  Paul says yes or no: approved
        (the moderation queue)          │  -> data/deals_photo.json
                                        │
        ingest/build_bundles.py ────────┘  -> web/data/, commit, push
```

## Deploy (one time)

Needs `npm i -g wrangler` and `wrangler login`. Run from the repo root.

```sh
wrangler r2 bucket create hhf-photos
wrangler d1 create hhf                     # paste database_id into wrangler.toml
wrangler d1 execute hhf --remote --file worker/schema.sql

cd worker
wrangler secret put ADMIN_TOKEN            # `openssl rand -hex 32`
wrangler secret put IP_SALT                # `openssl rand -hex 16`
wrangler deploy

# Wrangler needs BOTH env vars with an account-scoped token: with only
# CLOUDFLARE_API_TOKEN set it calls /memberships and dies "Authentication
# failed (status: 400) [code: 9106]". Also export:
#   CLOUDFLARE_ACCOUNT_ID=83f33c67294ca2f2f0869b63c1663b0e
```

`wrangler deploy` prints the live URL. Two places need it, and they must match:

1. `web/app.js` → `SUBMIT_API`. Now `https://hhf-submit.paulmichaelrenzi.workers.dev`
   (deployed 2026-08-31). It was a **guess** — `paulrenzi`, not the account's
   real subdomain `paulmichaelrenzi` — for as long as the Worker went
   undeployed, and a wrong value here fails the Send button with a network
   error while nothing else on the site breaks. That is exactly how it read
   from a phone: "Couldn't reach us", on full 5G.
2. `happy-hour-finder/.env` (this repo's own — never another repo's):

   ```
   SUBMIT_API=https://hhf-submit.<subdomain>.workers.dev
   ADMIN_TOKEN=<the same value you put in the secret>
   ```

Check it with `curl https://.../health` → `{"ok":true,"service":"hhf-submit"}`.

**Photos live in KV, not R2.** R2 is not enabled on this Cloudflare account —
creating the bucket returns code 10042, "Please enable R2 through the
Cloudflare Dashboard", which is a billing opt-in nobody can do from a script.
The Worker keeps both paths (`putPhoto`/`getPhoto`) and uses whichever binding
exists, so switching to R2 later is: enable it, create `hhf-photos`, uncomment
the `r2_buckets` block in `wrangler.toml`, copy existing keys across, redeploy.

## Running the queue

```sh
python ingest/extract_photo_deals.py --dry-run   # read the photos, print, post nothing
python ingest/extract_photo_deals.py             # post proposals onto the rows
python ingest/review_photos.py                   # approve or reject, one by one
python ingest/build_bundles.py                   # THIS is what publishes
git add -A && git commit -m "photo lane: <venues>" && git push
```

Extraction runs on the `claude` CLI against the Max subscription, like
`ingest/extract_prices_llm.py`. There is no Anthropic API key in this repo. If
`ANTHROPIC_API_KEY` is exported in your shell it silently outranks the CLI login
and bills an API account instead, so the script refuses to start when it sees
one.

## What protects what

| Risk | What stops it |
|---|---|
| GPS of the bar stored with the photo | Canvas re-encode in the browser, then a JPEG marker strip in the Worker. Two passes because the first one only runs if JS did |
| Something that isn't an image | Magic-byte sniff. The `Content-Type` header is the client's word for it and is not trusted |
| The endpoint becoming an open image host | 8 MB cap, 12/day per submitter (salted IP hash, never the address), optional Turnstile |
| An unreviewed photo becoming a public URL | Nothing is served from R2 to the public. `/admin/photo/<id>` needs the token |
| A price nobody printed | The model must quote the transcript it produced; an item whose quote is not in it is dropped before a human ever sees it |
| A deal that breaks PA law | `ingest/validate_pa.py`, the same validators every other lane clears |
| A photo of a person, a receipt, anything else | The extraction pass raises `concerns`, and a person looks at every photo regardless |

Two things the Worker deliberately cannot do: publish, and reopen a decision. A
row only moves `pending → extracted → approved|rejected`, and a submission a
human has already ruled on is not something a later extraction pass can touch.

## Optional: Turnstile

Rate limiting is per-IP and an IP is cheap. If the lane gets abused, add a
Turnstile widget to the sheet and set the secret — `/submit` starts requiring a
token the moment the secret exists, and ignores it while it doesn't.

```sh
wrangler secret put TURNSTILE_SECRET
```

## The night-out layer (added 2026-09-04)

Same Worker, second module: `worker/nightout.js`. Why it exists and what it is
for is `PLAYBOOK-NIGHT-OUT.md`; the routes are listed at the top of the file.
Tables are appended to `worker/schema.sql` (all `IF NOT EXISTS`, so the same
`wrangler d1 execute` line applies them).

| Route | Who | What |
|---|---|---|
| `POST /subscribe` `{email, zone_id}` | public | pending row + confirm token. 5/day per IP |
| `GET /subscribe/confirm?t=` | the mail | marks confirmed, redirects to the board |
| `GET /subscribe/leave?t=` | the mail | deletes the row outright |
| `GET /live/events.json[?zone=]` | public | approved events, today + 14 days, keyed by licence id. The board patches these onto cards like the deals overlay |
| `POST /venue/events` `{token, events}` | a venue with its magic link | publishes immediately, `source_kind: venue_form` |
| `GET /admin/events?status=pending` | admin | the review queue |
| `POST /admin/events` `{events}` | `ingest/read_events_venue.py --post` | bulk insert, `pending` |
| `POST /admin/events/review/<id>` `{status, note}` | admin | `status` is `approved`, `rejected`, or `pending` (the last is for undoing your own bulk-action mistake, not for a re-read to overturn a person's ruling) |
| `POST /admin/venue-token/<lid>` `{contact}` | admin | mints the venue's link: `web/venue.html#<token>`. Minting again replaces it |
| `GET /admin/subscribers?status=` | admin / the PC sender | the list |
| `POST /admin/subscribers/mailed` `{emails}` | the PC sender | stamps `mailed_at` so nothing is sent twice |

**Mail.** The Worker sends the confirm link only when `RESEND_API_KEY` (and
optionally `MAIL_FROM`) is set. Until then a subscriber sits `pending` with
`mailed_at NULL`; a script on Paul's PC can read `/admin/subscribers?status=pending`,
send from this repo's own address, and report back through `/admin/subscribers/mailed`.
There is no sender script yet — that is the next piece.

**Events reach a card two ways.** A venue's own form publishes on write, because
the venue is the author. Everything the agent reads off a calendar picture or a
page lands `pending` and waits for a person, exactly like a stranger's menu photo.

```sh
python ingest/read_events_venue.py --zone phoenixville --show --rejects   # read, file only
python ingest/read_events_venue.py --zone phoenixville --post             # ...and queue for review
curl -H "X-Admin-Token: $ADMIN_TOKEN" "$SUBMIT_API/admin/events?status=pending"
curl -H "X-Admin-Token: $ADMIN_TOKEN" -X POST "$SUBMIT_API/admin/events/review/<id>" \
     -H "Content-Type: application/json" -d '{"status":"approved"}'
```

`campaigns` and `pledges` are in the schema and served by nothing. See the
playbook, section 9a, for what has to be true before they are.

## Accounts (added 2026-09-05)

Third module: `worker/accounts.js` — a saved list of places and a private note
on any of them. Tables are appended to `worker/schema.sql`; the same
`wrangler d1 execute` line applies them, and the `ALTER TABLE subscribers ADD
COLUMN account_at` at the very end of that file is expected to fail on a re-run
("duplicate column name") — everything before it has already run.

| Route | Who | What |
|---|---|---|
| `POST /account/signin` `{email}` | public | mints a one-time link and mails it. **202 whether or not the address is known** — the endpoint must never be an account-lookup oracle. 6/day per IP |
| `GET /account/callback?t=` | the mail | one use, 30 minutes; redirects to the board with the session in the **fragment** |
| `GET /account/me` | Bearer session | `{email, favorites, notes}` |
| `POST /account/favorite` `{lid, on}` | Bearer session | save or unsave one bar |
| `POST /account/note` `{kind, id, body}` | Bearer session | a note on a venue (`kind: "venue"`, id = lid) or one night (`kind: "event"`, id = event id). An empty body deletes it |
| `POST /account/signout` | Bearer session | deletes that session, and only that session |
| `POST /admin/account/signin-link` `{email}` | admin | mints a link and **returns** it instead of mailing it |

Three rules, all gated by `tests/accounts.test.mjs` (which runs `schema.sql`
itself against Node's SQLite):

1. **An account is not a subscription.** An account is a row in `subscribers`,
   because an address is one person either way — but `status` still means "is
   this on the digest", and signing in never touches it. An account-only row is
   `status = 'none'`.
2. **Nothing reversible is stored.** Both tokens are held as SHA-256 hashes.
   The copy in the mail and the copy in the browser are the only usable ones.
3. **Notes are private.** They are the most personal thing this database holds.
   They are served only to the account that wrote them, never mailed, and never
   reach the board's bundles.

🛑 **Mail needs `RESEND_API_KEY`, and it is not set.** Until it is, a public
`POST /account/signin` answers 202 and sends nothing, so nobody can sign in
without the admin route above. Setting it is one command:

```sh
cd worker && wrangler secret put RESEND_API_KEY   # and MAIL_FROM in [vars]
```
