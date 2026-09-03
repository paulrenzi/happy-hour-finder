# Thin reads, and the new towns — 2026-09-03, night

**Supersedes `HANDOFF-START-HERE-20260903-NIGHT-PA-NON-PHILLY-UNDER-10.md`**
for "where to pick up." That doc's ladder, schema, and standing rules (§3-§5)
still stand — read it if you need those. This file replaces its priority list
and adds one new rule that changes how you should read `HAND-READ-LOG.md`.

## 0. The finding this session — read this before touching the log

Paul pointed at two live venues directly: `Limoncello`
(`https://www.limoncellorestaurant.com/happy-hour-menu`, lid `59213`,
`west_chester`, one item) and Liberty Union Bar and Grill
(`https://libertyunionbar.com/chester-springs/specials/happy-hour/`, lid
`65626`, `exton_downingtown`, one item). Both on the board, both plainly
under-read — a page that almost certainly carries a fuller happy-hour menu
than what got captured.

**🔑 THE RULE, Paul's words: if a listing has under 5 happy-hour items, treat
it as needing a re-scrape.** Not just the hand-read lane — every lane that
claims items (`auto_extract`, `agent_read`, `menu_read_llm`, `staff`,
`roundup_extract`). Board-wide tonight, that's **146 distinct venues / 155
deals**. Full breakdown, the rule's exact scope, and the audit script are in
`ARCHITECTURE-MENU-INGEST.md`, section "A 'SHIPPED' HAND-READ CAN STILL BE A
THIN READ — RULE: UNDER 5 ITEMS ⇒ RE-SCRAPE" — read it before starting.

🛑 **This is now tracked as a first-class artifact, not just a doc note:**
`python tests/thin_read_report.py` regenerates `data/RESCRAPE-QUEUE.json` —
every zone/venue/lid/url/item-count under the 5-item bar — and is wired into
`tests/run.sh` so every full test run prints the current backlog by zone.
**Run it first thing this session** to get the live, current list (146/155 is
tonight's snapshot; the board moves).

🛑 **`data/HAND-READ-LOG.md`'s `SHIPPED` mark now means two different things
and you have to tell them apart:** "a window and at least one item are live"
(true for everything in the queue) vs. "the menu was read to completion / has
≥5 items" (false for everything in the queue). **Do not treat `SHIPPED` alone
as "skip this venue"** — cross-check it against `data/RESCRAPE-QUEUE.json`
first. `data/HAND-READ-LOG.md` already has a new RESULT value for this:
`RESHIPPED` (re-read, fuller menu, was thin).

## 1. This session's job — two halves

### Half A: work `data/RESCRAPE-QUEUE.json` down

Run `python tests/thin_read_report.py` to get the current list (printed by
zone, worst zones first — `center_city` and `wilmington` are the biggest
single buckets tonight, but those may be lower priority than the non-Philly
PA/DE zones per the standing scope rule below). For each venue in the queue:
go back to the cited URL (or re-run the ladder if it's gone), and this time
**capture every item on the happy-hour menu** — every food item, every drink
deal, every price — until the count clears 5 or the venue's own page is
genuinely exhausted (a real 2-3 item happy hour exists at some places; don't
pad it). Overwrite the existing record for that lid in
`data/agent_handread.json` (`build_agent_venues.py`/`build_bundles.py` take
the latest record per lid — this also works for a venue whose thin read came
from a non-hand-read lane like `auto_extract`; it just becomes a new
`agent_handread.json` record for that lid). Log it as `RESHIPPED` in
`HAND-READ-LOG.md` with the before/after item count, e.g.:

```
- west_chester | Limoncello (59213) | RESHIPPED | was 1 item, now 5 (drinks+apps) | 2026-09-04
```

Re-run `python tests/thin_read_report.py` periodically to watch the count
drop and refresh `data/RESCRAPE-QUEUE.json` for the next session.

### Half B: new towns — mostly seeded, one still needs work

A concurrent session this same night already did most of this: `new_hope`,
`newtown_bucks`, `perkasie`, `quakertown` are seeded into `data/zones.json` +
`venue_base.json` from a fresh PLCB export, and three are live and confirmed
via `tests/live_front_door.py`: **new_hope 1, newtown_bucks 2, perkasie 1.**
**`quakertown` is still 0 live** — 11 candidates were read and every one
dead-ended (`NO_CLOCK_TIME`/`UNREACHABLE`, logged in `HAND-READ-LOG.md`); it's
seeded but genuinely thin for the hand-read ladder as it stands. Worth one
more pass with fresh eyes (raw urllib fetch instead of `sweep_site.py` for any
JS-rendered site, PDF/Instagram steps) before writing it off.

Beyond that, the non-Philly PA/DE zones still under ~10 venues (recount
first, this table drifts): `ambler_upper_dublin`, `chester_chichester`,
`havertown`, `limerick_royersford`, `norristown_bridgeport`, `pottstown`,
`abington_jenkintown`, `manayunk`, `malvern_great_valley`,
`warminster_warrington`, `collegeville_trappe`, `hockessin_greenville`,
`kennett_square`, `lansdale_montgomeryville`, `new_castle_de`,
`newtown_square_broomall`. 🛑 Most of these were swept again this session and
dead-ended too (empty sweeps, 403/timeout, no absolute price reachable) — this
territory is close to tapped out for the hand-read ladder as written. A fresh
lever (not just repeating the same 6 steps) is more likely to move it than
another sweep — check `HAND-READ-LOG.md` before spending time on any of them.

**Photo coverage is DONE — do not re-spend on it.** The concurrent session ran
`ingest/fetch_venue_photos.py --from-board` across the whole board:
**351 of 351 live venues now have a photo (100%), $0.86 total spent.** Only
re-run it for a venue newly added after this point.

## 2. Standing rules — unchanged

- 🛑 A venue counts only when its items are visible in the LIVE JSON under its
  own name — `tests/live_front_door.py <zone>`. Not a build, not green tests,
  not an HTTP 200, not an agent's own self-report. **This session found actual
  cases of agents overclaiming their own delta** — always independently
  re-verify counts before writing them down anywhere.
- 🛑 A wrong item is worse than a miss — a venue's own words only, never a
  third-party roundup/listicle, never inferred.
- 🛑 Never write a backslash escape through a bash heredoc — use Write/Edit.
- 🛑 Philly-proper zones stay out of scope for hand-reads.
- 🔑 **NEW: any live deal with under 5 items needs a re-scrape** — see §0.
- Report format: one line with counts, then venue names. Nothing else.

## 3. Where it's written

- The thin-read finding, the ≥5-item rule, and the audit script:
  `ARCHITECTURE-MENU-INGEST.md`, "A 'SHIPPED' HAND-READ CAN STILL BE A THIN
  READ — RULE: UNDER 5 ITEMS ⇒ RE-SCRAPE".
- `tests/thin_read_report.py` — regenerates `data/RESCRAPE-QUEUE.json`, also
  runs as part of `tests/run.sh`.
- `README.md` top status table — current as of tonight, states the 146-venue
  thin-read backlog plainly.
- `data/HAND-READ-LOG.md` — the attempt log; `RESHIPPED` result value and the
  finding are already in its header.
- `umbrella-arcades/Knowledge-Graph.md` — top entry, 2026-09-03 night.
- Memory: `project_hhf_the_item_gap_is_the_standing_failure.md` and
  `project_hhf_two_thirds_of_agent_reads_cannot_publish.md` — both updated
  tonight with this finding.
