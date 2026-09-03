"""Turn hand reads into publishable venue rows.

An agent (or a person) opens a venue's own site, reads the happy hour off it,
and writes ONE compact record into data/agent_handread.json:

    {"lid": "DE23baa43531",
     "url": "https://...",
     "read_on": "2026-09-03",
     "quote": "Happy Hour Mon-Fri 4pm-7pm ...",     # the venue's own words
     "days": [1,2,3,4,5],                            # 1=Mon .. 7=Sun
     "start": "16:00", "end": "19:00",
     "items": [{"category": "draft", "label": "Draft beer", "price_usd": 5.0}]}

`items` may be omitted, and then the items already paid for in
data/deals_agent.json for that same licence are used -- that file is where the
agent lane has been depositing verified items that had no window to hang on.

This script joins each record to venue_base.json for the name, address and
zone, and writes data/deals_agent_venues.json in the same shape as
deals_menus.json. build_bundles.py reads it as a full source, so a venue no
crawler ever parsed hours for can still reach the board.

    python ingest/build_agent_venues.py
"""
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ingest"))

from validate_pa import state_of, validate_deal  # noqa: E402

HAND = os.path.join(REPO, "data", "agent_handread.json")
AGENT_ITEMS = os.path.join(REPO, "data", "deals_agent.json")
BASE = os.path.join(REPO, "data", "venue_base.json")
OUT = os.path.join(REPO, "data", "deals_agent_venues.json")


def load(path, default):
    if not os.path.exists(path):
        return default
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, payload):
    tmp = path + ".new"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def main():
    hand = load(HAND, [])
    items_by_lid = load(AGENT_ITEMS, {})
    base = load(BASE, {})

    venues, skipped = [], []
    for rec in hand:
        lid = rec["lid"]
        b = base.get(lid)
        if b is None:
            skipped.append(f"{lid}: not in venue_base.json")
            continue
        items = rec.get("items")
        if items is None:
            items = items_by_lid.get(lid)
        if not items:
            skipped.append(f"{b['name']}: no items, and none banked for {lid}")
            continue
        # `days` + one clock covers almost every venue. `windows` is for the
        # ones whose happy hour starts when they open and so lands on a
        # different clock each day (Brew Works North: "From Open until 6pm").
        windows = rec.get("windows") or [
            {"dow": d, "start": rec["start"], "end": rec["end"]}
            for d in rec["days"]]
        deal = {
            "type": rec.get("type", "happy_hour"),
            "confidence": rec.get("confidence", "likely"),
            "last_verified_at": rec["read_on"],
            "windows": windows,
            "items": items,
            "verified_by": "agent_read",
            "source": {
                "kind": "venue_site",
                "url": rec["url"],
                "quote": rec["quote"],
            },
        }
        if rec.get("clock_quote"):
            deal["source"]["clock_quote"] = rec["clock_quote"]
        if rec.get("heading"):
            deal["source"]["heading"] = rec["heading"]
        if rec.get("fine_print"):
            deal["fine_print"] = rec["fine_print"]
        errs = validate_deal(deal, state_of(b["address"]))
        if errs:
            skipped.append(f"{b['name']}: {errs[0]}")
            continue
        venues.append({
            "id": lid,
            "lid": lid,
            "name": b["name"],
            "plcb_name": b.get("plcb_name") or b["name"],
            "address": b["address"],
            "zone_id": b["zone_id"],
            "website": b.get("website") or rec["url"],
            "deals": [deal],
        })

    write_json(OUT, {
        "_comment": "Venues an agent read BY HAND off their own site -- hours "
                    "and menu together (ingest/build_agent_venues.py). Edit "
                    "data/agent_handread.json, not this file.",
        "as_of": max([r["read_on"] for r in hand], default=""),
        "venues": sorted(venues, key=lambda v: v["id"]),
    })
    n = sum(len(v["deals"][0]["items"]) for v in venues)
    print(f"{len(venues)} venue(s), {n} item(s) -> data/deals_agent_venues.json")
    for line in skipped:
        print(f"  ! skipped {line}")


if __name__ == "__main__":
    main()
