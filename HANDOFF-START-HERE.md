# Happy Hour Finder — Build Handoff

**Read this first, then [SPEC.md](SPEC.md).**
Written 2026-07-31. Nothing has been built yet — this repo contains two markdown files.

---

## What this is

A mobile-web happy hour finder for the ~20-mile area around King of Prussia, PA.
**Standalone project.** It is not part of umbrella-arcades, shares no code, no
credentials, and no deploy pipeline with it. Its own repo, its own GitHub remote,
its own Cloudflare account surface.

The one-line product definition, which everything else serves:

> **A live answer to "where can I go in the next 30 minutes, and is the deal actually still on?"**

---

## Decisions already made — do not re-litigate these

These were settled 2026-07-31. If a future session wants to change one, that's a
conversation with Paul, not a design call.

| # | Decision | Why |
|---|---|---|
| 1 | **Its own repo, `happy-hour-finder`, not a subdirectory of umbrella-arcades** | Entirely separate product. No shared code or creds. |
| 2 | **Photo submissions of timestamped happy hour menus are a front-and-center feature**, not a v2 nicety | See "The photo lane" below. This is the freshness engine's real fuel. |
| 3 | **Mobile phone first — to the point of being hostile to desktop-first thinking** | The core actions (find one now / photograph a menu) both happen standing up, one-handed, on cellular. |
| 4 | **Scraping comes first, but only to bootstrap.** Automate what's automatable, then let photos carry it | A cold corpus with no refresh mechanism is the failure mode that killed every competitor (SPEC §1). |
| 5 | **Browse by named zone, not by radius** | A 20-mile disc from KoP reaches Center City Philadelphia (~15.4mi) and Camden NJ (~17.6mi). SPEC §2. |
| 6 | **PA liquor law supplies the deal schema and the validators** | SPEC §3. Three deal types, five free correctness checks. |
| 7 | **No login to browse. No login to submit a photo.** | Friction here kills the contribution rate, which kills the product. |

---

## Still open — needs Paul, don't guess

1. **Name and domain.** Everything ships under a placeholder until this exists.
2. **NJ in scope?** Recommend no for v1 — different legal regime, different validators.
3. **Center City Philly:** collect but default off, or exclude entirely? Recommend collect + default off.
4. **Google Places budget** — confirm one resolution pass over ~3,000 venues fits the free tier before wiring it in.
5. **Who reviews the moderation/correction queue, and how often.** The trust model rests on this being a real habit.

---

## The photo lane (new since the spec — treat SPEC §6 as amended by this)

**The idea.** A user standing in a bar photographs the happy hour table tent,
chalkboard, or printed menu. That photo is dated, located, and visually verifiable —
it is the strongest freshness evidence that exists, stronger than anything scraped,
and it is trivially easy for a human to produce. One tap on the camera.

### Why it beats scraping

Scraping tells you what a venue *published* — often years ago, often on a PDF nobody
has opened since. A photo tells you what was **physically on the table on Tuesday**.
It also solves the hardest venues: the ones with no website, no PDF, no Toast menu,
just a chalkboard. Those are exactly the neighborhood bars people want.

### Trust chain — what "timestamped" actually means

**Do not trust EXIF.** Device clocks are wrong, and EXIF is trivially editable.
The anchor is server-side:

| Signal | Trust | Use |
|---|---|---|
| Server receipt time | ✅ Authoritative | This is *the* timestamp. Everything else is corroboration. |
| Geolocation at capture (one-shot, in-session) | ✅ Strong when within ~150m of the venue | Promotes the submission; its absence demotes but does not reject |
| EXIF `DateTimeOriginal` | ⚠️ Corroborating only | Flag if it disagrees with receipt time by >48h |
| EXIF GPS | ⚠️ Corroborating only | Same |

A photo taken at the venue during business hours, submitted immediately, is the
gold standard. A photo uploaded from the camera roll three towns away is still
useful — it just enters at a lower confidence.

**Strip all EXIF before storing the image.** Keep the extracted fields in the
database; never serve a user-uploaded file with location metadata still attached.

### Pipeline

```
capture (camera or roll)
  → client-side downscale to ~1600px long edge, strip EXIF after reading it
  → upload to R2 via a Worker-signed URL
  → Claude vision extraction → JSON schema (same deal schema as SPEC §4)
  → PA legal validators (SPEC §3)
  → pass  → deal upsert, confidence = verified-by-photo, photo linked as evidence
    fail  → moderation queue
  → the photo itself is displayed on the deal card: "Photographed 6 days ago" → tap to view
```

**The photo is the receipt.** Showing the actual menu image next to the extracted
deal is the single most trust-building thing this app can do. The user does not have
to believe our parser — they can look.

### Model choice

Use **`claude-opus-5`** for photo extraction. Volume is low (tens to hundreds a
week, not thousands), the inputs are hostile (chalk, glare, handwriting, angled
phone shots, dim bar lighting), and a misread price is exactly the failure that
destroys trust. Bulk web-text extraction stays on Haiku 4.5 via the Batch API —
that's a different job with different economics (SPEC §5).

Use structured outputs (`output_config.format` with a JSON schema) so the response
is guaranteed-parseable, and have the model return a per-field confidence plus a
`legible: bool`. An illegible photo should say so rather than hallucinate a price.

### Moderation — required, not optional

User-uploaded images to a public surface means:

- Nothing appears publicly until it clears the queue, **or** it appears only after
  the vision pass extracts a schema-valid deal and finds no people in frame.
- Reject/flag: faces, anything not a menu, anything the validators reject.
- One-tap takedown path on every photo.
- Rate-limit per anonymous contributor token.

### Contributor identity without accounts

Anonymous token in `localStorage`, minted on first submission. Enough to rate-limit,
enough to build a per-contributor reliability score over time (a contributor whose
photos consistently validate can have later submissions auto-promote). No email,
no OAuth, nothing to log into.

---

## Mobile-first, concretely

Not "responsive." **Phone is the target; desktop is the courtesy fallback.**

- **Two thumb-zone actions, always reachable at the bottom of the screen:**
  `What's on now` and `📷 Add a menu`. Nothing else competes for that space.
- **Camera in one tap.** `<input type="file" accept="image/*" capture="environment">`
  opens the camera directly — no app, no permission dance beyond the native prompt.
- Single column. No hover states. Tap targets ≥44px. Text legible in a dim bar.
- **PWA, installable, offline-capable.** The zone bundle is cached; "what's live
  right now" is pure client-side math over cached data, so it works with no signal
  in a parking lot or a basement bar.
- **Sub-second on LTE.** Per-zone JSON bundles are ~10–20KB gzipped (SPEC §9).
  Ship the corpus, filter in the browser.
- One-shot geolocation, in-session only. **Never background-track.**
- Upload must survive a flaky connection: queue the submission locally, retry,
  tell the user it's queued. Losing someone's photo because they walked into an
  elevator is how you lose a contributor permanently.
- Test on a real phone on real cellular, not a desktop devtools viewport.

---

## Build order

Phase 0 has not been done. **It is not optional.**

| Phase | Scope | Exit criterion |
|---|---|---|
| **0 — Feasibility** *(1–2 days)* | Pull the PLCB licensee list for the area; count per zone; hand-check 30 venues for a findable happy hour page | Know the real denominator and the real yield rate before building anything. If yield is 15% and not 40%, the shape of the whole product changes — and the photo lane becomes even more central. |
| **1 — Corpus** | Seed venues, resolve Places, crawl, cold-start Batch extraction, run PA validators | ≥400 venues with ≥1 validated deal |
| **2 — "Right now"** | Static per-zone bundles, live-now feed with ends-in countdown, map, venue pages, PWA shell | A KoP user answers "where now?" in under 10 seconds on a phone |
| **3 — Photo lane** | Capture → upload → vision extract → validate → moderate → publish, with the photo shown as evidence | A stranger can photograph a table tent and see their deal live within a day |
| **4 — Freshness** | Confidence ladder, decay, geofenced "still on?" tap, report-wrong link, weekly delta crawl | Confidence + age visible on every card |
| **5 — Depth** | Normalized price sort, food filters, crawl builder, vibe/accessibility tags | The features nobody else has (SPEC §7) |
| **6 — Operators** | Claim-your-listing, one-screen editor | First 25 claimed venues |

Note the reordering versus SPEC §11: **the photo lane moved ahead of the general
freshness work**, because it is the mechanism that makes freshness possible rather
than a feature layered on top of it.

---

## Repo layout (proposed)

```
happy-hour-finder/
  SPEC.md
  HANDOFF-START-HERE.md      # this file
  ingest/
    seed_plcb.py             # licensee registry → venues
    resolve_places.py        # Google Places enrichment
    fetch_sources.py         # crawl + content-hash gate
    extract_deals.py         # Batch API, Haiku 4.5, JSON schema
    extract_photo.py         # Opus 5 vision, JSON schema
    validate_pa.py           # PA legal validators (SPEC §3)
    build_bundles.py         # emit per-zone JSON
  worker/
    index.js                 # uploads, verifications, reports, claims
    schema.sql               # D1
  web/
    index.html app.js sw.js styles.css manifest.json
  data/
    zones.json
```

Python: stdlib + requests + dotenv, standalone CLI scripts. JS: vanilla, no framework.
`.env` in this repo only — **do not reach into `shopify-analytics/.env`.** Different
product, separate credentials, and the isolation is deliberate.

---

## Non-negotiables

1. Never display a deal that fails a PA legal validator — it's bad data by definition.
2. Never render a claim the source didn't make.
3. Always show verification age. Deals **decay**, they never silently vanish.
4. Store and link the source (URL or photo) for every deal.
5. Honor `robots.txt`; rate-limit crawls to something a small restaurant's shared host won't notice.
6. Strip EXIF from every stored image. Never background-track location.
7. No paid placement in the "right now" feed, ever.
8. Keep this operationally separate from Umbrella Arcades' venue prospecting (SPEC §10).
   If operators read it as lead-gen, claim rates collapse and the data asset dies.
