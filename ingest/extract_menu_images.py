#!/usr/bin/env python3
"""Read the happy-hour menus that venues published as a PICTURE.

    python ingest/extract_menu_images.py --limit 3    # a bounded first pass
    python ingest/extract_menu_images.py              # every image on file
    python ingest/extract_menu_images.py --show

Malbec Argentine Steakhouse is the case this exists for. Our crawler reached
http://www.malbecsteakhouse.com/happyhour/, read the hours off the site
correctly, and returned no prices at all -- because the entire happy-hour menu
on that page is a JPG exported from a PDF. There is not one dollar sign in the
page's HTML. No parser and no smarter language model fixes that; the words are
pixels, and the only way to read them is to look.

So this is the same reviewed vision path a customer's photo submission takes
(ingest/extract_photo_deals.py), pointed at images the crawl found instead. It
reuses that module's prompt, its transcript grounding and its PA validators
rather than restating them, so a menu photographed by a customer and a menu
posted by the venue are held to one standard.

WHAT IT WILL NOT DO. It writes PRICED ITEMS ONLY, into a sidecar, exactly as
ingest/extract_prices_llm.py does. Windows stay the deterministic extractor's
alone -- Malbec's "Tuesday - Friday 4 to 7 PM" was already read correctly off
the venue's own text, and a model looking at a picture is not allowed to
overrule that. An item reaches the sidecar only if its quote is inside the
model's own verbatim transcript AND survives verify() from the price pass.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_deals import HITS, SITES, one_per_osm, slug  # noqa: E402
from extract_photo_deals import ask, ground, norm  # noqa: E402
from extract_prices_llm import verify  # noqa: E402

CACHE = os.path.join(REPO, "data", "menu_images")
OUT = os.path.join(REPO, "data", "deals_menu_images.json")
# The model's verbatim transcript of each menu picture, kept so that
# extract_deals.py can run its own window grammar over the happy-hour lines.
# Rivertown Taps publishes NOTHING in text: its "Wednesday through Friday
# 3pm to 6pm" exists only as pixels, so without this the venue had items
# on file and no card to put them on.
TRANSCRIPTS = os.path.join(REPO, "data", "menu_image_transcripts.json")
# The rendered-artifact audit records what a visitor can see after JavaScript
# and lazy loading.  Its image entries are deliberately not filtered by file
# name: an opaque CMS upload on a page that calls itself happy hour is still a
# menu worth the vision reader's `is_menu` decision.
AUDIT = os.path.join(REPO, "data", "rendered_artifacts.json")
UA = "happy-hour-finder-ingest/1.0 (+https://paulrenzi.github.io/happy-hour-finder/)"
MAX_BYTES = 12_000_000


def image_key(url):
    """One responsive image, not five reads of its size variants."""
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if k.lower() not in {"w", "h", "width", "height", "dpr", "fit", "fm", "format"}]
    path = re.sub(r"-\d{2,4}x\d{2,4}(?=\.(?:jpe?g|png|webp|gif|avif)$)", "",
                  parts.path, flags=re.I)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path,
                                    urllib.parse.urlencode(query), ""))


def image_rank(url):
    """Prefer the largest responsive rendition when one image has many URLs."""
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    def num(key):
        try:
            return float(query.get(key, 0))
        except ValueError:
            return 0
    return max(num("w"), num("width"), num("h"), num("height")) * max(num("dpr"), 1)


def targets():
    """[(venue_id, name, image_url)] for every image a page exposed as a menu.

    The legacy crawler's filename-named menu images remain valid input.  The
    rendered audit adds lazy and opaque images from pages that visibly call
    themselves happy hour.  Both still go through the same visual `is_menu`,
    transcript-grounding, and PA-validation gates below.
    """
    hits = json.load(open(HITS, encoding="utf-8"))
    sites = json.load(open(SITES, encoding="utf-8"))
    out, seen = [], {}

    def add(venue_id, name, url, lid):
        key = image_key(url)
        prior = seen.get(key)
        if prior is None or image_rank(url) > image_rank(prior[2]):
            seen[key] = (venue_id, name, url, lid)
    for lid, v in one_per_osm(hits, sites):
        vid = slug(v["osm_name"] or v["name"], v["address"])
        for im in v.get("menu_images") or []:
            add(vid, v["osm_name"] or v["name"], im["src"], lid)
    if os.path.exists(AUDIT):
        by_lid = {str(lid): (slug(v["osm_name"] or v["name"], v["address"]),
                            v["osm_name"] or v["name"])
                  for lid, v in one_per_osm(hits, sites)}
        audit = json.load(open(AUDIT, encoding="utf-8"))
        for row in audit.values():
            lid = str(row.get("lid") or "")
            owner = by_lid.get(lid)
            if not owner:
                continue
            for asset in row.get("assets") or []:
                if (asset.get("kind") != "image" or not asset.get("candidate")
                        or not asset.get("visible") or not asset.get("url")
                        or not asset.get("url")):
                    continue
                add(owner[0], owner[1], asset["url"], lid)
    return list(seen.values())


def fetch(url):
    """The image on disk, downloaded once. Returns a path, or None."""
    os.makedirs(CACHE, exist_ok=True)
    ext = re.search(r"\.(jpe?g|png|webp)$", url, re.I)
    name = re.sub(r"[^A-Za-z0-9]+", "-", url)[-120:] + "." + (ext.group(1) if ext else "jpg")
    path = os.path.join(CACHE, name)
    if os.path.exists(path):
        return path
    # A WordPress upload keeps the characters that were in the original
    # filename, so a menu posted as '...4-×-6-in.png' is a URL urllib
    # refuses outright with an ascii codec error -- Jerry's Bar was lost to it.
    # Only the path and query are encoded; the host is left alone.
    parts = urllib.parse.urlsplit(url)
    safe = urllib.parse.urlunsplit((
        parts.scheme, parts.netloc,
        urllib.parse.quote(parts.path, safe="/%"),
        urllib.parse.quote(parts.query, safe="=&%"), ""))
    req = urllib.request.Request(safe, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as res:
        blob = res.read(MAX_BYTES)
    if not blob:
        return None
    # Write beside and rename: a half-written image left by an interrupted run
    # is indistinguishable from a cached one on the next pass.
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(blob)
    os.replace(tmp, path)
    return path


def items_from(read):
    """Priced items this menu really states, or [] with the reasons.

    Two gates, both borrowed rather than rewritten: ground() drops anything not
    inside the model's own transcript, then verify() -- the price pass's check
    -- re-reads the number out of the quote and refuses the item if the digits
    are not there.
    """
    kept, dropped = ground(read)
    transcript = read.get("transcript") or ""
    items, seen = [], set()
    for deal in kept:
        # HAPPY-HOUR DEALS ONLY. These items are attached to a happy-hour window
        # the text extractor already validated, so anything else on the sheet is
        # being published under an hour it does not apply to. A page called
        # 'Daily Specials' is the common case and it is a DINNER menu: La Porta
        # offered a $32 crispy duck and Chap's a $17 chopped Italian, both of
        # which would have rendered as happy-hour prices.
        if deal.get("type") != "happy_hour":
            dropped.append(f"{deal.get('type')!r} deal: not the happy hour")
            continue
        for item in deal.get("items") or []:
            clean, why = verify(dict(item, evidence=item.get("quote")), transcript,
                               menu=True)
            if not clean:
                dropped.append(f"{item.get('label')!r}: {why}")
                continue
            key = (clean["label"].lower(), clean.get("price_usd"), clean.get("discount_pct"))
            if key in seen:
                continue
            seen.add(key)
            items.append(clean)
    return items, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--rejects", action="store_true")
    ap.add_argument("--match", help="only venues whose name matches this regex")
    # The scoped-run recipe named this pass with a bare --match, which selects
    # nothing, and Valley Forge Pizza's two happy_hours_page PNGs sat in
    # crawl_hits.json unread for a day. A run names its venues by licence id,
    # the same file every other stage takes.
    ap.add_argument("--lids", help="file of licence ids, one per line")
    ap.add_argument("--force", action="store_true", help="re-read images already transcribed")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    todo = targets()
    if args.match:
        todo = [t for t in todo if re.search(args.match, t[1], re.I)]
    if args.lids:
        only = {ln.strip() for ln in open(args.lids, encoding="utf-8") if ln.strip()}
        todo = [t for t in todo if t[3] in only]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} menu image(s) to read\n")

    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    scripts = (json.load(open(TRANSCRIPTS, encoding="utf-8"))
               if os.path.exists(TRANSCRIPTS) else {})
    for n, (vid, name, url, _lid) in enumerate(todo, 1):
        if not args.force and url in ((scripts.get(vid) or {}).get("images") or {}):
            continue
        try:
            path = fetch(url)
            if not path:
                print(f"[{n}/{len(todo)}] {name[:34]:<36} -- empty download")
                continue
            read = ask(path)
        except Exception as e:  # noqa: BLE001 -- one bad image is not a failed run
            print(f"[{n}/{len(todo)}] {name[:34]:<36} !! {type(e).__name__}: {e}"[:160])
            continue
        if not read.get("is_menu"):
            print(f"[{n}/{len(todo)}] {name[:34]:<36} -- not a menu: "
                  f"{read.get('rejection_reason','')[:60]}")
            continue
        items, dropped = items_from(read)
        if items:
            # Two sheets, one venue: Valley Forge Pizza posts its drinks on
            # page_1 and its food on page_2. Add, never replace.
            fresh = {x["label"].lower() for x in items}
            held = [i for i in out.get(vid, []) if i.get("label", "").lower() not in fresh]
            out[vid] = held + items
        if read.get("transcript"):
            # Every picture's transcript is kept, keyed on its URL, because
            # the hours are on ONE of a venue's sheets and the last one read
            # used to overwrite it. `url`/`transcript` stay as the latest read
            # for anything still reading the old shape.
            rec = scripts.get(vid) or {}
            imgs = dict(rec.get("images") or {})
            if rec.get("url") and rec.get("transcript") and rec["url"] not in imgs:
                imgs[rec["url"]] = rec["transcript"]
            imgs[url] = read["transcript"]
            scripts[vid] = {"url": url, "transcript": read["transcript"], "images": imgs}
        print(f"[{n}/{len(todo)}] {name[:34]:<36} {len(items)} item(s)"
              + (f", {len(dropped)} dropped" if dropped else ""))
        if args.show:
            for it in items:
                amt = (f"${it['price_usd']:g}" if "price_usd" in it
                       else f"{it['discount_pct']:g}% off")
                print(f"      {amt:>8}  {it['label']}")
        if args.rejects:
            for d in dropped:
                print(f"      x {d}")
        # Written every image: a vision pass is slow and interrupting it must
        # not throw away the reads already paid for.
        tmp = OUT + ".new"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
        os.replace(tmp, OUT)
        tmp = TRANSCRIPTS + ".new"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(scripts, fh, indent=1, sort_keys=True)
        os.replace(tmp, TRANSCRIPTS)

    print(f"\n{len(out)} venue(s) on file -> {OUT}")


if __name__ == "__main__":
    main()
