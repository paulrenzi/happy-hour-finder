# HANDOFF — the daily one-town job ran for real, and the §2 sequence was wrong

**Written 2026-09-02**, after the first run of the recurring daily job specified in
`HANDOFF-CODEX-DAILY-SCRAPE-20260902.md` §2. Read that file for the *intent* of the
job; read **this** file for the sequence that actually works. Where the two disagree,
this one is right — §2 was never executed end to end before today.

---

## 0. What shipped

**Doylestown**, the first zone worked by the daily job. Chosen off
`ingest/report_funnel.py` as `<- no discovery pass`, small, walkable, high headroom.

| | before | after |
|---|---|---|
| licensees | 41 | 41 |
| with a website | 6 | **32** |
| crawled | 6 | **32** |
| with a deal quote | 0 | **11** |
| **cards on the board** | **0** | **4** |

Cards: 86 West, Chambers 19 Bistro & Bar, Frost Doylestown, New Britain Inn.

**Cost: $0.** 42 Google Places lookups, inside the 1,000/month Enterprise free tier.
No model passes ran — **this repo's `.env` has no `ANTHROPIC_API_KEY`** (it holds
`GOOGLE_PLACES_API_KEY`, `ADMIN_TOKEN`, `SUBMIT_API` and nothing else). §2 step 6 is
therefore not runnable as written until a key is added here. Do **not** reach into
`shopify-analytics/.env` for it.

Live, verified by the only command that may say so:

```
python tests/live_front_door.py doylestown
  built     : 4 venues, 6 items
  painted   : 28 blocks, body 7668 chars
  named live: 4 of 4
  LIVE - the built bundle is on the site and paints
```

`bash tests/run.sh` — **425 tests, 0 fail** (419 + 6 new).

---

## 1. 🛑 THE CORRECTED SEQUENCE — §2 has a hole in its discovery half

§2 gives discovery as **one** command. It is **two**, plus a base rebuild, and getting
it wrong fails **silently** — no error, no exit code, just a smaller board.

```sh
ZONE=doylestown

# ---- DISCOVERY (three commands, in this order) --------------------------
python ingest/discover_places.py --zone $ZONE --dry-run          # scope
python ingest/discover_places.py --zone $ZONE                    # THE PAID RESOLVE PASS
python ingest/discover_places.py --zone $ZONE --merge-sites --execute
python ingest/build_venue_base.py                                # carries websites onto the board

# ---- then the rest of §2, unchanged -------------------------------------
python ingest/needy.py $ZONE --show --lids run.lids
python ingest/crawl_sites.py --lids run.lids --recrawl --render
python ingest/extract_deals.py
#   ... roundups (§5 below) ...
python ingest/build_bundles.py
bash tests/run.sh
git add -A && git commit && git push origin master
python tests/live_front_door.py $ZONE
```

On a zone with **no prior discovery pass**, `crawl_sites.py --lids run.lids` will crawl
almost nothing, because `needy.py` cannot see venues that are not yet on the board.
Use `crawl_sites.py --zone $ZONE --recrawl --render` for a zone's **first** run —
only the new LIDs are uncrawled anyway — and `--lids` for every run after.

---

## 2. Three silent defects found by running it. All fixed, all now guarded.

Each shrank the run and none raised anything. This is the `silent-drop class` the
README already names, one level up: not a dropped item, a dropped *town*.

### D1 — `--merge-sites` is a NO-OP on a zone nobody has resolved
`main()` dispatches `--merge-sites` and **returns before the resolve pass ever runs**.
So §2's one-liner `--zone Z --merge-sites --execute` merged a stale
`places_venues.json` and printed a perfectly healthy-looking `+0 to add`.
The resolve pass is a separate, earlier command.
**Guard:** `merge_sites()` now prints `! NOTHING RESOLVED FOR <zone> -- this merge is
a no-op` with the exact command to run, whenever the zone has no resolved rows.

### D2 — `build_venue_base.py` is missing from §2, and it is the step that carries a website onto the board
`build_bundles.py` reads the website from `data/venue_base.json`, not from
`data/venue_sites.json`. Skip the base rebuild and the 28 newly discovered venues ship
with **no `website` field** — which blinds **`ingest/needy.py`**, the selection
instrument for *every* scoped run. It named **5** needy venues where there were **33**.
**Guard:** both `needy.py` and `build_bundles.py` now compare mtimes and print
`! data/venue_sites.json is NEWER than data/venue_base.json` with the fix.
🔑 **This one is the most dangerous of the three** — it does not just cost a town, it
quietly caps the scope of every scoped model run that follows, which is money.

### D3 — `is_heading()` could not see `86 West — Best for Groups and Drinks`
Many outlets head a list entry with **the venue name plus why it made the list**.
The tail pushed the line past `HEADING_WORDS = 7`, so no heading was seen, the prose
under it was filed to no venue, and the town's only roundup quote was the **address
line in the card block at the foot of the article**.
**Fix:** `heading_text()` takes the part before an em/en/hyphen dash; `is_heading()`
keeps its sentence test on the **whole** line, so a paragraph cannot pass on its short
opening clause. Three regression tests, including that negative case.

### D4 (bonus, caught by the suite) — a supplied trade name can BE the legal entity
The base left a Places/OSM name alone on the rule that it "is already the trade name".
Google lists this Doylestown bar as **`FACENDA SPIRITS LLC`** — its paperwork. That
shipped a card whose only content was the licensee.
**Fix:** `_trade()` strips an entity suffix from a *supplied* name too. The sign over
a door never ends in LLC. Four regression tests.

🛑 **The first version of this fix was WRONG and is worth remembering.** It reused
`ENTITY_SUFFIX_RE`, which lists `CO|COMPANY|GROUP|ENTERPRISES|…` — correct for a PLCB
*licensee*, and destructive on a *supplied* name, because those are real words on real
signs. It renamed 14 good venues across the corpus: `Wrong Crowd Beer Company` →
`Wrong Crowd Beer`, `Victory Brewing Company` → `Victory Brewing`, and visibly
**`Bagels & Co.` → `Bagels &`**. `tests/run.sh` was **green** for all of it — the suite
only asserts a name does not END in a legal suffix, so a name it *shortened* passes.
Caught by diffing `venue_base.json` against the previous commit, which is the check
that actually sees this class. **A rename is a silent-drop too.** There is now a
separate, much narrower `TRADE_ENTITY_SUFFIX_RE` (LLC/INC/LP/LLP/LTD/CORP only) and a
test naming the seven words that belong on a sign.

🔑 **After any change to naming or matching, diff the base against the last commit:**
```sh
git show <last>:data/venue_base.json > /tmp/old.json
# then compare name-by-name; the suite will not catch a rename
```

---

## 3. 🔑 The next build: **join a roundup by ADDRESS, not only by name**

This is the single highest-value open item and it is well-evidenced.

The BUCKSCO.Today Doylestown piece names **two** venues with real clocks:

- **Penn Taproom** — Mon–Fri 4:30–6:30 PM, Sun 3–5 PM, half-price drafts
- **Maxwell's On Main (MOMs)** — daily 5–7 PM

**Neither reached the board.** `mentions()` matches on name by design ("a roundup
carries no address"), and Maxwell's licence is the shell **`37 N MAIN STREET
ENTERPRISES LLC`** — the licensee is literally the street address as a company name.

But **this article does carry addresses**: it has a card block at the foot with
`37 N Main St, Doylestown, PA 18901` sitting as a paragraph under the heading
`Maxwell's On Main (MOMs)`. The docstring's premise is false for this outlet shape.

So the build is: **when a heading resolves to no venue, try the address paragraph
that follows it.** A street-number + zone match is *stronger* evidence than a name
match, so this widens yield without weakening grounding. It needs a second pass,
because the prose section and the address card block are far apart in the document.

I did **not** do this today — it rewrites the roundup matcher, the West Chester
regression risk is real, and the standing rule is one town per run, refuse rather
than guess. It is the right first thing next session.

---

## 4. Where to point the job next

`python ingest/report_funnel.py` — take any row marked `<- no discovery pass`.
**~29 PA zones remain.** Highest headroom first (licensees ÷ sites):

| zone | lic | sites | cards | note |
|---|---|---|---|---|
| `media` | 41 | 12 | 5 | walkable bar town, good roundup odds |
| `doylestown` | 41 | 36 | 4 | **done today** |
| `pottstown` | 47 | 20 | 2 | 29% card/quote — a reading problem, not a reach one |
| `norristown_bridgeport` | 47 | 11 | 1 | |
| `havertown` | 26 | 7 | 1 | small, cheap |
| `springfield_delco` | 36 | 11 | 1 | |
| `warminster_warrington` | 49 | 7 | 0 | Bucks — BUCKSCO.Today covers it |
| `north_philly` | 206 | 7 | 0 | big; discovery alone is ~200 lookups |

🛑 The Philly zones (`center_city` 635 lic, `north_philly` 206, `northeast_philly` 127)
will each **blow the 1,000/month Places free tier on their own**. Budget them
deliberately; do not let the rotation wander into one by accident.

🛑 **West Chester stays stand-alone**, after the small towns. Unchanged.

## 5. Roundups — what worked, and the outlet list is region-shaped

The §3 outlet list is **western-suburbs shaped** (County Lines, Main Line Today,
VISTA.today cover Chester/Delco/Montco). Doylestown is **Bucks**, and the sibling
outlet is **`bucksco.today`** — same publisher network as vista.today. It is now
proven to publish dated pieces with days, clocks and addresses. **Add it to the §3
list for every Bucks zone** (`doylestown`, `warminster_warrington`).

Three rows added to `data/roundup_sources.json` for `doylestown`. One is inside the
120-day window; the other two ship stale-labelled, which is correct since 2026-09-02.

Search that worked: `"<town>" happy hour` with `allowed_domains` set to the outlet
list — not a bare web search, which returns aggregator spam.

## 6. Open, carried forward

- **The address join for roundups** — §3 above. The next build.
- **No `ANTHROPIC_API_KEY` in this repo's `.env`.** §2 step 6 cannot run until Paul
  adds one here. 🛑 Never borrow another repo's.
- **Doylestown card/quote is 36%** — 7 venues quoted something and produced no card.
  That is exactly the population the scoped model pass exists for, and it is the
  measurement of what step 6 would buy on a town. First real test when a key exists.
- **Service worker / stale board** — carried from the previous handoff, still untouched.
- **Ground truth still has no confirmed row for any town.** Every number in this file
  is measured against our own output. Paul's minute on a town remains the only real
  accuracy number.
- **Penn Taproom and Maxwell's On Main are a known, named miss** — not a guess we
  refused blindly, a join we cannot yet make. They are the acceptance test for §3.
