# How a menu becomes items — the architecture, and where it breaks

**Read this before touching `ingest/crawl_sites.py` or `ingest/extract_deals.py`.**
Written 2026-09-01, after three venues Paul found by browsing the sites himself.

The product's hard part is no longer the website, the zones, the ranking or the
PA validators. It is this: **a venue publishes a happy hour menu, and we cannot
read it.** 107 of the 175 windows we publish name a schedule and not one thing
you can buy. This file is the map of why.

---

## The goal, stated by Paul 2026-09-01

> Get every single menu that's listed, period. If the website has a happy hour
> menu, we do everything required to actually get it, read it and ingest it, in
> whatever form it takes.

That is the standard. Not "most", not "the ones on platforms we have met."

---

## The five gates

A fix that stops before the last gate has moved no data and is not a fix.

```
ingest/crawl_sites.py     the web  -> data/crawl_hits.json      (QUOTES, never deals)
ingest/extract_deals.py   quotes   -> data/deals_extracted.json (deals + items)
ingest/build_bundles.py   deals    -> web/data/*.json           (per-zone bundles)
git push                                                         (GitHub Actions)
GitHub Pages              the LIVE URL in a real browser
```

Scoped recrawl of a few venues, which is what you want while iterating:

```
python ingest/crawl_sites.py --lids scratch/lids.txt --recrawl
python ingest/extract_deals.py && python ingest/build_bundles.py
```

**The last gate is a browser at the live URL.** An intermediate file, a green
aggregate, an HTTP 200 and a card count are each blind to a different failure.
`tests/render_check.py` and `tests/search_check.py` hold the working selectors —
`#menuBtn` then `#search`, and **reload between venues** (the panel toggles, so a
second click closes it).

---

## Two ways to read a menu, and only one of them is honest

### Prose inference — the old way, still used for most venues

The crawler grabs text quotes; `extract_deals.py` matches price patterns and
infers the *kind* of thing (draft / wine / cocktail / food ...) from a word list
over dish names. It is how independents get read, and it is lossy by
construction: re-deriving what the source already stated can only be less
accurate than reading it. On structured data a word list can only **lose** items.

### Structured adapters — read what the source states

The source itself says the dish, the price, and the section. Two exist:

| adapter | platform | trigger today | what it reads |
|---|---|---|---|
| **Darden** | Darden's menu API | `DARDEN_HOSTS` tuple (8 brands) | products, prices, and the *other* menus for the not-a-deal gate |
| **FRC** | Fox Restaurant Concepts markup | `FRC_HOSTS` tuple (6 brands) | `menu-item-name` / `menu-item-price` / `data-section-slug` |

Both emit quotes carrying a **`[cat:x]` marker** — the source's own category.
`strip_category_marker()` in `extract_deals.py` reads it instead of guessing.
The board has exactly eight categories: `draft, bottle_can, wine, well, call,
cocktail, shot, food`. A section that maps to none of them is **REFUSED and
logged by name**, never filed under the thing it resembles. A Phony Negroni on
the board as a cocktail is a customer ordering a drink that is not what they
came for.

> 🛑 **The trigger is the defect.** Both adapters are gated on a typed-in list of
> **hostnames**. A sibling brand on the *identical platform* that nobody typed in
> falls silently back to prose inference and becomes another window with no
> items. The fix is to **fingerprint the platform, not the brand** — trigger FRC
> on seeing its markup, Darden on the menu API answering — so an unseen brand on
> a known platform reads correctly the first time we ever meet it. This is the
> cheapest single change available and it is not done.

---

## The hole report — the scraper names its own misses

```
python ingest/report_holes.py                     # ranked by class
python ingest/report_holes.py --class chrome-only # one class, with URLs
```

Offline. Fetches nothing, decides nothing. Reads `crawl_hits.json` +
`deals_extracted.json`.

**A published WINDOW with ZERO ITEMS is the machine-visible signature of a
scraper miss.** Every venue Paul found by hand already had it. Run this after
`extract_deals.py` on any new zone, *before* asking what to look at.

**The class is the unit of work, not the venue.** One slug alias fixed two
Capital Grilles; one adapter fixed a chain. A class holding one venue is
probably not worth code.

| class | count 2026-09-01 | meaning |
|---|---|---|
| `no-price-published` | 36 | several quotes, no `$` anywhere — some genuinely publish no prices |
| `priced-but-unreadable` | 33 | **prices ARE in our quotes and our own extractor refused them** — offline parser work, no fetching |
| `nothing-but-the-hours` | 18 | the hours quote is all we got — JS menu or an API (this was Capital Grille) |
| `chrome-only` | 14 | we read the nav tabs and stopped (this was North Italia) |
| `menu-is-a-document` | 6 | a PDF we reached and read nothing out of |

---

## Findings that cost a session each — do not re-learn these

**A price can have no dollar sign.** North Italia's entire happy-hour menu was
inline HTML on the first byte the whole time. The handoff said "JS-rendered
menu"; it was not. This platform prints `<span class="menu-item-price">8</span>`,
so `DEAL_RE`, `BARE_PRICE_RE` and the price pass all looked straight past a full
menu. **Before concluding a menu is JS-rendered, grep the raw bytes for the dish
name.**

**A page a human sees can be 2.7 KB of loader to us.** `thecapitalgrille.com/happy-hour`
is exactly that — the button and the items are real, and drawn in the browser.
The menu came from the API instead. Paul is right that the *site* is simple; the
complication was entirely ours.

**A brand may not call it "happy hour."** Capital Grille brands its as
**CAPITAL HOURS** (`capital-hours`). Matching the literal slug read the hours
fine and returned zero dishes — the same silent nothing as a venue we never
crawled. Fixed with an explicit per-brand alias, `DARDEN_HH_SLUGS`, and
deliberately **not** a loose pattern: a loose match does not fail closed, it
files a brand's dinner menu as a happy hour and puts full-price steaks on the
board as bargains.

**A priced happy-hour line is only a deal if it BEATS the same dish elsewhere on
that menu.** The gate matched on product slug alone, and a brand that shortens
the name on its HH menu walks through it. Three full-price appetizers — a $40
caviar dip among them — were about to publish as bargains. `darden_regular()`
now matches normalised names too, prefix-match included.

**The silent-drop class.** An item vanishes with no error anywhere:
`®`, `™`, a **mid-name `*`** (footnote mark), accents, curly quotes, a 40-char
cap, and `$5.5` — neither two decimals nor none, which deleted All Beers at
$5.50 because `rstrip("0")` had turned a valid half-dollar into a shape the
label pattern refuses. `money()` and `darden_dish_name()` handle these now.
**When items are missing and nothing errored, suspect the label charset.**

**File structured hits under `venue["website"]`.** `items_from_hits()` pairs
items to a schedule by exact URL. North Italia produced 19 quotes and 0 items
because the dishes were filed under `?menu=happy-hour` while the hours came from
the bare URL. Darden already did this correctly; FRC now does too.

**A number in a handoff is not a measurement.** A suspected regression on
Eddie V's (18 items vs a handoff's 17) was checked by running the pre-change
code out of `git show HEAD:ingest/crawl_sites.py`. Base was also 18. The handoff
was stale.

**Patch this file with a script, not a heredoc.** An unquoted heredoc collapses
backslash escapes and a repair then reports success and changes nothing. Write
`.new` and `os.replace`.

---

## Standing rules

- **One venue at a time, finished on the live site before the next**, and Paul
  picks the next one. Since 2026-09-01 the unit is increasingly the **class**.
- Open with one plain-English sentence: no jargon, no paths, no numbers.
- `bash tests/run.sh` runs everything. A web page is verified by **running** it.
- This repo has **its own `.env`**. It must never read `shopify-analytics/.env`.
- Crossing a state line changes the law, not just the data. `RULES["DE"]` is
  deliberately empty; it needs a named authority and Paul's sign-off, never
  inference from PA.
