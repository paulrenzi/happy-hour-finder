#!/usr/bin/env python3
"""Seed northern Delaware from Google Places, because there is no PLCB there.

    python ingest/seed_places_de.py --dry-run     # scope + cost, no calls
    python ingest/seed_places_de.py --spend       # actually seed
    python ingest/seed_places_de.py --zone wilmington --spend

🛑 THIS IS NOT THE SAME KIND OF SEED AS PENNSYLVANIA'S, AND THE DIFFERENCE
MATTERS MORE THAN THE CODE DOES.

`seed_plcb.py` starts from the state's own list of everyone licensed to pour.
That list is a DENOMINATOR: it answers "did we miss a bar?", and every coverage
number in this repo is a fraction of it. Delaware publishes no equivalent. Its
open-data portal carries business licences ("RETAILER RESTAURANT", 2,497
statewide) with no liquor signal, and the Alcoholic Beverage Control
Commissioner's licensee list is not machine-readable.

So the Delaware seed is Google's opinion of what is there. That is a perfectly
good WORKING LIST and a bad denominator, and the two must never be confused:

  * a Delaware zone's "N venues" is what Google returned, not what exists;
  * "0 of 40 publish a happy hour" in Delaware does NOT mean the same thing as
    it does in Media, where the 44 is the state's own count;
  * a Delaware bar Google does not list is invisible to us and we cannot know
    it. In Pennsylvania that class is measurable. Here it is not.

Rows are written to data/venues_de.csv in the venues.csv schema, TRACKED in git
(unlike venues.csv, which is a free regeneration of a public file -- this one
costs money to rebuild). seed_plcb.py appends it.

🛑 A DELAWARE VENUE STILL CANNOT PUBLISH until validate_pa.RULES["DE"] is
filled in and signed off. Crossing a state line changes the law, not just the
data source. Seeding is deliberately allowed to run ahead of that: the crawl
and the extractor are jurisdiction-blind, and the single door onto the board is
build_bundles.py, which refuses a state with no ruleset.
"""

import argparse
import csv
import json
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from discover_places import load_key  # noqa: E402

OUT_CSV = os.path.join(REPO, "data", "venues_de.csv")
ZONES_JSON = os.path.join(REPO, "data", "zones.json")
SEARCH = "https://places.googleapis.com/v1/places:searchText"

MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.location", "places.websiteUri", "places.primaryType",
    "places.photos", "nextPageToken",
])
USD_PER_SEARCH = 0.035  # Enterprise SKU: websiteUri and photos are in the mask

# The types that can pour. `restaurant` is in the net on purpose -- most of a
# town's happy hours are in restaurants, and a place with none is refused
# downstream by the extractor at no cost.
TYPES = ["bar", "pub", "wine_bar", "bar_and_grill", "brewery", "restaurant"]

# Northern Delaware, by drinking district rather than by municipality: the same
# rule the PA zones follow. A district is what a person would walk between.
#
# 🛑 middletown_de is SOUTH of the C&D Canal. It is here because it is the rest
# of New Castle County and rides with the northern zones commercially, but if
# the brief is literally "above the canal" it is the one zone to delete.
ZONES = {
    "wilmington": {
        "name": "Wilmington",
        "anchor": "Trolley Square, Riverfront, Market St",
        "queries": [
            "Trolley Square, Wilmington, Delaware",
            "Riverfront, Wilmington, Delaware",
            "Market Street, downtown Wilmington, Delaware",
            "Union Street, Wilmington, Delaware",
            "Little Italy, Wilmington, Delaware",
        ],
    },
    "newark_de": {
        "name": "Newark, DE",
        "anchor": "Main St",
        "queries": [
            "Main Street, Newark, Delaware",
            "Newark, Delaware",
            "Christiana, Delaware",
            "Bear, Delaware",
            "Glasgow, Delaware",
        ],
    },
    "hockessin_greenville": {
        "name": "Hockessin & Greenville",
        "anchor": "Lancaster Pike, Kennett Pike",
        "queries": [
            "Hockessin, Delaware",
            "Greenville, Delaware",
            "Centreville, Delaware",
            "Pike Creek, Delaware",
        ],
    },
    "new_castle_de": {
        "name": "New Castle & Claymont",
        "anchor": "Delaware St, Philadelphia Pike",
        "queries": [
            "New Castle, Delaware",
            "Claymont, Delaware",
            "Delaware City, Delaware",
            "Elsmere, Delaware",
            "Newport, Delaware",
        ],
    },
    "middletown_de": {
        "name": "Middletown",
        "anchor": "Main St",
        "queries": [
            "Middletown, Delaware",
            "Odessa, Delaware",
            "Townsend, Delaware",
        ],
    },
    # The Sussex County coast, added 2026-09-04 on Paul's ask. These are NOT
    # northern Delaware and do not ride with the zones above commercially or
    # geographically -- they are ninety miles south, they are seasonal, and
    # they carry the densest happy-hour culture in the state. They get their
    # own box (BOXES below), their own county, and their own market box in
    # tests/test_ingest.py.
    #
    # 🛑 Note what this reverses: the DE_BOX comment below was written to
    # EXCLUDE exactly these towns, because a Hockessin query kept returning
    # Crooked Hammock in Lewes. The contamination and the target are the same
    # rows. That is why the box is now per-zone rather than one constant --
    # a single widened box would have quietly re-admitted Rehoboth to
    # Hockessin's results and nothing would have errored.
    "rehoboth_beach": {
        "name": "Rehoboth Beach",
        "anchor": "Rehoboth Ave, the Boardwalk",
        "county": "Sussex County",
        "box": "SUSSEX_COAST",
        "queries": [
            "Rehoboth Avenue, Rehoboth Beach, Delaware",
            "Rehoboth Beach boardwalk, Delaware",
            "Rehoboth Beach, Delaware",
            "Midway, Rehoboth Beach, Delaware",
        ],
    },
    "dewey_beach": {
        "name": "Dewey Beach",
        "anchor": "Coastal Highway",
        "county": "Sussex County",
        "box": "SUSSEX_COAST",
        "queries": [
            "Dewey Beach, Delaware",
            "Coastal Highway, Dewey Beach, Delaware",
        ],
    },
    "lewes": {
        "name": "Lewes",
        "anchor": "Second St, Savannah Rd",
        "county": "Sussex County",
        "box": "SUSSEX_COAST",
        "queries": [
            "Second Street, Lewes, Delaware",
            "Lewes, Delaware",
            "Savannah Road, Lewes, Delaware",
            "Nassau, Delaware",
        ],
    },
}


def lid_for(place_id):
    """A stable, collision-free id in the LID key space.

    Never a number: a PLCB LID is a number, and a Delaware row must not be
    mistakable for one at a glance in a log line or a bundle.
    """
    import hashlib

    return "DE" + hashlib.sha1(place_id.encode()).hexdigest()[:10]


def search(key, query, kind, requests, token=None):
    body = {"textQuery": f"{kind.replace('_', ' ')} in {query}",
            "includedType": kind, "pageSize": 20}
    if token:
        body["pageToken"] = token
    r = requests.post(SEARCH, headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": MASK},
                      json=body, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d.get("places", []), d.get("nextPageToken")


# 🛑 NORTHERN Delaware, as a box, because ", DE" is not a location.
#
# A text search for "brewery in Hockessin, Delaware" returned Crooked Hammock
# Brewery in LEWES -- ninety miles south, on the ocean -- and 16 more from
# Rehoboth Beach, Dover, Smyrna and Millsboro. Every one of them is genuinely
# in Delaware, which is all the state test asked. Places widens a query it
# cannot satisfy locally, and the whole state is a small enough haystack that
# it succeeds.
#
# The box is northern New Castle County plus MOT: north of Smyrna, east of the
# Maryland line. Caught by tests/test_ingest.py's geocode disc, which is the
# only check in the repo that ever looks at where a venue actually IS.
DE_BOX = {"lat": (39.35, 39.92), "lng": (-75.90, -75.35)}

# The Sussex coast, as its own box rather than a widening of the one above.
# Lewes sits at 38.77, Rehoboth at 38.72, Dewey at 38.69; the northern box
# starts at 39.35, so every beach row would have been dropped by in_delaware()
# with no error and no log line -- a seeded zone that silently returns nothing.
# East edge is ocean. West edge stops short of Georgetown (-75.385) so the
# Route 1 corridor is in and the inland county is out.
SUSSEX_COAST_BOX = {"lat": (38.60, 38.85), "lng": (-75.30, -75.02)}

BOXES = {"NORTHERN_DE": DE_BOX, "SUSSEX_COAST": SUSSEX_COAST_BOX}

# 🛑 A row's zone comes from the QUERY that found it, and inside a small box
# that is not good enough. The three beach towns are ten minutes apart, so
# "restaurant in Lewes, Delaware" returns Rehoboth and Dewey freely: the first
# seeded zone kept 30 Rehoboth bars and 4 Dewey ones under `lewes`, plus
# Millsboro, Milton and Bethany Beach, and every one of them passed the box.
# The box answers "is this the right REGION"; only the address answers "is this
# the right TOWN". So for these zones the address decides, and a town nobody
# asked for is refused rather than filed under its nearest neighbour.
TOWN_ZONES = {
    "lewes": "lewes",
    "rehoboth beach": "rehoboth_beach",
    "dewey beach": "dewey_beach",
}


def town_of(address):
    """The town a Delaware address names, lowercased, or None."""
    m = re.search(r",\s*([A-Za-z .'-]+),\s*DE\b", address or "")
    return m.group(1).strip().lower() if m else None


def zone_from_address(address, default):
    """Re-file a beach row onto the town its own address names.

    Returns None for a town outside the three, which drops the row: a Bethany
    Beach bar published under 'Lewes' is a wrong claim, and absent beats wrong.
    """
    return TOWN_ZONES.get(town_of(address), None) if default in TOWN_ZONES.values() \
        else default


def in_delaware(place, box=DE_BOX):
    if ", DE " not in (place.get("formattedAddress") or ""):
        return False
    loc = place.get("location") or {}
    lat, lng = loc.get("latitude"), loc.get("longitude")
    if lat is None or lng is None:
        return False
    return (box["lat"][0] < lat < box["lat"][1]
            and box["lng"][0] < lng < box["lng"][1])


SITES_JSON = os.path.join(REPO, "data", "venue_sites.json")


def merge_sites():
    """Put the seeded websites in the crawl frontier. No API calls.

    The PA lane needs a whole argument about which joins are strong enough to
    crawl FOR EVIDENCE (discover_places.EVIDENCE_SAFE_PREFIXES), because there
    the licence and the website come from two different places and have to be
    matched. Here they do not: one Places record carried the business, its
    address and its website together, so there is no join to be wrong about.
    """
    sites = json.load(open(SITES_JSON, encoding="utf-8"))
    added = 0
    with open(OUT_CSV, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if not r.get("website") or r["lid"] in sites:
                continue
            sites[r["lid"]] = {
                "address": r["address"], "kind": None,
                "lat": float(r["lat"]) if r["lat"] else None,
                "lng": float(r["lng"]) if r["lng"] else None,
                "matched_by": "places text search (DE seed)",
                "name": r["name"], "opening_hours": None, "osm": None,
                "osm_name": r["name"], "phone": None,
                "website": r["website"], "zone_id": r["zone_id"],
            }
            added += 1
    with open(SITES_JSON + ".new", "w", encoding="utf-8") as fh:
        json.dump(sites, fh, indent=1, sort_keys=True, ensure_ascii=False)
    os.replace(SITES_JSON + ".new", SITES_JSON)
    print(f"+{added} Delaware sites -> {len(sites)} in the frontier")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merge-sites", action="store_true",
                    help="add the seeded websites to the crawl frontier (no API calls)")
    ap.add_argument("--zone", help="one zone only")
    ap.add_argument("--dry-run", action="store_true", help="scope + cost, no calls")
    ap.add_argument("--spend", action="store_true", help="run the billed searches")
    ap.add_argument("--pages", type=int, default=2,
                    help="pages per query (20 results each, max 3)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.merge_sites:
        return merge_sites()

    zones = {k: v for k, v in ZONES.items() if not args.zone or k == args.zone}
    if not zones:
        sys.exit(f"no such zone {args.zone!r} -- have {', '.join(ZONES)}")
    calls = sum(len(z["queries"]) for z in zones.values()) * len(TYPES)
    print(f"{len(zones)} zone(s), {calls} first-page searches "
          f"(up to {args.pages} pages each)")
    print(f"about ${calls * args.pages * USD_PER_SEARCH:,.2f} at list price, "
          f"worst case -- fewer where a query has one page")
    if args.dry_run or not args.spend:
        print("\nNothing spent. Re-run with --spend.")
        return

    key = load_key()
    if not key:
        sys.exit("No GOOGLE_PLACES_API_KEY. Put one in happy-hour-finder/.env")
    import requests

    rows = {}
    if os.path.exists(OUT_CSV):
        for r in csv.DictReader(open(OUT_CSV, encoding="utf-8", newline="")):
            rows[r["lid"]] = r

    spent = 0
    for zid, z in zones.items():
        found = 0
        box = BOXES[z.get("box", "NORTHERN_DE")]
        dropped_outside = 0
        dropped_town = 0
        for q in z["queries"]:
            for kind in TYPES:
                token, page = None, 0
                while page < args.pages:
                    try:
                        places, token = search(key, q, kind, requests, token)
                    except Exception as e:  # noqa: BLE001 -- one query is not the run
                        print(f"  {zid:<22} {kind:<14} {q[:34]:<36} failed: {str(e)[:60]}")
                        break
                    spent += 1
                    page += 1
                    for p in places:
                        if not in_delaware(p, box):
                            dropped_outside += 1
                            continue
                        lid = lid_for(p["id"])
                        if lid in rows:
                            continue
                        addr = p["formattedAddress"].replace(", USA", "")
                        zone_id = zone_from_address(addr, zid)
                        if zone_id is None:
                            dropped_town += 1
                            continue
                        rows[lid] = {
                            "lid": lid,
                            "license_number": "",
                            # No licence class exists for these rows and none is
                            # invented: an empty field reads as "unknown", a
                            # borrowed PA class would read as a fact.
                            "license_type": "",
                            "tier": "core",
                            "name": p["displayName"]["text"],
                            "licensee": "",
                            "address": addr,
                            "zip": (p["formattedAddress"].split()[-2]
                                    if p["formattedAddress"].split() else ""),
                            "municipality": q.split(",")[0].strip(),
                            "county": z.get("county", "New Castle County"),
                            "zone_id": zone_id,
                            "miles_from_kop": "",
                            "expiration_date": "",
                            "place_id": p["id"],
                            "website": p.get("websiteUri") or "",
                            "lat": (p.get("location") or {}).get("latitude", ""),
                            "lng": (p.get("location") or {}).get("longitude", ""),
                            "primary_type": p.get("primaryType") or "",
                        }
                        found += 1
                    if not token:
                        break
                    time.sleep(0.2)
        print(f"  {zid:<22} +{found:<4} ({dropped_outside} outside the "
              f"{z.get('box', 'NORTHERN_DE')} box"
              + (f", {dropped_town} in a town outside the zone set" if dropped_town else "")
              + ")")
        # A zone that keeps nothing while its queries return plenty is a box
        # that does not contain the town, not a town with no bars. That is the
        # failure this seeder is most likely to have and the least likely to
        # notice, so it says so instead of printing a tidy +0.
        if found == 0 and dropped_outside:
            print(f"  ! {zid}: kept NOTHING and dropped {dropped_outside} -- "
                  f"check BOXES[{z.get('box', 'NORTHERN_DE')!r}] contains the town")

    fields = list(next(iter(rows.values())).keys()) if rows else []
    with open(OUT_CSV + ".new", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for lid in sorted(rows):
            w.writerow(rows[lid])
    os.replace(OUT_CSV + ".new", OUT_CSV)
    print(f"\n{len(rows)} Delaware venues, {spent} searches "
          f"(about ${spent * USD_PER_SEARCH:,.2f}) -> {os.path.relpath(OUT_CSV, REPO)}")
    print("🛑 Google's list, not the state's. It is a working list, never a "
          "coverage denominator -- see the module docstring.")
    print("next: python ingest/seed_plcb.py  (appends this file to venues.csv)")


if __name__ == "__main__":
    main()
