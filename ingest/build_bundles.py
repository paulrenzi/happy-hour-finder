#!/usr/bin/env python3
"""Emit the per-zone JSON bundles the web app ships (SPEC section 9).

Reads data/deals_seed.json, drops anything the PA validators reject, applies
the confidence decay ladder (SPEC section 6), and writes web/data/.

    python ingest/build_bundles.py
"""

import datetime
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validate_pa import validate_deal, validate_food_combo_count  # noqa: E402

DEALS_JSON = os.path.join(REPO, "data", "deals_seed.json")
ZONES_JSON = os.path.join(REPO, "data", "zones.json")
PHOTOS_JSON = os.path.join(REPO, "data", "venue_photos.json")
COORDS_JSON = os.path.join(REPO, "data", "venue_coords.json")
OUT_DIR = os.path.join(REPO, "web", "data")


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


def main():
    today = datetime.date.today()
    payload = json.load(open(DEALS_JSON, encoding="utf-8"))
    zones = json.load(open(ZONES_JSON, encoding="utf-8"))
    zone_names = {z["id"]: z["name"] for z in zones["zones"]}
    # Optional: written by ingest/fetch_venue_photos.py. A venue with no entry
    # gets the app's generated tile instead.
    photos = json.load(open(PHOTOS_JSON, encoding="utf-8")) if os.path.exists(PHOTOS_JSON) else {}
    # Written by ingest/geocode_venues.py. Without it the app still works, it
    # just cannot rank by distance or tell you whether you can make it in time.
    coords = json.load(open(COORDS_JSON, encoding="utf-8")) if os.path.exists(COORDS_JSON) else {}

    by_zone, rejected, hidden = {}, 0, 0
    for venue in payload["venues"]:
        deals = []
        for deal in venue.get("deals", []):
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
    located = sum(1 for v in published if "lat" in v)
    print(f"\n{sum(z['deals'] for z in index)} deals across {len(index)} zones"
          f"  ({rejected} rejected by validators, {hidden} decayed out)")
    print(f"{located}/{len(published)} venues have coordinates"
          + ("" if located == len(published) else "  -- run ingest/geocode_venues.py"))


if __name__ == "__main__":
    main()
