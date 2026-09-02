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


# The chain a website walks before this selector can see it. Every link is a
# separate command, and skipping ANY of them shrinks the list with no error.
STALE_CHAIN = (
    ("data/venue_sites.json", "data/venue_base.json",
     "python ingest/build_venue_base.py && python ingest/build_bundles.py"),
    ("data/venue_base.json", "web/data/index.json",
     "python ingest/build_bundles.py"),
)


def newest_bundle_mtime():
    """The built board's age, from the index the build always rewrites."""
    p = os.path.join(REPO, "web", "data", "index.json")
    return os.path.getmtime(p) if os.path.exists(p) else None


def warn_if_base_is_stale():
    """A website discovered but never carried onto the board is invisible here.

    needy() reads the BUILT bundles, so the website has to walk the whole
    chain: venue_sites.json -> venue_base.json -> web/data/. On Doylestown
    (2026-09-02) a missing base rebuild named 5 venues where there were 33,
    which is the scope -- and the cost -- of every scoped run that follows.

    🔑 The first version of this guard compared only the first pair, and on
    Media the next day it stayed SILENT while doing exactly the same damage: a
    base rebuilt and bundles that were not named 9 venues where there were 26.
    A guard that watches one link of a chain is not a guard on the chain.
    """
    stale = False
    for newer, older, fix in STALE_CHAIN:
        a, b = os.path.join(REPO, *newer.split("/")), os.path.join(REPO, *older.split("/"))
        if not (os.path.exists(a) and os.path.exists(b)):
            continue
        if os.path.getmtime(a) > os.path.getmtime(b):
            stale = True
            print(f"! {newer} is NEWER than {older} --\n"
                  "  websites discovered since then are INVISIBLE to this\n"
                  "  selection, so the count below is too low. Run:\n"
                  f"      {fix}\n", file=sys.stderr)
    return stale


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

    warn_if_base_is_stale()
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
