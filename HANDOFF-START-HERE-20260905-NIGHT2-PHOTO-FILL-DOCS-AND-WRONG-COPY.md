# HANDOFF — 2026-09-05 (second pass tonight): docs, a copy fix, and where photo-fill stands

Start here. Read `README.md` top to bottom, then this file for what happened
this session and what's queued next.

## ⏳ NEXT SESSION: DO THIS FIRST — mobile text-box overflow on "wrong"

**The report-wrong flow's text input area overflows on mobile.** When a user
taps "wrong" on a venue card, the sheet that opens (`reportWrong()` in
`web/app.js`, around line 1261) includes a free-text box for describing what's
wrong. On a phone-width viewport the box (or its surrounding sheet) overflows
its container — a CSS/layout bug in that input area, not a JS logic bug. Fix
it before touching anything else next session. Verify **on a phone-width
viewport in a real headless browser** (per this repo's rule: never trust a
desktop screenshot or an HTTP 200 for a mobile layout issue) — `tests/
render_check.py` / `tests/search_check.py` show the pattern for driving a
real browser against the site; extend one of them or write a scoped check
that opens the "wrong" sheet at a narrow viewport width and inspects the
textarea's bounding box against its container.

---

## What happened this session

### A. Removed a stray internal-mechanics clause from the "wrong" report copy

The report-wrong sheet's body copy used to read:

> Wrong window, new prices, a menu that changed last week — it is all the
> same fix, and the fastest one by a distance is a photo of the menu: it goes
> into the same queue a person reads every day, and an approved photo
> replaces what's on the card above.

The trailing clause (everything from the colon on) described our internal
review-queue mechanics — a reader doesn't need to know a person reads a
queue to use the feature. Cut to:

> Wrong window, new prices, a menu that changed last week — it is all the
> same fix, and the fastest one by a distance is a photo of the menu.

Shipped `web/app.js` (commit `9c791c3`), rebuilt bundles in a detached
worktree (`/tmp/hhf-build-wt`, `git worktree add --detach`), gated clean
(`bash tests/run.sh` → 578 tests, OK), pushed (`bff5fee`), watched the GitHub
Pages Action to green, then verified **live** by fetching the actual served
`app.js` bytes directly (`curl` + `grep`, not a local check and not an HTTP
200) — the string is gone from the live bundle and the sentence reads clean.
Also ran `tests/live_front_door.py center_city` (114 of 114 named live) as a
second live confirmation.

### B. Documentation pass — three findings from earlier tonight's photo work written down

Added to **`ARCHITECTURE-MENU-INGEST.md`** (this repo's architecture/KG
notes — read it before touching ingest):

1. **The photo pipeline is `ingest/fetch_venue_photos.py`, not
   `discover_places.py`.** `discover_places.py` resolves a venue's website;
   the photo fetch, storage and manifest-write are a separate script. Older
   handoffs (including tonight's earlier one) name the wrong file — read the
   correction before running anything.

2. **🛑 The photo-fetch coverage check is board-keyed, not manifest-keyed —
   unfixed defect.** `from_board()` in `fetch_venue_photos.py` skips a lid
   only if `shipped_with_a_photo()` (the **built, pushed bundles**) already
   shows it with a photo. It loads `data/venue_photos_by_lid.json` into
   `manifest` but never checks it for the skip decision. So a lid resolved
   and written to the manifest during an earlier `--spend` run that was
   never built + pushed reads as "not covered" on the next run and gets
   **re-bought** — full search + photo billing again. This is exactly what
   happened during tonight's earlier center_city pass: a stale uncommitted
   partial run left resolved-but-unbuilt lids in the manifest, and the next
   run re-bought them, costing roughly **$22.66** in duplicate lookups (403
   successful lookups landed but the manifest only grew net +26). **Not
   fixed at the tooling level.** The fix is straightforward — the skip test
   should be `lid in covered or lid in manifest` — but nobody has made that
   change yet. Until it's fixed: **always commit + build + push before
   re-running the fetcher on the same zone**, and manually check
   `data/venue_photos_by_lid.json` for already-resolved lids from an earlier
   aborted run before spending again.

3. **`ingest/exclusions.py`'s mechanism**, now documented: it runs at the two
   build doors (`build_venue_base.py`, `build_bundles.py`), not at scrape
   time, so adding a name takes effect on the next rebuild with no re-crawl.
   Tonight it removed 114 grocery-store liquor licensees plus five named
   venues (Fine Wine & Good Spirits, Panera Bread, Suite 4 Eleven, Opa!
   Opa!, El Diablo). **Left alone, deliberately:** three rows where a
   fast-food name (McDonald's, two Chipotle rows) is misattributed to a
   grocery-store PLCB liquor licence — the PLCB licensee field names a
   grocery store at that address, but the resolved trade name is the
   fast-food chain sharing the licence/address. This is a licence-sharing
   misattribution, a separate known data anomaly, not a bug in the
   exclusion regex (which matches on trade `name` for exactly this reason).
   Nobody has fixed the misattribution itself.

Also added a condensed version of finding #2 and #3 to **README.md**'s
"Traps that have each cost a session" list, pointing back to
`ARCHITECTURE-MENU-INGEST.md` for the full detail. Note: this repo currently
has only one `PLAYBOOK*.md` file (`PLAYBOOK-NIGHT-OUT.md`), and it is scoped
to the night-out/events business layer, not the menu/photo ingest pipeline —
it was not the right home for these findings, so they went into
`ARCHITECTURE-MENU-INGEST.md` (the ingest architecture doc) and README's
traps list instead, which is where this repo's other ingest-debugging
findings already live.

Commits: `9c791c3` (app.js), `bff5fee` (bundle rebuild), `3438014`
(ARCHITECTURE-MENU-INGEST.md + README traps). All pushed and CI-green.

**Note on the shared checkout:** another session was committing to this same
working tree concurrently tonight (`dd8d93c`, docs on the two-file zone
split and stats refresh, landed mid-session). No conflict resulted — commits
interleaved cleanly and this session rebased onto `origin/master` before its
own push — but it's worth knowing this repo saw two active sessions on the
same checkout tonight, which is exactly the shape of bug the "shared
checkout" KG memory warns about. Nothing here needs further action; just
flagging it happened without incident.

---

## Photo-fill status — where it stands, and what's stale

**center_city is done**: photo-fill pass closed the gap from 582 missing to
33 missing (597/630 have photos as of that pass). Commits `8c4b7ad`,
`364eb3d`. Verified live via `tests/live_front_door.py` and a direct live
JSON fetch.

**Not yet started**, counts as of the *start* of tonight's session (from the
prior handoff, `HANDOFF-PHOTOS-NEXT-2026-08-01.md`-style table — these are
stale now that center_city's own numbers moved and the exclusions pass
removed venues from the corpus; **re-derive them before spending anything**):

| zone | missing (session-start count) |
|---|---:|
| university_city | 111 of 117 |
| south_philly | 105 of 109 |
| northwest_philly | 70 of 71 |
| manayunk | 55 of 58 |
| west_philly | 81 of 82 |

**Re-check these five zones' real gap before running the photo fetcher on
any of them** — both the venue counts (six exclusions removed 120 venues
from the corpus corpus-wide tonight, some possibly in these zones) and the
photo-covered counts may have shifted. Use `ingest/fetch_venue_photos.py
--from-board --zone <zone>` with no `--spend` first — it prints the real
gap and the dollar cost before doing anything, at Google's current list
price ($0.032/search + $0.007/photo).

---

## Standing rules, recap for whoever picks this up

- **Paid Google Places calls, scoped to one zone at a time, never the whole
  corpus.** Dry-run (no `--spend`) first to see the real gap and the cost.
- **Before spending on a zone already touched by an earlier aborted run**,
  check `data/venue_photos_by_lid.json` by hand for lids from that zone —
  see the coverage-check defect above. Commit + build + push any prior
  partial run before re-running the fetcher, so the board-keyed coverage
  check actually sees what's already resolved.
- `bash tests/run.sh` is the gate. It must show `OK` (not just a nonzero
  exit-free finish) before anything ships.
- **Any `web/` change ships nothing until a detached-worktree rebuild
  restamps `web/sw.js`.** Never build in the shared working tree — use
  `git worktree add --detach <path> HEAD`, run `ingest/build_bundles.py`
  there, gate there, commit + push from there.
- **Stage `web/sw.js` together with whatever bundle files it's welded to** —
  they must land in the same commit.
- **Verification is a live fetch or a live browser render, never an HTTP
  200.** Use `tests/live_front_door.py <zone>`, `tests/render_check.py`,
  `tests/search_check.py`, or a direct `curl` of the served bytes with a
  cache-busting query string. A local render, a green CI run, and a 200
  status are each blind to a different real failure.
- **Never invent or guess an item, price, or window.** A wrong item is
  worse than a miss.
- This repo's `.env` never borrows shopify-analytics' or any other repo's.
