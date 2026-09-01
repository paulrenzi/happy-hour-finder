# Handoff — the "Hours not published" population, 2026-09-01

**Read this first:** `ARCHITECTURE-MENU-INGEST.md` — the two new sections are
*"The OTHER hole population"* and *"Who is not on the board"*.

---

## The one sentence

Reclaiming the venues Paul finds by clicking is not a parser problem — it is
that we had **no way to tell one silent venue from another**, and now we do.

## What Paul asked, and what he got

> *"we are still hand correcting these. this isn't a structurally working system
> yet. the amount of places in just King of Prussia showing under 'Hours not
> published' with happy hour menus I can find with a few clicks is still a bunch.
> how do we reclaim these quickly? are we ready for that scrape?"*

**Answer to "are we ready?": no — and it is now sized rather than guessed.**

There are **two** hole populations and only the small one was ever measured:

| population | the card says | size | reported by |
|---|---|---|---|
| a window, no items | "happy hour 4-6" and names nothing | ~100 | `report_holes.py` |
| **no window at all** | **"Hours not published"** | **~2,584** | `report_holes.py --silent` |

Every tool in the repo reported the first. Paul's complaint is entirely the
second.

## The structural change

**One field in the crawl made the silent population rankable.** A fetch
returning 200 and 11 lines of text and a fetch returning 200 and 400 lines were
**the same row** in `crawl_hits.json` — and they are opposite problems: a
JavaScript shell we cannot see into, versus a page we read in full that does not
mention a happy hour. Nothing downstream could tell them apart, so every silent
venue looked identical and none could be ranked.

`crawl_sites.py` now records `lines` and `hh` per page. `report_holes.py
--silent [--zone X] [--class Y]` sorts the population into eight named classes,
ranked by size. **Seven of the eight are our defect.**

```
python ingest/report_holes.py --silent --zone king_of_prussia
```

King of Prussia today — 36 venues with a website and no window:

| class | n | the work |
|---|---|---|
| `crawled-before-the-line-count` | 26 | crawled before today. **Recrawl to sort them** — never guess a line count |
| `fetch-failed` | 3 | BWW, Chili's, Nan Xiang — 403s and chains |
| `never-crawled` | 3 | Cheesecake Factory, Tommy Bahama, Wegmans — **we hold a website and never queued it. A frontier bug, and the cheapest venues on the list** |
| `robots-refused` | 3 | CPK, Netflix House, Regal — nothing in the parser fixes it |
| `venue-says-it-has-none` | 1 | Founding Farmers. **An answer, not a hole** |

## The reclaim classes found behind KoP's silent venues

Seven venues say "happy hour" on their own homepage while we publish nothing.
**None of the causes is venue-specific:**

1. **The window line never entered the quote.** bartaco's page reads "high tide
   happy hour / (at the bar) / weekdays 3-6pm"; our quote stops after two lines.
   The grammar is innocent — `days_in('weekdays 3-6pm')` → `{1..5}`,
   `window_in` → `('15:00','18:00')`.
2. **Items but no clock ⇒ we publish nothing.** Peppers (`$2 OFF any bar bite |
   $1 OFF any beer | ...`) and Pizzeria Vetri (`Happy Hour` + `$6 Wine on Tap`)
   both name priced items and no window was found.
3. **A start with no end is refused.** Bonefish: "Happy Hour starts at 3:30pm
   daily." The card **already renders "Starts 3pm"** — Tommy's proves it. This is
   publishable and is being thrown away.
4. **JavaScript shells.** Cheesecake's own `/happy-hour` is 13 KB of HTML and
   **11 lines** of text; Bonefish is 163 KB and 55 lines. One fix, all of them.

## The next-zone tiers, in order of return

1. **Recrawl** so `lines`/`hh` are populated and the 26 unknowns sort themselves.
2. **The headless tier** (Playwright) for `page-is-a-shell`.
3. **The never-crawled frontier bug** — cheapest of the three.

Then the small ones: accept a start-time-only window; carry the window line into
the quote; record genuine-tail verdicts in `data/menu_verdicts.json`; drive the
ratchet ceiling (`HOLE_BUDGET = 0.50`) down with each fix.

---

## Bald Birds and the hotels — `ingest/exclusions.py` (new)

One module, **two doors**: `build_venue_base.py` (where a venue first exists,
and in the sibling-LID pass too, so a ban cannot re-enter as an `also_lids` of
the premises next door) and `build_bundles.py` (so a stale *committed* base
cannot put a banned venue back on the site).

- **Bald Birds Brewing — banned permanently.** Keyed on the PLCB licensee name,
  matched as *contained*: Google hands us "Bald Birds Brewing Company - King of
  Prussia".
- **Hotels — by BRAND, not by licence.**

🛑 **The trap, nearly shipped:** `'Hotel (Liquor)'` is a **licence class held by
178 venues, of which only 87 are hotels.** Excluding on it would have deleted
**The Black Horse Tavern, The Stray Dog Tavern, Joseph Ambler Inn, Panorama and
CO-OP Restaurant & Bar** — all publishing a happy hour, all on the board. Caught
by listing the venues the filter would delete *before* running it.

Second trap, caught the same way: `motel` was put in the **brand** list, where
the tavern/pub/restaurant carve-out does not apply, and it took *The Olde Black
Horse Tavern and Motel* — a working tavern — off the board.

**Result: 2 Bald Birds + 113 hotels off. 199 deals across 38 zones, 2,783
venues ship.** The only deal correctly lost was Desmond Hotel Malvern.

---

## Verified

- `python -m unittest discover -s tests` — **298 pass** (10 new: `exclusions.excluded`
  including *a tavern on a hotel licence is KEPT*, and every `classify_silent` class).
- `sh tests/run.sh` — all five gates green.
- **The live URL in a real browser**, all 38 zones walked:
  1,081 rows painted, **199 with a window, zero banned venues anywhere**, Black
  Horse / Stray Dog / Joseph Ambler / CO-OP / Tommy's all still present, **zero
  `pageerror`**.
  🛑 The *first* run of that check found six hotels still on the board — GitHub
  Pages build lag, not a data bug. **The live check has to be run after Pages
  rebuilds, and it is the check that counts.**
- Pushed: `1a2e2aa` on `master`.

## A bug worth naming

`DENIAL_RE` shipped with `\b` written as a **literal backspace byte** (`\x08`) —
a bash heredoc collapsed the escape. The file parsed, the module imported, and
the regex **silently never matched**. Only a unit test asserting the *match*
caught it. 🛑 **Never put regex- or escape-bearing Python through a heredoc,
quoted or not** — this has now cost five sessions.

## Still owed by Paul (carried)

- Should an all-day special read "Mondays, all day" rather than "midnight to
  midnight"?
- Does a daily special get its own card, or a line on the venue's existing card?
- 🛑 The day↔special pairing is **off by one** in the crawler's quote assembly
  (KoP page says Monday→Titos, we read Tuesday). **Fix before any
  `daily_special` work.**
