# Thin reads, and the new towns — 2026-09-03, night

**Supersedes `HANDOFF-START-HERE-20260903-NIGHT-PA-NON-PHILLY-UNDER-10.md`**
for "where to pick up." That doc's ladder, schema, and standing rules (§3-§5)
still stand — read it if you need those. This file replaces its priority list
and adds one new rule that changes how you should read `HAND-READ-LOG.md`.

## 0. The finding this session — read this before touching the log

Paul pointed at a live venue directly: `Limoncello`
(`https://www.limoncellorestaurant.com/happy-hour-menu`, lid `59213`,
`west_chester`). It's on the board — window live, ONE item ("Pizza or
Flatbread $20"). The real page almost certainly has a fuller happy-hour menu.
The hand-read that shipped it found one price and stopped instead of reading
the whole menu.

An audit of every live deal's item count by `verified_by` found **28 more
like it**: 11 in `agent_read` (the hand-read lane), 17 in `menu_read_llm`.
Full list and the audit snippet are in `ARCHITECTURE-MENU-INGEST.md`, section
"A SHIPPED HAND-READ CAN STILL BE A THIN READ" — read that section, not just
this summary, before starting.

🛑 **`data/HAND-READ-LOG.md`'s `SHIPPED` mark now means two different things
and you have to tell them apart:** "a window and at least one item are live"
(true for all 28) vs. "the full menu was read" (not true for these 28, maybe
not true for others nobody has checked yet). **Do not treat `SHIPPED` alone as
"skip this venue."** Before skipping a `SHIPPED` venue, check its live item
count — if it's ≤1 or ≤2 for a place that plausibly has a bigger menu (a
tavern, not a coffee shop), it's a candidate for a completeness re-read, not a
closed case. `data/HAND-READ-LOG.md` needs a **new RESULT value** for this:
`RESHIPPED` (re-read, fuller menu, was thin) — add it to the taxonomy comment
at the top of the file the first time you use it.

## 1. This session's job — two halves

### Half A: re-read the 28 known thin venues for their FULL menu

The 11 named `agent_read` ones are listed in `ARCHITECTURE-MENU-INGEST.md`.
For `menu_read_llm`'s 17, run the audit snippet from that same doc but change
`verified_by` to `'menu_read_llm'` to get the per-venue list — not run yet,
do it first thing.

For each: go back to the cited URL (or re-run the ladder if the URL 404s/is
gone), and this time **capture every item on the happy-hour menu** — every
food item, every drink deal, every price — not just the first one found.
Overwrite the existing record for that lid in `data/agent_handread.json` (same
`lid`, new fuller `items` list — `build_agent_venues.py`/`build_bundles.py`
already take the latest record per lid). Log it as `RESHIPPED` in
`HAND-READ-LOG.md`, noting the old item count and the new one, e.g.:

```
- west_chester | Limoncello (59213) | RESHIPPED | was 1 item, now 5 (drinks+apps) | 2026-09-04
```

### Half B: keep growing — new towns need seeding, not just zones

`new_hope`, `newtown_bucks`, `perkasie`, `quakertown` exist in `data/zones.json`
(added by a concurrent session, not yet reflected in a handoff) but sit at
**0 venues each** — the zone shell exists, nothing is seeded into
`venue_base.json` for them yet. Seed real venues (`ingest/seed_plcb.py` or
`ingest/discover_places.py --zone <z> --dry-run` then `--execute` — never
invent a venue), then hand-read a handful with the full-menu discipline from
Half A from the start (don't create new thin reads while fixing old ones).

Beyond those four, the non-Philly PA/DE zones still under ~10 venues (re-count
first, this table drifts):
`ambler_upper_dublin`, `chester_chichester`, `havertown`, `limerick_royersford`,
`norristown_bridgeport`, `pottstown`, `souderton_harleysville`,
`abington_jenkintown`, `manayunk`, `middletown_de`, `malvern_great_valley`,
`warminster_warrington`, `collegeville_trappe`, `hockessin_greenville`,
`kennett_square`, `lansdale_montgomeryville`, `new_castle_de`,
`newtown_square_broomall`. Recount snippet is in the superseded handoff, §2.

**Photo coverage (`ingest/fetch_venue_photos.py --from-board --zone <z>
--spend`, ~$0.032-0.039/venue) was never started this round — still open,
do it per-zone as you finish each one, or as its own pass. Dry-run the whole
board first; if projected total spend looks like it'll clear ~$15-20, stop and
report the number instead of guessing.**

## 2. Standing rules — unchanged

- 🛑 A venue counts only when its items are visible in the LIVE JSON under its
  own name — `tests/live_front_door.py <zone>`. Not a build, not green tests,
  not an HTTP 200, not an agent's own self-report. **This session found actual
  cases of agents overclaiming their own delta** (see the reconciliation
  note in `data/HAND-READ-LOG.md` from earlier tonight) — always independently
  re-verify counts before writing them down anywhere.
- 🛑 A wrong item is worse than a miss — a venue's own words only, never a
  third-party roundup/listicle, never inferred.
- 🛑 Never write a backslash escape through a bash heredoc — use Write/Edit.
- 🛑 Philly-proper zones stay out of scope for hand-reads.
- Report format: one line with counts, then venue names. Nothing else.

## 3. Where it's written

- The thin-read finding, audit snippet, and full 11-venue list:
  `ARCHITECTURE-MENU-INGEST.md`, "A SHIPPED HAND-READ CAN STILL BE A THIN READ".
- `README.md` top status table — current as of tonight, states the 28-thin-read
  count plainly.
- `data/HAND-READ-LOG.md` — the attempt log; needs the `RESHIPPED` result value
  added the first time you use it.
- `umbrella-arcades/Knowledge-Graph.md` — top entry, 2026-09-03 night.
- Memory: `project_hhf_the_item_gap_is_the_standing_failure.md` and
  `project_hhf_two_thirds_of_agent_reads_cannot_publish.md` — both updated
  tonight with this finding.
