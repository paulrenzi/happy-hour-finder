#!/usr/bin/env python3
"""Resolve a coordinate for every venue on the board that still lacks one.

ingest/geocode_venues.py already does this, but it reads data/deals_seed.json
and keys on that file's slug, so it can only ever reach the original seed
corpus -- 387 rows, none of them added by the PLCB base or the zone expansions.
The board is built from data/venue_base.json and keyed on LID. This fills the
gap that leaves, and keys on the LID so a rebuild of the base (which is
regenerated wholesale from Places) cannot drop the answer on the floor.

    python ingest/geocode_missing.py            # published deal venues only
    python ingest/geocode_missing.py --all      # every base row with no coord
    python ingest/geocode_missing.py --limit 25

Writes data/venue_coords_lid.json. build_bundles.py consults it after the seed
coords and before the base's own Places coordinate.

A coordinate is what makes "a happy hour near where I am" answerable at all,
so a WRONG one is worse than a missing one -- it puts a bar on the map in a
town it is not in and the reader has no way to tell. Two guards, both of which
must pass before anything is recorded:

  * the ZIP Nominatim resolves must equal the ZIP we asked for. This is far
    stronger than a bounding box: '324 W Swedesford Rd' exists in both 19312
    and 19341, thirty miles apart and both inside any box drawn around the
    market.
  * the result must still land inside the market box, which now spans the
    Delaware beach zones as well as the Philadelphia suburbs.

Nothing is recorded for a miss. A Nominatim timeout and "this address does not
exist" are indistinguishable from the outside, and a cached negative would keep
the venue uncoordinated forever -- the trap that once poisoned 425 geocode keys.
"""

import argparse
import glob
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_JSON = os.path.join(REPO, "data", "venue_base.json")
OUT_JSON = os.path.join(REPO, "data", "venue_coords_lid.json")
ZONE_GLOB = os.path.join(REPO, "web", "data", "zone-*.json")

ENDPOINT = "https://nominatim.openstreetmap.org/search"
UA = "happy-hour-finder/0.1 (https://github.com/paulrenzi/happy-hour-finder)"
RATE_LIMIT_SECONDS = 1.1  # Nominatim asks for <=1/s; leave headroom.

# The market as it now stands: Pottstown and Doylestown in the north, Rehoboth
# and Lewes in the south. Only a backstop -- the ZIP check below does the work.
BBOX = {"lat": (38.4, 40.8), "lng": (-76.3, -74.4)}

ADDRESS_RE = re.compile(
    r"^(?P<street>.+?),\s*(?P<city>[^,]+?)\s+(?P<state>[A-Z]{2})\s+(?P<zip>\d{5})$"
)

# 'Ste 2', 'Suite 300', 'Bldg 19', 'Unit B', '#4', 'Fl 2'. A licensee writes the
# suite because the mail needs it; OSM has never heard of it and the whole query
# misses because of it. Well Crafted Beer is '300 Brookside Ave Bldg 19 Ste E'.
SUITE_RE = re.compile(
    r"(?i)[\s,]+(?:ste|suite|unit|apt|bldg|building|fl|floor|rm|room|#)\s*[-\w]*\s*$"
)


def split_address(address):
    """'800 Spring Mill Ave, Conshohocken PA 19428' -> its parts, or None."""
    m = ADDRESS_RE.match((address or "").strip())
    return m.groupdict() if m else None


def strip_range(street):
    """'30-32 E State St' -> '30 E State St', '10-12-14 E Gay St' -> '10 E Gay St'.

    A house-number range is how a storefront that grew through the wall next
    door describes itself, and OSM carries only the first number. geocode_venues
    strip_range() handles ONE hyphen, which silently left '10-14 E Gay St'
    behind on West Chester's Gay Street -- where four of the misses were. It
    also has to tolerate the space a licensee types before the dash
    ('4417 -4419 Main St').
    """
    return re.sub(r"^(\d+)(?:\s*-\s*\d+[A-Za-z]?)+\b", r"\1", street.strip())


def clean_street(street):
    """Drop the suite, then the range. Repeats: '... Ste 2 ,' leaves a comma."""
    s = street.strip().rstrip(" ,")
    for _ in range(3):
        stripped = SUITE_RE.sub("", s).rstrip(" ,")
        if stripped == s:
            break
        s = stripped
    return strip_range(s)


def query(params):
    params = dict(params, format="json", limit=1, addressdetails=1, countrycodes="us")
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as fh:
        rows = json.load(fh)
    return rows[0] if rows else None


def strategies(parts):
    """Query forms to try in order, most constrained first."""
    street = clean_street(parts["street"])
    yield "full", {"street": street, "city": parts["city"],
                   "state": parts["state"], "postalcode": parts["zip"]}
    # Berwyn and Plymouth Meeting are census places, not OSM cities -- passing
    # them as `city` returns nothing at all. Street + ZIP is the reliable form.
    yield "street+zip", {"street": street, "postalcode": parts["zip"]}
    yield "freeform", {"q": f"{street}, {parts['city']}, {parts['state']} {parts['zip']}"}


# How far from the middle of its own zone a venue may sit before a ZIP the
# licensee and OSM disagree about stops being a typo and starts being a
# different town. Zones are neighbourhood-sized; five miles is generous.
ZONE_RADIUS_MI = 5.0


def miles(a, b):
    """Good enough at this latitude, and it never has to be better than 'is
    this the same town or thirty miles away'."""
    dy = (a[0] - b[0]) * 69.0
    dx = (a[1] - b[1]) * 53.0
    return (dy * dy + dx * dx) ** 0.5


def accept(hit, want_zip, near=None):
    """A hit is ours only if it lands in the asked-for ZIP and in the market.

    The ZIP a licensee filed and the ZIP OSM holds genuinely disagree for
    buildings on a boundary -- Estia Taverna's licence says Radnor 19085 and
    the post office says 19087, and it is the same door either way. So a
    mismatch is not fatal on its own: it is fatal unless the answer lands
    inside the venue's own zone, which is the check the ZIP was standing in
    for. Recorded either way, flagged when it happened, so a bad call can be
    found later without re-running the whole pass.
    """
    lat, lng = float(hit["lat"]), float(hit["lon"])
    if not (BBOX["lat"][0] <= lat <= BBOX["lat"][1]
            and BBOX["lng"][0] <= lng <= BBOX["lng"][1]):
        return None, f"{lat},{lng} outside the market", False
    got_zip = ((hit.get("address") or {}).get("postcode") or "")[:5]
    if got_zip and got_zip != want_zip:
        if not near:
            return None, f"ZIP {got_zip} != {want_zip}, and the zone has no centre to check against", False
        d = miles((lat, lng), near)
        if d > ZONE_RADIUS_MI:
            return None, f"ZIP {got_zip} != {want_zip} and {d:.1f} mi from its zone", False
        return (lat, lng), None, True
    return (lat, lng), None, False


def geocode(address, sleep, near=None):
    parts = split_address(address)
    if not parts:
        return None
    for i, (label, params) in enumerate(strategies(parts)):
        if i:
            time.sleep(sleep)
        hit = query(params)
        if not hit:
            continue
        at, why, loose_zip = accept(hit, parts["zip"], near)
        if at:
            return hit, at[0], at[1], label, loose_zip
        print(f"    (rejected {label}: {why})")
    return None


def board_lids():
    """Every venue with a published window, from the bundles the app ships."""
    lids = set()
    for path in glob.glob(ZONE_GLOB):
        for venue in json.load(open(path, encoding="utf-8"))["venues"]:
            if venue.get("lat") is None and venue.get("lid"):
                lids.add(str(venue["lid"]))
    return lids


def zone_centres(base):
    """The median coordinate of each zone's already-resolved venues.

    Median, not mean: one venue geocoded to the wrong county would drag a mean
    far enough to start admitting other wrong answers, and the whole point of
    this number is to be the thing a doubtful answer is checked against.
    """
    by_zone = {}
    for row in base.values():
        if row.get("lat") is not None and row.get("zone_id"):
            by_zone.setdefault(row["zone_id"], []).append((row["lat"], row["lng"]))
    out = {}
    for zid, pts in by_zone.items():
        lats = sorted(p[0] for p in pts)
        lngs = sorted(p[1] for p in pts)
        out[zid] = (lats[len(lats) // 2], lngs[len(lngs) // 2])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="every base row with no coordinate, not just the board")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    base = json.load(open(BASE_JSON, encoding="utf-8"))
    cache = {}
    if os.path.exists(OUT_JSON):
        cache = json.load(open(OUT_JSON, encoding="utf-8"))

    if args.all:
        want = {lid for lid, row in base.items() if row.get("lat") is None}
    else:
        want = board_lids()
    todo = sorted(lid for lid in want if lid not in cache and base.get(lid, {}).get("address"))
    if args.limit:
        todo = todo[:args.limit]

    if not todo:
        print(f"nothing to do -- {len(cache)} coordinates cached")
        return 0

    centres = zone_centres(base)
    print(f"{len(todo)} venue(s) to resolve\n")
    hits = misses = errors = loose = 0
    for i, lid in enumerate(todo):
        if i:
            time.sleep(RATE_LIMIT_SECONDS)
        row = base[lid]
        try:
            found = geocode(row["address"], RATE_LIMIT_SECONDS,
                            centres.get(row.get("zone_id")))
        except Exception as exc:
            # A transport failure is not a missing venue. Record NOTHING.
            print(f"  ERROR {lid} {row.get('name','')}: {type(exc).__name__}: {exc}"
                  " -- not recorded")
            errors += 1
            time.sleep(5)
            continue
        if not found:
            print(f"  MISS  {lid} {row.get('name','')}: {row['address']!r}")
            misses += 1
            continue
        hit, lat, lng, how, loose_zip = found
        cache[lid] = {
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "queried": row["address"],
            "resolved": hit["display_name"],
            "matched_by": how,
            # place_rank 30 = a building; 26 = a whole road. A road-level match
            # is a street centroid, good to a block, not a doorway.
            "precision": hit.get("addresstype", "?"),
            "place_rank": hit.get("place_rank"),
            "osm": f"{hit['osm_type']}/{hit['osm_id']}",
        }
        if loose_zip:
            # Accepted on the zone check, not the ZIP. Kept on the record so
            # these can be listed and re-examined without another full pass.
            cache[lid]["zip_mismatch"] = True
            loose += 1
        hits += 1
        # Print the RESOLVED string, never just "ok". A wrong match returns a
        # plausible coordinate for the wrong building and looks like success.
        flag = " ZIP?" if loose_zip else ""
        print(f"  {lid:<8}{row.get('name','')[:26]:<28}{lat:9.5f},{lng:10.5f}"
              f"  [{how}{flag}]  {hit['display_name'][:52]}")

    tmp = OUT_JSON + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, OUT_JSON)

    print(f"\n{hits} resolved ({loose} on the zone check after a ZIP disagreement), "
          f"{misses} no match, {errors} transport errors (not recorded) "
          f"-> {len(cache)} cached")
    print("Eyeball every 'resolved' line above against the address it was asked for.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
