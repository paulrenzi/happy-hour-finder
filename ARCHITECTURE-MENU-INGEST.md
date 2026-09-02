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
python ingest/needy.py phoenixville --show --lids run.lids
python ingest/reach_llm.py links --lids run.lids --show     # a model picks the HH / town page off each site's link inventory
python ingest/crawl_sites.py --lids run.lids --recrawl --render   # --lids keeps EVERY page for the verdict
python ingest/extract_menu_images.py --lids run.lids --show # menus posted as PICTURES (vision + per-image transcript)
python ingest/reach_llm.py verdict --lids run.lids --show   # a model: does a "no happy hour" page state one anyway?
python ingest/read_pages_llm.py --lids run.lids --show --rejects
python ingest/read_windows_llm.py --lids run.lids --show --rejects   # the WINDOW half
python ingest/extract_deals.py && python ingest/build_venue_base.py && python ingest/build_bundles.py
python ingest/fetch_venue_photos.py --from-board --spend    # a storefront photo for every new card (~$0.04 each)
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

## Standing rules

- **One venue at a time, finished on the live site before the next**, and Paul
  picks the next one. Since 2026-09-01 the unit is increasingly the **class**.
- Open with one plain-English sentence: no jargon, no paths, no numbers.
- `bash tests/run.sh` runs everything. A web page is verified by **running** it.
- This repo has **its own `.env`**. It must never read `shopify-analytics/.env`.
- Crossing a state line changes the law, not just the data. `RULES["DE"]` is
  deliberately empty; it needs a named authority and Paul's sign-off, never
  inference from PA.
