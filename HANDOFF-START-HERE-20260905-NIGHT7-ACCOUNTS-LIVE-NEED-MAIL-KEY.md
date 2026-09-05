# HANDOFF — the two board faults are fixed, accounts are live, and mail is the one thing missing (2026-09-05, night 7)

**Read this first.** `PLAYBOOK-NIGHT-OUT.md` §15.11 and §16 hold the mechanism
behind everything below.

---

## The one-sentence state

The two faults Paul reported off the live board are fixed and shipped, and
accounts — magic-link sign-in, a saved list, a `Saved` chip, and a private note
on a place or on one night at it — are built, deployed and proven end to end
against the real Worker; **the only thing between them and a real customer is
`RESEND_API_KEY`, which is not set, so no sign-in email can be sent.**

## What shipped

### 1. Events were bleeding into the live-shows filter (§15.11)

The chip asked about the **venue** ("does this bar have a band in the next
fortnight") and the card then printed whichever event came next, with no kind
at all — so "Live music" advertised **"Tonight · Quizzo Night"**. A chip is now
the **kind predicate itself** (`FILTERS.music.kindTest`), the event that
survived it rides on the row, and the filter, the ranking, the card line and
the summary counts all read that one function.

### 2. No night-first order (§15.11)

An event row was ranked by its **happy hour** — window left, price, confidence
— so a band a week out outranked one tonight, and a bar with a band and no
published window fell out of the order entirely into "Hours not published" at
the foot of the board, on a card template with no line to say what was on.
Under an event chip the board is now a **calendar**: banded by the show's day
(tonight first, one header per night), then **distance**, then start time. A
venue with no window keeps its place in the night and prints its show.

### 3. Accounts (§16)

Four decisions were put to Paul before any code, and all four answered: **one
identity** (a subscriber address IS the account), **magic link**, the **whole**
of v1 (favourites + notes + a Saved chip + notes on events + cross-device
sync), same Worker and same D1.

- `worker/accounts.js`, tables appended to `worker/schema.sql`, applied to the
  remote D1 and the Worker deployed.
- 🔑 **One identity is not one consent.** `subscribers.status` still means only
  "is this on the digest"; signing in never touches it. An account-only row is
  `status = 'none'`. Gated in both directions.
- The session arrives in the URL **fragment** and is stripped from the address
  bar before the board rewrites the hash. Neither token is stored reversibly —
  both are SHA-256 hashes.
- The browser caches the saved list, so the board paints your places offline.
  Every write is optimistic and every failure puts it back.

## 🛑 The blocker, and it is one command

**`RESEND_API_KEY` is not set on the Worker**, so `POST /account/signin`
answers 202 and sends nothing. Nobody can sign in.

```sh
cd worker && wrangler secret put RESEND_API_KEY
# and set MAIL_FROM in [vars] to an address on a domain verified with Resend
```

Until then the only door is the admin route, which returns the link instead of
mailing it — it is also how the lane was proven live:

```sh
curl -s -X POST "$SUBMIT_API/admin/account/signin-link" \
  -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"email":"you@example.com"}'
```

Note the same key gates the **existing** email-signup lane, which has been
sitting `pending`/unmailed for the same reason since it was built.

## Everything is live — verified, not assumed

- `git log`: `626b4b2` is `HEAD`, pushed, matches `origin/master`.
- `web/sw.js` restamped and confirmed served: `hhf-2026-09-05-471-3628e8d4`.
- The live `app.js`, `lib.js`, `index.html` and `styles.css` were re-fetched
  from the CDN and confirmed to carry the account code, the `savedTest` filter,
  `#accountBox` and the save-button styles.
- The deployed Worker was driven end to end with curl: mint a link, redeem it,
  save a bar, write a note, read both back, watch the reused link answer
  `#signin=expired`, sign out and get a 401. **The smoke-test rows were then
  deleted** — `favorites` and `subscribers` are back to 0.
- `bash tests/run.sh` → exit 0, every section `OK`, including the two new
  gates below.

## New gates

| File | What it proves |
|---|---|
| `tests/events_filter_check.py` | The painted page in WebKit: the Live music chip shows only bands, tonight leads, nearest leads inside a night |
| `tests/accounts.test.mjs` | `worker/accounts.js` over **`schema.sql` itself** in Node's SQLite: one-use links, no plaintext tokens, no cross-account reads, signing in never subscribes |
| `tests/account_check.py` | The painted page: sign in, save, filter to it, note it, and the note survives a fresh load |

🛑 Two standing browser-check traps bit again while writing these, both now
commented in the files: a second `goto()` between `#hash` URLs **does not
reload**, and Playwright's `browser.new_page()` opens a new **context** with
its own `localStorage` — where the session and the cache live.

## Known open, not fixed

- The three defects listed in night 6's handoff are all still open: concurrent
  whole-file readers clobber each other, the hand-read path has no door-check
  guard, and the review queue shows the act but not the building.
- No UI lists "the places you have notes on" — a note is only reachable from
  the venue's sheet. Worth a pass once people actually have notes.
- Sessions never expire and nothing sweeps `sessions` or used `signin_tokens`.
  Harmless at this size; a scheduled DELETE is the fix when it isn't.

## Suggested next

1. Set `RESEND_API_KEY` (one command) and send a real sign-in link to yourself.
   Nothing else about accounts can be judged until that is done.
2. Read events for more towns — the lane is proven, the data is three towns
   deep, and the new order makes tonight's shows the top of the board.
