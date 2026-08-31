#!/usr/bin/env python3
"""Fold everything approved on the Worker into data/deals_photo.json.

The admin page approves on the Worker, which makes a deal visible in seconds
through GET /live/deals.json. That is the overlay, and it is deliberately not
durable: it is a patch applied over the built bundles at page load.

This is the other half. It pulls every approved submission down and writes it
into the file the bundle build reads, so the next build bakes it in permanently
and the overlay entry becomes a no-op -- the app skips an overlay deal whose
photo_id is already in the bundle it just loaded.

Without this, an approval made on the admin page lives only as long as the row
does, and a rebuild would quietly drop it off the board. Run it before every
build:

    python ingest/sync_approved.py
    python ingest/build_bundles.py

Uses the same supersession rule as ingest/review_photos.py, from that module, so
there is one definition of what a newer photo replaces.
"""

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_photo_deals import api, env_file  # noqa: E402
from review_photos import PHOTO_JSON, load_photo_deals, superseded  # noqa: E402

BASE_JSON = os.path.join(REPO, "data", "venue_base.json")


def main():
    env = dict(os.environ)
    env.update(env_file())
    for key in ("SUBMIT_API", "ADMIN_TOKEN"):
        if not env.get(key):
            print(f"missing {key} -- see ingest/extract_photo_deals.py", file=sys.stderr)
            return 1

    base = json.load(open(BASE_JSON, encoding="utf-8")) if os.path.exists(BASE_JSON) else {}
    payload = load_photo_deals()
    approved = api(env, "/admin/queue?status=approved")["submissions"]

    # Oldest first, so a run that folds in several submissions applies them in
    # the order they were approved -- the same order review_photos.py would
    # have applied them one at a time. Supersession depends on it.
    approved.sort(key=lambda s: s["submitted_at"])

    added = 0
    for sub in approved:
        try:
            extracted = json.loads(sub["extracted"] or "{}")
        except json.JSONDecodeError:
            print(f"  ! {sub['id'][:8]} has unreadable extracted JSON -- skipped")
            continue
        if not extracted.get("deals"):
            continue

        venue = next((v for v in payload["venues"] if v["id"] == sub["lid"]), None)
        if venue and any(
            (d.get("source") or {}).get("photo_id") == sub["id"] for d in venue["deals"]
        ):
            continue  # already folded in by an earlier run

        b = base.get(sub["lid"]) or {}
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

        venue["deals"] = superseded(venue["deals"], sub) + extracted["deals"]
        added += len(extracted["deals"])
        print(f"  {sub['id'][:8]}  {venue['name']}  +{len(extracted['deals'])} deal(s)")

    if not added:
        print("nothing new to fold in")
        return 0

    # Never truncate before the new bytes exist.
    tmp = PHOTO_JSON + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, PHOTO_JSON)
    print(f"\n{added} deal(s) written to data/deals_photo.json")
    print("Now: python ingest/build_bundles.py, then commit and push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
