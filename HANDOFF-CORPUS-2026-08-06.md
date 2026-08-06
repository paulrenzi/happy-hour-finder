# Handoff — corpus 8 → 100 venues, and photos without a Places key (2026-08-06)

**Live and verified:** <https://paulrenzi.github.io/happy-hour-finder/> — Playwright at
390px against the deployed URL reported `cards 100 photos 70`, kicker
"100 venues · 28 live now", zero page errors, zero ≥400 responses.
Deployed by `gh workflow run pages.yml --ref master` (run 31128773958, success).
Gate at commit `16c24c4`: **53 python + 29 node + validators 8/8**.

---

## What the ask was

> "there's not nearly enough data, so we need to find a way to scrape additional
> deals from websites, google maps or some other site with more info. also, we
> need actual pictures for these places from google maps. none are displaying in
> the cards."

Then, when the previous session stopped short and blamed a missing API key:
**"so fix it, what are you doing. do the fixes and update the live site"** —
i.e. neither the missing key nor an unstarted extraction pass is a reason to stop.

## The two findings that mattered

**1. Scraping was never blocked on extraction — it was blocked on *discovery*.**
The PLCB export has no URLs, so nothing said *where* to crawl. Joining the 2,911
licensees to OpenStreetMap **on address** (never on name — ~37% of PLCB rows carry
a corporate shell, and two "Iron Hill Brewery" rows are two different bars) yields
**691 crawlable websites**, free, ODbL, storable and shippable — the same argument
that made Nominatim the geocoder.

**2. Photos did not need Google Places.** Places photo *bytes* are under a caching
restriction a public git repo cannot honour, and the key isn't in the repo anyway.
Each venue's **own `og:image`** is the picture that venue chose to represent itself
— fetched from the venue, credited to the venue, linking back to it. Falls back to
an in-page image scan for the ~third of these sites predating social-share tags.

## Numbers

| | |
|---|---|
| crawlable sites (OSM join) | 691 |
| crawled | 689 |
| published something quotable | 201 |
| **promoted to a deal** | **93** |
| quote states no schedule | 88 |
| rejected by PA validators | 5 |
| **published corpus** | **100 venues / 26 zones** (was 8 in 1) |
| venues with a photo | **70 / 100** (63 new; 33 from og:image) |
| venues with coordinates | 99 / 100 |

## Files

- `ingest/extract_deals.py` **(new)** — quote → deal promoter. Writes
  `data/deals_extracted.json`, merges OSM centres into `data/venue_coords.json`.
- `ingest/fetch_og_images.py` **(new)** — key-free photo lane. Writes
  `data/venue_photos.json` (exact shape the Places script would have written) plus
  `web/img/venues/*.jpg`. Imports `DELAY, TIMEOUT, UA, allowed` from `crawl_sites`
  so politeness is shared, not re-implemented.
- `ingest/build_bundles.py` — merges extracted behind the seed; `norm_addr()`
  (house number + ZIP) catches the same bar written two ways.
- `tests/test_ingest.py` — `+15` tests: `DealExtraction` (12), `PhotoSourcing` (3).
- `README.md` — pipeline diagram + Status rewritten.

## Rules the extractor enforces (don't relax these casually)

- A quote becomes a deal only with **days AND times AND an unambiguous meridiem**,
  no hedge, and a pass through the same PA validators the build runs.
- **No meridiem at all ⇒ refused, never guessed.** `4:30 - 6:00` is evening to you
  and 4:30am to a parser.
- Meridiem inheritance: `4 - 6 pm` → start inherits `pm`; an inherited meridiem
  that *inverts* the window means it crosses noon (`11 - 2 pm` → 11:00–14:00).
- Day ranges **wrap**: "Sunday - Friday" is six days, not a typo.
- Days stated *after* the time (event listings) are paired only by a bounded
  whole-quote fallback: ≤200 chars and **exactly one** time range, else it'd be a
  guess about which days went with which times.
- Extracted deals ship `confidence: "unconfirmed"`, `verified_by: "auto_extract"`,
  with `source.quote` = the exact sentence. **Seed wins on collision** — a person
  read that page, a regex read this one. They live in separate files on purpose.

## EXIF

`store()` does `Image.frombytes("RGB", im.size, im.tobytes())` — a fresh image
written from **pixels only**, so no EXIF block survives. That line *is*
non-negotiable 5; there is no later scrub pass. Don't "optimise" it into a copy.

## Open / next

1. **30 venues have no photo** — mostly dead domains, self-signed certs, image
   fetch 400s, robots-disallowed images. Not a code bug; see the run log.
2. **Most cards read "Window published without prices."** The bar published the
   window, not the menu. Honest per rule 2. Putting prices on more cards means an
   **LLM extraction pass over the same quotes** — deliberately not built, needs Paul's go.
3. **108 quotable-but-unpublished venues** sit in `data/crawl_hits.json` as
   evidence. A stricter-source pass could revisit them.
4. `chickie-s-pete-s-philadelphia` has no OSM centre (99/100 located).
5. **The README's dead-push-trigger warning may be stale** — a push-triggered run
   (31128175338) succeeded on its own 2026-08-06. Confirm before trusting it; I
   still dispatched by hand.
6. `web/` still has **no map** by design — the README said revisit past ~50 venues.
   **We are at 100.** That call is now live and unmade.

## Reminders

- Test suite is **pure logic, no DOM** — screenshot at a real 390px
  device-emulation viewport for any UI change (headless Chrome clamps window size).
- This repo is standalone: **its own `.env` only**, never `shopify-analytics/.env`.
  Keep operationally separate from Umbrella Arcades' venue prospecting.
