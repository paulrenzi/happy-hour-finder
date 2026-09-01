# Handoff — prices are paired, the model pass is 2.8x cheaper, next stop Wilmington

**Written 2026-09-01. HEAD `678b7dd`, pushed, CI green, live board verified in WebKit.**

---

## 🛑 START THE SESSION LIKE THIS

**Open with ONE plain-English sentence — no jargon, no file paths — saying what we are
trying to achieve. Say it to Paul, not to yourself.** Then get to work.

---

## What is true right now

The board is live at `https://paulrenzi.github.io/happy-hour-finder/` with **169 cards
painted and zero page errors**, confirmed by running it in WebKit, not by an HTTP 200.

Two things shipped this session.

**1. The crawler now knows which item a price belongs to.** It used to glue a bare price
to *both* its neighbouring lines without recording which side the dish was on, so 40
venues had visible prices we refused to publish. The text genuinely cannot answer the
question — CO-OP's `$8` belongs to the dish above it, Chili's `$3` to the one below. The
**markup** answers it: one box on the page is one menu item. `ingest/crawl_sites.py` now
parses with `html.parser.HTMLParser` (`_Lines`), records each line's ancestor element
chain, and `item_beside()` walks up from the price to the smallest enclosing box that
holds another line. A box bigger than `ITEM_BOX_LINES` (8) **refuses rather than guesses** —
unpriced is the right answer to a question we cannot answer.

**2. The sampling against real pages caught a second, bigger bug — and the green test
suite had not.** `items_from_hits` joined every quote with a space before parsing, so
`Beef Quesadilla $7` + `Blue Moon draft $4` was read as `$7 Blue Moon draft`. **35
published items across 20 venues were priced across a quote boundary, live and wrong.**
Fixed by reading one quote at a time plus an end-anchored `TRAILING_PRICE_RE`.

Net: **52 → 65 priced venues, 140 → 168 items**, plus corrections to prices that were
already wrong on the live board (Great American Pub Blue Moon $7→**$4**, Fairmount Jai
Alai $9→**$7**, Mahou $7→**$6** — all three re-read out of the deployed zone bundles).

**3. The model pass costs 2.8x less for the identical items.** Measured, not guessed —
see the cost section below.

`bash tests/run.sh` is green: **233 Python + 64 JS**.

---

## 🎯 What Paul wants next, in order

1. **Switch the price pass to Sonnet.** *This is already done and committed* —
   `MODEL` defaults to `sonnet` in `ingest/extract_prices_llm.py`. Confirm it, don't redo it.
2. **A more targeted pass over the 15 miles around King of Prussia.**
3. **Then Wilmington, DE, and 15 miles around it.**

### On (2) — read this before touching anything

**The radius already exists.** `data/zones.json` carries `origin` (King of Prussia,
40.089 / -75.396) and `radius_miles: 20`; `ingest/seed_plcb.py` filters on it and stamps
`miles_from_kop` onto every row of `data/venues.csv`. **1,561 of the 2,955 seeded venues
are already inside 15 miles.**

🛑 So a "15-mile pass" needs no new data — it is a filter over what is on disk. But note
that changing `radius_miles` 20 → 15 **removes** venues. If the intent is to work the near
ring *harder* (deeper crawl, more effort per venue, the `NOUNS` gap below), filter the
**work queue**, do not shrink the corpus. **Ask Paul which he means if it is not obvious
from his wording** — the two produce opposite boards.

### On (3) — 🛑 the important one

**Crossing into Delaware changes the LAW, not just the data source.** Two independent
Pennsylvania assumptions are baked into the pipeline:

- **Licence data.** `seed_plcb.py` is built entirely on the Pennsylvania PLCB
  active-licensee export (statewide CSV, ~15MB, no auth), and `counties_in_scope` is five
  PA counties. There is not a single Delaware row anywhere in this pipeline. DE publishes
  through its own Division of Alcohol and Tobacco Enforcement.
- **Legality.** `ingest/validate_pa.py` encodes *Pennsylvania* liquor law and **every
  deal is gated on it**: a `BANNED` list (all-you-can-drink, bottomless, 2-for-1,
  unlimited, free drink), `MAX_HOURS_PER_WEEK = 24.0`, a midnight cutoff, and a **2
  food+drink combos per day** cap. Those numbers are PA's, not DE's.

🛑 **Running DE venues through the PA validator is a correctness hazard in both
directions** — it can suppress a lawful DE deal and, worse, publish one PA would have
banned. **The validator must become per-jurisdiction before a single Delaware venue is
published.** That is the first task of the Wilmington work, ahead of any crawling.

This is the nationwide expansion problem in miniature: **the real cost of going national
is data engineering and per-state law, not model tokens.**

---

## The cost work, and the two findings that reverse the obvious answer

**The `claude -p` agent harness costs more than the model does.** A nine-token prompt
billed **28,272 input tokens**; ~97% of the price pass was boilerplate. Fixed with flags,
not prompts — `LEAN_ARGS` in `extract_prices_llm.py` (`--setting-sources ""`,
`--exclude-dynamic-system-prompt-sections`, an explicit `--system-prompt`,
`--disallowed-tools`), mirrored into `extract_photo_deals.py`. ~3x off the fixed cost.

Bake-off on 40 real venues:

| config | in | out | items | $ | $/item |
|---|---|---|---|---|---|
| opus, full harness, batch 8 (before) | 207,355 | 3,954 | 54 | $0.7564 | $0.0140 |
| opus lean batch 20 | 39,503 | 9,767 | 56 | $0.3540 | $0.0063 |
| **sonnet lean batch 20 (shipped)** | 39,703 | 18,481 | 54 | **$0.2660** | $0.0049 |
| haiku lean batch 40 | 19,390 | 27,273 | 46 | $0.1489 | $0.0032 |

🛑🔑 **A smaller model is not automatically cheaper, and raw tokens are the wrong unit.**
Haiku spends its input saving back as output (67,624 out vs Opus's 8,261); at batch 8 it
costs *more in total tokens* than Opus, and at batch 40 Opus beat Haiku on raw tokens
**and** recall simultaneously. On a Max plan Opus is metered far more heavily than Haiku,
so read **`total_cost_usd`** off the JSON envelope — it reorders the ranking. Judging on
input tokens picks the worse config.

🛑🔑 **Cheap-model recall is not stable enough to plan on.** Identical config, three runs:
**55 / 45 / 46** items. Haiku's remaining ~1.8x saving was declined for that reason.

🔑 **Batch size is the dominant lever**, because it amortises the fixed harness cost.
Both knobs are env-overridable: `HHF_PRICE_BATCH`, `HHF_PRICE_MODEL`.

🔑 **The cheapest tokens are the ones the deterministic pass makes unnecessary.**
`build_bundles.py:340` consults the model sidecar **only** where the free pass found
nothing (`and not deal.get("items")`), so every crawler improvement both adds accuracy and
removes model calls. The crawler and extractor are stdlib Python: **zero tokens for 929
venues.** A cheaper model also cannot publish a wrong price — `verify()` requires the price
to appear literally in the venue's own text — so the only thing a cheap model can cost is
recall, which is exactly what the bake-off measures.

---

## ⏳ The next real block (flagged, not touched)

**The `NOUNS` whitelist in `ingest/extract_deals.py` is now the limiting gate, not the
pairing.** Of 115 correctly-paired quotes measured mid-crawl, **23 were dropped** by it —
`$3 Bud Light 16 oz`, `$8 Pimento Cheese Dip`. Chili's now pairs all five of its prices
correctly and publishes **one**. This is a different block from the one just fixed and I
deliberately did not touch it. It is probably the cheapest remaining win on the KoP board.

---

## House rules that cost previous sessions time

- 🛑 **A web page is verified by RUNNING it**, never by an HTTP 200. Assert cards painted
  and **zero `pageerror`**, in WebKit — `node --check` has passed a file no browser could parse.
- 🛑 **Sample the output against the real pages before publishing.** The green suite did
  not catch the 35 wrong prices; sampling did. A fixture that is *flat* makes every line a
  sibling and hides the whole mechanism — fixtures must carry the real pages' **nesting**.
- 🛑 This repo has **its own `.env`**. Never read `shopify-analytics/.env` for it.
- Publishing flow: `sync_approved.py` → `extract_deals.py` → `build_bundles.py` →
  `bash tests/run.sh` → commit/push → `gh run list -L 1` → WebKit check.

## Files that changed this session

- `ingest/crawl_sites.py` — `_Lines` parser, `text_lines()`, `item_beside()`, `quotes(stacks=)`
- `ingest/extract_deals.py` — per-quote reading, `TRAILING_PRICE_RE`
- `ingest/extract_prices_llm.py` — `LEAN_ARGS`, `BATCH` 8→20, `MODEL` opus→sonnet
- `ingest/extract_photo_deals.py` — lean flags
- `tests/test_ingest.py` — `WhichSideOfTheJoinTheItemIsOnIsREADOFFTHETREE` (6 tests)
