# Handoff — get every menu that is listed

**Written 2026-09-01.** Previous handoff: `HANDOFF-STRUCTURED-MENUS-20260901.md`
(now superseded for the menu lane; its still-open items are listed at the bottom).

**Read `ARCHITECTURE-MENU-INGEST.md` first.** It is the durable map of how a menu
becomes items and where it breaks. This file is only the state and the next move.

---

## The goal, in Paul's words

> Get every single menu that's listed, period. If the website has a happy hour
> menu, we do everything required to actually get it, read it and ingest it, in
> whatever form it takes.

Not "most." Not "the platforms we have met." The measurement is already on disk:
**107 of the 175 windows we publish name a schedule and not one thing you can
buy** (`python ingest/report_holes.py`).

---

## 🛑 START HERE: the first task is a PLAN, not a patch

Paul asked, explicitly, that this session **open by producing a plan** to reach
the goal above, before writing any code. Do not start fixing venues. Bring him a
plan and let him choose.

The plan has to answer, at minimum:

1. **What are the 107 actually made of?** The five classes in the architecture
   doc are a first cut made by one function; they have not been audited against
   the real pages. How many of `no-price-published` (36) genuinely publish no
   price, and how many are misclassified? That number decides whether the goal is
   107 venues of work or ~70.
2. **What is the general mechanism?** Today we add a brand to a tuple. That does
   not scale and Paul has said so. Candidates, cheapest first:
   - **Fingerprint the platform, not the brand** (see the architecture doc). One
     change, converts "6 FRC brands we typed in" into "every restaurant on that
     platform." Almost certainly step one.
   - **Enumerate the platforms.** Toast, Square, BentoBox, Popmenu, SinglePlatform,
     Squarespace, Wix — a handful of publishers carry most independents. Count
     them across the corpus before writing any adapter; the count decides the
     order.
   - **A headless fetch tier** for pages that are genuinely drawn in the browser,
     used only where a cheap fetch has provably failed. Playwright is already a
     dependency (`tests/`).
   - **PDF and image menus.** There is already an LLM pass with a measured cost
     model — `HANDOFF-PRICES-COST-20260901.md`; the harness costs more than the
     model and BATCH is the lever. This is the honest last resort for the
     genuinely unstructured tail, and it is the one with a dollar figure
     attached, so it is Paul's call, not a session's.
3. **How do we know it worked, at the class level?** `report_holes.py` is the
   scoreboard. The plan should state the number it expects to move and to what.
4. **What is out of scope?** A venue that publishes no menu at all is not a
   scraper failure and should be named as such, not counted against us.

---

## State as of this handoff — all green, all live

- Working tree clean, `master` in sync with `origin/master`.
- `bash tests/run.sh` — **64 pass, 0 fail**; 8/8 seed deals pass the PA validators.
- 173 deals across 38 zones built and pushed; GitHub Pages deployed.
- Verified in WebKit at the live URL with **zero pageerrors**: North Italia and
  The Capital Grille both render their items.

### What landed in the previous session (commit `d0c2163`)

| venue | was | cause | now |
|---|---|---|---|
| North Italia | window, no items | its platform prints prices with **no dollar sign**; not a JS menu, contrary to the old handoff | **19 items live** |
| The Capital Grille (KoP + Philadelphia) | window, no items | the brand calls its happy hour **CAPITAL HOURS** | **16 items each, live** |

Three silent bugs fell out on the way and are fixed: a `$40` caviar dip and two
full-price appetizers about to publish as bargains (the not-a-deal gate matched
on slug only); two dishes deleted by a mid-name `*`; `$5.5` deleted by
`rstrip("0")`. All are written up in the architecture doc.

`ingest/report_holes.py` is new — the scraper now names its own misses, ranked by
class, offline.

---

## Sullivan's Steakhouse — diagnosed, not built

Paul asked whether it is automatable. **Yes, and it looks easy.** Two facts, both
established:

- It **403s our crawler's user-agent** and returns 200 to a browser UA.
  `robots.txt` allows `/menus/` with `Crawl-delay 10`.
- There is a plain per-location URL —
  `https://www.sullivanssteakhouse.com/king-of-prussia/menus/happyhour-food-drink/`
  — whose HTML is readable prose with **price headings owning the items beneath**
  ($25 / $20 / $15 / $10, plus "$5 Off Select Martinis"). That is exactly the
  `heading_prices` / `SECTION_PRICE_RE` machinery this repo already has.

It sits in the `priced-but-unreadable` class. It is a reasonable first proof for
whatever general mechanism the plan picks.

---

## Still open, and still Paul's calls — do not decide these

- The **NOUNS open-vocabulary question** for prose pages.
- The **Cloudflare Worker deploy**. (`CLOUDFLARE_API_TOKEN` lives in
  `umbrella-arcades/.env` and in shopify-analytics'; **this repo's own `.env`
  does not have it, and this repo must never read shopify-analytics'.**)
- The **6-item display cap** — it cuts in quote order.
- **Wilmington DE.** `RULES["DE"]` is deliberately empty. It needs a named
  authority and Paul's sign-off, never inference from PA.
- The `$1.00 off` hole on `black-horse-tavern-phoenixville`.
- **Missing tests**, now a real list: `heading_prices`, `item_label`,
  `section_items`, `SECTION_OFF_RE`, `darden_off_pct`, `darden_menu_quotes`,
  `darden_category`, `strip_category_marker`, `price_max`, and from this session
  `frc_menu_quotes`, `frc_category`, `money`, `darden_regular`.

---

## How Paul wants this worked

- Open with **one plain-English sentence**: no jargon, no paths, no numbers.
- **Pointed probes, not long test suites.**
- **Finish on the live URL in a browser showing the rendered card.** An
  intermediate file, a green aggregate and an HTTP 200 are each blind.
- Run **all five gates** or the fix has moved no data.
- One thing at a time, finished before the next — and **Paul picks the next one.**
