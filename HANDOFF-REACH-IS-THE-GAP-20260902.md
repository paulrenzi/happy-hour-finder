# Happy Hour Finder — reach is the gap, not extraction (2026-09-02)

**Read this first, then `ARCHITECTURE-MENU-INGEST.md` §"THE WHOLE FUNNEL,
MEASURED END TO END".** Nothing below was run against a town — Paul's
instruction was *"figure out what's left before we run these, that's for next
session."* This session measured, corrected the record, and stopped.

---

## In one sentence

**The reading half of the pipeline is done: once a readable page mentions a
happy hour we turn 86% of it into a card. What is left is reach — getting a
page in front of the reader at all — and for a town that has never had a
discovery pass we do not have the websites to begin with.**

---

## The measurement, and how to repeat it in one command

```
python ingest/report_funnel.py                       # every zone
python ingest/report_funnel.py king_of_prussia       # one town
```

Reads disk, fetches nothing. It exists because this question got answered from
memory twice and was wrong twice.

| stage | all zones | King of Prussia (most-worked) |
|---|---|---|
| PLCB licensees | 2,788 | 49 |
| website held + crawled | 848 | 49 |
| a page fetched ok | 731 | 43 |
| a page said "happy hour" | 361 | 22 |
| **card on the board** | **216** | **19** |

**card/quote = 86% KoP, 68% corpus-wide.** Everything left is to the LEFT of
the `quote` column.

---

## 🛑 Two claims made earlier this session, struck by the pages themselves

Do not re-derive either. Both were brand knowledge dressed as evidence.

1. ~~"About ten of KoP's 21 no-quote venues plainly run happy hours."~~
   **RETRACTED.** City Works, Davio's, True Food Kitchen, Plaza Azteca and
   Maggiano's were fetched: **75–179 visible lines each, read perfectly well.**
   Their location pages simply do not say "happy hour".
2. ~~"`PAGE_CAP = 4` starves us of the happy-hour page."~~ **RETRACTED.** In a
   30-venue sample of the no-quote class, **zero** unvisited candidate links
   were hour-named. `candidate_links()` already ranks an hour-named link first
   and the crawl already fetches it.

**And a third, caught before it was written down:** a probe reported *"30 of 30
venues are JavaScript shells, 100% of the class was never read"*. That was
`len()` of a **tuple** — `text_lines()` returns `(lines, stacks)`, so every site
on the internet measured "2 lines". The real figure is **13%**, and it inverts
the conclusion. A result with no variance in it is a broken instrument, not a
strong finding. Validate a probe against a case whose answer you already know.

---

## What is left, ranked — this is next session's menu

### 1. Store the visible line count in `crawl_hits.json` — do this first

> **Checked 2026-09-02: this was already built the day before** (commit
> `1a2e2aa`, 2026-09-01). `crawl_sites.py` writes `"lines"` on every ok page
> and `report_holes.py --silent` classifies on it, with
> `crawled-before-the-line-count` for the rows that predate it. What is
> missing is the DATA, not the code: 454 of 2,079 ok pages carry the count,
> and 80 of 566 no-quote venues have it on any page. It fills in as scoped
> recrawls run. Nothing below needed re-deriving on this point.

`"ok, 0 quote(s)"` currently means **both** *"we read the page and it has no
happy hour"* **and** *"the page was a JavaScript shell and we read nothing"*.
No line count is stored, so **the 390-venue no-quote class cannot be separated
without re-fetching it** — which is exactly what this session had to do. One
field in the page result dict, written in `crawl_sites.py` where the lines are
already in hand. Cheapest item on the list, unblocks the measurement of every
item below it. Nothing needs re-crawling to start recording it.

### 2. Widen the render gate — ~13% of the no-quote class, ~50 venues

> **Built and run 2026-09-02.** `render_wanted()` now also
> fires for a depth-1 seed page of a venue with no quote yet, and the rendered
> HTML feeds `candidate_links()`. Six tests cover it, including the end-to-end
> shape: shell seed → render → `/happy-hour` discovered → quote. The ~13%
> yield is still the sampled figure, not a measurement.
>
> **Run against phoenixville 2026-09-02 (24 needy venues): 4 pages rendered,
> 0 quotes.** First real firing. It also exposed that `report_holes.py` called
> a page under 40 lines a shell while the gate refused anything over 25 --
> Chikara Sushi's 36-line homepage was reported as needing exactly the fix the
> crawler would not apply to it. The two now share one constant. The run added
> **no card**: all five quote-carrying venues say "happy hour" and state no
> clock, and the two windows that looked recoverable were a phone number and a
> set of business hours. ~~Both refusals are correct.~~
>
> 🛑 **STRUCK 2026-09-02 by Paul, in one minute with a browser.** The run was
> a failure, not a correct refusal: Revival, Rivertown Taps, Sly Fox and
> Sedona Taphouse all publish a happy hour in Phoenixville and none had a
> real card. See "The four misses" below. **A run that reports a town empty
> is checked against one human minute before it is called correct.**

`render_wanted()` requires `page_is_hh(url)` (the URL must name an hour) **and**
a page under `RENDER_LINE_FLOOR`. A shell homepage's URL does not name an hour,
and a shell yields no links, so the hour-named URL is never discovered. **The
gate is keyed on the thing the failure destroys.** Result: across all 390
no-quote venues, **zero pages were ever rendered**, `--render` on or off.

Fix is one condition, not a redesign: *a page under the line floor is a shell
whatever its URL says*, and the homepage of a venue with no quote is worth one
render. `RENDER_CAP = 40` already bounds the spend. Sized honestly: ~50 venues
corpus-wide, and some of them are Starbucks.

### 3. Cross-domain ordering hosts

True Food Kitchen's menu is at `order.truefoodkitchen.com` — a different
registrable domain, so `candidate_links()`'s host test drops it. That test was
already widened once for sibling hosts on the same domain; ordering platforms
(Toast, ChowNow, Zuppler, `order.*`) are the next case, and the same shape as
the Darden "menu is an API record" finding. Wild Rice already sits on
`food.zuppler.com` in KoP with no quote.

### 4. Website discovery for the unworked towns — the real volume

This is the biggest number in the project and it is not a scraper problem.
North Philly holds a website for **7 of 206** licensees; Center City 134 of 574;
Upper Darby 5 of 67. `report_funnel.py` flags these with `<- no discovery pass`.
**The first question about any town Paul names is whether discovery has run on
it** (`ingest/discover_sites.py`), because until it has, no extraction number
from that town means anything.

### 5. A licence-class filter, so recall numbers stop lying

The no-quote class contains Starbucks, Chipotle, Five Guys, Jamba, Saxbys,
GIANT, a catering company and an expo centre. **A PLCB licence class is not the
thing it names.** Some real share of the 390 is *correctly* empty, and every
recall percentage that treats all 390 as misses overstates the hole. Worth one
pass with `ingest/exclusions.py` before anyone quotes a coverage figure again.

### Not worth a project

- **The canonical guard**: only **2 pages** in the whole corpus were refused by
  it. One of the two is True Food's KoP page **refusing itself**
  (`canonical says king-of-prussia, not us`) — worth one look, not a lane.
- **Fetch failures**: 142 pages, dominated by `robots.txt unreadable (403),
  treated as disallow` (86) and `robots.txt disallows` (56). **These stay
  refused.** Robots is obeyed in this repo and the earlier override is retracted.

---

## The four misses (2026-09-02) — reach again, every one of them

Paul pulled up four Phoenixville happy hours in one minute after a run had
called the town empty. Not one was a reading problem; each was a page or a
picture the crawl never put in front of a reader. All fixed in commit
`9a1c861`, all four now on the board with the window and items their own
pages state.

| venue | where the happy hour was | why we never saw it | fix |
|---|---|---|---|
| Sly Fox | `/phoenixville`, "Appy Hour" Tue–Fri 3–6 | the link matched no `LINK_WORD`; the page never says "happy hour"; a trailing "saturday" line joined the quote | a link naming the venue's **own town** ranks first (`town_re`); "appy hour" is a heading; a day line **above** a heading owns it |
| Sedona Taphouse | `/locations/phoenixville-pa/` + `HappyHourMenu_PhxWC.pdf` | town link dropped, then displaced by three `nye-special` sitemap URLs; the PDF anchor is 220 chars of card markup, the link regex allowed 120; "$20 Oﬀ" (ligature) read as a $20 price | town link stays ahead of the sitemap top-up; anchor cap 400; NFKC on PDF text |
| Rivertown Taps | `Happy-Hour-Specials.png` on `/menu/` | images were only collected on hour-named URLs; the venue has **no text at all** | a self-named HH image counts on any page; the vision pass keeps its transcript in `data/menu_image_transcripts.json` and `extract_deals.picture_spans()` runs the unchanged window grammar over its happy-hour lines |
| Revival Pizza Pub | `Revival HH.png` on `/happy-hour-menu` | `MENU_IMG_RE` wanted `_hh_`/`-hh-`, URL had `%20HH.png`; the card carried **$6 margaritas** (Margherita Monday) because every quote fed the price pass | standalone `hh` token + unquote; `extract_prices_llm.vouched()` and `read_pages_llm.worth_reading()` refuse day/weekly/lunch-specials URLs |

**Corpus-wide, unrun by the standing constraint:** 16 venues have quotes from
day/weekly/lunch-specials pages and no happy-hour quote at all (VK Brewing,
Chap's, Cracker Barrel, Blue Dog among them). Their price sidecars were built
from those quotes. `--reverify` on the price pass does NOT apply `vouched()`;
a scoped recrawl of each town will.

**Known warts left on Sedona's card:** a duplicate `house wine by the glass
and $7.9` from the quote-regex item pass beside the page reader's clean
`House Wine by the Glass`. Cosmetic; not a wrong price.

**The measurement to add:** a town run should end with the four-venue check
Paul did by hand — open the top hits for "<town> happy hour" and ask whether
each has a card. That is the test the funnel table above cannot express.

---

## Still Paul's call, carried forward, not started

- `clauses()` does not split on a **line break** (Miller's Ale House states two
  schedules across one).
- Whether a no-meridiem range like `tues-fri from 3:30-5:30` on a page headed
  HAPPY HOUR may be read as afternoon. Today it is refused, and that refusal is
  why the window pass is safe to ship.
- The older carried ones: Morton's priceless named menu, Bonefish's start with
  no end, menus not on venue websites, all-day-special phrasing.

---

## State of the tree

- Everything is committed and pushed on `master`; working tree clean.
- `9a1c861` (2026-09-02): the four-misses fixes, 355 tests, exit 0.
- `bash tests/run.sh` **exits 0**.
- `python ingest/build_bundles.py` produces **no diff** — the live site is in
  sync with the committed data.
- **Verified live in WebKit** at <https://paulrenzi.github.io/happy-hour-finder/>
  this session: `The StoneRose — Starts 4pm — 11 items` (conshohocken),
  `Anthony's Coal Fired Pizza — Starts 3pm — 26 items` and `GARRETT HILL ALE
  HOUSE` (wayne_radnor), `Bistro on Bridge` and `il Granaio` (phoenixville),
  plus the KoP board. No page errors.
- 209 deals across 38 zones ship; 216 rows on the board (7 second licences
  collapsed into their bar's card — one bar, one card).

## Standing constraints — unchanged

- **No full-corpus runs.** A run names its towns; `ingest/needy.py` names the
  venues inside them.
- **West Chester stays untouched** until the small towns are good. They are not
  good yet.
- Robots.txt is obeyed; the previously recorded override is retracted here.
- This repo has **its own `.env`** and must never read `shopify-analytics/.env`.
- A web page is verified by **running it**, in the engine users run, at the live
  URL — never by an HTTP 200 or an intermediate file.
