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
from review_photos import PHOTO_JSON, load_photo_deals, merge_mode, superseded  # noqa: E402

BASE_JSON = os.path.join(REPO, "data", "venue_base.json")


RANK = {"verified": 3, "likely": 2, "unconfirmed": 1, "disputed": 0}


def upgrade(held, fresh):
    """Is the Worker's copy at least as confident as the one we already hold?"""
    best = lambda ds: max((RANK.get(d.get("confidence"), 1) for d in ds), default=1)  # noqa: E731
    return best(fresh) >= best(held)


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

    added = updated = 0
    for sub in approved:
        try:
            extracted = json.loads(sub["extracted"] or "{}")
        except json.JSONDecodeError:
            print(f"  ! {sub['id'][:8]} has unreadable extracted JSON -- skipped")
            continue
        if not extracted.get("deals"):
            continue

        venue = next((v for v in payload["venues"] if v["id"] == sub["lid"]), None)
        held = [d for d in (venue or {}).get("deals", [])
                if (d.get("source") or {}).get("photo_id") == sub["id"]]
        if held:
            # Folded in by an earlier run -- but the row on the Worker can have
            # CHANGED since: a reviewer approving it, or the auto-approve gate,
            # rewrites the stored extraction to say the deal is verified. A
            # plain `continue` here meant that upgrade never reached the
            # bundles, so the card kept the confidence it had at first read.
            if held == extracted["deals"] or not upgrade(held, extracted["deals"]):
                # Only ever move UP. Approvals made through the local review
                # tool upgrade the copy in this file without telling the
                # Worker, so the Worker's row can be the STALER of the two --
                # and a re-read that quietly demoted a verified deal back to
                # unconfirmed would be this sync undoing a person's decision.
                continue
            venue["deals"] = [d for d in venue["deals"] if d not in held] + extracted["deals"]
            updated += len(extracted["deals"])
            print(f"  {sub['id'][:8]}  {venue['name']}  ~{len(extracted['deals'])} deal(s) re-read")
            continue

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

        venue["deals"] = superseded(venue["deals"], sub, merge_mode(extracted)) + extracted["deals"]
        added += len(extracted["deals"])
        print(f"  {sub['id'][:8]}  {venue['name']}  +{len(extracted['deals'])} deal(s)")

    if not added and not updated:
        print("nothing new to fold in")
        return 0

    # Never truncate before the new bytes exist.
    tmp = PHOTO_JSON + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, PHOTO_JSON)
    print(f"\n{added} new + {updated} updated deal(s) written to data/deals_photo.json")
    print("Now: python ingest/build_bundles.py, then commit and push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
