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
    p = os.path.join(REPO, "web", "data", "venues-%s.json" % zone)
    out = []
    for v in json.load(open(p, encoding="utf-8"))["venues"]:
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
