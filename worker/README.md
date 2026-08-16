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
```

`wrangler deploy` prints the live URL. Two places need it, and they must match:

1. `web/app.js` → `SUBMIT_API`. It is currently set to a **guess**
   (`https://hhf-submit.paulrenzi.workers.dev`) because the subdomain is only
   known once you have deployed. If it is wrong the Send button fails with
   "Couldn't reach us" and nothing else on the site breaks.
2. `happy-hour-finder/.env` (this repo's own — never another repo's):

   ```
   SUBMIT_API=https://hhf-submit.<subdomain>.workers.dev
   ADMIN_TOKEN=<the same value you put in the secret>
   ```

Check it with `curl https://.../health` → `{"ok":true,"service":"hhf-submit"}`.

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
