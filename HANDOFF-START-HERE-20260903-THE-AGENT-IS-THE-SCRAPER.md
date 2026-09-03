# The agent is the scraper — 2026-09-03

**Supersedes `HANDOFF-START-HERE-20260902-THE-SCRAPER-IS-THE-JOB.md`.** Its §0a
(33 days, 70 commits, single digits) still stands as the record of why.

## 0. Paul, verbatim, 2026-09-03

> "it seems to me that you are trying to build a scraper, and we need an ai
> agent … it seems to me we cannot scrape websites with a bot. it requires an
> actual AI agent hand scraping each happy hour menu"

> "your answer over the last 2 days being the same: 'we have the image, but
> nothing looked at it.' … i never want to hear it again."

He was right on both. This document is the answer and the new process.

## 1. The venue he pointed at, and what actually happened

`https://www.thegreeneturtle.com/location/christiana/` — licence `DE6779bbc094`,
Newark DE. A person finds the happy hour in three moves: open the location
page, press the button that says **Happy Hour Menu**, look at the JPG. It is a
full menu: Monday–Friday 3–6, $3 shots, $5 cocktails, $7 bites, 23 items.

What the pipeline did:

| step | what happened |
|---|---|
| crawl, 09-02 21:10 | reached the page, captured the JPG into `crawl_hits.menu_images` — **correctly** |
| image reader | last run 09-02 **20:45**, before that crawl. Never re-run. Of **152** captured menu images, **141 had never been read** |
| image reader, run by hand 09-03 | model read all 23 items correctly; `verify()` **refused every one** — "price 3 not written in the evidence" — because the price is printed once in a circle over each column, not on the item's line |
| build | folded the Christiana licence into the Main Street card ("same name, same source page" — both read the chain's one corporate page). **The venue had no card.** |

So "we have the image, nothing looked at it" was true four times over, and
each time a session read one image by hand and moved on, because the process
was fourteen hand-typed commands in a markdown file with regex gates between
them. Nothing ran them, nothing failed when one was skipped.

## 2. What was built — one model call per venue, with hands

`ingest/agent_read_venue.py`. One `claude -p` session per venue with the tools
a person uses — **WebFetch, curl, Read** — and nothing that writes. The prompt
is "find where this venue states its happy hour, follow the link, download the
PDF or picture, look at it, transcribe it, read the deals out of the
transcript." The code keeps only the jobs it is good at:

- the **grounding gate**: every item's `quote` and `price_quote` must be
  character-for-character in the model's own transcript (`ground()`), then
  `verify()` re-reads the digits out of that span;
- the **PA/DE validators**; `happy_hour` deals only;
- **items only, never a window** — same rule as the other sidecars;
- a **human review** before anything ships, as before.

Proof, on the venue Paul named and no other:

```
[1/1] The Greene Turtle Sports Bar & Gri   image 26 item(s)  $0.34 6t
      https://images.getbento.com/.../17536TGT_Corp26_HappyHour_Aug20.jpg
```

Six turns, no venue-specific code, 26 items through the gates, on the card,
live: `python tests/live_front_door.py newark_de`.

Three defects fixed on the way, each of which would have hidden the result:

1. `extract_menu_images.py` / `extract_photo_deals.py` — **price bands.** The
   menu prompt now asks for `price_quote` (the span where THIS item's price is
   printed — its own line, or the header/badge over its group) and verify()
   accepts it when it is in the transcript. Greene Turtle: 0 → 21 items.
2. `build_bundles.py` — **a chain's page is not one bar.** "Same name, same
   source page" now also requires the same street number + ZIP before it
   merges; two branches six miles apart stay two cards.
3. `build_bundles.py` — `norm_addr()` could not read `180B Mill Rd` (returned
   the ZIP as the house number). Fixed; P.J. Whelihan's / Oaks Cinema still
   merge as one building.
4. Sidecars keyed by slug collide for two branches of a chain in one town —
   the agent sidecar is keyed by **licence id** and `build_bundles` attaches it
   by licence.

## 3. THE PROCESS for scraping websites in bulk, going forward

**One command per town. The agent reads; the code checks; a person approves.**

```
python ingest/agent_read_venue.py --zone <zone> --show --rejects   # the agent lane
python ingest/build_bundles.py                                     # items onto cards
git commit && git push                                             # deploy (GH Pages)
python tests/live_front_door.py <zone>                             # "it is live"
```

Rules:

- **Scoped runs only.** `--zone` or `--lids`. Never the corpus.
- **Two sessions at a time** (`--workers 2`). Three lost a quarter of reads to
  `claude -p` exit 1 and hid a real hit; an errored read is **not a zero** —
  the lane retries anything with `error` on the next run.
- **Cost** is subscription-metered: ~$0.35 of model time and ~1 minute per
  venue with a menu picture; less for a text page or a miss. A town of 100
  venues with websites is roughly an hour and $20 of metered time.
- **The existing lanes are not deleted.** The deterministic extractor still
  owns the **window** (the agent's window reading is kept in
  `data/agent_reads.json` as evidence for a future decision). The regex crawl
  still runs discovery and the "asking to be filled in" list.
- **Never say "we have the image, nothing looked at it."** If that is ever
  true again, the fix is not to read the image — it is to find which step of
  the four above was skipped and make it fail loudly.

## 4. What is NOT yet proven

- One venue. The lane has read The Greene Turtle Christiana and nothing else.
  The next session's first job is **one town** (`--zone newark_de`, 9 other
  captured images sit unread there) and the human minute on the result.
- The agent's **window** readings are recorded, not published. Whether a
  venue with NO deterministic window may take the agent's is Paul's call.
- WebFetch obeys robots and refuses some hosts; the agent then has curl. What
  it does on a JS shell (McGlynn's class) is untested.
- `data/agent_reads/<lid>/` holds downloaded menus; gitignored.

## 5. Standing rules — still in force

- Scoped runs only. "It is live" is one command. Prove it on one town for a
  dollar before a sweep. Never write a backslash escape through a bash heredoc.
- A wrong item is worse than a miss. The grounding gate and the reviewer are
  not optional.
