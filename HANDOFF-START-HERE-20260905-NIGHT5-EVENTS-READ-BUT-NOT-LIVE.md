# HANDOFF — the events reader works, the chips work, nothing is live (2026-09-05, night 5)

**Read this first, then `PLAYBOOK-NIGHT-OUT.md` §14, then §13.**

---

## The one-sentence state

Paul tapped **Live music**, all towns, no other filter, and got **zero rows** —
not a bug: the 28 grounded event rows read from Wayne were never `--post`ed, so
`GET /live/events.json` returns `{"venues":{}}` and the chip has nothing to
filter.

Verified this session, live, not inferred:

```
$ curl -s https://hhf-submit.paulmichaelrenzi.workers.dev/live/events.json
{"generated_at":"2026-09-05T18:29:24Z","today":"2026-09-05","horizon_days":14,"venues":{}}
```

---

## What is true right now

| | |
|---|---|
| the agent events reader | **works** — one town read end to end |
| Wayne: board venues / publish a calendar | **14 / 4** |
| grounded rows on file | **28** (`data/events_reads.json`), 0 dropped |
| cost | ~$7.47, **~$0.53 a venue** |
| rows in the database | **0** |
| rows on the board | **0** |
| the UI that shows them | **built, live, tested, empty** |

The UI half **is** live and confirmed on the deployed site: `index.json` carries
the `state` field, `sw.js` is stamped `hhf-2026-09-05-471-45ca912d`, the four
chips are `Everything · Drinks under $5 · Live music · Events`, the State picker
offers `All / PA / DE` (52 towns → 44 PA, 9 DE), and the Sort control is gone.

---

## Do this first, in this order

**1. Get Wayne's rows into the review queue** (~30 seconds, needs `ADMIN_TOKEN`
and `SUBMIT_API` from this repo's own `.env` — never another repo's):

```
python ingest/read_events_venue.py --zone wayne_radnor --post
curl -H "Authorization: Bearer $ADMIN_TOKEN" "$SUBMIT_API/admin/events?status=pending"
```

**2. Rule on them.** Agent rows land `pending` by design and are invisible until
a person approves each one — `POST $SUBMIT_API/admin/events/review/<id>` with
`{"status":"approved"}`. 🛑 This is a human ruling and a re-read must never
overturn it. Paul has not yet said to approve; ask.

**3. Prove it landed** with the overlay, not with an HTTP 200:

```
curl -s "$SUBMIT_API/live/events.json" | head -c 400
```

Then open the board and tap **Live music**. If it is still empty, run §11's
checklist in order — overlay non-empty? → row `approved`? → the row's `lid` in
the built bundle? → `applyEvents` in the **live** `lib.js`?

---

## Then: dig into the schedules (what Paul asked the next session for)

The reader has proven itself on one town. The open work is depth and breadth:

- **Fan out from Wayne.** The zone is the unit. Budget `venues × $0.53` and
  expect ~7 in 10 to return a clean "none" — worth paying for, because it is
  what stops us re-reading them.
- 🛑 **`HHF_MAX_TURNS=28`, never the default 14.** 118 North's page is 755KB; at
  14 turns the agent exhausted itself, returned `kind: "exhausted"`, and cost
  $0.67 for nothing. An exhausted result is **not** evidence a venue publishes
  no events — re-run it bigger before believing a "none".
- **Recurring shows are unhandled.** Flip and Baileys' Music Bingo and Dollar
  Drink Night are weekly; the reader returns them as dated one-offs inside its
  14-day window, so the rows go stale rather than repeating. Decide whether a
  weekly rule belongs in the schema or whether re-reading every fortnight is the
  answer.
- **The four fields that are the moat are still mostly blank** — start time, set
  length, cover, kitchen-open-during-the-set. Wayne's rows carry start times;
  almost nothing else. 🛑 Blank means unknown, never zero.
- **Set the re-read cadence.** Nothing schedules this reader yet.

---

## Standing rules this work sits under

- **Happy hours are the front of the product.** Events hang off a venue that
  already earned its card by publishing an hour we could prove. Paul restated
  this on 09-05: *"I still want the website to be about happy hours first."*
- **Two chips, because they are two questions** — "live music is one thing, and
  events is another" (Paul). Both are `venueTest`, so an event filter is asked
  once per venue and **keeps a bar with a band and no published happy hour**.
- Any `web/` change ships nothing until a **detached-worktree** rebuild
  (`git worktree add --detach <path> HEAD`) restamps `web/sw.js` **in the same
  commit** as the bundles it is welded to.
- `bash tests/run.sh` prints `OK` or nothing ships. A green suite proves the
  code, **not** that the lane has data in it — that takes one curl.
- Verification is a live fetch of served bytes or a live browser render. Never
  an HTTP 200, never a green CI run.
- Pull before push. Other sessions and Codex work in this checkout.

---

## Files touched this session

| | |
|---|---|
| `web/lib.js` | `FILTERS.music` / `FILTERS.events` (venueTest), food/drinks removed, `nextEvent` clock-aware |
| `web/app.js` | State picker, `paintZonePicker`, Sort control removed (`SORTS` kept for `s=` links) |
| `web/index.html`, `web/styles.css`, `web/manifest.json` | State control, and copy that is no longer about King of Prussia |
| `data/zones.json`, `ingest/build_bundles.py` | explicit `state` on every zone, carried into `index.json` |
| `ingest/read_events_venue.py` | `bundle_sites()` fallback — it could not see 33 of 471 board venues |
| `data/events_reads.json` | Wayne's 14 venues, 28 rows |
| `PLAYBOOK-NIGHT-OUT.md` | **new §14** — this session's findings |
| `README.md` | the events lane's real state, and the read-a-town commands |
| `tests/events.test.mjs`, `tests/time_math.test.mjs`, `tests/near_check.py` | new filters, clock-aware `nextEvent`, no `#sort` |

## Still queued from before, untouched

Backend for bar self-signup (foundation exists: `venue_tokens`, `web/venue.html`,
`POST /venue/events`) · the 3-mile "later tonight in town" strip · §13 step 0
Untappd prevalence sweep · Ticketmaster/West Chester · photo-fill for five Philly
zones (paid Google Places calls, needs Paul's go-ahead).
