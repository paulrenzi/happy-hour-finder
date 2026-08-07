# Handoff — happy-hour-finder, 2026-08-07 (coverage)

Supersedes `HANDOFF-2026-08-06-NIGHT.md`. Repo is standalone; its own `.env`
only. Live: https://paulrenzi.github.io/happy-hour-finder/

Paul's brief: *"we need to triple these lists, especially in phoenixville, KOP
and Conshohocken. I still see 4 entries in KOP. you're not doing something
right."*

## What the counts are now — shipped and verified live

| Zone | Was | Now |
|---|---|---|
| King of Prussia | 4 | **6** |
| Conshohocken | 4 | **5** |
| Phoenixville | 1 | **4** |
| Corpus | 132 | **154** |

**That is not tripled.** It is +50% on the corpus and 4x on Phoenixville. The
gap between this and 3x is measured below, venue by venue — it is not a mystery
and it is not scarcity.

Verified by fetching the live artifacts with a cache-buster and diffing against
the local build, per the standing rule. `sw.js` live and local both read
`hhf-2026-08-06-154-c3beea14`; all three zone bundles byte-match; CI run
31141829401 `completed success`.

## Paul was right that something was wrong. Five things were.

Every one of these was in our code. None of them was the corpus being thin.

**1. A 403 on robots.txt was being recorded as the venue disallowing us.**
210 of 886 crawled venues — 24% — carried `"robots.txt disallows"` in
`crawl_hits.json`. A 401/403 is the old convention for "stay out entirely", and
`robots_for` applied it faithfully; it is also what a WAF returns to anything
that is not a browser. I re-fetched robots.txt for eight of them by hand and
**all eight allow us outright** (`Disallow:` empty, or only `/wp-admin/`).

The last handoff carried this forward as a property of four venues —
*"robots.txt disallows us: City Works, Hooters, Sullivan's, Buffalo Wild
Wings"* — and set hand-verification as the next task. **They crawl fine.** City
Works returned 4 quotes, Sullivan's 5, Hooters 1, on a plain recrawl. Sullivan's
is now published.

Fixed: retry once before believing a 403, and record an unreadable robots.txt as
its own distinct result so it is never again read as the venue's answer.
Corpus-wide recrawl of the affected hosts: **210 → 73 blocked, and only 7 of
those are genuinely unreadable.** Venues holding a deal quote went 258 → 321.
The rest of the 73 are marriott.com, hyatt.com and netflix.com, which really do
disallow.

**2. `verify()` stripped the apostrophe from the licensee but not from the page.**
`clean_name` turns `CREEDS SEAFOOD & STEAKS` into `creeds`; creedskop.com writes
"Creed's". The two halves could never meet. Creed's, Morton's and Dave &
Buster's were all failing this with correct seed URLs already on file.

**3. A PLCB store number was being required on the page.** `SEASONS 52 #4510`
asked the page to say "4510"; `YARD HOUSE 8371` asked for "8371". Unprovable by
construction. Now stripped — but only on a `#` marker or a run of four or more
digits, so Stable 12 and Catch 101 keep theirs.

**4. "coming soon" marked a page as parked.** Bowen Arrow Winery says it about
four wines. A placeholder is a placeholder because the phrase is nearly all the
page has, not because the phrase appears — so it now only disqualifies a page
under 1500 characters.

**5. The crawler could not see `4p` as a time — the largest loss of the five.**
`CONTEXT_RE` matched `am|pm` but not the single-letter form. Pepperoncini's page
reads `Happy Hour` / `in the bar area` / `mon - fri` / `4p - 6p`, and the two
context slots went to the day line and a `$2 OFF` line while the line holding
the actual window was invisible. The venue was then dropped for "stating no
schedule". `TIME_RE` in the extractor had the same blind spot, and `h24`
compares the whole string, so an unexpanded `p` would have silently published a
4pm happy hour as 04:00.

Now the window gets first refusal on the two slots, and a bare meridiem is read
as the same claim as `pm` — still requiring a word boundary, so "buy 4 - 6
pizzas" is not a window.

### One regression, caught and pinned

My first version of the fix also reached further down the page for a time. That
made things worse: Fogo de Chão's `$6 Beers` line acquired the dining room's
`Mon - Thu 3:00 PM - 9:30 PM`, which is opening hours, fails the four-hour cap,
and **un-published a venue that had been correct.** BOTLD broke the same way.
Neither the span nor the slot count moves now — only the ordering within the
slots. Both cases are pinned:
`test_a_match_that_already_has_context_pulls_in_nothing` and
`test_two_windows_under_one_heading_both_survive`.

## New mechanism: a seed may carry a trade name

`site_seeds.json` entries may now be `{"url": ..., "name": "The StoneRose"}`.
`COLD RIVER LLC` at 822 Fayette St is the StoneRose, and no page of theirs will
ever say "cold river" — so neither the stem guess nor a bare seed could reach
it, because the name half of `verify()` was asking for a name the venue does not
use.

**It is not a bypass.** The supplied name is what `verify()` then requires the
page to show, alongside the town, exactly as the licensee's own would. It also
becomes the card's display name, so the deal ships as "The StoneRose" rather
than under a holding company.

**Every lead was found by searching the STREET ADDRESS, never the name.** That
is not a style preference. Searching by name is what made me briefly conclude
Rivertown Taps was missing from the corpus — it is in it, correctly joined,
under `226 BRIDGE STREET LLC`. The ~37% shell rate makes name-absence worthless
as evidence.

15 sites proven in the three towns (was 1), plus 9 more corpus-wide for free
from the rule fixes alone.

## Joins

- **Charkoal's was not a mis-join.** Same venue, rebranded from Gaucho's Prime.
  The address join was right and the *site* had gone stale, so a live happy hour
  was shipping under a name the building no longer uses — the Bonchon failure
  again. Now `charkoals.com`, display name corrected. Pinned.
- **Founding Farmers is not a mis-join either.** That URL is correct; it returns
  **403** to our crawler. Nothing to fix in the data.
- **Two real ones dropped**: First Watch was not the Residence Inn at 127 S Gulph
  Rd; PrimoHoagies was not the Giant at 700 Nutt Rd. Both neighbours in the same
  plaza. Nothing substituted — absent beats publishing under another business's
  name. Pinned by `test_a_neighbours_site_stays_dropped`.

## ⏳ Running when this was written

A corpus-wide recrawl of the **other 26 zones** is in progress
(`scratchpad/recrawl_all.log`). The three towns are already done; the quote and
meridiem fixes have *not* yet been applied to the other ~800 venues, and this is
the single biggest remaining lift for the overall count. When it finishes:

```
python ingest/extract_deals.py && python ingest/validate_pa.py
python ingest/build_bundles.py && python ingest/geocode_venues.py
python -m unittest discover -s tests && node --test tests/time_math.test.mjs
git add -A && git commit && git push && gh run list --limit 3
```

`crawl_sites.py` writes after every venue, so an interrupted run is safe and
resumable — `--recrawl --zone <z>` picks up wherever it stopped.

## The remaining gap to 3x, named

Corpus funnel now: 917 crawled → 324 with a quote → **164 "quote states no
schedule"** → 150 kept. The no-schedule bucket is now the biggest single loss.

**In the three towns specifically, what is still missing and why:**

| Venue | Why it is not published |
|---|---|
| City Works (KoP) | Its KoP page links two food menus and a charity event, no happy-hour page, and its sitemap returns nothing. Not reachable. |
| Founding Farmers (KoP) | 403 to our crawler. |
| Stable 12 (Phoenixville) | `www.stable12.com` returns **403** (Cloudflare). Real site, real block. |
| Bistro on Bridge (Phx) | 10 quotes, prices only — `$5 BEERS`, `$9 COCKTAILS` — the window is not in the page text. |
| il Granaio, Great American Pub (Conshy), Spring Hollow, Root Down, StoneRose | "Happy Hour" with no window anywhere the crawler reached. |
| Tommy's Tavern, Pizzeria Vetri | Genuinely state a day and no hours. Correct to drop — do not relax this. |
| Seasons 52, Yard House, Eddie V's | Darden location pages are 2.7 KB JS shells. Nothing to read. |
| Taku (KoP) | `takusteakhouse.com` is a **different Taku** (Kokomo/Columbus, Indiana). The seed is a bad lead; `verify()` correctly refuses it. |
| Bald Birds (KoP) | Their site lists Audubon and Jersey Shore only. The KoP row may be unopened. |
| Wyatt Erb, Conshy Corner Tavern, Wild Rice | No live site. `wyatterb.com` is a "Launching Soon" stub; `conshycorner.com` and `wildricepa.com` do not resolve. |

**The two levers that would actually get to 3x**, in order of size:

1. **The 403 bucket.** Stable 12, Founding Farmers, CPK, Bonefish, Tommy Bahama,
   Eataly and others return 403 to `happy-hour-finder/0.1`. A browser User-Agent
   would very likely get through. **I did not do this and it is Paul's call** —
   robots.txt is honoured either way, but sending a browser UA to defeat a
   deliberate block is a different posture from the one this crawler has had,
   and it should be a decision, not a side effect of a coverage push.

2. **The photo lane.** Below.

**Also worth a look next session:** three real Phoenixville bars — Crowded
Castle Brewing, Gridiron Sports Bar — are not in `venues.csv` under any address
I could find. Check `seed_plcb.py`'s license-type filter; an "Eating Place
(Malt)" licence may be excluded. That is a corpus-scope question, not a join
question.

## Photo-upload pipeline (Paul's item 4) — blocked on a decision, not on work

The pick-and-preview UI ships and works. The rest does not exist, and it needs
something the project does not have: **a backend.** The site is static GitHub
Pages, so an upload endpoint, blob storage, vision extraction and moderation all
need somewhere to live. The two candidates each carry a commitment:

- **Cloudflare Worker + R2** — same shape as akumal-scooters, near-zero fixed
  cost, new account surface to manage.
- **oracle-vm** — already running, already carries the mgmt API — but it is
  under Oracle's idle-reclamation notice for ~08-18 and that is unresolved.

I did not pick one. It commits ongoing cost and ops, and the oracle-vm option
may be gone in eleven days.

## Standing constraints (unchanged)

- 🛑 Do not relax the price pass's evidence check, the window requirement, or
  the address join to raise the venue count. Nothing above did: the window fix
  makes a window that is *on the page* reach the extractor, it does not lower
  the bar for what counts as one.
- 🛑 No map.
- 🛑 The join is on **address, never name**.
- Scan for stale crawler processes before every run — each holds its own
  in-memory snapshot of `crawl_hits.json` and rewrites the whole file per venue.
- After every deploy push: `gh run list`, confirm success, then fetch the LIVE
  artifact and read the value that changed.

## Gate before any commit

```
python -m unittest discover -s tests      # 113 tests
node --test tests/time_math.test.mjs      # 29
python ingest/validate_pa.py              # 8/8
python ingest/build_bundles.py            # also stamps web/sw.js
gh run list --limit 3                     # AFTER the push
```

To reproduce CI locally (it has no `requests`):
`PYTHONPATH=<dir with a requests.py that raises> python -m unittest discover -s tests`
— confirmed green this session.
