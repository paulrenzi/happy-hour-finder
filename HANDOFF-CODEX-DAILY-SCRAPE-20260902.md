# HANDOFF — the roundup lane is the yield, and the daily town job (for Codex)

**Written 2026-09-02, after the analysis session Paul asked for in
`HANDOFF-RE-ANALYZE-THE-ARCHITECTURE-20260902.md` §3.** Read that file's §0–§2
first for the funnel; this file is the answer to its §3 and the spec for the
recurring job that follows.

---

## 0. The §3 answer — was the deal in HTML we had?

**No. 0 of 12.** The 26 "crawled fine, published nothing" West Chester venues
were pulled by hand. 12 are not happy-hour venues at all (three Giants, Panera,
a maltster, a theater, two bottle shops, a wine shop, a roast-beef counter, a
fine-dining BYOB) — **the silent set is 14, not 26**. Of the 12 real bars looked
at, the venue's own site carried the happy hour for **none** in text we could
read:

| where the deal actually lives | venues |
|---|---|
| a magazine roundup, not the venue's site | Santino's, Artillery, Wrong Crowd, dolce Zola, Kildare's (hours), Sedona (roundup + own site) |
| an image on the venue's own site (`Daily Drink Specials…PNG`) | Saloon 151 |
| a third-party listing only (OpenTable, Happy Hopper) | Goal Line, Kooma, Jolene's |
| no evidence of a happy hour anywhere | Four Dogs, Levante, Ground Provisions, Pica's |

Wrong Crowd's drink menu **was rendered** (197 lines) and still had nothing —
so `render_wanted()`'s gate was not the lead. The crawl→regex→model
architecture was not the failure on these venues; **the venues do not publish
the thing on their own sites.** Fixing that venue-by-venue never finishes, as
the previous handoff said.

**One County Lines Magazine article (May 2024) names 27 West Chester bars with
days, clocks and prices.** Joined to the base: 9 were already on the board, 6
had quoted from their own site and never reached the board, 5 were silent on
their own site, 8 are not in the licence base (your §5 `unmatched` list, now
with a second source agreeing).

`ingest/crawl_roundups.py` had existed since 2026-08-06, had never produced a
`roundup_hits.json`, was consumed by nothing, and discarded that article on
sight (`ROUNDUP_MAX_AGE_DAYS = 120`).

## 1. What changed this session (all shipped, `tests/run.sh` 0 fail, 419 tests)

- **Roundup lane finished.** `data/roundup_sources.json` (two County Lines
  pieces for `west_chester`) → `ingest/crawl_roundups.py --write` →
  **new `ingest/extract_roundups.py`** → `data/deals_roundup.json` → merged by
  `build_bundles.py` at rank 4 (below photo, seed, model-read, extractor). Own
  tier, `source.kind: roundup`, capped `unconfirmed`, never outranks the
  venue's page — Paul's 2026-08-06 rule, unchanged.
- **Age is a LABEL, not a discard.** An old article ships with the outlet and
  month on the card ("Source: County Lines Magazine (May 2024)"), written by
  `sourceLink()` in `web/app.js`. `stale_days` is on the hit. `fresh_enough()`
  still answers the 120-day question, it just no longer decides.
- **`mentions()` rewritten**: heading + paragraph, not "the six lines after a
  name". The County Lines page repeats and PAIRS headings, so a paragraph is
  matched to the queued heading it names, newest first. Both the licensee name
  and the trade name (`osm_name`) are indexed — the article says Santino's,
  the licence says Rams Head.
- **One inference, written down**: inside a happy-hour article a bare
  "4 to 6" is a PM range (`pmify()`). Everything after that is the extractor's
  own `windows_from()`, unmodified. Clause-split so "…4 to 6, and can be
  paired with **daily** drink specials" no longer reads as every day.
- **Item labels cut from prose are refused as clauses** — "and the apps are
  half-off" at $5 was the margaritas' price on the apps. A wrong item is worse
  than a missing one.
- **Sedona Taphouse West Chester was losing its fully-read card to Lascala's
  Fire** because both are at 44 W Gay St and `merge_venues()` keyed duplicates
  on address alone. Now an address match is a duplicate only when a name
  agrees (`name_agrees`, incl. the PLCB shell name). This was the one true
  "selection logic" bug in the §3 list.
- `extract_deals.py --rejects` crashed on a venue with no quotes (IndexError).

**West Chester: 13 → 20 cards. $0 spent. card/quote 65% → 100%.** Live check
after the push: `python tests/live_front_door.py west_chester`.

## 2. The daily town job — what Codex should build

The pipeline for ONE town, in order, all stdlib+requests, no model unless the
step says so. Every step is idempotent and reads/writes files in `data/`.

```
# 0. pick the zone id from data/zones.json (38 exist; adding one = adding a
#    row there with its municipalities; the licence base comes from data/venues.csv)
ZONE=west_chester

# 1. websites for licensees that have none (PAID, ~$2/town, Google Places;
#    key is GOOGLE_PLACES_API_KEY in happy-hour-finder/.env, never another repo's)
python ingest/discover_places.py --zone $ZONE --dry-run      # scope first
python ingest/discover_places.py --zone $ZONE --merge-sites --execute

# 2. venues worth re-fetching (website AND (no deal OR no items)) -> lids file
python ingest/needy.py $ZONE --show --lids run.lids

# 3. crawl those sites, rendering where the gate says so (free, robots obeyed)
python ingest/crawl_sites.py --lids run.lids --recrawl --render

# 4. regex read of what the crawl quoted (free)
python ingest/extract_deals.py

# 5. ROUNDUPS -- the yield step. Find 1-3 dated local articles for the town
#    ("<town> happy hour" on the outlets in §3), add rows to
#    data/roundup_sources.json {url, outlet, zone_id}, then:
python ingest/crawl_roundups.py --write
python ingest/extract_roundups.py --show

# 6. (optional, PAID, sonnet) the model passes, scoped to run.lids only:
#    reach_llm.py, read_menus_llm.py, read_pages_llm.py, extract_prices_llm.py
#    -- see HANDOFF-SCOPED-RUNS / project_hhf_scoped_runs_not_full_corpus.
#    Never --zone on a big town, never the corpus. Budget per town ~$2.

# 7. build, test, ship
python ingest/build_bundles.py
bash tests/run.sh
git add -A && git commit -m "hhf: <zone> daily -- N->M cards" && git push origin master

# 8. prove it is live (the ONLY liveness check; GitHub Pages lags a few minutes)
python tests/live_front_door.py $ZONE
```

Standing rules that survive the handoff:
- 🛑 **One town per run. Never the corpus.** `needy.py` is the scope.
- 🛑 **Robots obeyed** (`crawl_sites.allowed`). 2 s between hits to a host.
- 🛑 **Grounding**: every span a literal substring of the document; `build()`
  re-checks against the file on disk. A roundup deal carries the paragraph.
- 🛑 **A web page is verified by running it** — `live_front_door.py`, not a 200.
- 🛑 **A wrong item is worse than a miss.** Refuse, don't guess — except the
  two named inferences (clock + no days = every day; bare range in a
  happy-hour article = PM).
- Commit `web/data/*` with the run: the site IS the built bundles.

## 3. Where roundups come from (the human minute, now a search)

Local outlets that publish dated happy-hour lists for these towns — the
discovery is a web search for `"<town>" happy hour` restricted to them:
`countylinesmagazine.com`, `mainlinetoday.com`, `vista.today`, `phillymag.com`,
`inquirer.com`, `philly.eater.com`, `downtownwestchester.com`, `whyy.org`,
`patch.com`, local BIDs / "downtown X" sites. `published_date()` refuses an
undated page; `mentions()` needs the venue to be in the base under either its
licensee or trade name. A one-word venue name matches only as a HEADING.

## 4. Expanding beyond the western suburbs — read before scheduling "new areas across the US"

Three things are Pennsylvania-shaped and will refuse, by design, elsewhere:

1. **The licence base is PLCB** (`ingest/seed_plcb.py`, `data/raw/plcb_licenses_*.csv`).
   Every other state needs its own licensee export (most publish one: NJ ABC,
   NY SLA, DE OABCC, MD comptroller…) mapped into `data/venues.csv`'s columns
   and a zone row in `data/zones.json`. Without a licence base there is no
   denominator, no `needy.py`, and nothing to join a roundup's names to.
2. **The law is PA's.** `validate_pa.RULES` encodes Acts 57 & 86 (4 h/day,
   24 h/week, midnight cutoff, banned claims). **`RULES["DE"]` is empty ON
   PURPOSE** and `build_bundles.surviving()` fails CLOSED for any state
   without a ruleset — a DE bar cannot reach the board until DE's rules are
   encoded from a named authority **and Paul signs them off**. That is not a
   Codex decision. See `project_hhf_crossing_a_state_line`.
3. **The zone picker is a static list** (`data/zones.json`, 38 zones). New
   areas are added there; the PWA's service worker (`web/sw.js`) is stamped
   by the build, so a new zone ships with the next push.

So the honest sequence is: **PA towns first** (all 38 zones exist, ~30 have had
no discovery pass — that is where the daily job earns its keep for weeks),
then one new state with its licence export + ruleset as a separate, signed-off
piece of work.

## 5. Open, carried forward

- **Service worker / stale board** (§3.4 of the previous handoff): a user with
  the PWA installed can hold an old board. Not touched this session.
- **Saloon 151's `Daily Drink Specials…PNG`** — the deal is an image on the
  venue's own site; the vision pass (`extract_menu_images.py`) is the tool,
  not run this session (costs money).
- **Stove & Tap's "Tappy Hour"** and **dolce Zola's "20% off, Tue–Thu"** (no
  clock) are refused correctly; the article's grammar, not ours.
- **Ground truth still has no confirmed row for any town** — every number here
  is measured against our own output. Paul's minute on
  `data/ground_truth/west_chester.json` is still the only real accuracy number.
