# Handoff — the app is restyled; the corpus is still the whole problem

Written 2026-08-06. HEAD `4bf502e`, pushed, CI green, verified live.
Supersedes the *look* described in the 08-01 handoffs. Everything they say about
the **photo chain and the corpus is still current and still the actual next work.**

---

## What happened this session

The UI was redesigned to mirror <https://paulrenzi.github.io/cenote-map/>, and the
repo got the README it never had.

Changed, all under `web/`: `index.html` (rebuilt structurally), `styles.css`
(rewritten), `app.js` (two lines — it fills the new `#sectionKicker`), `sw.js`
(cache `hhf-v3` → `hhf-v4`, fonts precached), `manifest.json` (theme colors), plus
new `web/fonts/`. **`lib.js` was not touched.** Every id and class `app.js` binds
survived verbatim, which is why a full visual rewrite cost two lines of JS.

### Three decisions embedded in it — don't quietly undo them

1. **Fonts are self-hosted** (`web/fonts/*.woff2`, latin subset, OFL, in the `sw.js`
   shell list). A CDN `@import` would have traded the offline property for a
   typeface. If you ever refresh them, `unicode-range` in `styles.css` must match
   the subset the files were cut from or missing glyphs render as tofu.
2. **The control strip is NOT sticky, and the phone hero is capped at 52vh**
   (66vh ≥700px; the tagline hides <700px). An editorial hero plus four rows of
   controls pushes the first deal off the first screen — the page's entire job.
   Both numbers were measured, not guessed.
3. **Still no map.** Paul re-confirmed it this session while choosing the cenote
   look. At 8 venues a sorted list beats one, and it would be the first CDN dep.
   Revisit past ~50 venues.

### The trap that cost the most time

**The test gate cannot see the markup.** 29 node tests + 21 python tests + the PA
validators + the bundle-drift check all passed while the desktop control strip was
eating half the viewport and the first deal sat below the phone fold. The suite is
pure logic over `lib.js` by design, and that is the right design — but it means
**any UI change must be screenshot at a real viewport before you believe it.**

Playwright is installed. Headless Chrome *clamps window size*, so you must pass a
device-emulation viewport, not resize a window:

```python
pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
```

Check `document.documentElement.scrollWidth == 390` (any larger = horizontal
overflow), the `.card` count, the resolved `#hero h1` font family (proves the
local woff2 loaded), and the console/pageerror channels. A working script lived in
this session's scratchpad; it is ~30 lines and faster to rewrite than to find.

---

## What's next, in order

**1. Zone expansion — the cheapest real win, no key, no network.**
`data/venues.csv` has 2,911 PLCB rows already on disk, and **1,789 in-disc venues
have no zone assigned.** Lower Providence is 4 miles from KoP and unzoned. This is
pure local compute against files that are already here. The corpus knowing 8 bars
is the only thing holding the product back; nothing else on this list matters as
much.

**2. Photos — blocked on Paul, not on code.** The chain is *proven end-to-end*
against a stub (`60ef3fd`): it puts a photo on 8/8 venue cards. What's missing is
`GOOGLE_PLACES_API_KEY` — there is no `.env` in this repo at all. See
`HANDOFF-PHOTOS-2026-08-01-EVENING.md`.

⚠️ **Two things to settle before photos scale, both unresolved:**
- Google's terms restrict storing Places photo **bytes**, and the fetcher commits
  them into a **public** repo. Verify the current Photos policy first — this is the
  same distinction that made ODbL/Nominatim correct for coordinates.
- "Strip EXIF from stored images" is a non-negotiable the fetcher does **not**
  honor (`r.content` is written verbatim). Low risk for Google's re-encodes, high
  risk the moment the user-upload lane exists.

**3. Everything else needs an explicit go-ahead:** the upload → vision → moderation
lane, the Cloudflare Worker + D1 write path, Places at corpus scale (~2,900
lookups), the general crawl.

Paul's sequencing rule still stands: *"we can dig deeper after we have an actual
product that does anything."*

---

## Orientation for a cold session

- Live: <https://paulrenzi.github.io/happy-hour-finder/> — Pages publishes `web/`
  only, on every push to `master`, **gated on the test job**. A red suite blocks
  the site.
- Read `README.md` first now; it covers the pipeline, the two ranking rules, and
  how to run the gate. Then `SPEC.md` for the legal schema.
- `lib.js` = all pure logic and the only tested part. `app.js` = paint only.
  Preserve that split.
- Its own repo, its own `.env`. **Never reach into `shopify-analytics/.env`.**
- Non-negotiables are listed in the README and `HANDOFF-START-HERE.md`. The PA
  validator gate (Acts 57 & 86 of 2024) is not advisory.
