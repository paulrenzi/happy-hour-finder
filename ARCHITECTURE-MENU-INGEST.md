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
fetch: only a page that came back under 25 lines, and of those only one whose
URL **names an hour** — or, since 2026-09-02, the **seed page of a venue with
no quote yet**. The second shape is the fix from §"THE WHOLE FUNNEL" below: a
shell homepage has no links, so the hour-named URL was never discovered and the
gate could never fire. The rendered seed now feeds `candidate_links()`, which is
where the gain is. `RENDER_CAP = 40` per run still bounds the spend.

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
python ingest/reach_llm.py town phoenixville --spend       # what the web says the town has ($0.13) -> ground truth candidates
python ingest/needy.py phoenixville --show --lids run.lids   # reads BOTH bundle files
python ingest/reach_llm.py links --lids run.lids --show     # a model picks the HH / town page off each site's link inventory
python ingest/crawl_sites.py --lids run.lids --recrawl --render   # --lids keeps EVERY page for the verdict
python ingest/extract_menu_images.py --lids run.lids --show # menus posted as PICTURES (vision + per-image transcript)
python ingest/reach_llm.py verdict --lids run.lids --show   # a model: does a "no happy hour" page state one anyway?
python ingest/read_pages_llm.py --lids run.lids --show --rejects
python ingest/read_windows_llm.py --lids run.lids --show --rejects   # the WINDOW half
python ingest/read_menus_llm.py ask --lids run.lids --show --rejects 40  # THE MODEL READS THE MENU
python ingest/read_menus_llm.py build --show                # re-check every quote against the file on disk
python ingest/extract_deals.py && python ingest/build_venue_base.py && python ingest/build_bundles.py
python ingest/fetch_venue_photos.py --from-board --zone phoenixville --every-venue --spend
                                                           # a photo for EVERY licensee in the town, deals or not (~$0.04 each)
python ingest/build_venue_base.py && python ingest/build_bundles.py
bash tests/run.sh && git add -A && git commit && git push
python scratch/card_diff.py          # WHICH cards moved — a total cannot see this
python ingest/report_coverage.py phoenixville --candidates   # cards / CONFIRMED ground truth; the 90% number
python scratch/live_check.py         # the gate that counts, ~2-3 min after push
# THEN the human minute, now aimed: confirm each --candidates row (open its site, record the
# URL that states the happy hour, set confirmed:true) and look at every NOT HELD name.
```

🛑 **`extract_menu_images.py` took no `--lids` until 2026-09-02** — the recipe's bare `--match`
selected nothing, and Valley Forge Pizza's two `happy_hours_page_*.png` sat in `crawl_hits.json`
unread through a whole "correct" run. Every stage takes the same lids file now.

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

## 🔑 THE WHOLE FUNNEL, MEASURED END TO END (2026-09-02)

Paul asked the only question that matters at this stage: *"if I name an area,
what percentage of the web pages with happy hour listings do we pull in — are we
at that point yet, or do we need more functionality?"* Everything below is
**measured off the data on disk**, not estimated, because the previous answers to
this question were estimates and two of them were wrong.

### The corpus funnel

| stage | all zones | King of Prussia (the most-worked zone) |
|---|---|---|
| PLCB licensees | 2,788 | 49 |
| website on file **and crawled** | 848 | 49 |
| at least one page fetched ok | 731 | 43 |
| a page said "happy hour" | 361 | 22 |
| **card on the board** | **216** | **19** |

> 🔑 **Once a readable page mentions a happy hour, we convert 86% of it in KoP
> (60% corpus-wide).** That half of the pipeline is genuinely solved, and the
> window reader is why. **The gap is everything to the LEFT of that column.**

### 🛑 Two claims I made from brand knowledge, and the pages refused both

Both are struck. Read this before repeating either.

1. ~~"About ten of KoP's 21 no-quote venues plainly run happy hours, so real
   recall is nearer 65%."~~ **RETRACTED.** That was a claim about brands, not
   about pages. When the pages were actually fetched, City Works, Davio's, True
   Food Kitchen, Plaza Azteca and Maggiano's all **read fine** — 75 to 179
   visible lines each. Their location pages simply do not say "happy hour". A
   venue I am confident about is still a venue I have not read.
2. ~~"The dominant cause is enumeration — `PAGE_CAP = 4` starves us of the
   happy-hour page."~~ **RETRACTED.** Measured across a 30-venue sample of the
   no-quote class: **zero** unvisited candidate links were happy-hour-named. The
   ranking in `candidate_links()` already puts an hour-named link first and the
   crawl already fetches it. The links we skip are `menu`, `events`, `about`.

### 🛑 The instrumentation gap that forced a live probe — fix this first

`crawl_hits.json` records a page result as `"ok, 0 quote(s)"`. **That one string
means two completely different things:**

- we read the page in full and it has no happy hour on it, **or**
- the page was a JavaScript shell, we read *nothing*, and found no happy hour
  for the same reason a blindfolded man finds no happy hour.

**The record cannot tell them apart, because the line count is never stored.**
That is why answering Paul's question needed 60 live fetches of pages we had
already fetched. **One field — the visible line count — in each page result
separates the largest hole class in the project without a single new fetch.**
It is the cheapest thing on this list and it should go in before anything else.

### The no-quote class, sized by sampling (30 of 390)

| what it turned out to be | share | what it needs |
|---|---|---|
| genuinely read, no happy hour published anywhere we can reach | ~87% | mostly nothing — see the licence-class note |
| a JavaScript shell we could not read at all (0–15 lines) | **~13%** | the render gate, widened |

A large part of that 87% is **not a bar**. The sample contained Starbucks,
Chipotle, Five Guys, Jamba, Saxbys, GIANT, a catering company and an expo
centre. This is the standing trap restated: **a PLCB licence class is not the
thing it names.** Some meaningful share of the 390 is *correctly* empty, and any
recall percentage that treats all 390 as misses is overstating the hole.

### 🔑 The render gate can never fire on the class that needs it

`render_wanted()` requires `page_is_hh(url)` — the URL must name an hour — **and**
a page under `RENDER_LINE_FLOOR`. But a shell homepage's URL does not name an
hour, and a shell yields no links, so no hour-named URL is ever discovered for
it. **The gate is keyed on the thing the failure destroys.** The ~13% shell
class is therefore structurally unreachable today, and `--render` being on
changes nothing for it: across all 390 no-quote venues, **zero** pages were ever
rendered.

The fix is one condition, not a redesign: a page that comes back under the line
floor is a shell *whatever its URL says*, and the homepage of a venue with no
quote is worth one render. `RENDER_CAP` already bounds the spend.

**Built 2026-09-02.** `render_wanted(url, lines, depth, quoted)` now also fires
for a depth-1 seed page of a venue holding no quote. Not yet run against a town
— the yield number above is still the sampled ~13%, not a measurement.

### The smaller, named causes

- **A cross-domain ordering host is dropped.** True Food Kitchen's menu lives at
  `order.truefoodkitchen.com` — a different registrable domain, so
  `candidate_links()` refuses it by the host test. That test was widened once
  already for sibling hosts on the same domain; ordering platforms are the next
  case, and they are the same shape as the Darden "menu is an API record" finding.
- **The canonical guard is small but has a self-refusal.** Only 2 pages in the
  entire corpus were refused by it, so it is not a coverage problem — but one of
  the two is True Food's KoP page **refusing itself** (`canonical says
  king-of-prussia, not us`). Worth one look, not a project.
- **Fetch failures are 142 pages**, dominated by `robots.txt unreadable (403),
  treated as disallow` (86) and `robots.txt disallows` (56). These stay refused.
  Robots is obeyed here and the earlier override is retracted.

### 🎯 So: are we at the point where naming an area is enough?

**No, and the reason is not the scraper.** For a town that has had a discovery
pass, the reading pipeline is in good shape. For a town that has not, we do not
have the websites at all: North Philly has a website for **7 of 206** licensees,
Center City for 134 of 574. **Website discovery, not extraction, is what decides
what a newly-named town returns.** The first question about any town Paul names
is whether it has had a discovery pass — `ingest/discover_sites.py` — and the
funnel table above is how to answer it in one command.

## 🔑🔑 REACH, PROVEN BY FOUR MISSES — and what "intelligence over a town" has to mean (2026-09-02)

A scoped Phoenixville run had ended with "no card added, both refusals correct".
Paul opened a browser and in one minute found four venues that publish a happy
hour and had no real card: **Revival Pizza Pub, Rivertown Taps, Sly Fox, Sedona
Taphouse.** Every one was a hole in *reach* — a page or a picture the crawl
never put in front of any reader — and not one would have shown in the funnel
table above, because the funnel counts what we fetched, and these were never
fetched. Fixed in `9a1c861`; all four are on the live board.

| venue | where the happy hour was | why we never saw it |
|---|---|---|
| Sly Fox | `/phoenixville` — "Appy Hour", Tue–Fri 3–6 | the link named the town, not an hour, so it matched no `LINK_WORD`; the page never says "happy hour"; the day line **below** the block was a Saturday from the next section |
| Sedona Taphouse | `/locations/phoenixville-pa/` + `HappyHourMenu_PhxWC.pdf` | town link dropped, then displaced by three `nye-special` sitemap URLs; the PDF anchor was 220 chars of card markup and the link regex allowed 120; "$20 Oﬀ" (one ligature glyph) read as a $20 price |
| Rivertown Taps | `Happy-Hour-Specials.png` on `/menu/` | images were only collected on hour-named URLs, and the venue has **no text at all** — hours and items are pixels |
| Revival Pizza Pub | `Revival HH.png` on `/happy-hour-menu` | the image regex wanted `_hh_`/`-hh-` and the URL was `%20HH.png`; worse, the card carried **$6 margaritas** from Margherita Monday because a day-specials quote fed the price pass |

### The architecture that changed

- **A link naming the venue's own town is the venue's page.** `town_re(address)`
  builds a regex from the town in the venue's PLCB address; `candidate_links()`
  ranks a match first and the sitemap top-up (`ours + extra + rest`) can no
  longer displace it. Sly Fox and Sedona are location-page chains; their
  happy hour lives on the location page, never the homepage.
- **An image that names itself the happy hour is the menu, on any page.**
  `HH_IMG_RE` uses a standalone `hh` token after `urllib.parse.unquote`; the
  crawl calls `menu_images(html, url, self_named=not on_hh)` on every page, not
  only hour-named ones.
- **A picture can state the hours.** `extract_menu_images.py` now keeps each
  image's verbatim transcript in `data/menu_image_transcripts.json`;
  `extract_deals.picture_spans()` takes the happy-hour heading line plus the two
  lines under it and runs the **unchanged** `windows_from()` grammar over them.
  Used only when a venue has no text hit at all. The model still writes no
  window itself; it transcribes, the grammar decides.
- **A day line directly above a heading owns it.** `DAY_LINE_RE` + the
  day-above rule in `quotes()`; reading forward only had handed Sly Fox a
  Saturday it does not have.
- **"Appy Hour" is a happy hour** (`DEAL_RE`, `HH_HEADING_RE`).
- **A day-specials page is a different menu.** `extract_prices_llm.vouched()`
  refuses quotes whose URL matches `DAY_SPECIALS_URL_RE`, and
  `read_pages_llm.worth_reading()` refuses the page outright. 🛑 **A wrong item
  is worse than a missing one** — a $6 margarita that is not on at happy hour is
  the kind of thing a reader stops trusting the board over.
- **PDF text is NFKC-normalised** (`pdf_clean`) so ligatures spell out.
- **A menu-card anchor can be 400 chars wide** (was 120).

`build_bundles` merges sidecars in the order pages → `deals_prices_llm.json` →
`deals_menu_images.json` with `setdefault`, so 🛑 **a stale prices entry must be
deleted by hand before image items can show through** (Revival needed this).

### 🛑 The process defect underneath all four

The run's own verdict was *correct refusals*. The funnel table, `needy.py`, the
hole report and the render gate all agreed, because every one of them measures
**what we fetched**, and a page never fetched is invisible to all of them. The
only instrument that caught it was a human with a search box.

> 🔑🔑 **A run that calls a town empty is checked against one human minute before
> it is called correct** — open the top hits for "<town> happy hour" and ask
> whether each has a card. That check is now a stage of every scoped run, and
> the next piece of work is to make the machine do it.

### ✅ Built the same day — `ingest/reach_llm.py`, `ingest/report_coverage.py`, `data/ground_truth/`

Paul, later on 2026-09-02, after finding a fifth miss (Valley Forge Pizza, `/happy-hours/`,
two PNGs): *"the problem is that you're hand reviewing these with fable level intelligence.
we can't do that. we need this to scale, so that when we run through a town's websites, we
get everything in one pass."* So the three model calls below exist now, and the scoped-run
recipe above is the one pass.

| call | what it sees | what it may return | checked in code |
|---|---|---|---|
| `links` | every same-domain anchor on the homepage + the sitemap, "TEXT -> URL", ≤120 lines, venue name + town | ≤3 happy-hour URLs, ≤3 location-page URLs | a URL not in the inventory is dropped (`pick()`); winners are depth-1 seeds in `crawl_sites` |
| `verdict` | the visible text of a saved page the regex called `hh: false` | `states_happy_hour` + ≤8 verbatim lines | a line not literally on the page is dropped (`grounded()`, zero-width chars stripped); kept lines are filed as one ordinary hit, `by: reach_llm`, and `windows_from()` decides |
| `town` | Google Places "happy hour in <town>, PA" for the zone's towns | names + addresses | matched to the base on house number + zip (a PLCB range `208-212` meets `212`), then name; matched rows are **candidates** in ground truth, unmatched in-zip rows are **NOT HELD** |

**Phoenixville, first run through the pass:** 21 needy venues; links picked for 20 (Valley
Forge's `/happy-hours` among them, unprompted); crawl kept 60 pages; verdict judged 29 pages
of 13 venues and said *no happy hour* to all — correctly, those venues do not publish one;
the picture pass read 8 images and produced Valley Forge (14 items, **Mon–Fri 4–6 off
page_1**) and Molly Maguire's (4 items, Mon–Fri 5–7 off `Mollys-Happy-Hour-Website.jpg`).
`report_coverage.py phoenixville` → **5 cards over 5 confirmed = 100%**, 8 candidates
unconfirmed, 5 NOT HELD (Boardroom, Molly Maguire's second licence, Rec Room, Vintner's
Table, Grid Iron — Google lists them, the PLCB base does not).

Two wrong windows the run exposed, both fixed in `extract_deals.main`:
- 🛑 **A clock longer than 4 h is opening hours.** Valley Forge's page says "Happy Hours /
  Mon–Sun 11:00 AM – 10:00 PM"; the validators would have rejected the venue whole, and
  the picture never got a hearing. Refused before the picture is consulted (18 corpus-wide,
  no card lost — `card_diff` showed the two gains only).
- 🛑 **A picture that names the happy hour beats text that does not.** Molly's only text with
  a clock is "Late Night Menu Thursdays 10pm to 11pm"; for one build it shipped as the
  happy hour with the picture's $5 wines under it.
- 🛑 **Transcripts are per image now** (`images: {url: text}`); one-per-venue meant page_2
  (food) overwrote page_1 (hours).

**Left, named:** Sly Fox's **daily specials** (Wed $9 growlers, $12 cheesesteak+pint, Thu $12
burger+pint, Sat $11 mystery pitcher, Sun $2 off Bloody Marys) are on its page and Paul wants
them on the card. SPEC has `daily_special` / `food_combo`; `extract_deals` emits only
`happy_hour`, and the day-specials refusal in the price pass is deliberate. That is a new deal
type, end to end (grammar, validators, card), not a regex.

### 🎯 The goal for the next sessions, in Paul's words (2026-09-02)

*"When we run a scrape over a town, we need to be running intelligence over it
as part of our process, and get to 90% coverage on restaurants that actually
have happy hour menus."*

Two things fall out of that sentence, and they are different projects:

1. **The denominator must exist before the percentage can.** "Restaurants that
   actually have happy hour menus" is not the PLCB list (Starbucks, Chipotle and
   a catering firm are on it) and it is not the crawled list (Sedona was crawled
   and missed). It is a **per-town ground-truth list**, built the way Paul built
   it — web search + a human minute — and kept on disk
   (`data/ground_truth/<zone>.json`: venue, the URL that states the happy hour,
   date checked, who checked). Coverage = cards ÷ that list. Phoenixville has
   4 named entries today; the list has to be built before the number means
   anything.
2. **"Intelligence over the town" is an LLM doing reach, not reading.** The
   reading half is at 86%. What the four misses needed was judgement at three
   places the crawler currently uses regexes:
   - **which link to follow** — give a model the venue's link inventory
     (homepage anchors + sitemap, text and URL, ~100 lines) and ask *"which of
     these is the happy hour page or menu?"* One small call per venue replaces
     `LINK_WORDS`/`town_re` ranking, which is a list of patterns we add one
     miss at a time;
   - **whether a page states a happy hour** — `DEAL_RE` is a regex over
     "happy hour"/"appy hour"; a model reading the fetched text says yes/no
     with the quoted line, so a venue's own vocabulary stops being a miss;
   - **what is not on the site at all** — a per-town search
     ("<town> happy hour", the venue name + "happy hour") whose results are
     compared to the venues and URLs we hold, so a venue with no website on
     file (10 of Phoenixville's 40) or a happy hour published only on a
     third-party page is at least *named* as a hole.

   Cost is the number of calls, not the model size. A town of 30 sites is
   ~30 link-picker calls plus the page reads already being paid for.

**Phoenixville today, off disk:** 40 licensees, 30 with a website, 28 fetched,
13 quoted, **8 cards** by the funnel's count; 21 still `no deal`. The board zone
shows 32 cards because it draws neighbouring zones in. Until the ground-truth
list exists, no one may say what fraction of "the ones that actually have a
happy hour" those 8 are.

## 🚨🔑🔑 THE MODEL DOES NOT READ MENUS — and "5/5" was measured against the finder's own finds (2026-09-02, night)

Paul, closing the session: *"the model needs to read menus. how am i explaining this basic
fact after this much work based on a goal that requires them to be read?"* He is right, and
this section strikes the claim that the reach pass answered the 90% question. It did not.

**What the three reach calls do, exactly, and what they do not:**

| call | reads | decides |
|---|---|---|
| `links` | a link inventory | which URL to fetch |
| `verdict` | a saved page's text | yes/no + verbatim lines, then **`windows_from()` (regex) decides the window** |
| `town` | Google search results | which venues to list as candidates |
| `extract_menu_images` | pixels → transcript | then **`picture_spans` + `windows_from()` (regex) decide** |
| `read_pages_llm` / `extract_prices_llm` | regex-KEPT quotes only | items, from lines a regex chose |

No model ever reads a menu page or picture and returns *the deals on it*. Every window and
every item still comes out of a grammar that handles the phrasings we have met. A venue whose
page says the thing in a form the grammar cannot parse ships nothing, and the pass calls that
"correct". That is the whole "regardless of format" hole, and it is the build.

**Why 5/5 is not a measurement.** The five confirmed Phoenixville rows are the five Paul found
by hand. Each was fixed *for* the scraper before the number was taken. A run scored against
the misses already patched for it reads 100% by construction. The 8 search candidates are
unconfirmed, so the true Phoenixville number is anywhere in 5/13..13/13 and has not been taken.
🛑 **The only coverage number that counts is a town Paul has NOT touched, run blind, then his
one human minute, then the count of what he found that the run did not.** Five misses to date,
five found by a human after the run, zero found by the pass before him.

### The build, next session — in this order, both, nothing else first

1. **A blind town.** Pick a small town nobody has looked at. Run the recipe as written. Paul
   spends one minute on it. Count the misses. That is the baseline the model-reader is
   measured against.
2. **The model reads menus.** A fourth call, `reach_llm.py read` (name it what you like),
   takes a page's visible text **or an image transcript** and returns the deals on it as
   structured rows: `{kind, days, start, end, items:[{label, price}], quote}`. Grounding rule
   is the verdict's: every `quote` must be a literal substring of the source, and the days,
   clock and prices must appear inside that quote. The regex grammar becomes the **validator**
   (PA-law checks, >4h = opening hours, a price is on the quote) and stops being the reader.
   `windows_from()` stays for the validators and for anything the model did not return.
   - `kind` is one of SPEC's three: `happy_hour`, `daily_special`, `food_combo`. **Daily
     specials are happy-hour items and go on the card** (Paul, 2026-09-02: "they are happy
     hour items"). Sly Fox's Wed $9 growlers / $12 cheesesteak+pint, Thu $12 burger+pint, Sat
     $11 mystery pitcher, Sun $2 off Bloody Marys are the acceptance case. The deliberate
     refusal of day-specials pages in `extract_prices_llm.vouched()` and
     `read_pages_llm.worth_reading()` goes; the guard that replaces it is the `kind` field,
     so a Margherita-Monday price never lands under a happy-hour heading.
   - It runs over **every** saved page and every transcript of a scoped venue, not only
     no-hit venues (the verdict's `not v["hits"]` gate is the same defect in miniature).
   - Cost is calls, not model size. A town is ~30 venues × a few pages; batch like the verdict.
3. **Photos for every venue in a town, deals or not.** Paul: "for restaurants with hours not
   published, all of those photos should be present too, for all towns." `fetch_venue_photos.py`
   at ~$0.04/venue; the no-deal population is ~2,570 (~$100). Run it town by town inside the
   recipe, not as one corpus sweep.

### Findings for future debugging, so they are not re-learned

- The recipe's image pass ran with a bare `--match` for weeks; it selected nothing. A step
  that selects nothing exits 0. 🛑 **A recipe step is verified by the count it changed.**
- `build_bundles` merges sidecars with `setdefault`; a stale `deals_prices_llm.json` row hides
  image items. Delete it by hand (Revival).
- `reach_verdicts.json` / `reach_links.json` are keyed by lid with `asked_at`; `--force` re-asks.
- `crawl_sites --lids` keeps every page (`_keep_all`); a zone run keeps only hh-named pages.
  If a page is "missing" from `data/pages/`, that is why.
- `data/ground_truth/<zone>.json`: `confirmed: true` + `url` counts; everything else is listed
  and never counted. Flip `confirmed` only with a URL in hand.
- Wix pages carry zero-width characters inside words; `grounded()` strips `​-‍﻿`.
- `DEAL_RE` still matches "late night menu"; only the picture-wins rule kept Molly's honest.
- Justop's photo: Google returns the apartment block; no fix.


---

## ✅ THE MODEL READS MENUS — built 2026-09-02, and what a blind town cost

`ingest/read_menus_llm.py`. The table in the section above listed five model
calls and every one of them read something a regex had already chosen. This is
the sixth and it reads the document:

| call | reads | decides |
|---|---|---|
| `read_menus_llm ask` | **the whole page, and the whole transcript of a menu posted as a picture** | **the deals on it** — `{kind, days, start, end, items, quote}` |

`extract_deals`'s grammar is still imported. It is now only ever asked to
REFUSE — `HEDGE_RE`, `ONE_OFF_RE`, `MEAL_RE`, `days_in()` as a cross-check,
`_hours()` for the over-4h rule — and `windows_from()` is never asked what a
window is. Landing is a venue file `data/deals_menus.json`, merged by
`build_bundles` above the extractor and below a person.

**Grounding, all of it in code.** The quote is a literal substring of the
document, checked when the answer is written and **re-checked by `build` against
the file on disk** — the sidecar is not evidence of itself. The clock has to be
spelled inside the quote; the days have to be named in it; every item's price
has to sit in its own evidence span; `validate_pa` decides last.

### `kind` is what replaced the day-specials refusal

Paul, 2026-09-02: *"daily specials are a deal type, and they should be picked up
and added. they are happy hour items."* The refusals in
`extract_prices_llm.vouched()` and `read_pages_llm.worth_reading()` were the
reason Sly Fox's card was two items. It now ships its Appy Hour **and** the
Wednesday $9 growlers, the $12 cheesesteak-and-a-pint, the Thursday $12 burger
and pint, the Saturday $11 mystery pitcher and the Sunday $2-off Bloody Marys —
seven deals, each with the venue's own heading on it.

🔑 **A daily special routinely states NO clock of its own.** "Wednesday: $9
Select Growlers" carries a day and a price and no time, because it runs the
whole day the pub is open — and the pub's hours are further up the same page.
So a `daily_special` or `food_combo` may ground its clock in a SECOND span of
the same document (`clock_quote`), and the card records which. A `happy_hour`
may not: one that does not state its own hours is not one we can publish, and a
9-hour "happy hour" is the opening hours by another name.

### 🛑 The guard cost a $50 prime rib — the heading is the venue's own word

The first run read William Penn Inn's dinner PDF and returned three
`daily_special` rows: Tue–Fri 5:00–6:30, Saturday 4:30–5:30, Sunday 3:00–4:00,
ten entrées at $35–$50 under each. **Every one was correctly grounded.** The
clock is on the page, the days are on the page, the prices are on the page, and
it is a recurring time-bounded priced offer. It is still not a thing to put on
this board, because the heading two lines above reads **"WILLIAM PENN INN PRIX
FIXE"**. It is the dinner service, served early.

So the model must return the venue's **own heading** for each deal, checked as a
literal substring like every other span, and `NOT_A_DEAL_RE` refuses a heading
that names a meal service whatever `kind` the model chose. It caught Bridget's
Steakhouse's "Pre-Fixe Dinner Menu" on the very next run. 🔑 **The list is a
BLOCKLIST on purpose** — a whitelist of deal words would refuse "Wing
Wednesday", and refusing is the invisible answer, not the safe one.

### 🛑 Three instruments were wrong the moment a venue could hold two deals

All three had been right for exactly as long as every card carried one deal.

1. **`needy.py` read only `venues-<zone>.json`** — which `build_bundles` fills
   with the venues that have NO deal. So the second half of its own rule, *"or a
   deal carrying no items"*, **had never selected anything**: 76 of the corpus's
   214 deal-bearing venues carry a window and no item and not one of them could
   be reached by a scoped run. It hid Fireside Bar and Grill on the blind town —
   a venue Google names as having a happy hour.
2. **`card_diff` read `deals[:1]`** and called that the card. Sly Fox went from
   one deal to seven and the diff reported it as "2 items → 1". A card is all of
   its deals.
3. **`lib.js` pushed one board row per DEAL.** Sly Fox painted seven cards in a
   row and Sedona two. It is one row per bar now — the deal that answers "can I
   go now?" first — and the venue sheet still lists every one. `render_check`'s
   item gate moved with it: a card paints ONE of a venue's deals, so it can no
   longer name which, and instead asserts that every painted label is one the
   venue ships and that a venue whose deals ALL carry items never paints blank.

🔑 And outranking the extractor **loses its sidecars**: Bistro on Bridge went
26 items → 6 on the first build, the same prices verified against the same page,
dropped because the row carrying them had been outranked. `build_bundles` now
merges the price sidecars in behind a model-read venue's own items, into the
richest `happy_hour` only — one deal per venue, or Sedona's 24 prices landed on
both of its happy-hour blocks and every item painted twice.

### 🎯 The blind town: Ambler / Upper Dublin, 2026-09-02

Chosen because nobody had opened it and none of its zips bleed into a worked
zone. **35 licensees, 13 with a website, 2 cards before, 2 cards after, 0 new
venues.** Baseline in `data/ground_truth/ambler_upper_dublin.json`.

| stage | result |
|---|---|
| `reach_llm town` | 4 searches, 21 candidates matched to a licensee, 8 not held |
| `needy` | 15 (13 before the `needy.py` fix, which added the two card-bearing ones) |
| `reach_llm links` | **7 of 15 could not be fetched at all** — 403, SSLError, ConnectTimeout, ReadTimeout |
| `crawl --lids --recrawl --render` | 15 crawled, **6 with ZERO pages**, 2 with a deal quote |
| `extract_menu_images` | 0 — nobody in this town posts a menu as a picture |
| `reach_llm verdict` | 18 pages, 0 quotes added |
| `read_menus_llm` | 21 documents, **7 deals across 2 venues** — and it is the only pass that got William Penn Inn and Bridget's in front of a reader at all |
| photos `--every-venue` | 27 of 33 fetched, 6 refused by the name guard, 2 have none |

🛑 **The reach half is the whole story of this town.** Six of fifteen venues
returned no page at all, and 14 of the 21 things Google calls a happy hour in
Ambler have no website on file. Every one of those is invisible to a reader,
however well it reads. **The next number that matters is Paul's minute against
this list**, not another pass over the nine pages we did fetch.


## ✅🔑 WILLOW GROVE / HORSHAM — one town, proven end to end (2026-09-02, late)

Paul: *"We aren't doing big scrapes. You've failed at all of them. **Prove it on
a single town.**"* Then, once the photos landed: *"Photos are trivial. Where are
my happy hour menus for the town?"* So the whole recipe was run over exactly one
zone, and the answer is measured, not asserted.

| | before | after |
|---|---|---|
| venues with a website | 9 | **32** |
| venues with a photo | 0 | **34** |
| cards carrying hours | 0 | **11** |
| items on those cards | 0 | **83** |
| board, corpus-wide | 214 | **225** |

Cost: **$1.68** for the photo/website pass, and one scoped `read_menus_llm` run
over 32 venues. Anthony's Coal Fired 24 items, Buona Via 19, Palz Tap House 19,
Miller's Ale House 8, PJ Whelihan's 6, Select Pizza Grill 6, and The Copper
Crow's weekday 4:30–6:30. Verified live in WebKit against the town's own venue
names, 35 cards painted, zero page errors.

🔑 **The photo call already had the websites and was throwing them away.** The
Places Text Search that buys a photo is billed at Pro tier whether or not you
ask for `websiteUri`, and the field mask did not ask. 162 photos bought across
the corpus, 162 websites discarded. Adding one field to the mask is why 9
websites became 32 in this town for no extra money — and website coverage is
the ceiling on everything downstream.

### 🛑🛑 Four silent defects, each refusing real menus while reporting success

The town read as "correct and empty" until The Copper Crow was walked by hand.
All four are now covered by `tests/test_menu_reader.py` (16 offline cases —
`vet()` takes a row and a document, so the entire grounding half tests without
spending a cent).

1. **A literal backspace byte where `\b` was meant.** Inside an `r"..."` regex a
   raw `chr(8)` matches nothing and raises nothing, so the guard it belonged to
   simply **stops existing**. One was mine, in this pass's meridiem check. The
   second **had been shipping in `extract_deals.items_in()`'s label splitter**,
   where `all day\b` has therefore never matched. 🔑 This is what a generated
   edit does when a heredoc or a tool layer eats one backslash. Write patch
   scripts with the Write tool and spell a backslash `chr(92)`; never a
   `<<'PY'` heredoc. The build now **fails on any control byte in any source
   file** — that test is the only thing standing between us and a third one.
2. **`clock_in()` never generated the zero-padded 12-hour form.** A specials
   calendar prints `04:30 PM - 06:30 PM`. The only candidates for 16:30 were
   `16:30` (absent) and `4:30` (refused — the `(?<!\d)` lookbehind sees the
   leading `0`). **Every venue that writes its hours that way was refused.**
3. **A bare hour matched inside a longer time.** `11` hit inside `11:00 am`, and
   the meridiem test then read the `:` as *"no meridiem stated"* and accepted
   it — so an 11am opening time could evidence an 11pm window. The lookahead is
   `(?![\d:])`, not `(?!\d)`.
4. **The specials-calendar page class was refused three ways at once.**

### 🔑 The specials calendar is a page CLASS, and code reads it, not the model

```
Tuesday September 1st
Happy Hour (Bars and High Tops ONLY!) - $5 per birria taco     04:30 PM - 06:30 PM
Wednesday September 2nd
Happy Hour (Bars and High Tops ONLY!) - $5 off all pizzas      04:30 PM - 06:30 PM
```

The happy-hour line **names no day and no clock of its own** — both sit on
adjacent lines — and the dated header makes `ONE_OFF_RE` read the whole thing as
a party. Three refusals, and this is The Copper Crow and Bridget's Steakhouse in
Ambler both.

The fix is deliberately **not** to let the model assert the missing spans:

- `clock_near(quote, start, end, source)` — **code** looks for the clock line
  within ±300 chars of each occurrence of the quote.
- `day_header(quote, source)` — **code** walks **backwards only**, up to 600
  chars, for the nearest weekday named *before* the entry. Backwards because an
  entry belongs to the header above it; a symmetric window would straddle the
  next day's header and hand a Tuesday deal Wednesday's name.
- Both are gated on `repeats(heading, source) >= 3` — a heading printed three
  times is what makes a page a **calendar**. A one-off party is announced once
  and is still refused.
- And a `happy_hour` may only take a clock **adjacent** to it, so the opening
  hours at the top of the page can never become a nine-hour "happy hour".

The card records `clock_quote` and `day_quote` beside the deal quote, so a
reader can see exactly which lines it was assembled from.

### 🛑 Left open, on purpose, and named

- **The name guard refuses apostrophe and spacing variants.** Richies vs
  Richie's, Magerks vs MaGerk's, Na Brasa vs NaBrasa — **4 of the 9 refusals in
  this town**, and the live board currently paints *"Richie's Too"* and
  *"Richies Bar & Grill"* as two venues. Normalising punctuation before the
  match is the fix and it was not done.
- **`scratch/live_check.py` reads only the first 24 hours-unknown cards** and
  never clicks *Show more*, so it can report a venue missing that is on the
  board. It falsely reported Palz.
- **No ground-truth row has ever been confirmed for any town**, so
  `report_coverage` still prints *"0 confirmed rows — no denominator, no
  percentage"*. **Paul's minute is still the missing instrument**, on Ambler
  (`HANDOFF-THE-MINUTE-ON-AMBLER-20260902.md`) or on this town.

---

## 🛑🔑 BONEFISH GRILL WILLOW GROVE — the menu was ONE LINK off the page we already had (2026-09-02)

Paul found it by hand:
`https://bonefishgrill-d8cba7f0a6b8gwd7.a02.azurefd.net/menu/BSH-1_0626.pdf`
— **3:00PM–6:30PM, EVERY. SINGLE. DAY., ~15 items with prices.** A full card,
in the town we had just called proven.

🔑 **We fetched the page that links it.** `data/pages/61425__336b7771523f.json`
is the Willow Grove location page, on disk, from the scoped run. The PDF anchor
is in that HTML. Nothing was unreachable, nothing was blocked — robots allows
both hosts — and no budget ran out. **Five independent gates each dropped it on
their own**, which is why it read as "correctly empty":

1. **`candidate_links()` drops the link as foreign.** The test is
   `registrable(netloc) != host`, and the menu is on a CDN:
   `bonefishgrill-d8cba7f0a6b8gwd7.a02.azurefd.net` registers as `azurefd.net`,
   not `bonefishgrill.com`. **A chain's menu assets do not live on the chain's
   domain.** The sibling-host widening that rescued locations.pjspub.com was
   written for subdomains and stops exactly here — yet the CDN host carries the
   brand's own label in its name, which is the same evidence a subdomain is.
2. **The anchor's label is not the venue's word for the link.** The `<a>` wraps a
   card image and its inner text is *"Let's Go!"*; the title **"Social Hour
   Menu"** sits in the markup **above** the anchor. `candidate_links` reads only
   `<a>...</a>`, so the one word that identified the document was outside the
   window it looks at.
3. **`HH_DOC_RE` does not match the filename.** `BSH-1_0626.pdf` — BSH is
   *Bonefish Social Hour*, and the venue's abbreviation for its own deal is not
   a word we could have listed. The rule "follow a PDF that NAMES ITSELF the
   happy hour" has no purchase on a filename that is a SKU.
4. **The PDF is linked from a page that is not an HH page**, so the other half
   of the queueing rule (`on_hh_page`) is false too. Gates 3 and 4 are the whole
   condition: `if on_hh_page or HH_DOC_RE.search(u)`.
5. **`EVERYDAY_RE` cannot read `EVERY. SINGLE. DAY.`** — `daily|every ?day|all
   week|7 days a week|seven days`. `days_in()` returns the empty set on the
   clock line, so even with the document in hand the days are unnamed.
   (`window_in()` reads `3:00PM – 6:30PM` correctly — the clock half is fine.)

🛑 **And the on-domain page that names the deal carries no hours and no prices.**
`www.bonefishgrill.com/social-hour-menu/irresistible-cocktails` exists,
`url_names_hh()` says True, and it lists item names only. Reaching *it* would
have produced a card with a heading and nothing to publish. **The PDF is the
only document in the world that states this venue's happy hour**, so any fix
that stops short of fetching it is not a fix.

### 🔑 The general shape, which is not about Bonefish

**A chain location page is a link farm to assets on hosts we call foreign,
labelled outside the anchor, named by an internal SKU.** Five gates, each
individually defensible, and the product of them is zero. `report_holes` had
nothing to say because every gate reported success. This is the same class as
the four silent defects above: **a refusal that never prints is indistinguishable
from an absence.**

### Named, sized, not yet built

- **A.** Allow a foreign host for a `.pdf` when that host's netloc contains the
  page's registrable label (`bonefishgrill` in `bonefishgrill-…azurefd.net`).
  Narrow: it opens CDNs the brand named after itself, not the web.
- **B.** Give `candidate_links` the ~200 characters **before** the `<a>` as a
  second label, so a card's title counts. This alone turns gate 3 into a hit,
  because "Social Hour Menu" is in that window and `DEAL_RE` already knows
  `social hour`.
- **C.** `EVERYDAY_RE` must read `every\W*single\W*day`.
- **D.** ❓ **PAUL'S CALL: `DOC_CAP` is 2 and this page links THREE PDFs**
  (brunch, gluten-friendly, social hour). With A+B the social-hour one ranks
  first by label, so 2 is probably enough — but if the label window is noisy the
  budget decides which menu we read, and the wrong two cost the card.

🛑 **None of this ships until it is proven on the next town Paul names**, and
the Bonefish card is the acceptance test: 3:00pm–6:30pm, seven days, items priced.

---

## ✅🔑 WEST CHESTER — one town, and the count question answered (2026-09-02)

Paul picked it and asked two things: are we missing restaurants from our total,
and get pictures for everything.

| | before | after |
|---|---|---|
| venues with a website | 22 | **49** (of 62) |
| venues with a photo | 9 | **44** |
| the needy list | 23 | **42** |
| cards carrying hours | 9 | **13** |

Cost: **$2.07** photos/websites + $0.10 for the town search + one scoped
`read_menus_llm` run. New: **Opa Taverna 33 items**, Lascala's Fire 16, Avalon
Restaurant, Ryan's Pub, Teca-R. Corpus 225 → 230 published windows. Verified
live in WebKit against the town's own venue names, 37 cards painted, zero page
errors.

🔑 **The website lift is the whole run.** 22 → 49 websites took the needy list
23 → 42, and a venue with no website is a venue the crawl cannot read. This is
the Willow Grove lesson holding on a second town: the cheap certain data comes
first, and everything downstream is bounded by it.

### 🛑🛑 "NOT A LICENSEE WE HOLD" was wrong a third of the time

The instrument answering Paul's question was itself the thing to fix. The town
search called **12** venues missing; **four were already ours**:

1. **`house_numbers()` read only the first two parts of a range.** Limoncello's
   licence is `5-7-9 N Walnut St`; Google calls it `9 N Walnut St`. The one
   number the sign uses was the one dropped.
2. **`match_place()` required Google and the PLCB to agree on a ZIP.** The Stone
   Tavern is 19382 to Google and 19380 on its licence — both West Chester.
   Inside one zone that is not evidence of a different bar; the name test is
   still exact and both ZIPs must be the zone's own.
3. Bar Avalon and two others we hold under a different trade name or in a
   neighbouring zone, found by the photo pass and by name.

36/12 → **38 matched, 10 unmatched**, of which two more are ours in an adjacent
zone. **Eight are genuinely absent from the licence base** — The Social, LoCali
Wine Lounge, High Street Caffe, Bier and Loathing, Bottle Room, R Five Wines,
Concordville Bar and Grille, and Victory Brewing Downingtown's taproom. They are
in `data/ground_truth/west_chester.json` under `unmatched`. **Adding a
non-licensee to a licence-derived base is Paul's call, not a session's.**

### 🛑🛑🔑 A chain's events calendar is every town at once

The West Chester card shipped **"Pottstown – Trivia Every Wednesday!"** and
**"Drexel Hill – Quizzo Tuesday"**. Artillery Brewing publishes one events page
for every location it owns, each row prefixed with its town.

🔑 **Both were correctly grounded.** Those words really are on that page, the
quote check passed, the clock and day came off adjacent lines exactly as the
calendar rule intends. **No grounding check can see this** — it is the
`$50 prix fixe` failure again: right evidence, wrong thing.

`another_towns_row()` refuses a row headed with a town the licence base knows
that is not the venue's own. Narrow on purpose — **prefix position only**, so
`Wings - $5` and `Bar Bites: half price` are untouched — and checked in `vet()`
**and again in `build()`**, so rows already written before the guard existed are
dropped rather than shipped once more.

### Checked, and NOT a regression

**Sedona Taphouse left the board.** It is the second active licence at
**44 W Gay St**, where Lascala's Fire now trades; the PLCB still lists both as
Active because status lags a tenancy. One building, one card — `merge_venues`
keyed on (house number, ZIP) is doing what it was written to do, and Sedona
falls back to the hours-unknown list under its own name. Its licence row is
intact.

### Left open, named

- **`scratch/live_check.py` reported Ryan's Pub missing from a board it was
  painted on** — the board carries the curly apostrophe, a typed name carries a
  straight one. Fixed locally; `scratch/` is gitignored, so the fix does not
  ship and the next session will meet it again.
- **`reach_llm links` lost one batch to a `JSONDecodeError`** (5 of 42 venues,
  three of which have unreachable sites). The batch's reply is not saved, so
  there is nothing to look at afterwards — that is the fix, not a retry.
- Three cards ship a window with **0 items** (Avalon, Pietro's Prime, Teca-R).
  Those venues publish hours and no prices. Honest, not broken.
- **No ground-truth row is confirmed for this town either.** `report_coverage`
  still has no denominator. **Paul's minute is still the missing instrument.**

---

## 🛑🔑🔑 THE FUNNEL SAYS THE WALL IS YIELD, NOT REACH (2026-09-02)

Read this before proposing another extraction fix. `python ingest/report_funnel.py`:

```
zone                          lic  site crawl    ok quote  card   card/quote
west_chester                   62    49    49    46    20    13    65%
king_of_prussia                49    49    49    43    22    19    86%
willow_grove_horsham           43    32    32    29    14    11    79%
ALL                          2788   888   888   769   380   236    62%
```

**Two walls, and neither is the one the last several sessions were fixing.**

**Wall 1 - supply.** 888 of 2788 venues have a website at all (32%). Zones with a
discovery pass run 79-100%; zones without run 10-25%. **Bought with money, not
cleverness** (~$2/town of Google Places `websiteUri`). Understood, not interesting.

**Wall 2 - yield.** 769 sites crawl OK and only 380 produce a quote. **Half of
every page we successfully fetch yields nothing.** West Chester: 46 crawled fine,
26 published nothing. Those are not unreachable venues - we got their pages, read
them, and published nothing.

🔑 **Wall 2 is the project, and it does not close one venue at a time.** Every
session so far has fixed a genuine instance of it - a CDN host, a label above an
anchor, `EVERY. SINGLE. DAY.` Each fix was correct and each recovered roughly one
venue. **At one venue per fix this never finishes.** The next architectural move
has to change the class, not the instance.

🛑 **"Add a rendering crawler" is NOT the move -- it exists and West Chester
used it.** `crawl_sites.py --render` launches WebKit; that run **rendered 14
pages** and yield was still 20 of 46. The live question is whether
`render_wanted()`'s gate is too narrow: it fires only under
`RENDER_LINE_FLOOR = 40` lines, only at an hour-named URL or a quoteless
venue's **seed** page, `RENDER_CAP = 40` per run. A homepage returning 60
lines of real chrome that hides its menu behind JS **can never be rendered**.
The floor is not arbitrary -- rendering a fully-read page measured **zero
yield** on King of Prussia -- so moving it needs a measurement, not a guess.

### The yield that passes is thin, in six named classes

`python ingest/report_holes.py` - of 231 published windows, **117 name no item at
all**: `no-price-published` 37, `priced-but-unreadable` 26, `nothing-but-the-hours`
25, `menu-is-a-picture` 11, `chrome-only` 11, `menu-is-a-document` 7.

🛑🔑 **`no-price-published` is mostly OURS, not the venue's silence.** The tool's
own audit note records **24 of 36 had prices in the raw HTML**. The largest
"the venue doesn't publish prices" class is a **retrieval failure reporting itself
as an absence** - the same shape as every silent defect here: *a refusal that never
prints is indistinguishable from an absence.*

Also on the West Chester run, `extract_deals` **rejected 17 quotes as "opening
hours, not a happy hour" against 8 windows kept.** The classifier discards twice
what it keeps, and that ratio has never been sampled.

### 🛑🔑🔑 "IT IS LIVE" MUST BE ONE COMMAND, AND IT IS THIS ONE

```
python tests/live_front_door.py <zone>
```

Root URL, **fresh WebKit context (no service worker, no HTTP cache)**, drive the
zone picker like a person, compare what is **painted** against the **locally built**
bundle. Expected names come from the built file, never a CLI argument - a typed
name carries a straight apostrophe, the board carries a curly one, and that
mismatch once made the old check cry wolf about Ryan's Pub.

🔑 **Every wrong "it's live" came from answering a smaller question**:
`render_check.py` runs the LOCAL page; fetching `data/zone-*.json` proves a FILE
shipped. **Neither proves the board a visitor opens draws the work.** It lives in
`tests/` and not `scratch/` on purpose - the previous instrument was gitignored,
so its own fix never shipped.

Corollary, still open: **a user holding a stale service worker does not have the
fix.** `web/sw.js` records this class twice already. A deploy that a person cannot
see is not a deploy.

---

## ✅🔑🔑 A ROUNDUP *DOES* CARRY AN ADDRESS — the join, and the two things it must refuse (2026-09-02)

`ingest/crawl_roundups.py` opened with a premise written into its own docstring:
*"a roundup carries no address"*, which is why `mentions()` matched venues **by
name only**. That premise is **false for at least one common outlet shape**, and
believing it cost two Doylestown bars that were sitting in a dated article with
real clocks.

BUCKSCO.Today's Doylestown piece carries addresses in **two** places:

- a **card block at the foot** of the article — `37 N Main St, Doylestown, PA
  18901` as a paragraph under the heading `Maxwell's On Main (MOMs)`;
- the **prose opener** — *"Located at 80 W State Street right in the heart of
  downtown, Penn Taproom seats roughly 70 guests..."*.

Neither venue could **ever** have been joined by name, and this is the point:

| the sign over the door | the licence we hold |
|---|---|
| Maxwell's On Main (MOMs) | `37 N MAIN STREET ENTERPRISES LLC` |
| Penn Taproom | `PA GRILL ROOM LLC` |

> 🔑🔑 **The venue whose licence is a shell is exactly the venue a name
> join can never reach — and it is also the one no site was ever found for, so it
> is not in `venue_sites.json` at all.** The address index is therefore built from
> **`venue_base.json`**, which holds every licence, not from the site join.

### How it is wired

`mentions(text, index, addr_index=None)` still matches **on name first**, unchanged.
What is new is that a heading the name index cannot resolve is **kept with its
paragraphs** as an *orphan*, and a **second pass** joins those orphans by the
street address the paragraphs carry.

```
headings -> name index          (unchanged; wins outright)
   |
   +-- unresolved -> orphans[heading] = [paragraphs]
                          |
                          +-- second pass: address_venue(heading, paras, addr_index)
```

Three design points, each of which was forced by the data:

- **It is a SECOND PASS, not a wider window.** The prose section and the card
  block are far apart in the document — there are five other venues between
  Maxwell's paragraph and Maxwell's address. No single-pass lookahead reaches.
- **It is a FALLBACK.** A heading the name index resolves is **never** re-routed
  by an address. Address evidence widens reach; it does not overrule a name.
- **The hit carries the ARTICLE'S HEADING as the display name.** That is the sign
  over the door, which is precisely what a shell-licenced venue is missing. The
  licensee still ships as `plcb_name`.

`address_keys()` reuses `street_core()` from `discover_sites.py`, so `37-39 N Main
St` (the licence) meets `37 N Main St` (the article) **and** `39 N Main St`, the
same range logic the venue lane already needed for `5-7-9 N Walnut St`.

### The two refusals — both found by running it over the whole corpus BEFORE shipping

**1. Two licences at one door.** 44 W Gay St, West Chester is Lascala's Fire *and*
Sedona Taphouse. The address key indexes to a **list**; a list of two refuses. The
same building with two bars must not silently pick one.

**2. 🛑🔑🔑 A DOOR OUTLIVES ITS TENANTS.** This is the important
one, and it only appeared because the join was run over the corpus rather than the
one town it was built for. The first run produced:

| article, year | heading | the door today |
|---|---|---|
| County Lines, 2024 | `Serum Kitchen & Taphouse` | **Station 142** (142 E Market St) |
| County Lines, 2021 | `Split Rail Tavern` | **Bierhaul** (15 N Walnut St) |

Both joins were *correct about the building* and would have shipped a card **under
a name the building stopped using** — the same stale-join shape
`HandCorrectedJoins` already pins for North Italia and Charkoal's.

> 🔑 **A stale join looks identical to a wrong one from inside the data.** The
> discriminator is not the address, it is **who last read the sign**. Where the base
> carries a trade name a **LIVE** source read off that door (`named_by` is `osm` or
> `places`) and it disagrees with the article's heading, the join is refused. A
> **licence-only** name (`named_by == "plcb"`) is the shell the join exists to see
> through, and is **never** held against the heading.

That single rule is what separates "widen reach" from "publish under the wrong
name", and it is why the join can be allowed to be *looser* than a name match
without being *weaker*.

### What it bought

| zone | cards before | after | who arrived |
|---|---|---|---|
| doylestown | 4 | **6** | Penn Taproom, Maxwell's On Main |
| west_chester | 20 | **22** | Jitters (`PTLL LLC`), Side Bar (`S BAR 10 INC`) |

Nothing was lost in either zone. Every arrival is a shell licence.

---

## 🛑🔑🔑 A WRONG WINDOW SHIPPED WHILE ITS OWN QUOTE CONTRADICTED IT (2026-09-02)

`pmify()` in `ingest/extract_roundups.py` exists because a roundup writes clocks
without a meridiem — *"4 to 6"* — and inside an article about happy hours a bare
1–11 range is a PM range. The pattern made the **minutes on the END of the range
optional**. So in:

```
Happy hour runs Monday through Friday from 4:30 to 6:30 PM
```

it matched the `4:30 to 6` **inside** `4:30 to 6:30 PM` and rewrote the sentence to
the nonsense `4:30 pm - 6 pm:30 PM`. Penn Taproom's card shipped **4:30–6:00** off
a quote that plainly says 6:30.

`:` and a digit are now in the forbidden-follow set: a range that **already carries
its own meridiem** needs nothing from this lane, because `windows_from()` reads it
unmodified.

> 🛑🔑🔑 **The card and the evidence it cites disagreed, and nothing in
> the pipeline compares them.** Every validator asks whether a deal is *well formed*
> and whether its quote is *present in the document*. **No check asks whether the
> window we published is the window the quote states.** That is a real hole and it
> is still open — a wrong window is worse than a missing one, and this class is
> invisible to the entire suite.

---

## 🛑🔑 A CUT LABEL IS NOT A WORD — and it happens at BOTH ends (2026-09-02)

The item regexes cap a label at 29 characters. That cap truncates **in the direction
the pattern runs**, and both directions shipped a non-word onto a card in one day:

| regex | direction | quote | what shipped |
|---|---|---|---|
| `HALF_RE` | forwards | `half-price drafts and discounted appetizers` | `drafts and discounted appetiz` |
| `TRAILING_PRICE_RE` | **backwards** | `Housemade Buffalo Cauliflower Bites $6` | `ade Buffalo Cauliflower Bites` |

Neither was caught by the existing prose guard, which refuses a label of more than
four words or one that reads as a clause — both of these are four words and neither
is a clause.

- Forwards: cut at the conjunction, keeping the first noun. The price is on the
  first noun, and it is the fallback the priced path already applied.
- Backwards: anchor on `\b`, so the cut lands on a **word boundary**.

> 🔑 **Short by a whole WORD is a miss. Short by three letters is a wrong thing
> on a card.** Prefer the miss.

The guard that actually sees this class is board-wide, not unit-level:
`test_no_shipped_item_label_starts_mid_word` walks **every `zone-*.json` on the
board** and asserts no item label begins mid-word inside its own quote. A per-regex
test would have passed both defects, because each regex was doing exactly what it
was written to do.

---

## 🛑🔑🔑 A GUARD ON ONE LINK OF A CHAIN IS NOT A GUARD ON THE CHAIN (2026-09-02)

A website discovered by a Places pass must walk **three** files before
`ingest/needy.py` — the selection instrument for every scoped run — can see it:

```
data/venue_sites.json  ->  data/venue_base.json  ->  web/data/zone-*.json
      (discovery)            (build_venue_base)        (build_bundles)
```

`needy()` reads the **built bundles**. On 2026-09-02, Doylestown skipped the middle
step and the selector named **5** venues where there were **33**. A guard was
written the same day — and it compared **only the first pair**.

The next town, **media**, then did the other half of the same damage: the base *was*
rebuilt, the bundles were **not**, the guard stayed **silent**, and `needy` named
**9** where there were **28**.

> 🛑🔑🔑 **A guard that watches one link of a chain is not a guard on
> the chain — it is a guard on the link that failed LAST TIME.** `STALE_CHAIN` in
> `ingest/needy.py` now names every link as `(newer, older, fix)` and warns on any
> of them.

This matters more than a count: `needy.py` writes `run.lids`, which is the scope
of every model pass that follows. **A silently short selection is money not spent
and a town not read**, and it looks exactly like a town that had nothing to do.

---

## 🛑🔑 DROPPING A JOIN IN ONE OF TWO READERS IS NOT DROPPING IT (2026-09-02)

`THE FROSTED MUG`'s licence is **527 E Baltimore Pike**, Media. Google Places
answered with the **ACME Markets at 527 E Baltimore Ave** — two real and different
Media streets that share a house number, with names that agree on nothing. The row
shipped a bar's licence under a supermarket's name, website and photo.

It was hand-dropped into `HAND_DROPPED` — **and the drop did not take.**

`discover_places.merge_sites()` consults `HAND_DROPPED` and keeps the rejected join
out of `venue_sites.json`, the crawl frontier. But **`build_venue_base.py` reads
`data/places_venues.json` DIRECTLY**, so the base kept taking the supermarket's
name, website, photo and coordinate regardless.

> 🔑 **Two files read `places_venues.json`. A drop applied in one of them is not
> a drop.** Both loops in `build_venue_base.py` now go through a single
> `place_for(lid)`.

🛑 And they **must** both go through it. `premises_key()` reads the Places name,
so blanking the record in one loop and not the other builds **two different keys for
one building** — the sibling lookup then dies with a `KeyError`, which is how this
was caught. A partial fix here is a crash, not a miss; be grateful, because the
alternative is silence.

---

## 📖 THE ROUNDUP OUTLET LIST IS REGION-SHAPED — and the Delco half is now proven (2026-09-02)

The `.Today` network publishes one title per county, and they are the outlets that
actually carry dated happy-hour roundups with days, clocks and addresses:

| county | outlet | proven |
|---|---|---|
| Chester | `vista.today`, `countylinesmagazine.com`, Main Line Today | yes |
| Montgomery | `montco.today` | — |
| Bucks | `bucksco.today` | yes (Doylestown) |
| **Delaware** | **`delco.today`** | **yes (Media)** |

🔑 The search that works is `"<town>" happy hour` with `allowed_domains` set to
that list. A bare web search returns aggregator spam.

### 🎯 THE NEXT BUILD: a roundup that names the venue MID-SENTENCE

Four DELCO.today articles are in `data/roundup_sources.json` for `media`. All four
crawl, all four date cleanly, and all four match **zero** venues.

🛑 **That is a finding, not an empty town.** Read by hand, the pages say:

- *"**Azie** in Media has a happy hour on weekdays from **4 to 6 PM**"* — and
  `Azie Media` (lid 58431) is in our base.
- *"**Off the Rail**, also in Media, has **$3 domestic beers** during happy hours
  weeknights, **4 to 6 PM**"*

Both are real, both carry a clock, neither reaches the board. The cause is the
**document shape**: these articles are prose, not a list, and `mentions()` requires
a **heading**. Worse, the DELCO.today template emits roughly **100 chrome lines that
pass `is_heading()`** — `Commerce`, `Community`, `Search`, `About` — so the heading
queue fills with navigation that eats the real paragraphs.

The build is two halves:

1. **Ignore the site chrome.** A heading appearing on *every* article from one
   outlet is navigation, not a venue. The four crawled pages make this cheap to
   detect: the junk repeats, the venues do not.
2. **Match a venue named mid-sentence**, under the containment rule that already
   exists. 🛑 `Sedona it is.` must still not be Sedona. The safe shape is narrow:
   the venue name and a happy-hour clause in the **same sentence**, matched on the
   full multi-word name core, **never** a single word.

**Acceptance test: Azie and Off the Rail on the Media board, 4–6 PM weekdays.**
The source rows are left in place deliberately — they cost nothing, they date
cleanly, and they are the evidence.

---

## 🛑 A RENAME IS A SILENT DROP, AND A DISCOVERY PASS RENAMES IN BULK (2026-09-02)

The Media discovery pass changed **16** names in `venue_base.json` in one run — every
one a PLCB licensee giving way to the trade name Google reads off that same door
(`Sligo Tap` → `Sligo Irish Pub`, `Difabios Market & Tap` → `DiFabio's Market &
Tap`). All 16 were improvements. **The suite cannot tell.**

> 🔑 **After any run that touches naming — a discovery pass included — diff
> `venue_base.json` against the last commit and read the name changes.** The tests
> only assert a name does not END in a legal suffix, so a name that is *shortened*,
> *swapped* or *replaced by a neighbour's* passes green.

Two of the 16 changed **street**, and those are the ones to check by hand every time:

| lid | licence address | Places answered | verdict |
|---|---|---|---|
| 96258 | `117-121 South Ave` | `117 Veterans Sq` | ✅ same building, names agree |
| 69935 | `211 W State St` | `211 W State St` | ✅ same door, address-only join |
| 95653 | `527 E Baltimore **Pike**` | `527 E Baltimore **Ave**` | 🛑 **dropped** |

---

## 🔑 GITHUB PAGES LAGS A PUSH — one NOT LIVE is a deploy in flight (2026-09-02)

`python tests/live_front_door.py <zone>` is still the only command that may say a
zone is live. Both zones shipped this session **failed it on the first attempt and
passed on the second**, roughly a minute later, with the venue count climbing in
between (`named live: 4 of 6` → `6 of 6`).

> 🛑 A single `NOT LIVE` immediately after a push is a **deploy that has not
> landed**, not a broken build. Re-run before believing it. 🛑 And the inverse still
> holds: never call a zone live without running this, however obviously correct the
> build looks.

---

## 🛑🛑🔑🔑 NEVER WRITE A BACKSLASH ESCAPE THROUGH A BASH HEREDOC (2026-09-02)

Patching `ingest/extract_deals.py` through `cat > patch.py <<'EOF'` put a **literal
backspace byte (0x08)** into the file where `\b` was typed — in the regex *and* in
the comment above it. Quoting the heredoc delimiter did **not** prevent it. The file
still parsed, the patcher reported success, and the regex silently did not do what
it said.

This repo's git history already records the same class: *"four silent defects incl.
two literal backspace bytes"* (2026-09-01).

> 🔑 **Write patch scripts with a file-writing tool, never a heredoc, whenever the
> content contains a backslash.** If a heredoc is unavoidable, build the escape from
> `chr(92)`. Then check before believing it:
>
> ```sh
> python -c "print([hex(ord(c)) for c in open(p,encoding='utf-8').read() if ord(c)<9])"
> ```

🛑 A corrupted escape produces code that **runs and is wrong**, which is worse
than a syntax error, because a syntax error stops you.


## Standing rules

- **One venue at a time, finished on the live site before the next**, and Paul
  picks the next one. Since 2026-09-01 the unit is increasingly the **class**.
- Open with one plain-English sentence: no jargon, no paths, no numbers.
- `bash tests/run.sh` runs everything. A web page is verified by **running** it.
- This repo has **its own `.env`**. It must never read `shopify-analytics/.env`.
- Crossing a state line changes the law, not just the data. `RULES["DE"]` is
  deliberately empty; it needs a named authority and Paul's sign-off, never
  inference from PA.
- **A zone is live only when `python tests/live_front_door.py <zone>` says so** —
  and Pages lags a push by ~1 minute, so re-run once before believing a failure.
- **Diff `data/venue_base.json` against the last commit after any run that touches
  naming.** The suite does not see a rename.
- **A run that finds nothing gets checked against one human minute** before it is
  reported as an empty town. Four DELCO.today articles matching zero venues was a
  document-shape defect, not an absence of happy hours.
- **Never write a backslash escape through a bash heredoc.** It lands a literal
  control byte, the patch reports success, and the code runs and is wrong.
