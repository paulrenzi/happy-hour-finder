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
