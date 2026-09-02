# HANDOFF — start here next session (written 2026-09-02, late)

**This is the current entry point.** It supersedes
`HANDOFF-START-NEXT-SESSION-20260902-NIGHT.md`, whose §2 and §3 are both now
shipped and live.

---

## 0. Where things stand, in one paragraph

Both builds the last handoff named are done and on the board. The roundup lane
learned to name a venue in the middle of a sentence, and a new guard compares
every published window against its own printed quote — it found **26 cards on
the shipped board**, of which **five were live causes** and all five are fixed.
The board crossed a **state line**: northern Delaware is seeded, Delaware's
liquor law is encoded and signed off, and Wilmington opened with 16 cards.
Kennett Square opened with 4. Every card that has a happy hour now has a photo.

---

## 1. What is live right now

```
python tests/live_front_door.py media          ->  LIVE, 11 of 11
python tests/live_front_door.py wilmington     ->  (verify after the push)
bash tests/run.sh                              ->  503 tests, 0 fail
python tests/window_quote_check.py             ->  0 contradicting their own quote
```

| zone | before today | after | note |
|---|---|---|---|
| media | 9 | **11** | Azie + Off the Rail, the acceptance test |
| kennett_square | — | **4** | new PA zone |
| wilmington | — | **16** | **new state** |
| west_chester | 22 | 22 | items way up: Santino's 2→11, 9 Prime 3→12 |

**Spend today: about $9 total.** $5.81 seeding Delaware, ~$1.30 finishing the
board's photos, ~$1 of Places lookups, the rest on the suburban photo sweep.

---

## 2. 🛑 THE GUARD THAT SHOULD SHAPE THE NEXT SESSION

`tests/window_quote_check.py`, now in `tests/run.sh`. It asks the one question
449 tests could not: **does a published window agree with the quote printed
under it?**

🔑 **It does not re-use the grammar that produced the window.** Calling
`windows_from()` on the quote again would agree with itself by construction and
would have passed Penn Taproom, because the defect *was* that grammar. It reads
the quote the dumb way — every clock literal, every day word.

It has now caught **three separate defect classes in one day**, two of them
within minutes of landing:

1. **A day word we do not know reads as NO day, and no day means daily.**
   `weeknights` (Off the Rail), then `the working week` (Serum Kitchen). Both
   shipped a weekend the venue never had. 🔑 **This is a recurring shape. The
   next unknown day word will do the same thing silently.** A cheap next build:
   assert that a quote carrying a *day-ish* word which `days_in()` cannot read
   produces no window at all, rather than a daily one.
2. **A window nobody stated.** `dedupe()` publishes the OVERLAP of two
   disagreeing quotes. Spasso's Media page says 4–6 and its *Philadelphia* page
   says 5–7; the Media board shipped 5–6. Fixed by refusing another branch's
   quote (`another_branch()`), a review's quote, and by choosing a lead quote
   that actually survived.
3. **A dated event read as a weekly window.** Braeloch Brewing's whole site is
   an events calendar; three different Friday parties were intersected into a
   Friday 5–6pm it has never run.

---

## 3. 🎯 THE NEXT BUILDS, in order

### a. Finish Delaware — the crawl is the only thing left

Wilmington's 16 cards are almost all from **roundups**, not from the venues'
own pages. The site crawl of all five DE zones was running when this was
written; when it finishes, re-run:

```sh
python ingest/extract_deals.py
python ingest/extract_roundups.py --show
python ingest/build_bundles.py
bash tests/run.sh
python tests/live_front_door.py wilmington
```

`newark_de`, `hockessin_greenville`, `new_castle_de` and `middletown_de` had
**0 cards** at the time of writing purely because their crawl had not run yet.
Newark in particular should be rich: its Main Street is a college drinking
strip and `delawaretoday.com/food/outdoor-dining-newark/` already matched 13
venues (all refused for having no clock — those are a *reading* problem, not a
reach one).

### b. N dated entries at ONE clock is a schedule

The dated-event guard cost two cards. Marsha's South Street deserved to go —
"weekend pop-up Happy Hour". **The Pullman did not:**

```
Happy Hour / 04:30 PM - 06:30 PM / Wednesday September 2nd
Happy Hour / 04:30 PM - 06:30 PM / Thursday September 3rd
Happy Hour / 04:30 PM - 06:30 PM / Friday September 4th
Happy Hour / 04:30 PM - 06:30 PM / Saturday September 5th
Happy Hour / 04:30 PM - 06:30 PM / Monday September 7th
```

That is a standing happy hour published one evening at a time, and an
events-calendar CMS is how a lot of bars publish. **N ≥ 3 dated entries at the
SAME clock is a weekly schedule; N entries at different clocks (Braeloch: 2–6,
6–9, 5–8) is a party listing.** Braeloch stays off under that rule and The
Pullman comes back, which is the test.

### c. The roundup outlet list, one row per region

| county / state | outlet | proven |
|---|---|---|
| Chester | `vista.today`, `countylinesmagazine.com` | yes |
| Bucks | `bucksco.today` | yes |
| Delaware Co. | `delco.today` | yes |
| Montgomery | `montco.today` | **not yet** |
| Delaware (state) | `delawaretoday.com`, `visitwilmingtonde.com` | **yes, today** |

`outandaboutnow.com` (Out & About, Wilmington's nightlife magazine) is the
obvious untested DE outlet. `montco.today` is the obvious untested PA one.

---

## 4. 🛑 Delaware is a different kind of place, and the difference is written down

**`ingest/seed_places_de.py` opens by saying what its seed IS NOT.** Read it
before quoting any Delaware coverage number.

Pennsylvania starts from the PLCB's own list of everyone licensed to pour. That
list is a **DENOMINATOR** — every coverage fraction in this repo is a fraction
of it, and "did we miss a bar?" is answerable. Delaware publishes no
equivalent: its open-data portal has business licences with no liquor signal
(`RETAILER RESTAURANT`, 2,497 statewide) and the ABC licensee list is not
machine-readable.

So the Delaware seed is **Google's opinion of what is there**: a good working
list and a bad denominator.

- "0 of 40 publish a happy hour" in Newark ≠ what it means in Media.
- A Delaware bar Google does not list is invisible to us **and we cannot know
  it**. In Pennsylvania that class is measurable. Here it is not.

`middletown_de` is **south of the C&D Canal**. It is the rest of New Castle
County and rides with the north commercially; if the brief is literally "above
the canal" it is the one zone to delete.

### The law

`validate_pa.RULES["DE"]`, authority **4 Del. Admin. Code § 908 Rule 3.0
"Prohibited Practices"** (eff. 02/01/16) plus the Delaware OABCC, signed off by
Paul 2026-09-02.

🔑 **Delaware sets no hour cap and no cutoff.** No 4h/day, no 24h/week, no
midnight rule — its law governs the *shape* of the offer, not its length. This
is exactly why the old comment forbade copying PA's numbers across: a lawful
five-hour Wilmington happy hour would have been refused for breaking a
Pennsylvania cap, and it would have **looked right**, because the two states'
banned lists happen to agree almost exactly. `DE_BANNED` is therefore written
out rather than aliased.

🛑 **And the table was decorative until today.** `validate_deal()` read this
module's PA constants directly, so `RULES` existed, `rules_for()` had exactly
one caller, and adding Delaware to it would have changed **nothing**. It now
takes the state. *A table keyed by jurisdiction that nothing reads is not a
per-jurisdiction rule.*

---

## 5. What else changed, and why it matters beyond its own bug

- **The shell licence resolves now.** `looks_like_a_geocode()` only fired when
  Places answered with a bare street address, so a shell name that dragged the
  search onto a *neighbour* never reached the nearby fallback at all. Plus:
  nearby search was ranked by POPULARITY (returning the ten best-known bars on
  State Street rather than the one we were standing on) and a hyphenated
  frontage `109-111` only ever compared its first number. Media gained six real
  names — Off the Rail, Maris, Tap 24, Broad Table Tavern, John's Grille,
  Pairings Cigar Bar. **Re-run `discover_places.py --zone Z` on any zone whose
  misses were "street number disagrees": every one is a candidate.**
- 🔑 **`EVIDENCE_SAFE_MATCHES` was a set of string literals, and `resolve()`
  has never returned one of them** (`"nearby search"` vs `"nearby search at the
  geocode"`). Every venue the address fallback ever rescued was silently held
  out of the crawl frontier as though a name had matched it. *When a producer
  and its consumer agree by string equality, nothing fails when they drift.*
- 🔑 **`shipped_with_a_photo()` read only `zone-*.json`.** The venues WITHOUT a
  window live in `venues-*.json` and carry their photos there. King of Prussia
  read as 18 of 49 covered when the board draws 48 — so a 29-zone sweep offered
  to re-buy most of the photos the site already has. The same miscount that
  function was written to prevent, one file along.
- 🔑 **A guard on one link of a chain is a memorial to the link that failed
  last time.** The dated-event guard had to go in THREE places: the clause loop
  and both fallbacks, which re-read `days_in()` over the whole quote and let the
  window back in by the back door.
- 🛑 **Never write a backslash escape through a bash heredoc.** It happened
  again today: two one-line regex edits reported success and did not land.
  `days_in('all working week')` still returned nothing and the file was
  unchanged. Use the Write/Edit tool for any patch containing a backslash.
- 🛑 **Rebuild the base and the bundles BETWEEN photo runs.** Coverage is read
  off the shipped bundles, so a second run before the rebuild re-bills every
  venue the first one fetched. `ingest/photo_sweep.sh` does it for you.

---

## 6. Photos

**Every card with a published window has a photo (240/240 at the time of
writing).** Four of the last seventeen were refused because the search asked
Google with the *licensee* name — a shell licence is exactly the row whose
photo is missing — so `--from-board` now asks with the name the CARD shows.

Paul's call, this session: **suburbs now, Philadelphia later.** The 29 suburban
zones were swept (~940 venues, ~$37). **Still open: the six Philadelphia zones
plus `center_city`, about 1,150 venues and roughly $45.** That is a separate
decision, not an oversight.

---

## 7. Carried forward, still open

- **`newark_de`, `hockessin_greenville`, `new_castle_de`, `middletown_de` have
  0 cards** — their crawl had not finished. §3a.
- **The Pullman lost its card** to the dated-event guard and should get it
  back. §3b.
- **No `ANTHROPIC_API_KEY` in this repo's `.env`.** The scoped model pass still
  cannot run. 🛑 Never borrow another repo's key.
- **Ground truth still has no confirmed row for any town.** Every number here is
  measured against our own output. **Paul's minute on a town remains the only
  real accuracy number** — and Delaware has never had one at all.
- **Service worker / stale board** — carried from four handoffs back, untouched.
- `build_bundles.py` still reports `1 deal(s) matched no venue in the base`
  (Desmond Hotel Malvern) and `3 licensed venues sit outside every zone`. Both
  pre-existing, both one-line data fixes nobody has picked up.
- **Codex is working in this repo too.** It pushed `a7ed406` (Casey's Drexel
  Hill, plus a render retry on a blocked fetch and a `--lids` scoped
  re-extraction) mid-session. Pull before you push.
