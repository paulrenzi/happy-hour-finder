#!/usr/bin/env python3
"""Where a zone's venues fall out, from licence to card. Reads disk, fetches nothing.

    python ingest/report_funnel.py                 # every zone, worked ones first
    python ingest/report_funnel.py king_of_prussia phoenixville

Paul's question, 2026-09-02: "if I name an area, what percentage of the pages
with happy hour listings will we pull in?" This is how that gets answered in one
command instead of an afternoon, and it exists because the answer was twice
given from memory and was twice wrong.

Read the columns as a chain, because each one is a different kind of work:

  lic      PLCB licensees in the zone. Includes Starbucks, GIANT and caterers --
           a licence class is not the thing it names, so this is never the
           denominator of a recall claim.
  site     we hold a website for it. Below ~50% the zone has not had a discovery
           pass and NOTHING downstream is a measure of the scraper.
  crawl    we tried to fetch it.
  ok       at least one page came back. The gap to `crawl` is robots and errors.
  quote    a page said something about a happy hour.
  card     it is on the board.

The load-bearing ratio is card/quote: what we do with a page that IS about a
happy hour. In KoP that is 86%. Everything to the left of `quote` is reach, and
reach is where the remaining work is.

🛑 `ok` counts a JAVASCRIPT SHELL as a success. crawl_hits.json does not store a
line count, so a page we read in full and a page we could not read at all record
identically as "ok, 0 quote(s)". Until that field exists, a low quote/ok ratio
cannot be read as "these venues have no happy hour".
"""

import collections
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name, where="web/data"):
    return json.load(open(os.path.join(REPO, where, name), encoding="utf-8"))


def main():
    want = set(sys.argv[1:])
    board = load("board-by-lid.json")
    lz = load("lid-zone.json")
    hits = load("crawl_hits.json", "data")
    sites = {}
    for fn in os.listdir(os.path.join(REPO, "web", "data")):
        if fn.startswith("venues-") and fn.endswith(".json"):
            for v in load(fn)["venues"]:
                if v.get("website"):
                    sites[v["lid"]] = 1

    Z = collections.defaultdict(collections.Counter)
    for lid, zone in lz.items():
        d = Z[zone]
        d["lic"] += 1
        # A venue we crawled is a venue whose website we hold: the published
        # zone file only carries the field for venues the base was rebuilt
        # for, and reading it alone reported 30 sites for the 49 KoP venues
        # we had actually fetched.
        d["site"] += lid in sites or lid in hits
        v = hits.get(lid)
        if v:
            d["crawl"] += 1
            d["ok"] += any(p.get("result", "").startswith("ok")
                           for p in v.get("pages") or [])
            d["quote"] += bool(v.get("hits"))
        d["card"] += lid in board

    rows = [(z, d) for z, d in Z.items() if not want or z in want]
    rows.sort(key=lambda r: -r[1]["crawl"])
    print("%-27s %5s %5s %5s %5s %5s %5s   %s" % (
        "zone", "lic", "site", "crawl", "ok", "quote", "card", "card/quote"))
    tot = collections.Counter()
    for z, d in rows:
        tot.update(d)
        pct = "%3.0f%%" % (100.0 * d["card"] / d["quote"]) if d["quote"] else "   -"
        flag = "  <- no discovery pass" if d["lic"] and d["site"] * 2 < d["lic"] else ""
        print("%-27s %5d %5d %5d %5d %5d %5d   %s%s" % (
            z, d["lic"], d["site"], d["crawl"], d["ok"], d["quote"], d["card"],
            pct, flag))
    if len(rows) > 1:
        pct = "%3.0f%%" % (100.0 * tot["card"] / tot["quote"]) if tot["quote"] else "   -"
        print("%-27s %5d %5d %5d %5d %5d %5d   %s" % (
            "ALL", tot["lic"], tot["site"], tot["crawl"], tot["ok"],
            tot["quote"], tot["card"], pct))


if __name__ == "__main__":
    main()
