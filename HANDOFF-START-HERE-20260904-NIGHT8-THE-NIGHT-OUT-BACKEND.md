# HANDOFF — the night-out backend is live; next session is the redesign

**Date:** 2026-09-04, night 8
**Repo:** `C:\Users\paulm\happy-hour-finder` (its own `.env`, never another repo's)
**Live:** <https://paulrenzi.github.io/happy-hour-finder/>
**Worker:** <https://hhf-submit.paulmichaelrenzi.workers.dev>

## Next session, in one line

**Redesign the site with Claude design.** Read "What the redesign must not break"
below before touching a stylesheet — three of those five will look like dead code
and are not.

## What happened this session

Strategy turned into a shipped backend. Paul's thesis: the happy hour is the hook,
the product is the whole night — drinks at A, band at B, kitchen open at C. The gap
was proven on his own town: bands play Phoenixville every weekend and no aggregator
carries the set times, because The Fenix posts a JPEG, Twelve78 uses a Facebook
embed, and JamBase carries only the Colonial Theatre.

So the four fields nobody has — **start time, set length, cover, kitchen open during
the set** — became the schema, and the rails around them got built.

### Shipped, deployed, and verified by running it

| Piece | Where | State |
|---|---|---|
| Email list, double opt-in | `POST /subscribe`, signup section above the footer | **live** |
| Events table + public feed | `worker/schema.sql`, `GET /live/events.json` | **live, empty** |
| Events reader (agent) | `ingest/read_events_venue.py` | **built, never run for real** |
| Venue magic link | `web/venue.html`, `POST /venue/events` | **live** |
| `campaigns` / `pledges` | schema only | **reserved, served by nothing** |

Commits `4064e9c` → merged `673075c`, plus `784de65`. All on `origin/master`.
Worker version `82fd05d6-840d-49a8-96aa-1fd15b5762be`; remote D1 `hhf` at 8 tables.

**Verified live, not by a status code:**

```
signup section: 2      venue.html 200      applyEvents in lib.js: 1
painted: 35 blocks, body 9073 chars      named live: 11 of 11
```

Plus 13 curl smoke tests against the deployed Worker: happy path, bad token,
malformed date, idempotency, the approval flow, confirm replay, unsubscribe. The key
one — an agent-style row stayed `pending` and off the public feed until approved,
while a venue-form row published on write. All smoke rows deleted, empty feed
re-confirmed.

Full gate green: 578 Python tests, 78 Node tests, PA validators 14/14, every
Playwright check.

## What the redesign must not break

Read **[PLAYBOOK-NIGHT-OUT.md](PLAYBOOK-NIGHT-OUT.md) section 11** for the full set
with the reasoning. The five that will bite a redesign:

1. **`web/lib.js` is logic, `web/app.js` paints. Keep the split.** It is why the
   logic is testable without a browser, and it is what the 78 Node tests cover.
2. **Any `web/` edit ships nothing until `python ingest/build_bundles.py` runs.**
   It restamps the cache name in `web/sw.js`, which *is* the shell hash and the only
   eviction trigger. Never hand-edit `sw.js`. `test_ingest.ServiceWorkerCache` fails
   with a message naming none of the files you actually touched.
3. **These selectors are load-bearing, not decoration:** `.tonight` on the card
   template (removed at runtime when a venue has no event), and `#subscribe`,
   `#subscribeEmail`, `#subscribeNote` in the signup section. `app.js` queries them
   by name. Restyle freely; renaming means editing `app.js` in the same commit.
4. **Any new endpoint the page fetches needs a route stub** in all four of
   `tests/{render,card_chrome,search,picker}_check.py`, mirroring the
   `/live/deals.json` one. Without it the sandboxed test page throws
   `due to access control checks`, which reads like a code bug and is not.
5. **Verify in WebKit as well as Chrome.** WebKit has silently discarded CSS that
   Chrome drew. And "is it live" is one command: `python tests/live_front_door.py
   phoenixville` — a local render and an HTTP 200 are both blind to what breaks.

Design tokens today: cream `#f7f3eb`, teal `#0a8a9e`, Fraunces over Manrope, fonts
**self-hosted** in `web/fonts/` and precached — a redesign that pulls a webfont off a
CDN costs the offline story. Phone first, >=44px taps, no map by choice.

## Open, in the order it matters

1. **No mail sender exists.** Subscribers sit `pending` with `mailed_at NULL`, so
   nobody has received a confirm link. Either set `RESEND_API_KEY` on the Worker or
   write a sender on the PC reading `GET /admin/subscribers?status=pending` and
   reporting back to `POST /admin/subscribers/mailed`. Small, costs nothing to run.
   **Until this exists the email list collects addresses it cannot confirm.**
2. **The four-weekend clock has not started.** `read_events_venue.py` has never run
   against a real venue. First run is Phoenixville, and it spends subscription-metered
   model time across up to 46 venues, so it wants Paul's go-ahead:
   ```sh
   python ingest/read_events_venue.py --zone phoenixville --show --rejects   # file only
   python ingest/read_events_venue.py --zone phoenixville --post             # queue for review
   ```
   **Two things to watch, both untested:** whether the reader can see a Facebook
   embed at all, and whether a JPEG calendar survives the grounding gate — the model
   must transcribe the picture before it can quote it, the same path the menu lane
   took two sessions to get right.
3. **PLCB legal read** on whether prepaid tab credit and tipping-point promotions
   count as regulated drink discounts (PA caps happy hour at 4h/day, 14h/week). This
   blocks the `campaigns`/`pledges` tables and any money code.
4. **The three-band test** (playbook 9a): ask three acts off the Fenix calendar
   whether they would post a pledge link to their own followers. If the answer is
   "the bar has the followers, not us," the first screen gets built for the owner
   instead of the band.
5. **The item gap is still the standing failure** on the happy-hour side: 113 venues
   publish an hour and no items. Unrelated to the night-out layer, still the thing
   that makes the board thin.

## Where the documents are

- **README.md** — what it is, how it works, the traps. Now carries the night-out layer.
- **PLAYBOOK-NIGHT-OUT.md** — the strategy, the market evidence, the revenue model,
  the twelve unproven assumptions (7), the coordination models (9), the prior art
  that kills "nobody has done this" (9a), what is built (10), **the architecture (11)**.
- **ARCHITECTURE-MENU-INGEST.md** — the menu lane. Read before touching ingest.
- **worker/README.md** — the full route table and the operator commands.

## Standing rules that have each cost a session

- Only `master` deploys. A branch can ship commits and never go live.
- Pull before push — Codex works in this repo too. Never `git merge` during a crawl.
- `open(p,"w")` truncates before `write()` — write `.new` and `os.replace`.
- Never write a backslash escape through a bash heredoc; the patch reports success
  and the file is unchanged. Use an editor tool.
- This repo's `.env` has no `ANTHROPIC_API_KEY` and must never borrow another's — if
  one is exported it silently outranks the CLI login and bills an API account. The
  agent scripts refuse to start when they see one.
- A web page is verified by **running** it, never by an HTTP 200.
