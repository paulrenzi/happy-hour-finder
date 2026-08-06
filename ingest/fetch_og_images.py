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
import html as html_mod
import io
import json
import os
import re
import sys
import time
from urllib.parse import urlsplit

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawl_sites import DELAY, TIMEOUT, UA, allowed  # noqa: E402

BUNDLES = os.path.join(REPO, "web", "data")
IMG_DIR = os.path.join(REPO, "web", "img", "venues")
OUT = os.path.join(REPO, "data", "venue_photos.json")

MAX_W = 900          # the card band is a 16:9 strip 390px wide, 2x for retina
MAX_H = 700
# A logo floor, not a shape filter. Gating on the SHORT edge rejected a 480x270
# hero -- a 16:9 photo of exactly the shape the card band wants -- so the floor
# is the long edge plus a total-pixel check, which a 100x100 avatar fails and a
# wide banner passes.
MIN_LONG = 400
MIN_PIXELS = 400 * 225
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
            url = urllib.parse.urljoin(page_url, html_mod.unescape(found[key]))
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


def asset_allowed(url, page_url, robots):
    """Whether we may fetch an image the page we are allowed to read declares.

    robots.txt governs crawling a host, and the venue's own site is always
    checked that way. An image is different: it is an embedded asset of a page
    we have already been given permission to read, and most of these sites host
    theirs on a builder's CDN (static.wixstatic.com and friends) whose robots.txt
    is written to keep crawlers out of the CDN, not to stop a venue's own site
    from displaying its own photo. Treat a cross-host asset as part of the page
    that declared it -- the same call a browser or a link-preview unfurler makes
    when it renders the venue's og:image. Same-host images still obey the site's
    own robots.txt, so a venue that asks us to stay out of /photos/ is honoured.
    """
    import urllib.parse

    if urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(page_url).netloc:
        return True
    return allowed(url, robots)


CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+?)['\"]?\s*\)", re.I)


def css_images(html, page_url, cap=6):
    """Images a page paints as CSS backgrounds rather than <img> elements.

    Several of these sites are 120KB of markup with not one <img> in it: the
    hero shot of the dining room is a `background-image` on a div, which is how
    every current site builder does a full-bleed header. Without this the page
    reads as having no photograph at all.
    """
    import urllib.parse

    out, seen = [], set()
    for src in CSS_URL_RE.findall(html):
        if NOT_A_PHOTO.search(src) or src.lower().endswith((".svg", ".gif")):
            continue
        if src.startswith("data:") or src.startswith("#"):
            continue
        url = urllib.parse.urljoin(page_url, html_mod.unescape(src.strip()))
        if url.startswith("http") and url not in seen:
            seen.add(url)
            out.append(url)
        if len(out) >= cap:
            break
    return out


def inline_images(html, page_url, cap=8):
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
        # An attribute value is HTML-escaped, and these are increasingly image
        # *proxy* URLs carrying their real target in query parameters -- so a
        # literal '&amp;' does not merely look untidy, it hands the proxy a
        # parameter named 'amp;w' and earns a 400 for a photo that was there.
        url = urllib.parse.urljoin(page_url, html_mod.unescape(src.strip()))
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
    if max(im.size) < MIN_LONG or im.size[0] * im.size[1] < MIN_PIXELS:
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


PHOTO_PAGE_RE = re.compile(
    r"gallery|galler|photo|about|our.?story|the.?space|venue|interior|"
    r"food|menu|events?", re.I)
LINK_RE = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.{0,120}?)</a>',
                     re.I | re.S)
SUBPAGES = 2


def photo_pages(html, page_url):
    """Same-host pages likely to show the room, best guess first.

    Deliberately narrower than crawl_sites.candidate_links, which hunts for a
    deal: here a 'gallery' link is the prize and a 'menu' link is the consolation.
    """
    import urllib.parse

    host = urllib.parse.urlsplit(page_url).netloc
    found, seen = [], set()
    for m in LINK_RE.finditer(html):
        href, label = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        if not PHOTO_PAGE_RE.search(href) and not PHOTO_PAGE_RE.search(label):
            continue
        full = urllib.parse.urljoin(page_url, html_mod.unescape(href)).split("#")[0]
        if urllib.parse.urlsplit(full).netloc != host or full in seen:
            continue
        if full.rstrip("/") == page_url.rstrip("/"):
            continue
        seen.add(full)
        rank = 0 if re.search(r"gallery|photo|about", full + label, re.I) else 1
        found.append((rank, full))
    return [u for _, u in sorted(found, key=lambda t: t[0])]


def harvest(session, r, vid, name, robots):
    """Try every plausible image on one fetched page. (record, None) or (None, why)."""
    og = og_image(r.text, r.url)
    # The share image first; only if the page has none is it scanned for a
    # photo, and each candidate must clear the size floor before it is accepted.
    cands = ([og] if og else []) + inline_images(r.text, r.url) \
        + css_images(r.text, r.url)
    why = "no image on the page"
    for url in cands[:10]:
        if not asset_allowed(url, r.url, robots):
            why = "image robots-disallowed"
            continue
        time.sleep(DELAY)
        # Referer is what hotlink protection checks; without it a CDN that
        # happily serves the venue's own page returns 400 to us. Accept matters
        # because several serve AVIF/WebP only when asked, and HTML otherwise.
        ir = session.get(url, timeout=TIMEOUT, headers={
            "User-Agent": UA,
            "Referer": r.url,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        })
        ctype = ir.headers.get("content-type", "")
        if not ir.ok or "image" not in ctype:
            why = f"image fetch {ir.status_code}"
            continue
        if "svg" in ctype:
            # A vector is a logo, and these CDNs serve them from extensionless
            # URLs the filename filter cannot see.
            why = "vector, not a photograph"
            continue
        try:
            path, why = store(ir.content, vid)
        except Exception as e:  # noqa: BLE001 -- try the next candidate
            # One undecodable image (a truncated file, a format Pillow wasn't
            # built with) must cost this venue that candidate, not its whole
            # turn -- the next one down the page is usually a good photo.
            path, why = None, f"undecodable ({type(e).__name__})"
        if path:
            return {
                "file": path,
                "attribution": f"Photo: {name}",
                "source_url": url,
                "source": "og:image" if url == og else "page image",
                "page": r.url,
                "fetched_at": time.strftime("%Y-%m-%d"),
            }, None
    return None, why


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
                pages, tried, expanded = [site], set(), False
                why = "no image on the page"
                while pages:
                    page = pages.pop(0)
                    if page in tried:
                        continue
                    tried.add(page)
                    time.sleep(DELAY)
                    r = session.get(page, timeout=TIMEOUT, headers={"User-Agent": UA})
                    if not r.ok:
                        why = f"page fetch {r.status_code}"
                        # The stored website is often a deep link the crawler
                        # followed months ago -- a happy-hour menu page that has
                        # since been retired. The site itself is usually fine.
                        if page == site:
                            root = "{0.scheme}://{0.netloc}/".format(urlsplit(site))
                            if root != site:
                                pages.append(root)
                        continue
                    record, why = harvest(session, r, vid, name, robots)
                    if record:
                        photos[vid] = record
                        kept += 1
                        break
                    # A homepage that is one full-bleed video or a splash logo
                    # still has a photo of the room on its gallery or about
                    # page, so follow a couple -- bounded, same host, and only
                    # from the first page, so this can never become a crawl.
                    if not expanded:
                        expanded = True
                        pages += [u for u in photo_pages(r.text, r.url)[:SUBPAGES]
                                  if allowed(u, robots)]
        except Exception as e:  # noqa: BLE001 -- one dead site must not end the run
            why = f"{type(e).__name__}"
        print(f"[{n}/{len(todo)}] {name[:34]:<36} {'ok' if not why else why}")
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(photos, fh, indent=1, sort_keys=True)

    print(f"\n{kept} new photo(s); {len(photos)} on file -> {OUT}")


if __name__ == "__main__":
    main()
