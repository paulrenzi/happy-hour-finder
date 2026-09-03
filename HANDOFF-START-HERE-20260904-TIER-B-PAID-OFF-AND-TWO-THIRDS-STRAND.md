# Tier B paid off, and two thirds of what the lane buys still cannot publish — 2026-09-04

**Supersedes `HANDOFF-START-HERE-20260903-NIGHT-THE-LANE-READS-BUT-CANNOT-PUBLISH.md`.**
Its §2 question is still open. This document is what measuring it did to the question.

## 0. What is live right now

`newark_de` serves **180 items**. Two venues gained items tonight —
Firebirds Wood Fired Grill (11) and Potstickers Asian Grill (24) — both onto
windows they already had. Verified the one way that counts:
`python tests/live_front_door.py newark_de`, then the live bundle re-read for
the two names.

Nothing was published from the agent's windows. **That rule is untouched.**

## 1. 🛑 THE DECISION — §2 is now a measured number, not a judgement call

Paul was asked a/b/c and did not answer (asleep). The night was spent getting
the number that decides it instead. It is worse than the old handoff implied.

Across tier A + tier B, **9 venues returned items. 3 publish. 6 cannot.**

| | venues | items |
|---|---|---|
| published — already had a deterministic window | 3 | 61 |
| **stranded — no window, so no deal to carry them** | **6** | **52** |

Stranded: TGI Fridays (x2 licences), Founding Brothers Restaurant + Pub,
Lefty's Alley & Eats, P.F. Chang's, Plaza Azteca.

> **Two thirds of every venue the agent successfully reads reaches no card.**
> Option **c** ("items only where a window already exists") is not a
> conservative default — it throws away two thirds of everything this lane
> buys, and it means tier B's real yield is 2 in 25, not 7 in 25.

The three options are unchanged and still Paul's. What changed is the price of
**c**, and one hard constraint discovered while trying to build **a** (below).

## 2. 🛑 Option (a) is NOT the cheap one. It was assumed to be.

The old handoff read as though (a) — items on a window-less card — was the
small, safe change. It is the **larger** one:

- `validate_pa.py:173` refuses **any** deal with no window, deliberately:
  *"a deal with no time is not an answer to 'can I go now?'"*. So the board's
  3,097 window-less venues carry **no deal at all** — there is no such thing
  today as a deal that carries items and no times.
- Every item render in `web/lib.js` is `deal.items` (lines 112, 117, 133, 144).
  Nothing reads items off a venue.

So (a) needs a schema change **and** a renderer change. **(b) needs neither** —
an agent window validates and renders today, and the change is confined to
`build_bundles.py`. That is the real shape of the choice:

| | cost to build | what it risks |
|---|---|---|
| **a** | schema + renderer + gate | nothing new; a card with prices and no times |
| **b** | one file | the agent becomes a source of TIMES — and day-banding, "on now" and every sort key off the window, so a bad read moves a venue everywhere, not just on its own card |
| **c** | nothing | 6 of 9 venues, 52 paid-for items, permanently discarded |

## 3. The stranding was worse than diagnosed, and is now audible

The old §2 blamed the sidecar merge sitting inside `for deal in
venue["deals"]`. True, but only half:

**Lefty's Alley & Eats has no row in `deals_seed.json` or
`deals_extracted.json` at all.** It exists only in `venue_base.json`, so it
never reaches `surviving()` and never reaches that loop. Two different ways to
vanish, one silence, and a fix aimed only at the loop would have moved nothing.

`build_bundles.py` now ends with, when it applies:

```
! 52 verified item(s) across 6 venue(s) were READ AND NEVER PUBLISHED
  -- no window means no deal to carry them: TGI Fridays (4), ...
```

Asked at the end against what actually **shipped**, because that is the only
place both failure modes are answerable at once. Control holds: Greene Turtle's
26 items are correctly not flagged. It reports; it does not fix.

## 4. Tier B is a much better buy than tier A — the selector is the finding

| tier | venues read | returned items | hit rate | spend |
|---|---|---|---|---|
| A — a captured, unread menu image | 10 | 1 | **10%** | ~$4 |
| **B — the crawl quoted happy hour on a page** | **25** | **7** | **28%** | ~$8 |

**The crawl having quoted "happy hour" is worth ~3x a captured menu image as a
selector.** Tier A was run first on the theory that a held image is the
strongest evidence; measured, it is the weakest of the two.

Tier C (118 venues, ~$41) is still unbought and should stay that way until §2
is settled — buying reads that cannot publish is the whole problem.

Also seen in the run: **6 of 25 reads ended `exhausted`** (turn-exhausted,
paid, no result). That is a quarter of the spend. Chain sites are the pattern.

## 5. 🛑 Repo state — TWO SESSIONS, ONE WORKING TREE, READ THIS BEFORE COMMITTING

A Codex session worked the fixed-dollar-discount gap in parallel, in the
**same checkout**. It created branch `dollar-off-discounts` and committed to
it. Consequences:

- **The main checkout at `C:\Users\paulm\happy-hour-finder` is on
  `dollar-off-discounts`, not master.** Check `git branch` before anything.
- Two commits of mine landed on that branch first (`f6b1039`, `8c4761b`) and a
  `git push origin master` was a silent no-op — local master had never moved.
  **Nothing was live until they were cherry-picked onto master** as `f845438`
  and `1e181d1` via a scratch worktree, so the shared tree was never yanked
  out from under the Codex session.
- **So my two commits exist twice**: on `dollar-off-discounts` and on master.
  When `dollar-off-discounts` is merged, expect git to drop the duplicates by
  patch-id, or to conflict on `web/data/`. **If it conflicts on `web/data/`,
  take master's side and rebuild** — the board is generated, never merged.
- Codex's change is **not merged** and the board does **not** depend on it:
  all 92 bundles were rebuilt on clean master and compared as parsed JSON —
  **92 identical, 0 differing**. The working-tree churn was line endings only.
- Their handoff owes a board rebuild. `$2 off` / `$3 off` items will not appear
  on any card until someone runs `build_bundles.py` after that merge.

## 6. NEXT SESSION

1. **Settle §2** with the numbers in §1 and the corrected costs in §2 in hand.
   It is still the only thing worth doing first.
2. Merge `dollar-off-discounts` (Paul's call), then **rebuild and push** —
   their fix ships nothing until the board is rebuilt.
3. Only then consider tier C, and only if §2 went (a) or (b). Under (c) tier C
   is buying reads that are 2/3 certain to be discarded.
4. Raise `MAX_TURNS` deliberately for chain sites, or exclude them — a quarter
   of tier B's spend ended `exhausted`.
5. `MEMORY.md` is over its own 17KB limit and still needs the prune.

## 7. Standing rules — unchanged

- Scoped runs only, one town at a time, never the corpus.
- "It is live" is one command: `python tests/live_front_door.py <zone>` — and
  GH Pages lags ~1 min, so one NOT-LIVE is a deploy, not a failure; re-run.
- A wrong item is worse than a miss. The grounding gate and the reviewer stay.
- Never write a backslash escape through a bash heredoc — use Write/Edit.
- 🛑 Check the built bundle, not the lane's own summary.
- 🛑 **Check your instrument saw the thing before believing its zero.** Bit
  twice tonight: a stranding check placed where Lefty's never reaches printed
  nothing, and a bundle comparison fed Windows backslash paths reported
  "0 identical, 0 differing" — an answer of neither.
