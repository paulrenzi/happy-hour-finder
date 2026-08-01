# Handoff — why the photos still don't display, and the one thing that unblocks them

**Repo:** `C:\Users\paulm\happy-hour-finder` (standalone — its own `.env`, its own deploy)
**Live:** https://paulrenzi.github.io/happy-hour-finder/
**HEAD:** `60ef3fd` (pushed, CI gated on 50 tests)
**Date:** 2026-08-01, evening

---

## The short version

Photos don't display because **there is no `.env`, so there is no
`GOOGLE_PLACES_API_KEY`**, so no photo was ever fetched. Nothing is broken in the
app. Every other link in the chain is wired, and that is now *proven*, not assumed.

And there was a real bug waiting: **the fetcher wrote every image into a directory
that does not exist.** If you had pasted in a key yesterday, you would have spent 16
billed Places calls, stored zero images, and seen eight lines of `download failed`
that look like a Google problem. Fixed in `60ef3fd`.

---

## The chain, with evidence

The photo path is five links. Four were green; link 1 is the only real gap.

| # | Link | State | Evidence |
|---|---|---|---|
| 1 | `.env` → `GOOGLE_PLACES_API_KEY` | **MISSING** | no `.env` file at all |
| 2 | `ingest/fetch_venue_photos.py` → `data/venue_photos.json` + `web/img/venues/*.jpg` | code present, **never run**, and had the path bug | proven via stubbed run |
| 3 | `ingest/build_bundles.py:53,87-89` attaches `photo` to each venue | wired, correctly optional | 8/8 got a `photo` key under the stub |
| 4 | `web/app.js:227-236` renders it; `index.html:70`; `styles.css:159` | wired, survived the app rewrite, 404s fall back to the tile | grep + stubbed bundle |
| 5 | git tracks `web/img/venues/` and the manifest; Pages publishes `web/` | clear — neither path is gitignored | `git check-ignore` |

**Diagnostic order for next time:** walk `.env` → manifest → `web/img/venues/` →
`"photo"` keys in `web/data/*.json`. **The first one missing is the answer.** Every
stage is `if exists:` optional by design, so a missing key produces *silence*, not an
error — reading the render code tells you nothing.

---

## The bug that was fixed (`60ef3fd`)

```python
rel = f"img/venues/{vid}.jpg"          # a path relative to the WEB root
download(key, photo, os.path.join(REPO, rel))   # ...joined against the REPO root
```

`makedirs` created `web/img/venues/`. The write went to `<repo>/img/venues/`, which
nothing creates → `FileNotFoundError` → swallowed by `except Exception: continue`.

The expensive part is the ordering: the Places **search and media calls both succeed
first**. The money is spent, the bytes arrive, and *then* the local write fails and
throws them away.

Fixed by deriving both paths in one place so they cannot drift:

```python
def photo_dest(vid):
    return os.path.join(IMG_DIR, f"{vid}.jpg"), f"img/venues/{vid}.jpg"
```

Also in that commit:
- a local write failure now **exits** instead of continuing — it is systemic, and
  continuing bills a call per remaining venue and stores none of them
- `requests` is imported **lazily**, so the path helpers stay importable and the CI
  gate stays stdlib-only (verified by blocking `requests` from `sys.meta_path` and
  re-running the suite — 21/21 still pass)
- two tests pin the download destination to the directory `makedirs` creates

---

## How it was verified without a key

`scratchpad/photo_chain_proof.py` (in the session scratchpad, not the repo) stubs
`requests` with a realistic Places payload and JPEG bytes, runs the **real** fetcher
and the **real** bundle builder, asserts, then removes every artifact and restores
the bundles byte-for-byte.

```
8/8 venues have a photo -> data/venue_photos.json
venues carrying a photo key across bundles: 8
broken src paths: none
RESULT: PASS - the chain works, only the key is missing
```

Worth keeping as the pattern: **a paid pipeline should be provable end-to-end with a
stubbed provider before the first real call.**

---

## To actually get photos on the site

1. Create `C:\Users\paulm\happy-hour-finder\.env` — **this repo's own key. Never read
   `shopify-analytics/.env`.** (`.env` and `.env.*` are gitignored.)
   ```
   GOOGLE_PLACES_API_KEY=...
   ```
   Needs **Places API (New)** enabled — the fetcher uses `places.googleapis.com/v1`.
2. `python ingest/fetch_venue_photos.py --limit 1` — **one venue first.** Confirm a
   file appears in `web/img/venues/` and the manifest names the bar you expected.
3. `python ingest/fetch_venue_photos.py` (8 venues, ~16 calls, well inside free tier)
4. `python ingest/build_bundles.py`
5. `sh tests/run.sh`, then commit `web/img/venues/`, `data/venue_photos.json`, and
   `web/data/`. Pages redeploys on push.

**Check step 2's `resolved_name` against the seed name.** Resolution is name+address
text search, and two "Iron Hill Brewery" rows are different bars. `8/8 succeeded` is
not evidence — the resolved string is.

---

## Two open questions to settle before scaling photos

1. **Storage terms.** The fetcher downloads Places photo *bytes* into a public git
   repo. Google's Places terms restrict caching/storing photo content (this is
   exactly the difference that made OSM/Nominatim the right answer for coordinates —
   ODbL data can be stored and shipped). **Verify the current Photos policy before
   committing images**, and consider serving by photo reference instead, or sourcing
   storefront images from the upload lane. This is a real risk to a public repo, not
   a theoretical one.
2. **EXIF.** A stated non-negotiable is "strip EXIF from stored images." The fetcher
   writes `r.content` verbatim. Low risk for Google-re-encoded photos; **it matters a
   lot for the user-upload lane**, which will need a stripping step (and that means
   the repo's first image dependency — decide deliberately).

---

## Still gated — needs an explicit go-ahead

- the photo **lane** (upload → vision → moderation)
- the Cloudflare **Worker + D1** write path
- **corpus expansion** / the general crawl
- Places at corpus scale (~2,900 lookups)
- a map (deliberately deferred until ~50 venues — it costs the first CDN dependency
  and the works-offline property)

## The actual constraint

**The app is good and it knows about 8 bars.** Photos are a polish item; the corpus
is the product. The cheapest next move needs no key and no network: `data/venues.csv`
already holds all 2,911 PLCB rows on disk, and **1,789 in-disc venues have no zone**
— Lower Providence is 4 miles from KoP and unzoned. Zone expansion is pure local
compute.

## Non-negotiables (unchanged)

Own `.env` only, never `shopify-analytics/.env` · never commit `.env`/tokens · never
log secrets · honor `robots.txt`, rate-limit crawls · never show a deal failing the PA
validator (Acts 57 & 86 of 2024) · never render a claim the source didn't make ·
always show verification age and link the source · strip EXIF from stored images · no
background location (one tap, `sessionStorage`) · no paid placement in the "right now"
feed · keep operationally separate from Umbrella Arcades' venue prospecting.
