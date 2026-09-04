# Turn budget fixed, one more venue landed, 23 exhausted reads left — 2026-09-04

**Supersedes `HANDOFF-START-HERE-20260904-TIER-B-PAID-OFF-AND-TWO-THIRDS-STRAND.md`
and `HANDOFF-START-HERE-20260904-HAND-READS-PUBLISH.md`.** Both are still true
and worth reading once for the §2 story and the hand-read lane's shape. This
is what one narrow follow-up session did on top of them.

## 0. What was asked, and what happened

Paul: *"See if our current scraper process gets the happy hour items in full
from True Food Kitchen in KoP. Don't hand pull it."* Then: *"Do what's
required then verify it. Where else have we seen this limit stop us?"*

Ran the real lane (`agent_read_venue.py`, not a hand read) against True Food
Kitchen. It exhausted at the hard-coded 14-turn cap on an 8-page chain PDF, 0
items. Two real bugs found and fixed, both in `agent_read_venue.py`:

1. **`MAX_TURNS` was a hard 14, no override.** Now `HHF_MAX_TURNS` env var,
   default unchanged.
2. **The lane's own prompt schema never had `amount_off_usd`**, even though
   every sibling extraction script already did (commit `c6f581c`) and the
   validator already accepted it. "$3 OFF ALL COCKTAILS"-style items were
   silently gated out. Added the field to the prompt.

Both fixes landed on `master` at `1d22a26`. True Food Kitchen re-read clean
(5/5 items) and was published via the `deals_seed.json` route-around.

Then tested whether the fix generalizes: ran one more exhausted venue from
each of the three towns Paul cares about most (Wilmington, Newark, West
Chester), each at `HHF_MAX_TURNS=28`:

| venue | town | result |
|---|---|---|
| **Big Fish Grill on the Riverfront** | Wilmington | ✅ 16 items in 8 turns (well under even the *old* 14-cap — the missing field was this venue's real problem, not turns). Published, live. Commit `f04bf12`. |
| Wrong Crowd Beer Company | West Chester | Correctly resolved `none` — no happy hour anywhere on the site. Not a turn-limit case; nothing to fix or publish. |
| Deer Park Tavern | Newark | **Still exhausted at 29 turns.** A genuine chain-site wandering case (Darden-class), not the schema gap. Unresolved. |

So: **one clean win, one confirmed non-issue, one confirmed-different problem.**
Not every venue on the exhausted list shares a cause.

## 1. What is live right now

Verified with `python tests/live_front_door.py wilmington` (39/39 named live)
and a direct read of `web/data/zone-wilmington.json`:

- **True Food Kitchen** (King of Prussia) — 5 items, Mon–Thu 3–6pm / Fri 3–5pm.
- **Big Fish Grill on the Riverfront** (Wilmington) — 16 items, Mon–Fri 4–6pm.

Both promoted via the `deals_seed.json verified_by: agent_read` route-around
(same pattern as the earlier Lefty's Alley & Eats precedent, commit `327b51a`).

**🔑 Use the newer lane instead, next time.** `data/agent_handread.json` →
`ingest/build_agent_venues.py` → `data/deals_agent_venues.json`, merged at
rank 2 by `build_bundles.py` — settled and proven on 61 venues the same
09-03/04 night, documented in `HANDOFF-START-HERE-20260904-HAND-READS-PUBLISH.md`
and the Knowledge-Graph entry *"A HAND READ CARRIES THE WINDOW..."*. It was not
noticed until after both of tonight's venues were already promoted the older
way — both work, but the newer lane is less hand-typing and is now the
documented standard. Full writeup of tonight's fixes:
`ARCHITECTURE-MENU-INGEST.md`, section *"THE AGENT LANE'S §2 IS SETTLED, AND
ITS OWN TWO GAPS ARE FIXED"*.

## 2. The full remaining-exhausted list — 23 venues, ~$12.42 already spent

Re-surveyed after tonight's fixes and after the 09-03/04 hand-read pass took
most of the original 38 down already:

| zone | count |
|---|---|
| newark_de | 16 |
| wilmington | 4 |
| phoenixville | 2 |
| west_chester | 1 |

Get the current list any time with:

```python
import json
reads = json.load(open("data/agent_reads.json", encoding="utf-8"))
base = json.load(open("data/venue_base.json", encoding="utf-8"))
for lid, rec in reads.items():
    if rec.get("kind") == "exhausted":
        v = base.get(lid, {})
        print(v.get("zone_id"), lid, v.get("plcb_name") or v.get("name"))
```

Newark's 16 (mostly Darden/chain-style sites, same pattern as Deer Park
Tavern) are the bulk of what's left and the most likely to need something
past a bigger turn budget — possibly excluding them outright, per the
standing rule "a wrong item is worse than a miss" and "don't chase a
population that's already shown it won't pay off."

## 3. NEXT SESSION — start here

1. **Don't blanket-run the 23.** One at a time or small batches, same
   discipline as always. `HHF_MAX_TURNS=28` (or higher) per run:
   `HHF_MAX_TURNS=28 python3 ingest/agent_read_venue.py --lids <file> --force --show`
2. **Route any hit through `data/agent_handread.json`**, not
   `deals_seed.json` — it's the documented standard now, one record, done.
   (Omit `items` to rescue what's already banked in `deals_agent.json`.)
3. **After each publish:** `python ingest/build_bundles.py`, full test suite
   (`python -m unittest discover -s tests`, `node --test tests/time_math.test.mjs`,
   `python ingest/validate_pa.py`), commit, push to `master` (only branch that
   deploys), `python tests/live_front_door.py <zone>` to confirm.
4. **Check `git branch --show-current` before committing anything** — this
   repo is routinely shared with concurrent sessions (Codex, other Claude
   sessions). A `git push origin master` from a stale checkout is a silent
   no-op. If in doubt, work in an isolated `git worktree`.
5. Newark's 16 are worth a hit-rate gut check before spending more on them —
   most are chain sites. Consider excluding known Darden/chain domains from
   future `--tier` runs rather than re-buying the same "exhausted" ending at
   ever-higher turn budgets.
6. `MEMORY.md` (project-wide) was flagged over its 17KB limit in an earlier
   handoff — still not pruned, still not this session's job, but worth doing
   soon.

## 4. Standing rules — unchanged

- Scoped runs only, one town (or a short explicit lid list) at a time, never
  the corpus.
- "It is live" is one command: `python tests/live_front_door.py <zone>` —
  never local build, never green tests, never HTTP 200 alone. GH Pages lags
  ~1 min; one `NOT LIVE` is usually just that — re-run before diagnosing.
- A wrong item is worse than a miss. The grounding gate and the human review
  stay, no exceptions.
- Never write a backslash escape through a bash heredoc — use Write/Edit.
- Check the **built bundle**, not the lane's own summary, before believing a
  read reached the board.
- `web/app.js`, `web/index.html`, `web/sw.js` may carry unrelated
  multi-photo-submission WIP from another session/branch
  (`dollar-off-discounts`) — do not touch those three files for this work
  unless explicitly asked; they are someone else's in-flight change.
