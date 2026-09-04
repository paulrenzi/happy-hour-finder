#!/usr/bin/env python3
"""Find venues Google knows about that our PLCB denominator does not.

    python ingest/find_denominator_gaps.py --zone phoenixville --dry-run
    python ingest/find_denominator_gaps.py --zone phoenixville --spend

The Boardroom in Phoenixville (101 Bridge St) found this class the hard way:
it appears NOWHERE in a 60,701-row PLCB active-licence export, in all
likelihood because it pours under a sibling business's distillery licence
rather than a premises licence of its own. Our whole PA denominator is
premises-keyed, so a venue like that is invisible to every tool that starts
from `data/venues.csv` -- it was never seeded, never given a website, never
crawled. `discover_places.py` walks OUR rows looking for a Places match; it
cannot find a row we never had.

This runs the query the other direction: ask Places what bars/restaurants
exist near the zone, then diff by STREET NUMBER (never name -- a third of
PLCB rows are a holding company) against every address already in
`data/venue_base.json`. What is left over is a candidate, not a finding: it
still needs a human or a PLCB address lookup to say why it has no premises
licence, same as the Boardroom did.

🛑 This does not seed venues.csv or write into the PA denominator. Doing that
would blur a list that answers "did we miss a bar?" with a Google opinion of
what exists -- exactly the distinction seed_places_de.py's docstring draws
for Delaware. A confirmed gap goes into `data/deals_seed.json` by hand, the
same route the Boardroom took.

Two things this got wrong on the first pass, both silent:

  * `data/venue_base.json` addresses read "STREET, TOWN PA ZIP" -- ONE comma,
    no comma between the town and the state. A locality regex written for
    Places' "STREET, TOWN, PA ZIP, USA" (two commas) matched every base
    address to no town at all, so nothing the base already held could ever
    match a candidate -- Molly Maguire's, Sedona Taphouse, Stable 12 and
    every other venue Phoenixville already has all came back as "missing."
    normalize_locality() below reads both shapes.
  * A text search with no geographic bound widens exactly the way
    seed_places_de.py's DE_BOX comment already warned about: "restaurant in
    Phoenixville, PA" returned Royersford, Pottstown, Trappe, Limerick,
    Essington and a Wayne wine shop already covered by a DIFFERENT zone.
    Candidates are now filtered to within RADIUS_MILES of the zone's own
    anchor point, geocoded once via Nominatim (free, no key) the same way
    geocode_venues.py resolves the seed corpus.
"""

import argparse
import io
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from discover_places import load_key, street_numbers  # noqa: E402

BASE_JSON = os.path.join(REPO, "data", "venue_base.json")
SEARCH = "https://places.googleapis.com/v1/places:searchText"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "happy-hour-finder/0.1 (https://github.com/paulrenzi/happy-hour-finder)"

MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.location", "places.websiteUri", "places.primaryType",
])
USD_PER_SEARCH = 0.032  # no photos in the mask -- Pro tier, not Enterprise

TYPES = ["bar", "pub", "wine_bar", "bar_and_grill", "brewery", "restaurant"]

# Anchors, not municipality names: a zone's `municipalities` in zones.json are
# PLCB civil-boundary names ("Lower Merion Twp"), which nobody types into a
# map and Places resolves poorly. RADIUS_MILES is a walking-and-a-short-drive
# district, not a township -- wide enough to keep Spring City and Kimberton in
# Phoenixville's own zone (both already hold venues there), narrow enough to
# drop Royersford and Pottstown, which are their own towns a few miles further
# out with no bar of ours between here and there.
ZONE_QUERIES = {
    "phoenixville": {
        "anchor": "Bridge Street, Phoenixville, PA",
        "queries": ["Bridge Street, Phoenixville, PA", "Phoenixville, PA",
                    "Spring City, PA", "Kimberton, PA"],
        "radius_miles": 3.5,
    },
    "conshohocken": {
        "anchor": "Fayette Street, Conshohocken, PA",
        "queries": ["Fayette Street, Conshohocken, PA", "Conshohocken, PA",
                    "West Conshohocken, PA"],
        "radius_miles": 2.5,
    },
    "ardmore_bryn_mawr": {
        "anchor": "Suburban Square, Ardmore, PA",
        "queries": ["Ardmore, PA", "Suburban Square, Ardmore, PA",
                    "Bryn Mawr, PA", "Narberth, PA"],
        "radius_miles": 2.5,
    },
}


def geocode_anchor(address):
    params = urllib.parse.urlencode({"q": address, "format": "json", "limit": 1,
                                     "countrycodes": "us"})
    req = urllib.request.Request(NOMINATIM + "?" + params, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as fh:
        rows = json.load(fh)
    if not rows:
        sys.exit(f"Nominatim could not resolve anchor {address!r}")
    return float(rows[0]["lat"]), float(rows[0]["lon"])


def miles_between(lat1, lng1, lat2, lng2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# Base addresses read "STREET, TOWN PA ZIP" -- one comma. Places addresses read
# "STREET, TOWN, PA ZIP, USA" -- two. Both forms are handled so a candidate can
# actually be compared against what the base already holds.
_LOCALITY = re.compile(r",\s*([A-Za-z][A-Za-z .'-]*?)\s*,?\s*PA\b")


def normalize_locality(addr):
    m = _LOCALITY.search(addr or "")
    return m.group(1).strip().lower() if m else None


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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zone", required=True, choices=sorted(ZONE_QUERIES))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--spend", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    z = ZONE_QUERIES[args.zone]
    calls = len(z["queries"]) * len(TYPES)
    print(f"{args.zone}: {calls} first-page searches, "
          f"about ${calls * USD_PER_SEARCH:,.2f} at list price")
    if args.dry_run or not args.spend:
        print("Nothing spent. Re-run with --spend.")
        return

    key = load_key()
    if not key:
        sys.exit("No GOOGLE_PLACES_API_KEY. Put one in happy-hour-finder/.env")
    import requests

    alat, alng = geocode_anchor(z["anchor"])
    print(f"anchor: {z['anchor']} -> {alat:.4f},{alng:.4f}  "
          f"(radius {z['radius_miles']} mi)")

    # Matched against the WHOLE corpus, not just this zone's own slice: a
    # venue correctly zoned elsewhere (a Conshohocken bar filed under
    # blue_bell_plymouth_meeting because its township is Plymouth Twp, not
    # Conshohocken borough) is not a denominator gap, and checking only the
    # current zone's base reported it as one -- noise indistinguishable from
    # a real Boardroom-class miss until a human re-checked every row by hand.
    base = json.load(io.open(BASE_JSON, encoding="utf-8"))
    known_nums = set()
    for v in base.values():
        loc = normalize_locality(v.get("address"))
        for n in street_numbers(v.get("address")):
            known_nums.add((n, loc))

    seen_place_ids = set()
    candidates = {}
    out_of_range = 0
    for q in z["queries"]:
        for kind in TYPES:
            try:
                places, _ = search(key, q, kind, requests)
            except Exception as e:  # noqa: BLE001 -- one query is not the run
                print(f"  {kind:<14} {q[:34]:<36} failed: {str(e)[:60]}")
                continue
            for p in places:
                if p["id"] in seen_place_ids:
                    continue
                seen_place_ids.add(p["id"])
                loc = (p.get("location") or {})
                lat, lng = loc.get("latitude"), loc.get("longitude")
                if lat is None or lng is None:
                    continue
                if miles_between(alat, alng, lat, lng) > z["radius_miles"]:
                    out_of_range += 1
                    continue
                addr = p.get("formattedAddress") or ""
                nums = street_numbers(addr)
                town = normalize_locality(addr)
                if any((n, town) in known_nums for n in nums):
                    continue  # matches something already in the base
                candidates[p["id"]] = {
                    "name": p["displayName"]["text"], "address": addr,
                    "website": p.get("websiteUri") or "",
                    "type": p.get("primaryType") or "",
                }
            time.sleep(0.15)

    print(f"{out_of_range} result(s) outside the {z['radius_miles']}-mile "
          f"radius, dropped\n")
    print(f"{len(candidates)} candidate(s) with no matching street number "
          f"in the {args.zone} base:\n")
    for c in sorted(candidates.values(), key=lambda x: x["name"]):
        print(f"  {c['name']:<38} {c['address'][:44]:<46} {c['website'][:36]}")
    print("\nEach one still needs a PLCB address check before it is a finding "
          "-- this only says Places knows an address our base does not.")


if __name__ == "__main__":
    main()
