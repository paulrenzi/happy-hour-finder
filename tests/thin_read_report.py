#!/usr/bin/env python3
"""Regenerate data/RESCRAPE-QUEUE.json: every live deal with under 5 items.

Paul's rule, 2026-09-03: a live happy-hour deal with fewer than 5 items is not
a closed venue, it's a re-scrape candidate. He pointed at two live examples
directly -- Limoncello (west_chester, one item) and Liberty Union Bar and
Grill (exton_downingtown, one item) -- both plainly under-read.

Not a pass/fail gate (a genuinely 1-3 item happy hour is real at some venues),
so this is a report, not a test that fails the suite. Run it at the start of
any hand-read session to see the current backlog:

    python tests/thin_read_report.py
"""
import glob
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(REPO, "data", "RESCRAPE-QUEUE.json")


def build():
    rows = []
    for f in sorted(glob.glob(os.path.join(REPO, "web", "data", "zone-*.json"))):
        zone = os.path.basename(f).split("zone-")[1].split(".json")[0]
        d = json.load(open(f, encoding="utf-8"))
        for v in d["venues"]:
            for deal in v.get("deals", []):
                n = len(deal.get("items", []))
                if 0 < n < 5:
                    rows.append({
                        "zone": zone,
                        "name": v["name"],
                        "lid": v.get("lid"),
                        "verified_by": deal.get("verified_by"),
                        "item_count": n,
                        "url": deal.get("source", {}).get("url"),
                        "status": "NEEDS_RESCRAPE",
                    })
    rows.sort(key=lambda r: (r["zone"], r["name"]))
    return rows


def main():
    rows = build()
    out = {
        "rule": "Paul, 2026-09-03: any live deal with under 5 happy-hour items needs a re-scrape.",
        "generated": __import__("time").strftime("%Y-%m-%d"),
        "count": len(rows),
        "venues": rows,
    }
    with open(QUEUE, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"{len(rows)} deals under 5 items -> {QUEUE}")
    by_zone = {}
    for r in rows:
        by_zone.setdefault(r["zone"], 0)
        by_zone[r["zone"]] += 1
    for zone, n in sorted(by_zone.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {zone}")


if __name__ == "__main__":
    main()
