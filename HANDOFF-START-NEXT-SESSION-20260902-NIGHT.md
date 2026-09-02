# HANDOFF — start here next session (written 2026-09-02, night)

**This is the current entry point.** It supersedes
`HANDOFF-DAILY-TOWN-JOB-20260902-MEDIA.md`, `HANDOFF-DAILY-TOWN-JOB-RUNNING-20260902.md`
and `HANDOFF-CODEX-DAILY-SCRAPE-20260902.md` §2 as the thing to read first.

Everything below is shipped, pushed and **verified live**. Nothing is half-done.

---

## 0. Where things stand, in one paragraph

The daily one-town job now runs end to end, twice proven. The roundup lane learned to
join a venue **by street address** when its liquor licence is a corporate shell, which
put four previously unreachable bars on the board. **Media** was worked as the next
town off the rotation and went 5 → 9 cards for $0. Six silent defects were found and
fixed along the way, all guarded by tests. The next build is **named, evidenced and has
a written acceptance test**: a roundup that names the venue mid-sentence.

---

## 1. What is live right now

```
python tests/live_front_door.py doylestown    ->  LIVE, 6 of 6
python tests/live_front_door.py media         ->  LIVE, 9 of 9
python tests/live_front_door.py west_chester  ->  LIVE, 22 of 22
bash tests/run.sh                             ->  449 tests, 0 fail
```

| zone | cards before today | after | who arrived |
|---|---|---|---|
| doylestown | 4 | **6** | Penn Taproom, Maxwell's On Main (MOMs) |
| west_chester | 20 | **22** | Jitters, Side Bar & Restaurant |
| media | 5 | **9** | La Catrina, Luna's Mexican Grill, Sligo Irish Pub, State Street Pub |

A full rebuild of `venue_base.json` **and** the bundles produces **no diff**, so the
published board matches the corpus exactly. The working tree is clean in both repos.

**Cost today: $0.** 44 Google Places lookups for Media, inside the 1,000/month free
tier. 🛑 **No model passes ran, and none can** — this repo's `.env` still has no
`ANTHROPIC_API_KEY` and must never borrow another repo's.

### Commits (all pushed)

| repo | commit | what |
|---|---|---|
| happy-hour-finder | `c7ec4e6` | the roundup address join + the wrong-clock and cut-label fixes |
| happy-hour-finder | `ada9a69` | media 5 → 9, the chain guard, the Frosted Mug drop |
| happy-hour-finder | `d462443` | the Media handoff |
| happy-hour-finder | `f328a99` | **the playbook** — 8 new sections + 5 standing rules |
| umbrella-arcades | `bb9eff3` | **the Knowledge Graph** — 3 entries, + a backspace-byte repair |

---

## 2. 🎯 THE NEXT BUILD — a roundup that names the venue MID-SENTENCE

This is the one thing to pick up. It is evidenced, scoped, and has an acceptance test.

`DELCO.today` is the Delaware County sibling outlet (same publisher network as
`bucksco.today` and `vista.today`). Four of its articles are already in
`data/roundup_sources.json` for `media`. All four **crawl cleanly, date cleanly, and
match zero venues.**

🛑 **Zero is a document-shape defect, not an absence of happy hours.** Checked by hand:

- *"**Azie** in Media has a happy hour on weekdays from **4 to 6 PM**"* — and
  `Azie Media` (lid 58431) is in our base.
- *"**Off the Rail**, also in Media, has **$3 domestic beers** during happy hours
  weeknights, **4 to 6 PM**"*

Two reasons nothing matched, both in `ingest/crawl_roundups.py`:

1. **These articles are prose, not lists.** The venue is named *inside a sentence*, and
   `mentions()` requires a **heading**.
2. **The outlet's page template emits ~100 chrome lines that pass `is_heading()`** —
   `Commerce`, `Community`, `Search`, `About`, `Partner / Advertise`. They queue up and
   eat the real paragraphs.

### The build

- **Ignore the site chrome.** A heading that appears on *every* article from one outlet
  is navigation, not a venue. The four crawled pages make this cheap: the junk repeats
  across all four, the venues do not.
- **Match a venue named mid-sentence**, under the containment rule that already exists.
  🛑 `Sedona it is.` must still not be Sedona. The safe shape is narrow: the venue name
  and a happy-hour clause in the **same sentence**, matched on the **full multi-word
  name core**, never a single word.

**Acceptance test: Azie and Off the Rail on the Media board, 4–6 PM weekdays.**

The four source rows are left in place **deliberately** — they cost nothing, they date
cleanly, and they are the evidence. Do not delete them as "an outlet that doesn't work".

📖 Full write-up: `ARCHITECTURE-MENU-INGEST.md`, section *"THE ROUNDUP OUTLET LIST IS
REGION-SHAPED"*.

---

## 3. 🛑 The open hole worth fixing before it bites again

**Nothing compares a published window to the window its own quote states.**

Penn Taproom shipped a **4:30–6:00** card off a quote that plainly reads
*"4:30 to 6:30 PM"*. Every validator asks whether a deal is *well formed* and whether
its quote is *present in the source document*. **No check asks whether the two agree.**

The card and its own evidence contradicted each other in public, and the entire
449-test suite was blind to it. It was found by reading a card, not by a test.

🔑 A wrong window is worse than a missing one. This is the highest-value guard left
un-built, and it is cheap: re-read each shipped window's quote with the same grammar
that produced it and assert the result matches.

---

## 4. How to run the daily one-town job (the corrected sequence)

```sh
ZONE=<pick one>

# ---- DISCOVERY — THREE commands plus a base rebuild, in this order ----
python ingest/discover_places.py --zone $ZONE --dry-run          # scope + cost
python ingest/discover_places.py --zone $ZONE                    # THE PAID RESOLVE PASS
python ingest/discover_places.py --zone $ZONE --merge-sites --execute
python ingest/build_venue_base.py
python ingest/build_bundles.py                                   # 🔑 needy reads the BUNDLES

# ---- 🔑 CHECK THE RENAMES. The suite cannot see one. ----
git show HEAD:data/venue_base.json > /tmp/old.json    # then diff names

# ---- SELECT + CRAWL ----
python ingest/needy.py $ZONE --show --lids run.lids
python ingest/crawl_sites.py --zone $ZONE --recrawl --render     # FIRST run on a zone
# python ingest/crawl_sites.py --lids run.lids --recrawl --render  # every run after
python ingest/extract_deals.py

# ---- ROUNDUPS (optional, and region-shaped — see §5) ----
python ingest/crawl_roundups.py --write
python ingest/extract_roundups.py --show

# ---- SHIP ----
python ingest/build_bundles.py
bash tests/run.sh
git add -A && git commit && git push origin master
python tests/live_front_door.py $ZONE
```

🔑 **`build_bundles.py` is now part of the discovery half, not just the ship half.**
`needy.py` reads the **built bundles**, so a base rebuilt without a bundle rebuild
leaves the selection silently short — that is exactly what happened on Media (9 named
where there were 28). `needy.py` now warns on **every** link of the chain; heed it.

🔑 **GitHub Pages lags a push by ~1 minute.** All three zones failed
`live_front_door.py` on the first attempt today and passed on the second. A single
`NOT LIVE` straight after a push is a deploy in flight. Re-run before believing it —
and never call a zone live without running it at all.

---

## 5. Where to point the job next

`python ingest/report_funnel.py` — take any row marked `<- no discovery pass`.
**~27 PA zones remain.**

| zone | lic | sites | cards | note |
|---|---|---|---|---|
| `pottstown` | 47 | 20 | 2 | 29% card/quote — a **reading** problem, not a reach one |
| `springfield_delco` | 36 | 11 | 1 | **Delco** — DELCO.today covers it |
| `ridley_tinicum` | 53 | 10 | 1 | **Delco** |
| `norristown_bridgeport` | 47 | 11 | 1 | Montco — `montco.today` untested |
| `havertown` | 26 | 7 | 1 | small, cheap |
| `warminster_warrington` | 49 | 7 | 0 | **Bucks** — BUCKSCO.Today covers it |

🛑 The Philly zones (`center_city` 635 lic, `north_philly` 206, `northeast_philly` 127)
will each **blow the 1,000/month Places free tier on their own**. Budget them
deliberately; do not let the rotation wander into one by accident.

🛑 **West Chester stays stand-alone**, after the small towns. Unchanged.

**The roundup outlet list is region-shaped:**

| county | outlet | proven |
|---|---|---|
| Chester | `vista.today`, `countylinesmagazine.com`, Main Line Today | yes |
| Montgomery | `montco.today` | not yet |
| Bucks | `bucksco.today` | yes (Doylestown) |
| Delaware | `delco.today` | yes (Media) |

🔑 The search that works is `"<town>" happy hour` with `allowed_domains` set to that
list. A bare web search returns aggregator spam.

---

## 6. What changed in the code today, in one place

| file | change |
|---|---|
| `ingest/crawl_roundups.py` | the address join: `address_keys()`, `address_index()`, `address_venue()`, orphan second pass in `mentions()` |
| `ingest/extract_roundups.py` | `pmify()` no longer eats `4:30 to 6:30 PM`; `tidy_items()` cuts a conjoined label at the conjunction |
| `ingest/extract_deals.py` | `TRAILING_PRICE_RE` anchored on `\b` so a long dish name is cut at a word |
| `ingest/needy.py` | `STALE_CHAIN` — guards every link of sites → base → bundles |
| `ingest/discover_places.py` | `HAND_DROPPED` gains The Frosted Mug |
| `ingest/build_venue_base.py` | one `place_for()` both loops use, so a hand-drop actually drops |
| `tests/test_ingest.py` | +24 tests across 6 new classes |
| `data/roundup_sources.json` | 4 DELCO.today rows for `media` |

---

## 7. Standing rules that bit today (all now in the playbook)

- **A door outlives its tenants.** An address join must refuse when a *live* trade name
  disagrees with the article's heading — and must never hold a *licence-only* name
  against it, because the shell is the whole reason the join exists.
- **A guard on one link of a chain is a memorial to the link that failed last time.**
- **Dropping a join in one of two readers is not dropping it.**
- **A cut label is not a word, at both ends of a length cap.** Short by a whole word is
  a miss; short by three letters is a wrong thing on a card.
- **A rename is a silent drop.** Media renamed 16 venues in one discovery pass, all
  improvements, and the suite could not tell. Diff the base after any naming change;
  the two that changed **street** are where mis-joins hide.
- **A run that finds nothing is checked against one human minute** before it is
  reported as an empty town.
- 🛑 **Never write a backslash escape through a bash heredoc.** It lands a literal
  control byte, the patch reports success, and the code runs and is wrong. Cost an hour
  today; the same class had already put two backspace bytes into `Knowledge-Graph.md`
  the day before (repaired in `bb9eff3`).

---

## 8. Carried forward, still open

- **The mid-sentence roundup join** — §2. The next build.
- **No check that a window agrees with its quote** — §3. The best-value open guard.
- **No `ANTHROPIC_API_KEY` in this repo's `.env`.** The scoped model pass cannot run.
  Doylestown's card/quote is 55% and Media's 64% — the gap between a venue that quoted
  something and a venue that produced a card is exactly the population that pass exists
  for, and it is still unmeasured. 🛑 Never borrow another repo's key.
- **Service worker / stale board** — carried from three handoffs back, untouched.
- **Ground truth still has no confirmed row for any town.** Every number in this file is
  measured against our own output. **Paul's minute on a town remains the only real
  accuracy number.**
- **`build_bundles.py` still reports** `1 deal(s) matched no venue in the base` for the
  Desmond Hotel Malvern, and `3 licensed venues sit outside every zone`. Both are
  pre-existing, both are one-line data fixes nobody has picked up.
