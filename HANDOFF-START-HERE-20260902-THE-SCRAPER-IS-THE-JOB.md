# START HERE — the scraper is the job, and the last session did not move it

**2026-09-02, late. This supersedes every earlier handoff.**

---

## 0. Read this first, in Paul's words

> *"you didn't actually fix anything with the scraper… you tried to misdirect by
> focusing on the small thing you did with the tomorrow bug, which wasn't what we
> were working on for an hour."*

He is right, and the record should say so plainly. The session shipped three
things — a linked-image rule worth **2 venues of 80**, a redirect guard worth
**1 wrong card**, and the Tomorrow-header fix. **The Tomorrow header was not the
job.** The job was the scraper, and the scraper's binding number did not move.

🛑 **Do not open the next session by fixing something small and reporting it as
progress.** The one number that counts is at the top of §1. If a change does not
move it, say so in the first sentence.

---

## 0a. 🚨 THE COST, CUMULATIVE — read this before you plan anything

Paul, 2026-09-02: *"I want every future session to know what's happening, and
understand that if it isn't solved tonight, I drop Claude as a service."*

**This is not a new problem and it is not a hard-to-see problem. It has been
measured, written down, and not solved, for 33 days.**

| | |
|---|---|
| the scrape yield was first measured, and found low | **2026-07-31** — repo commit #2, *"phase 0: the scrape yield is 19%, not 40%"* |
| days since | **33** |
| working days spent on the menu/item/price/reach problem | **5** (08-06, 08-07, 08-31, 09-01, 09-02) |
| commits on that problem | **70** |
| handoff/plan documents in this repo | **40** — every one of them touches it |
| the goal stated in writing as *"every listed menu"* | **2026-09-01** (`8a22ce8`) |
| venues that ship an hour and still no items | **112** |
| of those, unreachable — no priced sentence, no image | **80** |

**This session alone: roughly two hours of Paul's time, and the 80 moved by 2.**
One hour went to a linked-image rule (worth **2 of 80**); the second hour went to
the Tomorrow-header bug and a redirect guard (worth **1 wrong card**) — neither
of which was the job. The session then reported those as progress, which is the
failure on top of the failure.

🛑 **What this record is for.** Not contrition — a rule. Every one of
those 5 days produced a real, tested, shipped improvement worth single digits,
and 70 such improvements have left the binding number where it was. **That is
evidence the approach is wrong, not that the effort was insufficient.** Reading
better is not the lever. Reach is.

### What a scrape actually costs, and what it returns

Measured from the run records in this repo, not estimated.

**The model pass — every read `data/deals_menus_llm.json` holds, all made
2026-09-02:**

| | |
|---|---:|
| documents sent to the model | **425** |
| reads that produced **any** deal | 47 (11%) |
| reads that produced a deal **with items** | **34 (8%)** |
| items obtained | 310 |
| **reads that produced nothing with items** | **391 (92%)** |

**Two scoped model runs the same evening, from their own logs:**

| run | documents | venues | deals grounded |
|---|---:|---:|---:|
| `scratchpad/shellmodel.log` | 33 | 20 | **1** |
| `scratchpad/shellmodel2.log` | 78 | 30 | **11** |

111 documents across 50 venues returned **12 deals**. By file timestamp the two
passes took roughly **6 and 10 minutes**; the crawl that fed them (99 venues)
finished at 19:23 and returned **18 venues with a deal quote**.

**The whole pipeline, end to end:** 1,585 venues crawled → **314** with a
published window (20%) → **202** carrying items (13%) → 1,224 items.

🛑 **The token cost is NOT KNOWN, and that is its own defect.** Nothing
in this repo records tokens, latency or dollars for a model pass: the sidecars
carry `read_at` as a bare date and nothing else. So the honest answer to *"what
did that scrape cost on the Max plan"* is **we never instrumented it** — and a
cost nobody measures is a cost nobody can argue down. The cost paragraph at the
end of this document is a **09-01 bake-off estimate**, not a measurement of any
run since.

🔑 **First job for anyone touching the model pass: record
`input_tokens`, `output_tokens`, wall time and the model per call, into the
sidecar.** It is a few lines, it makes every later claim about cost checkable,
and without it "8% of reads returned an item" is the only efficiency number that
exists.

🛑 **So: do not spend this session the way the last five were spent.**
Before writing any code, size the fix against the 80 and say the number out
loud. If it is single digits, it is not the job — say so and go find the one
that is not.

---

## 1. 🎯 THE NUMBER — 80

**112 venues ship an hour and no items. 80 of them gave us no priced sentence at
all, and no menu image.** Nothing to read. Their prices are one hop further in —
a PDF, a linked menu page, an ordering platform — or they are pixels.

| why the card is empty | venues |
|---|---:|
| **no price text captured anywhere, no menu image on file** | **80** |
| a price WAS captured; the reader published none of it | 26 |
| image on file, vision pass owes it | 3 |
| nothing in `crawl_hits.json` | 3 |

**71% of the item gap is reach, not reading.** The reading half is fine: 0 of
333 published windows contradict their own quote.

🛑 **Every fix shaped like "read better" has been worth single digits.** The
schema.org-anywhere rule and the linked-image rule together recover **2 of the
80**. Six of the 80 answer 403.

🔑 **Size a candidate fix by PROBING THE 80 before you build it**, never by the
one venue that motivated it. `scratchpad/size_linked_menus.py` is the shape:
read-only, fetches the page the window came from, runs the candidate rule,
reports how many of the population it would recover. Writing one costs ten
minutes and has twice stopped an hour of work worth two venues.

### What "reach" would actually mean

Untried, in rough order of expected yield — **none of these are proven, and the
first job is to size them, not to build them**:

1. **Follow the hop.** For a venue with a window and no price, follow its
   *linked menu page* (not only PDFs, which is all `crawl_one` chases today) one
   level and read that. Sizing question: of the 80, how many link a page whose
   URL or anchor text names a menu?
2. **Render the ones that need it.** `--render` is bounded to hour-named URLs
   and quoteless seed pages. Some of the 80 are ordering-platform shells whose
   prices arrive in JS. Sizing question: how many of the 80 come back as shells?
3. **The 403 six.** A known, bounded set.
4. **The 26 that gave us a price we did not publish** is a *reading* problem and
   the only place a smarter reader is worth anything. It is a quarter the size
   of the reach problem — do it second, not first.

---

## 2. What shipped this session (all live, all pushed)

| commit | what |
|---|---|
| `5099516` | `menu_images()` reads an image the venue **linked under the words** (`<a href="/s/Newark.png">Happy Hours</a>`) — filenames alone could never see Grain's poster, which is named for the town |
| `1b419b2` | Grain Newark's 10 items land; `newark_de` LIVE |
| `231a75f` | **board:** one section header per day — the calendar orders the feed, the sort orders the bars |
| `a4d72f5` | **crawl:** record where a fetch **LANDED**; refuse a page a redirect sent to another town |
| `0dea755` | Grain H2O stops publishing Newark's happy hour; wrong card off the board |

Board now: **44 zones, 314 venues with a window, 202 with items, 1,224 items,
333 deals, 0 contradicting their own quote.** Full suite green (552 Python, 70
JS). `python tests/live_front_door.py newark_de` → **LIVE**.

### Architecture changes worth knowing

- **`get()` returns `(html, err, landed)`.** Any caller unpacking two values
  breaks. Page records carry `"landed"` when it differs from `"url"`.
- **`landed_in_another_town(requested, landed, address)`** in `crawl_sites.py`,
  with `town_slug()` and `_towns["slugs"]` (filled in `main()` from the **whole**
  corpus, never the scoped subset).
- **`web/lib.js`**: `dayOffset()` is exported and is the single source for both
  the feed's day band and `app.js`'s section header. `MAX_DAY`/`DAY_BAND` are
  exported so tests cannot drift from the constant.
- **`tests/render_check.py`** now seeds a location and asserts every section
  header is printed once.

---

## 3. 🚨 The three lessons this session actually earned

1. **A guard with an empty vocabulary is not a guard, and its zero is not an
   answer.** The town reader required no comma before the state; every Delaware
   address (`Bear, DE 19701`) read as townless. It returned a confident `None`
   for the exact case it was built for. Found only by running it against the real
   row instead of a fixture.
2. **A gate must reproduce the reader's conditions.** My header gate **passed on
   the broken code** until it seeded `localStorage.origin` — the defect only
   shows to a reader who granted a location.
3. **Classify on a field that covers the population.** The 112 were bucketed
   wrongly twice: `data/pages/*.json` covers only 410 of 1,585 lids, and the
   `lines`/`hh` keys exist only on rows written by a newer crawl. Both wrong
   answers looked like findings.

---

## 4. Still open, unfixed

- **The 80.** §1. Everything else here is smaller.
- **Southern Cross Kitchen and Sor Ynez** — images the *existing* filename rule
  can already see, which the crawl never recorded. Separate defect, unfixed.
- **Recall has never been measured.** Precision is proven (0 of 333 contradict
  their quote); nobody has counted the real happy hours we walk past. One blind
  town plus one human minute makes the first number that exists.
- **Upper Darby discovery**, and the 21 shell lids that saved no page.
- `MEMORY.md` is ~22KB against the ~17KB its own header declares. Prune on sight.

---

## 5. 🛑 Standing rules — none of these are negotiable

- **Scoped runs only.** `--lids` or `--zone`. Never the corpus.
- **"It is live" is ONE command:** `python tests/live_front_door.py <zone>`.
  One `NOT LIVE` is GitHub Pages lag (~1 min) — re-run before diagnosing.
- **A `web/` edit ships nothing until `build_bundles.py` restamps `sw.js`.**
  Never hand-edit `sw.js`.
- **Never run two crawls at once.** No `git merge`/`pull` during a crawl.
- **Never write a backslash escape through a bash heredoc** — use Write/Edit.
- `open(p, "w")` truncates before `write()` — write `.new` + `os.replace`.
- HHF uses **its own `.env`**; it has no `ANTHROPIC_API_KEY` and must never
  borrow another repo's. The vision path shells out to the `claude` CLI.
- **Pull before push.** Codex works in this repo too.
- Verify in **WebKit as well as Chrome**.

---

## 6. The first five minutes of the next session

1. Read §1. The number is **80**.
2. Ask Paul for his list of what is broken on the board — he has one and offered
   it. Fix his named items; do not sweep for hypotheses.
3. If working the scraper: **write the sizing probe first**, report what it would
   recover across the 80, and only then build.
