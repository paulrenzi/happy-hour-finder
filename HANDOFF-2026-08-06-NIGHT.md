# Handoff — happy-hour-finder, 2026-08-06 night

Supersedes `HANDOFF-2026-08-06-EVENING.md`. Repo is standalone; its own `.env`
only, never `shopify-analytics/.env`. Live: https://paulrenzi.github.io/happy-hour-finder/

## Shipped and verified live

1. **Add a menu now offers the photo library.** `capture="environment"` removed
   from the file input — that attribute is exactly what forces camera-only. The
   change handler echoes the picked File back (name, MIME, size, preview) so a
   library pick is *shown* to have worked, with an explicit branch for a HEIC the
   browser can't decode. Screenshotted at a real 390px viewport (CDP metrics
   override, not `--window-size`) on both branches.
2. **sw.js cache name now carries a shell digest.** It previously moved only when
   the *corpus* moved, so a shell-only deploy shipped an identical name, evicted
   nothing, and left installed devices on the old `app.js` — defect A from the
   evening handoff, with the corpus in the clear.
3. **Roundup tier** (Paul's call, below).
4. **King of Prussia 3 → 4.**

## Paul's decisions this session — treat as settled

| Question | Decision |
|---|---|
| How roundups appear | **Own tier.** `source.kind: "roundup"`, outlet + publish date named on the card, capped at `unconfirmed`, never outranks a venue_site deal. |
| Recency | **Hard drop over 120 days.** Not a demotion. The vista.today Phoenixville piece (Oct 2024) is discarded at ingest. |
| Discovery API | **Google Places, scoped to the 7 towns (~$8).** ⏳ *Needs Paul to create the key — no `.env` work until then.* |
| robots.txt-blocked venues | **Hand-verify from the page**, entered with the URL as source. |
| Mis-joins | **Fix by hand + regression test.** The address join stays untouched. |

`validate_pa.KINDS` now checks `source.kind`; `aggregator` and `instagram` are
listed explicitly because both ship in the seed and a kinds check that forgot
them would have silently deleted two published deals.

`crawl_roundups.py` is built and tested but has **no `data/roundup_sources.json`
yet** — it exits cleanly saying there is nothing to crawl. Candidate outlets:
vista.today, countylinesmagazine.com, phoenixvillecurated.com, VisitKOP.

## The KoP finding — five causes, not one

Paul named ~17 bars he expected to see. Tracing each through every stage:

| Cause | Venues |
|---|---|
| Never discovered (not in PLCB corpus) | Seasons 52, Yard House, Taku, Meltin Pot |
| **robots.txt disallows us** | City Works, Hooters, Sullivan's, Buffalo Wild Wings |
| **Mis-joined to the wrong site** | North Italia (404), Charkoal's, Founding Farmers (403) |
| Crawled clean, 0 quotes (JS shell) | Davios, Bartaco, Maggiano's, Capital Grille |
| Deals found, correctly dropped | Tommy's Tavern (6 quotes), Pizzeria Vetri (2) |

**Tommy's and Vetri are worth understanding:** their quotes name a day but no
hours (`HALF PRICE ALL TITOS COCKTAILS / TUESDAY / WEDNESDAY`). No window means
no publish, by design, and their pages genuinely never state times. Do not relax
this to raise the count.

**North Italia was the whole 3 → 4**, and the cause was *not* the JS-shell theory:
its entry pointed at `locations.bonchon.com`, which 404s. Pointed at the real
site it returns 5 quotes, and its happy-hour PDF (Mon–Fri 4–6pm) was reachable
all along by the PDF lane shipped last session. **Check the joined URL's status
code before theorising about rendering.**

Two gotchas that cost a rebuild each:
- `osm_name` is what the card **displays**. The stale OSM node at that address
  still described the Bonchon that used to occupy the unit, so the first rebuild
  shipped North Italia's happy hour under "Bonchon Chicken".
- `crawl_hits.json` **caches the name at crawl time**, so a corrected
  `venue_sites.json` only lands after a **recrawl**.

Both pinned by `tests/test_ingest.py::HandCorrectedJoins`.

## 🛑 The gate does not catch everything — check the deploy

Two pushes ran the local gate green and **failed in CI in 9–12s**, so neither the
roundup tier nor the KoP fix reached the live site until a third push fixed it.
Cause: `crawl_roundups.py` imported `requests` at module scope. It is installed
on Paul's PC and **not on the runner**, and the test suite imports the module.
`crawl_sites.py` already avoided this.

**After every deploy push: `gh run list --limit 3`, confirm success, then fetch
the LIVE artifact and read the value that changed.** Verifying the local build
proves nothing. To reproduce CI locally, shadow the dep:
`PYTHONPATH=<dir with a requests.py that raises> python -m unittest discover -s tests`.

## Gate before any commit

```
python -m unittest discover -s tests      # 102 tests
node --test tests/time_math.test.mjs      # 29
python ingest/validate_pa.py              # 8/8
python ingest/build_bundles.py            # also stamps web/sw.js
gh run list --limit 3                     # AFTER the push -- see above
```

Pipeline order: crawl → `extract_deals` → `validate_pa` → `build_bundles` →
photos → **`build_bundles` again**.

## Next, in the order the evidence supports

1. **Places key** — unblocks the 4 never-discovered venues and the 9 missing
   coordinates. Waiting on Paul.
2. **Hand-verify the 4 robots-blocked venues**, City Works first. My guessed
   location URLs 404'd; the right paths still need finding.
3. **Remaining mis-joins** — Charkoal's and Founding Farmers still point at the
   wrong site. Four more listed in the evening handoff.
4. **The photo-upload pipeline.** Paul is in the Town Center and can photograph
   the boards the crawler is not allowed to read. Nothing else covers that.
5. Roundups — worth it for **Phoenixville** (1 published venue vs a dozen named),
   not for KoP.

## Standing constraints

- 🛑 Do not relax the price pass's evidence check, the window requirement, or the
  address join to raise the venue count.
- 🛑 No map.
- 🛑 The join is on **address, never name** — ~37% of PLCB rows carry a corporate
  shell, so a name mismatch alone is not evidence of a mis-join.
- Scan for stale crawler processes before every run; each holds its own in-memory
  snapshot of `crawl_hits.json` and rewrites the whole file per venue. Wait on
  background jobs with PowerShell `Wait-Process -Id <pid>`, never `pgrep`.
- Expected published yield is ~15–25% of crawled venues. Normal, not a defect.
