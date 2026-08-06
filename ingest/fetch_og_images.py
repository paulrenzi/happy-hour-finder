#!/usr/bin/env python3
"""Give every published venue a photo, using the one it publishes of itself.

    python ingest/fetch_og_images.py --limit 5     # a bounded first pass
    python ingest/fetch_og_images.py               # every published venue

Writes data/venue_photos.json (the file ingest/fetch_venue_photos.py would have
written from Google Places) plus the images themselves under web/img/venues/.
The bundle build picks them up with no change: a venue with no entry still gets
the app's generated tile.

Why the venue's own og:image rather than Google Places: Places photo *bytes* are
under a caching restriction that a public git repo cannot honour, and the key
isn't in this repo anyway. A site's og:image is the picture that venue chose to
represent itself with -- the same image that appears when someone pastes their
link into a text message -- and it is fetched from the venue, credited to the
venue, and links back to the venue.

Every image is decoded and re-encoded rather than saved as downloaded, which is
what actually drops EXIF (non-negotiable 5): a phone photo uploaded to a
restaurant's site carries GPS, and copying the bytes would republish it.
"""

import argparse
import io
import json
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawl_sites import DELAY, TIMEOUT, UA, allowed  # noqa: E402

BUNDLES = os.path.join(REPO, "web", "data")
IMG_DIR = os.path.join(REPO, "web", "img", "venues")
OUT = os.path.join(REPO, "data", "venue_photos.json")

MAX_W = 900          # the card band is a 16:9 strip 390px wide, 2x for retina
MAX_H = 700
MIN_SRC = 320        # a 100px logo is not a photo of a bar
QUALITY = 82

META_RE = re.compile(r"<meta\s[^>]*>", re.I)
PROP_RE = re.compile(r'(?:property|name)\s*=\s*["\']([^"\']+)["\']', re.I)
CONT_RE = re.compile(r'content\s*=\s*["\']([^"\']+)["\']', re.I)
# A social-share image is the venue's chosen photo of itself. Ranked: Facebook's
# og:image first because it is the one they actually curate.
WANTED = ["og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"]


def og_image(html, page_url):
    """The best social-share image URL on a page, absolutised, or None."""
    import urllib.parse

    found = {}
    for tag in META_RE.findall(html):
        prop, cont = PROP_RE.search(tag), CONT_RE.search(tag)
        if prop and cont and prop.group(1).lower() in WANTED:
            found.setdefault(prop.group(1).lower(), cont.group(1).strip())
    for key in WANTED:
        if found.get(key):
            url = urllib.parse.urljoin(page_url, found[key])
            # A tracking pixel or an SVG logo is not a photograph of the place.
            if url.startswith("http") and not url.lower().endswith(".svg"):
                return url
    return None


IMG_SRC_RE = re.compile(r'<img\s[^>]*src\s*=\s*["\']([^"\']+)["\']', re.I)
# Chrome, a logo and a tracking pixel are all <img>. Names are the only signal
# available without downloading every one of them.
NOT_A_PHOTO = re.compile(
    r"logo|icon|favicon|sprite|badge|avatar|placeholder|blank|pixel|spacer|"
    r"arrow|button|divider|loader|yelp|facebook|instagram|tripadvisor|opentable",
    re.I)


def inline_images(html, page_url, cap=4):
    """Plausible content photos on a page, in document order.

    A third of these sites predate social-share tags entirely, so with no
    og:image the alternative to this is no photo at all. The size floor in
    store() is what actually rejects a logo that slipped past the name filter.
    """
    import urllib.parse

    out, seen = [], set()
    for src in IMG_SRC_RE.findall(html):
        if NOT_A_PHOTO.search(src) or src.lower().endswith((".svg", ".gif")):
            continue
        url = urllib.parse.urljoin(page_url, src.strip())
        if url.startswith("http") and url not in seen:
            seen.add(url)
            out.append(url)
        if len(out) >= cap:
            break
    return out


def store(raw, vid):
    """Decode, downscale, re-encode without metadata. Returns the web path."""
    from PIL import Image

    im = Image.open(io.BytesIO(raw))
    if min(im.size) < MIN_SRC:
        return None, f"too small ({im.size[0]}x{im.size[1]})"
    im = im.convert("RGB")
    # The card band is a 16:9 strip 390px wide, so 900x700 covers it at 2x with
    # room to crop. A phone photo arrives 4032px tall and object-fit throws all
    # of it away -- shipping it would be bytes nobody ever sees.
    im.thumbnail((MAX_W, MAX_H), Image.LANCZOS)
    os.makedirs(IMG_DIR, exist_ok=True)
    # A fresh Image is written from pixels only, so no EXIF block survives --
    # this is the line that satisfies non-negotiable 5, not a later scrub pass.
    out = Image.frombytes("RGB", im.size, im.tobytes())
    out.save(os.path.join(IMG_DIR, f"{vid}.jpg"), "JPEG", quality=QUALITY, optimize=True)
    return f"img/venues/{vid}.jpg", None


def published():
    """(id, name, website) for everything currently in a zone bundle."""
    out = []
    for fn in sorted(os.listdir(BUNDLES)):
        if not fn.startswith("zone-"):
            continue
        for v in json.load(open(os.path.join(BUNDLES, fn), encoding="utf-8"))["venues"]:
            if v.get("website"):
                out.append((v["id"], v["name"], v["website"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refetch", action="store_true", help="revisit venues already stored")
    args = ap.parse_args()

    import requests

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    photos = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    session, robots = requests.Session(), {}
    todo = [t for t in published() if args.refetch or t[0] not in photos]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} venues without a photo\n")

    kept = 0
    for n, (vid, name, site) in enumerate(todo, 1):
        why = None
        try:
            if not allowed(site, robots):
                why = "robots.txt disallows"
            else:
                time.sleep(DELAY)
                r = session.get(site, timeout=TIMEOUT, headers={"User-Agent": UA})
                og = og_image(r.text, r.url) if r.ok else None
                # The share image first; only if the site has none does the page
                # get scanned for a photo, and each candidate must clear the
                # size floor before it is accepted.
                cands = ([og] if og else []) + (inline_images(r.text, r.url) if r.ok else [])
                why = "no image on the page"
                for url in cands[:5]:
                    if not allowed(url, robots):
                        why = "image robots-disallowed"
                        continue
                    time.sleep(DELAY)
                    ir = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
                    if not ir.ok or "image" not in ir.headers.get("content-type", ""):
                        why = f"image fetch {ir.status_code}"
                        continue
                    path, why = store(ir.content, vid)
                    if path:
                        photos[vid] = {
                            "file": path,
                            "attribution": f"Photo: {name}",
                            "source_url": url,
                            "source": "og:image" if url == og else "page image",
                            "page": r.url,
                            "fetched_at": time.strftime("%Y-%m-%d"),
                        }
                        kept += 1
                        break
        except Exception as e:  # noqa: BLE001 -- one dead site must not end the run
            why = f"{type(e).__name__}"
        print(f"[{n}/{len(todo)}] {name[:34]:<36} {'ok' if not why else why}")
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(photos, fh, indent=1, sort_keys=True)

    print(f"\n{kept} new photo(s); {len(photos)} on file -> {OUT}")


if __name__ == "__main__":
    main()
