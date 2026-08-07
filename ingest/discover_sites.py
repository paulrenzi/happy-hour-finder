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
    # brand:website is last on purpose: it is the chain's page, not this
    # location's, so it only answers when nothing more specific does.
    for k in ("website", "contact:website", "url", "brand:website"):
        v = (tags.get(k) or "").strip()
        if v.startswith("http"):
            return v
    return None


# Names are matched only as a guarded fallback (see promote_by_name), so the
# normaliser drops the corporate and category noise that would otherwise make
# two different bars look alike -- and the guard, not this list, is what makes
# it safe.
NAME_NOISE = {
    "the", "a", "an", "and", "of", "inc", "llc", "lp", "co", "corp", "company",
    "ltd", "llp", "pa", "restaurant", "bar", "grill", "grille", "tavern", "pub",
    "brewing", "brewery", "taproom", "cafe", "kitchen", "house", "group",
    "holdings", "enterprises", "associates", "partners",
}


def name_core(name):
    words = re.sub(r"[^\w\s]", " ", (name or "").lower()).split()
    return " ".join(w for w in words if w not in NAME_NOISE)


def name_agrees(plcb_name, osm_name):
    """Do these two names plausibly describe the same business?

    Deliberately loose, because it is only ever used to break a tie between
    licensees that already share one address: the question is not 'is this the
    same name' but 'of the several tenants at 250 Main St, which one is the
    site about'. One shared distinctive word answers that; a shell name such as
    'KOP FONDUE INC' shares none with 'The Melting Pot' and stays unresolved,
    which is the correct answer, not a failure.
    """
    a, b = set(name_core(plcb_name).split()), set(name_core(osm_name).split())
    return bool(a & b)


def collapse_shared(out):
    """Drop websites that belong to a neighbour rather than to the licensee.

    The address join is right that a name mismatch is not evidence of a
    mis-join -- roughly a third of PLCB rows are corporate shells. But a mall,
    a plaza, an airport terminal and a town center are all ONE street address
    holding many businesses, so the key that is elsewhere unique here returns
    the wrong tenant. Measured on the seven towns plus the disc, 100 licensees
    across 37 URLs are joined this way; in King of Prussia seven Town Center
    licensees were each handed Shake Shack's page.

    When several licensees land on one OSM element the site can belong to at
    most one of them, so it is kept only for those whose name agrees with the
    element's, and dropped for the rest. A wrong site is worse than none: it
    publishes a neighbour's happy hour under this venue's name. Nothing is
    dropped where the element is claimed by a single licensee, so this cannot
    lower the count for any venue the join was already right about.
    """
    claims = collections.defaultdict(list)
    for lid, v in out.items():
        if v.get("osm"):
            claims[v["osm"]].append(lid)
    dropped = []
    for osm_id, lids in claims.items():
        if len(lids) < 2:
            continue
        for lid in lids:
            v = out[lid]
            if not name_agrees(v["name"], v.get("osm_name") or ""):
                dropped.append((v["name"], v.get("osm_name"), v["zone_id"],
                                v["website"]))
                del out[lid]
    return dropped


def localities_osm(tags):
    """The locality tokens an OSM element can be pinned to, best first."""
    out = []
    city = (tags.get("addr:city") or "").strip().lower()
    zp = (tags.get("addr:postcode") or "")[:5]
    if city:
        out.append(("city", city))
    if len(zp) == 5:
        out.append(("zip", zp))
    return out


def localities_plcb(row):
    out = []
    tail = TAIL_RE.search(row["address"] or "")
    if tail:
        out.append(("city", tail.group(1).strip().lower()))
    zp = (row.get("zip") or "")[:5]
    if len(zp) == 5:
        out.append(("zip", zp))
    return out


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
    # Two weaker indexes, each used only when it answers *uniquely*.
    #  - by_street drops the ZIP, because 256 of the extract's elements carry a
    #    housenumber and street but a missing or 4-digit postcode, and a ZIP is
    #    not disambiguating information once the number and street already are.
    #  - by_name is the guarded name fallback: the corporate-shell and
    #    two-Iron-Hills reasons never to match on name alone are still true, so
    #    a name is only allowed to speak when it is unique within one locality
    #    on BOTH sides. Every pair it accepts is printed.
    by_street = collections.defaultdict(list)
    by_name = collections.defaultdict(list)
    for e in els:
        tags = e.get("tags", {})
        key = osm_key(tags)
        if key and (key not in by_addr or (site_of(tags) and not site_of(by_addr[key][1]))):
            by_addr[key] = (e, tags)
        num, street = tags.get("addr:housenumber"), tags.get("addr:street")
        if num and street:
            core = street_core(street)
            if core:
                by_street[(num.split("-")[0].strip(), core)].append((e, tags))
        core = name_core(tags.get("name"))
        if core:
            for loc in localities_osm(tags):
                by_name[(loc, core)].append((e, tags))

    rows = list(csv.DictReader(open(VENUES_CSV, encoding="utf-8")))
    # How often each name occurs per locality on the PLCB side -- the other half
    # of the uniqueness guard.
    plcb_names = collections.Counter()
    for row in rows:
        core = name_core(row["name"])
        if core:
            for loc in localities_plcb(row):
                plcb_names[(loc, core)] += 1

    out, stats, misses, promoted = {}, collections.Counter(), [], []
    for row in rows:
        key = plcb_key(row["address"])
        hit, how = (by_addr.get(key) if key else None), "address"
        if not key:
            stats["licensee address unparseable"] += 1
        if not hit and key:
            near = by_street.get((key[1], key[2]), [])
            if len(near) == 1:
                hit, how = near[0], "address (ZIP ignored)"
        if not hit:
            core = name_core(row["name"])
            for loc in localities_plcb(row) if core else []:
                cands = by_name.get((loc, core), [])
                if len(cands) == 1 and plcb_names[(loc, core)] == 1:
                    hit, how = cands[0], f"name, unique in {loc[1]}"
                    break
        if not hit:
            if key:
                stats["no OSM row at that address"] += 1
                if len(misses) < args.unmatched:
                    misses.append(row)
            continue
        el, tags = hit
        stats["matched to OSM"] += 1
        stats[f"  via {how.split(',')[0]}"] += 1
        if how.startswith("name"):
            promoted.append((row["name"], tags.get("name"), row["zone_id"], how))
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
            "matched_by": how,
        }

    shared = collapse_shared(out)

    # guess_sites.py merges its proven domains into the same file, and this one
    # rewrites that file whole -- so without this a re-run of the join silently
    # deletes every guessed site, and the loss looks like the guesser having
    # found nothing. A guess is only ever kept for a licensee the join itself
    # could not answer for, so the join always wins.
    kept = 0
    if os.path.exists(OUT):
        for lid, v in json.load(open(OUT, encoding="utf-8")).items():
            if lid not in out and str(v.get("matched_by", "")).startswith("guessed"):
                out[lid] = v
                kept += 1

    print(f"\n{len(rows)} licensees vs {len(by_addr)} addressed OSM venues\n")
    for k, v in stats.most_common():
        print(f"  {v:>6}  {k}")
    print(f"\ncrawlable websites: {len(out)}  ({kept} carried over from guess_sites)")

    if shared:
        print(f"\n{len(shared)} dropped: a neighbour's site at a shared address")
        for plcb, osm, zone, site in sorted(shared, key=lambda p: p[2])[:40]:
            print(f"  {plcb[:30]:<32} != {(osm or '?')[:22]:<24} {zone:<20}{site[:38]}")

    if promoted:
        print(f"\n{len(promoted)} promoted on name (review these):")
        for plcb, osm, zone, how in sorted(promoted, key=lambda p: p[2]):
            print(f"  {plcb[:32]:<34} -> {(osm or '')[:28]:<30} {zone:<22}{how}")

    if misses:
        print("\nunmatched sample:")
        for m in misses:
            print(f"  {m['name'][:38]:<40} {m['address'][:52]}")

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
