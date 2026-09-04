#!/usr/bin/env python3
"""Seed the venue list from the PLCB active-licensee export.

The PLCB publishes a full CSV of every active license at
https://plcbplus.pa.gov/pub/LicenseExport.aspx (no auth, ~15MB, statewide).
That file is the ground-truth denominator: it answers "did we miss a bar?"

This script filters it to public, on-premises retail licensees inside the seed
market, assigns each one a zone from data/zones.json, and writes venues.csv.

Distances use GeoNames ZIP centroids, which are accurate to roughly a mile.
That is fine for counting and zone assignment; real per-venue coordinates come
from the Places resolution pass in Phase 1.

    python ingest/seed_plcb.py                 # use cached data/raw files
    python ingest/seed_plcb.py --refresh       # re-download both sources
    python ingest/seed_plcb.py --counts        # print the per-zone table only
"""

import argparse
import collections
import csv
import json
import math
import os
import re
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "data", "raw")
PLCB_CSV = os.path.join(RAW, "plcb_licenses_2026-07-31.csv")
ZIP_TXT = os.path.join(RAW, "geonames_us_zips.txt")
ZONES_JSON = os.path.join(REPO, "data", "zones.json")
OUT_CSV = os.path.join(REPO, "data", "venues.csv")
# Written by ingest/seed_places_de.py and TRACKED in git: unlike venues.csv,
# it costs money to rebuild.
DE_CSV = os.path.join(REPO, "data", "venues_de.csv")

PLCB_EXPORT_URL = "https://plcbplus.pa.gov/pub/LicenseExport.aspx"
GEONAMES_URL = "http://download.geonames.org/export/zip/US.zip"

# On-premises licenses open to the general public. These are the venues that can
# legally run a happy hour a stranger can walk into.
CORE_TYPES = {
    "Restaurant (Liquor)",
    "Eating Place Retail Dispenser (Malt)",
    "Hotel (Liquor)",
    "Hotel (Malt)",
    "Brewery Pub",
    "Public Venue Restaurant",
    "Economic Development Restaurant (Liquor)",
    "Economic Development Eating Place (Malt)",
    "Airport Restaurant (Liquor)",
    "Off-Track Wagering Restaurant (Liquor)",
    "Privately-Owned Public Golf Course Rest (Liquor)",
    "Privately Owned Public Golf Course (Malt)",
    "Municipal Golf Course (Liquor)",
    "Municipal Golf Course (Malt)",
    "Performing Arts Facility",
}

# Producers with public tasting rooms. They run happy hours but sit under a
# different part of the discount rules, so they are tracked as their own tier.
#
# "Brewery Storage" reads like a warehouse licence and was excluded on that
# reading, but in this market it is overwhelmingly the *secondary* licence a
# brewpub holds on its own taproom -- Forest and Main Pub, Steel City
# Coffeehouse, The Citadel Taproom, Sterling Pig, Backstage Tap and Grille all
# reach the corpus by no other row. Of 32 active in-zone storage licences only
# one names a premises another licence already covers, so excluding the type
# dropped ~30 public bars outright. A genuine warehouse costs nothing here: it
# publishes no happy-hour window and the evidence gate drops it downstream.
TAPROOM_TYPES = {
    "Brewery",
    "Brewery Storage",
    "Limited Winery",
    "Limited Distillery",
    "Distillery",
    "Winery",
    "Distillery of Historic Significance",
}

# Members-only. Deliberately excluded from the consumer corpus.
CLUB_TYPES = {
    "Club (Liquor)",
    "Club (Malt)",
    "Catering Club (Liquor)",
    "Privately Owned Private Golf Club",
    "Privately Owned Private Golf Club Catering Club",
}

ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\s*$")

# Zone assignment is one municipality, one zone (tests/test_ingest.py's
# `test_no_municipality_or_zip_is_claimed_twice`), and Conshohocken's downtown
# does not respect that: Ridge Pike west of Fayette St carries a "Conshohocken
# PA" mailing address while sitting in Plymouth Twp, which zones.json already
# gives whole to blue_bell_plymouth_meeting -- correctly, for the Plymouth
# Meeting Mall cluster three-plus miles further up the same township. Giving
# Plymouth Twp to conshohocken instead would take that whole mall district
# with it; splitting the township by ZIP does not work either, because
# municipality is checked first and wins.
#
# So this is a hand list, not a zones.json change, the same shape as
# discover_places.HAND_DROPPED. Found 2026-09-04 by ingest/find_denominator_gaps.py:
# Andy's Diner & Pub, Outback Steakhouse and P.J. Whelihan's all read as
# "missing from Conshohocken" until a distance check against every OTHER
# blue_bell_plymouth_meeting venue's coordinate showed a clean break -- five
# venues cluster at 1.57-1.81 miles from Conshohocken's own anchor (Fayette
# St), then nothing until 1.93 miles and a completely different commercial
# cluster (Plymouth Meeting Mall, Cracker Barrel, Miller's Ale House) starting
# there and continuing to 6+ miles. Every LID below carries a "Conshohocken
# PA" postal address in the PLCB's own export.
CONSHOHOCKEN_BOUNDARY_LIDS = {
    "59081",   # Andy's Diner & Pub, 505 W Ridge Pk
    "62087",   # Outback Steakhouse, 322 Ridge Pk
    "117317",  # P.J. Whelihan's, 200 W Ridge Pike
    "29585",   # Domino's, 107-109 W Ridge Pk
    "32489",   # Franzone's Pizzeria, 1940 Main Ave
    "118876",  # The Goat's Beard (Daisy Tavern), 1100 Hector St
    "101704",  # 641 Old Elm Hotel, 641 Old Elm St
    "101974",  # The Giant Company, 10 E Ridge Pike
    "121138",  # Royal Farms, 906 W Ridge Pike
    "50725",   # Chippers Cafe, 725 Conshohocken Rd
    "69227",   # Weis Markets, 200 Ridge Pk
    "67533",   # Bar Lucca (licensed as Milfred Moon LLC), 729 E Hector St
}


def miles(a, b):
    r = 3958.8
    p = math.pi / 180
    x = (
        math.sin((b[0] - a[0]) * p / 2) ** 2
        + math.cos(a[0] * p) * math.cos(b[0] * p) * math.sin((b[1] - a[1]) * p / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(x))


def download(url, dest, member=None):
    import requests

    print(f"  fetching {url}", file=sys.stderr)
    r = requests.get(url, timeout=180, headers={"User-Agent": "happy-hour-finder/0.1"})
    r.raise_for_status()
    if member:
        tmp = dest + ".zip"
        with open(tmp, "wb") as fh:
            fh.write(r.content)
        with zipfile.ZipFile(tmp) as z:
            with z.open(member) as src, open(dest, "wb") as out:
                out.write(src.read())
        os.remove(tmp)
    else:
        with open(dest, "wb") as fh:
            fh.write(r.content)
    print(f"  wrote {dest} ({os.path.getsize(dest):,} bytes)", file=sys.stderr)


def load_zip_centroids():
    out = {}
    with open(ZIP_TXT, encoding="utf-8") as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) > 10 and f[9] and f[10]:
                out[f[1]] = (float(f[9]), float(f[10]))
    return out


def build_zone_index(zones):
    by_mun, by_zip = {}, {}
    for z in zones["zones"]:
        for mun, county in z.get("municipalities", []):
            by_mun[(mun.lower(), county.lower())] = z["id"]
        for zp in z.get("zips", []):
            by_zip[zp] = z["id"]
    return by_mun, by_zip


def load_licensees():
    """Active, public-facing, on-premises licensees inside the seed market."""
    zones = json.load(open(ZONES_JSON, encoding="utf-8"))
    origin = (zones["origin"]["lat"], zones["origin"]["lng"])
    radius = zones["radius_miles"]
    counties = set(zones["counties_in_scope"])
    by_mun, by_zip = build_zone_index(zones)
    centroids = load_zip_centroids()

    kept, dropped = [], collections.Counter()
    with open(PLCB_CSV, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["Status"] != "Active":
                dropped["not active"] += 1
                continue
            lt = row["License Type"]
            if lt in CORE_TYPES:
                tier = "core"
            elif lt in TAPROOM_TYPES:
                tier = "taproom"
            elif lt in CLUB_TYPES:
                dropped["private club"] += 1
                continue
            else:
                dropped["not on-premises retail"] += 1
                continue
            if row["County"] not in counties:
                dropped["county out of scope"] += 1
                continue
            m = ZIP_RE.search((row["Premises Address"] or "").strip())
            zp = m.group(1) if m else None
            c = centroids.get(zp) if zp else None
            # Municipality wins over ZIP: ZIPs only name zones inside
            # Philadelphia, and a Philadelphia ZIP can spill across the city
            # line (19153 covers both Eastwick and Tinicum Twp).
            zone = by_mun.get(
                (row["Municipality"].lower(), row["County"].lower())
            ) or (by_zip.get(zp) if zp else None)
            if row["LID"] in CONSHOHOCKEN_BOUNDARY_LIDS:
                zone = "conshohocken"
            # 🛑 The zip/centroid gate below existed to answer ONE question --
            # is this row within radius of an unnamed zone -- and it used to
            # run before a resolved municipality was even consulted, so a row
            # a NAMED zone had already claimed could still be dropped for a
            # reason that has nothing to do with it. Found 2026-09-04:
            # Buena Vista Restaurant (Ardmore) carries a PLCB typo, "19005"
            # for what should read "19003", and Vecchia Pizzeria of
            # Phoenixville's own export row ends "19460-" -- a dangling
            # hyphen ZIP_RE cannot parse at all. Both have "Municipality"
            # fields (Lower Merion Twp, Phoenixville) that resolve a zone with
            # no ZIP involved, and both were dropped anyway. 10 active,
            # in-scope-county, municipality-matched rows corpus-wide were
            # blocked by this gate before it moved below the municipality
            # lookup -- same shape as the Kennett Square fix the comment two
            # lines down already describes for the RADIUS half of this same
            # function, just the ZIP half of it.
            if not zone:
                if not m:
                    dropped["no parseable zip"] += 1
                    continue
                if not c:
                    dropped["zip not in gazetteer"] += 1
                    continue
            # 🔑 A NAMED ZONE IS THE SCOPE; the radius only bounds what is NOT
            # named. Kennett Square sits 24 miles from the King of Prussia
            # origin, so adding the zone seeded ONE of its 97 active licences
            # and the other 96 were dropped as "outside radius" -- a town added
            # on purpose, silently emptied by a number set for a different
            # question. Adding a zone is the decision; the radius is not
            # entitled to overrule it.
            dist = miles(origin, c) if c else None
            if dist is not None and dist > radius and not zone:
                dropped["outside radius"] += 1
                continue
            kept.append(
                {
                    "lid": row["LID"],
                    "license_number": row["License Number"],
                    "license_type": lt,
                    "tier": tier,
                    "name": row["Premises"] or row["Licensee"],
                    "licensee": row["Licensee"],
                    "address": row["Premises Address"],
                    "zip": zp or "",
                    "municipality": row["Municipality"],
                    "county": row["County"],
                    "zone_id": zone or "",
                    "miles_from_kop": round(dist, 1) if dist is not None else "",
                    "expiration_date": row["Expiration Date"],
                }
            )
    return zones, kept, dropped


def dedupe_premises(rows):
    """One venue can hold several licenses (restaurant + brewery, say)."""
    seen, out = {}, []
    for r in rows:
        key = (r["name"].strip().lower(), r["address"].strip().lower())
        if key in seen:
            prev = seen[key]
            prev["license_number"] += "|" + r["license_number"]
            if r["tier"] == "core":
                prev["tier"] = "core"
            continue
        seen[key] = dict(r)
        out.append(seen[key])
    return out


def print_counts(zones, venues, dropped):
    zone_names = {z["id"]: z["name"] for z in zones["zones"]}
    by_zone = collections.Counter(v["zone_id"] or "(unzoned)" for v in venues)

    print(f"\nActive public on-premises licensees within "
          f"{zones['radius_miles']} mi of King of Prussia: {len(venues)}\n")
    print(f"{'zone':<34}{'venues':>8}{'core':>8}{'taproom':>9}")
    print("-" * 59)
    ordered = [z["id"] for z in zones["zones"]] + ["(unzoned)"]
    for zid in ordered:
        n = by_zone.get(zid, 0)
        if not n:
            continue
        core = sum(1 for v in venues if (v["zone_id"] or "(unzoned)") == zid and v["tier"] == "core")
        tap = n - core
        label = zone_names.get(zid, zid)
        if zid == "center_city":
            label += " *"
        print(f"{label:<34}{n:>8}{core:>8}{tap:>9}")
    print("-" * 59)
    named = sum(v for k, v in by_zone.items() if k != "(unzoned)")
    print(f"{'in a named zone':<34}{named:>8}")
    print(f"{'total':<34}{len(venues):>8}")
    print("\n* Center City is collected but off by default for KoP users.")
    print("\nDropped from the statewide export:")
    for k, v in dropped.most_common():
        print(f"  {v:>7,}  {k}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download source files")
    ap.add_argument("--counts", action="store_true", help="print counts, skip writing venues.csv")
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    if args.refresh or not os.path.exists(PLCB_CSV):
        download(PLCB_EXPORT_URL, PLCB_CSV)
    if args.refresh or not os.path.exists(ZIP_TXT):
        download(GEONAMES_URL, ZIP_TXT, member="US.txt")

    zones, rows, dropped = load_licensees()
    venues = dedupe_premises(rows)
    dropped["duplicate premises (multi-license)"] = len(rows) - len(venues)
    print_counts(zones, venues, dropped)

    if not args.counts:
        fields = list(venues[0].keys())
        # Delaware rides along, in the same file and the same schema, because
        # everything downstream of here reads one venues.csv. It is NOT the same
        # kind of row and the difference is load-bearing: PA comes from the
        # state's own licence export and is a coverage DENOMINATOR, DE comes
        # from Google and is only a working list. See ingest/seed_places_de.py.
        # Its own columns (place_id, website, lat/lng) are dropped here so the
        # schema stays one thing; they live on in data/venues_de.csv.
        extra = []
        if os.path.exists(DE_CSV):
            with open(DE_CSV, encoding="utf-8", newline="") as fh:
                extra = [{k: r.get(k, "") for k in fields}
                         for r in csv.DictReader(fh)]
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(venues)
            w.writerows(extra)
        print(f"\nwrote {OUT_CSV} ({len(venues)} PA venues"
              + (f" + {len(extra)} DE venues from {os.path.relpath(DE_CSV, REPO)}"
                 if extra else "") + ")")


if __name__ == "__main__":
    main()
