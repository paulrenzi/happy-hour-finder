#!/usr/bin/env python3
"""Emit the per-zone JSON bundles the web app ships (SPEC section 9).

Reads data/deals_seed.json, drops anything the PA validators reject, applies
the confidence decay ladder (SPEC section 6), and writes web/data/.

    python ingest/build_bundles.py
"""

import datetime
import hashlib
import json
import re
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validate_pa import validate_deal, validate_food_combo_count  # noqa: E402

DEALS_JSON = os.path.join(REPO, "data", "deals_seed.json")
EXTRACTED_JSON = os.path.join(REPO, "data", "deals_extracted.json")
# Approved menu-photo submissions (ingest/review_photos.py). Distinct from
# PHOTOS_JSON below, which is venue hero images and has nothing to do with deals.
PHOTO_DEALS_JSON = os.path.join(REPO, "data", "deals_photo.json")
ZONES_JSON = os.path.join(REPO, "data", "zones.json")
PRICES_JSON = os.path.join(REPO, "data", "deals_prices_llm.json")
PHOTOS_JSON = os.path.join(REPO, "data", "venue_photos.json")
COORDS_JSON = os.path.join(REPO, "data", "venue_coords.json")
BASE_JSON = os.path.join(REPO, "data", "venue_base.json")
OUT_DIR = os.path.join(REPO, "web", "data")


def norm_addr(address):
    """Enough of an address to tell whether two records are one bar. The seed
    writes '324 W Swedesford Rd, Berwyn PA 19312' where the PLCB row the crawler
    carried says '324 WEST SWEDESFORD ROAD'; the number and the ZIP agree."""
    m = re.search(r"\b(\d{5})\b", address or "")
    n = re.match(r"\s*(\d+)", address or "")
    return (n.group(1) if n else "?", m.group(1) if m else "?")


def norm_name(name):
    """Two display names are the same bar's name if they differ only in the
    punctuation a licensee typed: PJ Whelihan's / P.J. Whelihan's / P. J.
    Whelihan's Pub + Restaurant all collapse to the same key."""
    n = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    n = re.sub(r"\b(pub|restaurant|bar|grill|grille|tavern|cafe|and|the)\b", " ", n)
    # Spaces go too: a licensee typing "PJ" and another typing "P. J." is the
    # same three letters, and the source-page check below is what actually
    # guards the merge.
    return re.sub(r"[^a-z0-9]", "", n)


def deal_sources(venue):
    return {(d.get("source") or {}).get("url") for d in venue.get("deals", [])
            if (d.get("source") or {}).get("url")}


def collapse_name_collisions(by_zone):
    """One bar, one card.

    Six bars painted TWICE on the live board -- three P.J. Whelihan's, Hard Rock
    Cafe, Amada, The Post. Not a rendering bug and not two branches: the PLCB
    lists a SECOND licence in the same building (the Giant next door, the
    Marriott upstairs, the cinema in the same plaza), the name/site match gave
    that licence the bar's trade name, and the crawl then hung the bar's happy
    hour on both. premises_key could not merge them because it is deliberately
    strict -- Google gave them different place ids, and the licensee names
    ("THE GIANT COMPANY LLC") do not agree.

    So the merge happens here instead, where a much stronger signal exists: the
    two rows carry the SAME name in the same zone AND their deals were read off
    the SAME page. One web page is one bar's hours. The loser keeps its licence
    row -- it is a real premises -- but gives up the trade name it was never
    entitled to and the deals that belong next door, so it falls back to the
    'hours unknown' list under its own licensee name. Its LID rides along in
    also_lids, so a correction quoting it still lands on the right card.

    Returns the number of collisions collapsed.
    """
    collapsed = 0
    for venues in by_zone.values():
        groups = {}
        for v in venues:
            if v.get("deals"):
                groups.setdefault(norm_name(v["name"]), []).append(v)
        for rows in groups.values():
            if len(rows) < 2:
                continue
            # Sub-group by the page the hours were read off. Three P.J.
            # Whelihan's share a zone: two are one bar in Conshohocken with two
            # licences, the third is a real second branch in Blue Bell with its
            # own page. Asking what ALL of them share finds nothing and merges
            # nobody -- the question is which of them share a page.
            by_page = {}
            for v in rows:
                for url in deal_sources(v):
                    by_page.setdefault(url, []).append(v)
            for page, same in by_page.items():
                if len(same) < 2:
                    # Same name, a different page. That can be two real
                    # branches, and merging two real bars is far worse than
                    # listing one twice.
                    continue
                collapsed += merge_rows(same)
    return collapsed


def merge_rows(rows):
    """One winner keeps the card; the losers give back the trade name and the
    deals, and ride along in also_lids. Returns how many were collapsed."""
    rows = [v for v in rows if v.get("deals")]
    if len(rows) < 2:
        return 0
    rows.sort(key=lambda v: (-len(v["deals"]), "photo" not in v,
                             "website" not in v, str(v["id"])))
    winner, losers = rows[0], rows[1:]
    also = list(winner.get("also_lids") or [])
    for v in losers:
        print(f"  merged: {v['name']} ({v['id']}) into {winner['id']} "
              f"-- same name, same source page")
        also += [str(v.get("lid") or v["id"])] + list(v.get("also_lids") or [])
        v["deals"] = []
        v.pop("also_lids", None)
        if v.get("plcb_name"):
            v["name"] = v["plcb_name"]
    winner["also_lids"] = sorted(set(also) - {str(winner.get("lid") or "")})
    return len(losers)


def decay(confidence, verified_at, today):
    """A deal never disappears, it demotes. SPEC section 6.

    The bundle ships `last_verified_at` and the confidence the source earned;
    the app re-runs this same ladder at read time (web/lib.js). Baking the
    demotion in here would freeze it at build time, so a bundle served for two
    months would keep calling a stale deal fresh. This copy exists to drop
    deals that have decayed out entirely, which is a build-time size decision.
    """
    age = (today - datetime.date.fromisoformat(verified_at)).days
    if confidence in ("verified", "disputed"):
        return confidence, age
    if age > 120:
        return "hidden", age
    if age > 45 and confidence == "likely":
        return "unconfirmed", age
    return confidence, age


# The precached shell files. data/index.json is covered by the venue count.
#
# sw.js is hashed too, but through _sw_source_for_digest, which blanks the CACHE
# line before hashing: the naive version has no fixed point, because stamping the
# name changes the bytes that produced it. Leaving it out entirely was the other
# way to break the tie, and it left a hole -- a deploy that changes ONLY the
# service worker (a caching-strategy fix, say) kept the previous cache name, so
# activate() deleted nothing and every installed device kept serving the old
# precached shell out from under the new worker.
SHELL_FILES = ("index.html", "app.js", "lib.js", "styles.css", "manifest.json")

CACHE_LINE = re.compile(r'const CACHE = "[^"]*";')


def _sw_source_for_digest():
    """sw.js with its own cache name neutralised, so hashing it terminates."""
    with open(os.path.join(REPO, "web", "sw.js"), encoding="utf-8") as fh:
        return CACHE_LINE.sub('const CACHE = "";', fh.read()).encode("utf-8")


def shell_digest():
    """A short hash of the precached shell, so a shell-only deploy still evicts.

    The date and venue count move only when the CORPUS moves. A deploy that
    changes app.js or index.html and nothing else produces the same name, the
    activate handler deletes nothing, and every already-installed device keeps
    serving the old shell out of the precache -- the exact shape of the King of
    Prussia freeze, with the corpus in the clear.
    """
    h = hashlib.sha256()
    for name in SHELL_FILES:
        with open(os.path.join(REPO, "web", name), "rb") as fh:
            h.update(fh.read())
    h.update(_sw_source_for_digest())
    return h.hexdigest()[:8]


def sw_cache_name(built_at, n_published, digest=None):
    """The cache name a build of this shape must ship.

    The service worker precaches data/index.json, and its cache name is the ONLY
    thing that evicts. A hand-edited constant went four builds without changing,
    so devices kept serving an index from an older corpus -- King of Prussia read
    1 venue while the server had said 3 for hours, with nothing on either side to
    show a disagreement. The venue count rides along with the date so that a
    second build on the same day still evicts, and the shell digest so that a
    build changing only the app code evicts too.
    """
    return f"hhf-{built_at}-{n_published}-{shell_digest() if digest is None else digest}"


def stamp_service_worker(built_at, n_published):
    path = os.path.join(OUT_DIR, "..", "sw.js")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    new = re.sub(r'const CACHE = "[^"]*";',
                 f'const CACHE = "{sw_cache_name(built_at, n_published)}";', src, count=1)
    if new != src:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)
        print(f"sw.js cache -> {sw_cache_name(built_at, n_published)}")


def main():
    today = datetime.date.today()
    payload = json.load(open(DEALS_JSON, encoding="utf-8"))
    reserve = []

    def merge_venues(payload, more, label, rank):
        """Add venues from a lower-priority source, skipping any the higher ones
        already describe. Never merged INTO an existing venue: where two sources
        describe one bar the higher-priority source wins outright.

        The loser is not thrown away: it goes on `reserve` and publishes if the
        winner turns out to have no deal LEFT once the validators and the decay
        ladder are done with it. Dropping it outright meant a venue could win on
        priority and then publish nothing -- a photo whose hours had aged into
        `hidden` would take the crawler's still-good window off the board with
        it and the card would go blank. A stale window is a bug; a venue that
        silently loses the hours it had is worse."""
        seen = {}
        for v in payload["venues"]:
            seen.setdefault(v["id"], v)
            seen.setdefault(norm_addr(v["address"]), v)
        fresh, dupes = [], []
        for v in more:
            # Which venue this one lost to, kept with it: the fallback has to ask
            # whether THAT venue published, not whether this one's own licence
            # number is on the board. Two licences at one building have two
            # different numbers, so asking about its own would always say no and
            # every duplicate would publish a second card for the same bar.
            beat_by = seen.get(v["id"]) or seen.get(norm_addr(v["address"]))
            if beat_by is None:
                fresh.append(dict(v, _rank=rank))
            else:
                dupes.append((dict(v, _rank=rank), beat_by))
        reserve.extend(dupes)
        print(f"  +{len(fresh)} {label} venues ({len(dupes)} already covered)")
        return dict(payload, venues=payload["venues"] + fresh)

    def merge(payload, path, label, rank):
        if not os.path.exists(path):
            return payload
        return merge_venues(payload, json.load(open(path, encoding="utf-8"))["venues"],
                            label, rank)

    # Priority order, highest first:
    #   deals_photo.json      a person approved a photo of the venue's own menu
    #   deals_seed.json       a person read the venue's own page
    #   deals_extracted.json  a regex read a page
    # A photo is the menu on the wall, dated, moderated by a human (SPEC section
    # 8), and it is the only source a customer can correct us with. So it now
    # outranks the hand-read seed as well as the crawler: the seed was read once,
    # months ago, and somebody standing in a bar photographing the board is
    # usually telling us it has changed since. Ranking the seed above it meant an
    # approved correction for a seeded venue was merged, counted, and then
    # silently dropped -- the submitter saw nothing change, ever. Written by
    # ingest/review_photos.py -- approving is not publishing, this build is.
    seeded = [dict(v, _rank=1) for v in payload["venues"]]
    photos = (json.load(open(PHOTO_DEALS_JSON, encoding="utf-8"))["venues"]
              if os.path.exists(PHOTO_DEALS_JSON) else [])
    print(f"  {len(photos)} photo-submitted venues (highest priority)")
    payload = dict(payload, venues=[dict(v, _rank=0) for v in photos])
    payload = merge_venues(payload, seeded, "hand-seeded", 1)
    payload = merge(payload, EXTRACTED_JSON, "machine-extracted", 2)
    zones = json.load(open(ZONES_JSON, encoding="utf-8"))
    zone_names = {z["id"]: z["name"] for z in zones["zones"]}
    # Optional: written by ingest/fetch_venue_photos.py. A venue with no entry
    # gets the app's generated tile instead.
    # Written by ingest/extract_prices_llm.py: prices read off the same quotes
    # the deal was built from, each already checked against that quote's text.
    # It only ever fills in items -- windows are the extractor's alone.
    prices = json.load(open(PRICES_JSON, encoding="utf-8")) if os.path.exists(PRICES_JSON) else {}
    photos = json.load(open(PHOTOS_JSON, encoding="utf-8")) if os.path.exists(PHOTOS_JSON) else {}
    # Written by ingest/geocode_venues.py. Without it the app still works, it
    # just cannot rank by distance or tell you whether you can make it in time.
    coords = json.load(open(COORDS_JSON, encoding="utf-8")) if os.path.exists(COORDS_JSON) else {}

    # The venue base: every licensed premises in the corpus, keyed on its PLCB
    # LID (ingest/build_venue_base.py). This is what the board is a list OF. A
    # deal is an attribute some of them have -- and the ones that don't are the
    # whole point, because a venue nobody can see is a venue nobody can correct.
    base = json.load(open(BASE_JSON, encoding="utf-8")) if os.path.exists(BASE_JSON) else {}
    if not base:
        print("  ! data/venue_base.json missing -- shipping ONLY deal-bearing venues.\n"
              "    Run ingest/build_venue_base.py (needs data/venues.csv).")

    # A second licence at one building was collapsed into the row that holds the
    # card; a deal crawled against the sibling LID belongs on that same card.
    canon = {lid: lid for lid in base}
    for lid, v in base.items():
        for other in v.get("also_lids", []):
            canon[other] = lid
    # Fallback for a deal whose LID predates the base (the hand-written seed has
    # no LID at all): the number and the ZIP, which is enough to tell two bars
    # apart and is the same key the seed/extract merge above uses.
    by_addr = {}
    for lid, v in base.items():
        by_addr.setdefault(norm_addr(v["address"]), lid)

    def base_lid_for(venue):
        lid = canon.get(str(venue.get("lid") or ""))
        return lid or by_addr.get(norm_addr(venue["address"]))

    by_zone, rejected, hidden = {}, 0, 0
    deals_by_lid, orphans = {}, []

    def surviving(venue):
        """The deals of one venue that are fit to publish: past the PA
        validators, and not decayed out from under their own age."""
        nonlocal rejected, hidden
        deals = []
        for deal in venue.get("deals", []):
            extra = prices.get(venue["id"])
            if extra and deal.get("verified_by") == "auto_extract" and not deal.get("items"):
                # Applied before the validators, not after, so a price the model
                # read still has to clear the same PA checks as any other item.
                deal = dict(deal, items=extra, items_source="llm_extract")
            errs = validate_deal(deal)
            if errs:
                rejected += 1
                print(f"  rejected: {venue['name']} -- {errs[0]}")
                continue
            conf, _age = decay(deal["confidence"], deal["last_verified_at"], today)
            if conf == "hidden":
                hidden += 1
                continue
            # Ship the facts (confidence as sourced, plus the absolute date) and
            # let the app derive age and any demotion when it renders.
            deals.append(dict(deal))
        for e in validate_food_combo_count(deals):
            print(f"  rejected: {venue['name']} -- {e}")
            deals = []
        return deals

    def place(venue, deals):
        lid = base_lid_for(venue)
        if lid is None:
            # A deal for a premises the base has never heard of. It still ships
            # -- a proven happy hour is not something to drop over a join -- but
            # it is counted, because a rising number here means the base is stale.
            orphans.append(venue["name"])
        key = lid or f"orphan:{venue['id']}"
        held = deals_by_lid.get(key)
        # Two licences at one building: the higher-priority source first, and
        # within one source the richer read rather than whichever sorted first.
        if held is None or (venue.get("_rank", 9), -len(deals)) < (
            held[0].get("_rank", 9), -len(held[1])
        ):
            deals_by_lid[key] = (venue, deals)

    for venue in payload["venues"]:
        deals = surviving(venue)
        if deals:
            place(venue, deals)

    # The duplicates merge set aside. One publishes only where the source that
    # outranked it ended up with nothing left to say.
    for venue, beat_by in reserve:
        if (base_lid_for(beat_by) or f"orphan:{beat_by['id']}") in deals_by_lid:
            continue
        deals = surviving(venue)
        if deals:
            print(f"  fallback: {venue['name']} -- {beat_by['name']} outranked it "
                  "and then published nothing")
            place(venue, deals)

    for key, (venue, deals) in deals_by_lid.items():
        b = base.get(key) or {}
        v = {
            "id": b.get("lid") or venue["id"],
            "lid": b.get("lid"),
            # The id every shared link minted before the board was keyed on LIDs.
            # #v=iron-hill-media must keep opening Iron Hill.
            "slug": venue["id"],
            # A hand-checked seed name is a person's reading of the sign; below
            # it, the trade name Places resolved beats the crawler's.
            "name": venue["name"] if venue.get("verified_by") != "auto_extract"
            else (b.get("name") or venue["name"]),
            "address": b.get("address") or venue["address"],
            "zone_id": venue["zone_id"],
            "website": venue.get("website") or b.get("website"),
            "plcb_name": venue.get("plcb_name") or b.get("plcb_name"),
            "license_type": b.get("license_type", ""),
        }
        at = coords.get(venue["id"])
        if at:
            v["lat"], v["lng"] = at["lat"], at["lng"]
            # A road-level match is a street centroid: good to a block, not a
            # doorway. The app rounds those distances harder.
            v["geo_precision"] = at.get("precision", "?")
        elif b.get("lat") is not None:
            v["lat"], v["lng"], v["geo_precision"] = b["lat"], b["lng"], b["geo_precision"]
        shot = photos.get(venue["id"])
        if shot and os.path.exists(os.path.join(REPO, "web", shot["file"])):
            v["photo"] = {"file": shot["file"], "attribution": shot.get("attribution", "")}
        elif b.get("photo"):
            v["photo"] = b["photo"]
        v["deals"] = deals
        by_zone.setdefault(venue["zone_id"], []).append(v)

    # Then every venue the corpus knows about that no source gave us a window
    # for. It ships with deals: [] and the app renders it as a card asking to be
    # filled in -- that ask IS the coverage plan.
    outside = 0
    for lid, b in base.items():
        if lid in deals_by_lid:
            continue
        if not b["zone_id"]:
            # A licence whose municipality matched no zone -- Croydon, St Peters.
            # There is no zone for a person to select, so a card for it is
            # unreachable, and shipping it invents a nameless zone in the picker.
            outside += 1
            continue
        v = {k: b[k] for k in ("lid", "name", "address", "zone_id", "license_type")
             if k in b}
        v["id"] = lid
        v["plcb_name"] = b["plcb_name"]
        for k in ("website", "lat", "lng", "geo_precision", "photo", "also_lids"):
            if k in b:
                v[k] = b[k]
        v["deals"] = []
        by_zone.setdefault(b["zone_id"], []).append(v)

    merged = collapse_name_collisions(by_zone)

    for venues in by_zone.values():
        # Deal-bearing first, then alphabetical: the bundle order is what the app
        # falls back to whenever two rows score the same.
        venues.sort(key=lambda v: (not v["deals"], v["name"].lower(), v["id"]))

    os.makedirs(OUT_DIR, exist_ok=True)
    index = []
    for zid, venues in sorted(by_zone.items()):
        # Two files per zone, and the split is a load-time decision, not a
        # taxonomy. The app boots by fetching EVERY zone's deals so it can answer
        # "what's on right now" across the whole area -- 169 venues, small. The
        # venue base is 2,900 and would be a megabyte on a phone in a parking
        # lot, so it ships per zone and is fetched only when that zone is picked.
        dealful = [v for v in venues if v["deals"]]
        rest = [v for v in venues if not v["deals"]]
        meta = {"zone_id": zid, "name": zone_names.get(zid, zid),
                "built_at": today.isoformat()}
        path = os.path.join(OUT_DIR, f"zone-{zid}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict(meta, venues=dealful), fh, indent=1)
        rest_path = os.path.join(OUT_DIR, f"venues-{zid}.json")
        with open(rest_path, "w", encoding="utf-8") as fh:
            json.dump(dict(meta, venues=rest), fh, indent=1)
        index.append(
            {
                "id": zid,
                "name": zone_names.get(zid, zid),
                "venues": len(venues),
                # How many of them we can actually tell you the hours for. The
                # zone picker shows this, because "59 venues, 6 with hours" is
                # the honest state of the board and hiding it would be the lie.
                "with_deals": len(dealful),
                "deals": sum(len(v["deals"]) for v in venues),
            }
        )
        print(f"  {zid:<32}{len(venues):>4} venues{len(dealful):>4} with hours  "
              f"{os.path.getsize(path):>6,} + {os.path.getsize(rest_path):>7,} bytes")

    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"built_at": today.isoformat(), "zones": index}, fh, indent=1)

    # What is published, keyed by licence ID. The Worker reads this to answer one
    # question before it auto-approves a photo: does this venue already have
    # hours? Adding hours to a blank venue publishes itself; CHANGING hours that
    # are already on the board is the damaging case and waits for a person. The
    # admin page reads the same file to show a reviewer what approving replaces.
    #
    # Deliberately small -- windows and provenance, no items, no prices. It is
    # fetched by a Worker on a submission, not by a reader.
    board = {}
    for venue in (v for vs in by_zone.values() for v in vs if v["deals"]):
        entry = {
            "name": venue["name"],
            "deals": [
                {"type": d["type"], "windows": d["windows"],
                 "source": {"kind": (d.get("source") or {}).get("kind", "")}}
                for d in venue["deals"]
            ],
        }
        for key in [venue.get("lid")] + list(venue.get("also_lids") or []):
            if key:
                board[str(key)] = entry
    with open(os.path.join(OUT_DIR, "board-by-lid.json"), "w", encoding="utf-8") as fh:
        json.dump(board, fh, indent=1)

    # Licence ID -> zone, for EVERY venue including the 2,729 with no hours.
    # The live overlay needs it: a photo that auto-publishes is by definition
    # for a venue with nothing on the board, so that venue is not in any deals
    # bundle and the app has to be told which zone base to go and fetch.
    lid_zone = {}
    for venue in (v for vs in by_zone.values() for v in vs):
        for key in [venue.get("lid")] + list(venue.get("also_lids") or []):
            if key:
                lid_zone[str(key)] = venue["zone_id"]
    with open(os.path.join(OUT_DIR, "lid-zone.json"), "w", encoding="utf-8") as fh:
        json.dump(lid_zone, fh, separators=(",", ":"))

    # Every venue we hold, by name, so a submitter can find their bar.
    #
    # The submit picker used to search only what the app had in memory: the 169
    # venues with hours, plus whatever zone the reader had already opened. Type
    # "Taku" with no town picked and it answered "no match" about a venue that
    # has been in our data all along -- and a missing route reads exactly like a
    # missing record, so the person concludes we do not have their bar and
    # stops. This is the file that lets it answer honestly.
    #
    # Rows, not objects, and fetched only when the picker opens -- never at
    # boot. It is ~2,900 entries and the reader who is not submitting a photo
    # should not pay for it. Zone travels with each row because two bars share a
    # name often enough that the town is what tells them apart.
    name_index = [
        [str(v["lid"]), v["name"], v.get("address", ""), v["zone_id"]]
        for vs in by_zone.values()
        for v in vs
        if v.get("lid")
    ]
    name_index.sort(key=lambda r: (r[1].lower(), r[0]))
    with open(os.path.join(OUT_DIR, "name-index.json"), "w", encoding="utf-8") as fh:
        json.dump({"built_at": today.isoformat(),
                   "zone_names": zone_names,
                   "venues": name_index}, fh, separators=(",", ":"))

    published = [v for vs in by_zone.values() for v in vs]
    dealful = [v for v in published if v["deals"]]
    # The service worker cache name has always keyed on the count of what ships.
    # It must keep keying on the DEAL count: the venue base moves only when the
    # PLCB corpus does, so keying on it would stop evicting on a deal-only build.
    stamp_service_worker(today.isoformat(), len(dealful))
    located = sum(1 for v in published if "lat" in v)
    print(f"\n{sum(z['deals'] for z in index)} deals across {len(index)} zones"
          f"  ({rejected} rejected by validators, {hidden} decayed out)")
    print(f"{len(published)} venues ship, {len(dealful)} with a published window "
          f"({len(published) - len(dealful)} asking to be filled in)")
    if merged:
        print(f"  {merged} second licence(s) at a bar already on the board were "
              f"collapsed into its card (one bar, one card)")
    if outside:
        print(f"  {outside} licensed venue(s) sit outside every zone and cannot be "
              f"reached in the UI -- add a zone in data/zones.json to surface them")
    if orphans:
        print(f"  ! {len(orphans)} deal(s) matched no venue in the base "
              f"-- rebuild it: {', '.join(orphans[:3])}")
    print(f"{located}/{len(published)} venues have coordinates"
          + ("" if located == len(published) else "  -- run ingest/geocode_venues.py"))


if __name__ == "__main__":
    main()
