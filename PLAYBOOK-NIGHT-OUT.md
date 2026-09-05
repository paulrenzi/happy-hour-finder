# PLAYBOOK — The Night Out (directional guidelines + revenue model)

Written 2026-09-04 from a research pass. This is the **why and where** for Happy Hour
Finder. The **how** for ingest stays in `ARCHITECTURE-MENU-INGEST.md`; the **what a deal
is** stays in `SPEC.md`. When this file and a handoff disagree about direction, this file
wins until Paul changes it.

---

## 1. The thesis in one paragraph

A happy-hour board does not reach $5M. The board is the **hook**. What the venue will
pay for is the **rest of the night**: the band, the trivia, the dinner seating, the thing
with margin that nobody can find. Paul stood on Bridge Street in Phoenixville for several
hours on 2026-09-04 while bands played in bars around him, and could not have planned a
night around them because no source told him who was on, when they went on, or what it
cost. That is the product: **the unit is a night in a town, not a venue.**

## 2. The gap, proven on our own town

Checked Friday 2026-09-04 for Phoenixville, PA:

| Source | What it had |
|---|---|
| JamBase | 12 events, all at the Colonial Theatre. Zero bars. No start times. |
| Bandsintown | Artist-driven; a cover duo that never claimed a page is invisible. Fetch blocked. |
| The Fenix, Bridge St | Rhythm & Blondes Fri, Tucker Michaels Sat, "7 to 10 pm." **Published as a JPEG of a calendar.** No cover listed. |
| Twelve78 Brewing | Benefit show Sat 6–9, band Sun 2–5, trivia Tue 7. **Facebook event embeds.** |

The data existed and was published. No aggregator carried it because it lives in an
image and a Facebook embed. Facebook's own event search went login-gated platform-wide
on 2026-08-01 and the Graph API has never returned other pages' events without app
review, so the hole is structural, not temporary.

**The fields nobody has, anywhere, including the venue's own page:** start time, set
length, cover charge, whether the kitchen is open during the set. Those four fields are
the moat. Everything else on the board is a commodity.

## 3. Who is already here, and where each one stops

| Player | Model | Where it stops for us |
|---|---|---|
| Bandsintown Pro for Venues | Free page; $150 per promoted email; size-priced premium | Serves ticketed rooms with a marketing person. A bar paying a duo $250 is not the customer. **$150 is the only hard willingness-to-pay anchor we have.** |
| Untappd for Business | $899–$1,199/yr for the beer menu | Owns "which beer is on." Do not rebuild. A beer-on-happy-hour search is a **join** between their public menu and our times. |
| BBK Music Seeker (locallivemusic.ai) | Scrapes venue calendars, Anthropic API fills gaps, AdSense | Proof the scrape works; proof ads do not pay for it. Lists West Chester PA as a market. |
| Do215 (DoStuff) | Promoter-fed city calendar, giveaways | City-center only. Does not reach Bridge Street. |
| Discotech | ~10% commission on tables/tickets/guest lists, 1,000 clubs, 50 cities | ~$7M gross / **$875K net** in 2019 after a decade. That is the ceiling of a pure commission model in nightlife. |
| Updown Nightlife (KC) | Local nightlife audience, 40K regulars | Acquired by BarGlance 2024 at a stated **$5M** after ten years. One loyal metro is worth about that to an acquirer. |
| Fever | Curated experiences, ticket margin, $724M rev | Proof packaged nights sell when someone assembles them. Not bar gigs. |

## 4. The economics that make a bar care

The 443 Social Club owner published his books. A $250 solo act needs about 61 drinks to
break even. Free shows lost money even with a full room; every local act now carries a
$5 door. Second-hand figures from a Bar & Restaurant piece (not fetched, see §7): checks
up 5–10% and revenue up ~25% on live-music nights.

So the venue's problem is not "get bodies in." It is **get bodies who stay and spend
through the set.** The happy-hour crowd that leaves at 7 is the wrong crowd. The crowd
that arrives at 6 because they know the band starts at 8 and dinner is in between is
the one that pays the guarantee. Nobody sells that crowd because nobody has the set time.

## 5. Revenue model, in the order it is earned

| Layer | Who pays | Why they pay | Status |
|---|---|---|---|
| Happy-hour listing | nobody, ever | it is the hook | live |
| Email list | nobody | the only asset besides the data that an acquirer values | **not built** |
| Event data (start, set, cover, kitchen) | nobody yet | the moat; must exist before anything below | **not built** |
| Event promotion | the venue | a $400 band in an empty room is a sunk cost | after data |
| Committed-group RSVP with a redemption code | venue per redeemed head, or a small cover we keep a cut of | guaranteed bodies on the night they feared; **it is also our sell-through measurement** | pilot with 5 bars on their deadest night |
| Cross-venue packages (drinks at A, band at B, late kitchen at C) | venues in the package | only after two venues on one block each have a redemption record with us | later |
| Discounted show tickets | ticketed rooms only (Colonial Theatre is the one in Phoenixville) | small bars have a $5 door, nothing to discount | later |

The exit, if there is one: an acquirer that can measure sell-through in its own POS or
reservation system (Toast, OpenTable, Untappd, Bandsintown) buying the bar-gig layer
none of them has, across several metros, with a redemption record that proves it moves
drinks. Updown's $5M for one loyal metro is the reference price.

## 6. Build order

1. **Close the happy-hour item gap first.** Still the standing failure. A night planner
   on top of a half-empty board is a shinier empty room.
2. **Turn on email signup.** Cheapest asset on the list.
3. **Ingest events by image and embed, not by API.** Point the per-venue agent lane
   (`ingest/agent_read_venue.py`) at the events image and the Facebook embed. Same
   tooling, new target. Prove one town's events correct for **four straight weekends**
   before adding a single feature. Phoenixville is the town.
4. **Ask venues for the four fields directly.** They already email set times to a
   booker (The Fenix routes bands through a gmail address). One form, one text a week.
5. **Fold `dead-shows` in as the first genre lane.** It has the geo, the Ticketmaster
   proxy, the daily refresh action, and an audience that already plans nights around
   bands. The Dead tribute circuit is exactly the bar-gig layer Ticketmaster misses.
6. **Reddit** the week one town looks full.
7. **Pilot the RSVP** with five bars. Charge per redeemed head. The number that comes
   out is the sales pitch for every other metro.
8. **Beer on happy hour** = join Untappd's public venue menu to our times. Do not
   build a beer database.

**Explicitly not building:** avatars, points, badges, bartender profiles, upvotes, beer
list upload. All retention polish. We do not have a retention problem; we have a supply
problem. Revisit only when a town has four correct weekends behind it.

## 7. Assumptions we are making that may not hold — research these before betting on them

Ranked by how much of the plan falls over if the assumption is wrong.

1. **That people plan nights ahead at all.** Paul's own anecdote was spontaneous: already
   in town, several hours, no plan. If the real behaviour is "what's on within walking
   distance in the next two hours," the product is a live board, not a planner, and the
   RSVP layer is much weaker. *Research:* ask 20 people on Bridge Street on a First Friday
   whether they knew the lineup before they arrived, and whether they would have booked.
2. **That the happy-hour crowd converts to dinner and a show at the same venue.** Happy
   hour customers bar-hop by nature, and most happy hours end (6 or 7) before most bands
   start (8 or 9). *Research:* we already hold happy-hour end times; ingest event start
   times and measure the overlap per venue. If the median gap is two hours the "same
   venue" story is wrong and the cross-venue package is the primary product, not a later
   one.
3. **That venues will give us set times.** The Fenix's own page says "7 to 10 pm" and
   nothing finer; bands often decide on the night. If set times do not exist as data
   anywhere, we cannot own a field that does not exist. *Research:* ask ten Phoenixville
   venues what they know at 3 pm on show day. Maybe the field is "doors + first set" and
   "second set" is unknowable.
4. **That a bar will pay per head.** The 443 numbers say margins are thin: a $5 cover on
   20 people is $100 and 10% of that is $10, below the cost of collecting it. Bandsintown's
   $150 per email campaign is the only observed price a small venue pays. *Research:* run
   the pilot as a flat fee per night first and discover the per-head number from
   redemptions, rather than pricing per head up front.
5. **That set time and cover are the missing fields, rather than "is there music
   tonight, yes or no."** The binary might deliver 80% of the value at 10% of the
   ingest cost. *Research:* ship the binary first for one town and see whether anyone
   asks for more.
6. **That event data can be kept correct weekly.** A menu is good for months; a lineup
   for a week. Rot rate is untested and a wrong events board dies faster than an empty
   one. *Research:* the four-weekend test in §6 step 3 is the measurement.
7. **That the $5M reference is real.** Updown's figure is a single press-stated
   acquisition number, terms unknown (cash vs stock), after ten years and 40K users.
   Discotech's net was under $1M/yr. The honest range from the evidence is "low single-
   digit millions for one loyal metro, and only to a buyer who wants the audience."
8. **That the Bar & Restaurant live-music numbers are real.** The page returned 403; the
   5–10% / 25% figures are second-hand from a search summary. *Research:* fetch the study,
   find who ran it and the sample, or drop the numbers from any pitch.
9. **That the dead-shows audience spills over.** Their radius is 100 miles for a tribute
   act; a happy hour is five miles. Different trip, possibly different person.
   *Research:* look at dead-shows' actual search radii in whatever logs the worker keeps.
10. **That Untappd's public menus can be joined freely.** Their ToS may prohibit scraping
    venue menus; Untappd for Business is a paid product and they defend it. *Research:*
    read the ToS before writing the join.
11. **That competing venues on one block will cooperate on a package.** They compete for
    the same Friday. *Research:* the First Friday organisers (Phoenixville First) already
    coordinate the block; start there, not venue-to-venue.
12. **That Facebook embeds on venue sites render without a login.** If Meta gates embeds
    the way it gated search on 2026-08-01, Twelve78's calendar goes dark to us too.
    *Research:* fetch the embed unauthenticated and check; if it fails, the image-read
    path is the only one left and the venue-supplied form in step 4 moves up the list.

## 8. Sources

- Bandsintown venue pricing — https://help.venues.bandsintown.com/en/articles/8487058-pricing
- Untappd for Business pricing — https://toolradar.com/tools/untappd-for-business
- BBK Music Seeker — https://www.locallivemusic.ai/
- JamBase Phoenixville — https://www.jambase.com/concerts/us/pennsylvania/concerts-in-phoenixville
- The Fenix events — https://thefenixbar.com/events/
- Twelve78 calendar — https://www.twelve78brewing.com/event-calendar/
- 443 Social Club, economics of live music — https://443socialclub.com/economics-of-live-music-in-small-venue-revisited/
- Bar & Restaurant live-music study (403, unverified) — https://www.barandrestaurant.com/operations/new-study-confirms-music-matters-bars-restaurants
- Discotech on Wefunder — https://wefunder.com/discotech
- BarGlance acquires Updown — https://startlandnews.com/2024/10/barglance-updown-nightlife-app/
- Fever revenue — https://getlatka.com/companies/feverup.com
- Do215 — https://do215.com/
- Apify Facebook events scraper (the Aug 1 gate) — https://apify.com/apify/facebook-events-scraper
- Phoenixville First Fridays — http://www.phoenixvillefirst.org/first-fridays

## 9. Coordination models — where a cut is earned (ideation, 2026-09-04)

Paul's filter: the venue must already want us for something **it controls** before the
set-time data shows up as a byproduct. Rank by "does the bar use this on a Tuesday with
zero consumers on our site," then by whether it produces a cut.

The venue's asset is **empty capacity at a specific hour**. The consumer's asset is
**certainty** (it will be good, I have a seat, my friends are coming). Prepay is what
certainty costs; a cut is earned wherever we turn certainty into committed demand at an
hour the venue could not fill. Pure discounts fail (Groupon); pure listings earn nothing.

| # | Model | Venue wants it before we have users? | Consumer value | Cut |
|---|---|---|---|---|
| 1 | **Booking inbox** — free calendar replacing the bands@gmail address; venue confirms act, time, pay, door; publishes to their site and to us | **Yes** — it is the mess they already have. The set time exists because the band enters it to be confirmed | the calendar | none at first; ~5% booking fee once bands apply through it (GigSalad) |
| 2 | **Tipping-point show** — "band plays Tue if 25 people prepay $10, credited to the tab" | **Yes** — funds the $250 guarantee before the venue commits (443 books) | zero risk: no tip, no charge | cut of what tips; we hold the money |
| 3 | **Prepaid tab windows** — "$20 buys $25 on the tab, 8–11 pm Thu" | yes — hour-by-hour yield control; steers the HH crowd into the band window | discount + no cash at the door | cut on prepay |
| 4 | **Seat hold with deposit** — $10 holds a table near the band, converts to first round | only on already-busy nights | the seat | cut on deposit |
| 5 | **Host model** — one person opens a night, invites eight, table confirmed when six prepay, host drinks free | needs 2 or 4 underneath | social certainty | cut on group prepay |
| 6 | **Block pass** — wristband sold through Phoenixville First: drinks at A, band at B, kitchen at C | the organiser wants a pass product | one purchase, no decisions | pass margin. This is how cross-venue happens without asking competitors to cooperate |
| 7 | **Band as scheduler** — redemption data gives each act a measured draw; venues book by draw, bands post set times to be counted | needs a year of data | better nights | booking fee |

**Sequence:** 1 + 2 together in Phoenixville, with venues that already book through a gmail
inbox. The inbox gives the calendar, the tipping-point show gives the first dollar and the
first redemption record, and both produce the start time as a side effect. 3–6 are each
one step on the same money rail. Stripe is already wired in `akumal-scooters`.

**Research before writing a line:** PLCB rules on prepaid drink credit and tipping-point
promotions (happy hour capped at 4 h/day, 14 h/week; some promotions banned outright), and
stored-value / gift-card law on unredeemed tab credit. Models 2 and 3 live or die on
whether "$10 prepaid, credited to the tab" is a regulated drink discount.

### 9a. Model 2, the tipping-point show — prior art and the band-side entry (2026-09-04)

**It has been done, and every version is dead:** Songkick Detour (2012, 10 beta gigs, folded
into ticketing), GigFunder (2011, Chicago, 30-day campaigns), Eventful "Demand It!" and
BringTheGig (Jonathan Coulton), Queremos (Brazil). All four were **fan pays the artist to
travel**: the band had to be big enough for strangers to pledge, the money bought a tour
stop, the venue was a passive line item. Touring-artist product, city-sized unit.

**Why the bar version is a different product:** the money is a **tab credit, not a ticket**,
so it flows to the venue's bar and the venue pushes it; the band is already ten miles away,
so nothing is funded except the $250 guarantee; and the crowd is **the bar's regulars, not
the band's fans**. That last one is the caveat: most cover bands have no draw of their own.
So the venue runs the campaign to its regulars, the band is the attraction, and the band's
own list is a boost. Two-sided promotion, which none of the dead ones had.

**What each side gets:** the band gets its dates seen and a **measured draw** (how many
tipped, which room, which night), the one currency a bar band cannot make alone and the
thing that gets it rebooked. The venue gets **a booking decision backed by pledges instead
of a guess**. The set list is the byproduct, not the value.

**Reaching bands is half done:** the venue calendars we ingest anyway name every act that
plays in a town. That is the roster. Match to a Facebook page; the free submit is "your
dates are already on our board, claim them and see your pledges." No cold directory.

**Test before building:** ask three acts off the Fenix calendar whether they would post a
pledge link to their own followers. If the answer is "the bar has the followers, not us,"
the venue runs the campaign and the band only confirms; the product stands, the first
screen is built for the owner instead of the band.

## 10. What is built, as of 2026-09-04

The rails, not the money. Deployed and smoke-tested live; see `worker/README.md`
for the route table and the operator commands.

| Piece | Where | State |
|---|---|---|
| Email list, double opt-in | `POST /subscribe`, `web/index.html` above the footer | **live**. Confirm link is sent only when `RESEND_API_KEY` is set on the Worker; until then rows wait `pending` with `mailed_at NULL` for a sender on the PC. **The sender script is the next piece and does not exist yet.** |
| Events table + public feed | `worker/schema.sql`, `GET /live/events.json` | **live, empty**. Patched onto cards like the deals overlay; carries start, set length, cover, kitchen. |
| Events reader | `ingest/read_events_venue.py` | **built, never run against a real venue.** Same grounding gate as the menu lane; rows land `pending`. |
| Venue magic link | `POST /admin/venue-token/<lid>`, `web/venue.html`, `POST /venue/events` | **live**. A venue's own rows publish on write. |
| `campaigns` / `pledges` | schema only | **reserved, served by nothing.** |

**The four-weekend clock has not started.** Nothing has been read off a real
calendar yet, so section 6 step 3 is still open. First run is Phoenixville:

```sh
python ingest/read_events_venue.py --zone phoenixville --show --rejects   # file only
python ingest/read_events_venue.py --zone phoenixville --post             # queue for review
```

**Two things to watch on that first run**, both untested: whether the reader
can see a Facebook embed at all (assumption 12), and whether a JPEG calendar
survives the grounding gate — the model must transcribe the picture before it
can quote it, which is the same path the menu lane took two sessions to get
right.

## 11. The night-out architecture, and what to know before debugging it

Written the session it was built (2026-09-04) so the next one does not have to
re-derive it. The shapes here are deliberate; each paragraph names the failure it
prevents.

### The pieces and where they live

```
worker/schema.sql      subscribers · events · venue_tokens · campaigns · pledges
worker/nightout.js     the whole layer: validator, fingerprint, feed, signup, venue form, admin
worker/index.js        routes only — it imports nightout.js and dispatches
web/lib.js             applyEvents · nextEvent · eventLine · validEmail   ← the tested half
web/app.js             loadEvents() · wireSubscribe() · the card line     ← paints only
web/venue.html         the magic-link form a venue fills in itself
ingest/read_events_venue.py   the agent reader and its grounding gate
tests/events.test.mjs         7 Node tests   ·  tests/test_events_reader.py   6 Python tests
```

### Six rules the code depends on

**1. The overlay is additive and idempotent, and a failed fetch changes nothing.**
`loadEvents()` patches the static bundle at runtime exactly like the deals overlay.
`applyEvents` keys on event id, so running it twice adds nothing and a re-fetch
cannot duplicate a night. If the Worker is down the board is simply the board — the
offline PWA story is untouched. **Never make a card's render depend on a live fetch.**

**2. Two sources, two trust levels, one table.** A row from `/venue/events` publishes
on write because the venue is the author of its own calendar. A row from the reader,
posted to `/admin/events`, lands `pending` and is invisible until a person approves
it. The upsert enforces this: `status = CASE WHEN events.status = 'pending' THEN
excluded.status ELSE events.status END` — **a re-read can never overturn a human
ruling**, in either direction. That one CASE is the safety property; the live smoke
test checks it, and any schema change must keep it.

**3. `eventFingerprint` is what stops a nightly re-read from stacking duplicates.**
`${lid}|${date}|${act}` with the act lowercased, `&` mapped to `and`, and every
non-alphanumeric stripped — so "Rhythm & Blondes" and "rhythm and blondes!" are one
night, not two. The id is derived, never generated; drop that and every calendar
re-read grows the table.

**4. Blank means unknown, never zero.** A venue that says nothing about cover is not
a venue with no cover. `eventFrom` maps an empty string to `null` and `eventLine`
omits the clause entirely, so the card says only what the source said. The line
renders "no cover" **only** for a literal 0. Same for `kitchen_open`. This is the
same rule the menu lane learned the hard way, applied before it could bite here.

**5. The Worker runs UTC and "tonight" does not.** `localToday()` uses
`toLocaleDateString("en-CA", {timeZone:"America/New_York"})`. Without it the feed
drops tonight's shows at 8pm Eastern, which is exactly when people look. Any new
date math on the server goes through that helper.

**6. The grounding gate is a substring test against the model's own transcript.**
`ground()` in `read_events_venue.py` drops any event whose `quote` is not in the
transcript after whitespace/case normalisation, plus anything outside the 14-day
window, an unknown `kind`, a clock that is not `HH:MM`, or a non-numeric cover.
It **drops, never repairs** — a half-understood row is worse than an absent one.
It re-reads anything older than six days because a calendar rots in a week.

### Traps this build already hit

- **A new live `fetch()` in `app.js` breaks every Playwright check at once.** The
  sandboxed test page refuses the cross-origin call and it surfaces as
  `uncaught page error: … due to access control checks`, which reads like a code
  bug and is not. **Any new endpoint the page calls needs a route stub added to
  `tests/{render,card_chrome,search,picker}_check.py`**, mirroring the
  `/live/deals.json` stub already there. Four files, same edit.
- **Touching `web/` without rebuilding fails a test that names none of the files
  you touched.** `test_ingest.ServiceWorkerCache` compares `sw.js`'s cache name to
  the hash of the shell. Run `python ingest/build_bundles.py`; never hand-edit `sw.js`.
- **Deploying is not shipping.** The Worker and GitHub Pages are separate deploys
  with separate lags, and only `master` publishes the site. Verify by fetching the
  live JS and running the live page, never by a 200.
- **R2 is not enabled on this account** (error 10042 is a dashboard billing opt-in),
  which is why menu photos live in `PHOTOS_KV`. Do not plan storage around R2.
- **`zone-<id>.json` is the board; `venues-<id>.json` is everything with NO
  window.** The names do not say so, and reading the wrong one returns a
  confident false answer rather than an error. It has cost two sessions:
  dead-shows joined against `venues-*` and reported "0 of 18 matched venues
  publish a happy hour" — necessarily true of a file defined as the venues
  with no window — and the same misreading produced "only 1 of 476 deal
  venues carries a coordinate", filed as a blocker on this project when 441
  of them had one. **Any consumer must read both, deal-bearing first.**
- **`#v=<lid>` alone is a dead link, and it fails silently.** The app boots only
  the zones' deal bundles; a venue with no published window arrives with its
  zone's *base*, which is fetched only when the hash names a zone. Without
  `z=`, `openVenue()` looks the id up in a list it was never in and returns —
  the reader lands on the default board and concludes the link is broken.
  **Share a venue as `#z=<zone>&v=<lid>`.**
- **The app reads the hash once, at boot.** There is no `hashchange` listener,
  so navigating between two of our own deep links inside one document changes
  `location.hash` and nothing else. Harmless for real links (they open a fresh
  document) but it will silently invalidate any browser check that reuses one
  page across several URLs — every result after the first describes the first.
  **Open a fresh page per link.**
- **The sw cache name could not see a build that changed a bundle's contents.**
  It was date + deal count + shell digest, so filling in 30 coordinates on the
  same day as the previous build produced an identical name and evicted
  nothing. It now covers the shipped data too (`data_digest`). If you add a
  build step that rewrites bundles, check the stamp actually moves.

### The one thing to check first when events do not appear

In order, because each step is cheap and rules out the one below it:
`GET /live/events.json` non-empty? → the row's `status` is `approved`? → the row's
`lid` matches a venue in the built bundle? → `applyEvents` present in the **live**
`lib.js`? A live-`lib.js` miss means a build or a deploy did not land, not a bug.

## 12. The two-way link with `dead-shows`, and the direction still missing (2026-09-05)

Step 5 of the build order ("fold `dead-shows` in as the first genre lane") is now
**half done**, and the half that exists is the cheap half.

**Built — shows → happy hours.** `dead-shows/scripts/link_happy_hour.py` joins its
835 GDTB events to our published bundles at **build time**, address-first and
city-gated, and writes `data/hhf-links.json` plus an `hhf` block on each event. A
show card can now say "happy hour until 6 nearby" and link to
`#z=<zone>&near=<lat>,<lng>&from=<venue>`, which sorts that town's board by
distance from the show's door. Neither static site gained a runtime dependency on
the other; the join is a file, not a fetch. 23 events matched on the first run.

**Not built — happy hours → shows.** A reader on our board cannot see what is on
after their drink. That is the direction the product thesis actually needs (§1: the
unit is a night, and the drink is the first hour of it), and it is the next design
session.

### What the reverse direction is really asking for

Three populations, and they are not the same problem:

1. **A local band or cover duo playing the bar you are already looking at**, during
   or just after the happy hour. **No aggregator has this** (§2). It lives in the
   venue's own calendar, as a JPEG or a Facebook embed, and it is the moat.
   `ingest/read_events_venue.py` is the tool and has still never been run against a
   real venue.
2. **A ticketed show in the same town** — the Colonial Theatre case. Ticketmaster's
   Discovery API carries these and `dead-shows/worker/worker.js` already proxies it
   on the free tier (5,000 calls/day). This is the population we can fill *today*
   without inventing anything.
3. **A tribute/genre circuit** — GDTB is one community directory that catches
   small-bar gigs Ticketmaster misses. There are others per genre. Cheap per genre,
   and each one is a lane, not a platform.

**Sequence follows cost, not value:** 2 is nearly free and proves the surface; 3
reuses a scraper shape we have already run daily for months; 1 is the expensive,
defensible one and should not be the thing that blocks the other two shipping.

### What carries over from `dead-shows`, and what does not

- **Carries over:** the build-time join (never a runtime cross-site fetch); the
  address-first, **city-gated** key — an ungated address key matched "101 Walnut St,
  Montclair NJ" to "101 Walnut St, Green Lane PA", and did in practice; a daily
  GitHub Action that refreshes data and commits back to master; a Worker that hides
  a third-party key from the page.
- **Does not carry over:** its audience radius. A tribute act pulls 100 miles; a
  happy hour is five. Assumption 9 in §7 is unchanged — **do not assume the
  dead-shows reader is the happy-hour reader.**
- **The trap that has now cost three readings:** `zone-*.json` is the board,
  `venues-*.json` is everything with **no** window. Any events consumer must read
  both, deal-bearing first, or it gets a confident false answer instead of an error.

### Fields, before anything is ingested

Whatever the source, a show row on our board has to answer the four fields from §2
(start, set length, cover, kitchen) and obey rule 4 of §11: **blank means unknown,
never zero.** A Ticketmaster row will have a start and a price and will not have a
set length or a kitchen; that is fine, and the card must say only what the source
said. `worker/schema.sql`'s `events` table and `eventLine` already enforce this —
a third-party importer writes into that same table, at the **`pending`** trust
level, and never invents a field to fill a column.

### The open design questions for that session

1. Does an event ride the **venue's card** (an extra line, like the deals overlay)
   or a **separate surface** ("tonight in this town")? The first is nearly free and
   only works for population 1; the second is where a ticketed show four blocks
   away belongs.
2. Are third-party rows written into `events` at all, or joined at render? Writing
   them means our table now holds data we do not own and must expire (a lineup rots
   in a week, §7 assumption 6); joining at render means a runtime dependency the
   offline PWA story forbids on the board itself.
3. What is the **radius**, and is it a walk or a drive? The whole value of "after
   your happy hour" collapses past about a mile on foot.
4. Which town proves it? §6 says Phoenixville for population 1. Population 2 may be
   better proven where a ticketed room and a dense bar block coexist — West Chester
   or Wilmington.

## 13. "What's on after" — the design, and the plan to build it (2026-09-05, night 4)

§12 asked four questions and left them open. This section answers them, adds a
fifth the survey turned up (Untappd), and ends in a build order. No code was
written for it; two things were *probed*, and both probes are recorded below
because each one changes the plan.

### 13.1 The answer to Q1: it is two surfaces, and the split is DISTANCE, not population

The tempting split is "population 1 on the card, populations 2 and 3 somewhere
else." That is wrong, because it makes the surface a property of where the data
came from, which is an implementation detail the reader cannot see.

The split the reader actually feels is **here vs. nearby**:

- **An event AT this venue is a line on this venue's card.** Already built —
  `nextEvent` + `eventLine` + the `.tonight` node in `app.js`. Nothing new is
  needed for this and nothing about it should change.
- **An event NEAR this venue is not a property of any card.** It is a property
  of the *town*. Putting "band at the Colonial, four blocks away" on the Iron
  Hill card is a lie about Iron Hill, and repeating it on all eleven West
  Chester cards is eleven lies.

So the second surface is **one strip per board, not per card**: *"Later tonight
in West Chester"*, at most three rows, below the board, each row a start time, an
act, a room, a distance and an outbound link. It appears only when the zone has
rows for tonight or tomorrow, and it is the natural landing place for the
`from=` link `dead-shows` already sends us — the reverse direction closes the
loop on the same rail.

This also means population 2 needs **no per-venue data model at all**. It is
zone-scoped. That is most of why it is the cheap one.

### 13.2 The answer to Q2: third-party rows do NOT go in `events`

Two reasons, and the first is decisive on its own.

**`events.lid` is `NOT NULL`.** A Ticketmaster row at the Colonial Theatre has
no `lid`, because the Colonial is not a licensed bar on our board. Writing it in
means minting a fake `lid`, and every consumer keyed on `lid` — `applyEvents`,
the admin queue, `events_lid` — then holds rows pointing at venues that do not
exist. The schema is telling us these are not the same thing.

**And §11 rule 2 is a safety property we should not dilute.** "Two sources, two
trust levels, one table" works because both sources are *statements about one of
our venues* — the venue itself, or an agent reading that venue. A Ticketmaster
feed is neither. It is a third party's assertion about a room we do not track,
and it rots on a different clock (§7 assumption 6).

**So: a third static file, built the `dead-shows` way.** `data/shows-<zone>.json`,
one per zone that has any, produced by a scheduled job, committed to master, read
by the page from its own origin. Never a runtime cross-site fetch; the offline
PWA story is untouched, and expiry is free because the file is rebuilt daily with
a 14-day horizon and simply stops containing what has passed.

The one crossing case: a ticketed show whose venue **does** match a board venue.
Then it may also render as that card's line — but it is still sourced from the
static file and still rendered through `eventLine`, so rule 4 (blank means
unknown) and rule 3 (`eventFingerprint` derived) hold unchanged. The match is
`dead-shows`' own address-first, **city-gated** key (`scripts/venuetext.py`), and
it is gated because an ungated address key has already matched Montclair NJ to
Green Lane PA in production.

### 13.3 The answer to Q3: half a mile is the walk, three miles is the cap

`dead-shows` ranks a 100-mile audience. That number must not travel here. A
reader who has just been told where to drink at 5 will walk to the 8 o'clock
thing or not go.

- **≤ 0.5 mi** — "a few minutes' walk". This is the band the strip is *for*.
- **0.5–3 mi** — "a short drive", shown only when the walk band is empty.
- **> 3 mi** — not shown. There is no fallback to a wider radius. An empty strip
  is the correct output for a quiet town, and widening a window to fill it is
  the failure mode already recorded on the fleet side.

Distance is measured from **the venue the reader last opened**, else from
`state.origin` (which `near=` already lets a link set). And distance **leads the
sort outright** — the `near=` session found that a distance term scaled over 200
miles lost to two confidence terms, so "Nearest" meant "best sourced". Any new
ranking here asserts the resulting order in a test, never the formula.

### 13.4 The answer to Q4: two towns, because they prove two different things

- **West Chester** proves population 2. It is an existing zone, it has a ticketed
  room and a dense bar block inside a quarter mile of each other, and the whole
  claim of the strip — "the show is a walk from your drink" — is either true
  there or true nowhere.
- **Phoenixville** proves population 1. Not because it is better, but because
  §2 already collected the evidence there on 2026-09-04 (the Fenix's JPEG
  calendar, Twelve78's Facebook embeds) and that read has still never been run.
  Running the reader anywhere else throws that away.

### 13.5 Q5, which §12 did not ask: Untappd, and what is actually reachable

Paul asked whether Untappd can be integrated free for general beer lists.
Three doors were checked. Two are shut and the third is wide open.

- **The v4 consumer API is shut.** 100 calls/hour per key by default, and new
  application registration is approval-gated to the point of being closed. It
  could not cover 2,116 venues even if granted.
- **The Untappd for Business API is shut *to us*.** Its token lives under the
  venue's own Premium account (`business.untappd.com/account`); every endpoint
  requires it; there are no public read endpoints. This is not a door we can
  open — but it is worth noting it is a door a *venue* can open for us, and we
  already mail venues a magic link (`venue_tokens`). That is a partner
  conversation, not an integration.
- **The venue's own published embed is open, keyless, and complete.** This is
  the find. When a bar puts an Untappd menu on its website, the page carries

  ```
  PreloadEmbedMenu('https://business.untappd.com', "menu-container", <loc>, <theme>)
  ```

  and one plain GET of

  ```
  https://business.untappd.com/locations/<loc>/themes/<theme>/js
  ```

  returns the **entire menu already rendered into the payload** — no key, no
  cookie, no second XHR, no browser. Proven today against location 39393,
  theme 153078 (a venue already in `data/agent_reads/108084`): 115 lines of
  menu, every item with its price, section descriptions, and a per-menu
  `Updated on Sep 2, 4:33 PM EDT` stamp.

  **It is not only beer.** That payload contained a section titled
  `HAPPY HOUR BITES` whose description reads, verbatim:

  > Join us for Happy Hour! Select $5 Draft Beers and $12 Cocktails.
  > Monday to Thursday | 4pm to 6pm

  That is a window, six priced items, and a freshness timestamp — HHF's core
  product, from the venue's own mouth, in one unauthenticated request. It is a
  better source than the JPEG-reading agent, and it is the only source we have
  ever had that stamps its own last-update time.

  Three things to know before building on it:

  1. **Discovery is our crawl, not an Untappd directory.** There is no way to
     ask Untappd "which venues near West Chester have a menu". The ids come out
     of the bar's own site, which we already fetch. The regex above is the
     whole detector.
  2. **Prevalence is unmeasured.** Five embeds turned up in the handful of pages
     `agent_reads` happens to have saved. That is a hit, not a rate. Sizing it
     across the 2,116 sites in `venue_sites.json` is a one-evening job and must
     happen before anything is designed around it.
  3. **The theme config carries `"show_events": false`.** UTFB has an events
     feature. Whether a venue that turns it on ships its band calendar down the
     same free payload is **unprobed**, and if it does it is a population-1
     source that costs a GET instead of an agent session. Probe it early; it is
     cheap and it could reorder everything below.

  One judgment call belongs to Paul, not to a session: this reads a widget the
  venue chose to publish on its own public page — the same act as the agent
  reader fetching that page — but Untappd's terms are Untappd's. Flagging it,
  not deciding it.

### 13.6 The build order

Cost first, exactly as §12 set out, with the Untappd lane inserted where its
evidence puts it.

**Step 0 — two spikes, one evening, no schema.** (a) Sweep `venue_sites.json`
for the `PreloadEmbedMenu` regex and report the real hit rate. (b) Pull one
venue known to run UTFB events and see whether events ride the theme payload.
Both write findings to the playbook and nothing else. **Nothing after this is
planned in detail until 0(a) returns a number.**

**Step 1 — the ticketed layer, West Chester.** A build-time script
`ingest/fetch_shows.py` calling Ticketmaster Discovery through a Worker route
that hides the key (mirror `dead-shows/worker/worker.js`; note its artist list
lives in *two* files that must be edited together — ours has no artist list, so
this trap does not apply, but the key-hiding shape does). Writes
`data/shows-<zone>.json`, 14-day horizon, geo-queried from the zone centroid at
3 miles. Then the strip in `web/`, reading that file. Gate: `tests/` asserts the
rendered *order* and that a >3 mi row never appears.

**Step 2 — the strip's own correctness.** UTC vs "tonight" (§11 rule 5 —
`localToday`), blank-means-unknown on price (a TM row has a price range and no
set length; the card says only what it said), and the walk/drive band copy.

**Step 3 — the Untappd lane**, scoped by what Step 0(a) found. If the hit rate
is material, a keyless fetcher becomes a *first-class source* for items and
windows — with its own `source_kind`, its `Updated on` stamp carried through as
real freshness, and rows landing `pending` like every third-party read.

**Step 4 — the genre circuit.** GDTB's shape, one lane per genre, reusing the
scraper we already run daily.

**Step 5 — population 1, Phoenixville.** Run `ingest/read_events_venue.py`
against the Fenix and Twelve78 for the first time. This is the moat and it is
last **on purpose**: it must not block the three cheap layers, and by the time
it runs, the surface it paints into already exists and is proven.

### 13.7 Rules this build inherits and must not rediscover

All from §11, each having cost a session already: blank means unknown, never
zero · a third-party row lands `pending`, never `approved` · `eventFingerprint`
is derived, never generated · the Worker runs UTC and "tonight" does not ·
`zone-*.json` is the board and `venues-*.json` is everything with **no** window,
so read both, deal-bearing first · and **any new endpoint the page calls needs a
route stub in all four browser checks** (`render`, `card_chrome`, `search`,
`picker`) or every Playwright run fails at once with what looks like a code bug.

Two more, newer: a `web/` change ships nothing until a **detached-worktree**
rebuild restamps `sw.js` in the same commit; and a browser check must open a
**fresh page per URL**, because the app reads its hash once at boot.

## 14. The first read, the first chips, and the gap between them (2026-09-05, night 5)

Night 4 designed §13. Night 5 built the top of it and found the one thing the
design did not name.

### 14.1 The reader works, and the hit rate is the finding

`ingest/read_events_venue.py` had never been run against a real venue. It has
now read one whole town, Wayne, and the numbers are the planning input every
later town should be sized against:

| | |
|---|---|
| board venues in Wayne | 14 |
| that publish a calendar we can read | **4** |
| grounded event rows returned | **28** |
| rows dropped by the grounding gate | 0 |
| cost | ~$7.47, about **$0.53/venue** |

118 North 15 rows, LaScala's Fire 6, Flip and Baileys 4, Black Powder Tavern 3.
**Roughly three in ten venues publish anything.** Budget a town read as
`venues × $0.53`, and expect two thirds of it to buy a clean "none" — which is
still worth paying for, because a clean "none" is what stops us re-reading.

Two things the reader needed before it worked at all:

- **It could not see most of the board's websites.** `population()` read only
  `venue_sites.json`; **33 of 471** published venues have no row there, 118 North
  among them, and the run printed "0 venue(s) to read" rather than an error. It
  now falls back to the shipped bundles (`bundle_sites()`, reading `venues-*.json`
  then `zone-*.json`, deal-bearing wins) and prints a loud skip line naming what
  it could not reach.
- **The turn budget, not the source, was the whole gap.** 118 North's page is
  755KB. At the default 14 turns the agent exhausted itself, returned nothing,
  and cost $0.67 for it. `HHF_MAX_TURNS=28` returned 15 grounded rows for $0.99.
  🛑 A `kind: "exhausted"` result is **not** evidence that a venue publishes
  nothing. Re-run it with a bigger budget before believing a "none".

### 14.2 The population is not bands, and that shaped the UI

The 28 rows are bands, DJs, **music bingo**, a **dollar drink night** and a
**historical dinner lecture**. Paul: *"All of those events are important, even the
bingo, trivia nights etc. we want all of that."* And then, on labelling: *"live
music is one thing, and events is another."*

So the board ships **two chips, not one**: `FILTERS.music` (`kind === "live_music"`)
and `FILTERS.events` (every other kind). A reader who taps "Live music" and is
handed music bingo reads that as the board being wrong.

🔑 **Both are `venueTest`, not `test`** — an event filter is a question about the
venue's calendar, not about a deal. `buildFeed` asks it **once per venue**, and
keeps a venue that has a band and **no published happy hour**. That bar is
exactly the one worth showing; asking the question per-deal would have silently
dropped it.

Also removed the same session: the **Sort** picker (three orders for a question
with one right answer, and the app already overrode it once it learned where the
reader was — `SORTS` stays as a table because `readHash` still honours an `s=`
on an older shared link), and the **Food deals / Drink deals** chips, which
nearly every window on the board matched and so removed almost nothing.
Added: a **State** picker (`All / PA / DE`) on the town line, backed by an
explicit `state` field on every zone in `data/zones.json` and carried into
`index.json` by `build_bundles.py` — derived from the zones, so a zone in a third
state needs no code edit.

### 14.3 🛑 The gap: a filter can ship ahead of the data it filters on

Paul selected **Live music**, all towns, no other filter, and got **zero**. That
is not a bug in the chip. `GET /live/events.json` returns `{"venues":{}}` on the
live Worker, because the Wayne read was run **without `--post`**: 28 grounded
rows sit in `data/events_reads.json` and have never touched the database.

Two half-lanes, and neither is finished:

```
reader → data/events_reads.json     ← DONE (28 rows, Wayne)
       → POST /admin/events         ← NEVER RUN   (needs --post)
       → a person approves          ← NEVER RUN   (rows land `pending` by design)
       → GET /live/events.json      ← returns {} today
       → app.js applyEvents         ← works, has nothing to apply
```

**The lesson, general:** an events row has to cross **four** boundaries (file →
Worker → human approval → overlay) and the UI is the fifth. Shipping the fifth
first makes an empty board that looks like a defect. When a new surface reads a
new source, the acceptance test is a **live fetch of the overlay**, not a green
unit test — the unit tests all passed, against fixtures.

§11's "one thing to check first when events do not appear" already listed
`GET /live/events.json` non-empty as step one. It was right. **Run it before
believing a filter is broken.**

### 14.4 What is still on file only

`--post` sends rows to `$SUBMIT_API/admin/events` with `ADMIN_TOKEN`, where they
land `pending`; `GET /admin/events?status=pending` lists them and
`POST /admin/events/review/<id>` rules on each. Until a person rules, the board
shows nothing — that is the design (a re-read must never overturn a human
ruling), not a delay to route around.

## 15. The four boundaries, and how a standing weekly show is represented (2026-09-05, night 6)

§14 found the gap and named it. This section closes it, and answers the design
question §14 left open: what a recurring show *is* in the schema.

### 15.1 The lane runs end to end now, and two defects were in the way

Wayne's 28 rows are `pending` → approved → live. `GET /live/events.json` carries
4 venues and 28 rows. Two things had to be fixed to get there, and **both were
invisible because this lane had literally never run**:

- 🛑 **There was no path from `data/events_reads.json` to the queue at all.**
  `to_post` was built *inside the read loop*, so only a venue read in this run
  could ever be posted. And `todo` skips any venue read in the last 6 days — so
  the handoff's own instruction, `--zone wayne_radnor --post`, would have read
  **zero** venues and posted **zero** rows, printing a cheerful summary either
  way. Re-posting what is already on file required `--force` and **$7.47 of
  re-reading to send rows that were already grounded on disk.**
  Fixed: `--post-only` posts what is on file, reads nothing, spends nothing.
  `post_row()` is now one function both paths call, so they cannot drift.
- 🛑 **Cloudflare's edge 403s `Python-urllib/3.x` before the Worker is reached.**
  The same request from `curl` is a 200. The reader now sends a real
  `User-Agent`. **A 403 here is not an auth failure** — the Worker returns 401
  for a bad admin token, so a 403 means you never got to it.

**The general lesson:** a lane with four boundaries (file → Worker → human
ruling → overlay) has four places to die, and the *last* one to be built is
usually where the bodies are. Verification is a **live fetch of the overlay**,
never a green unit test — every unit test passed, against fixtures, the whole
time nothing worked.

*(One unreproduced event, recorded not explained: the first-ever 28-row POST
returned 500. The same payload from curl, and from python a minute later, both
returned 200. Cold-start or a first-batch D1 hiccup; if it recurs, look there.)*

### 15.2 🔑 A weekly show is ONE row keyed on its WEEKDAY, expanded at read time

Flip and Baileys publishes *"Music Bingo — Thursdays 7pm-9pm"* and *"Dollar
Drink Night ... every friday"*. The reader returned those as **four dated
one-offs** inside its 14-day window. That is wrong three ways, and the third one
is fatal:

1. They go stale. Past the horizon the board forgets a show that runs every week.
2. They cost a re-read to refresh, forever.
3. 🛑 **The human ruling could never stick.** `eventFingerprint` was
   `lid|date|act`, so next Thursday's Music Bingo is a *different id*, and a
   different id lands `pending` again. Somebody would be re-approving Music
   Bingo **every week for as long as the bar runs it.**

**The decision: a weekly rule is a first-class row, and the deals side already
proved the shape.** A happy hour on this board *is* a weekly recurring rule —
`days + window`. Events invented a one-off-only model and walked straight into
the wall the deals half solved months ago. So:

| field | meaning |
|---|---|
| `recurs` | `NULL` = a one-off on `date`; `'weekly'` = every week on `date`'s weekday |
| `date` | the **first occurrence**. It carries the weekday; there is no separate `weekday` column to disagree with it |
| `until` | the last day the rule is **trusted**. Never open-ended |

- **`eventFingerprint` keys a weekly row on `weekly-<weekday>`, not on `date`.**
  One id for the life of the show, so one human ruling, and a re-read *refreshes*
  the row (pushing `date` and `until` forward) instead of minting a new one.
- **Expansion happens in the Worker, in `expandRecurring()`, not in the browser.**
  Deliberate: the page already renders a dated row, so a standing show needed
  **no `web/` change at all** — and a `web/` change is what costs a
  detached-worktree rebuild to restamp `sw.js`. Each occurrence gets a per-date
  `id` plus `rule_id`, so nothing downstream sees two rows sharing a key.
- **`until` defaults to `date + 35 days`** when the reader does not set one.
  Longer than the fortnightly re-read cadence, short enough that **two missed
  reads retire a show that quietly ended**. A stale standing claim is worse than
  a blank — the same rule as "blank means unknown, never zero", pointed at time.

The reader's prompt now asks for a rule when the venue states one ("Thursdays
7-9pm") and a date when it prints one ("September 11: Joe Miralles"). The
grounding gate validates `recurs` and carries it through.

🔑 **The tell was already in the evidence.** Music Bingo's quote is
`"Thursdays 7pm-9pm"` — **no date in it**. The model *derived* 9/10 and 9/17
from a rule. A dated row whose own quote contains no date is, by construction, a
derived date, and that is exactly what a recurrence rule looks like from the
outside. The grounding gate could learn to detect this rather than trust the
model to declare it — **not built, worth building.**

### 15.3 Still open

- **The fan-out to West Chester + Phoenixville launched before the recurrence
  prompt landed**, so its rows come back as dated one-offs. They are still
  grounded and still correct as one-offs; a targeted second pass with `--force`
  over just the venues showing a repeated act converts them, rather than paying
  to re-read a whole town.
- **Wayne's four Flip and Baileys rows are still dated one-offs on the board.**
  Correct for 14 days, wrong in shape. A `--force` re-read of that one venue
  (~$0.53) is the honest fix; hand-editing an approved row is not.
- **Nothing schedules this reader yet.** The cadence the `until` window is sized
  against — a fortnight — is a decision, not a cron entry that exists.
- **The four moat fields are still mostly blank** — start time is arriving, set
  length / cover / kitchen-open almost never. 🛑 Blank means unknown, never zero.

### 15.4 🚨 The events lane put one bar's whole night on another bar's card

Paul asked for "the correct name and a picture" on the 118 North card. There was
no 118 North card. What he was looking at was **The Blue Elephant's licence
wearing 118 North's entire identity.**

| lid | licence | door | actually |
|---|---|---|---|
| **105248** | `110 NORTH WAYNE LLC` | 110 N Wayne Ave | **The Blue Elephant Wayne** |
| **66143** | `JDM WAYNE INC` | 118 N Wayne Ave | **118 North** |

Two different buildings, eight house numbers apart. Lid **105248** was shipping:
its licensee's name ("110 North Wayne"), **118 North's website**, **118 North's
happy hour** (from a hand-read of `118northwayne.com`), and — as of this session
— **15 approved event rows read off 118 North's calendar.** All retracted.

**The mechanism, and it is the NIGHT4 defect wearing new clothes.** A hand-read
attached `118northwayne.com/menus#happyhour` to lid 105248 because the licensee
name *"110 North Wayne"* looks like a street-address version of *"118 North"*.
Nothing ever checked that guess against the **door number in the licence**, which
disagreed the whole time. NIGHT4 wrote the rule after Serum/Slow Hand — *"when a
join has a strong fallback key, ask what checks the primary path"* — and
`quote_names_another_door()` guards the **roundup** joiner. **The hand-read path
has no such guard.** Same bug, second door.

> 🔑 **The general rule, sharper: a licence is a DOOR, not a name.** Every join
> onto `lid` is a claim about a street address. When a name and an address
> disagree, the address is the licence and the name is a guess.

**And the events lane multiplies it.** A wrong happy hour is one wrong card. A
wrong *venue join* now also drags a calendar, so one bad join publishes fifteen
false claims about a restaurant that has no band — and each one had been through
a human approval that could not see the join underneath it. 🛑 **Approving a row
is not approving the venue it is filed under.** The queue shows the act, the
date and the lid; it does not show whether that lid is the right building.

**Fixed the NIGHT4 way — refuse, do not re-route.** 118 North's page, hand-read,
and events read were *removed* from 105248 rather than moved to 66143 on my own
authority. 66143 then earned its own identity through the normal mechanism:
Places resolved `JDM WAYNE INC → 118 North` at 118 N Wayne Ave, the site merge
gave it `118northwayne.com`, `build_venue_base.py` now names it **118 North**,
and 105248 correctly reads **The Blue Elephant Wayne**. Its happy hour and its
events are being re-read under the right lid.

**Still open here:** the hand-read path needs the door check
`quote_names_another_door()` already gives the roundup path — until it has one,
this is one hand-read away from happening again. And nothing in the review queue
shows the reviewer *which building* a row belongs to; the queue should print the
venue name and address next to the act.

### 15.5 The fan-out, and what three towns say about the shape of the data

| | Wayne | West Chester | Phoenixville |
|---|---|---|---|
| venues read | 14 | 48 | 40 |
| that publish a calendar | 4 | 14 | 11 |
| cost | $7.47 | $30.88 | $25.83 |
| per venue | $0.53 | $0.64 | $0.65 |

**~3 in 10 publish, and it is stable across three towns.** Budget a town at
`venues × $0.65`, not $0.53 — Wayne was the cheap one.

🔑 **The finding that reorders the roadmap: most of a bar's calendar is a
STANDING WEEKLY GRID, not a list of gigs.** Saloon 151 publishes eight weekly
shows; Kildare's seven. Of 105 grounded rows across the three towns, **38 are
weekly rules and 67 one-offs — and before collapsing, those 38 rules occupied
76 duplicate rows.** 118 North, an actual music room booking named touring acts
on named dates, is the **exception**, and it was the town we designed from.

**So recurrence was not a nicety, it was the majority case.** Saloon 151 went
from 17 rows to 8 — and those 8 are exactly the grid the bar prints.

### 15.6 🔑 Re-grounding beats re-reading: the transcript is already paid for

The fan-out launched minutes before the recurrence prompt landed, so 129 rows
came back as dated one-offs. Re-reading two towns to fix that is **$56**.
Instead `--reground` re-runs the grounding gate over the transcripts already on
file: **$0**, and it cannot invent anything, because `ground()` still checks
every quote against the transcript character for character.

> **The general rule:** when a gate changes, re-derive from the evidence before
> re-buying it. The expensive half of an agent read is the reading; the
> transcript is the asset, and it does not expire when our rules improve.

**Two signals decide a weekly rule** (`ingest/recurrence.py`, both tested):

1. **The quote states a rule and prints no date** — "Thursdays 7pm-9pm",
   "every friday". Both halves are required: "Sat Sep 05 ... Doors 7:00 PM"
   names a day *and* a date, and the date wins.
2. **The model expanded the same act onto the same weekday twice, and no quote
   in the group carries a date.** 🛑 **Signal 1 alone under-detects badly** — it
   caught **1 of Saloon 151's 8** standing shows, because a model `quote` is a
   narrow slice ("Quizzo Starts at 7pm") while the "Mondays:" heading that makes
   it a rule sits one line above, *outside the quote*. But a 14-day window holds
   each weekday twice, so the model's own duplication **is** the evidence of the
   rule it read. Signal 2 took Saloon 151 from 1 to 8 and Kildare's to 7.

### 15.7 🛑 Two concurrent reads silently lose each other's work

`read_events_venue.py` holds `_lock` around `save(READS, reads)` — but that lock
is **per process**. Two runs at once each hold a whole-file copy in memory and
each writes it back, so the last one to finish erases the other's venues. It
happened twice this session: the 118 North read was wiped by the fan-out mid-run,
and a venue I had deliberately deleted was **resurrected** from the fan-out's
stale copy. The rows survived only because they had already been `--post`ed.

**Nothing is fixed here yet.** Until it is: **do not run two readers at once**,
and after any concurrent run, re-check the file rather than trusting it. The
same shape is in `fetch_og_images.py` (`data/venue_photos.json`) and in every
other whole-file `load`/`save` pair in `ingest/`.

### 15.8 🛑 The queue shows the act. It does not show the building.

A reviewer approving 15 rows saw acts and dates and lids — never a venue name or
a street address — so the wrong-venue join in §15.4 was invisible at exactly the
moment a person was asked to rule on it. **`GET /admin/events` should join the
venue's name and address onto every row.** Not built.
