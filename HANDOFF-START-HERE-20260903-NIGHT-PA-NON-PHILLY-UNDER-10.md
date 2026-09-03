# PA non-Philly, under-10 zones — 2026-09-03, night

**Supersedes `HANDOFF-START-HERE-20260904-HAND-READS-PUBLISH.md`** for what to
do next. That document's architecture section still stands — read it if you
need the hand-read record schema or the discovery ladder; this file only
replaces its "where to pick up."

## 0. What just landed (verified live, not self-reported)

Two nights, worktree `hhf-menus30` (branch `menus30`) — the main checkout
(`happy-hour-finder`, branch `dollar-off-discounts`) is held by another
session, work here stays in this worktree, push via
`git push origin menus30:master`, never a plain `git push origin master`.

| zone | before | after | delta |
|---|---|---|---|
| wilmington | 0 | 39 | +27 hand-read (15 then +12; board also carries other sources) |
| newark_de | 6 | 31 | +18 hand-read across newark_de + new_castle_de combined |
| new_castle_de | 0 | 5 | +5 |
| west_chester | 8 | 24 | +16 |

Confirmed live tonight with `python tests/live_front_door.py <zone>` for all
four — 39/39, 31/31, 5/5, 24/24 named live. Not a build claim, not the
agent's own say-so — this session ran the check itself.

West Chester's ask was +15 stretch; it landed +16 total across two rounds but
several strong candidates (Slow Hand, Stove & Tap, Roots Cafe, Andiario, dolce
Zola) hit a genuine wall: full menu found, **no clock time anywhere in the
venue's own words** — `validate_deal()` correctly refuses a windowless deal,
and that refusal is not a bug to work around.

## 1. Next goal — Paul, verbatim

> "Next session we focus back on PA, with a focus on non Philly areas with
> under 10 entries. Shoot for 5 each, 10 in Manayunk."

**Manayunk is the priority — 1 venue on the board today, target 10 (+9).**
Then every other non-Philly PA zone under 10 entries, +5 each, same ladder as
the DE push. Philly-proper zones (`north_philly`, `south_philly`,
`west_philly`, `university_city`, `fishtown_kensington`, `northeast_philly`,
`northwest_philly`, `center_city`) are **out of scope** this round — Paul said
non-Philly.

## 2. The target list (current counts, non-Philly PA, under 10)

Ranked by count, ties broken by whatever's fastest to read first. Priority
zone at top, then the rest in ascending count order (0-count zones may need
`discover_places.py` first — see §4):

| zone | current | target (+5, Manayunk +9) |
|---|---|---|
| **manayunk** | **1** | **10** |
| audubon_eagleville | 0 | 5 |
| springfield_delco | 0 | 5 |
| chester_chichester | 1 | 6 |
| havertown | 1 | 6 |
| norristown_bridgeport | 1 | 6 |
| ridley_tinicum | 1 | 6 |
| upper_darby_lansdowne | 1 | 6 |
| ambler_upper_dublin | 2 | 7 |
| limerick_royersford | 2 | 7 |
| pottstown | 2 | 7 |
| souderton_harleysville | 2 | 7 |
| abington_jenkintown | 3 | 8 |
| malvern_great_valley | 3 | 8 |
| warminster_warrington | 3 | 8 |
| collegeville_trappe | 5 | 10 |
| glen_mills_chadds_ford | 5 | 10 |
| lansdale_montgomeryville | 5 | 10 |
| newtown_square_broomall | 5 | 10 |
| conshohocken | 6 | 11 |
| doylestown | 6 | 11 |
| blue_bell_plymouth_meeting | 7 | 12 |
| ardmore_bryn_mawr | 9 | 14 |

Re-count any zone before starting — this table is from tonight, not the day
you read it. One line:

```
python3 -c "
import json,glob
for f in sorted(glob.glob('web/data/zone-*.json')):
    z=f.split('zone-')[1].split('.json')[0]
    d=json.load(open(f,encoding='utf-8'))
    print(len(d.get('venues',[])), z)
" | sort -n
```

Don't try to clear the whole list in one session — Manayunk to 10, then as
many +5s as fit. Report honestly what shipped, same as tonight's DE report.

## 3. The ladder (unchanged, proven twice now)

1. `python ingest/sweep_site.py <url>` — raw site text; catches what
   WebFetch's summarizer drops. **Prefer this over a bare WebFetch call.** If
   the snippet looks thin and the site is obviously JS-rendered (Next.js,
   React — check for a build manifest / `__NEXT_DATA__` in the raw HTML), do
   a raw fetch instead (`urllib.request.urlopen(url).read()`) — that's what
   surfaced Slow Hand's full menu tonight when `sweep_site.py` returned almost
   nothing.
2. Guess a Popmenu-style URL: `/<town>-<venue>-happy-hours-specials`.
3. A menu PDF: `python ingest/pdf_to_png.py menu.pdf out/`, then Read the PNG
   (poppler isn't installed — Read can't open a PDF directly).
4. A posted menu image/JPEG.
5. A targeted web search for the venue's own deep page.
6. The venue's own Instagram.

Write straight into `data/agent_handread.json` (a JSON list). Schema:

```json
{
  "lid": "...",
  "url": "https://...",
  "read_on": "2026-09-04",
  "heading": "Happy Hour",
  "clock_quote": "the venue's own sentence naming the days/hours",
  "quote": "the venue's own words for the deal",
  "days": [1,2,3,4,5],
  "start": "15:00",
  "end": "19:00",
  "items": [
    {"category": "Food", "label": "...", "price_usd": 10, "evidence": "..."}
  ]
}
```
Irregular days: replace `days`/`start`/`end` with
`"windows": [{"dow": 2, "start": "...", "end": "..."}, ...]`.
Omit `items` entirely to adopt whatever's already banked in
`data/deals_agent.json[lid]` (rescue path — check that file for the lid
first if a venue looks familiar from an earlier crawl).

Then:
```
python ingest/build_agent_venues.py
python ingest/build_bundles.py
python tests/live_front_door.py <zone>      # after push, not before
```
Commit, push (`git push origin menus30:master`), re-check live (allow ~1 min
Pages lag before treating a `NOT LIVE` as real).

## 4. If a zone is at 0 and has no candidates in `venue_base.json`

`audubon_eagleville` and `springfield_delco` are 0 — check whether that's
"no venues seeded" or "seeded, none read yet":
```
python3 -c "
import json
d=json.load(open('data/venue_base.json',encoding='utf-8'))
print(sum(1 for v in d if v.get('zone_id')=='audubon_eagleville'))
"
```
If the denominator itself is thin, `ingest/discover_places.py --zone <z>
--dry-run` then (Paul's call before spending) `--execute` resolves websites
for venues already in `venue_base.json` — it does **not** invent new venue
names. If a real bar in that zone isn't in `venue_base.json` at all, that's a
PLCB/seed gap, out of scope for a hand-read session; flag it, don't chase it.

## 5. Standing rules — unchanged, still binding

- 🛑 A venue counts only when its items are visible in **the live JSON under
  its own name** — `tests/live_front_door.py <zone>`, nothing else. A local
  build, green tests, and an HTTP 200 are all blind to it.
- 🛑 A wrong item is worse than a miss — never infer a window or price; a
  venue's own words only, never a third-party roundup/listicle.
- 🛑 Never write a backslash escape through a bash heredoc — use Write/Edit
  for any patch containing one.
- 🛑 `agent_read_venue.py` (the unattended per-venue model lane) is still a
  sidecar and still strands ~2/3 of what it reads — making it emit a
  window too remains open, not done, not this session's job.
- Report format at the end: one line with counts, then the venue names.
  Nothing else.

## 6. Where it's written

- Architecture + the hand-read lane's full write-up:
  `ARCHITECTURE-MENU-INGEST.md`, section "THE HAND-READ LANE" (new tonight).
- `README.md` — top status table and the two-lane explanation, current as of
  tonight.
- `umbrella-arcades/Knowledge-Graph.md` — top entry, 2026-09-03/04.
- Memory: `project_hhf_two_thirds_of_agent_reads_cannot_publish.md` (updated
  tonight with final counts).
