# HANDOFF — start here next session (written 2026-09-02, late)

**This is the current entry point.** It supersedes
`HANDOFF-START-NEXT-SESSION-20260902-NIGHT.md`, whose §2 and §3 are both shipped
and live.

---

## 0. Where things stand, in one paragraph

Both builds the last handoff named are done and on the live site. A new guard
compares every published window against its own printed quote; it found **26 of
266 shipped cards** wrong, five of them live causes, and it has kept catching
things all evening. The board crossed a **state line**: northern Delaware is
seeded, Delaware's liquor law is encoded and signed off, and Wilmington is live
with 30 cards. Kennett Square opened with 5. Every card on the board has a
photo, and Delaware's listings are 96% photographed. **One thing is unfinished
and it is the first thing to pick up: the Delaware site crawl was still running
when the session ended.**

---

## 1. 🔴 THE ONE UNFINISHED THING — resume the Delaware crawl

It was running against `newark_de` and had three more zones to go. It is safe
to resume: `crawl_sites.py` skips any LID already in `crawl_hits.json` unless
you pass `--recrawl`, so **do not pass it**.

```sh
cd ~/happy-hour-finder
for z in newark_de hockessin_greenville new_castle_de middletown_de; do
    python ingest/crawl_sites.py --zone $z --render
done
python ingest/extract_deals.py
python ingest/crawl_roundups.py --write && python ingest/extract_roundups.py --show
python ingest/build_bundles.py
bash tests/run.sh
git pull --rebase && git add -A && git commit && git push origin master
for z in newark_de hockessin_greenville new_castle_de middletown_de; do
    python tests/live_front_door.py $z
done
```

🛑 **Never run two crawls at once**, and do not `git merge` while one is
running. `crawl_sites.py` loads `crawl_hits.json` at start and writes the whole
dict back at each checkpoint — a concurrent write is silently overwritten.

🛑 **`Casey's Drexel Hill` (lid `125992`) needs a re-crawl** for exactly that
reason: Codex added it mid-session, the running Delaware crawl rewrote
`crawl_hits.json` from its pre-merge copy, and the entry was lost. Its
`also_urls` survived in `venue_sites.json`, so this brings it straight back:

```sh
echo 125992 > run.lids && python ingest/crawl_sites.py --lids run.lids --recrawl --render
```

---

## 2. What is live right now

```
python tests/live_front_door.py wilmington     ->  LIVE, 30 of 30
python tests/live_front_door.py newark_de      ->  LIVE, 2 of 2
python tests/live_front_door.py kennett_square ->  LIVE, 5 of 5
python tests/live_front_door.py media          ->  LIVE, 11 of 11
python tests/live_front_door.py doylestown     ->  LIVE, 6 of 6
python tests/live_front_door.py west_chester   ->  LIVE, 19 of 19
bash tests/run.sh                              ->  518 tests, 0 fail
python tests/window_quote_check.py             ->  297 deals, 0 contradictions
```

**44 zones, 280 deal cards, 3,412 listings, 1,689 with a photo.**

| zone | cards | listings | photos | note |
|---|---|---|---|---|
| wilmington | **30** | 132 | 130 | new state |
| newark_de | 2 | 194 | 191 | **crawl unfinished** |
| hockessin_greenville | 5 | 92 | 91 | **crawl not started** — all 5 from roundups |
| new_castle_de | 0 | 85 | 83 | **crawl not started** |
| middletown_de | 0 | 58 | 56 | **crawl not started**; south of the canal |
| kennett_square | **5** | 26 | 24 | new PA zone |
| media | 11 | 41 | 38 | was 9 — Azie + Off the Rail |

**Spend today: about $47.** $5.81 seeding Delaware, ~$38 on the 29-zone
suburban photo sweep plus Delaware's, ~$3 of Places lookups.

---

## 3. 🛑 THE GUARD THAT SHOULD SHAPE THE NEXT SESSION

`tests/window_quote_check.py`, in `tests/run.sh`. It asks the one question 449
tests could not: **does a published window agree with the quote printed under
it?**

🔑 **It does not re-use the grammar that produced the window.** Calling
`windows_from()` on the quote again agrees with itself by construction and
would have *passed* Penn Taproom — the defect *was* that grammar. It reads the
quote the dumb way: every clock literal, every day word.

It found **five separate defect classes today**, three of them after it landed:

1. 🚨 **A day word we do not know reads as NO day, and no day means daily.**
   `weeknights` (Off the Rail), then `the working week` (Serum Kitchen). Both
   shipped weekends the venues never had. **This will recur.** The vocabulary
   is `WEEKDAY_RE` / `WEEKEND_RE` / `EVERYDAY_RE` / `DOW` / `DAY_CODE` in
   `extract_deals.py`.
   🎯 **Cheap next build:** a quote carrying a *day-ish* word the strict grammar
   cannot resolve should produce NO window, rather than a daily one.
2. **A window nobody stated.** `dedupe()` publishes the OVERLAP of two
   disagreeing quotes. Spasso's Media page says 4–6 and its *Philadelphia* page
   says 5–7; Media's board shipped 5–6. Other Half Brewing's Philadelphia card
   shipped **Buffalo, New York's** hours. Pier Bar's came from a customer
   review embedded on its own homepage.
3. **The card printed the richest quote, not a surviving one.**
4. **A dated one-off event read as a weekly window** — and its inverse, N dated
   entries at ONE clock being a real schedule.
5. **A venue removed from the corpus went on publishing** (§5).

---

## 4. 🎯 THE NEXT BUILDS, in order

### a. Finish the Delaware crawl — §1. Everything else waits behind it.

Newark should be rich: Main Street is a college drinking strip and
`delawaretoday.com/food/outdoor-dining-newark/` already matches 13 venues (all
refused for stating no clock — a *reading* problem, not a reach one).

### b. Delaware's roundup outlets are half-explored

| county / state | outlet | proven |
|---|---|---|
| Chester | `vista.today`, `countylinesmagazine.com` | yes |
| Bucks | `bucksco.today` | yes |
| Delaware Co. | `delco.today` | yes |
| Delaware (state) | `delawaretoday.com`, `visitwilmingtonde.com` | **yes, today** |
| Montgomery | `montco.today` | **not yet** |
| Delaware (state) | `outandaboutnow.com` — Wilmington's nightlife magazine | **not yet** |

### c. The unknown-day-word guard — §3, item 1.

### d. Philadelphia photos — ~1,150 venues, ~$45. Paul's call, deliberately
not made. The suburbs and Delaware are done.

---

## 5. What else changed, and why it matters beyond its own bug

Full write-ups are in **`ARCHITECTURE-MENU-INGEST.md`** (8 new sections) and in
`umbrella-arcades/Knowledge-Graph.md` (3 entries). The short list:

- **The shell licence resolves now** — three faults at once. `looks_like_a_
  geocode()` only fired on a bare-address answer, so a shell name that dragged
  the search onto a *neighbour* never reached the fallback; the nearby search
  was ranked by POPULARITY, returning the ten best-known bars on State Street
  rather than the one we were standing on; and `109-111 W STATE ST` only ever
  compared its first number. Media gained six real names.
  🔧 **Re-run `discover_places.py --zone Z` on any zone whose misses read
  "street number disagrees".**
- 🔑 **`EVIDENCE_SAFE_MATCHES` was a set of string literals `resolve()` has
  never returned.** Every venue the address fallback ever rescued was silently
  held out of the crawl frontier. *A producer and consumer agreeing by string
  equality drift with nothing failing.*
- 🔑 **`shipped_with_a_photo()` read only `zone-*.json`.** KoP read as 18 of 49
  covered when the board draws 48 — a 29-zone sweep offered to re-buy most of
  the photos the site already has.
- 🔑 **A named zone is the scope; the radius only bounds what is not named.**
  Adding Kennett Square seeded 1 of its 97 licences. Six other zones had been
  silently clipped: Warminster 49→74, Doylestown 41→55, Pottstown 47→56,
  Souderton 47→55.
- 🛑 **`", DE"` is not a location.** A Places search for "brewery in Hockessin,
  Delaware" returned Crooked Hammock Brewery in **Lewes**, 90 miles south, plus
  16 more from Rehoboth, Dover and Smyrna. Northern Delaware is now a box.
- 🛑 **A venue removed from the corpus went on publishing.** `extract_deals`
  walks `crawl_hits.json`, an archive that is never pruned. `build_bundles`
  refuses such a deal at the door — *which is why nobody noticed*: the card
  never shipped but the corpus and the coordinate cache still carried it.
  Refusing it upstream turned up **98** of them.
- 🛑 **A gazetteer is the wrong tool for out-of-market cities, and it was
  tried.** Matching URL paths against GeoNames' US place list **cost 27 cards to
  win 2**: `/happy-hour/` is refused because *Happy, Texas* exists. Measure what
  a filter costs before believing it is precise.
- 🛑 **Never write a backslash escape through a bash heredoc.** Third time in
  two days. This time a silent no-op: two regex edits reported success and did
  not land.

---

## 6. 🇺🇸 Delaware is a different KIND of place, and the difference is written down

**Read `ingest/seed_places_de.py`'s docstring before quoting any DE coverage
number.**

Pennsylvania starts from the PLCB's own list of everyone licensed to pour — a
**DENOMINATOR**, so "did we miss a bar?" is answerable. Delaware publishes no
equivalent, so its seed is **Google's opinion of what is there**: a good working
list and a bad denominator.

- "0 of 40 publish a happy hour" in Newark ≠ what it means in Media.
- A Delaware bar Google does not list is invisible **and we cannot know it**.

`middletown_de` is **south of the C&D Canal** — the one zone to delete if the
brief is literally "above the canal".

**The law:** `validate_pa.RULES["DE"]`, authority **4 Del. Admin. Code § 908
Rule 3.0** (eff. 02/01/16) + Delaware OABCC, signed off by Paul 2026-09-02.
🔑 **Delaware sets no hour cap and no cutoff** — copying PA's numbers would have
refused a lawful five-hour Wilmington happy hour, and would have *looked right*
because the two states' banned lists happen to agree. 🛑 And the `RULES` table
was **decorative** until today: `validate_deal()` read the PA constants
directly, so adding a Delaware row would have changed nothing.

---

## 7. Carried forward, still open

- **The Delaware crawl** — §1. And **Casey's Drexel Hill** needs a re-crawl.
- **No `ANTHROPIC_API_KEY` in this repo's `.env`.** The scoped model pass still
  cannot run. 🛑 Never borrow another repo's key.
- **Ground truth still has no confirmed row for any town.** Every number here is
  measured against our own output. **Paul's minute on a town remains the only
  real accuracy number** — and Delaware has never had one at all.
- **The oldest card still shipping is off a March 2019 article** (Two Stones Pub
  Wilmington). The card names the outlet and the month, which is the design, but
  whether 2019 is inside the label's usefulness is Paul's call. Two rows from
  2009 and 2016 were removed as traps.
- **Service worker / stale board** — carried from four handoffs back, untouched.
- `build_bundles.py` still reports `3 licensed venues sit outside every zone`.
- **Codex works in this repo too.** It pushed twice mid-session (`a7ed406`
  Casey's + a render retry on a blocked fetch + `--lids` scoped re-extraction;
  `a34caa6` a rendered-menu-artifact audit). **Pull before you push.**
