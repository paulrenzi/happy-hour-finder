# HANDOFF — re-analyze the architecture, or the project ends

**Written 2026-09-02, at Paul's instruction, after the West Chester run.**
Paul's words: *"this entire process is completely broken and both a waste of time
and tokens. next session we are going to entirely re-analyze the architecture to
try and fix it one more time. if it cant be done, neither can this project."*

Read this file first. **The next session is an ANALYSIS session, not a run.**

---

## 0. What is actually true right now

**The West Chester work IS on the live site.** That is not a claim this time, it
is a check anyone can re-run:

```
python tests/live_front_door.py west_chester
```

It opens `https://paulrenzi.github.io/happy-hour-finder/` at its **root**, in a
**fresh WebKit context with no service worker and no HTTP cache**, drives the
zone picker the way a person does, and compares what is **painted** against the
**locally built** bundle. Result at time of writing: *13 of 13 named live, 37
blocks painted, 0 page errors.*

🔑 **This tool is the whole reason "it's live" was reported wrong repeatedly.**
Every earlier claim rested on a smaller question — `render_check.py` runs the
LOCAL page; fetching `data/zone-*.json` proves a FILE shipped. Neither proves the
board a visitor opens draws the work. **Nothing may be called live except by
running the command above.** It ships in `tests/` precisely so it cannot be lost
the way the gitignored `scratch/live_check.py` was.

If Paul still sees an old board on his own device, the cause is his **installed
PWA holding an old service worker**, not the deploy. `web/sw.js`'s own comments
record this exact class of bug twice before. That is a real product defect and it
belongs in the analysis below — **a user who cannot see a fix does not have the
fix.**

---

## 1. Paul's verdict on the output, which is correct

> *"the west chester list is embarrassing. of the 13, which is already far too
> low for a town that size, you barely have any information on deals"*

Both halves are true and the numbers say so:

| West Chester | |
|---|---|
| venues in the licence base | 62 |
| cards with a happy-hour window | **13** |
| total priced items across all 13 | 78 |
| **items contributed by just Opa Taverna + Lascala's Fire** | **49 of 78** |
| cards carrying <= 3 items | 7 |
| cards carrying **zero** items | 3 |

The median West Chester card carries about **two** items. "Barely any information
on deals" is the accurate description of the product, not an overstatement.

---

## 2. THE FUNNEL — this is where the next session starts

`python ingest/report_funnel.py` — the most useful single artifact in the repo:

```
zone                          lic  site crawl    ok quote  card   card/quote
west_chester                   62    49    49    46    20    13    65%
king_of_prussia                49    49    49    43    22    19    86%
willow_grove_horsham           43    32    32    29    14    11    79%
ALL                          2788   888   888   769   380   236    62%
```

**Two walls, and they are not the wall we have been fixing.**

### Wall 1 — supply: 888 of 2788 venues have a website at all (32%)

Most zones are marked `<- no discovery pass`. Zones that HAVE had one run 79-100%
website coverage; zones that have not run ~10-25%. **This wall is understood and
is bought with money, not cleverness** (Google Places `websiteUri`, ~$2/town).
It is not the interesting one.

### Wall 2 — yield: 769 crawled OK produce only 380 quotes (49%)

**Half of every site we successfully fetch yields nothing.** In West Chester:
**46 crawled fine, 20 gave a quote, 26 gave nothing.** These are not unreachable
venues. We got their pages. We read them. We published nothing.

**Wall 2 is the project.** Every session so far has fixed instances of Wall 2 one
at a time — a CDN host, a label above an anchor, `EVERY. SINGLE. DAY.` Each fix
was correct and each recovered roughly one venue. **At one venue per fix, this
never finishes.** That is the architectural finding, and it is the thing to
re-analyze.

### And the yield that DOES pass is thin

`python ingest/report_holes.py` — of the 231 published windows, **117 name no item
at all**, in six named classes:

| class | venues | what it means |
|---|---|---|
| `no-price-published` | 37 | the tool's own note says **24 of 36 audited had prices in the raw HTML** — so this class is mostly OUR miss, not the venue's silence |
| `priced-but-unreadable` | 26 | prices are in the quote and the extractor refused them |
| `nothing-but-the-hours` | 25 | likely a JS menu or an API we never execute |
| `menu-is-a-picture` | 11 | the words are pixels; this is the vision pass |
| `chrome-only` | 11 | we captured navigation, not content |
| `menu-is-a-document` | 7 | PDF / doc |

🔑 **`no-price-published` being 24/36 wrong is the single most important line in
this handoff.** The largest "the venue just doesn't publish prices" class is
mostly a **retrieval failure that reports itself as an absence.** Same shape as
every silent defect this project has hit: *a refusal that never prints is
indistinguishable from an absence.*

One more, from `extract_deals` on the West Chester run: **17 quotes were rejected
as "opening hours, not a happy hour"** against only **8** windows genuinely read
off a page. The classifier throws away twice what it keeps.

---

## 3. What the next session should actually analyze

Do not open a town. Do not spend a dollar. Answer these, in order:

1. **Is the crawl -> quote step the right architecture at all?** We fetch HTML,
   regex for happy-hour-ish text, then ask a model about what we found. The 26
   West Chester venues that crawled fine and published nothing are the sample.
   **Pull ten of them by hand and look at what is on the page.**
   - If the deal is visibly there in the HTML we already fetched, the
     architecture is fine and the **selection logic** is broken.
   - If the deal is behind JS, an API, an image, or a PDF, the **architecture is
     wrong** and needs a rendering crawler, not more regex.

   **This one question decides whether the project continues.**
2. **Audit `no-price-published` properly.** The 24/36 note is from 2026-09-01 and
   was never acted on. If it holds, ~25 venues are one fix away.
3. **Why does the hours-vs-happy-hour classifier reject 17 and keep 8?** Sample
   the 17.
4. **The service worker / stale-board problem.** Paul could not see shipped work.
   Whatever the cause, the product must not be able to show a user an old board.

**Paul's own proposal is on the table and should be taken seriously:** *"im going
to end up clicking on each website by hand again and handing them to you."* A
human minute per venue may genuinely beat this pipeline. **If the analysis says
so, say so.** That is a legitimate answer, not a failure to report.

---

## 4. Standing rules that did not change

- 🛑 **No corpus runs, ever.** One town, scoped, finished on the live site.
  **Paul picks the next town.**
- 🛑 **A web page is verified by RUNNING it**, now specifically by
  `tests/live_front_door.py`. An HTTP 200 is not verification. A local render is
  not verification.
- Robots obeyed.
- Grounding: every span is a literal substring of the document, checked at write
  time and re-checked by `build()` against the file on disk.

## 5. Open items carried forward

- **Paul's call:** 8 West Chester venues are genuinely absent from the
  licence-derived base (The Social, LoCali Wine Lounge, High Street Caffe, Bier
  and Loathing, Bottle Room, R Five Wines, Concordville Bar and Grille, Victory
  Brewing Downingtown). Listed under `unmatched` in
  `data/ground_truth/west_chester.json`. Adding non-licensees to a licence base
  is not a session's decision.
- **Paul's minute:** no ground-truth row is confirmed for ANY town, so
  `report_coverage` still prints "no denominator, no percentage". Worksheets
  exist for Ambler and West Chester. **Without this the project has never had a
  real accuracy number** — every quality claim, including this handoff's, is
  measured against our own output.
- **Named, not built:** `reach_llm links` loses a batch to `JSONDecodeError`
  (5 of 42 venues in West Chester). The failing reply is not saved, so there is
  nothing to inspect. **Saving it is the fix, not a retry.**
- A multi-deal venue's board row is "what starts first" vs "the best deal"
  (Sly Fox).

## 6. Landed this session

- **Bonefish CDN reach:** `same_site()` document exception, `hh_named_docs()`
  reading ~400 chars above the anchor, `EVERYDAY_RE` += `EVERY. SINGLE. DAY.`,
  and the photo guard's possessive/plural fold. Acceptance test: the real page's
  happy-hour PDF is candidate rank 0 and uniquely named.
- **`another_towns_row()`** — a chain's events calendar is every town at once;
  West Chester was shipping Pottstown's and Drexel Hill's trivia, **both
  correctly grounded**. Checked in `vet()` **and** `build()`.
- **Two joiner defects** that inflated the "missing restaurants" count by a third
  (`house_numbers()` dropping the third part of `5-7-9 N Walnut St`;
  `match_place()` demanding a ZIP agreement inside one town).
- **`tests/live_front_door.py`** — the shipped liveness instrument in §0.
- 408 unittest tests, `tests/run.sh` 0 fail.
