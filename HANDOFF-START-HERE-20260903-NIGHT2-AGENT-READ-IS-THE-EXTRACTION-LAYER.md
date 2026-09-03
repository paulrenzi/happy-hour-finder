# Handoff — agent_read_venue.py proven on the known failure cases, two real
# publish-pipeline bugs found and fixed, live

**Branch: `menus30`, fast-forward-merged into `master` and pushed. `git log
origin/master -1` should show `23bb04c` or later.**

## What Paul actually asked, and what changed as a result

Paul's real question this session: if the deterministic text extractor keeps
losing to PDFs, images, JS-rendered content, and a click deeper, why is it
still the primary path for reading a menu, instead of `agent_read_venue.py`
(one Sonnet call per venue, WebFetch+Read+curl, the tools a person uses)?

The honest answer, and it's now settled, not theoretical: **the extractor's
job is discovery (does a site exist, does it mention a happy hour) —
extraction should go straight to the agent reader.** Proof, not assertion:

Ran `agent_read_venue.py --force` against the two venues flagged
image/PDF-blocked in an earlier session and never revisited:

| Venue | Before | After (agent read) |
|---|---|---|
| La Porta Ristorante (page menu, no PDF/image at all — a plain HTML page the extractor never followed to) | 1 item | 8 items |
| Sedona Taphouse x3 (PDF menu) | 1-2 items each | 18 items each |

Cost: $1.74 for 4 venues (~$0.44 avg, matches the existing 40-venue average of
$0.43/venue from `data/agent_reads.json`). At 3,479 venues total, running
every venue that Layer-1 crawling confirms has a site + a happy-hour mention
through the agent reader instead of the regex extractor would cost roughly
$1,500 — real money, but the regex pass isn't free either: every miss it
produces gets caught by a person and re-read anyway, which is strictly worse.

**I started building a regex-based "image/PDF menu" detector
(`ingest/detect_image_pdf_menu.py`) before Paul redirected me — deleted,
never committed. It would have been patchwork on the wrong layer: solving
Layer 4 (image/PDF detection) with more regex when the actual fix is routing
extraction to the agent reader in the first place.**

## Two real bugs found proving this out, both fixed, both live

Getting the 4 known-failure venues' richer reads to actually reach
`web/data/` (not just `data/deals_agent.json`) surfaced two independent bugs
in `ingest/build_bundles.py`'s sidecar-merge logic — **the same shape of bug
that quietly ate hand-read work before, just not caught until now**:

1. The agent-items sidecar only overrode an existing deal when that deal's
   `verified_by` was exactly `auto_extract` AND it had zero items. A venue
   that already had even 1 thin item — whether from `auto_extract` or a
   prior `agent_read` — could never pick up a strictly richer re-read.
   Fixed: also allow `verified_by == "agent_read"`, and allow override when
   the new read is strictly bigger (`richer = len(extra) > len(existing)`).

2. Separately, `extra = prices.get(slug) or agent_items.get(lid)` picked
   whichever sidecar was merely non-empty *first* — so La Porta's fix from
   bug #1 still didn't ship, because `deals_prices_llm.json` had its own
   1-item entry for the same venue's slug, sitting in front of the 8-item
   agent read. Fixed: take whichever sidecar actually has more items.

Both are commits on `master` now (`c4bf6f0`, `ba54e20`). **If a future
session re-reads a thin venue and it still doesn't ship, check this merge
logic in `build_bundles.py` before assuming the read itself failed** — the
read can be correct and sitting unused in a sidecar file.

## Verified live, bytes read, not just a green Action

```
La Porta Ristorante (64766, newtown_square_broomall):  9 items (was 1)
Sedona Taphouse (118439, newtown_square_broomall):     20 items (was 2)
Sedona Taphouse (91502, phoenixville):                 26 items (was 1)
Sedona Taphouse (101577, west_chester):                19 items (was 2)
```
Pulled from `https://paulrenzi.github.io/happy-hour-finder/data/zone-*.json`
directly after `gh run view` showed the deploy job complete — not inferred
from the Action status.

`data/RESCRAPE-QUEUE.json` dropped 147 -> 138 as a direct result.

## Next step

The reframe from this session should change how future rounds are run, not
just this one: **for a venue Layer-1 already confirms has a site and
mentions happy hour, go straight to `agent_read_venue.py`, don't run the
extractor as the first pass and fall back only when a person notices it's
thin.** The RESCRAPE-QUEUE backlog (138 venues, still ranked by zone count in
the queue file) is the concrete list to work through that way next.

**Every round ends with the "Publishing a branch's work" sequence in
`README.md` — do not skip the live-JSON read at the end.**
