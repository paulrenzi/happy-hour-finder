# Happy Hour Finder — the reach pass exists, and Phoenixville measures 5/5 (2026-09-02, evening)

**Read this first, then `ARCHITECTURE-MENU-INGEST.md` §"Scoped runs" (the recipe changed)
and §"REACH, PROVEN BY FOUR MISSES" → "Built the same day".** Supersedes
`HANDOFF-INTELLIGENCE-OVER-EVERY-TOWN-20260902.md`'s "The build, in order" — steps 1 and 2
are built; step 3 ran once.

---

## In one sentence

**A town run now carries three model calls over its reach — which link, whether a page
states a happy hour, what the web says the town has — measured against a per-town
ground-truth list; Phoenixville reads 5 cards over 5 confirmed (100%), and every deal
card on the board has a storefront photo.**

## What Paul said this session, verbatim, and what each became

1. *"https://www.slyfoxbeer.com/phoenixville (the happy hour and daily specials, and its
   not fully represented on the card)"* — the Appy Hour (Tue–Fri 3–6, $2 off apps, $1
   wings) is on the card. **The daily specials are not**, and are the one thing left
   undone: see "Open" below.
2. *"we are still missing a ton of restaurant pictures … google maps has endless pictures
   for all of these places, and we are using that api"* — 33 of 219 board venues had never
   been looked up; `fetch_venue_photos.py --from-board --spend` ($1.29) fixed 31, a
   name-guard loosening (a trade name sitting whole inside Google's name) fixed Sly Fox.
   **213 of 214 deal cards now carry a photo** (Justop is the holdout: Google returns the
   apartment block). The 2,570 no-deal venues draw a tile by design; covering them is
   ~$100 and Paul's call.
3. *"yet another thing the scraper missed: valleyforgepizza.com/happy-hours/ … you're hand
   reviewing these with fable level intelligence. we can't do that. we need this to scale,
   so that when we run through a towns websites, we get everything in one pass."* — the
   build below. Valley Forge is on the board: Mon–Fri 4–6, 14 items, read off its PNGs.

## What was built

- **`ingest/reach_llm.py`** — `links`, `verdict`, `town`. Each is grounded in code: a picked
  URL must be in the inventory shown, a quoted line must be literally on the page, a
  searched venue is a candidate until confirmed. Model never writes a window.
- **`ingest/report_coverage.py <zone>`** — cards ÷ confirmed ground truth. **This is the
  90% number.** Candidates and NOT HELD rows are listed, never counted.
- **`data/ground_truth/phoenixville.json`** — 5 confirmed (Paul's five), 8 candidates from
  the town search, 5 NOT HELD.
- `crawl_sites.py`: reach URLs are depth-1 seeds; a `--lids` run keeps every page it reads.
- `extract_menu_images.py`: `--lids`, `--force`, per-image transcripts, items add not replace.
- `extract_deals.py`: >4 h clock = opening hours (refused before the picture); a picture
  naming the happy hour beats text that does not; `picture_spans` reads every sheet.
- `fetch_venue_photos.py`: name guard accepts the trade name inside Google's name.
- `tests/test_reach.py` (17). Full gate: 372 unit + 64 node + render/search/picker/card, all ok.

## Phoenixville, the run

21 needy → links for 20 → crawl 21 (7 quoted, 10 WebKit renders, 60 pages kept) → 8 images
read → verdict over 29 pages, all "no happy hour" (correct) → read_pages 35 items /
read_windows 0 spans → **2 cards gained** (Valley Forge, Molly Maguire's), 0 lost
(`card_diff`). Funnel: 40 lic / 30 site / 30 crawl / 14 quote / 9 card. Coverage **5/5**.

The 8 candidates are the next human minute, and it is now *aimed*: Bella Trattoria,
Liberty Union, The Country House at Kimberton (no website on file), Bloom Southern Kitchen,
Limoncello, and three that already have cards. Open each, record the URL, flip `confirmed`.

## Open

- **Daily specials on the card** (Sly Fox: Wed $9 growlers / $12 cheesesteak+pint, Thu $12
  burger+pint, Sat $11 mystery pitcher, Sun $2 off Bloody Marys). SPEC has
  `daily_special` and `food_combo`; nothing emits them; the price pass refuses day-specials
  pages on purpose (Revival's $6 margaritas). A new deal type end to end. Paul asked for it.
- The next small town through the same recipe. West Chester last, stand-alone.
- `DEAL_RE` still matches "late night menu"; it made Molly's wrong window possible and only
  the picture rule caught it.
- Verdict runs only over venues with **no** hits; a venue with one bad hit and a good
  unlabelled page is not judged. `--force` covers it by hand.
- The 5 NOT HELD Phoenixville venues: the PLCB base does not have them under any name.

## Standing constraints — unchanged

No full-corpus runs; West Chester last; robots obeyed; this repo's own `.env`; verify in
WebKit at the live URL; `.new` + `os.replace`; a wrong item is worse than a missing one.
