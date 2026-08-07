#!/usr/bin/env python3
"""Emit the per-zone JSON bundles the web app ships (SPEC section 9).

Reads data/deals_seed.json, drops anything the PA validators reject, applies
the confidence decay ladder (SPEC section 6), and writes web/data/.

    python ingest/build_bundles.py
"""

import datetime
import json
import re
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validate_pa import validate_deal, validate_food_combo_count  # noqa: E402

DEALS_JSON = os.path.join(REPO, "data", "deals_seed.json")
EXTRACTED_JSON = os.path.join(REPO, "data", "deals_extracted.json")
ZONES_JSON = os.path.join(REPO, "data", "zones.json")
PRICES_JSON = os.path.join(REPO, "data", "deals_prices_llm.json")
PHOTOS_JSON = os.path.join(REPO, "data", "venue_photos.json")
COORDS_JSON = os.path.join(REPO, "data", "venue_coords.json")
OUT_DIR = os.path.join(REPO, "web", "data")


def norm_addr(address):
    """Enough of an address to tell whether two records are one bar. The seed
    writes '324 W Swedesford Rd, Berwyn PA 19312' where the PLCB row the crawler
    carried says '324 WEST SWEDESFORD ROAD'; the number and the ZIP agree."""
    m = re.search(r"\b(\d{5})\b", address or "")
    n = re.match(r"\s*(\d+)", address or "")
    return (n.group(1) if n else "?", m.group(1) if m else "?")


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


def sw_cache_name(built_at, n_published):
    """The cache name a build of this shape must ship.

    The service worker precaches data/index.json, and its cache name is the ONLY
    thing that evicts. A hand-edited constant went four builds without changing,
    so devices kept serving an index from an older corpus -- King of Prussia read
    1 venue while the server had said 3 for hours, with nothing on either side to
    show a disagreement. The venue count rides along with the date so that a
    second build on the same day still evicts.
    """
    return f"hhf-{built_at}-{n_published}"


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
    # Machine-extracted deals (ingest/extract_deals.py) ship alongside the
    # hand-verified seed, never merged into it. Where both describe one venue the
    # seed wins outright -- a person read that page, a regex read this one.
    if os.path.exists(EXTRACTED_JSON):
        seen = {v["id"] for v in payload["venues"]}
        seen |= {norm_addr(v["address"]) for v in payload["venues"]}
        auto = json.load(open(EXTRACTED_JSON, encoding="utf-8"))["venues"]
        fresh = [v for v in auto if v["id"] not in seen and norm_addr(v["address"]) not in seen]
        print(f"  +{len(fresh)} machine-extracted venues "
              f"({len(auto) - len(fresh)} already hand-verified)")
        payload = dict(payload, venues=payload["venues"] + fresh)
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

    by_zone, rejected, hidden = {}, 0, 0
    for venue in payload["venues"]:
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
        if not deals:
            continue
        v = {k: venue[k] for k in ("id", "name", "address", "zone_id", "website")}
        v["plcb_name"] = venue.get("plcb_name")
        at = coords.get(venue["id"])
        if at:
            v["lat"], v["lng"] = at["lat"], at["lng"]
            # A road-level match is a street centroid: good to a block, not a
            # doorway. The app rounds those distances harder.
            v["geo_precision"] = at.get("precision", "?")
        shot = photos.get(venue["id"])
        if shot and os.path.exists(os.path.join(REPO, "web", shot["file"])):
            v["photo"] = {"file": shot["file"], "attribution": shot.get("attribution", "")}
        v["deals"] = deals
        by_zone.setdefault(venue["zone_id"], []).append(v)

    os.makedirs(OUT_DIR, exist_ok=True)
    index = []
    for zid, venues in sorted(by_zone.items()):
        path = os.path.join(OUT_DIR, f"zone-{zid}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                {"zone_id": zid, "name": zone_names.get(zid, zid), "built_at": today.isoformat(),
                 "venues": venues},
                fh,
                indent=1,
            )
        index.append(
            {
                "id": zid,
                "name": zone_names.get(zid, zid),
                "venues": len(venues),
                "deals": sum(len(v["deals"]) for v in venues),
            }
        )
        print(f"  {zid:<32}{len(venues):>3} venues  {os.path.getsize(path):>6,} bytes")

    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"built_at": today.isoformat(), "zones": index}, fh, indent=1)

    published = [v for vs in by_zone.values() for v in vs]
    stamp_service_worker(today.isoformat(), len(published))
    located = sum(1 for v in published if "lat" in v)
    print(f"\n{sum(z['deals'] for z in index)} deals across {len(index)} zones"
          f"  ({rejected} rejected by validators, {hidden} decayed out)")
    print(f"{located}/{len(published)} venues have coordinates"
          + ("" if located == len(published) else "  -- run ingest/geocode_venues.py"))


if __name__ == "__main__":
    main()
