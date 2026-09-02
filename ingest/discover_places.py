#!/usr/bin/env python3
"""Resolve every licensed venue in a zone to its Google Places listing.

    GOOGLE_PLACES_API_KEY=...   in happy-hour-finder/.env  (this repo's own key --
                                never reach into another project's credentials)
    python ingest/discover_places.py --zone king_of_prussia --dry-run
    python ingest/discover_places.py --zone king_of_prussia
    python ingest/discover_places.py --all --max 1000

PLCB already tells us every venue that can legally pour in a zone -- 60 in King
of Prussia. What it does not carry is a website or a photo, and OSM only filled
34 of those 60. The missing 26 are not obscure: Dave & Buster's, Cheesecake
Factory, Yard House, Eataly. They never appear in the app because we never found
a URL for them, not because they are absent from the ground truth.

So this does not go hunting for venues. It walks our own licence rows and asks
Places what it knows about each address.

Two lookups, because one does not cover both shapes of row:

  text search   `<name>, <address>` -- works whenever the licence names the
                business the public knows ("TOMMY'S TAVERN + TAP").
  nearby search at the point that came back -- the fallback for the ~37% of rows
                naming a holding company ("WYATT ERB INC"). A bare address text
                search resolves to the *street-address geocode*, which has no
                website and no photos by construction; the business standing on
                that spot is only reachable by searching around the point.

The join stays on address, never name. A shell row's name matches nothing, and
Places will happily return a plausible neighbour, so a result is only accepted
when its street number agrees with the licence's.

Cost is set by the field mask, not the call count. `websiteUri` puts both calls
in the Enterprise SKU (1,000 free/month), so `--max` is a hard stop and the
default run is one zone.
"""

import argparse
import csv
import json
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENUES_CSV = os.path.join(REPO, "data", "venues.csv")
OUT_JSON = os.path.join(REPO, "data", "places_venues.json")

SEARCH = "https://places.googleapis.com/v1/places:searchText"
NEARBY = "https://places.googleapis.com/v1/places:searchNearby"

# Everything we want about a venue, in one call. Adding to this is a pricing
# decision, not a convenience -- see the module docstring.
MASK = ",".join(
    f"places.{f}"
    for f in ("id", "displayName", "formattedAddress", "location",
              "websiteUri", "primaryType", "photos")
)

# What counts as a place that can serve a happy hour. Used to filter the nearby
# fallback, where we are choosing among whatever shares the licence's address.
FOOD_TYPES = ["restaurant", "bar", "pub", "cafe", "bakery", "meal_takeaway"]

ENTERPRISE_FREE_PER_MONTH = 1000
NEARBY_RADIUS_M = 120.0  # a licence address and its storefront are the same lot
DELAY = 0.05


def load_key():
    path = os.path.join(REPO, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k == "GOOGLE_PLACES_API_KEY" and v:
                return v.strip().strip("\"'")
    return os.environ.get("GOOGLE_PLACES_API_KEY")


STREET_SUFFIX = (
    "ST|STREET|RD|ROAD|BLVD|BOULEVARD|PIKE|PK|AVE|AVENUE|DR|DRIVE|LN|LANE"
    "|WAY|HWY|HIGHWAY|CT|COURT|PL|PLACE|TPKE|TURNPIKE|CIR|CIRCLE"
)
# The number that belongs to the street, not the first number in the string. A
# PLCB premises address routinely leads with the complex it sits in --
# "THE COURT UNIT C263A 690 W DEKALB PIKE" -- so reading the leading digits
# returns None for every mall tenant. That made all 12 King of Prussia mall
# venues look like Places had no listing for them, when the comparison simply
# never ran. Both sides go through this, or the join silently never fires.
_STREET_NUM = re.compile(
    r"\b(\d+)\b(?=[^,]*\b(?:" + STREET_SUFFIX + r")\b)", re.I
)


def street_number(s):
    s = (s or "").strip()
    m = _STREET_NUM.search(s)
    if m:
        return m.group(1)
    m = re.match(r"\s*(\d+)", s)
    return m.group(1) if m else None


# A door with two numbers on it. The PLCB writes the whole frontage a licence
# occupies -- "109-111 W STATE ST 2ND FLOOR" -- and Google writes the one number
# the business answers to, "109 W State St". Reading only the first number is
# right half the time by luck and wrong the other half: Media's DKD 109 LLC (the
# shell licence over Off the Rail) resolved to nothing for exactly this reason.
# So the LICENCE side spans a set and the comparison is membership, not equality.
_RANGE_NUM = re.compile(r"\b(\d+(?:-\d+)+)\b(?=[^,]*\b(?:" + STREET_SUFFIX + r")\b)", re.I)


def street_numbers(s):
    """Every house number the licence's frontage covers, as a set of strings."""
    m = _RANGE_NUM.search((s or "").strip())
    if m:
        return {n for n in m.group(1).split("-") if n}
    n = street_number(s)
    return {n} if n else set()


CORP_NOISE = re.compile(
    r"\b(inc|llc|lp|llp|co|corp|company|restaurants?|the|of|at)\b|#\s*\d+|\d+", re.I
)


def name_tokens(s):
    return set(re.sub(r"[^a-z0-9 ]", " ", CORP_NOISE.sub(" ", s or "").lower()).split())


def locality(s):
    """The 5-digit ZIP -- the guard that keeps a name match local.

    Not the city line: a PLCB premises address has no clean comma-delimited city
    ("...690 W DEKALB PIKE, KING OF PRUSSIA PA 19406"), so splitting on commas
    finds no digit-free segment and the guard rejects everything it is asked
    about. The ZIP is present and identically formatted on both sides.
    """
    return set(re.findall(r"\b(\d{5})(?:-\d{4})?\b", s or ""))


def name_agrees(licence_name, place_name, licence_addr, place_addr):
    """A fallback join for venues a mall addresses differently than the PLCB does.

    Only reached when the street numbers disagree. A *missing* name match is
    worthless evidence at a ~37% shell rate, but a positive one is not the same
    claim -- "MAGGIANO'S LITTLE ITALY" at 205 Mall Blvd and "Maggiano's Little
    Italy" at 160 N Gulph Rd Ste 205 are the same restaurant, and the mall simply
    numbers its tenants twice. Guarded three ways: one side's tokens must contain
    the other's, the shorter side must carry real signal rather than one generic
    word, and both must sit in the same town. Recorded as its own matched_by so a
    card sourced this way stays auditable.
    """
    ours, theirs = name_tokens(licence_name), name_tokens(place_name)
    if not ours or not theirs:
        return False
    if not (ours <= theirs or theirs <= ours):
        return False
    if min(len(ours), len(theirs)) < 2 and not (ours & theirs):
        return False
    return bool(locality(licence_addr) & locality(place_addr))


def looks_like_a_geocode(place, licence_addr):
    """True when Places answered with the address itself rather than a business.

    A geocode result names the street ("940 Township Line Rd") and carries no
    website and no photos. Treating one as a venue would publish a card for a
    parking lot, so it is the signal to fall back to the nearby search.
    """
    name = (place.get("displayName") or {}).get("text", "")
    if place.get("websiteUri") or place.get("photos"):
        return False
    n = street_number(licence_addr)
    return bool(n and name.strip().startswith(n))


def post(key, url, body):
    import requests

    r = requests.post(
        url,
        headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": MASK},
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("places", [])


def text_search(key, venue):
    places = post(key, SEARCH, {
        "textQuery": f"{venue['name']}, {venue['address']}",
        "maxResultCount": 1,
    })
    return places[0] if places else None


def nearby_search(key, lat, lng, licence_addr):
    """Whatever business stands at the licence address, when the row named a shell.

    Ranked by DISTANCE, not by the default popularity. On a dense main street
    120 m holds far more than ten bars, and popularity order returns the ten
    best-known ones -- which is never the shell-licensed rooftop we are looking
    for. Media's 109 W State St sat eleventh behind its own neighbours and read
    as "no place at this address"; asking for the nearest ten put it second.
    """
    places = post(key, NEARBY, {
        "includedTypes": FOOD_TYPES,
        "maxResultCount": 10,
        "rankPreference": "DISTANCE",
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": NEARBY_RADIUS_M,
            }
        },
    })
    want = street_numbers(licence_addr)
    # Prefer an exact street-number agreement; the nearest neighbour is a guess,
    # and a guess here is exactly the name-join we refuse to make elsewhere.
    for p in places:
        if want and street_number(p.get("formattedAddress")) in want:
            return p
    return None


def geocode_point(key, licence_addr):
    """The licence address's own point -- the address alone, with no name.

    Deliberately the geocode: asking for a street address and nothing else is
    how you get the spot rather than a business standing near it, and the spot
    is what the nearby search needs a centre for.
    """
    places = post(key, SEARCH, {"textQuery": licence_addr, "maxResultCount": 1})
    loc = (places[0].get("location") or {}) if places else {}
    if loc.get("latitude") is None:
        return None
    return loc["latitude"], loc["longitude"]


def resolve(key, venue):
    """One venue -> (place, how_we_matched). Returns (None, reason) on no match."""
    place = text_search(key, venue)
    how = "text search"
    if place and looks_like_a_geocode(place, venue["address"]):
        loc = place.get("location") or {}
        if loc.get("latitude") is None:
            return None, "geocode without a point"
        place = nearby_search(key, loc["latitude"], loc["longitude"], venue["address"])
        how = "nearby search at the geocode"
    if not place:
        return None, "no place at this address"
    ours = street_numbers(venue["address"])
    theirs = street_number(place.get("formattedAddress"))
    if theirs not in ours:
        pname = (place.get("displayName") or {}).get("text", "")
        paddr = place.get("formattedAddress")
        # A mall tenant's suite number is often the PLCB's street number.
        if any(re.search(r"\b(?:ste|suite|unit)\s*" + n + r"\b", paddr or "", re.I)
               for n in ours):
            return place, "suite number matches the licence street number"
        if name_agrees(venue["name"], pname, venue["address"], paddr):
            return place, "name agrees, same town (addresses differ)"
        # The shell row that landed on a NEIGHBOUR, not on a geocode. This was
        # the hole: looks_like_a_geocode() only fires when Places answers with
        # the bare street address, so a shell name that dragged the search onto
        # a real business three doors down never reached the nearby fallback at
        # all -- it was refused on the street number and filed as a miss. Media
        # lost Off the Rail ("DKD 109 LLC") and Maris ("BARNIEU RESTAURANT
        # MANAGEMENT, LLC") that way, both on State Street, both with sites.
        # So: throw away the answer, geocode the LICENCE address, and look at
        # what stands on that spot. The street-number guard is unchanged, which
        # is what keeps this from becoming a nearest-neighbour guess.
        point = geocode_point(key, venue["address"])
        if point:
            near = nearby_search(key, point[0], point[1], venue["address"])
            if near:
                return near, "nearby search at the licence address"
        return None, "street number disagrees"
    return place, how


SITES_JSON = os.path.join(REPO, "data", "venue_sites.json")

# The join that discovered a website decides whether the crawler may read that
# website FOR EVIDENCE. An address join says the state and Google agree on the
# building. A name join says two strings look alike in one ZIP -- enough to hang
# a photo and a link off, which is all it was ever allowed to do. Promoting one
# into the crawl frontier would make a happy hour attributable to a licence on
# the strength of a name, which is the line the address-only rule draws.
#
# 🛑 This is a PREFIX test, not a set of literals, because the set was one.
# resolve() has never returned the bare string "nearby search" -- it returns
# "nearby search at the geocode" and now "nearby search at the licence address"
# -- so every venue the address fallback ever rescued was silently held back
# from the crawl frontier as though it had been name-joined. The rescue and the
# thing that consumes it drifted apart with nothing failing.
#
# The suite-number and name-agrees joins stay OUT. A suite match is an address
# join in spirit, but it is the one shape where our number and Google's number
# mean different things, so it keeps its discovery-only status until a run needs
# it and can weigh it.
EVIDENCE_SAFE_PREFIXES = ("text search", "nearby search")


def evidence_safe(matched_by):
    return (matched_by or "").startswith(EVIDENCE_SAFE_PREFIXES)

# Licences whose site was removed BY HAND after a neighbour in the same plaza
# was found claiming the row -- absent beats publishing under another business's
# name. An automated merge must not quietly overturn that: a re-added row looks
# identical to one that was never reviewed.
#
# Places has since resolved 127673 to a marriott.com Residence Inn page, which
# is very likely the right site. Re-enabling it is a decision to make on that
# evidence, by deleting the entry here -- not a side effect of running a merge.
HAND_DROPPED = {
    "127673": "First Watch is not the Residence Inn at 127 S Gulph Rd",
    "86292": "PrimoHoagies is not the Giant at 700 Nutt Rd",
    # Media, 2026-09-02. THE FROSTED MUG's licence is 527 E Baltimore PIKE;
    # Places answered with the ACME Markets at 527 E Baltimore AVE. Two real
    # and different Media streets that share a house number, and the names
    # agree on nothing -- so the row shipped a bar's licence under a
    # supermarket's name, website and photo.
    "95653": "ACME Markets on Baltimore Ave is not The Frosted Mug on Baltimore Pike",
}


def merge_sites(dry_run=True, zone=None):
    """Feed the addresses Places resolved into the crawl frontier.

    ingest/crawl_sites.py reads data/venue_sites.json, so a website Places found
    is invisible to it until it lands there -- which is why King of Prussia's 26
    newly-discovered sites had never been read for a window.
    """
    places = json.load(open(OUT_JSON, encoding="utf-8"))
    sites = json.load(open(SITES_JSON, encoding="utf-8"))
    venues = {v["lid"]: v for v in csv.DictReader(open(VENUES_CSV, encoding="utf-8"))}

    added, held, dropped = {}, [], []
    for lid, p in sorted(places.items()):
        if lid in sites or not p.get("website"):
            continue
        row = venues.get(lid)
        if row is None:
            continue
        if zone and row["zone_id"] != zone:
            continue
        if lid in HAND_DROPPED:
            dropped.append((lid, p.get("places_name", ""), HAND_DROPPED[lid]))
            continue
        if not evidence_safe(p.get("matched_by")):
            held.append((lid, p.get("places_name", ""), p.get("matched_by")))
            continue
        added[lid] = {
            "address": row["address"],
            "kind": None,
            "lat": p.get("lat"),
            "lng": p.get("lng"),
            "matched_by": f"places {p['matched_by']} -> {p.get('places_address', '')}",
            "name": row["name"],
            "opening_hours": None,
            "osm": None,
            # The crawler shows osm_name on a card. Places resolved the trade
            # name against this exact address this month, so it is the better
            # display name -- and leaving it null would ship the licensee.
            "osm_name": p.get("places_name"),
            "phone": None,
            "website": p["website"],
            "zone_id": row["zone_id"],
        }

    # --merge-sites RETURNS before the resolve pass ever runs (see main()), so
    # on a zone nobody has resolved yet it is a silent no-op: it merges whatever
    # places_venues.json already held and reports "+0 to add". That is how the
    # handoff's one-line `--zone Z --merge-sites --execute` discovered nothing
    # on Doylestown (2026-09-02). Merging is not the discovery step; say so.
    if zone and not any(v.get("zone_id") == zone for lid, v in
                        ((lid, venues.get(lid) or {}) for lid in places)):
        print(f"  ! NOTHING RESOLVED FOR {zone} -- this merge is a no-op.\n"
              f"    The resolve pass is a SEPARATE, EARLIER command:\n"
              f"        python ingest/discover_places.py --zone {zone}\n"
              f"    then re-run this one.")

    print(f"{len(places)} resolved by Places, {len(sites)} already in the frontier")
    print(f"  +{len(added)} to add (address-joined, safe to crawl for evidence)")
    print(f"  {len(held)} held back -- name-joined, discovery only:")
    for lid, name, how in held:
        print(f"      {lid}  {name[:40]:<42} {how}")
    if dropped:
        print(f"  {len(dropped)} held back -- removed by hand, see HAND_DROPPED:")
        for lid, name, why in dropped:
            print(f"      {lid}  {name[:40]:<42} {why}")
    if dry_run:
        print("\ndry run -- nothing written. Re-run with --execute.")
        return added

    sites.update(added)
    json.dump(sites, open(SITES_JSON, "w", encoding="utf-8"), indent=1, sort_keys=True)
    print(f"\nwrote {len(sites)} venues -> data/venue_sites.json")
    print("next: python ingest/crawl_sites.py --zone <id>   (only the new LIDs are uncrawled)")
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone", help="resolve one zone (e.g. king_of_prussia)")
    ap.add_argument("--all", action="store_true", help="resolve every seeded venue")
    ap.add_argument("--dry-run", action="store_true", help="report scope, make no calls")
    ap.add_argument("--max", type=int, default=1000, help="hard cap on billed lookups")
    ap.add_argument("--force", action="store_true", help="re-resolve venues already done")
    ap.add_argument("--merge-sites", action="store_true",
                    help="add resolved websites to the crawl frontier (no API calls)")
    ap.add_argument("--execute", action="store_true", help="with --merge-sites: actually write")
    args = ap.parse_args()

    if args.merge_sites:
        merge_sites(dry_run=not args.execute, zone=args.zone)
        return

    if not (args.zone or args.all):
        sys.exit("Pick a scope: --zone <id> or --all")

    venues = list(csv.DictReader(open(VENUES_CSV, encoding="utf-8")))
    if args.zone:
        venues = [v for v in venues if v["zone_id"] == args.zone]
        if not venues:
            sys.exit(f"No seeded venues in zone {args.zone!r}")

    cache = json.load(open(OUT_JSON, encoding="utf-8")) if os.path.exists(OUT_JSON) else {}
    # A cached miss is not a settled answer -- it can be a transient 503 or a
    # join bug we have since fixed -- so only a resolved place counts as done.
    todo = venues if args.force else [
        v for v in venues if not cache.get(v["lid"], {}).get("place_id")
    ]

    print(f"venues in scope   {len(venues):>6}")
    print(f"already resolved  {len(venues) - len(todo):>6}")
    print(f"to look up        {len(todo):>6}   Enterprise SKU, "
          f"{ENTERPRISE_FREE_PER_MONTH:,} free/month")
    if args.dry_run:
        return

    key = load_key()
    if not key:
        sys.exit(
            "No GOOGLE_PLACES_API_KEY. Put one in happy-hour-finder/.env -- this project\n"
            "keeps its own credentials and does not read another repo's .env."
        )
    import requests

    todo = todo[: args.max]
    print(f"\nresolving {len(todo)} (capped at --max {args.max})\n")
    stats = {"site": 0, "photo": 0, "nearby": 0, "miss": 0}
    for i, v in enumerate(todo, 1):
        try:
            place, how = resolve(key, v)
        except requests.HTTPError as e:
            print(f"  {v['name'][:38]:<40} lookup failed: {e}")
            continue
        if not place:
            stats["miss"] += 1
            cache[v["lid"]] = {"name": v["name"], "address": v["address"], "miss": how}
            print(f"  {v['name'][:38]:<40} -- {how}")
        else:
            site = place.get("websiteUri")
            photos = [p["name"] for p in place.get("photos", [])[:1]]
            if site:
                stats["site"] += 1
            if photos:
                stats["photo"] += 1
            if how.startswith("nearby"):
                stats["nearby"] += 1
            cache[v["lid"]] = {
                "name": v["name"],
                "address": v["address"],
                "zone_id": v["zone_id"],
                "place_id": place["id"],
                "places_name": (place.get("displayName") or {}).get("text"),
                "places_address": place.get("formattedAddress"),
                "primary_type": place.get("primaryType"),
                "lat": (place.get("location") or {}).get("latitude"),
                "lng": (place.get("location") or {}).get("longitude"),
                "website": site,
                "photo_names": photos,
                "matched_by": how,
            }
            flag = "S" if site else "-"
            flag += "P" if photos else "-"
            print(f"  {v['name'][:38]:<40} {flag}  {cache[v['lid']]['places_name']}")
        if i % 25 == 0:
            json.dump(cache, open(OUT_JSON, "w", encoding="utf-8"), indent=1, sort_keys=True)
        time.sleep(DELAY)

    json.dump(cache, open(OUT_JSON, "w", encoding="utf-8"), indent=1, sort_keys=True)
    print(f"\n  resolved with a website {stats['site']}")
    print(f"  resolved with a photo   {stats['photo']}")
    print(f"  via the nearby fallback {stats['nearby']}")
    print(f"  no match                {stats['miss']}")
    print(f"\nwrote {OUT_JSON}")


if __name__ == "__main__":
    main()
