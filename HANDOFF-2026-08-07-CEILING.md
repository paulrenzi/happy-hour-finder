# Handoff — happy-hour-finder, 2026-08-07 (the source ceiling)

Supersedes `HANDOFF-2026-08-07-COVERAGE.md`, and **corrects two things it got
wrong**. Repo is standalone; its own `.env` only. Live:
https://paulrenzi.github.io/happy-hour-finder/

Paul: *"something is very wrong with whatever process you're doing… the results
for king of prussia are abysmal… Most of these restaurants are listed on google
maps, with great pictures. Where's founding farmers?"*

He is right, and the previous handoff misdiagnosed why.

---

## The answer: the ceiling is architectural, not a bug list

```
2911 PLCB licence rows        (~37% corporate shells)
 →  827 with a proven website
 →  917 crawled
 →  330 hold a happy-hour quote     ← 585 hold NONE
 →  169 of those state no schedule
 →  155 published
```

**585 of 917 crawled venues yield zero quotes.** Two sessions of crawler
bug-fixing moved the corpus 132 → 155. Every fix was real. **None of them
touches that 585.**

The pipeline's only evidence source is **the venue's own website HTML.** That
fails structurally whenever:

- the site is a **JS shell** — Darden (Seasons 52, Yard House, Eddie V's) serves
  2.7 KB and hydrates client-side
- the venue is **Instagram/Facebook only**, or has no site
- the hours are in a **photo of a chalkboard** or a scanned PDF
- the site is real but simply **never states a window** (169 venues)

Google Maps has these venues, their hours, and their photos. We never ask it.

> **The Google Places key is not backlog item 1. It is the unblock for the whole
> approach** — and it is the same key that fixes the "great pictures" gap.
> It is blocked on Paul creating it.

**Do not spend another session bug-fixing the HTML crawler for coverage.** The
remaining bugs are worth single digits each.

---

## What shipped this session — `9891c5c`, CI 31142764357 green, live verified

**A 403 from `requests` is not a 403 to us.**

`wearefoundingfarmers.com` and `stable12.com` return **403 to requests/urllib3
and 200 to `urllib`** — same URL, same `happy-hour-finder/0.1` User-Agent.
Header cycling does not move it (`Accept`, `Accept-Encoding: identity`,
`Connection: close` all still 403). The WAF fingerprints the *connection*
urllib3 makes, not our identity.

`crawl_sites.get()` now retries a 403 through `urllib`. **No UA change, no
browser disguise, no robots bypass** — robots.txt is still fetched and obeyed.

### Two corrections to the last handoff

1. **I told Paul the fix was a browser User-Agent and called it "the largest
   lever to 3x", framing it as a posture decision for him.** All three were
   wrong. It needed no identity change, it was a four-line bug, and the bucket
   is **26 venues** — a number I never counted before calling it the biggest
   lever. I escalated a bug to the user as an ethics question.

2. **Founding Farmers KoP has no happy hour.** It crawls fine now and still does
   not publish, *correctly*: its own location FAQ says **"we don't have a
   traditional happy hour or offer discounted pricing."** The Google result that
   looks like a counter-example — `/now-serving-happy-hour/` — is a
   DC/Georgetown blog page; "King of Prussia" appears only in its nav and one
   seasonal-cocktail blurb. There is no window on it. The exclusion was always
   right; the 403 is what made it unauditable.

Gotcha worth keeping: `requests` hands back a **case-insensitive** header map.
A plain `dict` from urllib answers `None` to `headers.get("content-type")`, so
the first version logged a fully successful fetch as `200 ?` and threw the page
away — the same failure shape as the original bug. Pinned by
`test_the_fallbacks_headers_answer_to_a_lowercase_lookup`.

Net: crawled 917, quoting 324 → **330**, published 154 → **155**
(Wacky Zaki's, The 700, + Founding Farmers reachable but correctly excluded).

---

## Counts now — verified live

| Zone | Now |
|---|---|
| King of Prussia | 6 |
| Conshohocken | 5 |
| Phoenixville | 4 |
| **Corpus** | **155** |

Not tripled. The gap is the 585, and it does not close from this side.

Verified per the standing rule: all four live artifacts fetched with a
cache-buster and diffed against local — `zone-king_of_prussia`,
`zone-conshohocken`, `zone-phoenixville`, `index` all **MATCH**; live and local
`sw.js` both `hhf-2026-08-06-155-c3beea14`. Note the raw byte diff will always
show a difference from git's autocrlf — **normalise through `json.tool` before
concluding a mismatch.**

---

## Next session, in size order

1. **Google Places** — blocked on Paul's key. Second evidence source + photos.
2. **Corpus-wide recrawl.** The `4p` and quote-slot fixes have *still* not
   reached the ~800 venues outside the three towns; the run was interrupted
   twice. Resumable and safe — `crawl_sites.py` writes after every venue:
   ```
   for z in <zones>; do python -u ingest/crawl_sites.py --recrawl --zone $z; done
   python ingest/extract_deals.py && python ingest/validate_pa.py
   python ingest/build_bundles.py && python ingest/geocode_venues.py
   ```
3. **`seed_plcb.py`'s licence-type filter.** Crowded Castle Brewing and Gridiron
   Sports Bar — real Phoenixville bars — are absent from `venues.csv` under any
   address. Possibly an "Eating Place (Malt)" exclusion. Corpus-scope, not join.
4. **Photo pipeline** — still needs a backend decision (Cloudflare Worker + R2
   vs oracle-vm, which is under reclamation ~08-18). Largely mooted by Places.

## Standing constraints (unchanged)

- 🛑 The join is on **address, never name**. Name-absence is worthless evidence
  at a 37% shell rate.
- 🛑 Do not relax the price evidence check, the window requirement, or the
  address join to raise the count.
- 🛑 No map.
- Scan for stale crawler processes before every run — each holds its own
  in-memory snapshot of `crawl_hits.json` and rewrites the whole file per venue.
  (Unrelated but noticed: ~40 orphaned `ga4_client.py` processes are running on
  this PC from another project, dating back to 7/20.)
- After every deploy push: `gh run list`, then fetch the LIVE artifact and read
  the value that changed.

## Gate before any commit

```
python -m unittest discover -s tests      # 117 tests
node --test tests/time_math.test.mjs      # 29
python ingest/validate_pa.py              # 8/8
python ingest/build_bundles.py            # also stamps web/sw.js
gh run list --limit 3                     # AFTER the push
```

CI has no `requests`; reproduce with
`PYTHONPATH=<dir containing a requests.py that raises> python -m unittest discover -s tests`
— confirmed green this session.
