# Handoff — Happy Hour Finder, 2026-09-01 evening

## 🛑 START THE NEXT SESSION WITH ONE PLAIN-ENGLISH SENTENCE

Before any tool call, write **one sentence, no jargon, naming the goal of the session** —
what a person visiting the board should be able to see that they cannot see today.
Not "re-run the extract pipeline". Something like: *"Get Yard House's happy-hour menu
onto the board so someone in King of Prussia can read it."* If you cannot write that
sentence, you do not yet know what you are doing.

## The challenge Paul set for next session

**https://www.yardhouse.com/happy-hour** — he wants to see it work end to end,
on the live site, with him looking at it. Do not start it before writing the sentence above.

---

## What actually happened this session (read this before you trust yourself)

Paul's words: *"you aren't checking your work and this is frustrating... i don't want
theoretical fixes, i want data on the front end that I can see."* He was right, and the
reason is worth more than the fix.

**Yard House and Paladar were correct in the local data the whole time.** The code worked.
I reported success three separate ways and every one of them was a check of something
that was not the thing Paul looks at:

1. I checked `data/deals_extracted.json` — an intermediate file, four steps from a browser.
2. I checked the built bundle **with the wrong key** — I read `venue["items"]`, which does
   not exist. Items live at `venue["deals"][N]["items"]`. My probe printed `items: 0` for
   both venues and I read that as the failure it was not.
3. I ran the test suite, which was green, and quoted *"the board actually paints: 174 cards"*
   as if it meant the menus were there. It did not. See below.

And underneath all three: **I never pushed.** I said "not committed or pushed, needs your
word" and then reported the board as fixed in the same message. Those cannot both be true.

### 🔑 THE ONLY CHECK THAT COUNTS IS THE LIVE URL IN A BROWSER

There are **five** gates between editing a `.py` file and Paul seeing a change. Every one
of them has silently held a "finished" fix:

```
edit ingest/*.py
  └─► crawl_sites.py       ──► data/crawl_hits.json
        └─► extract_deals.py   ──► data/deals_extracted.json
              └─► build_bundles.py ──► web/data/zone-*.json + web/sw.js
                    └─► git commit && git push
                          └─► GitHub Pages Action ──► the live site
```

The stages are **file-to-file**. A code change alters no data until the stages re-run, and
alters no site until it is pushed AND the Action finishes. Nothing warns you.

- Re-run scoped to one venue: `python ingest/crawl_sites.py --lids <file> --recrawl`,
  then `extract_deals.py`, then `build_bundles.py`. All three. Every time.
- The Pages deploy is normally ~37s; **this one took 4m26s**. Do not conclude "it didn't
  deploy" from one poll. `gh run list` / `gh run watch <id>` is the answer.
- Verify with `python tests/render_check.py` locally, then load the **live URL**
  `https://paulrenzi.github.io/happy-hour-finder/` in Playwright/WebKit and assert the
  named venue's card has `ul.items li` children. A 200 on the JSON is not a rendered card.

### 🔑 A TEST THAT COUNTS CARDS IS BLIND TO AN EMPTY CARD

`tests/render_check.py` asserted zones, feed rows, card count, no duplicates — and was
**green on a board where the two venues in question showed nothing at all**. A venue with
an empty menu paints a card exactly like a venue with six prices.

Fixed this session. It now reads every `web/data/zone-*.json`, collects every venue the
build gives items to, and asserts **each one painted them** — plus that the first label on
the card is that venue's own. It found a real defect in its own first run (see below).

> The general lesson, again: **assert the specific thing, not a healthy-looking aggregate.**
> "174 cards" is an aggregate. "Yard House shows BONELESS WINGS" is the thing.

### 🔑 THREE CHICKIE'S & PETE'S ARE THREE BARS

The new check first failed with *"Chickie's & Pete's ships items and painted an empty card"*.
That was **the test's bug, not the site's**: I keyed venues by name, and there are three
Chickie's locations (Malvern has 2 items, Northeast Philly and South Philly have none), so
one bar answered for another's menu. Keyed on **name + town** now. Any per-venue lookup in
this corpus needs the town; the names are not unique.

---

## What is live right now (verified in WebKit against the live URL, 0 page errors)

Commit **`5e1c084`**, Pages run `33547934048`, deploy succeeded.
`https://paulrenzi.github.io/happy-hour-finder/` — 173 cards, kicker "173 venues · 26 live now".

```
CARD: Yard House                    CARD: PALADAR LATIN KITCHEN & RUM BAR
  50% off FOUR CHEESE SPINACH DIP     $4.50      Draft Beer
  50% off CHICKEN LETTUCE WRAPS       $6.50      Sangrias
  50% off FRIED CALAMARI              $6.50      Mojitos & Margaritas
  50% off MIGUEL'S QUESO DIP          $7.50-7.75 Traditional Guacamole
  50% off HAND-BATTERED CHICKEN...    $7.50-7.75 Street Tacos (2)
  50% off BONELESS WINGS              $7.50-7.75 Paladar Sliders (2)
```

Board: **96 venues with items, 295 items** (was 95 / 284).
Test suite: `bash tests/run.sh` → **pass 64, fail 0**, all render checks ok.

---

## Architecture added this session

### Darden chains — the page is a shell, the menu is an API

`yardhouse.com/happy-hour` is **2.7KB of JavaScript loader**. There is nothing on it for a
crawler to read. This is not a crawler weakness to tune; it is a class of site that must be
fetched differently. Found the route by walking the Next.js chunk map.

- Hours: `https://www.{host}/api/restaurants/{num}`
- Menu:  `https://www.{host}/api/menu?restaurantNum={num}`
- Both need header **`X-Source-Channel: WEB`**. Plain `urllib` is enough — no headless browser.
- The venue's `{num}` is in its own website URL (Yard House KOP = `8371`).
- 🔑 **Check for a JSON endpoint BEFORE reaching for Playwright.**

**One adapter covers eight chains**: Yard House, Olive Garden, LongHorn, Bahama Breeze,
Seasons 52, Eddie V's, Capital Grille, Cheddar's. Only Yard House is in the corpus today;
the rest come free when they appear. Code: `darden_off_pct()` / `darden_menu_quotes()` in
`ingest/crawl_sites.py`, and `SECTION_OFF_RE` in `ingest/extract_deals.py`.

### 🛑 THE API'S PRICE IS THE FULL PRICE — THE DEAL IS ONLY IN THE HEADING

The menu API gives every happy-hour dish a `price`, and **that number is the regular menu
price**. The discount exists nowhere except the section heading: `HH 1/2 OFF SELECT APPS`.

Publishing the number sitting right there would have put **$14.99 on the board for a $7.50
spinach dip** — the same defect as the `$X off` items that shipped wrong before, except the
wrong number looks completely legitimate. **We publish `discount_pct: 50`, never the price.**
A section whose heading names no discount we can read is **skipped, not guessed at**.

> 🔑 A field named `price` is not a promise about *which* price. When a source gives you a
> number and a deal separately, the number is the one you must not trust.

---

## Open, in priority order

1. **🛑 The 6-item cap is the biggest live constraint — Paul's call.**
   `items_from_hits()` ends `return out[:6]`; `extract_prices_llm.MAX_ITEMS = 6`.
   The cut is **quote order, not importance**. Paladar reads 11 items correctly and shows 6.
   Yard House reads 14 and shows 6 — which is why its card is all appetizers and **none of
   the six half-off pizzas**. The card already folds behind a "+N more" toggle, so the
   display can hold more than six; the cap is upstream of the fold and throws them away.
   Options: raise the cap, or cap *per category* so drinks and food both survive.
2. **⚠️ The Cloudflare Worker is NOT deployed.** `worker/validate_pa.js` and
   `worker/admin_page.js` changed (the `price_max` field) and are committed but live is
   still older code. `wrangler deploy` needs `CLOUDFLARE_API_TOKEN`, which is **not in this
   repo's `.env`** — and this repo must never read `shopify-analytics/.env`. Paul's call.
   Impact is limited to the photo-submission approval path; the board is unaffected.
   *(Trap on record: a stale `wrangler login` silently beats `CLOUDFLARE_API_TOKEN`.)*
3. **Wilmington, DE** — `validate_pa.RULES["DE"]` is built and **deliberately empty**, so
   `build_bundles` refuses DE venues rather than applying PA law to them. Filling it needs
   DE liquor law from a **named authority** (Division of Alcohol and Tobacco Enforcement)
   and **Paul's sign-off**. 🛑 Never infer it from PA. Then DE licence data to replace the
   PLCB seed.
4. **`NOUNS` open-vocabulary decision — Paul's call.** The whitelist drops 48% (301/629) of
   correctly-paired prices, and **140 of 195 misses are singletons**, so adding words cannot
   fix it. It is whitelist-vs-open-vocabulary, a design decision, not a bug.
5. **`$1.00 off` hole** in `extract_prices_llm.verify()` — its OFF guard catches `$1 off`
   but not `$1.00 off`, so `black-horse-tavern-phoenixville` publishes a wrong `pints $1.00`.
6. **Sullivan's** publishes a window with zero items, unexplained.
7. **No tests** cover the new mechanisms: `heading_prices`, `item_label`, `section_items`,
   `SECTION_OFF_RE`, `darden_off_pct`, `darden_menu_quotes`, `price_max` in both validators.

## How Paul wants this worked

> *"we are going to fix it with pointed, quick scrape tests, not large tests that take 20
> minutes to complete... modify the scrape method until it does work, and gets all of the
> correct information on a single pass. then we can move onto another example"*

One venue at a time. Scope the crawl with `--lids` + `--recrawl`. **Finish each one on the
live site before moving to the next** — and show him the rendered card, not a JSON blob.
