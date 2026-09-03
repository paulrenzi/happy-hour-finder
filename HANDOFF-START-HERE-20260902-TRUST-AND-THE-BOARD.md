# START HERE — 2026-09-02, end of day. The board is the next job.

**This supersedes every earlier handoff, including
`HANDOFF-START-HERE-20260902-NIGHT-SHELL-CAPTURE.md`.** Nothing is mid-flight.
Everything below is committed, pushed, and verified on the live site.

Read §1 and §2, then §6 before you touch anything.

---

## 1. The honest answer to "can I trust the scraping"

**Trust the cards. Do not trust the silence.**

| | |
|---|---|
| published windows that contradict their own quote | **0 of 334** |
| venues on the board with a window | 315 |
| …carrying items you can order | 201 venues, 1,214 items |
| **venues we have never checked for a miss** | **all of them** |

Everything we publish is tied to a sentence on the venue's own page: the clock
must be spelled in the quote, every day must be in the quote, and every price
must sit in its own evidence span, re-checked against the file on disk at build
time. `tests/window_quote_check.py` runs that comparison over all 334 on every
test run, and it is clean.

**What has never been measured is recall.** No run has ever been scored against a
list of the happy hours that actually exist in a town. Every miss we know about —
Two Stones' prices, McGlynn's whole menu, the four in Ambler — was found by Paul
opening a website, not by the pipeline. `report_coverage.py` still prints *"0
confirmed rows — no denominator"*.

🛑 **So the number that matters does not exist yet, and building it is not a code
task: it is one blind town, run end to end, then one human minute checking it.**
That is the same open ask as three sessions ago and it is still the only thing
that can turn "trust the cards" into "trust the scrape".

---

## 2. What shipped this session

**A. The "Tomorrow" view was answering a different question.** Two independent
defects, both reproduced in a real browser engine before anything was touched:

1. **Picking a day silently picked a time** (`app.js` set the anchor to 5pm), and
   in this codebase *an anchor is also a cutoff* — `nextOccurrence()` treats any
   window ending before the anchor minute as over and rolls it forward a week. So
   "Tomorrow" meant "what is on at 5pm tomorrow": four lunchtime deals vanished,
   and 210 cards were handed a clock sitting inside their window.
2. **Nothing marked that clock hypothetical**, so `groupFor()` made present-tense
   judgements — *Live now*, *Ends before you'd get there* — about a day that had
   not started.

Fixed by anchoring a future day at 00:00, adding a **planning mode** to
`groupFor()`/`buildFeed()` in which no card may claim to be live, and stamping
every hit with an absolute `dateKey` so a section label can never be derived from
a delta against a movable anchor (which is what printed "Tomorrow" over the day
after tomorrow). Before: 210 *Live now* / 71 *Ends before you'd get there* / 14
*Tomorrow*. After: **290 under Tomorrow**, six of them windows the 5pm cutoff had
been hiding.

**B. The venue publishes its menu for machines, and we looked in one place for
it.** McGlynn's Pub reads as a 25-line shell — two of those lines are "Load More
Content" — and its four real `ld+json` tags carry `Restaurant` records only. The
entire menu is a **schema.org `Menu` document serialised as an escaped string
inside the React boot state**: 14,293 bytes, six sections, dish, price, window.
Three defects, each its own general rule:

1. We only read schema.org inside a `<script type="application/ld+json">` tag.
   Now `embedded_ld_docs()` finds one *anywhere in the page* by the one thing it
   cannot omit — its `@context`. Popmenu, BentoBox, Toast and every
   server-rendered React front end ship data this way.
2. We demanded the whole `Menu` name itself the happy hour. McGlynn's menu is
   called "Food & Drink Specials" and the happy hour is a `MenuSection` inside
   it. The rule is the **name, not the depth**. The guard is unchanged in
   strength: a section that does not name itself is still read as somebody's
   dinner.
3. 🛑 **The one that would have wasted another hour.** After both fixes it still
   returned `items: []`. The structured block was appended *last*, and
   `read_menus_llm` caps a document at `DOC_CAP` (9,000 chars) — McGlynn's 157
   loosely-recovered strings pushed the four priced items off the end. Correct,
   saved, and unread. **The structured block now goes first.**
   *General form: when you add a better source to a document something else
   truncates, placing it is half the change. Check what survives the cap.*

McGlynn's now carries Boneless Wings $15, Loaded Tater Tots $5, Fried Brussels
Sprouts $15.50, Pretzels & Mustards $5 under Mon–Fri 4–6pm, on all three of its
branches. `newark_de` went 80 → 88 items.

Both are written up in `ARCHITECTURE-MENU-INGEST.md` → *"ASK THE PAGE FOR ITS
DATA BEFORE YOU READ ITS PROSE"*, and gated by seven new tests (three in
`tests/time_math.test.mjs`, four in `tests/test_ingest.py`).

---

## 3. 🎯 The next job: the board itself. Paul's words

> *"plenty of basic things are still fucked up on the website, including the fact
> that when i select tomorrow, it shows me options, then shows a separate section
> called tomorrow"*

**This one is diagnosed, reproduced, and deliberately NOT fixed** — the fix is a
product decision, not a bug fix, and it is Paul's call. Run
`python scratchpad/tomorrow_sections.py` to see it: with Tomorrow picked the feed
prints

```
Tomorrow    11
Saturday     1
Tomorrow    35
Friday       1
Tomorrow    63
Monday       1
Tomorrow      2      … and so on, 20+ times
```

**Cause:** the feed is ordered by *score*, and `app.js` emits a section header
whenever the label changes from the previous row. So a single next-week card
scoring between two Tomorrow cards splits the block and prints the header again.
In planning mode `groupFor()` returns `UPCOMING` for *every* non-anchor day, so
all seven days share one group and interleave freely.

**The decision to make:** in planning mode, should the feed be ordered by **date
first, then score within a date** (one header per day, which is what a day-picker
implies), or should ranking stay global? Everything needed for the first is
already there — every hit carries `dateKey`. It is a small change in `buildFeed()`
plus a test; it is small because the shape is already right, not because it is
trivial to decide.

Paul also said **plenty** of basic things are broken. Ask for the list before
starting — a sweep for what *might* be wrong is exactly the mistake that cost an
hour this session.

---

## 4. Open, in the order I would take it

1. **The board** — §3, plus whatever else Paul names.
2. **One blind town, then one human minute** — §1. The recall number does not
   exist and nothing else can create it.
3. **Size the schema.org class across the corpus.** McGlynn's cannot be the only
   one. 🛑 It cannot be measured offline: `data/pages/*.json` stores extracted
   lines, not raw HTML, so it needs a scoped re-crawl. Do it on one town, not the
   corpus.
4. **The second site Paul named.** He said he gave two; only McGlynn's was
   re-supplied after a context compaction and it is fixed. **Ask him for the
   other one.**
5. **Upper Darby discovery** — the town's wall is discovery, not extraction: 6 of
   71 licences sited, ~$2 to fix. Untouched.
6. **Remaining Codex ideas**, not formally reviewed: render-on-blocked-fetch
   retry, `extract_deals.py --lids`, `needy_lids(only=)` in `read_windows_llm`.
7. **21 shell lids saved no page at all** — a separate, unexamined class.

## 5. The process lesson from this session, because it cost an hour

Paul handed over two named, known-broken websites. I spent the hour instead on a
speculative 100-site sweep that moved the published count by one, then had to be
told twice. **A known failure outranks a hypothesis, every time.** If a sweep is
worth running, it is worth proving on the handful of cases already in hand first.

## 6. Standing rules — still in force

- 🛑 **Scoped runs only, never the corpus.** `--lids` or `--zone`.
- 🛑 **"It is live" is one command:** `python tests/live_front_door.py <zone>`.
  One `NOT LIVE` is GitHub Pages lag — re-run before diagnosing.
- 🛑 **A `web/` edit ships nothing until `build_bundles.py` restamps `sw.js`.**
  Never hand-edit `sw.js`.
- 🛑 **Never run two crawls at once.** No `git merge`/`pull` during a crawl.
- 🛑 **Never write a backslash escape through a bash heredoc** — use Write/Edit.
- 🛑 `open(p, "w")` truncates before `write()` — write `.new` + `os.replace`.
- 🛑 HHF uses its own `.env`. No `ANTHROPIC_API_KEY` in it; never borrow another
  repo's.
- **Pull before push** — Codex works in this repo too.
- **Verify in WebKit as well as Chrome.**

## 7. State at handoff

- `bash tests/run.sh` — green.
- `python ingest/build_bundles.py` — 334 deals, 44 zones, 315 published windows,
  1,214 items.
- `python tests/window_quote_check.py` — 334 published deals, **0** contradicting
  their own quote.
- `python tests/live_front_door.py newark_de` — **LIVE**, 25 of 25 venues named,
  88 items.
- Working tree clean, `master` pushed, live `sw.js` cache name matches the build.
