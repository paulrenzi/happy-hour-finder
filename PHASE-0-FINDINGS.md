# Phase 0 — Feasibility Findings

Run 2026-07-31. Exit criterion from the handoff: *know the real denominator and the
real yield rate before building anything.* Both are below. **Phase 1 has not started.**

Reproduce with `python ingest/seed_plcb.py`. Evidence lives in
[data/phase0_checks.csv](data/phase0_checks.csv) — one row per hand-checked venue,
with the URL and the quoted deal text.

---

## Headline

| Question | Answer |
|---|---|
| Real denominator inside 20 mi of KoP | **2,911 active public on-premises licensees** — dead centre of the spec's 2,500–3,500 guess |
| …of which are actually visitable venues | **~2,520** (13% of the licence rows are not a place you can walk into) |
| Venues that run *some* happy hour | **50%** (13/26) — top of the spec's 30–50% guess |
| Venues whose happy hour is **scrapeable from their own site** | **19%** (5/26), 95% CI 8.5–37.9% |
| Venues with **no first-party happy hour signal at all** | **50%** (13/26) |

**The yield question the handoff asked has an answer, and it is the bad one.**
The handoff said: *"If yield is 15% and not 40%, the shape of the whole product
changes — and the photo lane becomes even more central."* Measured yield is **19%**,
and the upper end of the confidence interval barely touches 38%. Scraping cannot
carry this product. The photo lane is not a phase-3 feature; it is the only
mechanism that reaches half the corpus.

---

## 1. The denominator

**Source found and working:** the PLCB publishes a complete statewide CSV of every
active licence at `https://plcbplus.pa.gov/pub/LicenseExport.aspx` — no auth, no key,
no rate limit, ~15 MB, 59,987 rows. It carries licence type, status, premises name,
full address, county and municipality. SPEC §5 flagged this as "verify the current
endpoint" — it is verified and wired into `ingest/seed_plcb.py`.

Filtering: `Status = Active` → public on-premises licence types → the five in-scope
counties → premises ZIP within 20 mi of 40.089/−75.396 (GeoNames ZIP centroids).

| Zone | Venues | Core | Taproom |
|---|---:|---:|---:|
| King of Prussia | 60 | 57 | 3 |
| Conshohocken | 20 | 19 | 1 |
| Wayne / Radnor | 57 | 54 | 3 |
| Ardmore / Bryn Mawr | 45 | 44 | 1 |
| Norristown / Bridgeport | 48 | 42 | 6 |
| Phoenixville | 24 | 16 | 8 |
| West Chester | 51 | 42 | 9 |
| Media | 29 | 29 | 0 |
| Manayunk / Roxborough | 56 | 53 | 3 |
| Collegeville / Trappe | 29 | 27 | 2 |
| Blue Bell / Plymouth Meeting | 40 | 39 | 1 |
| **11 suburban zones** | **459** | **422** | **37** |
| Philadelphia — Center City | 663 | 650 | 13 |
| *(inside the disc, no named zone)* | 1,789 | 1,644 | 145 |
| **Total** | **2,911** | | |

Excluded on purpose: 2,549 private-club licences (members-only), 6,910 non-on-premises
licences (beer distributors, transporters, importers, direct shippers).

### Three things the count exposes

**a. The 12 named zones cover 39% of the disc.** 1,789 venues sit inside 20 miles and
inside no zone — 896 of them suburban. The biggest unclaimed clusters: Upper Darby (45),
Springfield Twp (22), Concord Twp (20), Newtown Twp Delco (18), Montgomery Twp (18),
West Whiteland (18), East Whiteland (17), Haverford Twp (17), Abington (16), Pottstown (16),
Lower Providence (15, and only **4 miles** from KoP). The zone list needs roughly 6–10 more
entries or it silently hides two-thirds of the market.

**b. No New Jersey question exists.** The PLCB registry is PA-only — Camden contributes
zero rows. NJ isn't a scope cut to decide, it's a separate data source we'd have to go
find. Open question #2 in the handoff is closed by default.

**c. Center City is 23% of the disc, not 70%.** SPEC §2 feared Philly would swamp the
dataset. Restricted to Center City ZIPs it's 663 of 2,911. The *whole* of Philadelphia
County is 1,619 (56%) — so the swamp is real only if we take all of Philadelphia, and
the Center City zone as defined is a manageable slice.

---

## 2. The yield rate

30 venues, drawn with a seeded stratified random sample proportional to zone size
across the 11 suburban zones — the surface a KoP user actually sees. Frame: 459 venues.
Sample and classifications: [data/phase0_sample.csv](data/phase0_sample.csv),
[data/phase0_checks.csv](data/phase0_checks.csv).

| Outcome | n | What it means |
|---|---:|---|
| **first-party, full** | 5 | Own site, days + times + items + prices. Extractable today. |
| **first-party, partial** | 2 | Own site states the window, no items. Half a deal. |
| social only | 2 | Real HH, published only to Instagram/Facebook. |
| third-party only | 4 | Real HH, visible only on Yelp/OpenTable/reviews. |
| site, no HH | 10 | Website exists, publishes no happy hour. |
| no website at all | 3 | Nothing to crawl. |
| **not a venue** | 3 | Licence held by a producer or an office. |
| **closed** | 1 | Taproom shut; licence still reads Active. |

**19% (5/26) is the honest scrape yield.** Add the two partials and 27% yields at least
a window. Both numbers are well under the 40% SPEC §5 assumed for venue websites.

### What the 19% looks like

The five that worked are worth naming, because they're a type, not a spread:
Will's + Bill's, Pietro's Radnor (a PDF dated **2026-07-06** — three weeks old),
Tired Hands, Iron Hill Media (a chain with a genuine per-location HH page), and
The Black Horse Tavern. **Four of five are breweries or brewery-adjacent.** Places whose
identity is the beer publish their beer prices. Neighbourhood taverns do not.

### What the 50% failure looks like

Jake's Bar (1938, cash only), Murphy's Tavern (1969), Scanlon's Saloon (1976), the
Cresson Inn, the Frosted Mug — dive bars with a Facebook page and no site. These are
**exactly** the venues SPEC §1 says people want and every competitor misses, and they
are unreachable by crawler at any level of engineering effort. A photo of a table tent
is the only path to them.

Two more patterns worth carrying into Phase 1:

- **The site exists but the specials are on Facebook.** Screwballs literally prints
  "Check our Facebook page for daily specials." The Great American Pub's own specials
  page is an events calendar reading "No Events" for every day of July 2026. Fitzwater
  Station advertises "Happy Hour specials" as a feature and publishes none (it does
  publish a *Yappy Hour puppy menu*). A crawler sees a live, healthy, recently-updated
  page and extracts nothing.
- **Barnaby's returned 403 to an automated fetch** while serving a browser fine. Some
  share of the corpus will be crawler-hostile regardless of `robots.txt` compliance.

### Registry decay is measurable

4 of 30 rows (13%) were not a venue a person can visit:

- **Bald Birds Brewing KoP** — closed at the end of **this month**, licence still Active.
- **Jamestown Tavern LLC** — the tavern closed in 2025; the address is now Henry James
  Saloon. The licence still carries the dead name.
- **DeRo Spirits** — a limoncello producer. Tours by appointment, no taproom.
- **American Spirits Exchange** — a national importer's back office, Suite 209.
- (**Bolmar St** — a Brewery licence with no findable public identity under any name.)

So the licence list is a good denominator and a *bad* venue list. Places resolution
isn't enrichment, it's a required correctness pass — which leads to the next problem.

### The PLCB name is frequently not the venue's name

In the 30-venue sample, 11 rows carried a corporate shell instead of a trade name:
`SCREWBALLS LLC`, `300-E-6, INC.` (Coyote Crossing), `BKBC INC` (Will's + Bill's),
`FRA-MAR ENTERPRISES LTD` (Tony G's), `LACEY CORPORATION` (Jake's Bar), `TJ 5892 INC`
(Murphy's Tavern), `1976 LLC` (Scanlon's Saloon), `WAYNE TOWN USA, INC.` (The Great
American Pub), `BOLMAR ST`, `PEKING MEDIA LLC`, `PERKY CAFE` (The Perky).

**~37% of venues cannot be identified by name from the registry alone.** Every one of
them resolved cleanly by *address*. So the Places pass must key on address, not name,
and it is load-bearing for the whole corpus — not the optional enrichment SPEC §5
ranked third.

---

## 3. What this does to Phase 1

Phase 1's exit criterion is **≥400 venues with ≥1 validated deal**. Applying the
measured 13% dead-row rate and the 19% first-party yield:

| Corpus | Licensees | Real venues | Scrapeable deals | vs. the 400 target |
|---|---:|---:|---:|---|
| 11 suburban zones | 459 | ~400 | **~76** (CI 34–151) | misses by 5× |
| + Center City | 1,122 | ~970 | **~187** (CI 83–368) | misses by 2× |
| Whole 20-mi disc | 2,911 | ~2,520 | **~485** (CI 215–956) | clears it, but only just, and only by taking all of Philadelphia |

**Scraping alone does not reach 400 anywhere near King of Prussia.** The suburban
market a KoP user would actually use tops out around 76 venues from crawling.

---

## 4. Decisions this forces — for Paul

1. **Is 400 still the Phase 1 bar, or is the bar "the 11 zones are genuinely complete"?**
   ~76 scraped + photo/manual coverage of the rest is a *better* product than 485 venues
   spread across Philadelphia, but it fails the criterion as written.
2. **Expand the zone list?** 1,789 in-disc venues have no zone. Lower Providence is 4 miles
   from KoP and unzoned. Recommend adding ~8 zones before any crawl runs.
3. **Reorder the phases again?** Photo lane is currently phase 3. At 19% yield it is the
   difference between a half-empty directory and a live product. Recommend photo lane
   moves to phase 2, alongside "right now."
4. **Do social/third-party sources get promoted from "later" to "v1"?** They are the only
   evidence for 6 of the 13 venues that actually run a happy hour. SPEC §5 rates Instagram
   as ToS-hostile and recommends deferring it — that recommendation was made assuming a
   40% first-party yield.
5. **Google Places budget** (still open from the handoff). It is now confirmed *required*,
   not optional, and must resolve by address. ~2,900 lookups.

Nothing has been built past the seed script. Phase 1 waits on 1–4.
