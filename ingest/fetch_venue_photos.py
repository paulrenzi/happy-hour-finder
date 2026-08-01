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
import json
import os
import sys
import time

# requests is imported lazily by the two functions that reach the network, so the
# path helpers below stay importable -- and the CI test gate stays stdlib-only.

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEALS_JSON = os.path.join(REPO, "data", "deals_seed.json")
MANIFEST = os.path.join(REPO, "data", "venue_photos.json")
IMG_DIR = os.path.join(REPO, "web", "img", "venues")

SEARCH = "https://places.googleapis.com/v1/places:searchText"
MAX_W = 800  # a card band is never wider than this on a phone


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N lookups")
    ap.add_argument("--force", action="store_true", help="refetch venues already in the manifest")
    args = ap.parse_args()

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
