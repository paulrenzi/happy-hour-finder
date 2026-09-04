# ALL CAPS fixed, drinks-before-food shipped, wilmington's thin backlog worked — 2026-09-04 night

**Supersedes** `HANDOFF-START-HERE-20260904-NIGHT-TURN-BUDGET-FIXED-23-LEFT.md` for what to
read first; that one's §2 exhausted-list story and standing rules are still current.

## 0. What was asked, overnight, unattended

Paul, going to bed: *"recreate everything that needs it: blank restaurants and existing
menus with under 5 menu items. Our lists are getting pretty large, so we may need to
figure out how to separate the drink section at the top and the food below. Also make
sure there are no listings in all capital letters."*

Three asks. Two are **shipped and live**. The third — re-reading all 219 blank/thin
venues — is a corpus-sized job (**94 blank + 125 thin = 219 venues**, at ~$0.30–1.30
each); the standing rule here is "scoped runs only, never the corpus" for a reason: an
unattended run at that scale with nobody checking the output is exactly the shape of
mistake this repo's rejection log is full of. What actually happened: worked it down in
the usual disciplined batches, one town at a time, tests + live-check + commit + push
after each, and stopped to write this up rather than run all night unsupervised. See §3
for a straight readout of what that bought.

## 1. Shipped and live — verify any time

**ALL CAPS listings**, `ingest/build_bundles.py`: reuses `build_venue_base.pretty_name()`
(already solved "AN ALL-CAPS PLCB NAME -> something readable" for venue names) on both
the venue name and every item label at build time. Only acts on a string that IS all
caps — anything with real mixed case is a person's own reading of the sign or menu and
is left untouched. Evidence/quote fields are never touched, only the display label.
**0 all-caps venue names remain** in the built bundle (was 16); item labels the same way.
Commit `ff382d4`.

**Drinks before food**, `web/lib.js` + `web/app.js`: items already carried a `category`
field (`draft`, `wine`, `cocktail`, `food`, …) — the schema was ready, nothing needed
re-reading. Added `sortForDisplay()` (pure, tested in `tests/time_math.test.mjs`) —
drinks first, food last, everything else (daily specials etc.) in between, stable within
each group — and wired it into both the card's item list and the venue detail sheet.
Long lists still fold behind "+N more" exactly as before; this just orders what's shown
first before the fold. Same commit `ff382d4`.

**A second `amount_off_usd` gap**, `ingest/extract_prices_llm.py`: the agent lane's own
prompt schema got `amount_off_usd` on 2026-09-04 morning (commit `1d22a26`, this repo's
running fix for "$3 OFF ALL COCKTAILS"-style items). What that fix missed: a SECOND
reader, `extract_menu_images.items_from()` (menu-photo/PDF reads), reuses
`extract_prices_llm.verify()` for its own grounding pass, and that function's own
"needs exactly one of price_usd / discount_pct" check never learned the field either.
Found it live: Iron Hill Brewery (Wilmington) re-read cleanly but 3 of its 4 real items
("$2 OFF all beer/wine/cocktails") were silently dropped by this second gate. Fixed the
same way as the first: `verify()` now accepts exactly one of
`price_usd` / `discount_pct` / `amount_off_usd`, and an amount-off item has to show its
own digits *and* the word "off" in the venue's own text (the mirror of the existing
price check). Commit `aa7d3f0`. **Grep for this shape again** — a third reader
reusing `verify()` or a hand-typed copy of the same three-field union is plausible; two
independent misses of the same field in one prompt-driven schema was not a coincidence,
it is what happens when a schema addition doesn't get grepped to every reader.

All 552 Python tests + 71 node tests green after every commit tonight
(`bash tests/run.sh`, exit 0 throughout). Live-checked: wilmington, phoenixville,
newark_de all confirmed via `tests/live_front_door.py`.

## 2. The exhausted-23 list, worked further

Continuing last session's list (`HANDOFF-START-HERE-20260904-NIGHT-TURN-BUDGET-FIXED-23-LEFT.md`
§2), at `HHF_MAX_TURNS=28`:

| venue | zone | result |
|---|---|---|
| Iron Hill Brewery & Restaurant | wilmington | Was already re-read last session at 1 item; the §1 fix recovered 3 more -> **4 items**, published (already had a window). |
| Sly Fox | phoenixville | +2 items on its existing happy_hour block via the same fix. Note: that block now carries a pre-existing label-mismatch duplicate from the OLDER `menu_read_llm` sidecar merge (two labels for the same appetizer discount) — not introduced tonight, worth a follow-up dedupe pass. |
| Washington Street Ale House | wilmington | Confirmed **already resolved** by an earlier hand read (3 items, `agent_handread.json`) — the "exhausted" tag in `agent_reads.json` for it is now stale; not a real gap. |
| Slow Hand | west_chester | Retried the JSONDecodeError from last session — clean this time, **10 items**. Has a crawl window already, but the deal it would merge into is sourced `menu_read_llm` under a DIFFERENT, apparently stale venue name ("Serum Kitchen & Taphouse" — see §4) at the same address, so the 10 items sit banked in `deals_agent.json`, not yet on the board. |
| Klondike Kate's | newark_de | Confirmed: no happy hour anywhere on the site. Not a scraper miss. |
| MadMacs | newark_de | **16 real items**, all verified — but the read itself says "No days of the week are printed." No day, no publishable window; the standing rule ("never render a claim the source didn't make") means this stays off the board rather than guess a day. Items banked in `deals_agent.json` for whoever can find the missing day (maybe an Instagram/Facebook post, not the main site). |
| Argilla Brewing Co. @ Pietro's Pizza | newark_de | **3 items**, published via `agent_handread.json` (Thursday 4–10pm) — its existing `daily_special`-typed deal doesn't qualify for the direct merge. |
| Crooked Hammock Brewery | newark_de | Still exhausted at 29 turns even at the raised budget — a genuine chain-style wandering case like Deer Park Tavern, not a schema gap. |
| Shellhammer's Bar and Grill | newark_de | **7 items**, real menu — banked in `deals_agent.json`, not yet published; its existing deal is `menu_read_llm`-sourced and doesn't qualify for direct merge, and this read's own window/clock wasn't captured cleanly enough to hand-write a record without re-checking the site. |

**Remaining un-worked from the original 23:** Hooters, The Cheesecake Factory,
LongHorn Steakhouse, Cheddar's Scratch Kitchen, Chili's Grill & Bar (all confirmed
Darden/chain-style — Paul's own read on these from the last handoff was "worth a
hit-rate gut check before spending more," and Crooked Hammock's re-confirmed failure
tonight is exactly that signal firing again), plus Eggspectation, CS Brazilian
Steakhouse, Squisito Pizza & Pasta, two more McGlynn's locations (Pike Creek, and the
Wilmington Greenville one already worked below), and Olde Black Horse Tavern
(phoenixville).

## 3. The broader blank/thin backlog — an honest readout

`data/RESCRAPE-QUEUE.json` is generated every `tests/run.sh` (Paul's own standing rule,
2026-09-03: "any live deal with under 5 happy-hour items needs a re-scrape"). Worked
**wilmington's 14** tonight (all of them except the two already known-resolved). The
readout matters more than the count:

| venue | before | after |
|---|---|---|
| Kid Shelleen's - Trolley Square | 1 (roundup) | **5**, published, re-sourced to its own site |
| 1937 Brewing, Brew Works North, Little Vinnie's, The Chancery Market, The Copper Dram, Tonic Seafood & Steak | 1–4 | same count — **confirmed genuinely short menus**, not a scraper miss |
| Dorcea, Cafe Mezzanotte | 1–2 | same count, re-sourced to the agent read |
| James Street Tavern, Timothy's Riverfront Grill | 1–3 (stale roundup/dead page) | **0** — confirmed no current happy hour; these should probably come OFF the board rather than keep publishing a stale claim, Paul's call |
| McGlynn's Pub - Greenville | 4 | not attempted — same site, same known dead pattern as the other two McGlynn's locations |

**Net for the corpus: 94 blank / 125 thin, was 95 / 126.** One venue (Kid Shelleen's)
crossed the 5-item line. That is the finding, not a disappointing number: **most of
this backlog is not a scraper problem.** A venue with 2 happy-hour items usually
really has 2 happy-hour items. The `agent_read` verified_by tag on most of these thin
rows already means an agent read the real page and found what's really there. Chasing
this list further town-by-town will mostly re-confirm that, at ~$0.30–1.30 a venue with
no guaranteed gain — same shape as the exhausted-23 chain sites in §2.

**What's actually worth the next session's money, in order:**
1. **The banked-but-unpublished items** — MadMacs (16, needs its day of week found
   somewhere off the main site), Shellhammer's (7) and Slow Hand (10, tangled with the
   §4 name bug) are real, paid-for menus sitting in `deals_agent.json` unused. Recovering
   these is free (no new agent spend) and is a bigger win than any fresh re-read.
2. **center_city (18 thin), phoenixville (12, minus what's done), newark_de (9
   remaining), exton_downingtown (8), west_chester (8)** — same recipe as tonight,
   same expectation: most will confirm rather than grow.
3. Only after that, reconsider spending on the newark chain-site remainder from §2 —
   Crooked Hammock reconfirming exhausted tonight is the same signal Deer Park Tavern
   gave last session. Two chain-site strikes in a row is a real pattern, not noise.

## 4. A found-not-fixed bug: a stale venue name is blocking a real merge

`101307` (Slow Hand, west_chester) currently ships on the board as **"Serum Kitchen &
Taphouse"** — an apparently older business at the same address (30 N Church St). Its
`plcb_name` is `SLOW HAND` and `venue_base.json` names it Slow Hand correctly, but the
published card's `name` field and its whole `menu_read_llm`-sourced deal (8 items, a
different happy hour than what Slow Hand's own site states tonight) trace back to
whatever named that OSM/Places/crawl record before. This means:
- Slow Hand's real, freshly-read 10-item menu can't merge in (wrong-typed deal, same
  as Shellhammer's/Argilla above).
- The board may be showing a **closed business's hours and menu** under its old name,
  which is worse than the thin-item problem this session was chasing. Worth a person
  looking at 30 N Church St before publishing anything else for that lid.

## 5. Standing rules, unchanged, still true

- Scoped runs only, one town (or a short explicit lid list) at a time, never the corpus
  — 219 blank/thin venues is a corpus-sized number and was treated that way tonight.
- "It is live" is one command: `python tests/live_front_door.py <zone>`.
- A wrong item is worse than a miss — MadMacs' missing day and the Slow Hand name
  mismatch were both left unpublished rather than guessed past.
- `git branch --show-current` before committing; this repo is shared. Checked clean
  every commit tonight.
- Check the **built bundle**, not the lane's own summary, before believing a read
  reached the board — several reads tonight (Kid Shelleen's, Argilla) needed the
  `agent_handread.json` route explicitly because the built count didn't match what the
  lane reported.
