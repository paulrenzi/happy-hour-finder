# START HERE — 2026-09-02, night. The shell capture is built and live.

**This supersedes every earlier handoff, including
`HANDOFF-START-HERE-20260902-SLIDER-AND-SCRAPING.md`.** Nothing is mid-flight.
Read §1, then §5 before you touch anything.

---

## 1. What happened this session, in one paragraph

Paul named two venues we crawl and publish nothing useful for. One
(`twostonespub.com/happyhour`) was a wrong-price defect, fixed and shipped
earlier in the day. The other (`mcglynnspub.com/food-and-drink-specials`) is a
**JavaScript shell** — 22 visible lines, the whole happy hour sitting in a JSON
blob the page hands its own client. I started a fifth per-platform adapter for
it. Paul stopped that: *"you're making all of these tweaks to a python bot, but
the simple fact is it takes an AI model to review the sites one by one."* He
then asked why this was not already built, given the hours behind us. **It had
been found four times before and answered narrowly every time.** This session
built the general answer, measured it before building, and shipped it.

## 2. The finding you must not re-learn

🚨🔑🔑 **A SHELL IS NOT A SUCCESS.** A page we cannot see into used to file as
`ok, 6 quote(s)` and became invisible. `lines` was recorded per page on 09-01
(`1a2e2aa`) and **nothing ever refused on it** — an instrument, not a gate. That
is the whole reason the same finding was re-made in four sessions.

> 🔑 **A measurement that nothing gates on does not change an outcome. Name the
> number that has to move, and put the refusal in the same commit.**

The four narrow answers, and why each fell short, are in the table at
**`ARCHITECTURE-MENU-INGEST.md` → "A SHELL IS NOT A SUCCESS"** (last section).
Read it before proposing any new adapter.

## 3. What is built

**`ingest/crawl_sites.py`**

- `SHELL_FLOOR` (= `RENDER_LINE_FLOOR`, 40). One concept, one number, shared
  with `report_holes.py`.
- A page under it now prints
  `shell: 22 lines, 121 string(s) recovered from embedded JSON` instead of `ok`,
  and its row carries `shell: true` / `embedded: N`. **This count is the metric.**
- `embedded_json_lines(html)` — finds every `= {`, lets `raw_decode` find the
  object's end, walks it for strings, drops URLs / hex colours / paths / single
  words. **No platform knowledge whatsoever**, and none may be added.
- 🛑 The strings **never** reach the regex quote passes (they would fabricate
  deals). They are appended to the saved page under
  `[the page's embedded data, not visible text]`. **Capture is general and dumb;
  judgement belongs to `read_menus_llm.py`.**
- `save_page(..., embedded=)` records `visible_lines` and `embedded` counts.
- The keep rule widened: a shell is saved even when its visible text never says
  the words.

**`tests/test_ingest.py`** — `APageThatShipsItselfToItsOwnJavaScript`, 5 tests,
including the one that holds the containment line.

**`scratchpad/size_shells.py`** — the free sizing pass. No model, no spend.

## 4. What it measured and what shipped

| | |
|---|---|
| shell venues in the corpus | 100 (80 of them silent) |
| carrying a window or price in embedded JSON | **14** — a floor, the filter is keyword-based |
| McGlynn's, the venue Paul named | recovered, all three branches |
| pages now carrying embedded data | 39 |
| deals the model grounded from them | 13 |
| board | **314 published windows**, full suite green |

🛑 **The first sizing run reported "0 of 100" and was wrong.** `urllib_get()`
returns a `_Plain` object, not a string, so an `isinstance(html, str)` guard
silently discarded every fetch. Caught only by asking whether the instrument saw
anything at all (`visible_max == 0` for all 100). **Check that your instrument
saw the thing before you believe its zero.**

## 5. Standing rules — still in force

- 🛑 **Never run two crawls at once.** No `git merge`/`pull` during a crawl.
- 🛑 **Scoped runs only, never the corpus.** `--lids` or `--zone`.
- 🛑 **"It is live" is one command:** `python tests/live_front_door.py <zone>`.
  One NOT LIVE is GitHub Pages lag — re-run before diagnosing.
- 🛑 **A `web/` edit ships nothing until `build_bundles.py` restamps `sw.js`.**
  Never hand-edit `sw.js`.
- 🛑 **Never write a backslash escape through a bash heredoc** — use Write/Edit.
- 🛑 `open(p, "w")` truncates before `write()` — write `.new` + `os.replace`.
- 🛑 HHF uses its own `.env`. No `ANTHROPIC_API_KEY` in it; never borrow another
  repo's.
- **Pull before push** — Codex works in this repo too.

## 6. What is open, in the order I would take it

1. **The other 86 shells.** 14 of 100 carried a window under a keyword filter.
   The model sees every string, so the real number is higher. Run the model pass
   over all 100 shell lids, not just the 14 — roughly a few dollars, once.
   Regenerate the lid list with `scratchpad/size_shells.py` (it writes
   `shell_sizing.json`) or straight off `crawl_hits.json` where
   `max(p["lines"]) < 40`.
2. **Make the shell count a run-level line.** Right now the verdict is per page.
   The crawl summary should end with `N shell page(s), M with embedded data` so
   the number is visible without a script.
3. **Upper Darby discovery** — the town's wall is discovery, not extraction:
   6 of 71 licences sited, ~$2 to fix. Untouched.
4. **Remaining §4a Codex ideas** not formally reviewed: render-on-blocked-fetch
   retry, `extract_deals.py --lids`, `needy_lids(only=)` in `read_windows_llm`.
   Responsive-image dedupe was measured (471 → 146 unique) and is real.
5. **`MEMORY.md` is over its 17KB limit.** Paul's call, left alone.

## 7. Cost posture (asked and answered this session)

The model never reads the corpus. Capture is stdlib Python, zero tokens for all
798 crawled venues, and `build_bundles.py` consults the model sidecar only where
the free pass found nothing — about 12% of venues. **Sonnet**, batched, with
`LEAN_ARGS`: Haiku was rejected on unstable recall (55/45/46 items across
identical runs) and Opus found the same items at 2.8x. A new town is under a
dollar. Detail in `project_hhf_llm_pass_cost_architecture` and
`HANDOFF-PRICES-COST-20260901.md`.

Accuracy is not on the model's word: `verify()` requires every price to appear
literally in the venue's own captured text, and `tests/run.sh` checks every
published window against its own quote.
