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

## ✅ THE DECISION WAS MADE — 2026-09-02, Paul: **YES**

**The page reader may propose a WINDOW.** Built and shipped the same session,
in the approved shape: verbatim span → checked in code against the page (twice:
in the reader, and again in `extract_deals.py`, so the sidecar is never evidence
of itself) → converted by `windows_from()`, **the existing parser, unmodified.**
*"No meridiem ⇒ refused, never guessed"* is untouched; the model never states a
time. `ingest/read_windows_llm.py`, sidecar `data/windows_pages_llm.json`,
8 tests in `tests/test_window_reader.py`. Commit `07473a6`.

**First run:** 31 eligible pages (only venues whose quotes state no schedule are
ever sent), 6 calls, 6 spans / 5 venues, 3 refused. **208 → 213 kept, no existing
card changed**, and the new cards arrived carrying items that had already been
read and stranded — Bistro on Bridge 26, il Granaio 23 (from a PDF, both its
windows), Anthony's Coal Fired 26, StoneRose 11, Garrett Hill window-only.
Verified live in WebKit on the phoenixville board, no page errors.

🔑 **The refusals are the pass working:** Bonefish is a start with no end,
Cornerstone has no meridiem, Miller's Ale House states two clauses across a line
break `clauses()` will not split. The model pointed at the right sentence each
time and the deterministic parser declined it.

🛑 **Two claims in this handoff were wrong** — reading the cached pages corrected
them. **Autograph Brasserie is not 7–9:30 PM**; that `6:30-9:30 PM` is GIRLS
NIGHT OUT and its happy-hour section states no hours at all. **Blue Bell Inn's
4:30–6:30 is in no page we hold** — it needs a re-crawl, not a reader. A window
quoted in a handoff is a claim about a page; check it against the bytes first.

### What is next on this, and what it is worth

Only **27 of the 154** had a cached page to read; the rest arrive as towns get
crawled. So the next scoped town run should carry the window pass:

```
python ingest/needy.py <towns> --show --lids run.lids
python ingest/crawl_sites.py --lids run.lids --recrawl --render
python ingest/read_pages_llm.py --show --rejects        # items
python ingest/read_windows_llm.py --show --rejects      # windows
python ingest/extract_deals.py && python ingest/build_bundles.py
```

⏳ **Two parser gaps the refusals named, both Paul's call, neither built:**
`clauses()` does not split on a line break (Miller's), and a no-meridiem range
like `tues-fri from 3:30-5:30` is refused on a page that also says HAPPY HOUR —
where an afternoon reading is close to certain but still an inference.

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
