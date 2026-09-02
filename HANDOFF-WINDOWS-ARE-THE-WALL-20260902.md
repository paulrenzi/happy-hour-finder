# Handoff — the items are solved; the WINDOW is the wall

**Date:** 2026-09-02
**Repo:** `C:\Users\paulm\happy-hour-finder` (its own `.env`, never shopify-analytics')
**Branch:** `master`, pushed. **Verified live in WebKit** — 43 KoP cards, no page errors.
**Read first:** `ARCHITECTURE-MENU-INGEST.md` §*"The binding constraint moved to the
WINDOW"* and §*"Scoped runs — `ingest/needy.py`"*. Everything below is the short version.

---

## 🎯 What the next session is for

Paul: *"we're going to solve all of the remaining rough edges so these scrapes are
incredibly productive and successful each time we run one on a town."*

**The rough edge is not the reading any more. It is the window.** A run on a town now
reliably produces items and unreliably produces cards, because a venue with items and
no window gets no card.

---

## 🔑 The finding, in one number

`ingest/needy.py` over the seven KoP-adjacent towns returned **96** venues.
The full pipeline ran on all of them — 93 crawled, sonnet read **138 verified items
across 12 venues, 0 refused** — and `ingest/needy.py` **still returns 96.**

The board gained **one card** (Sullivan's 20 → 26 items).

Corpus-wide, `extract_deals.py` says it plainly:

```
366  venue had quotes
208    KEPT
154    quote states no schedule   <-- bigger than every other hole class combined
```

**And the windows are in the pages we already fetched and cached:** Blue Bell Inn
4:30–6:30 PM, il Granaio 4–6:30 PM, Autograph Brasserie 7–9:30 PM, Bistro on Bridge
to 6:00 PM, StoneRose 6pm. Three of those are inside **PDFs**. The quote pass produced
no schedule-bearing quote from any of them.

> This is *"there's no intelligence running over pages"* one field to the left. A rule
> engine decided what a schedule looks like; these venues did not spell it that way.

---

## ⏳ THE DECISION THAT UNBLOCKS EVERYTHING — Paul's, not a session's

**May the page reader propose a WINDOW?** Today the contract is *items only, never a
window*, and that contract is what makes the model shippable.

The shape that keeps the discipline intact:

- the model returns the **verbatim span** it read the window from
- `verify()` checks that span really occurs in the page — **in code**
- the **existing deterministic parser** converts the span to a window, so
  **"no meridiem ⇒ refused, never guessed" is untouched** and the model never invents
  a time

That is a reader proposing **evidence**, not a source stating a **fact** — the same
distinction the item pass already survives on.

🛑 **Nothing has been built. Do not build it without the call.** If the answer is yes,
it is worth roughly the 154 venues; if no, the 154 need a different plan and the towns
stay thin.

---

## 🛑 Scope rules that are already settled — do not reopen them

- **No full-corpus run.** *"sonnet isn't cheap at a certain scale."* The previous
  handoff's "cheapest remaining win — ~900 venues overnight" is **withdrawn**.
  A run names its towns and `ingest/needy.py` names the venues inside them.
- **West Chester is a stand-alone job, and it comes AFTER the small towns are good.**
  They are not good yet. Do not touch it.
- **robots.txt is obeyed.** A previous handoff recorded an override as Paul's call; it
  was misattributed to this project and is **retracted** — the flag and its code path
  are gone. Do not reintroduce one without Paul saying so about *this repo*, in writing.
- **One writer per worktree.** A second session in this checkout ran `git add -A` and
  swept another session's uncommitted work into its commits.

---

## The run command, end to end

```
python ingest/needy.py phoenixville wayne_radnor --show --lids run.lids
python ingest/crawl_sites.py --lids run.lids --recrawl --render
python ingest/read_pages_llm.py --show --rejects        # sonnet, batched
python ingest/extract_deals.py && python ingest/build_bundles.py
bash tests/run.sh && git add -A && git commit && git push
python scratch/card_diff.py     # WHICH cards moved — a total cannot see a value change
python scratch/live_check.py    # the gate that counts; wait 2-3 min or you grade the last deploy
```

`scratch/` is gitignored and rebuildable: `probe_pages.py` (start every defect here),
`dump.py`, `heads.py`, `live_check.py`, `probe_silent.py`, `card_diff.py`.

---

## Carried decisions, still open

1. ⏳ **Morton's** — `/event/power-hour/` names twenty dishes and prices none
   ("Specially Priced"). Does a named menu with no prices belong on a card? Today it
   ships a window and an empty list.
2. ⏳ **Bonefish** — *"Happy Hour starts at 3:30pm daily"*, a start with no end.
   `` `Live until ${hit.w.end}` `` needs one.
3. ⏳ **Menus not on venue websites** — Google Business posts / Instagram /
   aggregators / phone. The honest ceiling on a *full* board, and a product decision.
4. Should an all-day special read "Mondays, all day" rather than midnight-to-midnight?

---

## State, verified

- Live KoP board: Cheesecake 33, Sullivan's 26, Tommy's 19, Seasons 52 19,
  North Italia 19, Eddie V's 17, Taku 16, Capital Grille 16, Paladar 14,
  **bartaco 9** (the PNG pass did land — that was open in the last handoff), Fogo 7,
  D&B 6, Peppers 4, Valley Forge 3, Pizzeria Vetri 2, Red Lobster 1.
- `bash tests/run.sh` green. 204 deals, 38 zones, 2,783 venues shipping.
- `ingest/needy.py` is **new and committed** — the selection half of a scoped run,
  promoted out of `scratch/` because it is now standing procedure.
