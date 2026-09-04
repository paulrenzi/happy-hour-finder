# Docs caught up, no new menus this session — think about the list next time

**Supersedes** `HANDOFF-START-HERE-20260904-NIGHT4-WRONG-NAME-ON-THE-BOARD.md`
for what to read first. Its fix is live and not repeated here.

## 0. What this session was

Documentation and verification only — **no new agent reads, no new menus, no
board changes.** NIGHT4's fix (Serum→Slow Hand) was already committed and
live before this session started. This session:

1. Found and documented one more thing about *why* that bug survived two
   sessions (see §1).
2. Brought `README.md`'s numbers and diagrams back to exactly what
   `ingest/build_bundles.py` prints (several had drifted stale: `44` zones →
   `48`, `3,415` venues → `3,479`, `333` checked quotes → `371`).
3. Confirmed nothing was left uncommitted, unpushed, or un-live.

Board is unchanged from NIGHT4: **355** venues with a window, **264** with
items (**1,939**), **91** with an hour and no items. `python
ingest/build_bundles.py` reproduces byte-identical output — no drift.

## 1. New finding: a provenance field got read as a confidence field

Went back to check *why* the existing 2026-09-02 "a door outlives its
tenants" guard (`ingest/crawl_roundups.py:280`) didn't already catch the
Slow Hand join. It has its own escape hatch: it never holds an article
heading against a venue's name when `venue_base` says `named_by == "plcb"`,
on the theory that a licence-only name is always an anonymous shell safe to
overwrite.

Slow Hand's `venue_base` row is exactly `{"name": "Slow Hand", "named_by":
"plcb"}` — a real, current, live trade name that simply hadn't had the OSM/
Places enrichment pass run on it yet. `named_by` records **which pass wrote
the name**, not **whether the name is true**. That single field being reused
as a truth signal is what let the guard step aside for a real name.

`quote_names_another_door()` (NIGHT4's fix) doesn't look at `named_by` at
all — it reads the article's own quoted text for a mismatched street address
— so it's strictly more general and doesn't share this hole. Both guards
stay; they fire on different rows. Full writeup: `ARCHITECTURE-MENU-INGEST.md`
(new section, bottom of file) and the KG memory
`feedback-a-fallback-key-leaves-the-primary-join-unchecked.md` (updated, not
new — same file, doesn't touch `MEMORY.md`'s size budget).

## 2. The actual open work, unchanged since NIGHT4

- **MadMacs and Slow Hand** — 16 and 10 items respectively, paid for and
  banked in `data/agent_reads.json`/`data/deals_agent.json`, **published on
  neither** because neither venue's own website states a day or a clock
  anywhere. Needs Instagram/Facebook, not the main site. Cheapest real yield
  on the board — $0 additional agent spend, pure research.
- Thin-item towns: center_city (18 thin), phoenixville, newark_de (9 thin),
  exton_downingtown (8), remaining west_chester thin venues.
- `data/RESCRAPE-QUEUE.json`: **125** live deals under 5 items, corpus-wide.
- Paul's call, still open: drop James Street Tavern and Timothy's Riverfront
  Grill (confirmed no current happy hour)?

## 3. The actual ask for next session: how do we want to work the list?

This wasn't answered this session on purpose — it's a real decision, not
busywork, and it's worth framing before just running the next batch:

- **Depth-first per town** (finish west_chester's stragglers, then move to
  the next town) vs. **breadth-first by yield** (always read whichever
  venue/town is statistically likeliest to have a real happy hour, wherever
  it is) — the corpus doesn't have per-town yield stats yet; that would need
  building before breadth-first is even choosable.
- **Windows before items, or items before windows?** MadMacs/Slow Hand are
  the "items exist, window doesn't" case — cheap because no new agent spend.
  The 91-venue reach gap is the mirror case (window known, items don't) and
  is the $0.35/venue agent-read lane. Worth deciding whether the windowless-menu
  backlog (currently 2 venues) is worth building a *repeatable* off-site
  (Instagram/Facebook) search step for, or whether it's a one-off worth just
  doing by hand each time it comes up — 2 venues doesn't justify new
  infrastructure yet, but the list is what tells us if that changes.
- **Chain sites** stay parked — two independent confirmed-exhausted strikes
  (Deer Park Tavern, Crooked Hammock) — not worth agent spend until there's a
  reason to believe a chain menu differs from what's already been tried.

None of this needs to be resolved before running more reads — it's a framing
question so the next session's choice of what to read next isn't arbitrary.

## 4. Verification this session

- `python ingest/build_bundles.py` → identical output, `git status --short`
  clean before and after (no drift to commit).
- `bash tests/run.sh` → 558 Python tests green, node suite `fail 0`.
- `python tests/window_quote_check.py` → 371 published deals, 0 window/quote
  contradictions.
- `python tests/live_front_door.py west_chester` → LIVE, 23/23 named.
- `git log` / `git status` confirmed both NIGHT4 commits (`f195956`,
  `b1d3a1f`) already on `origin/master` with a clean tree before this
  session's docs commit.

## 5. Standing rules, unchanged

Scoped runs only, one town at a time, never the corpus. "It is live" is one
command: `python tests/live_front_door.py <zone>` — and for a *removal*,
re-fetch the live bundle too; GitHub Pages served the old copy for ~1 minute
after NIGHT4's push. A wrong item is worse than a miss. Check
`git branch --show-current` before committing (repo is shared with Codex).
Check the **built bundle**, not a lane's own summary.
