# Handoff — venue photos + what to test next (2026-08-01)

HEAD at write time: `9140b3d` "make it look like a place you would want to drink".
Working tree clean. Live at https://paulrenzi.github.io/happy-hour-finder/ (Pages
redeploys on every push to `master`).

## Where we are

| Ask | State |
|-----|-------|
| Beautiful redesign | ✅ shipped, Paul confirmed ("much better design") |
| Generic brewery hero | ✅ shipped, Wikimedia CC BY-SA 4.0, credited in `#credits` |
| Per-venue photos from Google | ⛔ **code complete, never run — no API key** |

## The one open item: photos

Nothing is broken in the page. The photos were never fetched. Confirmed absent on disk:

1. `.env` (→ no `GOOGLE_PLACES_API_KEY`)
2. `data/venue_photos.json`
3. `web/img/venues/`
4. any `"photo"` key in `web/data/zone-*.json`

Each stage degrades silently **by design**, which is exactly why this looks like a
rendering bug and isn't:

- `ingest/fetch_venue_photos.py` exits on a missing key, and is a manual step.
- `ingest/build_bundles.py:45` reads an empty `photos` dict when the manifest is absent,
  and `:72` attaches `v["photo"]` only if the manifest entry **and** the file both exist.
- `web/app.js:137` branches `if (v.photo)`; the `else` draws the designed tile
  (`hueOf` hue + serif monogram), so a missing photo still looks intentional.

**Debug rule for next time:** when something is *absent* rather than *broken*, walk that
list of four artifacts in order. The first one missing is the answer. Reading the render
code first tells you nothing.

### Unblock sequence

1. Google Cloud console → enable **Places API (New)** → create an API key.
   8 venues ≈ 16 calls, inside the free tier.
2. Create `happy-hour-finder/.env` with `GOOGLE_PLACES_API_KEY=AIza...`
   (`.gitignore` already covers `.env`; this repo never reads another repo's credentials).
3. Run:
   ```
   cd C:\Users\paulm\happy-hour-finder
   python ingest/fetch_venue_photos.py
   python ingest/build_bundles.py
   git add -A && git commit -m "venue photos" && git push
   ```

### What to actually check after the run — not "did it succeed"

- **Read the printed `resolved_name` / `resolved_address` for every venue.** Resolution is
  address-keyed because two "Iron Hill Brewery" rows are different bars. A wrong match
  returns a plausible photo of the wrong location and looks like success. Iron Hill Media
  is the one to eyeball.
- `--limit N` and `--force` exist; `--force` refetches venues already in the manifest.
- No service-worker bump needed: venue images aren't in `sw.js`'s `SHELL`, so they cache
  opportunistically and the fetch handler is network-first.
- Then load the live URL on a phone and confirm the images 200 (not just that cards render
  — the `error` listener at `app.js:142` silently falls back to the tile on a 404).

### Decision worth making before investing further

Google's terms don't permit storing Places photos indefinitely, so committing them to the
repo is a grey area that gets worse as the corpus grows past 8 venues. Fine for proving
the design out now. The durable version is Paul's own photo lane — same card slot, no
license question, and it's the lane already needed for the ~80% of bars that never publish
a happy hour at all (Phase 0 measured a **19%** scrape yield, not 40%).

## Not started — needs an explicit go-ahead

Sequencing is Paul's: *"we can dig deeper after we have an actual product that does anything."*

- Photo lane: upload → R2 → vision extraction → PA validators → moderation queue
- Cloudflare Worker + D1 write path (verifications, "this was wrong" reports, operator claims)
- Places resolution at corpus scale (~2,900 lookups; budget unconfirmed)
- Per-venue coordinates and a map
- Zone expansion (~8 more zones; 1,789 in-disc venues unzoned — Lower Providence is 4 miles
  from KoP and still unzoned)
- The general crawl / batch-extraction corpus build

## Ground rules that stay in force

Own `.env` only, never `shopify-analytics/.env`. Honor `robots.txt`, rate-limit crawls to
something a small restaurant's shared host won't notice. Never display a deal that fails the
PA legal validator (Acts 57 & 86 of 2024). Never render a claim the source didn't make.
Always show verification age and link the source. Strip EXIF from stored images, never
background-track location. No paid placement in the "right now" feed. Keep this operationally
separate from Umbrella Arcades' venue prospecting.
