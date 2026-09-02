# Happy Hour Finder — the model has to READ MENUS; nothing built so far does (2026-09-02, night)

**Read this first, then `ARCHITECTURE-MENU-INGEST.md` §"THE MODEL DOES NOT READ MENUS" (the
section just above "Standing rules"), then §"Scoped runs" for the recipe.** Supersedes
`HANDOFF-REACH-PASS-BUILT-20260902.md`, whose "5/5 = 100%" is struck below.

---

## In one sentence

**No model in this pipeline reads a menu and returns its deals — every window and item still
comes out of a regex grammar — so "scrape a town, get 90%+ of the menus regardless of format"
is NOT true yet, and the next session builds exactly that, measured on a town Paul has not
touched.**

## What Paul said closing the session, verbatim

> "have the changes been made that will allow us to scrape a town and get 90+% of the menus,
> regardless of format, if they exist on the website?" — **No.**
>
> "the model needs to read menus. how the fuck am i explaining this basic fact after this much
> work based on a goal that requires them to be read? for restaurants with hours not published,
> all of those photos should be present too, for all towns. … next session we will fix this
> based on 1 and 2, so we do those. daily special are a deal type, and they should be picked up
> and added. they are happy hour items."

## Why the honest answer is no

- `links`, `verdict`, `town` (`ingest/reach_llm.py`) decide *what to fetch* and *whether a
  page says it*. The window is then decided by `windows_from()` (regex). Items come from
  `read_pages_llm` / `extract_prices_llm`, which only see quotes a regex kept. Pictures are
  transcribed, then the same regex reads the transcript. **A phrasing the grammar has not met
  ships nothing, and the run calls that correct.**
- Phoenixville "5/5" is scored against the 5 venues Paul found by hand, each patched for the
  scraper before the number was taken. 8 search candidates are unconfirmed. Five misses to
  date: all five found by Paul after the run, none by the pass before him.
- Daily specials are refused on purpose (`extract_prices_llm.vouched()`,
  `read_pages_llm.worth_reading()`); Sly Fox's card is short because of it.

## Next session — do these, in this order, nothing else first

1. **Blind town.** A small town nobody has opened. Run the recipe as written in
   §"Scoped runs" (town → needy → links → crawl → images `--lids` → verdict → read_pages →
   read_windows → extract/build → photos → rebuild → tests → push → card_diff →
   report_coverage → live_check with the town's names). Then Paul's one minute. The count of
   what he found that the run did not is the baseline. Record it in
   `data/ground_truth/<zone>.json` and in the playbook.
2. **The model reads menus.** A new call over every saved page AND every image transcript of
   each scoped venue, returning structured deals `{kind, days, start, end, items:[{label,
   price}], quote}` where `kind` is one of `happy_hour`, `daily_special`, `food_combo`.
   Grounding: `quote` is a literal substring of the source and carries the days/clock/prices.
   The regex grammar becomes the validator (PA law, >4h = opening hours, price sits in the
   quote), not the reader. Daily specials go on the card as happy-hour items; drop the
   day-specials refusals and let `kind` be the guard against a Margherita-Monday price under a
   happy-hour heading. Acceptance: Sly Fox shows Appy Hour + Wed/Thu/Sat/Sun specials; the
   blind town's misses from step 1 close without a single new regex. Then rerun Phoenixville
   and confirm the 8 candidates.
3. **Photos for every venue in a town, deals or not** — `ingest/fetch_venue_photos.py`,
   ~$0.04 each, inside the recipe, town by town. The no-deal population is ~2,570 corpus-wide
   (~$100); do it per town, never as one sweep.

## State of the repo and the site

- `origin/master` = `6e8b3a2` + this docs commit. Pages deploy green. Live check in WebKit
  (`python scratch/live_check.py phoenixville "Sly Fox" "Rivertown" "Sedona" "Revival"
  "Valley Forge" "Molly"`): 34 cards painted, all six present, 0 page errors.
  🛑 `live_check.py` with no names defaults to KoP names and prints FAIL — pass the town's.
- Full gate at `6e8b3a2`: 372 unit + 64 node + render/search/picker/card, all ok.
- 213 of 214 deal cards carry a photo (Justop: Google returns the apartment block).

## Standing constraints — unchanged

No full-corpus runs; West Chester last, stand-alone; robots obeyed; this repo's own `.env`
(`GOOGLE_PLACES_API_KEY`, `ADMIN_TOKEN`, `SUBMIT_API`); `.new` + `os.replace`; verify in WebKit
at the live URL; a wrong item is worse than a missing one; the model is grounded in code,
never a source.
