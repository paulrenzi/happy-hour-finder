"""Venues in a zone whose card is missing something a recrawl could fill.

A venue is NEEDY when it has a website and either no deal at all, or a deal
carrying no items. A venue with a window AND items is left alone: re-fetching
it spends somebody's bandwidth to re-learn what we already hold.

This is the selection half of a scoped run. A full-corpus recrawl + page read
is not affordable at sonnet prices, so a run names its towns and this names the
venues inside them:

    python ingest/needy.py phoenixville wayne_radnor --show --lids run.lids
    python ingest/crawl_sites.py --lids run.lids --recrawl --render
"""
import argparse, json, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def needy(zone):
    # BOTH bundle files. build_bundles splits a zone by whether a venue has a
    # deal at all: zone-<id>.json is the deal-bearing half, venues-<id>.json is
    # the rest. Reading only the latter made the second clause of the rule above
    # -- "a deal carrying no items" -- unreachable by construction: 76 of the
    # corpus's 214 deal-bearing venues carry a window and no item, and not one
    # of them could ever be selected. Found 2026-09-02 on the Ambler blind run,
    # where it hid Fireside Bar and Grill, a venue Google names as having a
    # happy hour.
    rows = []
    for fn in ("zone-%s.json" % zone, "venues-%s.json" % zone):
        p = os.path.join(REPO, "web", "data", fn)
        if os.path.exists(p):
            rows += json.load(open(p, encoding="utf-8"))["venues"]
    out = []
    for v in rows:
        if not v.get("website"):
            continue
        deals = v.get("deals") or []
        if deals and any(d.get("items") for d in deals):
            continue
        out.append((v["lid"], v["name"], "no deal" if not deals else "no items"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("zones", nargs="+")
    ap.add_argument("--show", action="store_true", help="print every venue")
    ap.add_argument("--lids", help="write the licence ids to this file")
    a = ap.parse_args()

    total, lids = 0, []
    for z in a.zones:
        rows = needy(z)
        total += len(rows)
        lids += [r[0] for r in rows]
        print("%-28s %3d needy" % (z, len(rows)))
        if a.show:
            for lid, name, why in rows:
                print("   %-8s %-40s %s" % (lid, name[:40], why))
    print("-- %d venues" % total)

    if a.lids:
        with open(a.lids, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lids) + "\n")
        print("wrote", a.lids)


if __name__ == "__main__":
    main()
