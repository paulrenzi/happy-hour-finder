# Happy Hour Finder

**Live: <https://paulrenzi.github.io/happy-hour-finder/>**

One question, answered fast: **where can I get a drink deal near me, right now?**

A mobile-web PWA covering the western Philadelphia suburbs and northern Delaware.
No framework, no build step, no CDN — the site is static files in [`web/`](web/),
and the "what's on right now" math runs in the browser over a cached bundle, so it
works with no signal in a parking lot or a basement bar.

**Standalone project.** Its own `.env`, its own deploy, no shared code or
credentials with anything else on this machine.

---

## Where it stands (2026-09-03, evening)

| | |
|---|---|
| zones (named drinking districts) | 44 |
| licensed venues known — the denominator | 3,415 |
| …with a website we know of | 1,778 |
| …crawled | 1,585 |
| **on the board with a published happy-hour window** | **332** |
| …carrying items you can actually order | 234 venues, 1,509 items |
| …with an hour but **no items** — the open gap | **98** |
| published windows that contradict their own evidence | **0 of 351** |

**Read that table in two halves.** What we publish is checked: every window and
every price has to appear in a sentence on the venue's own page, and the test
suite re-checks all 333 against the quote they came from on every run
(`tests/window_quote_check.py`). What we *don't* publish is not checked at all —
nobody has ever measured how many real happy hours the pipeline walks past.
Every miss found so far was found by a person, not by a run.
**Trust the cards. Do not trust the silence.**

### The open problem, and how it is now worked: something reads each venue

**98** venues publish an hour and no items. For 33 days a regex crawler plus
fourteen hand-run commands tried to close that gap and moved it by single
digits. The fix was never a better parser — it was **letting something that
understands a page open the page**, the way a person does: fetch it, follow the
Happy Hour link, download the PDF or the picture, look at it.

Two lanes now do that, and the difference between them matters:

- **`ingest/agent_read_venue.py`** — a model session per venue, unattended.
  Cheap and scalable; on the towns measured it returned an item on **8%** of
  the venues it read, and its output is **items only**.
- **A hand read** — the session itself opens the site and writes one record
  into `data/agent_handread.json`. Slow, but it carries the **window as well as
  the items**, so it can publish a venue no crawler ever parsed hours for.
  28 venues, 203 items, landed this way on 2026-09-03.

The code keeps the jobs code is good at either way: every price must be found
character-for-character in the source the read cites, the PA and Delaware
validators run, and a person reviews before anything ships.

Current state and what to do next:
[`HANDOFF-START-HERE-20260904-HAND-READS-PUBLISH.md`](HANDOFF-START-HERE-20260904-HAND-READS-PUBLISH.md).

---

## How it works

```
data/zones.json         44 named districts, hand-maintained — the source of truth
   ↓ ingest/seed_plcb.py        + seed_places_de.py
data/venue_base.json    3,415 licensees, the denominator (regenerate, don't edit)
   ↓ ingest/discover_places.py  find each venue's website        ← the paid step
   ↓ ingest/build_venue_base.py carry those websites onto the board
   ↓ ingest/crawl_sites.py      robots-honouring crawl → data/crawl_hits.json  (the WINDOW)
   ↓ ingest/agent_read_venue.py an agent reads each venue's menu → data/deals_agent.json  (the ITEMS)
   ↓ ingest/build_agent_venues.py a hand read → data/deals_agent_venues.json  (WINDOW *and* items)
   ↓ ingest/validate_pa.py      PA Acts 57 & 86 of 2024 — a failing deal never ships
   ↓ ingest/build_bundles.py    → web/data/zone-*.json  (and restamps web/sw.js)
   ↓ git push → GitHub Actions → live site
```

Two lanes feed the board. The deterministic crawl still finds the **window**
(the hours) and the "asking to be filled in" list. The agent finds the
**items** (what you can order and at what price). Every read is recorded in
`data/agent_reads.json`: the URL it read, every fetch it made, the transcript,
and what it cost.

In the browser the split is strict: [`web/lib.js`](web/lib.js) holds **all** pure
logic — feed assembly, grouping, ranking, freshness decay, time math — and is the
part under test. [`web/app.js`](web/app.js) only paints the DOM. Keep that split;
it is why the logic is testable without a browser.

### The process for one town — four commands, in order

```
python ingest/agent_read_venue.py --zone <zone> --tier A --show --rejects   # the agent reads
python ingest/build_bundles.py                                              # items onto cards
git commit && git push                                                      # deploy
python tests/live_front_door.py <zone>                                      # "it is live"
```

All four, in order, or the fix exists only in the source. One town at a time,
never the corpus. Two agent sessions at a time (the default) — three lost a
quarter of its reads. Anything the agent found but the gates refused prints
under `--rejects`.

**Pick who gets read: `--tier`.** Reading every website in a town costs the same
per venue whether or not there is anything there to read, so a run is ordered by
the evidence already on disk:

| tier | what we already hold on the venue |
|---|---|
| **A** | the crawl captured a menu image and nobody ever read it |
| **B** | the crawl quoted happy hour on one of its pages |
| **C** | a website, and no sign of a happy hour anywhere |

`--tier` implies `--needy` (skip venues whose card already carries items).
**Run A, look at what it returned, then decide whether B is worth buying.**
Measured on newark_de: tier C was 118 of 153 venues — three quarters of the
money — against the population that publishes no price anywhere.

Cost is real and recorded per venue in `data/agent_reads.json`. Budget roughly
$0.35 and a minute for a venue with a menu to read; a venue with nothing costs
less, and one that wanders a chain site can cost more.

⚠️ **The stranding gap, and the way out.** `agent_read_venue.py` writes into a
**sidecar** (`data/deals_agent.json`), and a sidecar can only fill items into a
deal some earlier pass already built. A venue with no crawled **window** has no
deal row, so its paid-for items strand — silently, no error. Two thirds of the
lane's reads stranded this way.

**A hand read is the way out, because it carries the window too.** Write one
record per venue into [`data/agent_handread.json`](data/agent_handread.json):

```json
{"lid": "DE608516193f",
 "url": "https://the-venue-s-own-page",
 "read_on": "2026-09-03",
 "quote": "the venue's own words, verbatim, containing the hours and the prices",
 "days": [1,2,3,4,5], "start": "16:30", "end": "17:30",
 "items": [{"category": "draft", "label": "Draft beer", "amount_off_usd": 1.0}]}
```

Then `python ingest/build_agent_venues.py && python ingest/build_bundles.py`.
That builds a **whole venue row** — nothing needs to already exist — and it
enters the merge at rank 2, above every machine pass and below a person's seed
and an approved photo. Omit `items` and it picks up whatever the agent lane
already banked for that licence, which is how stranded items get rescued.
Use `windows` instead of `days`/`start`/`end` for a venue whose happy hour runs
from open (a different clock each day). Never edit
`data/deals_agent_venues.json` — it is generated.

The older window lane (`crawl_sites.py` → `extract_deals.py`) still runs when
a town needs its hours found; its full recipe is in
[ARCHITECTURE-MENU-INGEST.md](ARCHITECTURE-MENU-INGEST.md).

### Discovery is its own chain, and it is two commands

A website Google finds reaches the board only through the base, so a discovery
pass that stops early is **invisible rather than wrong** — no error, just a
smaller board:

```
python ingest/discover_places.py --zone Z                        ← the paid resolve
python ingest/discover_places.py --zone Z --merge-sites --execute
python ingest/build_venue_base.py                                ← then the five gates
```

`--merge-sites` returns *before* the resolve pass runs, so both flags in one
command only merges what a previous run resolved. Skipping `build_venue_base.py`
leaves discovered venues with no `website`, which blinds `ingest/needy.py` — the
selection instrument for every scoped run.

---

## Running it

```sh
# the site — any static server, no build
python -m http.server -d web 8000

# every test in the repo — this is the gate the deploy depends on
bash tests/run.sh

# "is it live?" is ONE command, and nothing else counts
python tests/live_front_door.py newark_de
```

A local render, a green aggregate and an HTTP 200 are each blind to the thing
that actually breaks. `live_front_door.py` fetches the real site, paints it in a
real browser engine and names the venues it can see. One `NOT LIVE` is usually
GitHub Pages lag (~1 min) — re-run before diagnosing.

Verify in **WebKit as well as Chrome**. WebKit has discarded CSS that Chrome drew.

---

## Rules worth knowing before you change anything

**1. Ranking is on *usable* minutes** (`until − drive`, capped at ~2h), with
driving weighted above deal-time. Sorting live deals by least-time-remaining — the
naive reading of "urgency" — puts on top the bar you have the least chance of
reaching.

**2. The feed never dead-ends.** It searches forward up to 7 days. Before that it
was blank roughly 18 hours a day, which is most of when a person opens it.

**3. A day you pick is not a time you picked.** Choosing "Tomorrow" used to anchor
the clock at 5pm, and the anchor is also a cutoff — so it silently hid every
lunchtime deal and then made present-tense judgements ("live now", "you can't get
there in time") about a day that had not started. A future day is anchored at
00:00 and grouped in *planning* mode, and every hit carries its own absolute
`dateKey` so a label can never drift with the anchor.

**4. Structured beats prose, always.** A restaurant that wants to be in Google's
results publishes its menu in schema.org — dish, price, section, often the window.
That is better evidence than any sentence, and it is not always in a `<script>`
tag: plenty of sites ship it as an escaped string inside their front end's boot
state. **Ask the page for its data before you read its prose.** The full rule, the
three ways McGlynn's Pub broke it, and the prose-vs-structured argument are in
**[ARCHITECTURE-MENU-INGEST.md](ARCHITECTURE-MENU-INGEST.md)** — read it before
touching `crawl_sites.py`, `read_menus_llm.py` or `extract_deals.py`.

**5. Prefer a rule that refuses loudly over one that filters.** A whole class of
bugs here share one shape: a valid item is dropped and nothing raises an error, so
the board just quietly has less on it. When an item is missing and no log
complains, look for a silent drop first.

**6. Scoped runs only — one town, finished, on the live site.** Never the corpus.

---

## Non-negotiables

1. Never display a deal that fails a PA legal validator — it is bad data by definition.
2. Never render a claim the source didn't make.
3. Always show verification age and link the source. Deals **decay**; they never silently vanish.
4. Honor `robots.txt`; rate-limit crawls to something a small restaurant's host won't notice.
5. Strip EXIF from every stored image. Never background-track location.
6. No paid placement in the "right now" feed, ever.
7. No login to browse, no login to submit a photo.

## Traps that have each cost a session

- **A `web/` edit ships nothing until `build_bundles.py` restamps `web/sw.js`.**
  The cache name *is* the shell hash and the only eviction trigger. Never hand-edit `sw.js`.
- **A chain's `/locations` URL is not a page — it is a redirect to one branch.**
  The crawl records where it **landed**, not only what it asked for, and refuses a
  landing whose path names another town. Before that guard, a bar in Bear, DE
  published Newark's happy hour and every downstream check passed.
- **Run a new guard against the real data before believing it.** The town reader
  above parsed no Delaware address at all on its first run, so it had an empty
  vocabulary and returned a confident "fine". A guard that cannot see the thing
  is not green — it is blind.
- **A step done by hand to diagnose the pipeline is an autopsy, not a test.**
  The proof of a lane is a run of the lane; `data/agent_reads.json` records every
  fetch the agent made so a reader can tell the two apart afterwards.
- **Never run two crawls at once**, and no `git merge`/`pull` during a crawl.
- **Never write a backslash escape through a bash heredoc** — the patch reports
  success and the file is unchanged. Use an editor tool.
- `open(p, "w")` truncates before `write()` — write `.new` and `os.replace`.
- **Pull before push.** Codex works in this repo too.
- This repo's `.env` has no `ANTHROPIC_API_KEY` and must never borrow another repo's.

## Design

Cream `#f7f3eb` page, teal `#0a8a9e` accent, Fraunces display over Manrope; fonts
are **self-hosted** in [`web/fonts/`](web/fonts/) and precached, so the look costs
nothing in offline capability. Phone is the target (≥44px taps, single column,
geolocation on an explicit tap only); desktop is the courtesy fallback. There is
deliberately no map.

## Where the documents are

- **[ARCHITECTURE-MENU-INGEST.md](ARCHITECTURE-MENU-INGEST.md)** — how a menu
  becomes items, every known class of failure, and the findings that cost a
  session each. The one to read before changing ingest.
- **[SPEC.md](SPEC.md)** — what a deal is, and the eight categories.
- **`HANDOFF-START-HERE-*.md`** — session notes, newest wins. The current one is
  [`HANDOFF-START-HERE-20260904-HAND-READS-PUBLISH.md`](HANDOFF-START-HERE-20260904-HAND-READS-PUBLISH.md).
