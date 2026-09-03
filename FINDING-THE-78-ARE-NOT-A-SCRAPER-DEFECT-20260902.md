# The 78 are not a scraper defect — measured, 2026-09-02

**This is a sizing result, not a change. Nothing was built. Read §1 and stop if
that is all you need.**

The previous handoff
(`HANDOFF-START-HERE-20260902-THE-SCRAPER-IS-THE-JOB.md`) named the binding
number as **80 venues that publish an hour and gave us nothing to read**, and
named four untried routes to fix it, with the standing instruction: *size a
candidate fix by probing the population before you build it.*

That was done. Four read-only probes, over the whole population, ~1,100 live
fetches, no writes into `data/`. **Every route sizes in single digits, and the
four together recover at most 9 of 78 — of which 2 are QR-code popups, so
realistically 7.**

---

## 1. The number

Population re-derived today: **78** (the 80 minus the two the linked-image rule
already took).

| route | recovers | note |
|---|---:|---|
| **A. the hop** — follow an HTML menu link off the happy-hour page | **6** | only **2** land on a page that names a happy hour; the other 4 are the catering / lunch / dinner menu |
| **B. the shell** — seed page returns almost no visible text | **7** | candidates only; a render was not run |
| **C. the refusals** — the handoff's "403 six" | **0** | **every one of the 78 answered.** That bucket no longer reproduces |
| **D. pixels** — a menu board `menu_images()` cannot see | **6** | 2 are QR-code popups (`popupqr.jpg`, `popup-mobile-qr.jpg`); ~2 are plausibly menus |
| **E. the dollar-less price** (new, found today) | **2** | see §3 — a real class, a small one |
| **union of A(safe) + D + E** | **9** | **7** after the QR popups |

Publishing the 4 dinner menus route A also found would take it to 13 and would
put wrong items on the board. A wrong item is worse than a miss.

## 2. Why — what the 78 actually publish

The 78 were bucketed on what `crawl_hits.json` **captured**. Captured is not
present. So the pages were asked directly (`scratchpad/size_the_seed.py`):

| the page we already fetch | venues |
|---|---:|
| carries no dollar price **anywhere on it** | **44** |
| ...and none on any page we followed from it either | **40** |
| carries a price, but with **no happy-hour section** to contain it | 23 |
| carries a price **inside** a happy-hour section, unpublished | **2** |

**41 of 78 had every candidate link already crawled.** The crawler is not
failing to go deep enough. It went there and there was nothing.

Coyote Crossing is the shape of the majority. `/happy-hour`, 81 visible lines,
zero prices, and the page says in words: *"Discounted signature margaritas …
Happy hour bites, tacos, guacamole, quesadillas, and more."* That is the venue
publishing an hour and declining to publish a price. No scraper reaches it
because there is nothing there.

🔑 **So the 112-item gap is not ~71% a reach problem. It is ~90% "the venue did
not publish a price."** That is a fact about the world, not a defect in this
repo, and 70 commits have been spent against it as though it were the latter.

## 3. The one real class found — a price need not have a dollar sign

The Quoin Wilmington publishes a complete happy-hour menu at
`thequoinhotel.com/restaurant/happyhour`, and it reads to this pipeline as a
venue with no prices:

```
Happy Hour: Tuesday - Friday, 4 PM - 6 PM
Peroni, Italian Pale Lager 4.7%
. . . 6
Pinot Grigio & Pinot Noir
. . . 8
Downtown Daiquiri
rum, lime, caribbean coconut
. . . 10
```

Every price rule in the repo is anchored on `$`: `BARE_PRICE_RE` is
`^\$\s?\d{1,3}`, `MENU_ITEM_RE` ends `\$\s?\d`, and every priced alternative in
`DEAL_RE` starts `\$`. A dot-leader menu — ordinary restaurant typography — is
invisible to all of them.

**It is worth 2 venues of 78** (`scratchpad/size_bare_prices.py`). It is a
genuine reader defect and it is still single digits. It is written down here so
the next session does not rediscover it and mistake it for the lever.

## 4. What this means for the goal

"Every listed menu" cannot be met from these 78 websites, because ~40 of them
publish no menu. The honest moves, in order:

1. **Fix the denominator.** The board reports 112 as a gap. At most ~13 of them
   are recoverable by any scraper. The number worth tracking is *venues that
   publish a price we failed to get* — roughly **7–13**, not 112. Everything
   else is a window-only card that is already correct and complete.
2. **A window-only card is not a failure.** Coyote Crossing's card, stating
   Mon–Fri 4–6 with no items, is exactly what that venue published.
3. **The only untested source is not the venue's website.** Off the Rail's
   `$3 domestic beers` came from `delco.today`, a third-party roundup — and
   `data/roundup_hits.json` currently holds two keys and names **0 of the 78**.
   Google Places reviews and editorial summaries are a second such source; we
   pay for Places already but hold no review text (`places_venues.json` has no
   review field), so sizing it costs money and is Paul's call. **Neither is
   sized. Do not build either on this document's say-so.**

## 5. The probes — read-only, re-runnable, they are the evidence

| file | asks |
|---|---|
| `scratchpad/size_the_hop.py` | does a linked HTML menu page carry priced lines? |
| `scratchpad/size_the_seed.py` | is the price on the page we already fetch? |
| `scratchpad/size_bare_prices.py` | is the price written without a dollar sign? |
| `scratchpad/size_pixels.py` | is the price a menu board the filename rule cannot see? |
| `scratchpad/look_at_silent.py` | print a silent page's visible text, no verdict |

Each writes only into `scratchpad/`, respects robots, and prints a population
count as its last line. `the80.json` is the population; regenerate it from
`noitem.json` + `crawl_hits.json` if the crawl moves.

## 6. Rules this run confirms

- **Size before you build.** Four probes cost under an hour and stopped four
  builds, three of which would have shipped and been worth two venues each.
- **A bucket derived from what a pipeline CAPTURED is not a description of the
  world.** Ask the page. The "403 six" evaporated on contact; the "reach" story
  was 90% "there is nothing there".
- **A page that names the hour and shows no price is usually telling the truth.**

---

## 7. Addendum 2026-09-03 — the source that exists when the venue writes nothing

Paul: *"tracking is not the solution."* Agreed. §4 said where the prices are
not; this says where they are. The one source untouched by every crawler
change is the venue's **Google listing**: customers photograph the happy-hour
board, and reviewers write the prices out. Proven on one town for $2.96.

`scratchpad/size_google_eyes.py` — one Places Text Search per venue (photos
and reviews ride the same call), up to 10 photo downloads, one vision read per
photo on the `claude` CLI subscription (the reader `extract_photo_deals.py`
already uses). Read-only; cache under `scratchpad/google_eyes/`.

| Center City, 29 of the 78 | venues |
|---|---:|
| matched a Google listing | 26 (Bar Bombón lost to the accent in `name_agrees`; Justop is the apartment-block case; DBG unmatched) |
| customer PHOTO of a board that names the happy hour AND carries prices | **3** (El Vez, The Trestle Inn, Bloomsday) |
| REVIEW sentence naming happy hour AND a price | **1** (Pearl & Mary: `$2 oysters, $1 clams, $5 beers, $6 house wine, $7 cocktails`) |
| either | **4 of 29** |

Bloomsday is the containment case again: the board's HAPPY HOUR section lists
three drinks with no price, and the `$16` lines sit under CHALKBOARD SPECIALS
beneath it. A photo needs the same section rule a web page gets. Strict count
is therefore **3 of 29, ~10%**, which extrapolates to **~8 of 78**.

What it recovers is different in kind from every other route: El Vez and
Trestle Inn are **whole priced happy-hour menus** (Trestle: six items, two
windows) for venues whose websites carry nothing. The pipeline to publish them
already exists end to end — download, vision read, grounding, PA validators,
human review in `review_photos.py` — the only unbuilt piece is feeding it a
Google photo instead of a submitted one, plus the section rule.

Instrument note: **62 of 260 reads failed with `claude -p exited 1`** under
three parallel CLI calls, and one of the three hits (Trestle Inn) was inside
those failures. A read that errors is not a zero; the probe now re-reads them.

Terms note: the card photo lane already displays Places photos with
attribution. Publishing deals *derived* from a Places photo or review is a
different use of the same data and should be checked against the Places
terms before the lane ships.

### The whole picture, all routes sized

| route | of 78 |
|---|---:|
| Google listing photo / review (new, extrapolated from 29) | ~8 |
| dollar-less price (dot leader) | 2 |
| the hop, safe half | 2 |
| pixels, non-QR | ~2 |
| **all four built** | **~14 (18%)** |
| **no published price found anywhere** | **~64** |

For those ~64 the price is not on the web. The only source left is the venue's
own hand: the intake worker already accepts a photo per licence id, so the ask
is "text us a photo of your board", not "fill in a form". That is outreach, and
outreach is a lane Paul already runs; it is not a scraper change.
