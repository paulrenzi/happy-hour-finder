# START HERE — a hand read publishes a whole venue (2026-09-03, evening)

**Read this, then `README.md`, then the last section of
`ARCHITECTURE-MENU-INGEST.md`. Nothing else.**

---

## What happened

Paul asked for **30 more real happy hour menus on the live board** —
Wilmington +15, Newark +5, West Chester +10 — with one rule: a venue counts
only when its items are visible in the **live JSON** under that venue's name.

**Landed: Wilmington 15/15, Newark 5/5, West Chester 8/10. 28 venues, 203 items.**
All three zones verified with `python tests/live_front_door.py <zone>`.

Wilmington — Washington Street Ale House, Chelsea Tavern, Union Street Pub,
Tonic Seafood & Steak, Roost Pub & Kitchen, The Copper Dram, Columbus Inn,
Trolley Square Oyster House, Iron Hill Brewery, Piccolina Toscana, Big Fish
Grill on the Riverfront, Docklands Riverfront, Cafe Mezzanotte, Little Vinnie's,
Brew Works North.
Newark — Founding Brothers, P.F. Chang's, Del Pez, Santa Fe Mexican Grill,
Klondike Kate's.
West Chester — S Bar 10, Bar Avalon, Kildare's, Más Mexicali, Pietro's Prime,
Saloon 151, Teca, Mercato.

**None of them came through `agent_read_venue.py`.** Every one was read by the
session itself, by hand. That is the finding, not a footnote.

---

## The architecture change — the only thing you must understand

Every enrichment source before today was a **sidecar** (`deals_prices_llm`,
`deals_menu_images`, `deals_agent`, `deals_pages_llm`). A sidecar carries items
only, and `build_bundles.py` can only fill items **into a deal that already
exists**. A deal exists only if a deterministic pass parsed a **window**.

⇒ A venue whose hours no crawler ever read has nowhere to put its items, and
they vanish **with no error**. 52 paid-for items had been sitting stranded in
`data/deals_agent.json`; two thirds of everything the agent lane bought went the
same way.

**New lane — a hand read carries the window too, so it publishes a whole venue:**

```
data/agent_handread.json          <- you write this, one record per venue
   ↓ ingest/build_agent_venues.py
data/deals_agent_venues.json      <- generated, NEVER edit
   ↓ ingest/build_bundles.py      <- merged at rank 2
web/data/zone-*.json
```

One record:

```json
{"lid": "DE608516193f",
 "url": "https://the-venue-s-own-page",
 "read_on": "2026-09-03",
 "quote": "the venue's own words, verbatim, carrying the hours and the prices",
 "days": [1,2,3,4,5], "start": "16:30", "end": "17:30",
 "items": [{"category": "draft", "label": "Draft beer", "amount_off_usd": 1.0,
            "evidence": "$1 off draft beer"}]}
```

- Omit `items` and it adopts whatever the agent lane already banked for that
  lid — that is how stranded items get rescued instead of re-bought.
- Use `windows: [{"dow":1,"start":...,"end":...}, ...]` instead of
  `days`/`start`/`end` for a venue whose happy hour runs from open.
- `"kind": "instagram"` when the venue posts specials only there. Still the
  venue speaking; the card cites it honestly.
- Rank 2 = above every machine pass, below a person's seed and an approved photo.
- `validate_deal()` runs on every record. A windowless deal is refused, by
  design.

---

## The ladder that actually finds menus — walk it in this order

1. **`python ingest/sweep_site.py <url>`** — crawls the site's own subpages and
   prints the raw text around every "happy hour". **This found ten venues
   WebFetch had already missed**, because WebFetch summarises and a summariser
   drops a price table. Reach for this *before* WebFetch.
2. **Guess the Popmenu path:** `/<town>-<venue>-happy-hours-specials`.
3. **The menu PDF:** `python ingest/pdf_to_png.py menu.pdf out/` then Read the
   PNG. 🛑 poppler is not installed, so the Read tool cannot open a PDF directly.
4. **The posted image** — half these menus are a JPEG.
5. **A targeted search for the venue's own deep page**, not for the answer.
6. **The venue's own Instagram.**

---

## Blockers — structural, already worked, do not re-open

- **A price with no clock:** TGI Fridays (×2), Lefty's Alley & Eats, Plaza
  Azteca. 15 banked items correctly refuse to publish — a windowless deal fails
  the validator and every renderer hangs items off a window.
- **A clock with no prices:** Snuff Mill, Bar XIII, Rockwell's on Main, Goal Line
  Pub. Already publishing a window; nothing to add.
- **A venue that contradicts itself:** Makers Alley's food tab and drink tab give
  different prices for the same happy hour. Skipped — *a wrong item is worse
  than a miss*.
- **Old roundups are not sources.** County Lines names ~25 West Chester venues
  with prices, dated 2021 and 2024; `decay()` hides anything over 120 days, and
  a roundup is the outlet speaking, not the bar.

## Why West Chester stopped at 8 — and it is a REACH finding

The `west_chester` zone base holds **62** rows. 15 already had items. Every
remaining one was opened by hand and none publishes a clock *and* a price
anywhere it owns. The venues that would have filled the gap — Greystone Oyster
Bar, The Social, Sterling Pig, Split Rail, Slow Hand — **are not in the zone's
base under those names.** More reading cannot fix that. Only discovery can.
Same finding as *the item gap is reach, not reading*, reached from the far end.

---

## Where to pick up

1. **Rescue the rest of the stranded reads.** Run the agent lane's banked items
   through the new lane: for each lid in `data/deals_agent.json` with no live
   window, hand-read just the **hours** and write a record with `items` omitted.
   The items are already paid for; only the clock is missing.
2. **West Chester's missing five is a discovery job**, not a reading one —
   `ingest/discover_places.py --zone west_chester`, then
   `--merge-sites --execute`, then `build_venue_base.py`. Skipping the third
   command leaves the new venues with no `website` and blinds `needy.py`.
3. **Decide whether `agent_read_venue.py` should return the window.** It returns
   items only, so it will keep stranding two thirds of what it buys until it
   emits a record in the `agent_handread` shape instead of a sidecar entry.
   This is the single highest-leverage change left in the lane.

## Standing rules that bit this session

- **"It is live" is one command:** `python tests/live_front_door.py <zone>`.
  A local build, a green test run and an HTTP 200 are each blind to it. One
  `NOT LIVE` is usually Pages lag (~1 min) — re-run before diagnosing.
- **Never write a backslash escape through a bash heredoc** — the patch reports
  success and the file is unchanged, or gains a literal control byte. Use an
  editor tool. This cost a `re.PatternError` here.
- **The repo may be shared with another session.** Check
  `git branch --show-current` before committing. This session worked in a
  `git worktree` (`../hhf-menus30`, branch `menus30`) and pushed with
  `git push origin menus30:master` — a plain `git push origin master` from a
  checkout another session has moved is a **silent no-op**.
- Windows console is cp1252: `sys.stdout.reconfigure(encoding="utf-8",
  errors="replace")` in any script that prints a venue name.
