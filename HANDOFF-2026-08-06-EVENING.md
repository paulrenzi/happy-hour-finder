# Handoff — happy-hour-finder, 2026-08-06 evening

Repo: `C:\Users\paulm\happy-hour-finder` (**standalone** — its own `.env` only,
never `shopify-analytics/.env`). Live: https://paulrenzi.github.io/happy-hour-finder/

## FIRST THING NEXT SESSION — Paul's explicit ask

> "i want the 'Add a menu' button to open my phone camera, but allow for me to
> submit a picture i already have on my phone from photos, not just take a
> picture on the spot. im going to run a test with a menu i have saved as a
> picture next session"

The fix is to **remove the `capture` attribute** from the file input. `capture`
is precisely what forces camera-only; `<input type="file" accept="image/*">`
*without* it gives the native iOS/Android sheet with both **Take Photo** and
**Choose from Library**.

- Find it: `grep -n "capture\|accept=\"image" web/index.html web/app.js`
- After the change, screenshot at a **real 390px device viewport** (drive Chrome
  over CDP — headless `--window-size` clamps and gives you a 485px layout
  cropped, see `feedback_headless_chrome_clamps_window_size`) and **look at the
  image**.
- Paul will test with a **saved** menu photo, so verify the library path end to
  end, not just that the sheet opens.

## What shipped this session

**Corpus 101 → 131 published venues across 29 zones**, 124 with photos.
Funnel: 886 crawled → 253 with a quote → 126 kept → **131 published**.
King of Prussia 1 → 3 (BOTLD, Paladar, Fogo de Chão).

1. **Registrable-domain (eTLD+1) sibling-host fix**, from the prior session,
   validated by recrawl: **28 of 66** previously-silent venues now publish a deal
   quote. Chains keep specials on `www` while the location page sits on
   `locations.*`; an exact-hostname test was discarding the only useful page.
2. **PDF menu lane** — `crawl_sites.pdf_text()`, `pypdf`, first 6 pages. A
   scanned image yields `""`, which is the correct answer: no text ⇒ no quote ⇒
   no deal, never a guess from a filename. `.pdf` removed from the
   extension blocklist in `candidate_links()`.
3. **sitemap.xml lane** — `crawl_sites.sitemap_links()`, consulted only when the
   homepage links to no deal page. Reaches `/happy-hour` pages that exist but are
   unlinked. Budget 3 fetches; a sitemap index is followed one level, never the
   whole tree of a 10,000-URL chain site.
4. **Venue-id / coordinate staleness fix** (see Defects below).
5. **Service-worker cache fix** (see Defects below) — this is what made KoP still
   read 1 on Paul's phone after the deploy.

88 tests green + `node --test tests/time_math.test.mjs` + `validate_pa.py` 8/8.

## Defects found — both were invisible failures, read these

### A. `sw.js` cache name never changed ⇒ the phone froze the corpus
Paul reported **KoP still says 1** after a deploy where the server said 3. Every
server check passed: live `data/index.json` and `zone-king_of_prussia.json` both
3, HTTP 200, correct `built_at`.

`web/sw.js` precaches `data/index.json` in `SHELL`, and `activate` evicts caches
**whose name differs**. `const CACHE = "hhf-v4"` hadn't changed since `4bf502e`,
four builds back — so the precache was never evicted. `fetch` was network-first,
which is why it looked impossible; but network-first still falls back to the
precache whenever a fetch fails, and that copy was months old.

Fixed:
- `build_bundles.stamp_service_worker()` writes
  `sw_cache_name(built_at, n_published)` → `hhf-2026-08-06-131`. The venue count
  rides with the date so a **second build the same day still evicts**.
- `tests/test_ingest.py::ServiceWorkerCache` fails if a build ships unstamped.
  **Validated against a known positive:** reverting to `hhf-v4` → FAILED,
  restoring → OK.
- `clients.claim()` added — without it an already-open tab or installed PWA keeps
  the OLD worker for days.
- `cache: "reload"` on the precache fill; `if (res.ok && res.type === "basic")`
  so a mid-deploy 404 isn't kept as the offline floor.
- `app.js` boot fetches `data/index.json` with `{cache: "no-cache"}`.

**Paul may still need one hard reload** on a device that already installed the
old worker — the new one claims on next load, but the currently-rendered page was
drawn from the old cache.

### B. A venue id silently carried another branch's coordinates
Venue id is `slug(name + city)`, so the two Santucci's in Philadelphia collide on
one bare slug, and **which one holds it changes between runs**. The coord cache
wrote only `if vid not in coords`, so the slug changed hands while the coordinate
did not — a pin several miles from the bar with nothing on the page to show it.
`extract_deals.py` now refreshes an `osm_site` entry whose `queried` address is no
longer the current holder's; hand-geocoded entries are still never touched.
Regression test validated by poisoning a record (FAILED) then restoring (OK).

## More data — where to go next, and why

Paul's constraint is **"in the last 4 months or so"**.

| Source | Verdict |
|---|---|
| Facebook | **✗** Page feeds need Page Public Content Access + App Review; the public `/search` endpoint is deprecated for standard dev accounts. Visible in a browser ≠ reachable by API. |
| Yelp | **✗** Fusion forbids caching content beyond 24h — a static GitHub Pages bundle **is** a cache. Display rules also forbid blending Yelp ratings with other sources. |
| PDF menus | **✓ shipped** |
| sitemap.xml | **✓ shipped** |
| BentoBox / Popmenu / Toast / Square menu JSON | **✓ viable, unbuilt.** Would reach the JS-rendered shells that currently fail verification: Creed's (649 chars), Paladar (1379), Taku (1880), Cheesecake (1905). |
| Dated local roundups | **✓ viable, unbuilt — and the important one.** |

**Why roundups matter:** venue pages are almost never dated, so "is this from the
last 4 months?" is *unanswerable* from the venue's own site. Roundups carry a
publish date, which is the only clean way to make Paul's recency rule a **hard
gate**. Candidates: vista.today, countylinesmagazine.com,
phoenixvillecurated.com, VisitKOP.

🛑 **Open question for Paul, ask before building:** a roundup is **not the venue
speaking**, so those deals belong at a **lower confidence tier with the outlet
named**, not `source.kind: "venue_site"`. That changes what the site is
asserting, so it's his call. Concrete illustration of why the date must gate: the
vista.today Phoenixville piece is from **October 2024** — outside the window.

Phoenixville is the clearest target: **1 published venue** while roundups name a
dozen (Bistro on Bridge, Root Down, Bluebird, Fitzwater Station, Rebel Hill).

## Still open / standing constraints

- ⏳ **Paul never answered the API-key question.** Options given: Google Places
  ~$8 scoped to the 7 towns, or Foursquare free tier. **No key work, no `.env`
  creation, until he answers.**
- 🛑 **Do not relax the price pass's evidence check, and do not relax the address
  join to raise the venue count.** Both strictnesses were bought with a reason.
- 🛑 **No map.**
- 🛑 Residual **single-claimant mis-joins** `collapse_shared` cannot see:
  RESIDENCE INN → firstwatch, NORTH ITALIA → locations.bonchon.com, COMFORT INN →
  Home2 Suites, SCREWBALLS → angelospizzakop, DOUBLE TREE → The Alloy,
  CHARKOAL'S → gauchosprimeusa. A discriminator exists (both names real and
  non-shell yet disagreeing) but acting on it means touching the join ⇒ **Paul's
  call.** Remember: the join is on **address, never name**, because ~37% of PLCB
  rows carry a corporate shell — **a name mismatch alone is NOT evidence of a
  mis-join.**
- 122/131 venues have coordinates. `geocode_venues.py` only covers the seed
  corpus, so it reports "all 8 already resolved". Not a blocker given "No map".
- README venue count drifts; reconcile when convenient.

## Operating notes

**Pipeline order matters:** crawl → `extract_deals` → `validate_pa` →
`build_bundles` → photos → **`build_bundles` again** (`fetch_og_images.published()`
reads `web/data/zone-*.json`, so photos only land in the bundles on a second build).

**Gate before any commit:**
```
python -m unittest discover -s tests      # 88 tests
node --test tests/time_math.test.mjs
python ingest/validate_pa.py
python ingest/build_bundles.py            # also stamps web/sw.js
```

**Deploy:** `git push`, which triggers Pages. `gh workflow run pages.yml --ref
master` is redundant on a push and gets cancelled as a duplicate. Verify by
fetching the **live** `data/index.json` — and read the key `venues`, not
`venue_count`, which does not exist (I burned a cycle on that).

🛑 **Waiting on a background job: use PowerShell `Wait-Process -Id <pid>`.**
`pgrep` in Git Bash **cannot see Win32 processes**, reports "finished"
immediately, and I nearly ran extraction against a half-crawled corpus. Also scan
for **stale crawler processes before every run** — each holds its own in-memory
snapshot of `crawl_hits.json` and rewrites the whole file per venue, so one
waking up silently overwrites hours of new results with an old copy. Three were
found alive this session.

Expected published yield is **~15–25% of crawled venues. That is normal, not a
defect** — most bars simply never publish a happy hour, which is the whole reason
the Add-a-menu upload lane matters.
