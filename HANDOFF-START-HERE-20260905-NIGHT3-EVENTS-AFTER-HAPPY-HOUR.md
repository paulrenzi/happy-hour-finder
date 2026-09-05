# HANDOFF — 2026-09-05 (night 3): the mobile sheet fix shipped, and the next session is "what's on after your happy hour"

Read `README.md` first, then **`PLAYBOOK-NIGHT-OUT.md` sections 10, 11 and 12** —
12 is new tonight and is the whole brief for the next session.

---

## ⏳ NEXT SESSION: design "events after the happy hour" — think it through, then plan

**No code first. This is a design session that ends in an implementation plan.**

The board tells a reader where to drink at 5. It cannot tell them what is on at
8, so the night stops at our card. Meanwhile `dead-shows` can already send a
reader *to* us. The reverse direction is the missing half, and it is the product
thesis itself: **the unit is a night in a town, not a venue.**

Three populations, and they are three different problems — the full framing,
what carries over from `dead-shows`, and the four open design questions are in
**`PLAYBOOK-NIGHT-OUT.md` §12**. In short:

| # | Population | Source | Cost to reach |
|---|---|---|---|
| 1 | local band / cover duo at the bar you are looking at | the venue's own calendar — a JPEG or a Facebook embed | expensive; it is the moat; `ingest/read_events_venue.py` exists and **has never been run against a real venue** |
| 2 | a ticketed show in the same town | Ticketmaster Discovery API, free tier, already proxied by `dead-shows/worker/worker.js` | nearly free |
| 3 | a genre circuit (Dead tribute is one) | community directories like gratefuldeadtributebands.com | cheap per lane |

**Sequence by cost, not by value:** 2 proves the surface almost free, 3 reuses a
scraper we already run daily, 1 is the defensible one and must not block the
other two.

**Do before proposing anything:**

- Read `dead-shows/scripts/link_happy_hour.py` (the build-time, city-gated join)
  and `dead-shows/worker/worker.js` (the key-hiding proxy, and the artist list
  embedded in **two** files — `artists.json` and the worker — that must be edited
  together).
- Survey the open-source/API landscape for the ticketed and genre layers.
  Ticketmaster Discovery is confirmed working on the free tier. Bandsintown is
  artist-driven and its fetch is blocked (§2). Facebook event search went
  login-gated platform-wide 2026-08-01 and the Graph API has never returned other
  pages' events — **that hole is structural; do not re-litigate it.**
- Answer §12's four questions (card line vs its own surface; write into `events`
  vs join at render; radius — walk or drive; which town proves it) before writing
  a schema line.

**Rules that already bind whatever gets built:** blank means unknown, never zero;
a third-party row lands `pending`, never `approved`; `eventFingerprint` is
derived, never generated; the Worker runs UTC and "tonight" does not; and any new
endpoint the page calls needs a route stub in **all four** browser checks. Those
are all `PLAYBOOK-NIGHT-OUT.md` §11 — read it, each one cost a session already.

---

## What happened this session

### A. The mobile overflow on the "wrong" sheet — fixed, gated, live

The prior handoff said the report-wrong sheet's **textarea** overflowed on a
phone. It does not. Measured in a real WebKit engine at 320 and 390px, `.noteBox`
sits exactly inside the sheet's padding box with `scrollWidth == clientWidth`.

**The actual defect was the button row.** `.actions > .btn` is
`white-space: nowrap` with `min-width: 0` — correct for a card, where a button
says "Directions". A sheet's buttons are sentences: "Send a photo of the menu"
next to "No photo — tell us instead" is wider than a 320px phone, so the pair
shrank under their own labels (each `scrollWidth 158` in a `clientWidth 134`
box), both clipped, the second ran past the sheet's right edge, and the sheet
scrolled sideways. The venue sheet's "These hours changed — send a photo of the
menu" clipped the same way on its own.

Fix, scoped to `#sheet` so no card layout moves (`web/styles.css`): the row wraps
and the label wraps with it, so a button too long for its row takes a line of its
own instead of losing its words. `min-width: min(100%, 8ch)` keeps a shared row
from collapsing a button to a sliver — an earlier `14ch` regressed the venue
sheet's Directions/Website/Share onto two lines, which is why the number is small
and measured rather than round.

**The gate:** `tests/card_chrome_check.py` already owned this class of bug (it was
written for a Directions label clipped by its own button) but only measured inside
the card. It now opens both sheets a reader can reach from a card, at 320px, and
checks every box against the sheet's padding box, its own `scrollWidth`, and the
sheet's sideways scroll. Proven not blind: reverting the CSS makes it print all
nine failures.

Commits `1ff3709` (CSS + gate) and `6dfb3ad` (detached-worktree rebuild,
restamping `sw.js`). Verified **live** — served `styles.css` and `sw.js` bytes
fetched with a cache-buster, then a real WebKit run against
`https://paulrenzi.github.io/happy-hour-finder/` at 320px: nothing clipped,
nothing past the edge, no sideways scroll, no page errors.

### B. `near=` — a link can sort a town around a place (commit `8c98585`)

Landed in this checkout by a concurrent session; recorded here because it is the
rail the next session builds on. `#z=<zone>&near=<lat>,<lng>&from=<name>` ranks a
town's board by distance from a **place** instead of from the reader, so
`dead-shows` can link a show to the happy hours around its door without copying
our list onto its card. The board already ranked from `state.origin`; the whole
feature is an origin the link gets to choose.

The real find inside it: **"Nearest" was not a distance sort on any future day.**
The distance term is a fraction of two hundred miles (half a mile = 0.00225 of
it) while two confidence terms reach 0.081 and 0.0081 — so the order was "best
sourced, then nearest," and a bar 0.2 mi away lost to one fifteen miles away.
Distance now leads; confidence breaks exact ties only. `tests/near_check.py`
opens a **fresh page per URL** (the app reads its hash once at boot) and asserts
the resulting order, not the formula.

### C. Documentation

- `PLAYBOOK-NIGHT-OUT.md` **§12** (new) — the two-way `dead-shows` link, what
  carries over and what does not, and the four open design questions.
- `README.md` — a new "Linking into the board from another site" section (the
  three URL forms are the board's public API); the sentence-length-button trap;
  and the tiebreak-sizing rule.

---

## State of the board

Unchanged this session — 51 zones, 471 published windows, 312 venues carrying
items, 161 with an hour and no items. `bash tests/run.sh` prints `OK` (578 tests,
every browser check `ok`). Local `web/sw.js` and the live one both read
`hhf-2026-09-05-471-c0b98fe1`, so what is committed is what is served.

## Still queued, untouched, needs Paul's go-ahead (paid Google Places calls)

Photo-fill for `university_city`, `south_philly`, `northwest_philly`, `manayunk`,
`west_philly`. **Re-derive the real gap first** with
`ingest/fetch_venue_photos.py --from-board --zone <zone>` and **no `--spend`** —
the session-start counts in the previous handoff are stale, and the coverage
check is still board-keyed rather than manifest-keyed (an aborted uncommitted run
gets re-bought at full price; ~$22.66 was lost this way on center_city). The
one-line fix is `lid in covered or lid in manifest` and nobody has made it.

## Standing rules

- `bash tests/run.sh` must print `OK`. Nothing ships otherwise.
- Any `web/` change ships nothing until a **detached-worktree** rebuild restamps
  `web/sw.js` (`git worktree add --detach <path> HEAD`). `sw.js` lands in the same
  commit as the bundles it is welded to.
- Verification is a live fetch of the served bytes or a live browser render.
  Never an HTTP 200, never a green CI run, never a desktop screenshot for a mobile
  layout question.
- Never invent or guess an item, price, or window.
- This repo's `.env` never borrows another repo's.
- Pull before push — other sessions and Codex work in this checkout.
