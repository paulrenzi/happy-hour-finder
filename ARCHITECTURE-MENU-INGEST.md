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

## 🔑 Three ways to read a menu — and only one of them can make a JUDGEMENT

**Added 2026-09-01, after Paul: _"why would a scraper running sonnet miss that
the whole page is a happy hour menu? there's no intelligence running over pages.
that's a mistake."_ He was right, and the answer is worth stating plainly
because it is the shape of every miss in this file.**

**The scraper was not running a model. It was not running any model at all.**
`crawl_sites.py` is ~2,000 lines of regex and DOM rules. `extract_prices_llm.py`
— the only model in the pipeline before today — reads **the quotes those rules
already produced**, prices only, never windows, never pages. So:

> 🛑 **A page the rules threw away was invisible to every model we run.** The
> model could not see the page. It could only see what a regex had already
> decided was worth keeping.

Three defects found in one hour of looking, all the same defect:

| what the venue wrote | what the rule said | cost |
|---|---|---|
| bartaco `/kophightidehour/` | `depth>1 and /happy.?hour\|special/` | menu is a **PNG**, never collected |
| Morton's `/event/power-hour/` | same regex | page read as ordinary |
| Sullivan's `/menus/happyhour-food-drink/` | needs an hh *heading*; page has none | 4 price bands, 26 dishes unread |

And the one no rule can fix: those dishes now reach `extract_deals.py`, which
asks `category_of()` — a **hand-typed noun whitelist** — and keeps **two of
nineteen**. "Beef Wellington Bites", because *bites* is a word somebody typed
in, and **"Jumbo Shrimp Cocktail", filed as a COCKTAIL**. A shrimp cocktail, on
the board, as a drink. "A5 Wagyu Nigiri" matches nothing and is dropped with no
line in any log.

**`ingest/read_pages_llm.py` is the answer.** `crawl_sites.py` now caches the
visible text of every happy-hour page to `data/pages/`, and that pass reads the
**whole page**. Same safety contract as the price pass, and it is what makes it
shippable:

- **Items only.** It never sees, proposes or alters a **window**. Days and times
  stay with the deterministic extractor and its meridiem rules, so
  *"no meridiem ⇒ refused, never guessed"* is untouched.
- **Every item carries the span it came from**, checked against the page in code
  by the same `verify()`. The model is a **reader, not a source**.

> 💰 **Cost is the NUMBER OF CALLS, not the size of the model.** `claude -p`
> bills a fixed harness on every invocation — 28,272 tokens, 9,407 with
> `LEAN_ARGS`. At batch 40 opus beat haiku on raw tokens *and* recall at once.
> **Batch size is the lever; the model is the smaller adjustment.** This is also
> why a haiku-then-sonnet **cascade can cost more than sonnet alone** — it
> doubles the calls. Sonnet, batched, is the setting (Paul, 2026-09-01).

> 🛑 **Cache widely, read narrowly.** The crawler caches on "happy hour appears
> anywhere", which is right — a page not kept cannot be reconsidered. The words
> are in the NAV of every restaurant site alive, so the first run put **47 pages
> up and 41 were a bottle shop's homepage**. `worth_reading()` gates the model
> on the page making a claim about ITSELF: the URL names an hour, or ≥2 prices
> under a happy-hour heading. A page that fails it is **not judged menu-less** —
> it is just not worth a call, and it stays cached.

### The headless tier

A page whose HTML holds no page is rendered in WebKit (`--render`), then read by
the same readers with the same containment. Bounded hard, because it is ~40x a
fetch: only a page whose URL **names an hour** that came back under 25 lines.

The Cheesecake Factory is the case that motivated it — 13KB of Laravel shell,
**11 visible lines**, no API. Rendered: **161 lines, 24 quotes.** And it shows
why the model tier is needed right behind it, because what the regex made of
those quotes was **`"800 cal $10.95"`** — a real price bound to a **calorie
count** instead of a dish.

> ⚖️ **`menu.thecheesecakefactory.com/robots.txt` is `User-agent: * / Disallow: /`,
> and we obey it.** An override was built on 2026-09-01 and **removed on
> 2026-09-02: it was attributed to a decision Paul never made in this repo.**
> 🛑 The crawler has **no way to ignore robots.txt** and must not grow one
> without Paul saying so about *this* project, in writing, here.
>
> The Cheesecake Factory's King of Prussia menu was collected from an
> **allowed** page, so nothing on the board depends on the override that is gone.

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

## The OTHER hole population — "Hours not published" (2026-09-01)

```
python ingest/report_holes.py --silent                        # every zone
python ingest/report_holes.py --silent --zone king_of_prussia
python ingest/report_holes.py --silent --class page-is-a-shell
```

There are **two** hole populations and only one of them was ever measured.

| population | signature | size | reported by |
|---|---|---|---|
| a window and **no items** | card says "happy hour 4-6" and names nothing | ~100 | `report_holes.py` |
| **no window at all** | card says **"Hours not published"** | **~2,584** | `report_holes.py --silent` |

Paul's complaint — *"the amount of places in just King of Prussia showing under
'Hours not published' with happy hour menus I can find with a few clicks"* — is
entirely about the second one, and nothing in the repo could rank it.

**What made it rankable is one field in the crawl.** A fetch that returns 200
and 11 lines of text and a fetch that returns 200 and 400 lines were **the same
row** in `crawl_hits.json`, and they are opposite problems: the first is a
JavaScript shell we cannot see into, the second is a page we read in full that
does not mention a happy hour. So `crawl_sites.py` now records `lines` and `hh`
per page, and `classify_silent()` sorts the whole silent population into named
classes ranked by size. **A silent venue is not a mystery; it is one of eight
things, and seven of them are ours.**

### 🔑 What King of Prussia turned out to be, once every class was worked (2026-09-01)

KoP is the proving zone: fill it to the brim with very little fallthrough, then
Phoenixville / Ardmore / Wayne. It went **16 → 18 venues on the board** across
one session, and — this is the part worth carrying forward — **the residue is
mostly not fallthrough.**

| what the 34 silent KoP venues actually are | n |
|---|---|
| **genuinely do not publish one** — read in full, and re-checked at a 40-page budget | 21 |
| **we cannot fetch the page at all** — robots.txt refusal, 403, timeout | 6 |
| **says happy hour, window unread** — the real remaining work | 6 |
| venue answered: it has none | 1 |

Of the 21: eight were classed `page-is-a-shell` and assumed to be the headless
tier. **All eight were rendered in WebKit and not one mentions a happy hour.**
True Food Kitchen goes 0 → 193 lines of text and still says nothing; Eataly
renders 396 lines and says nothing. **The headless tier returns zero for King of
Prussia.** The rest are a supermarket, a department store, a cinema and chains
whose location pages carry no hours.

> 🛑 **This is the third time a class was sized on a suspicion about its CAUSE
> and counted as if it were a pile of work** — after the hotel licences and the
> "no-price" venues. `page-is-a-shell` is a description of a page, not a
> diagnosis of why. **Render one before budgeting for all of them.**

> 🔑 So *"every menu that exists on a website"* and *"a full board"* are not the
> same target, and KoP is the proof: most of what is missing there is missing
> from the **venue's own site**, not from our reader. Closing the rest means
> going somewhere other than the venue's website — which is a product decision,
> not a scraper fix, and it is Paul's.

| class | meaning / the work |
|---|---|
| `never-crawled` | the frontier never queued a site we hold — a crawl input bug, and the cheapest venues on the list. Cheesecake Factory, Tommy Bahama and Wegmans in KoP alone |
| `page-is-a-shell` | 200 OK, under 40 lines of text — renders in JavaScript. **The headless tier, one fix for all of them.** Cheesecake's own `/happy-hour` is 13 KB of HTML and **11 lines** |
| `says-happy-hour-no-window` | the page says "happy hour" and we read no clock — the window is on another page, in an image, or in a form the grammar refuses |
| `quotes-but-no-window` | we kept quotes and none carried a window — where a grammar gap shows |
| `no-mention-anywhere` | read in full, never says it. Most of these genuinely publish none |
| `venue-says-it-has-none` | **an answer, not a hole.** Founding Farmers: *"we don't have a traditional happy hour"* / *"Every hour is happy here!"* |
| `robots-refused` / `fetch-failed` | the site refuses us, or the chain errors |
| `crawled-before-the-line-count` | crawled before 2026-09-01 — **recrawl to sort it**, never guess a line count |

**Are we ready for the next zone? No — and it is now sized.** Three tiers, in
order of return: recrawl to populate `lines`/`hh`; the headless tier for the JS
shells; the never-crawled frontier bug. Run the report on a zone *before*
deciding what to build for it.

### 🛑 The headless tier was sized on the wrong number (2026-09-01)

That ordering put the headless tier second on the strength of the
`page-is-a-shell` **count**. The count was never the question. `page-is-a-shell`
says *why we think* a venue is silent — it does not say a happy hour is hiding
behind the JavaScript, and for King of Prussia **none was.**

All 8 of KoP's shells were rendered in WebKit (the browser a headless tier
would use) and **not one mentions a happy hour**. True Food Kitchen goes from
0 to 193 lines of text and still says nothing; Eataly renders 396 lines and
says nothing. They are silent because the venue publishes nothing, not because
JavaScript hid it. **Building the headless tier for KoP would have returned
zero.**

This is `audit the classifier before planning on its counts`, again, and it is
the third time: `'Hotel (Liquor)'` was a licence class and not a hotel, 24 of
36 `no-price-published` venues had prices, and now `page-is-a-shell` is a
hypothesis about a cause, sized as though it were a stock of work.
🔑 **A class name states a SUSPICION. Before building the fix a class implies,
open the venues and check the fix would land.** Rendering eight pages cost two
minutes and cancelled a tier.

The real reclaim in KoP was two crawler bugs, not a renderer — see
`frontier()` and the seed-dropping fix in `crawl_sites.py`.

### The reclaim classes found behind KoP's 45 silent venues

Seven venues say "happy hour" on their own homepage while we publish nothing.
None of the causes is venue-specific:

- **the window line never entered the quote** — bartaco's page reads "high tide
  happy hour / (at the bar) / weekdays 3-6pm" and our quote stops at the first
  two lines. The grammar is innocent: `days_in('weekdays 3-6pm')` → `{1..5}`.
- **items but no clock ⇒ we publish nothing** — Peppers and Pizzeria Vetri both
  name priced items under a "Happy Hour" heading and no window was found.
- **a start with no end is refused** — Bonefish: "Happy Hour starts at 3:30pm
  daily." The card already renders "Starts 3pm" (Tommy's proves it). Publishable,
  and being thrown away.
- **JavaScript shells** — Cheesecake 11 lines, Bonefish 163 KB and 55 lines.

🛑 **Two of the four causes above were misdiagnosed, and the correction is the
useful part.** bartaco was written up as "the window line never entered the
quote — the grammar is innocent." The grammar was innocent and so was the
quote: the page we were given (`/kophightidehour/`) is a 29-line shell that
does not contain a window **at all**. The window is on `/location/kop/`, a URL
we already held in `venue_base`, and we had never fetched it — for two reasons,
both now fixed (`frontier()` seeds both URLs; untried seeds survive the queue
rebuild). And Cheesecake was never a JavaScript shell either — it was
`never-crawled`, and reading it took no renderer, only asking.
🔑 **Before believing a diagnosis in a handoff, fetch the page and look.** Both
of these had been reasoned about rather than opened.

---

## Who is not on the board — `ingest/exclusions.py` (2026-09-01)

One module, two doors: `build_venue_base.py` (where a venue first exists, and
in the sibling-LID pass too, so a ban cannot re-enter as an `also_lids` of the
premises next door) and `build_bundles.py` (so a **stale committed base cannot
put a banned venue back on the site**).

- **Bald Birds Brewing — banned by Paul, permanently.** Keyed on the PLCB
  licensee name, matched as *contained*, because the trade name arrives from
  Google as "Bald Birds Brewing Company - King of Prussia".
- **Hotels.**

🛑 **`'Hotel (Liquor)'` is a LICENCE CLASS, not a hotel.** 178 venues hold one
and only 87 are hotels. A licence-based filter — which was nearly shipped —
would have deleted The Black Horse Tavern, The Stray Dog Tavern, Joseph Ambler
Inn, Panorama and CO-OP Restaurant & Bar, all of which publish a happy hour and
were on the board. This is the classifier-audit rule made concrete: **a class
assigned by one field is a hypothesis; census it against the venues it would
delete before acting on it.**

So a hotel is recognised by **brand**, plus the narrow case of `hotel|motel` in
the name *and* the hotel licence *and* no `NOT_A_HOTEL_RE` word. `Inn` is
deliberately not a signal on its own. And `motel` is **not** in the brand list:
it was, and it took "The Olde Black Horse Tavern and Motel" — a working tavern —
off the board, because a brand match skips the carve-out.

Result: 2 Bald Birds + 113 hotels off, **199 deals across 38 zones, 2,783
venues**. The only deal correctly lost was Desmond Hotel Malvern.

---

## Findings that cost a session each — do not re-learn these

**The page budget was not the constraint, and we assumed it was for two
sessions (2026-09-01).** The suspicion was that `PAGE_CAP = 4` was starving the
crawl — the log looked damning, with Maggiano's spending its four fetches on
`/banquets/` and `/menus/catering` and Topgolf on a Special Olympics page. So
it was measured: every silent King of Prussia venue was re-fetched with a
**40-page** budget, following every internal candidate link and the whole
sitemap. **Exactly one venue of 38 turned up a "happy hour" on a page the
crawler had not already fetched**, and it was a chain marketing sentence with
no window in it.

> 🔑 **The pages were already in our hands. What was missing was the reading.**
> Three of the four venues reclaimed that day were fixed by reading a page we
> had fetched weeks earlier, differently. Before raising a cap, re-read what
> the cap already brought back.

**A venue can publish its happy hour as DATA, and we were the machine that did
not look.** Pizzeria Vetri states the whole thing — the window *and* three
priced sections — in a `<script type="application/ld+json">` schema.org `Menu`
block on `/menus/`, whose `description` is literally `"Weekdays: 4 PM - 6 PM"`.
The visible page says only the words "Happy Hour", behind a JavaScript tab. We
fetched that page, read it as prose, and filed the venue under
*says-happy-hour-no-window*. Now read by `jsonld_quotes()`.

> 🔑 This is a **W3C-backed standard, not a venue quirk** — the reason to build
> it for one KoP venue despite the "a class holding one venue is not worth
> code" rule. **Look for the machine-readable version before reaching for a
> headless browser.** It is cheaper, it is exact, and it is already downloaded.
>
> 🛑 Only a `Menu` that **names itself** the happy hour is read. A restaurant's
> main `Menu` block is its dinner menu, and publishing that as happy-hour items
> is the worst failure available here: the regular price, presented as a deal.

**The WINDOW belongs to a box, exactly as a price does.** Peppers publishes a
real window and we published nothing, because the page is a two-column row: the
deal sits in `col-sm-8` and `04:00 PM - 06:00 PM` in its sibling `col-sm-4`.
Read down the page as prose those are two useless lines — one with no time, one
with no subject. This is the same fact as `item_beside()`, one field over:
**which lines a page put in ONE box is read off the markup.** Now
`boxed_windows()`.

> 🛑 **The box is the IMMEDIATE parent, not an ancestor within a few levels.**
> The first version used an ancestor test, which made Peppers' whole section one
> box and paired the happy hour with the clock of the **row above** — publishing
> 4–9pm, which belongs to that day's other special. Two cells of one row share a
> parent; two rows do not. That is the entire difference between the right
> window and a plausible wrong one, and it is the day↔special off-by-one this
> corpus has hit before. Joining records that merely *follow* each other invents
> adjacencies.

**🚨 A bare LABEL is not a claim, and the deal count will not tell you.**
`boxed_windows()` shipped and immediately paired a **nav link** with the clock
beside it. Black Powder Tavern's home page carries a bare "Happy Hour" link in a
row of opening hours, so the reader manufactured three windows — lunch 11:30–4,
brunch 11–3 and the real 4–6 — and one of them **outranked the venue's own
sentence**, *"Happy Hour on Monday through Friday from 4:00 p.m. until 6:00
p.m."* A correct Mon–Fri window became **every day of the week, cited to a quote
that says 11:30 to 4.** Amada and The Pullman went the same way.

The box joins a **deal** to its clock, and "Happy Hour" alone is not a deal — it
is a tab, a title, a link. `states_a_deal()` asks what SURVIVES removing the
words: a price, or enough other words to be a sentence rather than a label.

> 🛑 **The deal count never moved.** 203 before, 203 after, with three windows
> quietly wrong inside it. It was found by **diffing every zone's cards against
> the previous commit** — name, window and item count per venue — not by
> watching a total. **A total cannot see a value change.** Do this diff after
> any change to the readers; the loop is in the handoff.

**One failed fetch is not the venue going quiet.** `reached_nothing()` protects
the venue whose whole host is down. It does not protect the commoner shape:
three pages read, one `ConnectionError`, and the quotes that page held silently
gone from the board. Gullifty's lost all five of its items exactly that way —
its `/drink-menu` fetch failed on a recrawl and the rebuild shipped a card with
nothing on it. **The window survived, so no count moved and nothing looked
wrong.** `keep_failed_pages()` now applies the per-venue rule per PAGE: a URL
that errored keeps what we held, and **only a page we actually READ may say a
page has nothing on it.**

**🚨 A chain will serve another town's page at our town's URL, 200 OK.**
`cityworksrestaurant.com/locations/king-of-prussia/happy-hour/` returns a
complete, well-formed happy-hour page that says *"City Works has the best Happy
Hour in **Frisco**"*, canonical `/locations/frisco/happy-hour-menu/`. Reading
the window off it would have published a **Texas schedule under a King of
Prussia bar** — sourced, quoted, and wrong.

> 🛑 **Every gate we have would have passed it.** The fetch was clean, the quote
> is real, the window parses, the validators are about Pennsylvania law and this
> *is* a lawful window. Nothing downstream asks whether the page was about this
> venue. This is the only failure class here that produces a confident wrong
> ANSWER rather than a miss, so it is refused at the crawler: `wrong_location()`
> believes the site's own canonical tag over the URL we asked for.
>
> 🔑 A wrong answer is worse than a hole. A hole is reported by
> `report_holes.py`; a wrong window is invisible until a customer drives there.


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

🛑 **NEVER put regex- or escape-bearing Python through a bash heredoc — even a
quoted one.** This has now cost five sessions. The latest went further than a
failed patch: `\b` was written into `DENIAL_RE` as a literal **backspace byte**
(`\x08`), the file parsed, the module imported, and the regex silently never
matched. It shipped, and only a unit test asserting the *match* caught it.
`assert old in s` on a raw-string source will also fail for the same reason.
**Use the editor tool, or a script file on disk. Not a heredoc.**

---

## 🔑 The binding constraint moved to the WINDOW (2026-09-02)

The item problem is solved well enough to be boring: point the page reader at a
town and it comes back with items. The **card** does not follow, because

> 🛑 **A venue with items and no window gets NO CARD.** The window is the card's
> spine — `Live until ${w.end}` has nothing to render without one — and windows
> belong exclusively to the deterministic extractor.

`extract_deals.py` corpus-wide, 2026-09-02:

```
366  venue had quotes
208    KEPT
154    quote states no schedule      <-- the whole remaining population
  4    REJECTED by the PA validators
```

**154 venues have a happy-hour quote in hand and no schedule in it.** That is
now larger than every other named hole class combined.

### And the windows are in pages we already paid for

The seven KoP-adjacent towns were run end to end (below). Sonnet read 138
verified items across 12 venues, **0 refused** — and the board gained **one
card**. Seven of those twelve have items and no window. The windows were sitting
in the cached page the whole time:

| venue | the window, in `data/pages/` | where it hides |
|---|---|---|
| Blue Bell Inn | 4:30–6:30 PM | happy-hours page, prose |
| il Granaio | 4–6:30 PM (and 2–4:30) | happy-hour **PDF** |
| Autograph Brasserie | 7–9:30 PM | happy-hour **PDF** |
| Bistro on Bridge | to 6:00 PM | homepage |
| StoneRose | 6pm | |

The quote pass produced no schedule-bearing quote from any of them, and three
are inside PDFs. **This is the same defect as "no intelligence over pages",
one field to the left** — a rule engine decided what a schedule looks like, and
these venues did not spell it that way.

> ✅ **DECIDED 2026-09-02, by Paul: YES, the reader may propose a window.**
> The shape approved is the shape built: the model returns a **verbatim span**,
> `check()` asserts the span is literally in the page (and `extract_deals.py`
> asserts it AGAIN before a card is built, so the sidecar is never evidence of
> itself), and **`windows_from()` — the existing parser, unmodified — converts
> it.** *"No meridiem ⇒ refused, never guessed"* is untouched, and the model
> never states a time. `ingest/read_windows_llm.py`, sidecar
> `data/windows_pages_llm.json`, tests in `tests/test_window_reader.py`.

### What it did on the first run — and the two inherited claims it corrected

31 eligible pages (the only pages sent are those of a venue whose quotes state
NO schedule — a venue we already hold a window for is never sent), 6 calls,
**6 verified spans across 5 venues, 3 refused.** `extract_deals.py` went
**208 → 213 kept**, no existing card changed, and the five new cards arrived
carrying the items that were already read and stranded:

| venue | span the venue wrote | card |
|---|---|---|
| il Granaio | `TUESDAY - FRIDAY 4PM - 6:30PM` + `SATURDAY & SUNDAY 2PM - 4:30PM` (**PDF**) | 23 items, 2 windows |
| Bistro on Bridge | `Monday-Friday 4:00-6:00PM` | 26 items |
| Anthony's Coal Fired Pizza | `MON - FRI • 3-6 PM • Dine-In Only` | 26 items |
| The StoneRose | `Monday - Friday 4 - 6pm \| Bar Area Only` | 11 items |
| Garrett Hill Ale House | `Happy Hour Wednesday-Friday / 4pm-7pm` | window only |

🔑 **The three refusals are the pass working, not failing.** Bonefish
(`Happy Hour starts at 3:30pm daily.`) is a start with no end; Cornerstone
(`tues-fri from 3:30-5:30`) has no meridiem; Miller's Ale House states two
clauses across a line break that `clauses()` will not split. In all three the
model pointed at the right sentence and **the deterministic parser declined it**
— which is exactly the division of labour the decision bought.

🛑 **Two claims in the 2026-09-02 handoff were wrong, and reading the pages
corrected them:**

- **Autograph Brasserie is NOT 7–9:30 PM.** That PDF's `6:30-9:30 PM` belongs to
  **GIRLS NIGHT OUT**, and the `5 - 7 PM` to a prix fixe dinner. Its HAPPY HOUR
  section states dishes, prices and **no hours at all**. The model returned
  nothing, and nothing is the correct answer.
- **Blue Bell Inn's 4:30–6:30 is not in any page we hold.** Both cached pages
  contain no time but a phone number. It needs a re-crawl, not a reader.

> 🔑 A window quoted in a handoff is a claim about a page. Check it against
> the cached bytes before building anything on it — two of the five named
> venues did not survive that check.

---

## Scoped runs — `ingest/needy.py`, and why a full corpus is not on the table

Paul, 2026-09-01: *"we don't want a full corpus run. sonnet isn't cheap at a
certain scale. we want to run it on only the entries with missing info, and
ideally in the towns closest to KOP … After those smaller places are scraped
well, we can do a stand-alone job for west chester because it's large."*

🛑 **The "cheapest remaining win" in the previous handoff — an overnight
~900-venue recrawl — was withdrawn on this instruction.** A run names its towns.

**A venue is NEEDY when it has a website AND (no deal at all OR a deal with no
items).** A venue with a window and items is left alone; re-fetching it spends
bandwidth to re-learn what we hold.

```
python ingest/needy.py phoenixville wayne_radnor --show --lids run.lids
python ingest/crawl_sites.py --lids run.lids --recrawl --render
python ingest/read_pages_llm.py --show --rejects
python ingest/read_windows_llm.py --show --rejects   # the WINDOW half
python ingest/extract_deals.py && python ingest/build_bundles.py
bash tests/run.sh && git add -A && git commit && git push
python scratch/card_diff.py          # WHICH cards moved — a total cannot see this
python scratch/live_check.py         # the gate that counts, ~2-3 min after push
```

### The run of 2026-09-02, in full — read this before scoping the next one

96 needy venues: phoenixville 26, wayne_radnor 23, ardmore_bryn_mawr 16,
norristown_bridgeport 11, blue_bell_plymouth_meeting 11, conshohocken 6,
audubon_eagleville 3.

| stage | result |
|---|---|
| crawl `--lids --recrawl --render` | 93 reached, **33 with a deal quote**, 93 pages cached, 1 WebKit render |
| `read_pages_llm.py` (sonnet, batch 5) | **138 verified items, 12 venues, 0 refused**, 12 calls |
| `extract_deals.py` | 208 kept, **154 no schedule** |
| `card_diff.py` | **one card changed** — Sullivan's 20 → 26 items |
| live in WebKit | 43 KoP cards painted, no page errors |

> 🔑 **`ingest/needy.py` re-run after all of that still returns 96.** Items
> without a window do not clear neediness, and that is the finding stated as a
> number: **the reading is done and the towns still have no cards.** Do not
> re-run these seven towns hoping for a different answer — the next move on them
> is the window decision above, not another crawl.

🛑 **West Chester is deliberately untouched.** Paul sequenced it as a stand-alone
job *after* the small towns are good, and they are not good yet.

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
