# Happy Hour Finder — intelligence over every town, and a 90% that has a denominator (2026-09-02)

**Read this first, then `ARCHITECTURE-MENU-INGEST.md` §"REACH, PROVEN BY FOUR
MISSES" and §"THE WHOLE FUNNEL".** The previous handoff
(`HANDOFF-REACH-IS-THE-GAP-20260902.md`) still holds; this one supersedes its
"what is left" ranking.

---

## In one sentence

**A scoped Phoenixville run called the town empty and Paul found four
published happy hours in one minute; every miss was reach, all four are fixed
and on the live board, and the next build is to make the machine do that
minute — an LLM over each town's reach, measured against a per-town list of
venues that actually publish a happy hour, target 90%.**

---

## The goal, in Paul's words (2026-09-02)

> *"when we run a scrape over a town, we need to be running intelligence over
> it as part of our process, and get to 90% coverage on restaurants that
> actually have happy hour menus."*

---

## What happened this session — read before touching the crawler

Paul's four URLs, all Phoenixville, none with a real card after a run that
reported "both refusals correct":

| venue | published where | why we missed it | fixed by |
|---|---|---|---|
| Revival Pizza Pub | `/happy-hour-menu`, menu is `Revival HH.png` | image regex wanted `_hh_`; URL was `%20HH.png`; card carried **$6 margaritas** from Margherita Monday | standalone `hh` token + unquote; day-specials URLs refused by `vouched()` and `worth_reading()`; stale sidecar rows deleted |
| Rivertown Taps | `Happy-Hour-Specials.png` on `/menu/` | images only collected on hour-named URLs; venue has **no text at all** | self-named HH image counts on any page; transcript sidecar `data/menu_image_transcripts.json`; `extract_deals.picture_spans()` runs the unchanged window grammar over the picture's HH lines |
| Sly Fox | `/phoenixville`, "Appy Hour" Tue–Fri 3–6 | link named the town, not an hour; "appy hour" ≠ "happy hour"; the Saturday line under the block joined the quote | `town_re()` ranks the own-town link first; "appy hour" heading; a day line **above** a heading owns it |
| Sedona Taphouse | `/locations/phoenixville-pa/` + HH PDF | town link dropped, then displaced by three `nye-special` sitemap URLs; anchor 220 chars > 120 cap; `$20 Oﬀ` ligature read as $20 | town link survives the top-up; anchor cap 400; NFKC on PDF text |

Live, in WebKit at `https://paulrenzi.github.io/happy-hour-finder/#z=phoenixville&f=all`:
32 cards, 0 page errors; Revival 4pm (10 items, no margaritas), Rivertown 3pm
Wed–Fri (5 items), Sly Fox 3pm ($2 off apps, $1 wings), Sedona 4pm (24 items).
`scratch/live_check.py` is that check; it is the gate that counts.

**Every one of these was to the LEFT of the funnel.** The funnel, `needy.py`,
the hole report and the render gate all measure what we fetched. A page never
fetched is invisible to all of them. That is the process defect, and it is why
regex-by-regex fixes will keep losing: each miss teaches us one more pattern.

**Left on purpose:** 16 venues corpus-wide have price sidecars built only from
day/weekly/lunch-specials quotes (VK Brewing, Chap's, Cracker Barrel, Blue Dog
among them). `--reverify` does not apply `vouched()`; a scoped recrawl of each
town will. No full-corpus run — standing rule. Cosmetic: Sedona shows a
duplicate `house wine by the glass and $7.9` beside the clean item.

---

## Phoenixville, measured off disk right now

```
python ingest/report_funnel.py phoenixville
zone           lic  site crawl  ok  quote  card  card/quote
phoenixville    40    30    30   28     13     8      62%
python ingest/needy.py phoenixville --show      # 21 needy, every one "no deal"
```

10 of 40 licensees have no website on file at all. 21 crawled venues have no
deal. **Nobody can say what fraction of "the ones that actually have a happy
hour" the 8 cards are, because that list does not exist yet.** Building it is
step 1 below, and it comes before any percentage is quoted.

---

## The build, in order

### 1. The denominator — `data/ground_truth/<zone>.json`

"Restaurants that actually have happy hour menus" is not the PLCB list
(Starbucks, Chipotle, a catering firm are on it) and not the crawled list
(Sedona was crawled and missed). It is a **per-town list built the way Paul
built it**: web search for "<town> happy hour" + venue-name searches + a human
minute per hit. Each row: venue (LID if we have one, else name + address), the
URL that states the happy hour, the date checked, who checked. Start with
Phoenixville's four; a town's list is built *before* the run, not after.

`ingest/report_coverage.py <zone>` = cards ÷ ground truth, naming each miss.
That number is the one Paul asked for. 90% is the bar.

### 2. Intelligence over reach, not reading — three model calls per town run

The reading half converts 86% of quoted pages. Spend the model where the misses
were:

- **Link picker.** For each venue, hand a model the link inventory (homepage
  anchors + sitemap: text and URL, ~100 lines, text-only) and ask which is the
  happy-hour page or menu, and which is the location page for *this* town.
  Returns URLs to queue ahead of `candidate_links()` ranking. Replaces the
  one-pattern-per-miss growth of `LINK_WORDS`/`town_re`. One small call per
  venue; a town of 30 sites is 30 calls.
- **Page verdict.** `DEAL_RE` is a regex for "happy hour"/"appy hour". A model
  over the fetched visible text answers *does this page state a happy hour,
  and quote the line* — so a venue's own vocabulary ("Appy Hour", "Social
  Hour", "Bar Bites 3–6") stops being a miss. Grounded on a verbatim quote,
  same rule as every other model call here.
- **Town search.** Search results for "<town> happy hour" compared against the
  venues and URLs we hold. Anything not matched is written to the hole report
  as *published, not reached* — the class none of our instruments can see
  today. This is also how ground truth gets seeded.

Cost is the number of calls, not the model size. `read_pages_llm.py` shows the
pattern (sonnet, batched, verbatim-grounded, `--lids` scoped).

### 3. Run Phoenixville again with 1+2 in place, then the next small town

Same scoped recipe (`ARCHITECTURE-MENU-INGEST.md` §"Scoped runs", now with the
image pass and the human-minute stage). Report coverage against ground truth.
West Chester stays untouched until the small towns are good.

### 4. Still worth doing, from the previous handoff

Store the visible line count in `crawl_hits.json` (separates "read it, no HH"
from "read nothing"); cross-domain ordering hosts; a licence-class filter so
recall numbers stop counting Starbucks.

---

## State of the tree

- happy-hour-finder `master`: `9a1c861` the fixes (355 tests, exit 0),
  `1a40f4b` handoff, then this session's docs commit. Pushed. Live verified.
- umbrella-arcades: `Knowledge-Graph.md` entry for 2026-09-02 (HHF) at the top.
- Memory: `feedback_a_run_that_calls_a_town_empty_is_checked_against_one_human_minute.md`.

## Standing constraints — unchanged

- No full-corpus runs; a run names its towns, `needy.py` names the venues.
- West Chester last, stand-alone.
- Robots.txt obeyed; the recorded override was misattributed and is retracted.
- This repo's own `.env`, never `shopify-analytics/.env`.
- A page is verified by running it in WebKit at the live URL, never by a 200.
- Write `.new` then `os.replace`. Never commit `.env`, tokens, credentials.
- One plain-English sentence first. A wrong item is worse than a missing one.
