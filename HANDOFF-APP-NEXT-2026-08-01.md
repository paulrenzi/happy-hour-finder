# Handoff — the app got good; the corpus is now the only thing holding it back (2026-08-01)

Supersedes nothing. [HANDOFF-PHOTOS-NEXT-2026-08-01.md](HANDOFF-PHOTOS-NEXT-2026-08-01.md)
is still accurate **for photos specifically** — that lane is untouched and still
blocked on a Google Places key.

Live at https://paulrenzi.github.io/happy-hour-finder/ (Pages redeploys on push to `master`).

## What changed and why

Measured against the app's own thesis — *"a live answer to: where can I go in the
next 30 minutes, and is the deal still on?"* — the build had five defects. Four
needed no credentials at all.

| # | Defect | Fix |
|---|---|---|
| 1 | **Blank ~18 hours a day.** `windowFor()` returned null outside a 3h lookahead, so at 11am or 9pm the page was an apology. | `nextOccurrence()` searches forward 7 days. The feed always answers. |
| 2 | **No coordinates anywhere in the corpus.** The app could not rank by "near me" — the second most important input after time. | `ingest/geocode_venues.py`, OSM/Nominatim, 8/8 resolved. |
| 3 | **Ranking was actively wrong.** `score()` sorted live deals by *least time remaining*, so the top card was the one you had the least chance of reaching. | Ranks on **usable minutes** (`until − drive`), capped at 2h, with driving weighted above deal-time. |
| 4 | **The differentiator was invisible.** `deal_item` normalizes price — the "nobody else can do this" claim — and the UI rendered a bullet list. | Food / under-$5 / drinks filters, three sort orders, day picker, venue pages, shareable links. |
| 5 | **Zero tests** on logic where the bundle uses `dow 1=Mon..7=Sun` and JS `Date` uses `0=Sun`. | 29 JS + 19 Python tests, gating deploy. |

### A sixth defect, found while wiring the CI gate

`age_days` was **computed at build time and frozen into the bundle**. A bundle
built once and served for two months would keep telling everyone a deal was
"Checked 1d ago" when it was 61 days old — the exact failure this product exists
to prevent.

Bundles now ship the *fact* (`last_verified_at` + the confidence the source
earned) and `web/lib.js` derives age and applies the decay ladder **at read
time**. The Python ladder in `build_bundles.py` is retained only to drop deals
that have decayed out entirely. The two ladders are tested against the same
boundaries (45 / 120 days) in both suites.

## Two data bugs the geocoder surfaced

- **Coyote Crossing's address was wrong in the seed** — "Springmill Ave" is
  "Spring Mill Ave". Nominatim found the venue by name once corrected.
- **House-number ranges defeat geocoding.** `30-32 E State St` and `7-15 S High
  St` both missed; both resolve exactly on the first number.

The resolver keys on **address, not name** (PHASE-0 §2: ~37% of venues can't be
identified by their registry name) and tries most-constrained first. It never
drops the ZIP: `324 W Swedesford Rd` exists in **both 19312 and 19341, thirty
miles apart**, and a query without the ZIP silently returns the wrong town.

Precision is recorded per venue. Seven matched at building level; **Tony G's
matched a street centroid**, so the UI renders it `~3 mi` with no decimal rather
than implying accuracy the match can't support.

## How to verify it yourself

```
sh tests/run.sh                                   # 48 tests
python -m http.server 8765 --directory web        # then open on a phone
```

The app was driven in a real 390×844 viewport over CDP (headless Chrome clamps
`--window-size` to ~500px, which will make any screenshot narrower than that a
lie — the content is laid out at 485 CSS px and cropped). Verified: no
horizontal overflow, no console errors, venue sheet, filters, day picker,
geolocation distance, nearest sort, and a cold-loaded shared link restoring
zone + filter + day + open venue.

## Deliberately NOT built

- **A map.** With 8 venues a map is worse than a sorted list — maps pay off at
  density, and it would add the repo's first CDN dependency and break the
  offline-in-a-parking-lot property. Revisit past ~50 venues.
- **The photo lane, the Worker/D1 write path, corpus expansion.** Still yours to
  call. "Wrong?" and the camera button are honest stubs that say nothing is sent.

## What's actually next

**The corpus is now the binding constraint, and it is the only one.** The app is
good; it knows about 8 bars. Everything below is a Paul decision, and PHASE-0 §4
is still the open decision list:

1. **Zone expansion is free and local.** `data/venues.csv` (2,911 rows) is
   already on disk. 1,789 in-disc venues have no zone; Lower Providence is 4
   miles from KoP and unzoned. Adding ~8 zones is pure local compute, no network,
   no key.
2. **Places budget** (~2,900 lookups) — still open, but note Nominatim now covers
   *coordinates* for free. Places is only needed for photos/hours/closure signal.
3. **Photo lane** — at 19% scrape yield it reaches the half of the market that
   publishes nothing. Still the highest-leverage lane and still needs a key.

## Ground rules that stay in force

Own `.env` only, never `shopify-analytics/.env`. Honor `robots.txt`, rate-limit
crawls (the geocoder sleeps 1.1s between calls per Nominatim's policy and sends a
real User-Agent). Never display a deal that fails the PA legal validator (Acts 57
& 86 of 2024). Never render a claim the source didn't make. Always show
verification age and link the source. Strip EXIF from stored images, never
background-track location — the app asks for position once, on an explicit tap,
and keeps it in `sessionStorage` only. No paid placement in the "right now" feed.
Keep this operationally separate from Umbrella Arcades' venue prospecting.
