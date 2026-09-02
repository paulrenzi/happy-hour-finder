# Handoff — there was never a model reading the pages, and now there is

**Date:** 2026-09-01 (night)
**Repo:** `C:\Users\paulm\happy-hour-finder`
**Branch:** `master`, pushed (`c4c9416`). **Verified in a real browser at the live URL.**
**Read first:** the new top section of `ARCHITECTURE-MENU-INGEST.md` —
*"Three ways to read a menu — and only one of them can make a JUDGEMENT."*

---

## 🔑 The finding this session exists for

Paul, looking at the board and naming four venues by hand:

> *"why would a scraper running sonnet miss that the whole page is a happy hour
> menu, when you see it immediately? why is our scraper so dumb?"*
> …
> *"there's no intelligence running over pages. that's a mistake."*

**He was right, and the answer is the shape of most of the misses in this repo.**

**THE SCRAPER WAS NOT RUNNING A MODEL. It was not running any model at all.**

- `crawl_sites.py` is ~2,000 lines of regex and DOM rules.
- `extract_prices_llm.py` — the only model in the pipeline before today — reads
  **the quotes those rules already produced**, prices only, never windows.

> 🛑 **A page the rules threw away was invisible to every model we run.** The
> model could not see the page. It could only see what a regex had already
> decided was worth keeping. Every "the venue doesn't publish it" verdict in the
> last three handoffs was produced by a rule engine with no way to be surprised.

---

## The four venues Paul named, and what each one actually was

| venue | what the rule said | the real defect |
|---|---|---|
| **bartaco** `/kophightidehour/` | `on_hh = depth>1 and /happy.?hour\|special/` | failed **both** halves ⇒ menu is a **PNG**, never collected |
| **Morton's** `/event/power-hour/` | same regex | brand calls it *Power Hour*; page read as ordinary |
| **Sullivan's** `/menus/happyhour-food-drink/` | `hh_sections()` needs an hh **heading**; page has none | 4 price bands, **26 dishes**, unread on a page held for weeks |
| **Cheesecake Factory** | — | 13KB JS shell, **11 visible lines** |

🔑 **Paul's hint was the whole fix for two of them: _"make sure we are grabbing
anything with 'hour' in the name."_** `url_names_hh()` now answers this in one
place, matching **HOUR** (never `hours` — that is the opening-hours page)
against the **path** only, at any depth. Link ranking and the sitemap filter
read the same function.

### And the one no rule can ever fix

Those 19 dishes now reach `extract_deals.py`, which asks `category_of()` — a
**hand-typed noun whitelist** — and keeps **two**:

- `Beef Wellington Bites` — because *bites* is a word somebody typed in
- **`Jumbo Shrimp Cocktail`, filed as a COCKTAIL.** A shrimp cocktail, on the
  board, as a drink.

`A5 Wagyu Nigiri` and `Cheesesteak Eggrolls` match nothing and are dropped
**with no line in any log**. Knowing a wagyu nigiri is food is a **judgement**,
and there was nowhere in this pipeline that a judgement could be made.

---

## What shipped — `ingest/read_pages_llm.py`

`crawl_sites.py` now caches the visible text of every happy-hour page to
`data/pages/` (gitignored, rebuildable). The new pass reads the **whole page**.

**The safety contract is unchanged from the price pass, and it is what makes
this shippable:**

- **ITEMS ONLY.** It never sees, proposes or alters a **window**. Days and times
  stay with the deterministic extractor and its meridiem rules, so
  *"no meridiem ⇒ refused, never guessed"* is untouched.
- **Every item carries the span it came from**, checked against the page **in
  code** by the same `verify()`. **The model is a reader, not a source.**

```
python ingest/crawl_sites.py --zone X --recrawl --render   # fills data/pages/
python ingest/read_pages_llm.py --show --rejects           # reads them
python ingest/extract_deals.py && python ingest/build_bundles.py
bash tests/run.sh && git add -A && git commit && git push
python scratch/live_check.py            # the gate that counts
```

### Results, verified in WebKit at the live URL

| venue | before | after |
|---|---|---|
| The Cheesecake Factory | 0 | **33** |
| Sullivan's Steakhouse | 2 (one **wrong**) | **20**, shrimp cocktail is food |
| Tommy's Tavern + Tap | 14 | **19** |
| Paladar | 12 | **14** |
| Fogo de Chão | 4 | **7** |

**74 items read, 0 refused.** All five gates green.

---

## 💰 Model and cost — settled, with the measurement behind it

**Sonnet, batched.** Paul: *"we use sonnet in controlled batches."*

> 🔑 **Cost is the NUMBER OF CALLS, not the size of the model.** `claude -p`
> bills a fixed harness on every invocation — **28,272 tokens, 9,407 with
> `LEAN_ARGS`**. At batch 40 **opus beat haiku on raw tokens AND on recall at
> once**. Batch size is the lever; the model is the smaller adjustment.

🛑 **This is also why a haiku→sonnet cascade can cost MORE than sonnet alone** —
it doubles the calls, and the fixed term dominates. If one is ever wanted, the
only shape that makes sense is **sonnet re-reading ONLY the pages haiku returned
nothing for**. `--model` and `--batch` are flags, so measuring is one command.

🛑 Haiku was already measured on the price pass and **rejected on evidence**:
**15% of items lost, and recall swinging 55/45/46 across identical runs.**
Unreliable recall is worse than expensive recall — you cannot tell a venue with
no menu from a venue haiku had a bad day on.

🛑 **Cache widely, read narrowly.** The crawler caches on "happy hour appears
anywhere", which is correct — a page not kept cannot be reconsidered. Those
words are in the **nav of every restaurant site alive**, so the first run put
**47 pages up and 41 were a bottle shop's homepage**. `worth_reading()` gates
the model on the page making a claim about **itself** (URL names an hour, or ≥2
prices under a happy-hour heading). A page that fails it is **not judged
menu-less** — it is just not worth a call, and it stays cached.

---

## The headless tier, and the line drawn on robots.txt

`--render`: a page whose URL **names an hour** that came back under 25 lines is
rendered in WebKit, then read by the **same readers with the same containment**.
Nothing is trusted differently for having come through a browser. Bounded hard —
it is ~40x a fetch.

Cheesecake Factory: **11 lines → 161, 24 quotes.** And it is the cleanest proof
of why the model tier sits right behind it: what the **regex** made of those 161
lines was **`"800 cal $10.95"`** — a real price bound to a **calorie count**.

> ⚖️ **`menu.thecheesecakefactory.com/robots.txt` is `User-agent: * / Disallow: /`.**
> That is **not** the same as the 403-ing WAFs this crawler already works around
> (a WAF fingerprints our connection shape; robots is an explicit request), and
> **rendering does not make us less of an automated client.**
> **Asked, and reaffirmed — Paul's call: we read it.** Implemented as
> `--render-blocked`: its own flag, **never implied by `--render`**, only for a
> page whose URL names an hour, same politeness delay. **Nothing else in the
> crawl ignores robots.txt** — it is still fetched and still obeyed everywhere
> else. Recorded in `crawl_one()` and in the architecture doc **as a policy
> choice, not a bug fix**.

---

## 🚨 Hazard hit this session — TWO SESSIONS IN ONE WORKTREE

Two commits appeared mid-session (`96913e7`, `38dd47e`) from another Claude Code
session running in this same checkout. It ran `git add -A` and **swept my
uncommitted crawler fixes into its commits.** The work survived, and its
`boxed_windows()` fix is good — **but that was luck.** Both sessions were
rebuilding `data/crawl_hits.json` and `data/deals_extracted.json`, and a
concurrent `--recrawl` silently clobbers the other's crawl.

🛑 **One writer per worktree.** If two sessions are wanted, the second belongs in
a `git worktree`, not in this directory.

---

## Also fixed, and worth keeping in mind

- 🔑 **A two-character evidence span is a PRICE BAND, not junk.** `verify()`
  floored evidence at 3 characters — right when every quote was a sentence,
  wrong the moment a whole page became readable. **Tommy's Tavern lost all eight
  of its real items** to it, refused as *"no evidence"* while the evidence was
  sitting in the page spelled exactly as claimed.
- 🔑 **A heading that is NOTHING but a price is a BAND, not a section title.** On
  Sullivan's every dish name is an `<h3>` too, so "stop at the next heading"
  stopped at the first dish; and the price sits in a **sibling column** to its
  items, so the box test broke as well. A bare-price heading now owns the marked
  headings after it, to the next priced heading.
- 🔑 **A page the venue TITLED its happy hour is one whose every line is inside
  it.** Granted only for an **hour** in the path, never for `/specials` —
  `/daily-specials` prices are Monday's, and containment is what lets a quote
  travel to another page's schedule.
- 🛑 **`pgrep` does not exist in this shell.** `until ! pgrep ...` exits
  instantly (command not found ⇒ non-zero ⇒ `!` true). Two "the crawl finished"
  reports this session were that bug, not a measurement. Use
  `Get-CimInstance Win32_Process` or poll for a marker the script prints.

---

## Next actions, in order

1. **A full-corpus `--recrawl --render` and page read.** All of this was proven
   on King of Prussia only. ~900 venues; run it overnight. **This is the
   cheapest remaining win by a wide margin** — the readers are built, tested and
   live, and 34 zones have never seen them.
2. **bartaco is still 0 items** — its menu is a **PNG**, now collected by
   `menu_images()`. `ingest/extract_menu_images.py` is the pass that reads those;
   it had not finished when this was written. **Check it.**
3. **Morton's is still 0 items and that may be correct** — `/event/power-hour/`
   lists twenty dishes and states **no price for any of them** ("Specially
   Priced"). ⏳ **Paul's call:** does a named menu with no prices belong on a
   card? Today the answer is no and the venue ships a window with an empty list.
4. **⏳ PAUL'S CALL, carried from the last handoff — Bonefish's start-only
   window.** *"Happy Hour starts at 3:30pm daily"* — a start with no end.
   `` `Live until ${hit.w.end}` `` needs one.
5. **⏳ PAUL'S CALL, carried — where to source menus that are not on venue
   websites** (Google Business posts / Instagram / aggregators / phone). Still
   the honest ceiling for a *full board*, and still a product decision.
6. Carried: should an all-day special read "Mondays, all day" rather than
   midnight-to-midnight?

---

## Tools left behind (in `scratch/`, gitignored)

- `probe_pages.py [urls…]` — run every reader over any URL and print what each
  one gets. **This is how all four of today's defects were found**; start here.
- `dump.py <url>` — the page's visible lines as the crawler sees them, numbered.
- `heads.py <url>` — which lines the page marked up as headings.
- `live_check.py` — the live board in WebKit, every painted KoP card with its
  window and item count. **The gate that counts.** 🛑 Give GitHub Pages ~2–3
  minutes after a push, or you will grade the previous deploy — that happened
  once tonight.
- `probe_silent.py <zone>` — re-fetch silent venues at a 40-page budget. Run
  before ever raising a cap.
