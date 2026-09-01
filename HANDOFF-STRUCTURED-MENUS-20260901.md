# Handoff — the menu already said what the item was, and we asked a word list instead

**Written 2026-09-01. HEAD `b1e1662` on `master`, pushed, Pages run `33553176544`
green, live board verified in WebKit at 0 pageerrors.** Continues
`HANDOFF-ENRICHMENT-HOLES-20260901.md`.

**Board: 341 → 357 items across 98 venues.** Suite **64 pass / 0 fail**, 8/8 deals
pass the PA validators.

---

## 🛑 START THE SESSION LIKE THIS

**Open with ONE plain-English sentence — no jargon, no file paths, no numbers —
saying what we are trying to achieve, addressed to Paul.** Then get to work.

---

## The session in one line

Paul asked *"why do we have a nouns list — happy hour is understood by a separate
menu or a separate section of a menu, underneath the title of happy hour."* He was
right, and the fix was architectural rather than a patch.

## The finding worth carrying forward

**A word list is for prose. Using it on structured data can only lose items.**

`NOUNS` / `category_of()` in `extract_deals.py` exists because on a free-text page a
`$8` next to some words could be a deal, a gift card or a corkage fee, and the
vocabulary is the *only* evidence available. That is a real guard and it stays.

But Darden's menu API **states** the fact — `configs.isBeverageItem`, on every
product inside a category slugged `happy-hour`. Re-deriving that from a whitelist
can never be more accurate than the source, only less: it was silently deleting six
Seasons 52 flatbreads because nobody had typed "flatbread" into the list.

**So the crawler now carries the category the source gave**, as a `[cat:x]` prefix
on the quote, and `strip_category_marker()` reads it before the extractor would
think to guess. Food never touches the word list again. The marker is validated
against the board's fixed eight categories so a source cannot invent one.

**A drink still needs its TYPE and no field carries it** — `isBeverageItem: true`
does not say draft vs wine vs cocktail, and the board has no generic "drink". So
`darden_category()` walks: **section heading → dish name → grape varietals →
refuse.** It refuses rather than guesses, because a wine on the board as a cocktail
is worse than a wine left off. The varietal list is what recovered Seasons 52's
reds — the heading is the single ambiguous word `RED`, but `PINOT NOIR` and `MALBEC`
are not, and varietals are a *closed* real-world vocabulary in a way food nouns can
never be.

Architecture writeup is now in [`README.md`](README.md) → *"Reading a menu: a prose
page and a structured source are not the same problem"*.

## What changed

| File | Change |
|---|---|
| `ingest/crawl_sites.py` | `darden_category()`, `darden_drink_category()`, `VARIETALS`; each quote emitted with a `[cat:x]` prefix |
| `ingest/extract_deals.py` | `CATEGORIES`, `CAT_MARKER`, `strip_category_marker()`; `section_items()` prefers the marker, falls back to `category_of()`. **`NOUNS` deliberately untouched.** |
| `ingest/extract_deals.py` | label cap 40 → 64 chars in `SECTION_ITEM_RE` and `SECTION_OFF_RE` |

## Results, all proven at the live URL

- **Seasons 52 12 → 19** — six flatbreads and three reds recovered
- **Eddie V's 8 → 17** — its whole HH-only TEASERS section; the six full-price
  dinner appetizers ($36 crab cake, $24 calamari…) are **still correctly refused**
  by the `elsewhere` not-a-deal gate. I checked each against the live dinner menu
  rather than assuming the gate held.
- **Yard House 20, unregressed**

## Two traps this session set off, for the next one

**1. Heredoc backslash collapsing cost most of the session.** Patching via
`bash <<'PY'` collapsed a double-backslash-b to a single one inside a *non-raw*
Python string, writing **byte 0x08 (backspace)** into `crawl_sites.py` in four
places. Word boundaries silently became a control character, every drink heading
returned `None`, and all drinks vanished. Three repair attempts *reported success
and changed nothing*, because the replacement string was itself collapsing to 0x08
— a no-op replace. **Diagnose with `cat -A`; build the replacement from raw byte
values** (`bytes([0x5c, 0x62])`) so no backslash literal is ever in the heredoc.
For prose files, prefer the Write tool over a heredoc entirely.

**2. A 40-char cap was deleting a valid item with no error anywhere.** Same silent-
drop class as the `®`, the accents, the curly quotes and the missing comma. When
an item is missing and nothing logs, look for a filter, not a crash.

---

## 🎯 NEXT SESSION — why the scraper could not read this page

**<https://www.northitalia.com/locations/king-of-prussia-pa/?menu=happy-hour>**

**Start here, it is already half-solved.** North Italia is **not** a discovery miss.
It is crawled (`lid 92272`), it is **live on the board right now**, and its window is
correct:

```
north-italia-king-of-prussia — happy_hour, Mon–Fri 16:00–18:00, items: []
quote: "Happy Hour / Mon - Fri / 4pm - 6pm"
```

So the schedule was read fine and **only the priced items are missing.** The crawl
hits for that exact URL contain the menu *tab labels*
(`Lunch Dinner Brunch Dessert Kids Happy Hour…`) and one stray `$25 Lunch Fixe` —
i.e. we are reading the page chrome and not the menu body. That is the signature of
a **JS-rendered menu**, the same shape as Yard House and the Darden chains.

Suggested order, cheapest first — and this repo's own lesson is **look for a JSON
endpoint before reaching for a headless browser**:

1. Watch the network tab / guess the menu API. North Italia is a **Fox Restaurant
   Concepts** brand (Cheesecake Factory group); the `?menu=happy-hour` query string
   strongly suggests the tab is client-side over a JSON payload already fetched.
   One endpoint plus one header answered plain `urllib` for Darden.
2. If there is an endpoint, this is an **adapter**, not a parser change — and
   check whether it covers the other FRC brands the way one Darden adapter covered
   eight chains. **Fix the class, not the venue.**
3. Only if there is genuinely no endpoint, consider Playwright.
4. Whatever the source, **carry its stated category through as `[cat:x]`** rather
   than re-deriving it. That is the whole lesson above.

**Do not hand-enter any value off that page.** Paul's standing instruction is find
out why the scraper missed it and prove the fix on a small pass.

## Method Paul expects

- **One venue at a time**, finished on the live site before starting the next, and
  **he picks the next one.**
- Pointed probes, not long suites.
- **Finish on the live URL in a browser** — an intermediate file, a green aggregate
  and an HTTP 200 are each blind. Show the **rendered card**, not a JSON blob.
- Run all five gates or the fix moves no data:
  `crawl_sites.py → extract_deals.py → build_bundles.py → push → Pages`.
  Scoped recrawl: `python ingest/crawl_sites.py --lids <file> --recrawl`.

## Still open, unchanged — Paul's calls, do not decide these

1. **The open-vocabulary `NOUNS` question for genuinely prose-only pages.** The
   structured half is now solved; prose is not, and adding words is not a fix.
2. **Cloudflare Worker deploy.** `worker/validate_pa.js` and `worker/admin_page.js`
   hold committed `price_max` changes that are **not live**. Token is located and
   proven (`CLOUDFLARE_API_TOKEN` in umbrella-arcades' `.env` — 🛑 **this repo must
   never read `shopify-analytics/.env`**). Watch for a stale `wrangler login`
   silently beating the token. Only Paul's word is missing.
3. **The 6-item display cap** and **Wilmington DE** (`RULES["DE"]` deliberately
   empty — needs a named authority and sign-off, never inferred from PA).
4. `$1.00 off` hole in `extract_prices_llm.verify()` → wrong `pints $1.00` on
   `black-horse-tavern-phoenixville`.
5. Sullivan's publishes a window with zero items — **same shape as North Italia**,
   may fall out of the same fix.
6. **No tests** cover `heading_prices`, `item_label`, `section_items`,
   `SECTION_OFF_RE`, `darden_off_pct`, `darden_menu_quotes`, `darden_category`,
   `strip_category_marker`, or `price_max`.
