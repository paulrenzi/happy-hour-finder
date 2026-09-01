# Plan — get every listed menu (2026-09-01)

**Status: PROPOSED. Nothing here is built. Paul picks the approach.**
Companion to `HANDOFF-EVERY-MENU-20260901.md` and `ARCHITECTURE-MENU-INGEST.md`.

The census that backs this plan is read-only and reproducible: it fetched each
of the 107 hole venues' crawled pages with a browser user-agent and looked at
the raw bytes. Nothing in the repo was changed.

---

## 1. What the 107 are actually made of

107 windows, **100 distinct sites**. Five chains account for 20 rows, so the
work is smaller than the count: P.J. Whelihan's alone is **10 rows** on two
domains (`pjspub.com`, `locations.pjspub.com`); Dandan 3, Amada 3, Bowlero,
Dave & Buster's, Hard Rock, Chickie's & Pete's, Bar Hygge, The Post, Well
Crafted 2 each.

What the raw bytes say, browser UA, no JavaScript run:

| fact | venues |
|---|---|
| "happy hour" text present in the HTML we can fetch | 106 / 107 |
| a `$` price somewhere in that HTML | 85 / 107 |
| "happy hour" followed by a `$` price within 400 characters | **49 / 107** |
| a PDF link whose filename says happy hour / HH / drinks | ~13 |
| no `$` anywhere in the raw bytes (drawn in the browser, or none published) | 22 |
| refuses our crawler's UA but serves a browser | **0** (Brickside 403s everyone) |
| on Darden's API or FRC markup, unrecognised | **0** |

So the five classes in the architecture doc are wrong in one specific way:
**`no-price-published` (36) is mostly misnamed.** 24 of those 36 have prices in
the HTML, and 12 have them right under the happy-hour heading (Osteria, Pearl &
Mary, Prohibition Taproom, The Continental, Royal Boucherie, Chickie's ×2, The
Stables, The Trestle Inn ...). The honest reclassification:

| true class | est. | what it is |
|---|---|---|
| **A. menu is in the HTML we already fetch, and we drop it** | **49 confirmed, up to ~70** | offline parser work |
| B. menu is a PDF the page links to | ~13 | follow the link, read the text layer |
| C. menu is drawn in the browser or served by an API | ~15 | headless tier or a platform API |
| D. menu is an image / scanned PDF | unknown, est. 5–10 | the LLM pass, Paul's dollar call |
| E. venue genuinely publishes no priced menu | est. 10–15 | **out of scope, named as such** |

Class A failure modes, all seen in the census snippets:

- `$ 7` — a space between `$` and the number (Squarespace and BentoBox print
  it this way; Pearl & Mary, Osteria, DBG, Prohibition, Royal Boucherie).
- `$1 off draft beer`, `$2 off specialty cocktails`, `$1.00 off pints` — the
  discount dialect (Lansdale Tavern, W Tavern, SPTR, Black Horse, Interstate).
- `-$8 Nachos, Tupelo Dippers, Jumbo Pretzels` — dash-led, price owning a list
  (Hard Rock ×2).
- `$25` heading owning the items beneath it (Sullivan's; `heading_prices` exists).
- The HH menu inline with the other menus on one page, hidden behind a tab in
  the *same* HTML (Mia Ragazza, Jasper's, 9 Prime, Cedar Point, Southern Cross).
- Day-of-week specials mixed into the HH block (Perky Cafe, Revival, Al Pastor).

Two premises from the handoff did not survive the census:

- **UA blocking is not a class.** Every site that serves a browser served our
  crawler UA too, this run. Sullivan's answered 200 to both.
- **Platform fingerprinting moves ~0 of the 107.** No unrecognised Darden or
  FRC brand is among them. It is still the right fix for the *next* zone, but
  it is not step one for this pile. The Toast links (25 venues) are gift-card
  and ordering pages, not menus.

The publishing platforms across the 107, for when adapters are worth it:
WordPress 24 · Squarespace 19 · Next.js 15 (PJ's ×10) · Wix 12 · BentoBox 9 ·
Untappd embed 18 (beer lists, not HH).

---

## 2. Three approaches — pick one

### Approach 1 — the deterministic ladder (recommended)

Work the classes cheapest first, each step gated by `report_holes.py`.

1. **Read the happy-hour SECTION, not the page.** Find the HH heading in the
   fetched HTML (`hh_sections` already does), then read *every* priced line
   inside it with one tolerant money grammar: `$ 7`, `$5.5`, `$1 off X`,
   `-$8 X, Y, Z`, `$25` heading owning items. Discount lines become `off`
   items, not dropped. This is class A. **Expected: 107 → ~55.**
   First proof venue: Lansdale Tavern (every dialect on one page) or Sullivan's.
2. **Follow the PDF the page links to.** Trigger on a link whose filename or
   anchor says happy hour. `pdf_text()` exists in the crawler. Text-layer PDFs
   read for free; image PDFs fall to step 5. **Expected: ~55 → ~42.**
3. **Headless tier, gated.** Playwright only for venues whose raw bytes hold
   no `$` at all *and* name a happy-hour page. Playwright is already a test
   dependency. **Expected: ~42 → ~30.**
4. **Fingerprint the platform** for the Darden and FRC adapters so the next
   zone reads right the first time. Moves ~0 today; cheap; do it after 1–3.
5. **LLM batch pass over what remains**: image menus, scanned PDFs, and any
   class A stragglers. Cost model in `HANDOFF-PRICES-COST-20260901.md`;
   batch is the lever. **This step has a dollar figure. Paul's call.**
6. **Name the tail.** A venue with no priced menu anywhere gets a durable
   `no-menu-published` verdict, reviewed by a person, and leaves the hole
   count. The scoreboard reports it separately, never as a miss.

Residual after 1–4: roughly 25–30 windows, split between step 5 and step 6.

### Approach 2 — LLM-first

Cut the HH section of every one of the 107 pages (and linked PDFs) and send
them to the model in one batch. Fastest to a number, covers every dialect at
once, and the harness has already been measured. Cost is per-venue, recurring
on every recrawl, and it puts an inference between the source and the board
for venues whose HTML states the price plainly. Deterministic step 1 first
still makes this pass smaller and cheaper.

### Approach 3 — platform adapters first

Write Squarespace, WordPress, Wix and BentoBox adapters that read menu markup
structurally, the way FRC does. Most precise per venue, ~64 of the 107 sit on
those four. Most code, four adapters before the first number moves, and each
platform has several menu plugins, so "WordPress" is not one shape.

---

## 3. How we know it worked

- `report_holes.py` is the scoreboard, run after each step. It gets the five
  true classes above so the report says *where the menu is*, not just that we
  missed it. Class E is reported below the line, not counted against us.
- Each step ends on the **live URL in a browser** for its proof venue, all
  five gates. An intermediate file, a green aggregate and a 200 are blind.
- The not-a-deal gate stays: a price inside the HH section is a deal only if
  it beats the same dish elsewhere on that menu.

---

## 4. Out of scope, by name

- Venues that publish a schedule and no priced menu anywhere (class E).
- Untappd beer boards: tap lists, not happy-hour pricing.
- Toast ordering pages: gift cards and online ordering, not the HH menu.
- The still-open items in the handoff: NOUNS, the Worker deploy, the 6-item
  cap, Wilmington DE, the missing tests.

---

## Census artefacts

`scratchpad/census.py` and `census.csv` (session scratchpad, not the repo)
hold the per-venue fingerprint: platform, HTTP codes under both UAs, whether
the HH text and a price are in the raw bytes, PDF and image counts. Rerunnable
in about two minutes; fetches, never writes.
