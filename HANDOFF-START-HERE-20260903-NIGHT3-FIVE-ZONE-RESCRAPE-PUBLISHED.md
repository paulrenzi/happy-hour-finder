# Handoff — 5-zone rescrape round (wilmington/phoenixville/west_chester/
# newark_de/exton_downingtown), published and verified live

**Branch: `menus30`, fast-forward-merged into `master` and pushed. `git log
origin/master -1` shows `e38e422`.**

## What this round did

Worked the top of `data/RESCRAPE-QUEUE.json` (thin, <5-item live venues),
prioritizing non-Philly zones in the order Paul specified: wilmington,
phoenixville, west_chester, newark_de, exton_downingtown. Used
`ingest/agent_read_venue.py` exclusively — never the regex/HTML extractor —
per the previous handoff's finding that the agent read *is* the extraction
layer.

**Exact counts, no padding:**

| Zone | Venues attempted | Venues that returned items | Items delta (live, before→after) |
|---|---|---|---|
| wilmington | 19 | 8 | 195 → 230 (+35) |
| phoenixville | 6 | 4 | 147 → 169 (+22) |
| west_chester | 12 | 7 | 166 → 190 (+24) |
| newark_de | 9 | 2 | 228 → 240 (+12) |
| exton_downingtown | 8 | 5 | 37 → 141 (+104, mostly one 75-item Limoncello re-read) |
| **Total** | **56** | **26** | **+197 net items live** |

The "venues attempted" counts are exactly what was in `RESCRAPE-QUEUE.json`
for each zone at the top of this round — every one of them was invoked
through `agent_read_venue.py --lids <zone-file> --force` (confirmed: no
regex extractor or HTML scraper touched in this round). 30 of the 56 venues
read genuinely had no confirmable happy-hour item in the source they cite
(mostly `%`-off or vague specials that the price/discount validator
correctly refused, or sites with nothing beyond a discount claim it couldn't
pin to a number) — that is a real ceiling in the source material, not a
tooling miss; the per-venue rejects are visible in the run output.

**Target was "approximately 100 items." Actual: 197 net items shipped live**
— comfortably over target, driven mostly by a few rich reads (Limoncello 75
items, Taco Grande/Trolley Tap House/Bardea Steak in wilmington,
Great American Pub/Sedona Taphouse in phoenixville).

## A mid-round collision, caught and resolved

Partway through, a second agent turned out to be running the *same* task
independently against the *same* checkout (`hhf-menus30`) — a
checkout-sharing hazard this project's docs explicitly warn about. It was
caught by noticing untracked scratchpad/lids files it had left behind,
stopped via `SendMessage` before it touched git (no commit, no push from its
side), and its in-progress reads (wilmington/phoenixville/west_chester/
newark_de, not yet exton_downingtown) were superseded cleanly by this
round's commit — no data lost, nothing duplicated. See the new memory file
below for the durable lesson.

## Build + tests

```
python ingest/build_bundles.py   → 368 deals across 48 zones, 0 rejected by validators, 0 decayed out
                                    3 venues / 20 items READ AND NEVER PUBLISHED (stranding gap,
                                    pre-existing and separate — see ARCHITECTURE-MENU-INGEST.md)
bash tests/run.sh                → 70/70 unit tests pass, 0 fail
                                    7/7 deals pass PA validators
                                    368 published deals, 0 whose window contradicts its own quote
                                    lib.js/app.js/sw.js parse in a real browser engine — pass
                                    board paints, search works, freshness restamp works, 360px card reads — pass
RESCRAPE-QUEUE.json regenerated: 138 → 122 (report file, not a gate)
```

## Publish, verified live (not just green CI)

```
git worktree add /c/Users/paulm/_wt_hhf_publish master   # separate from the working checkout
git merge --ff-only origin/master                        # up to date
git merge --ff-only menus30                               # clean fast-forward, e38e422
bash tests/run.sh                                          # 70/70 pass, in the worktree
python ingest/build_bundles.py                             # 0 diff — bundle already matched committed state
git push origin master                                     # 23bb04c..e38e422 master -> master
gh run list --branch master --limit 1                      # completed / success, headSha e38e4225...
```

Live JSON read directly after the Action completed (`built_at: 2026-09-03`
on every zone touched):

```
curl -s https://paulrenzi.github.io/happy-hour-finder/data/zone-exton_downingtown.json
  Limoncello items: 76

curl -s https://paulrenzi.github.io/happy-hour-finder/data/zone-wilmington.json
  Bardea Steak items: 9
  Taco Grande items: 14
  Trolley Tap House items: 14
```

Worktree removed after publish (`git worktree remove /c/Users/paulm/_wt_hhf_publish --force`).

## Docs / memory updated

- `ARCHITECTURE-MENU-INGEST.md` — added a dated addendum confirming the
  same-night sidecar-merge fix (`c4bf6f0`, `ba54e20`) holds up at multi-zone
  scale, and a practical note: `--tier`/`--needy` never sees
  `RESCRAPE-QUEUE.json`'s <5-item population (they select *zero*-item
  venues) — a rescrape round needs `--lids <file> --force`.
- New memory file:
  `project_hhf_rescrape_queue_needs_lids_force_not_tier.md` (in
  `C:\Users\paulm\.claude\projects\c--Users-paulm-umbrella-arcades\memory\`),
  pointer added to `MEMORY.md`'s HHF section.

## Open issues, for the next session

- The stranding gap is still open: `agent_read_venue.py` is still a sidecar
  and still loses reads with no crawled window to attach to (3 venues / 20
  items this round: 2× TGI Fridays, Plaza Azteca). The fix named in
  `ARCHITECTURE-MENU-INGEST.md` — make it emit an `agent_handread`-shaped
  record (window + items) instead of items-only — is still not built.
- `RESCRAPE-QUEUE.json` still has 122 thin venues after this round, spread
  across many zones (center_city 18, wilmington 14, phoenixville 12,
  west_chester 9, newark_de 8, exton_downingtown 4, plus many zones with
  1-4). The queue count did not fall as far as the venue-attempt count
  because it also regenerated to include venues below the original 138-row
  snapshot that weren't previously flagged.
- 30 of the 56 venues attempted this round returned nothing confirmable —
  worth a second look with a person (hand-read) rather than another agent
  pass, per the "agent lane still strands / can't always resolve a vague
  discount" pattern documented in `ARCHITECTURE-MENU-INGEST.md`.

**Next session: pick up `RESCRAPE-QUEUE.json`'s current top (center_city has
the largest single-zone count at 18, but it's Philly, not the non-Philly
priority Paul set this round — ask before reordering priority away from what
he specified). Always end with the "Publishing a branch's work" sequence in
README.md, worktree and live-curl included — do not skip it.**
