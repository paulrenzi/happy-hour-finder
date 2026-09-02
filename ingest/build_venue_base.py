#!/usr/bin/env python3
"""Emit data/venue_base.json -- every licensed venue, keyed on its PLCB LID.

This is the layer the product now rests on. The happy hour is an ATTRIBUTE of a
venue, not the reason a venue exists: a bar with no window we could prove still
gets a card, so a person can see it is missing and tell us what it is. A venue
nobody can see is a venue nobody can correct.

Run it whenever the PLCB corpus, the Places discovery, or the site frontier
moves:

    python ingest/build_venue_base.py

data/venues.csv is gitignored (it is a regenerated PLCB artifact) but CI rebuilds
the bundles and diffs them, so the bundle build must not read it. That is the
whole reason this step exists as its own committed file: this script needs the
CSV, ingest/build_bundles.py needs only the JSON it writes.
"""

import csv
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VENUES_CSV = os.path.join(REPO, "data", "venues.csv")
PLACES_JSON = os.path.join(REPO, "data", "places_venues.json")
SITES_JSON = os.path.join(REPO, "data", "venue_sites.json")
PHOTOS_LID_JSON = os.path.join(REPO, "data", "venue_photos_by_lid.json")
OUT_JSON = os.path.join(REPO, "data", "venue_base.json")

# A licence you cannot walk into. Brewery Storage is a warehouse permit -- the
# beer is there, nobody is drinking it. Everything else on the PLCB list serves
# the public, including the hotel bars and the golf course restaurants, so they
# stay: "is it worth going to" is the user's call, not ours.
EXCLUDED_LICENSE_TYPES = {"Brewery Storage"}

# Venues that are off the board by NAME, not by licence: the permanent bans and
# the hotel chains. Kept in ingest/exclusions.py with the reasoning, because
# 'Hotel (Liquor)' is a licence class and not a hotel -- see that file.
from exclusions import excluded  # noqa: E402

# Suffixes on a PLCB licensee name. They are the legal entity, never the sign
# over the door, and they are only ever stripped from the FALLBACK name -- a
# name Google or OSM gave us is already the trade name and is left alone.
ENTITY_SUFFIX_RE = re.compile(
    r"[\s,]+(?:"
    r"LLC|L\.L\.C\.|INC|INC\.|LP|L\.P\.|LLP|LTD|CORP|CORPORATION|CO|COMPANY|"
    r"ASSOCIATES|ENTERPRISES|HOLDINGS|GROUP|PARTNERS|PARTNERSHIP"
    r")\.?$",
    re.I,
)

# Words title-casing gets wrong. Small set on purpose: a name shown wrong is
# worse than a name shown plainly, so this only fixes what actually appears.
UPPER_WORDS = {
    "bbq", "byob", "kop", "llc", "ii", "iii", "iv", "vi", "vii", "viii", "ix",
    "nyc", "pa", "usa", "vfw", "dj", "tv", "jr", "sr", "bmw",
}
LOWER_WORDS = {"a", "an", "and", "at", "by", "de", "del", "for", "in", "la",
               "las", "los", "of", "on", "or", "the", "to", "y"}


def pretty_name(raw):
    """AN ALL-CAPS LICENSEE NAME -> something a person would read on a card.

    PLCB ships the licensee, upper-cased: `TOMMY'S TAVERN + TAP`, `SCREWBALLS
    LLC`. str.title() alone gives `Tommy'S Tavern + Tap`, which looks broken in
    exactly the place a card has nothing else to show.
    """
    name = ENTITY_SUFFIX_RE.sub("", (raw or "").strip())
    if not name:
        name = (raw or "").strip()
    if not re.search(r"[a-z]", name):  # only re-case something that IS all caps
        out = []
        for i, word in enumerate(name.split()):
            low = word.lower()
            bare = low.strip(".,&'\"()")
            if bare in UPPER_WORDS:
                out.append(word.upper())
            elif bare in LOWER_WORDS and i > 0:
                out.append(low)
            else:
                # Cap each alphabetic run, treating an apostrophe as INSIDE the
                # word and a hyphen as between two: TOMMY'S -> Tommy's, not
                # Tommy'S, while BAR-B-Q still caps each piece. str.title() and
                # a bare [A-Za-z]+ both get the possessive wrong, and it lands on
                # the one line a card with no other content has to show.
                out.append(re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)*",
                                  lambda m: m.group(0)[0].upper() + m.group(0)[1:], low))
        name = " ".join(out)
    return name


def pretty_address(raw):
    """`929-931 MACDADE BLVD, COLLINGDALE PA 19023-3720` -> title case, ZIP+4
    dropped. The card shows this under the name; the join never reads it."""
    addr = re.sub(r"(\b\d{5})-\d{4}\b", r"\1", (raw or "").strip())
    addr = re.sub(r"\s{2,}", " ", addr)
    if not re.search(r"[a-z]", addr):
        addr = re.sub(
            r"[A-Za-z]+",
            lambda m: m.group(0) if m.group(0).upper() in ("PA", "NE", "NW", "SE", "SW")
            else m.group(0).capitalize(),
            addr,
        )
    return addr


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def premises_key(lid, place, site, row):
    """What building is this licence for?

    One bar routinely holds several licences -- the Sheraton Valley Forge is two
    Hotel (Liquor) rows at 480 N Gulph Rd, and King of Prussia's "60 venues" is
    really 60 LICENCES. Rendering a card per licence shows the same bar twice.

    A Places id is Google's own identity for a business, and an OSM id is the
    element the site frontier matched; either is the building. Failing both, two
    rows are one venue only if the street number, the ZIP and the licensee name
    all agree -- deliberately strict, because merging two real bars is a much
    worse error than listing one twice.
    """
    if place.get("place_id"):
        return ("place", place["place_id"])
    if site.get("osm"):
        return ("osm", site["osm"])
    addr = row["address"] or ""
    num = re.match(r"\s*(\d+)", addr)
    return ("addr", num.group(1) if num else lid, row["zip"], row["name"].strip().upper())


def richer(a, b):
    """Which of two records for one building should hold the card. More data
    wins; a tie goes to the lower LID so the choice is stable across runs."""
    rank = lambda v: (("photo" in v), ("website" in v), ("lat" in v))  # noqa: E731
    if rank(a) != rank(b):
        return a if rank(a) > rank(b) else b
    return a if int(a["lid"]) <= int(b["lid"]) else b


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not os.path.exists(VENUES_CSV):
        sys.exit(f"missing {VENUES_CSV} -- run ingest/seed_plcb.py first")

    places = load_json(PLACES_JSON)
    sites = load_json(SITES_JSON)
    photos = load_json(PHOTOS_LID_JSON)

    with open(VENUES_CSV, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    by_premises, skipped, off_board = {}, 0, {}
    for row in rows:
        if row["license_type"] in EXCLUDED_LICENSE_TYPES:
            skipped += 1
            continue
        lid = row["lid"]
        place = places.get(lid) or {}
        site = sites.get(lid) or {}

        # A trade name beats a legal one, and Google's beats OSM's: the Places
        # record was resolved against this exact address this month, where an
        # OSM name can be a decade old. The PLCB licensee is the last resort.
        name = place.get("places_name") or site.get("osm_name") or pretty_name(row["name"])

        why = excluded(name, row["name"], row["license_type"])
        if why:
            off_board.setdefault(why, []).append(name)
            continue

        v = {
            "lid": lid,
            "name": name,
            "named_by": "places" if place.get("places_name")
            else "osm" if site.get("osm_name") else "plcb",
            "plcb_name": row["name"],
            "address": pretty_address(row["address"]),
            "zone_id": row["zone_id"],
            "license_type": row["license_type"],
            "tier": row["tier"],
        }

        # Third source, lowest rank: the website Google returned alongside the
        # photo, for a place whose name already agreed with ours. Before this the
        # photo run recovered a website for ~3 in 5 site-less venues and dropped it.
        website = place.get("website") or site.get("website")             or (photos.get(lid) or {}).get("website")
        if website:
            v["website"] = website

        # Places geocodes the premises; OSM placed the element. Either is a
        # building, so both are "place" precision -- unlike the street-centroid
        # matches ingest/geocode_venues.py falls back to.
        at = place if place.get("lat") is not None else site
        if at.get("lat") is not None:
            v["lat"], v["lng"] = at["lat"], at["lng"]
            v["geo_precision"] = "place"

        pic = photos.get(lid)
        if pic and os.path.exists(os.path.join(REPO, "web", pic["file"])):
            v["photo"] = {"file": pic["file"], "attribution": pic.get("attribution", "")}

        key = premises_key(lid, place, site, row)
        held = by_premises.get(key)
        by_premises[key] = v if held is None else richer(held, v)

    # Every LID that resolved to this building, the winner included. A person
    # reporting an hours correction quotes the card's LID, and the licence they
    # are standing in front of may be one of the others.
    lids_for = {}
    for row in rows:
        if row["license_type"] in EXCLUDED_LICENSE_TYPES:
            continue
        if excluded((places.get(row["lid"]) or {}).get("places_name", ""),
                    row["name"], row["license_type"]):
            continue
        key = premises_key(row["lid"], places.get(row["lid"]) or {},
                           sites.get(row["lid"]) or {}, row)
        lids_for.setdefault(key, []).append(row["lid"])

    out = {}
    for key, v in by_premises.items():
        siblings = sorted(set(lids_for[key]) - {v["lid"]}, key=int)
        if siblings:
            v["also_lids"] = siblings
        out[v["lid"]] = v

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)

    n = len(out)
    kept = len(rows) - skipped
    named = sum(1 for v in out.values() if v["named_by"] != "plcb")
    print(f"{len(rows)} PLCB rows, {skipped} excluded "
          f"({'/'.join(sorted(EXCLUDED_LICENSE_TYPES))})")
    for why in sorted(off_board):
        print(f"  {len(off_board[why]):>5}  off the board: {why}")
    print(f"{kept} licences collapsed to {n} venues "
          f"({kept - n} were a second licence at a building already listed)")
    print(f"wrote {n} venues -> {os.path.relpath(OUT_JSON, REPO)} "
          f"({os.path.getsize(OUT_JSON):,} bytes)")
    print(f"  {named:>5}/{n}  have a trade name (rest fall back to the licensee)")
    for field, label in (("website", "have a website"), ("lat", "have a coordinate"),
                         ("photo", "have a photo")):
        print(f"  {sum(1 for v in out.values() if field in v):>5}/{n}  {label}")


if __name__ == "__main__":
    main()
