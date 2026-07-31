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
OUT_DIR = os.path.join(REPO, "web", "data")


def decay(confidence, verified_at, today):
    """A deal never disappears, it demotes. SPEC section 6."""
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

    by_zone, rejected, hidden = {}, 0, 0
    for venue in payload["venues"]:
        deals = []
        for deal in venue.get("deals", []):
            errs = validate_deal(deal)
            if errs:
                rejected += 1
                print(f"  rejected: {venue['name']} -- {errs[0]}")
                continue
            conf, age = decay(deal["confidence"], deal["last_verified_at"], today)
            if conf == "hidden":
                hidden += 1
                continue
            d = dict(deal)
            d["confidence"] = conf
            d["age_days"] = age
            deals.append(d)
        for e in validate_food_combo_count(deals):
            print(f"  rejected: {venue['name']} -- {e}")
            deals = []
        if not deals:
            continue
        v = {k: venue[k] for k in ("id", "name", "address", "zone_id", "website")}
        v["plcb_name"] = venue.get("plcb_name")
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

    print(f"\n{sum(z['deals'] for z in index)} deals across {len(index)} zones"
          f"  ({rejected} rejected by validators, {hidden} decayed out)")


if __name__ == "__main__":
    main()
