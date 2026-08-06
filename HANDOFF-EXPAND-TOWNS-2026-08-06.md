# Handoff — expanding the corpus: breweries + the 7 target towns (2026-08-06, third session)

**The ask:** no map for now. Expand the list, **especially with all breweries**, but
also more smaller bars, focused on **Phoenixville, Wayne, Ardmore, Collegeville,
Bryn Mawr, Conshohocken, and Manayunk**.

**Nothing was changed this session.** I measured where those towns actually lose
venues before writing any code, and the measurement changes what the work should
be. Read this before touching the ingest scripts.

Prior handoffs: `HANDOFF-PRICES-PHOTOS-2026-08-06.md` (prices + 94/100 photos),
`HANDOFF-CORPUS-2026-08-06.md` (8 → 100 venues).

---

## The finding: it is the discovery join again, not the crawl

All seven towns already exist as zones (Bryn Mawr lives inside
`ardmore_bryn_mawr`, Manayunk is `manayunk`), and the PLCB seed already lists
plenty of licensees in them. The funnel, per zone, licensees → OSM website →
crawled → quotable → published:

| zone | licensees | core | taproom | has site | crawled | quotable | published |
|---|---|---|---|---|---|---|---|
| phoenixville | 41 | 28 | **13** | 15 | 15 | 2 | 1 |
| wayne_radnor | 64 | 61 | 3 | 30 | 30 | 9 | 8 |
| ardmore_bryn_mawr | 45 | 44 | 1 | 18 | 18 | 7 | 4 |
| collegeville_trappe | 45 | 43 | 2 | 18 | 18 | 2 | 1 |
| conshohocken | 20 | 19 | 1 | 9 | 9 | 3 | 4 |
| manayunk | 56 | 53 | 3 | **8** | 7 | 1 | 1 |
| **total** | **271** | 248 | 23 | **98** | 97 | 24 | 15 |

**271 licensees in the seven towns; we have a website for 98 of them.** The crawl
loses almost nothing after that (98 → 97). Manayunk is the extreme: 56 licensed
premises on and around Main St, and we hold 8 URLs. Every one of those towns is
capped by the same step — we never learned where to crawl.

### Why the join drops so many

The OSM extract in `data/raw/osm_venues.json` holds **5,303 elements, of which
3,234 carry a website tag** (`website` 3,128, `contact:website` 132,
`brand:website` 12, `url` 2). `data/venue_sites.json` holds **691**.

So the raw material for roughly 3,200 crawlable sites is already downloaded and
sitting in the repo — the address join in `ingest/discover_sites.py` is
matching about a fifth of it. That join is deliberately strict, and it is right
to be: it matches on (ZIP, house number, street core) and **never on name**,
because ~37% of PLCB rows carry a corporate shell and two "Iron Hill Brewery"
rows are two different bars. But strictness is what costs Manayunk — dense rowhome
commercial strips are exactly where OSM house numbers are missing or where the
PLCB writes a mall/plaza name.

**This is the same shape as the last corpus session's finding, one layer in:
scraping was never blocked on extraction, it was blocked on discovery. It still is.**

## Breweries specifically

The taproom tier is already collected and already in `venues.csv` —
`seed_plcb.py` keeps `Brewery`, `Limited Winery`, `Limited Distillery`,
`Distillery`, `Winery`, `Distillery of Historic Significance` as `tier=taproom`,
separate from `core`, on purpose (they sit under a different part of the PA
discount rules). No filter is hiding them.

Disc-wide: **195 taproom licensees, 42 with a website, 16 quotable.** Phoenixville
alone holds 13 of the 195 — it is the brewery town in this market and it is
currently one published venue.

So "all breweries" is not a new source to add. It is the same join problem,
weighted toward a tier where the join does worse (21% site rate vs 24% overall)
because a brewery is more likely to be tagged `craft=brewery` on a building
without a housenumber.

## What I'd do next, in order

1. **Widen the tag read before anything else — it is free.** `discover_sites.py`
   reads only `website`. Reading `contact:website`, `url`, and `brand:website`
   too is a few lines and picks up ~146 more sites from bytes already on disk.
   Do this first and re-measure; it changes the denominator for everything below.
2. **Add a second, *guarded* join key rather than loosening the address key.**
   Do not switch to name matching globally — the corporate-shell and
   two-Iron-Hills reasons that ruled it out are still true. A safe form: allow a
   name match **only** when the OSM element and the PLCB row are in the same
   municipality *and* the normalized name is unique on both sides. Print every
   pair it accepts so the promotion is reviewable rather than silent.
3. **Target the seven towns explicitly** by running the widened join and then
   crawling only their unmatched licensees, so the work is bounded and the effect
   is measurable per zone against the table above.
4. **Expect the published yield to stay near 15–25% of crawled venues.** That is
   not a defect: ~80% of bars never publish a happy hour anywhere, and a quote is
   only promoted when it carries days, times, an unambiguous am/pm, no hedge, and
   passes the PA validators. Getting Manayunk from 8 sites to ~35 should be read
   as a handful of new cards, not thirty.
5. **Re-run photos and prices after any corpus growth.** Both passes are
   idempotent and both are joined on the same venue ids (`one_per_osm()`), so
   they just extend.

## Still open from before

- **The map is still unbuilt.** Explicitly deferred again this session ("no map
  for now"). 100 venues against a README threshold of ~50, 99 geocoded.
- **Pushing does not deploy.** Confirmed again last session — a push to `master`
  creates no workflow run. Dispatch by hand: `gh workflow run pages.yml --ref master`,
  then check the live site.
- **README says 101 venues, the build says 100.** Pre-existing drift, still not
  reconciled. Worth fixing deliberately during the next corpus change, when the
  number moves anyway.
- **108 quotable-but-unpublished venues** sit in `data/crawl_hits.json`.
- `chickie-s-pete-s-philadelphia` has no OSM centre (99/100 located).
- The **robots.txt judgement call** on builder-CDN images is documented in
  `HANDOFF-PRICES-PHOTOS-2026-08-06.md` and remains open to Paul's veto.

## Reminders

- The gate is `python -m unittest discover -s tests` + `node --test
  tests/time_math.test.mjs` + `validate_pa.py` + `build_bundles.py`. It is **pure
  logic and touches no DOM** — screenshot at a real 390px device viewport for any
  UI change, and look at the image.
- This repo is standalone: **its own `.env` only**, never `shopify-analytics/.env`.
- Don't relax the price pass's evidence check, and don't relax the address join
  globally to raise the venue count. Both strictnesses were bought with a reason.
