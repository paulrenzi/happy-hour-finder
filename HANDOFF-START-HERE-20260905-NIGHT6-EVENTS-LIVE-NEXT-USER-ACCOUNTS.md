# HANDOFF — events lane is live, 144 rows/29 venues; next: user accounts (2026-09-05, night 6)

**Read this first.** No other handoff needed to start; PLAYBOOK-NIGHT-OUT.md
§15 has the full account if you want the mechanism behind any of this.

---

## The one-sentence state

The events lane that night 5 built but never posted is now live end to end —
**144 approved rows across 29 venues** (187 occurrences once 38 standing
weekly rules expand across the 14-day window) — in Wayne, West Chester and
Phoenixville, and the review queue Paul cleared is empty. Verified live:

```
$ curl -s https://hhf-submit.paulmichaelrenzi.workers.dev/live/events.json | python -c "
import json,sys; d=json.load(sys.stdin)
print(len(d['venues']),'venues',sum(len(v) for v in d['venues'].values()),'rows')"
29 venues 187 rows
```

## What shipped this session

1. **The four-boundary gap from night 5's handoff, fixed.** There was no code
   path from `data/events_reads.json` to the review queue at all, and
   Cloudflare's edge 403s the default `urllib` User-Agent before the Worker is
   ever reached (a 403 there is not an auth failure). `--post-only` posts what
   is grounded on file for $0; `--reground` re-runs the grounding gate over
   transcripts already paid for, also $0.
2. **Recurring weekly shows are first-class.** Most of a bar's calendar turned
   out to be a standing grid, not a list of gigs — Saloon 151 publishes 8
   weekly shows, Kildare's 7. `events.recurs`/`until` in the schema, a weekly
   row keyed on venue+weekday (not date) so a re-read refreshes it instead of
   re-approving it forever, expansion happens in the Worker so `web/` needed no
   change. `ingest/recurrence.py` infers a rule from the venue's words plus the
   model's own duplicate expansion — the second signal was necessary, the first
   alone caught only 1 of Saloon 151's 8 shows.
3. **🚨 A real wrong-venue join, found fixing "the 118 North card."** One
   licence (The Blue Elephant, 110 N Wayne Ave) was shipping a *different*
   restaurant's name, website, happy hour and 15 approved events — 118 North,
   118 N Wayne Ave, a different licence entirely. A hand-read had guessed the
   join from the business name alone; nothing checked it against the street
   address already in the licence row. Same defect NIGHT4 guarded on the
   roundup joiner, reopened through the hand-read path, which has **no
   equivalent guard yet**.
4. **Fan-out:** Wayne + West Chester + Phoenixville read (~102 venues, ~3 in
   10 publish a calendar, ~$0.65/venue).
5. **A queue-hygiene fix, deployed:** the review endpoint now accepts
   `status: "pending"` for undoing an operator's own bulk-action mistake
   (I wrongly bulk-rejected 85 good rows mid-session; there was no way back
   except a raw D1 patch until this shipped).
6. **118 North itself:** correct name, address, website, happy hour, photo,
   and its own 15-event calendar — all under lid 66143, not borrowed.

Full account, evidence and exact numbers: **PLAYBOOK-NIGHT-OUT.md §15**
(ten subsections, 15.1 through 15.10).

## Known open defects, not fixed — read before you hit them

- 🛑 **Concurrent whole-file readers can silently clobber each other.**
  `read_events_venue.py` and `fetch_og_images.py` (and probably others) each
  `load()`/`save()` a whole JSON file with a per-process, not cross-process,
  lock. Running two at once lost work twice this session. **Never run two
  readers/fetchers at once.**
- 🛑 **The hand-read path has no door-check guard.** `quote_names_another_door()`
  protects the roundup joiner; the hand-read path that caused this session's
  wrong-venue bug has nothing equivalent. It will happen again on the next
  hand-read until it does.
- 🛑 **The review queue shows the act, not the building.** A reviewer approving
  a row sees act/date/lid, never the venue's name or address — which is why
  the wrong join was invisible at the exact moment a person was asked to rule
  on it.

## Everything is live — verified, not assumed

- `git log`: `764d9c4` is `HEAD`, pushed, matches `origin/master`.
- `web/sw.js` restamped and confirmed served: `hhf-2026-09-05-471-fbc4bb14`.
- `GET /live/events.json` confirmed live with 29 venues / 187 rows (command
  above).
- 118 North's card confirmed live with the right name/address/photo via a
  direct fetch of `web/data/zone-wayne_radnor.json` from the CDN.
- `bash tests/run.sh` → every section prints `OK` or nothing, including the
  new `tests/test_recurrence.py` (all green, 590+91 tests).

## README

Top-of-file stats table and the events section are current as of this
session — read `README.md` fresh next session rather than trusting memory of
an older number.

---

## Next session: basic user accounts — favorite lists + notes

Paul's ask for next time, verbatim: **add basic user accounts to allow for
favorite lists, with the ability to add personalized notes to a place when
logged in.**

Nothing for this exists yet. Before writing code, resolve:

- **Auth mechanism.** No login of any kind exists on the board today (the
  email-signup lane is unconfirmed-email-only, no password, no session). Decide
  magic-link (reuses the `venue_tokens`/confirm-link pattern already proven in
  `worker/nightout.js`) vs. a real password/OAuth flow. Magic-link is the
  smaller build and matches the site's existing trust model.
- **Where favorites/notes live.** `worker/schema.sql` already holds
  `subscribers`; a `users` + `favorites` (+ optionally `notes`, keyed on
  `lid`) table is the natural extension, same D1 database, same Worker.
- **What "logged in" means on a static PWA.** The board is offline-first
  (`web/sw.js` precaches everything); a session token in `localStorage` plus a
  Worker endpoint for the authenticated CRUD is the shape that fits without
  breaking the offline story — read `web/lib.js`/`web/app.js`'s existing
  patterns (`applyEvents`, the subscribe flow) before inventing a new one.
- **Scope check first:** is this account system meant to unify with the
  existing email-subscriber list, or sit beside it as a separate identity?
  That decision changes the schema — ask Paul before building either way.

Start by reading `PLAYBOOK-NIGHT-OUT.md`'s existing sections on the
subscribe/venue-token mechanism (§11's "the pieces and where they live") for
the patterns already proven, then design the accounts schema before writing
any Worker code.
