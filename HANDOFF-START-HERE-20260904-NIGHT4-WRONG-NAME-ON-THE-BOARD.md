# The board was publishing a closed business's name — 2026-09-04 (night 4)

**Supersedes** `HANDOFF-START-HERE-20260904-NIGHT3-KG-UPDATE-AND-HANDOFF.md`
for what to read first. Its §1 findings (the duplicated `verify()` schema
field, the chain-site exhaustion pattern) are still current and not repeated.
**Its §2 and §3 are corrected below — do not act on them as written.**

## 0. What shipped

One card came off the board, and it is the most important thing this session
found. `west_chester` lid **101307** was shipping as **"Serum Kitchen &
Taphouse"**, Monday–Friday 4–6, with 4 items.

- The licence at **30 N Church St** is **SLOW HAND** (PLCB, `venue_base`).
- Slow Hand's own site says **Tue–Fri**, and **"Closed Mon"**.
- The roundup paragraph the deal was built from prints **142 E. Market St** —
  a different building three streets away, which `tests/test_ingest.py`
  already knows as **Station 142**.

So the board told a customer a closed business's name *and* a Monday happy
hour at a bar that is closed Mondays. Live now under its own name, no deal:
`python tests/live_front_door.py west_chester` → **LIVE**, 23/23 named,
`Serum` gone from the live bundle (confirmed by re-fetching it, not by a
green build).

Commit `f195956`. 558 tests (+6), node green, 371 published deals / 0 window
contradictions. Board: **355** venues with a window, **264** with items
(**1,939**), 91 with an hour and no items.

## 1. The mechanism, and why it survived two sessions

`crawl_roundups.py` joins a roundup heading on **name**, with **address** as a
*fallback* — documented as *"a heading the name index resolves is never
re-routed by an address."* So a name-join was **never checked against the
address printed in its own paragraph**. The refutation was one sentence away,
inside the very quote the deal was built from.

> **The general rule, now in the KG:** when a join has a strong fallback key,
> ask what checks the *primary* path. Usually nothing — a fallback is written
> to fire when the primary *fails*, so nobody writes the case where the
> primary *succeeds and is wrong*.

`quote_names_another_door()` (in `crawl_roundups.py`) now refuses such a join
at **build** time, wired into `build_bundles.py`'s roundup merge. Build time
because the bad deal is already baked into `data/deals_roundup.json` — a
crawl-time-only guard would need a re-crawl to take effect. It **refuses
rather than re-routes**: absent beats publishing under another business's
name, the rule `HAND_DROPPED` already keeps in `discover_places.py`.

**Second bug, found while validating the first.** `ADDRESS_RE` had no `re.I`
while the PLCB base **shouts** (`40 E MARKET ST`). The new check read *no door
at all* on those rows and could never disagree — blind, not green. My first
run of the guard showed **4** hits; three were this blindness. With `re.I` the
true count across all 23 roundup joins is **1**. Shipping on the un-measured
number would have dropped three good cards. Four base venues also parsed to no
address before this.

## 2. Corrections to NIGHT3 — two of its three "free money" rows were wrong

NIGHT3 §2 listed three paid-for menus needing "routing worked out". Checked
all three against the banked reads and the venues' own pages:

| venue | NIGHT3 said | actually |
|---|---|---|
| **Shellhammer's** | "not live, window not captured cleanly" | **Already fully live with all 10 items** — the 09-04 agent read's 7 *and* the 09-03 hand read's 3, merged, window Mon–Fri 16:00–19:00. Nothing to do. Grounded in the saved page: *"Served Monday thru Friday from 4-7pm"*. |
| **MadMacs** | needs a day found off-site | **Confirmed**: read says *"No days of the week are printed"*, `windows: []`. Genuinely blocked on real-world data. |
| **Slow Hand** | "blocked by the §3 bug" | Not a routing bug — see §0. Its 10-item read is real and banked, but **no happy-hour clock exists anywhere on its own site** (checked the live pages *and* the Next.js boot state, not just the prose). Days Tue–Fri, no time. Same class as MadMacs, mirrored. |

**So the "free money" was one already-done row and two genuinely blocked ones.**
Neither MadMacs nor Slow Hand can publish a window without inventing one.

NIGHT3 §3 said the name collision "needs a person to check the address before
touching this lid". It did not — the roundup's own quote named a different
street, and the PLCB licence, `venue_base`, the venue's site title and its
footer all agree on Slow Hand. Four current sources against one stale 2024
magazine paragraph. Resolved without a visit.

## 3. What is worth the next session

1. **The two windowless reads (MadMacs, Slow Hand) need a day/clock from
   off-site** — Instagram or Facebook, not the main site. Both menus are
   already paid for and banked in `data/deals_agent.json`; only the window is
   missing. This is the cheapest real yield on the board.
2. center_city (18 thin), phoenixville, newark_de (9 thin), exton_downingtown
   (8), west_chester (remaining thin).
3. **Still Paul's call, unchanged:** should James Street Tavern and Timothy's
   Riverfront Grill come off the board (confirmed no current happy hour)?
4. Chain sites stay low-probability — two confirmed-exhausted strikes
   (Deer Park Tavern, Crooked Hammock).

## 4. Housekeeping worth knowing

`~/.claude/.../memory/MEMORY.md` was **over its ~17KB visibility limit before
this session touched it** (≈17.8KB), which means part of it was already at risk
of not being loaded. Trimmed to 17.3KB by cutting dated run-detail clauses that
belong in playbooks, keeping every open blocker. Worth a proper prune pass.

## 5. Standing rules, unchanged

Scoped runs only, one town at a time, never the corpus. "It is live" is one
command: `python tests/live_front_door.py <zone>` — and for a *removal*,
re-fetch the live bundle too; GitHub Pages served the old copy for ~1 minute
after the push. A wrong item is worse than a miss. Check
`git branch --show-current` before committing (repo is shared). Check the
**built bundle**, not a lane's own summary.
