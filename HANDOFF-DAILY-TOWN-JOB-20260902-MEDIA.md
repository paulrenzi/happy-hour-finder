# HANDOFF — the address join shipped, Media shipped, and the next outlet shape is named

**Written 2026-09-02**, after the second run of the daily one-town job. Supersedes
`HANDOFF-DAILY-TOWN-JOB-RUNNING-20260902.md` for §3 (now done) and §4 (media now done).
Its §1 sequence is still correct and was followed unchanged.

---

## 0. What shipped

**Two commits.** Both live, both verified by the only command that may say so.

### `c7ec4e6` — the roundup ADDRESS join (that file's §3, the named next build)

| zone | cards before | after |
|---|---|---|
| doylestown | 4 | **6** |
| west_chester | 20 | **22** |

The two venues that handoff named as the acceptance test are **on the board**:

- **Penn Taproom** — Mon–Fri 4:30–6:30 PM, Sun 3–5 PM
- **Maxwell's On Main (MOMs)** — daily 5–7 PM

Neither could ever be joined by name: Maxwell's licence is the shell
`37 N MAIN STREET ENTERPRISES LLC` and Penn Taproom's is `PA GRILL ROOM LLC`.
West Chester gained **Jitters** and **Side Bar** for the same reason (`PTLL LLC`,
`S BAR 10 INC`).

### `ada9a69` — media, the next town off the rotation

| | before | after |
|---|---|---|
| licensees | 41 | 41 |
| with a website | 12 | **31** |
| crawled | — | 27 |
| with a deal quote | — | 14 |
| **cards** | **5** | **9** |

New: La Catrina, Luna's Mexican Grill, Sligo Irish Pub, State Street Pub — all four
read off the **venue's own site**, not a roundup.

**Cost: $0.** 44 Places lookups, inside the 1,000/month free tier. **No model passes
ran** — this repo's `.env` still has no `ANTHROPIC_API_KEY`, so §2 step 6 remains
unrunnable. 🛑 Never borrow another repo's.

```
python tests/live_front_door.py doylestown   -> LIVE, 6 of 6
python tests/live_front_door.py media        -> LIVE, 9 of 9
bash tests/run.sh                            -> 449 tests, 0 fail (425 + 24)
```

🔑 **GitHub Pages lags a push by roughly a minute.** Both zones failed the live check
on the first try and passed on the second. A single `NOT LIVE` immediately after a
push is a deploy that has not landed, not a broken build. Re-run before believing it.

---

## 1. How the address join works, and the two things it must refuse

`mentions()` matches on **name first**, unchanged. A heading the name index cannot
resolve is now kept with its paragraphs, and a **second pass** joins it by the street
address those paragraphs carry. Two shapes both work: the card block at the foot of
the article (`37 N Main St, Doylestown, PA 18901` under the heading), and the prose
opener (`Located at 80 W State Street`). They are far apart in the document, which is
why it is a second pass and not a wider window.

A house number + street core inside the article's **own zone** is *stronger* evidence
than a name, so this widens yield without loosening grounding. The hit carries the
**article's heading** as the display name — the sign over the door, which is exactly
what the venue with a shell licence is missing.

Two refusals it needs, both found by running it over the whole corpus before shipping:

- **Two licences at one door.** 44 W Gay St, West Chester is Lascala's Fire *and*
  Sedona Taphouse. The key indexes to a list; a list of two refuses.
- 🔑 **A DOOR OUTLIVES ITS TENANTS.** The first corpus run joined `Serum Kitchen &
  Taphouse` (County Lines, 2024) to the door Google now reads as **Station 142**, and
  `Split Rail Tavern` (2021) to today's **Bierhaul**. Both would have shipped a card
  under a name the building stopped using — the stale-join shape `HandCorrectedJoins`
  already names. So where the base carries a trade name a **live** source read off the
  door (OSM, Places) and it disagrees with the heading, the join is refused. A
  **licence-only** name is the shell the join exists to see through and is never held
  against the heading.

---

## 2. Four more silent defects. All fixed, all guarded, none of them raised anything.

### D1 — pmify() shipped a window the article does not claim
`4:30 to 6:30 PM` became **`4:30 pm - 6 pm:30 PM`**, and Penn Taproom's card carried
**4:30–6:00**. The minutes on the *end* of the bare range were optional, so the pattern
matched the `4:30 to 6` inside it. `:` and a digit are now in the forbidden-follow set.
🛑 **A wrong window is worse than a missing one**, and this one shipped silently
because the quote it cites still reads 6:30 — the card and its own evidence disagreed
and nothing compared them.

### D2 — the stale-base guard watched ONE LINK of a THREE-LINK CHAIN
A website walks `venue_sites.json` → `venue_base.json` → `web/data/` before
`needy.py` can see it. Yesterday's guard compared only the first pair. Today, with the
base rebuilt and the bundles **not**, it stayed **silent** while `needy` named **9**
venues where there were **28**. That is the same silent scope cap it was written to
stop, one link along — and scope is money.
🔑 **A guard on one link of a chain is not a guard on the chain.** `STALE_CHAIN` now
names every link.

### D3 — a neighbour at the same house number, and a drop that only took in one reader
`THE FROSTED MUG`'s licence is 527 E Baltimore **Pike**; Places answered with the
**ACME Markets** at 527 E Baltimore **Ave** — two real and different Media streets
sharing a house number, names agreeing on nothing. A bar's licence shipped under a
supermarket's name, website and photo.
Hand-dropped — **and the drop did not work.** `merge_sites()` keeps a rejected join out
of the crawl frontier, but `build_venue_base.py` reads `places_venues.json`
**directly**, so the row kept the supermarket's name anyway.
🔑 **Dropping a join in one of two readers is not dropping it.** Both loops now go
through one `place_for()` — and they *must*, because `premises_key()` reads the Places
name, so blanking it in one loop and not the other builds two different keys for one
building and the sibling lookup dies with a `KeyError`.

### D4 — a label cut from the LEFT
`TRAILING_PRICE_RE` runs backwards from the price under a 29-character cap, so
`Housemade Buffalo Cauliflower Bites $6` shipped State Street Pub an item called
**`ade Buffalo Cauliflower Bites`**. The exact mirror of the roundup lane's
`drafts and discounted appetiz`, which was fixed in the same session. Both are now
cut on a word boundary, and a test checks **every shipped label on the whole board**
against its own quote for a mid-word start.

---

## 3. 🔑 The next build: **a roundup that names the venue MID-SENTENCE**

Well-evidenced, and it is what Media's roundup lane ran into.

`DELCO.today` is the Delaware County sibling outlet (same publisher network as
vista.today and bucksco.today). Four of its articles are now in
`data/roundup_sources.json` for `media`. All four crawl, all four date cleanly, and
all four match **zero** venues.

🛑 **That is a finding, not an empty town.** Checked by hand against the pages:

- *"**Azie** in Media has a happy hour on weekdays from **4 to 6 PM**"*
  — and `Azie Media` (lid 58431) is in our base.
- *"**Off the Rail**, also in Media, has **$3 domestic beers** during happy hours
  weeknights, **4 to 6 PM**"*

Both are real, both carry a clock, neither reaches the board. The reason is the
**outlet shape**: these articles are prose, not a list. The venue is named inside the
sentence, and `mentions()` requires a **heading**. Worse, the DELCO.today template
produces ~100 chrome lines that pass `is_heading()` (nav items: `Commerce`,
`Community`, `Search`, …), so the queue is full of junk headings that eat the real
paragraphs.

So the build is two halves:

1. **Ignore the site chrome.** A heading that appears on *every* article from an
   outlet is navigation, not a venue. Cheap and safe: they repeat across the four
   crawled pages.
2. **Match a venue named mid-sentence** — but only under the containment rule that
   already exists. 🛑 `Sedona it is.` must still not be Sedona. The safe shape here is
   narrow: the venue name and a happy-hour clause in the **same sentence**, name
   matched on the full multi-word core, never a single word.

I did **not** do this today. The standing rule is one town per run and refuse rather
than guess, and the matcher had already been rewritten once this session. The four
source rows are left in place deliberately — they cost nothing, they date cleanly, and
they are the evidence and the acceptance test for this build.

**Acceptance test: Azie and Off the Rail on the Media board, with 4–6 PM weekdays.**

---

## 4. Where to point the job next

`python ingest/report_funnel.py` — take any row marked `<- no discovery pass`.
**~27 PA zones remain.** Highest headroom first:

| zone | lic | sites | cards | note |
|---|---|---|---|---|
| `pottstown` | 47 | 20 | 2 | 29% card/quote — a **reading** problem, not a reach one |
| `norristown_bridgeport` | 47 | 11 | 1 | |
| `havertown` | 26 | 7 | 1 | small, cheap |
| `springfield_delco` | 36 | 11 | 1 | **Delco** — DELCO.today covers it |
| `warminster_warrington` | 49 | 7 | 0 | **Bucks** — BUCKSCO.Today covers it |
| `ridley_tinicum` | 53 | 10 | 1 | **Delco** |
| `media` | 41 | 31 | 9 | **done today** |

🛑 The Philly zones (`center_city` 635 lic, `north_philly` 206, `northeast_philly` 127)
will each **blow the 1,000/month Places free tier on their own**. Budget them
deliberately; do not let the rotation wander into one by accident.

🛑 **West Chester stays stand-alone**, after the small towns. Unchanged.

🔑 **The outlet list is region-shaped, and the Delco half is now proven to exist:**
County Lines / Main Line Today / VISTA.today (Chester), MONTCO.today (Montgomery),
**BUCKSCO.Today (Bucks)**, **DELCO.today (Delaware)**. Search that works is
`"<town>" happy hour` with `allowed_domains` set to the outlet list — a bare web
search returns aggregator spam.

---

## 5. Open, carried forward

- **The mid-sentence roundup join** — §3 above. The next build, with a named
  acceptance test.
- **No `ANTHROPIC_API_KEY` in this repo's `.env`.** §2 step 6 still cannot run.
  Doylestown's card/quote is 55% and Media's is 64% — the gap between a venue that
  quoted something and a venue that produced a card is exactly the population the
  scoped model pass exists for, and it is still unmeasured.
- **Service worker / stale board** — carried from two handoffs back, still untouched.
- **Ground truth still has no confirmed row for any town.** Every number in this file
  is measured against our own output. Paul's minute on a town remains the only real
  accuracy number.
- 🔑 **Diff `venue_base.json` against the last commit after ANY run that touches
  naming.** Today: 16 renames, all Media, all a licensee name giving way to the trade
  name Google reads off that same door. Two of them changed street (`Media's Townhouse`
  → `Towne House`, `300 Media` → `320 Market Cafe`) and were checked by hand against
  the licence address before shipping. The suite does not see a rename.
