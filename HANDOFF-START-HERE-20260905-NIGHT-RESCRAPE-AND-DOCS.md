# HANDOFF — 2026-09-05 night: the thin-menu rescrape, and the docs it should have updated

Start here. Read `README.md` top to bottom first (it's current as of this
session), then this file for what happened tonight and what's queued next.

## What happened tonight

Paul's ask: keep digging overnight, wake up to 50-100 more fully-scraped
venues with over-5-item happy-hour menus.

Ran `ingest/agent_read_venue.py --force --workers 6 --show --rejects` against
the 145 unique venues in `data/RESCRAPE-QUEUE.json` (Paul's standing rule:
any live deal under 5 items needs a re-scrape). Lids came from
`scratchpad/rescrape_lids.txt` (145 unique, extracted from the queue).

**Result: 47 of 145 crossed the 5-item line**, short of the 50-100 target.
Why, honestly:
- 19 of the 145 had no `website` on file at all — `population()` in
  `agent_read_venue.py` filters on it, so those were never reachable. Not a
  bug; there was nothing to read.
- Of the 126 actually read, 76 came back grounded (passed the quote-substring
  gate); 50 came back with nothing new or still thin.
- A real fraction of what got read genuinely only publishes 1-4 items
  ($2-off-drafts-and-nothing-else). That's not a miss, it's what the venue
  put in writing — a wrong/invented item is worse than a short one.
- Cost: ~$58 of subscription-metered model time for the whole batch.

Shipped in two commits, seed then build (the correct order — seed must land
before the worktree rebuild reads it):
- `3fa1035` — agent read: 145 thin venues re-read, 47 cross the line
- `83526b6` — build: rebuilt bundles from that seed

Rebuilt in a detached worktree (`/tmp/hhf-build-wt`), gated clean
(`bash tests/run.sh` → EXIT 0, 578 tests OK), pushed, watched CI green, then
verified **live** with `tests/live_front_door.py` on two zones:
`center_city` 115/115 named live, `wilmington` 39/39 named live.

**Board is unchanged at 473 venues / 489-ish deals across 51 zones** — this
pass added item depth to already-published venues, it added zero new windows.

## A finding worth carrying forward: `RESCRAPE-QUEUE.json` counts *deals*, not *venues*

Regenerated it post-rebuild (`python tests/thin_read_report.py`, which
`tests/run.sh` also runs) expecting it to drop from 154 to something near
106. **It came back at 154 again, unchanged.** Not a bug in the report —
since 2026-09-02 a venue can carry more than one deal (happy hour, daily
specials, food combos), and the report counts every deal under 5 items, not
every *venue* under 5 items. A venue whose happy hour got fixed tonight can
still show up in the queue for an unrelated thin "specials" row. **Read
`item_count` per row to judge what's actually still weak — don't trust the
top-line `count` to mean "154 venues still broken."** This is now noted in
README; nobody had actually looked at this file's `build()` function before
tonight to notice the per-deal counting.

## Cosmetic, not a bug: the `LIVE —` line prints a mangled character

`tests/live_front_door.py` line 81 prints an em-dash (`—`). On this Windows
terminal it renders as `�`. The numeric verification around it (`named live:
X of X`) is unaffected and was clean both times it ran tonight. Not
investigated further — cosmetic console-encoding artifact, not a defect in
the test or the site. Leave it; don't spend a session on it.

## Docs updated this session

- `README.md` — stats table refreshed to today's real numbers (473 windows,
  312 with items/2,175 items, 161 hour-no-items, 3,714 licensed venues,
  2,113 with a website, 2,229 crawled), plus a new paragraph on tonight's
  rescrape pass and the deal-vs-venue counting note above.
- This handoff.
- `PLAYBOOK-NIGHT-OUT.md` — untouched; nothing built tonight touches the
  night-out layer. Still accurate as of 2026-09-04.

## Next session: photos, especially the weak Philly zones

Paul's explicit ask for next session: **fill in missing photos, especially
the weaker areas like Philly.** Numbers pulled tonight so the next session
doesn't have to re-derive them (counts are ALL venues in the zone —
`zone-*.json` with hours + `venues-*.json` without — since a photo is worth
having on a silent card too):

| zone | venues | with a photo | gap |
|---|---:|---:|---:|
| center_city | 642 | 60 | **582** |
| west_philly | 82 | 1 | **81** |
| university_city | 117 | 6 | **111** |
| south_philly | 109 | 4 | **105** |
| northwest_philly | 71 | 1 | **70** |
| manayunk | 58 | 3 | **55** |
| fishtown_kensington | 171 | 142 | 29 (already strong) |

Whole corpus for context: 3,712 venues, 2,024 with a photo, **1,688 without**.
Philly (the six weak zones above, excluding fishtown_kensington which is
already good) accounts for **1,004** of that gap by itself — the single
biggest lever available.

Photo pipeline lives in `ingest/discover_places.py` (Google Places photo
fetch — paid step) and `ingest/sync_approved.py` (bakes in user-submitted
photos). Read `ARCHITECTURE-MENU-INGEST.md` for the discover→build chain
before running anything at corpus scale — **scoped runs only, one zone at a
time**, same rule as menu reads. `center_city` alone (582 missing, 642
total) is worth its own dedicated pass before touching the smaller zones.

## Standing rules unchanged, still in force

- Scoped runs, one town/zone at a time, never the whole corpus.
- Seed commit → worktree rebuild → gate (`tests/run.sh`) → bundle commit →
  push → watch CI → `tests/live_front_door.py <zone>` is the only sequence
  that counts as "shipped." A rebuild in the shared tree ships whatever
  uncommitted junk is sitting in it.
- `bash tests/run.sh` is the gate — check the BUILT bundle, not a lane's own
  summary line.
- Never invent or guess an item, price, or window. A wrong item is worse
  than a miss.
- This repo's `.env` never borrows shopify-analytics'.
