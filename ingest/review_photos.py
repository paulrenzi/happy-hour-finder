#!/usr/bin/env python3
"""The moderation queue for photo submissions (SPEC section 8).

Nothing a stranger uploads reaches the board without passing through here. For
each extracted submission this saves the photo locally, opens it, prints what
the model read out of it, and waits for you.

    python ingest/review_photos.py             # walk the extracted queue
    python ingest/review_photos.py --status pending   # the ones extraction skipped
    python ingest/review_photos.py --no-open   # don't launch an image viewer

Approving writes the deals into data/deals_photo.json, which
ingest/build_bundles.py merges. Approving is NOT publishing: run

    python ingest/build_bundles.py && git add -A && git commit && git push

and the card appears on the next Pages deploy.

Reads the same happy-hour-finder/.env as ingest/extract_photo_deals.py.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_photo_deals import api, env_file, fetch_photo  # noqa: E402

PHOTO_JSON = os.path.join(REPO, "data", "deals_photo.json")
BASE_JSON = os.path.join(REPO, "data", "venue_base.json")
# Same order ingest/build_bundles.py publishes in, so what this prints as "on
# the board" is what is actually on the board.
BOARD_JSON = [
    PHOTO_JSON,
    os.path.join(REPO, "data", "deals_seed.json"),
    os.path.join(REPO, "data", "deals_extracted.json"),
]


def load_photo_deals():
    if os.path.exists(PHOTO_JSON):
        return json.load(open(PHOTO_JSON, encoding="utf-8"))
    return {"venues": []}


def on_board(lid):
    """What this venue's card says right now, highest-priority source first.

    Printed next to what the photo says, because most submissions are not a new
    venue -- they are somebody telling us the hours we are showing are stale.
    Approving is a replacement, so the thing being replaced has to be visible at
    the moment of the decision, not looked up afterwards.
    """
    for path in BOARD_JSON:
        if not os.path.exists(path):
            continue
        for v in json.load(open(path, encoding="utf-8"))["venues"]:
            if v["id"] == lid and v.get("deals"):
                return os.path.basename(path), v["deals"]
    return None, []


def print_board(lid):
    where, deals = on_board(lid)
    if not deals:
        print("  on the board now: nothing -- this venue has no published hours")
        return
    print(f"  ON THE BOARD NOW (from {where}) -- approving REPLACES this:")
    for d in deals:
        src = (d.get("source") or {}).get("kind", "?")
        print(f"    [{d.get('type')}] {src}, checked {d.get('last_verified_at', '?')}")
        for w in d.get("windows") or []:
            print(f"      day {w['dow']}  {w['start']}-{w['end']}")


def show(sub, extracted):
    print("=" * 72)
    print(f"{sub['venue_name'] or '(no name given)'}   LID {sub['lid']}")
    print(f"submitted {sub['submitted_at']}   {sub['bytes'] // 1024} KB")
    if sub.get("note"):
        print(f"their note: {sub['note']}")
    print_board(sub["lid"])
    print("-" * 72)
    if not extracted.get("is_menu", True):
        print(f"NOT A MENU: {extracted.get('reason', '')}")
    for concern in extracted.get("concerns") or []:
        print(f"  !! {concern}")
    on_menu = extracted.get("venue_name_on_menu")
    if on_menu:
        print(f"  name printed on the menu: {on_menu}")
        # The submitter picked the venue; the menu names one too. When they
        # disagree, one of them is wrong and neither is authoritative.
        if sub["venue_name"] and on_menu.lower()[:12] not in sub["venue_name"].lower():
            print("  !! that does NOT look like the venue they picked -- check before approving")
    for deal in extracted.get("deals") or []:
        print(f"\n  [{deal['type']}]  confidence {deal['confidence']}")
        for w in deal["windows"]:
            print(f"    day {w['dow']}  {w['start']}-{w['end']}")
        for item in deal["items"]:
            price = item.get("price_usd")
            off = item.get("discount_pct")
            amount = f"${price:g}" if price is not None else (f"{off:g}% off" if off else "?")
            print(f"    {amount:>10}  {item['category']:<10} {item['label']}")
        if deal.get("fine_print"):
            print(f"    fine print: {deal['fine_print']}")
    for line in extracted.get("rejected") or []:
        print(f"  dropped: {line}")
    if not extracted.get("deals"):
        print("\n  nothing publishable was read off this photo")
    print("-" * 72)


# A happy hour menu is often several pages, and those arrive as separate
# submissions a minute apart. A menu CHANGING arrives weeks later. Six hours
# tells those two cases apart with room to spare, and is the only reason this
# needs a window at all rather than "the newest photo wins".
PAGE_SET_HOURS = 6


def submitted_at(deal):
    return (deal.get("source") or {}).get("submitted") or ""


def merge_mode(extracted):
    """"add" if the reviewer said this photo is more of the same menu.

    Six hours tells the two common cases apart, but a second page photographed
    the next day is, by the clock, indistinguishable from a menu that changed.
    So the reviewer answers it at approval time and the answer rides on the
    deal. No answer means "replace", which is the safe end: hours that changed
    and did not supersede leave a card contradicting itself, while pages that
    replaced each other lose items the next photo puts back.
    """
    for deal in (extracted or {}).get("deals") or []:
        if (deal.get("source") or {}).get("merge") == "add":
            return "add"
    return "replace"


def superseded(deals, sub, mode="replace"):
    """The deals of this venue that survive approving `sub`.

    A newer photo is the newer truth: the menu on the wall today replaces the
    menu that was on the wall in June, so an older photo's windows come off the
    board rather than sitting beside the new ones. Pages of the SAME menu are
    not older -- they arrive together, so they add.

    This used to filter on `photo_id != sub["id"]`, which drops the deals of the
    submission being approved (there are none -- it has not been approved yet)
    and keeps every stale one. The result was a venue whose card grew a second,
    contradictory happy hour every time somebody corrected it.
    """
    if mode == "add":
        # Another page of the menu already on the board. Only this photo's own
        # deals come off, so re-approving it cannot double them up.
        return [d for d in deals if (d.get("source") or {}).get("photo_id") != sub["id"]]
    this = sub["submitted_at"]
    try:
        when = datetime.datetime.fromisoformat(this.replace("Z", "+00:00"))
    except ValueError:
        # An unparseable timestamp must not silently mean "supersede nothing".
        print("  ! submitted_at is unreadable -- replacing ALL earlier photo deals")
        return [d for d in deals if (d.get("source") or {}).get("kind") != "photo"]
    cutoff = (when - datetime.timedelta(hours=PAGE_SET_HOURS)).isoformat().replace("+00:00", "Z")
    kept = []
    for d in deals:
        src = d.get("source") or {}
        if src.get("kind") != "photo":
            kept.append(d)  # nothing else writes this file today, but do not eat it
        elif src.get("photo_id") == sub["id"]:
            continue  # re-approving the same photo replaces its own deals
        elif submitted_at(d) >= cutoff:
            kept.append(d)  # another page of the same menu
    dropped = len(deals) - len(kept)
    if dropped:
        print(f"  superseding {dropped} deal(s) from an earlier photo of this venue")
    return kept


def approve(sub, extracted, base):
    """Attach the deals to a venue row in data/deals_photo.json."""
    payload = load_photo_deals()
    b = base.get(sub["lid"]) or {}
    venue = next((v for v in payload["venues"] if v["id"] == sub["lid"]), None)
    if venue is None:
        venue = {
            "id": sub["lid"],
            "lid": sub["lid"],
            "name": b.get("name") or sub["venue_name"] or sub["lid"],
            "address": b.get("address", ""),
            "zone_id": b.get("zone_id", ""),
            "deals": [],
        }
        if b.get("website"):
            venue["website"] = b["website"]
        payload["venues"].append(venue)
    venue["deals"] = superseded(venue["deals"], sub, merge_mode(extracted)) + extracted["deals"]
    with open(PHOTO_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    return venue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="extracted", choices=["extracted", "pending"])
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    env = dict(os.environ)
    env.update(env_file())
    for key in ("SUBMIT_API", "ADMIN_TOKEN"):
        if not env.get(key):
            print(f"missing {key} -- see the docstring", file=sys.stderr)
            return 1

    base = json.load(open(BASE_JSON, encoding="utf-8")) if os.path.exists(BASE_JSON) else {}
    queue = api(env, f"/admin/queue?status={args.status}")["submissions"]
    if not queue:
        print(f"nothing {args.status}")
        return 0
    print(f"{len(queue)} submission(s) to review\n")

    for sub in queue:
        extracted = json.loads(sub["extracted"]) if sub.get("extracted") else {}
        if sub.get("extract_error"):
            print(f"(extraction failed: {sub['extract_error']})")
        show(sub, extracted)
        path = fetch_photo(env, sub)
        print(f"photo: {path}")
        if not args.no_open:
            try:
                os.startfile(path)  # noqa: B606  -- Windows; Paul's machine
            except AttributeError:
                subprocess.run(["xdg-open", path], check=False)

        publishable = bool(extracted.get("deals"))
        prompt = "[a]pprove  [r]eject  [s]kip  [q]uit > " if publishable else "[r]eject  [s]kip  [q]uit > "
        while True:
            choice = input(prompt).strip().lower()
            if choice == "q":
                print("stopped. Nothing further reviewed.")
                return 0
            if choice == "s":
                break
            if choice == "r":
                note = input("  why? (goes in the record) > ").strip()
                api(env, f"/admin/review/{sub['id']}", "POST",
                    {"status": "rejected", "note": note})
                print("  rejected")
                break
            if choice == "a" and publishable:
                venue = approve(sub, extracted, base)
                api(env, f"/admin/review/{sub['id']}", "POST",
                    {"status": "approved", "note": input("  note (optional) > ").strip()})
                print(f"  approved -> {venue['name']} now has {len(venue['deals'])} deal(s)")
                if not venue["zone_id"]:
                    print("  ! this LID is not in data/venue_base.json, so it has no zone "
                          "and will not appear until the base is rebuilt")
                break
            print("  a, r, s or q")
        print()

    print("Approved deals are in data/deals_photo.json but NOT on the site.\n"
          "Publish with: python ingest/build_bundles.py, then commit and push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
