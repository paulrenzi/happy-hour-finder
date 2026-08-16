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


def load_photo_deals():
    if os.path.exists(PHOTO_JSON):
        return json.load(open(PHOTO_JSON, encoding="utf-8"))
    return {"venues": []}


def show(sub, extracted):
    print("=" * 72)
    print(f"{sub['venue_name'] or '(no name given)'}   LID {sub['lid']}")
    print(f"submitted {sub['submitted_at']}   {sub['bytes'] // 1024} KB")
    if sub.get("note"):
        print(f"their note: {sub['note']}")
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
    # One photo replaces what an earlier photo of the same venue said. A newer
    # menu is the newer truth, and two photos of the same board would otherwise
    # double every window.
    venue["deals"] = [
        d for d in venue["deals"] if d.get("source", {}).get("photo_id") != sub["id"]
    ]
    venue["deals"].extend(extracted["deals"])
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
