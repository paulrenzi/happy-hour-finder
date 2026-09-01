#!/usr/bin/env python3
"""Fetch one storefront photo per venue from Google Places and write the manifest
the web app reads.

    GOOGLE_PLACES_API_KEY=...   in happy-hour-finder/.env  (this repo's own key --
                                never reach into another project's credentials)
    python ingest/fetch_venue_photos.py [--limit N] [--force]

Resolution is address-keyed, not name-keyed: two "Iron Hill Brewery" rows are
different bars, and the address is the only field that separates them. A venue
that does not resolve is left out of the manifest rather than guessed at -- the
app draws its own tile for anything missing, so a gap costs nothing.

Google requires the photo's author attribution to be displayed wherever the photo
is, so it is stored alongside the file and rendered on the card.
"""

import argparse
import glob
import json
import os
import sys
import time

# requests is imported lazily by the two functions that reach the network, so the
# path helpers below stay importable -- and the CI test gate stays stdlib-only.

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEALS_JSON = os.path.join(REPO, "data", "deals_seed.json")
MANIFEST = os.path.join(REPO, "data", "venue_photos.json")
# --from-places works off the licence id, so it needs its own manifest: a deal id
# and an LID are different key spaces and must not share a file.
PLACES_JSON = os.path.join(REPO, "data", "places_venues.json")
# --from-board reads the population the SITE actually shows. A manifest's own
# length says nothing about coverage, in EITHER direction: places_venues.json
# held 60 rows against a board of 169, so venues that had never been looked up
# read as "Google has no photo" -- and counting that one file said 7 of 169 were
# covered when the shipped bundles were drawing 125, because a photo reaches a
# card by more than one route. Count what the bundle carries (shipped_with_a_photo),
# never the length of the file you happen to be writing.
BOARD_JSON = os.path.join(REPO, "web", "data", "board-by-lid.json")
BASE_JSON = os.path.join(REPO, "data", "venue_base.json")
LID_MANIFEST = os.path.join(REPO, "data", "venue_photos_by_lid.json")
IMG_DIR = os.path.join(REPO, "web", "img", "venues")

SEARCH = "https://places.googleapis.com/v1/places:searchText"
MAX_W = 800  # a card band is never wider than this on a phone

# Google Places, September 2026 list price. A Text Search asking for
# places.photos bills at the Pro tier, and each photo download is billed again.
# These are here so the run can price itself out loud before it spends anything:
# a silent full-board sweep is a bill Paul finds out about from Google.
USD_PER_SEARCH = 0.032
USD_PER_PHOTO = 0.007


def load_key():
    path = os.path.join(REPO, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k == "GOOGLE_PLACES_API_KEY" and v:
                return v.strip().strip("\"'")
    return os.environ.get("GOOGLE_PLACES_API_KEY")


def resolve(key, venue):
    """Text search keyed on name + full address; take the first place with photos."""
    import requests

    r = requests.post(
        SEARCH,
        headers={
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.photos",
        },
        json={"textQuery": f"{venue['name']}, {venue['address']}", "maxResultCount": 1},
        timeout=30,
    )
    r.raise_for_status()
    places = r.json().get("places", [])
    if not places or not places[0].get("photos"):
        return None
    return places[0]


def photo_dest(vid):
    """Where the bytes go, and the path the app will ask for.

    These are different roots and must be derived together: the manifest stores a
    path relative to the *web* root, so joining it against REPO writes outside
    IMG_DIR -- into a directory nothing creates.
    """
    return os.path.join(IMG_DIR, f"{vid}.jpg"), f"img/venues/{vid}.jpg"


def download(key, photo, dest):
    import requests

    r = requests.get(
        f"https://places.googleapis.com/v1/{photo['name']}/media",
        params={"maxWidthPx": MAX_W, "key": key},
        timeout=60,
    )
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError(f"not an image: {r.headers.get('content-type')}")
    with open(dest, "wb") as fh:
        fh.write(r.content)
    return len(r.content)


def from_places(args, key, requests):
    """Download photos for venues already resolved by discover_places.py.

    That pass kept each venue's photo resource name, so the search half is
    already paid for -- re-resolving here would bill a second Places lookup per
    venue to learn something on disk. Keyed by PLCB licence id rather than a
    deal id, because the point of this mode is venues that have no deal yet.
    """
    resolved = json.load(open(PLACES_JSON, encoding="utf-8"))
    manifest = json.load(open(LID_MANIFEST, encoding="utf-8")) if os.path.exists(LID_MANIFEST) else {}
    os.makedirs(IMG_DIR, exist_ok=True)

    todo = [
        (lid, e) for lid, e in sorted(resolved.items())
        if e.get("photo_names") and (args.force or lid not in manifest)
        and (not args.zone or e.get("zone_id") == args.zone)
    ]
    if args.limit:
        todo = todo[: args.limit]
    print(f"venues with a photo to fetch: {len(todo)}\n")

    for lid, e in todo:
        dest, rel = photo_dest(lid)
        try:
            size = download(key, {"name": e["photo_names"][0]}, dest)
        except OSError as err:
            sys.exit(f"  {lid:<10} cannot write {dest}: {err}")
        except Exception as err:  # noqa: BLE001 -- one venue must not stop the run
            print(f"  {lid:<10} {e['name'][:34]:<36} download failed: {err}")
            continue
        manifest[lid] = {
            "file": rel,
            "attribution": "Photo: Google",
            "place_id": e["place_id"],
            "resolved_name": e.get("places_name"),
            "resolved_address": e.get("places_address"),
            "fetched_at": time.strftime("%Y-%m-%d"),
        }
        print(f"  {lid:<10} {e['name'][:34]:<36} {size:>7,} bytes  <- {e.get('places_name')}")

    with open(LID_MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    print(f"\n{len(manifest)} venues have a photo -> {LID_MANIFEST}")


def shipped_with_a_photo():
    """The LIDs whose CARD has a picture on it, read off the shipped bundles.

    Not the length of any one manifest, and not this file's manifest either.
    Photos reach a card by more than one route -- venue_photos_by_lid.json is
    only one of them -- so counting that file gave 7 of 169 when the board was
    in fact drawing 125. Believing it would have billed 118 lookups for photos
    the site already has. The bundle is what the reader sees, so the bundle is
    what gets counted.
    """
    out = set()
    for path in glob.glob(os.path.join(REPO, "web", "data", "zone-*.json")):
        for v in json.load(open(path, encoding="utf-8"))["venues"]:
            if v.get("photo"):
                out.add(str(v.get("lid") or v.get("id")))
    return out


def absorbed_lids():
    """LIDs that ride along in another card's also_lids and render nothing.

    A second PLCB licence at one address -- the supermarket next door wearing
    the bar's trade name -- is collapsed into the bar's card by build_bundles.
    It is still a key in board-by-lid.json, and base.get(lid) still carries the
    LICENSEE name, so searching it asks Google for GIANT and buys a photograph
    of a grocery store. Six were bought that way before this guard existed, and
    not one reached a card -- the winner keeps its own picture -- so the whole
    outlay was waste. Not a card => never a lookup.
    """
    out = set()
    for path in glob.glob(os.path.join(REPO, "web", "data", "zone-*.json")):
        for v in json.load(open(path, encoding="utf-8"))["venues"]:
            out.update(str(l) for l in (v.get("also_lids") or []))
    return out


def from_board(args, key):
    """Fetch photos for the venues that are ON THE BOARD and have none.

    --from-places can only ever cover what discover_places.py happened to look
    up. This mode starts from the other end -- the LIDs the site renders -- so a
    venue like Black Powder Tavern, which was on the board but had never been
    resolved, is in the population by construction. Same LID key space and same
    manifest as --from-places; only the population differs.
    """
    board = json.load(open(BOARD_JSON, encoding="utf-8"))
    base = json.load(open(BASE_JSON, encoding="utf-8"))
    manifest = json.load(open(LID_MANIFEST, encoding="utf-8")) if os.path.exists(LID_MANIFEST) else {}

    covered = shipped_with_a_photo()
    absorbed = absorbed_lids() & set(board)
    print(f"board: {len(board)} venues, {len(covered & set(board))} with a photo "
          f"({len(set(board) - covered - absorbed)} without)")
    if absorbed:
        print(f"{len(absorbed)} collapsed second licence(s) skipped -- not cards")

    todo = []
    unknown = []
    for lid in sorted(board):
        if lid in covered and not args.force:
            continue
        if lid in absorbed:
            continue
        b = base.get(lid)
        # Resolution is address-keyed on purpose -- two "Iron Hill Brewery" rows
        # are different bars -- so a venue with no address is left out rather
        # than searched on a name that would match the wrong one.
        if not b or not b.get("address"):
            unknown.append(lid)
            continue
        if args.zone and b.get("zone_id") != args.zone:
            continue
        todo.append((lid, b))
    if args.limit:
        todo = todo[: args.limit]

    if unknown:
        print(f"{len(unknown)} board venues have no address on file and are skipped")

    cost = len(todo) * (USD_PER_SEARCH + USD_PER_PHOTO)
    print(f"{len(todo)} lookups to run -- about ${cost:,.2f} at Google list price "
          f"(${USD_PER_SEARCH:.3f} search + ${USD_PER_PHOTO:.3f} photo each)")
    if not args.spend:
        print("\nNothing spent. Re-run with --spend to actually fetch.")
        return
    print()

    os.makedirs(IMG_DIR, exist_ok=True)
    import requests

    for n, (lid, b) in enumerate(todo, 1):
        try:
            place = resolve(key, b)
        except requests.HTTPError as err:
            print(f"[{n}/{len(todo)}] {lid:<8} {b['name'][:34]:<36} search failed: {err}")
            continue
        if not place:
            print(f"[{n}/{len(todo)}] {lid:<8} {b['name'][:34]:<36} no photo on Places")
            continue

        photo = place["photos"][0]
        dest, rel = photo_dest(lid)
        try:
            size = download(key, photo, dest)
        except OSError as err:
            # A local write failure is systemic, not per-venue: continuing bills
            # a Places call for every remaining venue and stores none of them.
            _save(manifest)
            sys.exit(f"  {lid:<8} cannot write {dest}: {err}")
        except Exception as err:  # noqa: BLE001 -- one venue must not stop the run
            print(f"[{n}/{len(todo)}] {lid:<8} {b['name'][:34]:<36} download failed: {err}")
            continue

        authors = [a.get("displayName", "") for a in photo.get("authorAttributions", [])]
        manifest[lid] = {
            "file": rel,
            # Google requires the author attribution to be shown wherever the
            # photo is, so it is stored beside the file and rendered on the card.
            "attribution": ("Photo: " + ", ".join(a for a in authors if a) + " / Google")
            if any(authors) else "Photo: Google",
            "place_id": place["id"],
            "resolved_name": place.get("displayName", {}).get("text"),
            "resolved_address": place.get("formattedAddress"),
            "fetched_at": time.strftime("%Y-%m-%d"),
        }
        print(f"[{n}/{len(todo)}] {lid:<8} {b['name'][:34]:<36} {size:>7,} bytes"
              f"  <- {manifest[lid]['resolved_name']}")
        # Written as we go: a lookup already billed must not be thrown away by
        # an interrupt half way through the sweep.
        _save(manifest)

    _save(manifest)
    # NOT len(manifest & board): this file is one of several routes a photo
    # takes to a card, so it printed "62/170" straight after a run that had
    # just taken the board to full coverage -- the very miscount that
    # shipped_with_a_photo() exists to avoid. The bundles are stale until the
    # rebuild, so report the fetch and let the rebuild report the board.
    print(f"\n{len(manifest)} venue(s) on file -> {LID_MANIFEST}")
    print("Now run: python ingest/build_venue_base.py && "
          "python ingest/build_bundles.py")
    print("Now run: python ingest/build_venue_base.py && python ingest/build_bundles.py")


def _save(manifest):
    tmp = LID_MANIFEST + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    os.replace(tmp, LID_MANIFEST)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N lookups")
    ap.add_argument("--force", action="store_true", help="refetch venues already in the manifest")
    ap.add_argument("--from-places", action="store_true",
                    help="use photo references discover_places.py already fetched")
    ap.add_argument("--from-board", action="store_true",
                    help="cover the venues the site actually shows (board-by-lid.json)")
    ap.add_argument("--spend", action="store_true",
                    help="with --from-board, actually run the billed lookups")
    ap.add_argument("--zone", help="with --from-places/--from-board, restrict to one zone")
    args = ap.parse_args()

    if args.from_board:
        key = load_key()
        # Priced before the key is demanded: the cost question is worth answering
        # on a machine that has no key at all.
        if not key and args.spend:
            sys.exit("No GOOGLE_PLACES_API_KEY. Put one in happy-hour-finder/.env")
        return from_board(args, key)

    if args.from_places:
        import requests

        key = load_key()
        if not key:
            sys.exit("No GOOGLE_PLACES_API_KEY. Put one in happy-hour-finder/.env")
        return from_places(args, key, requests)

    import requests  # the run itself needs it; fail here, before any work

    key = load_key()
    if not key:
        sys.exit(
            "No GOOGLE_PLACES_API_KEY. Put one in happy-hour-finder/.env -- this project\n"
            "keeps its own credentials and does not read another repo's .env."
        )

    venues = json.load(open(DEALS_JSON, encoding="utf-8"))["venues"]
    manifest = json.load(open(MANIFEST, encoding="utf-8")) if os.path.exists(MANIFEST) else {}
    os.makedirs(IMG_DIR, exist_ok=True)

    done = 0
    for venue in venues:
        vid = venue["id"]
        if vid in manifest and not args.force:
            continue
        if args.limit and done >= args.limit:
            break
        done += 1
        try:
            place = resolve(key, venue)
        except requests.HTTPError as e:
            print(f"  {vid:<34} search failed: {e}")
            continue
        if not place:
            print(f"  {vid:<34} no photo on Places")
            continue

        photo = place["photos"][0]
        dest, rel = photo_dest(vid)
        try:
            size = download(key, photo, dest)
        except OSError as e:
            # A local write failure is systemic, not per-venue. Continuing here
            # bills a Places call per remaining venue and stores none of them.
            sys.exit(f"  {vid:<34} cannot write {dest}: {e}")
        except Exception as e:  # noqa: BLE001 -- one venue failing must not stop the run
            print(f"  {vid:<34} download failed: {e}")
            continue

        authors = [a.get("displayName", "") for a in photo.get("authorAttributions", [])]
        manifest[vid] = {
            "file": rel,
            "attribution": ("Photo: " + ", ".join(a for a in authors if a) + " / Google")
            if authors
            else "Photo: Google",
            "place_id": place["id"],
            "resolved_name": place.get("displayName", {}).get("text"),
            "resolved_address": place.get("formattedAddress"),
            "fetched_at": time.strftime("%Y-%m-%d"),
        }
        print(f"  {vid:<34} {size:>7,} bytes  <- {manifest[vid]['resolved_name']}")

    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    print(f"\n{len(manifest)}/{len(venues)} venues have a photo -> {MANIFEST}")
    print("Now run: python ingest/build_bundles.py")


if __name__ == "__main__":
    main()
