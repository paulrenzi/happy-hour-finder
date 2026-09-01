# Handoff — five ways a page went missing, and the Delaware door is now locked

**Written 2026-09-01. HEAD `325cbd2` on `master`, pushed, CI green, live board
verified in WebKit.** Continues `HANDOFF-PRICES-COST-20260901.md`.

**The board went 169 → 173 venues with a window, 93 → 95 priced, 267 → 284 items** —
and that number is *net of removing 17 wrong prices that were live*. Suite green at
**260 Python + JS fail 0**, 174 cards painted.

---

## 🛑 START THE SESSION LIKE THIS

**Open with ONE plain-English sentence — no jargon, no file paths — saying what we
are trying to achieve, addressed to Paul.** Then get to work.

---

## What this session was

Paul sent three live happy-hour pages as evidence that "our enrichment process still
has some glaring holes", and said explicitly: **do not inject the data — find out why
the scraper missed it and prove the fix on a small pass.** That is what happened. No
value from those three pages was ever hand-entered.

Three pages turned out to be **three different mechanisms**, and looking for the
common cause would have been wasted time.

---

## The five holes, all upstream of the model

| # | Page | Root cause | Where |
|---|---|---|---|
| 1 | Paladar | The section **closed on the venue's own subheading** — its menu subdivides at a heading reading `DRINKS`, and `SUBDIVISION_RE` spelled its nouns **singular**. 5 of 6 prices sat one line outside the section. | `crawl_sites.py` |
| 2 | Sullivan's | The section **closed on its own hours line**, which the page marks up as a heading. A heading that only says *when* is still the same section. | `crawl_sites.py` |
| 3 | (corpus-wide) | **Price-first lines were never crawled.** Last session added an end-anchored `TRAILING_PRICE_RE` downstream, but the crawler's own `MENU_ITEM_RE` is end-anchored too, so `$4.50 Draft Beer` never reached it. Added `LEADING_ITEM_RE`. | `crawl_sites.py` |
| 4 | Yard House | **There was no page to fix** — a Next.js shell behind Akamai Bot Manager, location-gated. Playwright got 20 characters. | new adapter |
| 5 | 13 venues, **live and wrong** | **`$X off` was published as a price.** Lansdale Tavern shipped `off draft beer $1.00`. | `extract_deals.py` + `extract_prices_llm.py` |

### On (1) and (2) — the general rule

Containment is keyed on **the page's own headings**: a section opens at a happy-hour
heading and closes at the next heading naming something else. Both bugs were the
close rule firing on a heading that was **not a new subject**. 🔑 *When two branches
of one rule disagree about plurals, that is a bug, not a safety margin.*

### On (4) — fix the class, not the venue

Yard House publishes its hours as **data**: `https://www.<host>/api/restaurants/<num>`
with one header `X-Source-Channel: WEB`, happy hour being the `hoursInfo` entries whose
**`hourCode` is `"HH"`**. Plain `urllib`, no browser, no session. The same shape serves
the whole Darden group — `DARDEN_HOSTS` covers Yard House, Seasons 52, Eddie V's, The
Capital Grille, Olive Garden, Cheddar's, Bahama Breeze, LongHorn. **Four King of
Prussia venues that had all been silent came back from one adapter.**

🛑 **Check whether the site's own client is calling a JSON endpoint you can call too,
before reaching for a headless browser.**

### On (5) — and the worst finding of the session

The bare-price regex read `$1 off draft beer` as the item `off draft beer` at `$1.00`.
**17 items across 13 venues were live and wrong.** Closed in **both** paths: an `OFF_RE`
guard in `extract_deals.items_in`, and a semantic check in `extract_prices_llm.verify()`.
The existing "the digits must appear literally in the venue's own text" check **cannot**
catch this, because the digits *are* there. 🔑 **Presence of the number is not evidence
it is a price.**

🛑🔑🔑 **And the fix shipped while the wrong prices stayed live.** `verify()` runs when
an item is first read, and `build_bundles.py` trusts `data/deals_prices_llm.json`
*precisely because* everything in it was checked once. Black Horse Tavern's
`$1 off pints during Happy Hour` was still published as `pints $1.00` by a build running
entirely correct code — the sidecar predated the guard.
**A gate that runs only at write time cannot fix what is already through it.**

New: **`python ingest/extract_prices_llm.py --reverify`** re-runs `verify()` over the
sidecar with **no model calls**. Two things it had to learn the hard way:

- 🛑 **The sidecar does not store `evidence`** (a card has no use for it), so an item on
  file cannot simply be re-judged — there is nothing to judge. `evidence_candidates()`
  reconstructs the venue lines carrying both the label and the number and lets `verify()`
  rule on each. *A derived field you drop at write time is a re-check you cannot perform later.*
- 🛑 **`crawl_sites.py` writes `crawl_hits.json` INCREMENTALLY, inside its loop.** Running
  `--reverify` against a half-written hits file dropped **all 137 items**. It now always
  leaves the previous sidecar at `.bak`, and **you must not run it while a crawl is in flight.**
- 🛑 **It keeps what it cannot re-judge.** A first attempt dropped **15 live items across
  10 venues** because `50% off` is written *"half price"* and carries no `50` anywhere for
  the reconstruction to find. **A failed reconstruction is not a verdict.** It now keeps
  those and reports them separately. On the real sidecar it drops exactly the two it should:
  Wissahickon's `drafts $1.00` and `wine $3.00`.

---

## 🚪 Delaware — the door is locked, the law is not written

Paul chose **"validator first, then crawl."** Done:

- `ingest/validate_pa.py` now carries a **`RULES` dict keyed by state**, plus `state_of()`
  (reads the two-letter state off the venue address) and `rules_for()`.
- `ingest/build_bundles.py` — **the single door onto the board** — calls them and **rejects
  every deal from a state with no ruleset**, naming the state in the reject line.

🛑 **`RULES["DE"]` is deliberately absent, and that is the point.** The gate fails closed,
so no Wilmington venue can publish until someone fills it in. **Filling it in is a research
task with a named authority and Paul's sign-off — never an inference from PA's numbers.**
A comment in the file says so.

🔑 The general shape: *when a rule is really one jurisdiction's rule, key it by jurisdiction
and refuse the unknown key.* Do not let the default quietly become everyone's law.

### What Wilmington still needs, in order

1. **DE liquor law**, from the Division of Alcohol and Tobacco Enforcement: the banned-claims
   list, the per-day and per-week hour caps, any cutoff time, any food-combo rule. Into
   `validate_pa.RULES["DE"]` with `authority` naming the statute. **Paul signs this off.**
2. **DE licence data** to replace the PLCB seed. `seed_plcb.py` is 100% Pennsylvania and
   `counties_in_scope` is five PA counties; there is not one DE row in the pipeline.
3. Only then: `discover_sites` → `crawl_sites` → the rest, unchanged.

---

## ⏳ Still open — `NOUNS`, and it is Paul's call, not a patch

The whitelist in `extract_deals.py` drops **301 of 629 (48%) correctly-paired priced
labels**. 🛑 **But it cannot be closed by adding words: 195 distinct labels are missed and
140 of them appear exactly once** — "pommes frites", "negroni", "prime rib egg rolls".
**This is a whitelist against an open vocabulary.**

The model sidecar is the designed escape hatch for exactly this and handled Sullivan's
cleanly. `build_bundles.py` consults it **only** where the free pass found nothing, so the
shape is already right. The decision — widen it, drop it and lean on `verify()`, or accept
the model cost — is Paul's.

Also flagged, not started: a **`discount_usd`** field, so "$1 off drafts" can be *published
as a discount* rather than discarded. Touches `validate_pa` (py + js), `lib.js` sort key,
`admin_page.js`, `extract_photo_deals.py`, `review_photos.py`.

---

## ⚠️ Two traps that cost time this session

- 🛑 **A bash heredoc eats one level of backslash.** `r"^off\b"` landed on disk as `^off`
  plus a literal backspace and the guard silently never fired. Same for three `STATE_RE`
  classes and a test fixture. **Detect with `cat -A`; write patterns via `B = chr(92)`.**
- 🛑 **`all()` over an empty generator is `True`.** The first OFF guard in `verify()` would
  have refused every item whose match came from the digit-only fallback. Materialise the
  hits and guard `if hits and all(...)`.

Also noticed: **`data/crawl_hits.json` can go stale against `data/venue_sites.json`** —
Yard House's crawl record was bound to **Shake Shack's** website. It self-healed on recrawl,
but a hit record silently describing a different venue is a class of defect nothing detects.

---

## House rules (unchanged, and they keep earning their place)

- 🛑 **A web page is verified by RUNNING it**, never by an HTTP 200. Assert cards painted and
  **zero `pageerror`**, in WebKit.
- 🛑 **Sample the output against the real pages before publishing.** The green suite did not
  catch the 35 wrong prices last session, nor the 17 `off` prices this one. Sampling did.
- 🛑 **Fixtures must carry the real pages' nesting.** A flat fixture makes every line a sibling
  and hides the whole mechanism.
- 🛑 This repo has **its own `.env`**. Never read `shopify-analytics/.env` for it.
- 🛑 **Unpriced is the right answer to a question we cannot answer.** Refusing beats guessing.

## Files changed

- `ingest/crawl_sites.py` — `SUBDIVISION_RE` plurals, `TIME_CONTEXT_RE` exemption in
  `hh_sections()`, `LEADING_ITEM_RE`, the Darden adapter (`darden_ref`/`darden_quotes`/`darden_lines`)
- `ingest/extract_deals.py` — `OFF_RE`
- `ingest/extract_prices_llm.py` — the OFF check in `verify()`, `evidence_candidates()`, `--reverify`
- `ingest/validate_pa.py` — `RULES`, `state_of()`, `rules_for()`
- `ingest/build_bundles.py` — rejects a venue whose state has no ruleset
- `tests/test_ingest.py` — 7 new classes
