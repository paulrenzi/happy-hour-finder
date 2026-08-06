# Happy Hour Finder — King of Prussia, PA

**Live: <https://paulrenzi.github.io/happy-hour-finder/>**

> A live answer to *"where can I go in the next 30 minutes, and is the deal actually still on?"*

A mobile-web PWA covering the ~20-mile disc around King of Prussia. No framework,
no build step, no runtime CDN — the whole site is static files in [`web/`](web/),
and the "what's live right now" math runs client-side over a cached bundle, so it
works with no signal in a parking lot or a basement bar.

**This is a standalone project.** It shares no code, credentials, or deploy
pipeline with anything else. Its `.env` lives in this repo only.

---

## How it works

```
data/zones.json          38 named drinking districts — the zone map, hand-maintained
   ↓ ingest/seed_plcb.py  filter the statewide PLCB export to the disc, assign a zone
data/venues.csv          the denominator: 2,911 licensees, 2,908 in a zone (gitignored,
                         regenerate it — zones.json is the source of truth)
   ↓
data/deals_seed.json     the hand-verified corpus — 8 venues, read off the page by a person
   ↓ ingest/discover_sites.py     join the licensees to OSM on address → 691 websites
   ↓ ingest/crawl_sites.py        robots-honouring crawl → data/crawl_hits.json (quotes, not deals)
   ↓ ingest/extract_deals.py      quotes → data/deals_extracted.json, 93 venues
   ↓ ingest/fetch_og_images.py    each venue's own og:image → web/img/venues/
   ↓ ingest/geocode_venues.py     OSM/Nominatim, no key, ODbL (results are storable)
   ↓ ingest/validate_pa.py        PA Acts 57 & 86 of 2024 — a failing deal never ships
   ↓ ingest/build_bundles.py
web/data/*.json          per-zone bundles, ~10–20KB gzipped
   ↓ GitHub Actions (.github/workflows/pages.yml)
GitHub Pages             web/ only; ingest scripts and raw data stay off the site
```

In the browser, [`web/lib.js`](web/lib.js) holds **all** pure logic — feed assembly,
ranking, freshness decay, time math — and is the part under test.
[`web/app.js`](web/app.js) only paints the DOM. Keep that split; it is the reason
the logic is testable without a browser.

### Two rules worth knowing before you change anything

**Ranking is on *usable* minutes** (`until − drive`, capped at ~2h), with driving
weighted above deal-time. Sorting live deals by least-time-remaining — the naive
reading of "urgency" — puts on top the bar you have the least chance of reaching.

**The feed never dead-ends.** It searches forward up to 7 days. Before that it was
blank roughly 18 hours a day, which is most of when a person opens it.

---

## Running it

```sh
# the site — any static server, no build
python -m http.server -d web 8000

# the gate (what CI runs; the deploy is blocked on it)
python -m unittest discover -s tests
node --test tests/time_math.test.mjs      # needs node 22 for ESM + node --test
python ingest/validate_pa.py
python ingest/build_bundles.py            # web/data must not drift from the seed
```

⚠️ **Pushing does not currently deploy.** Since 2026-08-01 a push to `master`
stops creating a workflow run — the commit lands on GitHub and nothing fires, so
the live site silently stays on the last build (the 08-06 redesign sat
unpublished this way). Actions itself is fine: `gh workflow run pages.yml --ref
master` runs the gate and deploys normally. **Check the live site after a push,
and dispatch by hand until the trigger is fixed.**

The test suite is **pure logic and touches no DOM** — it cannot catch a markup or
layout regression. Screenshot the render at a real 390px viewport instead
(headless Chrome clamps window size, so a device-emulation viewport is required,
not a resized window).

---

## Design

The UI mirrors the [cenote-map](https://paulrenzi.github.io/cenote-map/) visual
language: cream `#f7f3eb` page, teal `#0a8a9e` accent, Fraunces display over
Manrope, photo hero → control band → kicker+headline section → support band.

- **Fonts are self-hosted** in [`web/fonts/`](web/fonts/) (latin-subset variable
  woff2, SIL OFL) and precached in `sw.js`, specifically so the look costs nothing
  in offline capability. See [`web/fonts/README.md`](web/fonts/README.md).
- **The control strip is not sticky, and the phone hero is capped at 52vh.** An
  editorial hero plus four rows of controls pushes the first deal off the first
  screen, which is the entire job of the page.
- **There is deliberately no map.** At 8 venues a sorted list beats one, and a map
  would cost the repo its first CDN dependency. Revisit past ~50 venues.

Phone is the target; desktop is the courtesy fallback. Tap targets ≥44px, single
column, one-shot geolocation on an explicit tap only.

---

## Non-negotiables

1. Never display a deal that fails a PA legal validator — it is bad data by definition.
2. Never render a claim the source didn't make.
3. Always show verification age and link the source. Deals **decay**; they never silently vanish.
4. Honor `robots.txt`; rate-limit crawls to something a small restaurant's shared host won't notice.
5. Strip EXIF from every stored image. Never background-track location.
6. No paid placement in the "right now" feed, ever.
7. No login to browse, no login to submit a photo.

## Status

**The corpus is 101 venues across 26 zones**, up from 8 in one.

Scraping was never blocked on extraction — it was blocked on *discovery*. The
PLCB export has no URLs, so nothing said where to crawl. Joining the 2,911
licensees to OpenStreetMap on address (never on name: ~37% of PLCB rows carry a
corporate shell, and two "Iron Hill Brewery" rows are two different bars) yields
**691 crawlable websites** for no fee and no licensing risk — ODbL results may be
stored and shipped, the same argument that made Nominatim the geocoder.

Of those, 201 published something a crawler could quote and **93 stated a
schedule specific enough to publish**. The gap is the point: a quote is only
promoted to a deal when it carries both days and times, an unambiguous am/pm, no
hedge, and it passes the PA validators — everything else is kept as evidence in
`data/crawl_hits.json` rather than guessed at. Machine-extracted deals ship at
`unconfirmed`, carry the sentence they came from in `source.quote`, and live in
their own file; the seed is what a person read, and merging them would lose the
only thing that distinguishes them.

**Prices are read from those same quotes, and never anything else.**
`ingest/extract_prices_llm.py` puts a language model over the text a deal was
already built from, because a bar that writes "drafts are five dollars" publishes
a price the regex cannot see. It is bounded by two rules. It touches **prices
only** — days and times stay with the deterministic extractor, so the
"no meridiem ⇒ refused, never guessed" guarantee is untouched. And every item it
returns carries the exact span it was read from, which is checked against the
quote *in code*: an item whose price is not literally in the venue's own sentence
is dropped before it reaches a card. It runs on `claude -p` (the subscription
already on this machine, not an API key this repo doesn't have), in batches,
because that call carries a large fixed prompt before it reads any of ours.

**Photos come from each venue's own og:image**, not Google Places — the Places
key isn't in this repo and its photo bytes are under a caching restriction a
public repo can't honour. Every image is decoded and re-encoded from pixels,
which is what actually drops EXIF (non-negotiable 5). The venue's own site is
always checked against its robots.txt; an image it hosts on a builder's CDN is
fetched as an embedded asset of a page we were allowed to read — the call a link
preview makes — because that CDN's robots.txt is about crawling the CDN and must
not be able to hide a bar from its own listing.

**94 of 100 venues carry a photo.** The last six are six different causes and
none of them is a bug: two Chili's pages offer only 210x140 thumbnails, two
venues publish no fetchable image at all, one site would not connect, and
Barnaby's of West Chester disallows us in robots.txt — so it stays photoless.

Still true: ~80% of bars never publish a happy hour anywhere, so the photo lane
(photograph a table tent → vision extract → validate → publish) remains the only
path to covering half the area.

Background: [`SPEC.md`](SPEC.md) · [`HANDOFF-START-HERE.md`](HANDOFF-START-HERE.md)
· [`PHASE-0-FINDINGS.md`](PHASE-0-FINDINGS.md) · the dated `HANDOFF-*.md` files are
session notes, newest wins.
