# The Sussex coast is on the board: Rehoboth, Lewes, Dewey

**Supersedes** `HANDOFF-START-HERE-20260904-NIGHT6-THE-HALF-WINDOW.md`
for what to read first. NIGHT6's finding is live and summarised in §4.

## 0. What shipped, and it is live

Paul asked for the three beach towns on the board with pictures, then a
menu scrape. All of it is live and verified with `live_front_door.py`.

| zone | venues | photos | windows | cards with items |
|---|---|---|---|---|
| rehoboth_beach | 101 | 100 | 29 | 12 |
| lewes | 52 | 52 | 12 | 9 |
| dewey_beach | 26 | 26 | 2 | 1 |

Board: 48 → **51 zones**, 355 → **399 windows**, 415 deals, **0** whose
window contradicts its own quote, 563 tests green.

**Total spend $21.09**: seed $2.74, photos $7.02, tier-A agent reads $6.86.
(The crawl is free.) The two venues without a photo are ones Google has none
for; the app draws its own tile.

## 1. Two silent failures had to be fixed before one row could survive

Both would have produced a confident nothing, not an error.

**`DE_BOX` is northern Delaware** (lat 39.35–39.92). Lewes is 38.77, Rehoboth
38.72, Dewey 38.69 — `in_delaware()` would have dropped *every* beach row with
no log line. Boxes are now **per zone** (`BOXES`), and the seeder says so out
loud when a zone keeps nothing and drops plenty.

🔑 Note what this reverses: `DE_BOX`'s own comment was written to **exclude
these exact towns**, because a Hockessin query kept returning Crooked Hammock
in Lewes. The contamination and the target are the same rows. That is why the
coast got its **own** box instead of the northern one being widened — widening
would have re-admitted Rehoboth to Hockessin's results with nothing objecting.
Same reasoning for the third `MARKET_BOX` in `tests/test_ingest.py`, which is
the only check in the repo that looks at where a venue actually is.

**A row's zone came from the QUERY that found it.** Inside a small box that is
not good enough: the three towns are ten minutes apart, so "restaurant in
Lewes, Delaware" filed **30 Rehoboth bars and 4 Dewey ones under `lewes`**. The
box answers which *region*; only the address answers which *town*.
`zone_from_address()` decides now, and a town nobody asked for (Millsboro,
Milton, Bethany Beach — 8 rows) is refused rather than filed under its nearest
neighbour.

## 2. The tier-A number, which is the one that decides tier B

14 venues read, **11 returned items — 79%**, $6.86. Tier A is the class where
the crawl already captured a menu image and nobody ever read it, so the fetch
was already paid for.

```
rehoboth_beach  6 of 9   $4.47
lewes           4 of 4   $2.02
dewey_beach     1 of 1   $0.37
```

**Tier B is 57 venues, ~$20, and is not yet bought — Paul's call.** The repo's
rule is run A, measure, then decide; A has now been measured at 79%, and tier B
(the crawl quoted happy hour on the page) is the next-best evidence class.
Tier C is 81 venues, ~$28, and is a blind read.

## 3. Open, and deliberately not done

- **The Dunes (rehoboth)** hit the 14-turn budget, recorded `kind: exhausted`.
  That is the designed refusal, not a loss — retry with `HHF_MAX_TURNS=25` for
  pennies. `MAX_TURNS` is env-overridable.
- **Dewey's 2 windows is not a bad crawl.** 16 of its 25 sites are shell pages,
  7 carrying embedded data — that is the **structured-data lane**
  (`crawl_sites.py --render`, `sweep_site.py`), a different tool than the prose
  crawl that ran. Rehoboth has 71 shell pages / 41 with embedded data, Lewes
  20 / 12. This is the single biggest untouched seam in the three towns and it
  costs no agent money. README rule 4 is the argument for doing it.
- **Two new strands** (see §4): Salt Air and Three Notch'd Rehoboth.
- The older open work is unchanged: MadMacs (needs days, (302) 737-4800),
  Slow Hand (needs a clock, (484) 999-8638), thin-item towns,
  `data/RESCRAPE-QUEUE.json`, and Paul's open call on James Street Tavern and
  Timothy's Riverfront Grill.

## 4. NIGHT6's strand warning earned itself on its first real run

It landed this morning and immediately caught two venues the beach reads
stranded, naming which half of the window each one holds:

```
Salt Air (12 items)                       -- window evidence held: days, no clock
Three Notch'd Brewery Rehoboth (3 items)  -- window evidence held: neither
```

Before today both would have printed an identical "no window" and somebody
would have gone hunting Instagram for both. Salt Air is one phone call; Three
Notch'd needs a source. Route either through `data/agent_handread.json`.

## 5. Verification

- `python tests/live_front_door.py rehoboth_beach|lewes|dewey_beach` → **LIVE**
  all three, after the Pages build completed (`gh run list` → success).
- Live `index.json` re-fetched from the site: 26/52/101 venues, 2/12/29 deals.
- `bash tests/run.sh` → **563** Python tests OK, node `fail 0`.
- `python tests/window_quote_check.py` → 415 published, 0 contradictions.
- Every beach window spot-checked against its own quote, e.g. Agave
  "Happy Hour / Monday-Friday / 2:00-4:00PM", Fish On "HAPPY HOUR 4-7PM Daily".

🛑 The boot-payload ratchet moved **600k → 700k**, and the measurement is the
justification: the three new zones are 54,220 bytes and the rest of the board
is 575,207, still under the old bar. That is deals getting richer, not the
1.47MB venue base leaking into the boot path — which is the only thing that
guard exists to catch. Do not raise it again without measuring the same way.

## 6. Standing rules, unchanged

Scoped runs only, one town at a time, never the corpus. Never two crawls at
once. "It is live" is one command: `python tests/live_front_door.py <zone>`.
A wrong item is worse than a miss. Check `git branch --show-current` before
committing (repo is shared with Codex). Check the **built bundle**, not a
lane's own summary.
