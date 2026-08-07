# Handoff — happy-hour-finder, 2026-08-07 (venue cards are live)

Supersedes `HANDOFF-2026-08-07-VENUE-BASE.md`. Repo is standalone; its own `.env`.
Live: https://paulrenzi.github.io/happy-hour-finder/

Shipped: **`a16ae89`** (the reframe) and **`418b5c2`** (crawl merge + a window bug).
Both CI-green, live artifacts fetched and byte-compared against local.

---

## Item 1 is done: every licensed venue has a card

King of Prussia showed **6 cards against 59 real bars**. It now shows all 59 —
7 with a published happy hour, 52 with a "hours not published — know them?"
card and a working way to send them in.

```
King of Prussia   59 venues,  7 with hours
whole board     2,898 venues, 169 with hours   (2,729 asking to be filled in)
```

### The layer this rests on

`data/venue_base.json` — every licensed premises, keyed on its **PLCB LID**.
Built by `ingest/build_venue_base.py`, and **committed**, because `data/venues.csv`
is gitignored and CI rebuilds the bundles and diffs them: the bundle build must
never read the CSV.

```
2,955 PLCB rows
  -44 Brewery Storage — a permit to keep beer in a building, not to serve it
  -10 a second licence at a building already listed
   -3 outside every zone, so unreachable in the UI
2,898 venues ship
```

The **-10** matters more than its size: the Sheraton Valley Forge is two Hotel
(Liquor) rows at one address, and a card per *licence* shows the same bar twice.
"60 King of Prussia venues" was always 60 **licences** — there are 59 venues.
Collapse key is the Places id, then the OSM id, then street number + ZIP + name.

Names come from the trade name Places resolved, then OSM, then the PLCB licensee
re-cased — a card whose only content is a name cannot print `SCREWBALLS LLC`.

### Two files per zone, and the split is a load-time decision

Boot fetches every zone's **deals** (169 venues, 255 KB) so "what's on right now"
stays an area-wide question. The 2,898-venue base is a megabyte, so it ships as
`venues-<zone>.json` and arrives only when you pick that zone. A test pins the
boot payload under 400 KB so a venue base cannot drift back into it.

Under **All zones** you get deal cards only, plus a line telling you to pick a
zone for full coverage. 2,898 cards is not a feed.

### The board is keyed on LIDs now

`#v=iron-hill-media` still opens Iron Hill — every venue that ever had a slug
carries it. All three link forms were driven in a browser and verified.

The service worker still stamps on the **deal** count, not the venue count: the
base moves only when the PLCB corpus does, so keying on the total would hold one
number steady across every deal-only build — the exact staleness that stamp
exists to catch.

### Submitting hours

`paul@umbrellaarcades.com`, **never rendered as text anywhere on the page** and
assembled at runtime rather than sitting in the bundle as a literal. The card
opens a prefilled draft carrying the venue, the address and the **LID**. There is
no write endpoint, so this is a real delivery path today and **one function to
replace** when a Worker lands. `SUBMIT_TO` in `web/app.js`.

---

## Item 3 is done, and it confirms the ceiling

`ingest/discover_places.py --merge-sites` feeds resolved websites into the crawl
frontier. That is why the 26 KoP sites had never been read: `crawl_sites.py`
reads `venue_sites.json`, and a website Places found was invisible until it
landed there.

**17 newly-readable King of Prussia sites yielded 1 quote.** That is the source
ceiling holding exactly where `HANDOFF-2026-08-07-CEILING.md` put it. Discovery
was never the coverage lever — it is the *venue list* lever, which is why the
reframe was the right call.

Two things the merge will not do, both load-bearing:

- **It will not promote a name-joined match.** An address join says the state and
  Google agree on a building; a name join says two strings look alike in one ZIP.
  Tommy Bahama, Cheesecake Factory and Wegmans stay discovery-only (photo +
  link). Do not widen this.
- **It will not re-add a licence dropped by hand.** Its first run put back the
  Residence Inn, whose row a neighbouring First Watch had claimed — an existing
  test caught it. `HAND_DROPPED` now lives in `discover_places.py` and the test
  reads it, because a drop only a test knows about is one an automated step keeps
  undoing.

---

## A window bug worth knowing about — 22 of 170 venues were wrong

Two schedules on one line were read as one. `days_in()` unioned every day either
clause named and `window_in()` took only the **first** range:

| the page said | we published |
|---|---|
| `Mon-Fri 5-7PM & Sun-Thu 10PM-12PM` | Sunday **5-7PM** |
| `Tuesday-Friday 4-6PM Saturday & Sunday 3-6PM` | Saturday **4-6PM** |
| `Mon-Thur 4-6pm - Fri 3-6pm` | Friday **4-6pm** |

A segment is now split where a separator is followed by a day name, and each
piece must hold exactly one time range. **11 venues corrected** — Chickie's
Sunday moved to the 10pm-12am its page actually states; Teikoku stopped
publishing its *lunch* hours as a happy hour.

`one_sided()` is the guard on the guard. Forsythia writes days **after** the time
(`5pm-8pm | Sunday-Thursday, 5pm-7pm Friday`), so splitting before a day name
cuts a time away from the days it belongs to. Rather than guess, that shape is
refused — which costs Forsythia, a venue that was previously **right**. It now
shows as a card asking to be filled in. That is only an acceptable trade because
the venue base exists: a refused extraction degrades into an invitation instead
of a disappearance.

---

## Next session, in order

1. **Decide the Places cost question — Paul's call, and it is the only thing
   blocking coverage of the other 37 zones.** Cost is set by the field mask, not
   the call count: `websiteUri` is Enterprise, **1,000 free/month**. Remaining
   corpus ≈ 2,840 venues.
   - free: ~3 monthly batches via `--max`
   - paid: roughly **$30–40 once**

   Without it the other zones still get cards — name, address, licence type and
   the ask all come from the PLCB corpus — but no photo and no website, so they
   look thinner than King of Prussia. Conshohocken and Phoenixville first; they
   are the other two towns with live counts to compare against.
2. **Decide the write endpoint.** `mailto:` works now but does not scale past a
   handful a week and gives no queue. Cloudflare Worker + KV is the shape; note
   **oracle-vm is under reclamation ~08-18**, so not the VM.
3. **Sweep the base for junk names.** 777 of 2,901 have a real trade name; the
   rest are re-cased licensees and a few read badly (`Lb's Lounge`). Cosmetic,
   but it is the only text on most cards.
4. Optionally re-enable LID `127673` — Places resolved a marriott.com Residence
   Inn page that looks correct. Delete its `HAND_DROPPED` entry after checking.

## State to know

- `data/venues.csv` is gitignored and `ingest/build_venue_base.py` needs it. If
  it is missing, regenerate with `ingest/seed_plcb.py` **before** the base build.
- The recrawl from the last session **finished** (934 venues on file) and is
  committed.
- 3 licences sit outside every zone (Croydon, St Peters, one Philadelphia ZIP).
  `build_bundles.py` prints the count and drops them; add a zone to surface them.
- `/favicon.ico` 404s. Pre-existing, harmless, unrelated to any of this.
- ~64 orphaned Python processes from **another project** (ga4_client, since 7/20)
  are on this PC. Do not mistake them for crawlers; check start dates.

## Standing constraints (unchanged)

- 🛑 The join is on **address, never name**, for evidence. The name path is
  discovery-only and ZIP-guarded — do not widen it.
- 🛑 Do not relax the price evidence check or the window requirement to raise the
  count. The converse now also has a precedent: **do not keep a wrong window to
  protect the count.**
- 🛑 No map.
- 🛑 Do not bug-fix the HTML crawler for coverage. (The fix above was
  *correctness* — it lowered the count.)
- Scan for stale crawler processes **by age** before every run — each holds its
  own in-memory snapshot of `crawl_hits.json` and rewrites it per venue.
- After every deploy push: `gh run list`, then fetch the **LIVE** artifact.
  Normalise through `json.tool` before concluding a mismatch — git autocrlf makes
  raw byte diffs always differ.

## Gate before any commit

```
python -m unittest discover -s tests      # 147
node --test tests/time_math.test.mjs      # 36
python ingest/validate_pa.py              # 8/8
python ingest/build_bundles.py            # also stamps web/sw.js
gh run list --limit 3                     # AFTER the push
```

Full pipeline, in order, when the corpus moves:

```
python ingest/build_venue_base.py                      # needs data/venues.csv
python ingest/discover_places.py --merge-sites --zone <id> [--execute]
python ingest/crawl_sites.py --zone <id>
python ingest/extract_deals.py && python ingest/validate_pa.py
python ingest/build_bundles.py && python ingest/geocode_venues.py
```

CI has no `requests`; reproduce with a `requests.py` that raises on `PYTHONPATH`
— confirmed green this session.
