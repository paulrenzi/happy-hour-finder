# Handoff — happy-hour-finder, 2026-08-07 (the venue base layer)

Supersedes `HANDOFF-2026-08-07-CEILING.md` for *priority*, and **corrects its
central claim about Google**. Repo is standalone; its own `.env` only.
Live: https://paulrenzi.github.io/happy-hour-finder/

Shipped: **`d23edf0`**, CI `31145814464` green, live assets verified.

---

## Paul's reframe — this is now the product direction

> *"we need the base data so we have full coverage of the area cards. after that,
> if we can't find happy hour menus online, users can fill them in. but they cant
> fill them in if bars, restaurants and breweries dont even show up"*

**The venue list is the product. The happy hour is an attribute users can
supply.** That inverts the old gate: a venue with no provable window should
still get a card.

⚠️ **The web app does not do this yet.** It still renders only deal-bearing
venues, so King of Prussia still shows **6 cards** on the live site. Building
that is item 1 below.

---

## What changed, and the number that matters

Measured **per zone** instead of corpus-wide — which is what exposed this:

```
King of Prussia
 60  licensed venues        <- PLCB, the exhaustive ground truth for a zone
 34  ever had a website     <- 26 NEVER FETCHED AT ALL
 40  crawled
 14  yielded a quote
  6  published
```

**The 26 were a discovery gap, not the HTML ceiling.** Dave & Buster's,
Cheesecake Factory, Yard House, Eataly, Seasons 52 — never absent from Google,
we just had no URL. New `ingest/discover_places.py`:

```
python ingest/discover_places.py --zone king_of_prussia --dry-run
python ingest/discover_places.py --zone king_of_prussia
python ingest/fetch_venue_photos.py --from-places --zone king_of_prussia
```

**Result: 60/60 resolved, 59 with a photo.** Re-running retries misses
automatically — a cached miss can be a transient 503 or a join bug since fixed,
so only a resolved `place_id` counts as done.

### Correction: Google Places is NOT a second evidence source

The ceiling handoff said *"Google Maps has these venues, their hours, and their
photos."* Measured against Rebel Hill, whose window we already knew:
`editorialSummary` **null**, `regularOpeningHours` = **opening** hours,
`reviews` capped at **5**, none mentioning happy hour. **There is no
happy-hour field in Places.** It buys identity, websites and photos. Not windows.

Paul's own two links confirm the ceiling from the other side:
- **Seasons 52 KoP** (HH 3–6 weekdays, plainly visible in a browser) serves
  **2,705 bytes with the word "happy" appearing zero times** — rendered
  client-side.
- **`kingofprussia-happyhour.splashthat.com`** — a curated list — **403s even
  through the urllib fallback.** Harder WAF than the ones `9891c5c` beat.

### Two joins that were silently never firing

Both presented as *"Google has no listing for this venue"* — the recurring trap.

1. `street_number()` read the **leading** digits. A PLCB premises address leads
   with the complex: `THE COURT UNIT C263A 690 W DEKALB PIKE`. It returned
   `None` for every mall tenant — **all 12 KoP mall venues.**
2. `locality()` split on commas seeking a digit-free city segment as a ZIP guard.
   A PLCB address has none, so the guard **rejected every candidate it was ever
   asked about.** Reads the ZIP now; both sides format it identically.

Pinned by `tests/test_places_join.py` (9 tests). Suite is **126** and green
with and without `requests` on the path.

### The one deliberate relaxation, and its guard

Where a mall addresses a tenant differently than the PLCB does — Maggiano's is
`205 Mall Blvd` to the state and `160 N Gulph Rd Ste 205` to Google — a **name**
match is accepted, but only behind a **ZIP guard**, only after the address test
fails, and recorded as its own `matched_by` string. The address join is
unchanged for **evidence**; this path is **discovery only** (website + photo).
That distinction is the whole reason it is safe — review it if you extend it.

---

## Cost — read before running `--all`

**Cost is set by the field mask, not the call count.** `places.id` alone is
Essentials IDs-Only (unlimited free). `displayName` is Pro (5,000/mo).
**`websiteUri` is Enterprise — 1,000 free/month.** `discover_places.py` requests
one mask carrying `websiteUri`, so **every venue it resolves is an Enterprise
call.** KoP cost 60+22 retries. The remaining corpus is ~2,900 venues:

- free route: ~3 monthly batches via `--max`
- paid route: roughly $30–40 once

**Paul's call.** `--max` defaults to 1,000 so a stray `--all` cannot overrun the
free tier silently.

---

## Next session, in order

1. **Render a card for every venue, not just deal-bearing ones.** This is the
   reframe and it is not built. Needs: a venue-card path keyed on **LID**
   (`data/places_venues.json`, `data/venue_photos_by_lid.json` are already keyed
   that way), a visible "hours not published — know them?" state, and a
   submission path. **No backend exists** — decide Worker+KV vs a form, noting
   oracle-vm is under reclamation ~08-18.
2. **Run `discover_places.py` for the other 37 zones** once Paul rules on cost.
   Conshohocken and Phoenixville first — they are the other two towns with live
   counts to compare against.
3. **Merge resolved websites into `venue_sites.json` and crawl only the new
   LIDs.** Not done: the recrawl was mid-flight (see below). This is where the
   26 KoP sites finally get read for a window.
4. **Finish the corpus recrawl** — it was still running at handoff time,
   `crawl_hits.json` written seconds before. Then:
   `extract_deals.py && validate_pa.py && build_bundles.py && geocode_venues.py`

## State to know

- **The recrawl was LIVE at handoff.** `data/crawl_hits.json` is **deliberately
  uncommitted** — committing a mid-write snapshot risks a torn file. Check it is
  finished (mtime stops moving), then commit it.
- `data/venues.csv` is **gitignored**; the `+44` Brewery Storage venues are a
  regenerated artifact, not a commit.
- `ingest/resolve_places.py` was **deleted** — `discover_places.py` supersedes it.
- ~64 orphaned Python processes from **another project** (ga4_client, since
  7/20) are on this PC. Do not mistake them for crawlers; check start dates.
- The KG index `MEMORY.md` is ~20KB against a 24.4KB read limit — worth a
  compaction pass.

## Standing constraints (unchanged)

- 🛑 The join is on **address, never name**, for evidence. The name path added
  this session is discovery-only and ZIP-guarded — do not widen it.
- 🛑 Do not relax the price evidence check or the window requirement to raise
  the count.
- 🛑 No map.
- 🛑 Do not bug-fix the HTML crawler for coverage. The remaining bugs are worth
  single digits each.
- Scan for stale crawler processes before every run — each holds its own
  in-memory snapshot of `crawl_hits.json` and rewrites it per venue.
- After every deploy push: `gh run list`, then fetch the **LIVE** artifact.
  Normalise through `json.tool` before concluding a mismatch — git autocrlf
  makes raw byte diffs always differ.

## Gate before any commit

```
python -m unittest discover -s tests      # 126 tests
node --test tests/time_math.test.mjs      # 29
python ingest/validate_pa.py              # 8/8
python ingest/build_bundles.py            # also stamps web/sw.js
gh run list --limit 3                     # AFTER the push
```

CI has no `requests`; reproduce with a `requests.py` that raises on
`PYTHONPATH` — confirmed green this session.
