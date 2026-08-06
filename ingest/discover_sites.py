#!/usr/bin/env python3
"""Find each licensee's website by joining the PLCB rows to OpenStreetMap.

The PLCB export has no URLs, so before Phase 0's 19% scrape yield can be
collected at all, something has to say *where to crawl*. Google Places answers
that for a per-call fee; OSM answers it for nothing, and -- the reason it is the
right source rather than merely the cheap one -- ODbL results may be stored and
shipped, which is the same argument that made Nominatim the geocoder.

    python ingest/discover_sites.py                # use the cached Overpass reply
    python ingest/discover_sites.py --refresh      # re-query Overpass
    python ingest/discover_sites.py --unmatched 40 # sample what did not join

Writes data/venue_sites.json, keyed by PLCB LID.

The join is on address, never on name: ~37% of PLCB rows carry a corporate shell
(`300-E-6, INC.` is Coyote Crossing), and two "Iron Hill Brewery" rows are two
different bars. House number plus ZIP plus the *core* of the street name is the
only key both sources agree on -- OSM writes "Riverside Drive" where the PLCB
writes "RIVERSIDE DR", so the suffix and any directional are dropped from both.
"""

import argparse
import collections
import csv
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "data", "raw")
OSM_JSON = os.path.join(RAW, "osm_venues.json")
VENUES_CSV = os.path.join(REPO, "data", "venues.csv")
OUT = os.path.join(REPO, "data", "venue_sites.json")

OVERPASS = "https://overpass-api.de/api/interpreter"
# The disc, in metres, straight from zones.json so the two never drift.
QUERY = """
[out:json][timeout:180];
(
  nwr["amenity"~"^(bar|pub|restaurant|biergarten|nightclub|cafe|fast_food)$"](around:{radius_m},{lat},{lng});
  nwr["tourism"="hotel"](around:{radius_m},{lat},{lng});
  nwr["leisure"~"^(golf_course|bowling_alley)$"](around:{radius_m},{lat},{lng});
  nwr["craft"~"^(brewery|distillery|winery)$"](around:{radius_m},{lat},{lng});
  nwr["shop"~"^(alcohol|wine|brewing_supplies)$"](around:{radius_m},{lat},{lng});
);
out tags center;
"""

# Street suffixes and directionals are spelled differently by the two sources and
# carry no disambiguating information once the number and ZIP already match.
SUFFIXES = {
    "st", "street", "ave", "av", "avenue", "rd", "road", "dr", "drive", "blvd",
    "boulevard", "ln", "lane", "pike", "pk", "ct", "court", "cir", "circle",
    "pl", "place", "ter", "terrace", "way", "hwy", "highway", "tpke", "turnpike",
    "sq", "square", "row", "trl", "trail", "run", "path", "walk", "expy",
    "pkwy", "parkway", "ext", "extension", "loop", "bypass", "byp",
}
DIRECTIONALS = {"n", "s", "e", "w", "ne", "nw", "se", "sw", "north", "south",
                "east", "west"}

# The state+ZIP tail is the only part of a PLCB address with a fixed shape.
TAIL_RE = re.compile(r",\s*(.+?)\s+([A-Z]{2})\s+(\d{5})")
# A house number may carry a unit letter ('1630C') or be a range ('929-931').
# Anchored at a word boundary so 'STORES 15 & 16  8919 RIDGE AVE' can be scanned
# for the *last* such run rather than the first.
NUM_RE = re.compile(r"\b(\d+)(?:-\d+)?[A-Za-z]?\s+([A-Za-z].*)$")

# Words that mean the text before them is a building or plaza name, not a street.
UNIT_RE = re.compile(
    r"\b(?:ste|suite|unit|apt|fl|floor|rm|room|bsmt|basement|space|bldg|building|"
    r"store|stores|terminal|#)\b.*$",
    re.I,
)


# Only ONE trailing suffix is dropped, and whatever survives is normalised to a
# single spelling: 'W St Rd' is West *Street* Road, a real street named 'Street',
# so popping every suffix word would erase the name itself.
ABBREV = {"street": "st", "avenue": "ave", "road": "rd", "drive": "dr",
          "boulevard": "blvd", "lane": "ln", "court": "ct", "place": "pl",
          "square": "sq", "pike": "pk", "highway": "hwy", "parkway": "pkwy",
          "mount": "mt", "saint": "st", "fort": "ft", "junior": "jr"}


def street_core(street):
    """'W Lancaster Avenue' and 'LANCASTER AVE' both reduce to 'lancaster'."""
    words = re.sub(r"[^\w\s]", " ", street.lower()).split()
    words = [w for w in words if w not in DIRECTIONALS]
    if len(words) > 1 and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(ABBREV.get(w, w) for w in words)


def plcb_key(address):
    """(zip, house number, street core) -- or None if the row is unparseable.

    A PLCB premises address often prefixes the street with a mall or building
    name that itself contains digits ('ROXBORO MARKET SQ ... STORES 15 & 16
    8919 RIDGE AVE'), so the number is taken from the *last* number-then-words
    run, not the first, and any trailing unit is cut before the street is read.
    """
    tail = TAIL_RE.search(address or "")
    if not tail:
        return None
    street_part = address[: tail.start()].strip()
    # Scan right-to-left for the last plausible 'number street' opening. The
    # unit is cut only from what follows it -- cutting first would delete the
    # street along with the 'STORES 15 & 16' that precedes it.
    best = None
    for m in re.finditer(r"\b(\d+)(?:-\d+)?[A-Za-z]?\s+(?=[A-Za-z])", street_part):
        best = m
    if not best:
        return None
    core = street_core(UNIT_RE.sub("", street_part[best.end():]))
    return (tail.group(3), best.group(1), core) if core else None


def osm_key(tags):
    num, street = tags.get("addr:housenumber"), tags.get("addr:street")
    zp = (tags.get("addr:postcode") or "")[:5]
    if not (num and street and len(zp) == 5):
        return None
    core = street_core(street)
    return (zp, num.split("-")[0].strip(), core) if core else None


def site_of(tags):
    for k in ("website", "contact:website", "url"):
        v = (tags.get(k) or "").strip()
        if v.startswith("http"):
            return v
    return None


def fetch_osm():
    import requests

    zones = json.load(open(os.path.join(REPO, "data", "zones.json"), encoding="utf-8"))
    q = QUERY.format(
        radius_m=int(zones["radius_miles"] * 1609.34),
        lat=zones["origin"]["lat"],
        lng=zones["origin"]["lng"],
    )
    print("  querying Overpass (this takes a minute)", file=sys.stderr)
    r = requests.post(
        OVERPASS,
        data={"data": q},
        timeout=300,
        # Overpass asks for a contactable agent; an anonymous bulk query is the
        # kind that gets the whole endpoint rate-limited for everyone.
        headers={"User-Agent": "happy-hour-finder/0.1 (paulmichaelrenzi@gmail.com)"},
    )
    r.raise_for_status()
    els = r.json()["elements"]
    os.makedirs(RAW, exist_ok=True)
    with open(OSM_JSON, "w", encoding="utf-8") as fh:
        json.dump(els, fh)
    print(f"  wrote {OSM_JSON} ({len(els)} elements)", file=sys.stderr)
    return els


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-query Overpass")
    ap.add_argument("--unmatched", type=int, default=0,
                    help="print N licensees that found no OSM row")
    args = ap.parse_args()

    if args.refresh or not os.path.exists(OSM_JSON):
        els = fetch_osm()
    else:
        els = json.load(open(OSM_JSON, encoding="utf-8"))

    # An address can hold several OSM rows (a way and a node for one building).
    # Keep the one that actually carries a website; a duplicate without one is
    # not evidence of anything.
    by_addr = {}
    for e in els:
        tags = e.get("tags", {})
        key = osm_key(tags)
        if not key:
            continue
        if key not in by_addr or (site_of(tags) and not site_of(by_addr[key][1])):
            by_addr[key] = (e, tags)

    rows = list(csv.DictReader(open(VENUES_CSV, encoding="utf-8")))
    out, stats, misses = {}, collections.Counter(), []
    for row in rows:
        key = plcb_key(row["address"])
        if not key:
            stats["licensee address unparseable"] += 1
            continue
        hit = by_addr.get(key)
        if not hit:
            stats["no OSM row at that address"] += 1
            if len(misses) < args.unmatched:
                misses.append(row)
            continue
        el, tags = hit
        stats["matched to OSM"] += 1
        site = site_of(tags)
        if not site:
            stats["  matched but no website tag"] += 1
            continue
        stats["  WITH A WEBSITE"] += 1
        out[row["lid"]] = {
            "name": row["name"],
            "osm_name": tags.get("name"),
            "address": row["address"],
            "zone_id": row["zone_id"],
            "website": site,
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "opening_hours": tags.get("opening_hours"),
            "kind": tags.get("amenity") or tags.get("tourism") or tags.get("leisure") or tags.get("craft") or tags.get("shop"),
            "lat": el.get("lat") or (el.get("center") or {}).get("lat"),
            "lng": el.get("lon") or (el.get("center") or {}).get("lon"),
            "osm": f"{el['type']}/{el['id']}",
        }

    print(f"\n{len(rows)} licensees vs {len(by_addr)} addressed OSM venues\n")
    for k, v in stats.most_common():
        print(f"  {v:>6}  {k}")
    print(f"\ncrawlable websites: {len(out)}")

    if misses:
        print("\nunmatched sample:")
        for m in misses:
            print(f"  {m['name'][:38]:<40} {m['address'][:52]}")

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
