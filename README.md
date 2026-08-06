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
data/deals_seed.json     the curated corpus — 8 venues today
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

The app surface is done, and the zone map now covers the disc: 2,908 of 2,911
licensees sit in one of 38 named zones (it was 1,122 in 12). That is the *target
list* — it says where a bar is, not what its happy hour is.

**The corpus is still the constraint — it knows about 8 bars.**
Phase 0 measured the real scrape yield at 19%, not 40%: ~80% of bars never publish
a happy hour anywhere, which is why the photo lane (photograph a table tent →
vision extract → validate → publish) is the only path to covering half the area.

Background: [`SPEC.md`](SPEC.md) · [`HANDOFF-START-HERE.md`](HANDOFF-START-HERE.md)
· [`PHASE-0-FINDINGS.md`](PHASE-0-FINDINGS.md) · the dated `HANDOFF-*.md` files are
session notes, newest wins.
