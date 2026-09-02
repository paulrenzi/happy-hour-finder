# Handoff — King of Prussia to the brim, and what "every menu" actually costs

**Date:** 2026-09-01 (evening)
**Repo:** `C:\Users\paulm\happy-hour-finder`
**Branch:** `master`, pushed. Live board verified in a real browser.
**Read first:** `ARCHITECTURE-MENU-INGEST.md` — the new blocks are
"What King of Prussia turned out to be, once every class was worked" and the
four entries at the top of "Findings that cost a session each."

---

## Paul's standard, restated

> "I want every single happy hour menu pulled in if it exists on a website.
> There is no middle ground."

**Is that happening yet? No — but for a reason worth reading, because it is not
the reason we assumed for two sessions.**

---

## 🔑 The one thing to carry forward: the crawl budget was never the constraint

The crawler fetches 4 pages per venue and the logs looked damning — Maggiano's
spent its budget on `/banquets/` and `/menus/catering`, Topgolf on a Special
Olympics page. Obvious conclusion: we are starving the crawl.

**It was measured instead.** `scratch/probe_silent.py` re-fetched every silent
King of Prussia venue at a **40-page** budget, following every internal
candidate link and the entire sitemap:

> **Exactly 1 venue of 38** turned up a "happy hour" on a page the crawler had
> not already fetched — and it was a chain marketing sentence with no window in
> it (Chili's `/specials`).

**The pages were already in our hands. What was missing was the reading.** Three
of the four venues reclaimed today were fixed by reading a page we had fetched
weeks earlier, *differently*.

🛑 **Do not raise `PAGE_CAP` on the strength of a log that looks wasteful.** Run
the unbounded probe on a sample and count what NEW thing it finds first.

---

## What shipped today (3 commits, all pushed)

`4864e6a` — three readers, 313 tests, all five gates green.

### 1. `jsonld_quotes()` — the venue published it as DATA and we didn't look

Pizzeria Vetri states its entire happy hour in a schema.org block on `/menus/`:

```json
{"@type": "Menu", "name": "Happy Hour", "description": "Weekdays: 4 PM - 6 PM",
 "hasMenuSection": [{"name": "$10 Select Neapolitan Pizzas"}, {"name": "$7 Spritzes"}]}
```

The **visible** page says only the words "Happy Hour", behind a JavaScript tab.
We fetched that page, read it as prose, and filed the venue under
*says-happy-hour-no-window*. Its quotes went 2 → 16.

🔑 **This is a W3C standard, not a venue quirk** — that is why it was built for
one KoP venue despite the "a class holding one venue isn't worth code" rule.
**Look for the machine-readable version before reaching for a headless
browser.** It is cheaper, exact, and already downloaded.

🛑 Only a `Menu` that **names itself** the happy hour is read. A restaurant's
main `Menu` block is its dinner menu; shipping that as happy-hour items is the
regular price presented as a deal.

### 2. `boxed_windows()` — the WINDOW belongs to a box, exactly as a price does

Peppers publishes a real window and we published nothing. The page is a
two-column row: the deal in `col-sm-8`, `04:00 PM - 06:00 PM` in its sibling
`col-sm-4`. Read as prose those are two useless lines — one with no time, one
with no subject. Same fact as `item_beside()`, one field over.

🛑 **The box is the IMMEDIATE parent, not an ancestor.** The first version used
an ancestor test, which made Peppers' whole section one box and paired the happy
hour with the **row above's** 4–9pm — that day's *other* special. Two cells of
one row share a parent; two rows do not. This is the day↔special off-by-one this
corpus has hit before.

### 3. 🚨 `wrong_location()` — a chain serves another town's page at our URL

`cityworksrestaurant.com/locations/king-of-prussia/happy-hour/` returns a
complete, well-formed happy-hour page that reads **"City Works has the best
Happy Hour in Frisco"**, canonical `/locations/frisco/happy-hour-menu/`.

🛑 **Every gate we have would have passed it.** Clean fetch, real quote, the
window parses, and it is lawful in PA. Nothing downstream asked whether the page
was about *this venue*. We would have published a **Texas schedule under a King
of Prussia bar** — sourced, quoted and wrong.

🔑 **This is the only failure class here that yields a confident WRONG ANSWER
rather than a miss.** A hole is reported by `report_holes.py`; a wrong window is
invisible until a customer drives there. Refused at the crawler now, by
believing the site's own `rel=canonical` over the URL we asked for.

---

## Where King of Prussia actually stands

**16 → 18 venues on the board.** 201 → 203 overall. Verified in WebKit at
`https://paulrenzi.github.io/happy-hour-finder/` — bartaco *Starts 3pm*,
Cheesecake *4pm*, Pizzeria Vetri *4pm* (2 items), Peppers *4pm* (4 items).

The 34 still silent, **every class worked**:

| what they are | n |
|---|---|
| **genuinely do not publish one** — read in full, re-checked at 40 pages | 21 |
| **we cannot fetch the page at all** — robots.txt, 403, timeout | 6 |
| **says happy hour, window unread** — the real remaining work | 6 |
| venue answered: it has none | 1 |

Of the 21, eight were classed `page-is-a-shell` and budgeted as the headless
tier. **All eight were rendered in WebKit; not one mentions a happy hour.** True
Food Kitchen goes 0 → 193 lines and says nothing; Eataly renders 396 lines and
says nothing. **The headless tier returns zero for King of Prussia.** The rest
are a supermarket, a department store, a cinema, and chains whose location pages
carry no hours.

> 🛑 That is the **third** time a class was sized on a suspicion about its CAUSE
> and counted as a pile of work — after the hotel licences and the "no-price"
> venues. `page-is-a-shell` describes a page; it does not diagnose one.

### 🔑 The honest answer to "is every menu being pulled in?"

**"Every menu that exists on a website" and "a full King of Prussia board" are
not the same target**, and KoP is the proof. Most of what is still missing there
is missing from the **venue's own website**. Wegmans, GIANT, Neiman Marcus and
Regal are on the board because they hold a liquor licence, not because they have
a happy hour.

**Closing the rest means going somewhere other than the venue's website** — and
that is a product decision, not a scraper fix. **It is Paul's call.** The
options, in rough order of yield:

1. **Google Places / Business Profile posts** — chains push happy hour there and
   nowhere else. We already hold a Places key and `venue_base.json`.
2. **Instagram / Facebook** — where Screwballs and the small independents post.
3. **Aggregators** — the thing the site is competing with; sourcing from them is
   a positioning question, not just a technical one.
4. **Call them.** 6 venues in KoP would be closed by four phone calls.

---

## Next actions, in order

1. **⏳ PAUL'S CALL — the four options above.** Nothing more can be squeezed out
   of venue websites in King of Prussia. Do not start a new scraper tier
   without an answer here.
2. **⏳ PAUL'S CALL — Bonefish's start-only window.** The page says *"Happy Hour
   starts at 3:30pm daily"* — a start with no end. `whenText()` renders "Starts
   3pm" only as a phase of a window that still HAS an end, and
   `` `Live until ${hit.w.end}` `` needs one. Publishing start-only requires
   deciding what the card says once it is open.
3. **The three neighbour towns are mid-recrawl** (Phoenixville, Ardmore/Bryn
   Mawr, Wayne/Radnor) to see whether the JSON-LD and boxed-window readers
   generalize. **It had not finished when this handoff was written — re-run it
   and rebuild:**
   ```
   for z in phoenixville ardmore_bryn_mawr wayne_radnor; do
     python ingest/crawl_sites.py --zone $z --recrawl
   done
   python ingest/extract_deals.py && python ingest/build_bundles.py
   bash tests/run.sh && git add -A && git commit && git push
   python scratch/live_check.py       # the gate that counts
   ```
   **This is the cheapest remaining win and it is already half-paid-for.**
4. **A full-corpus `--recrawl`** would apply all three readers to the other 34
   zones. ~900 venues at 2s/page ≈ several hours. Worth it, but run it
   overnight, and land the neighbour towns first so the yield is known.
5. Carried, still owed: should an all-day special read "Mondays, all day" rather
   than midnight-to-midnight? Does a daily special get its own card or a line on
   the venue's card?

---

## Tools left behind (in `scratch/`, gitignored)

- `probe_silent.py <zone>` — re-fetch every silent venue at a 40-page budget and
  report which say "happy hour" on a page the crawl never got. **Run this before
  ever raising a cap.**
- `probe_jsonld.py [zone]` — count how many silent venues publish schema.org
  data, and whether any of it names a happy hour.
- `live_check.py` — open the LIVE site in WebKit, pick King of Prussia, and
  print every painted card with its window and item count. This is the gate that
  counts; an intermediate file and a green aggregate are both blind.
