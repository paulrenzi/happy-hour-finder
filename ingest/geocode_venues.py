#!/usr/bin/env python3
"""Resolve each seed venue's street address to a coordinate.

Distance is the ranking input the app cannot fake: "is it live" only matters
once you know "can I get there." SPEC section 7 ranks by drive time, and nothing
in the corpus carried a lat/lng until this ran.

Uses OpenStreetMap's Nominatim -- no API key, no billing, and the result is
ODbL-licensed so it can be stored and shipped, which the Places photo lane
cannot. Nominatim's usage policy caps this at 1 request/second and requires a
real User-Agent; both are honored below.

Keys on ADDRESS, not name. PHASE-0-FINDINGS section 2 measured that ~37% of
venues cannot be identified by their registry name at all, and two "Iron Hill
Brewery" rows are different bars.

    python ingest/geocode_venues.py            # fills in what is missing
    python ingest/geocode_venues.py --force    # re-resolve everything
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEALS_JSON = os.path.join(REPO, "data", "deals_seed.json")
OUT_JSON = os.path.join(REPO, "data", "venue_coords.json")

ENDPOINT = "https://nominatim.openstreetmap.org/search"
UA = "happy-hour-finder/0.1 (https://github.com/paulrenzi/happy-hour-finder)"
RATE_LIMIT_SECONDS = 1.1  # Nominatim asks for <=1/s; leave headroom.

# A coordinate outside this box is a resolution failure, not a venue. The seed
# market is a 20-mile disc around King of Prussia (40.089, -75.396); Nominatim
# happily returns a same-named street in another state if the match is loose.
BBOX = {"lat": (39.6, 40.6), "lng": (-76.0, -74.8)}


ADDRESS_RE = re.compile(r"^(?P<street>.+?),\s*(?P<city>[^,]+?)\s+(?P<state>[A-Z]{2})\s+(?P<zip>\d{5})$")


def split_address(address):
    """'800 Spring Mill Ave, Conshohocken PA 19428' -> its parts, or None."""
    m = ADDRESS_RE.match(address.strip())
    return m.groupdict() if m else None


def strip_range(street):
    """'30-32 E State St' -> '30 E State St'.

    A hyphenated house-number range is how a venue describes its storefront and
    is not a thing OSM can match -- both Iron Hill and Barnaby's missed on the
    range and resolved exactly on the first number.
    """
    return re.sub(r"^(\d+)\s*-\s*\d+\b", r"\1", street.strip())


def query(params):
    params = dict(params, format="json", limit=1, addressdetails=1, countrycodes="us")
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as fh:
        rows = json.load(fh)
    return rows[0] if rows else None


def strategies(address):
    """Query forms to try in order, each labelled for the log.

    Ordered most-constrained first, so the ZIP is always in play: '324 W
    Swedesford Rd' exists in BOTH 19312 and 19341, thirty miles apart, and a
    query that drops the ZIP picks the wrong one without complaining.
    """
    parts = split_address(address)
    if not parts:
        yield "freeform", {"q": address}
        return
    street = strip_range(parts["street"])
    yield "full", {
        "street": street, "city": parts["city"], "state": parts["state"], "postalcode": parts["zip"]
    }
    # Berwyn and Plymouth Meeting are census places, not OSM cities -- passing
    # them as `city` returns nothing at all. Street + ZIP is the reliable form.
    yield "street+zip", {"street": street, "postalcode": parts["zip"]}
    yield "freeform", {"q": f"{street}, {parts['city']}, {parts['state']} {parts['zip']}"}


def geocode(address, sleep):
    """First strategy that lands inside the seed market wins."""
    for i, (label, params) in enumerate(strategies(address)):
        if i:
            time.sleep(sleep)
        hit = query(params)
        if not hit:
            continue
        lat, lng = float(hit["lat"]), float(hit["lon"])
        if BBOX["lat"][0] <= lat <= BBOX["lat"][1] and BBOX["lng"][0] <= lng <= BBOX["lng"][1]:
            return hit, lat, lng, label
        print(f"    (rejected {label}: {lat},{lng} is outside the seed market)")
    return None, None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-resolve venues already cached")
    args = ap.parse_args()

    payload = json.load(open(DEALS_JSON, encoding="utf-8"))
    cache = {}
    if os.path.exists(OUT_JSON) and not args.force:
        cache = json.load(open(OUT_JSON, encoding="utf-8"))

    todo = [v for v in payload["venues"] if v["id"] not in cache]
    if not todo:
        print(f"all {len(payload['venues'])} venues already resolved -- --force to redo")
        return 0

    failures = 0
    for i, venue in enumerate(todo):
        if i:
            time.sleep(RATE_LIMIT_SECONDS)
        try:
            hit, lat, lng, how = geocode(venue["address"], RATE_LIMIT_SECONDS)
        except Exception as exc:  # a transport failure is not a missing venue
            print(f"  ERROR {venue['id']}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        if not hit:
            print(f"  MISS  {venue['id']}: no match for {venue['address']!r}")
            failures += 1
            continue

        cache[venue["id"]] = {
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "queried": venue["address"],
            "resolved": hit["display_name"],
            "matched_by": how,
            # place_rank 30 = a building; 26 = a whole road. A road-level match
            # is a street centroid, so its distance is good to a block, not a
            # doorway -- worth knowing before anyone trusts "0.3 mi".
            "precision": hit.get("addresstype", "?"),
            "place_rank": hit.get("place_rank"),
            "osm": f"{hit['osm_type']}/{hit['osm_id']}",
        }
        # Print the RESOLVED string, never just "ok". A wrong match returns a
        # plausible coordinate for the wrong building and looks like success.
        print(f"  {venue['id']:<32} {lat:9.5f},{lng:10.5f}  [{how}]  {hit['display_name'][:62]}")

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)
        fh.write("\n")

    print(f"\n{len(cache)}/{len(payload['venues'])} venues resolved -> data/venue_coords.json")
    print("Eyeball every 'resolved' line above against the address it was asked for.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
