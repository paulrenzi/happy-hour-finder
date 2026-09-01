#!/usr/bin/env python3
"""Every venue we publish a happy hour for and cannot say ONE price on.

    python ingest/report_holes.py                  # ranked by class, then venue
    python ingest/report_holes.py --class chrome   # just one class, with URLs

Paul found North Italia, The Capital Grille and Sullivan's by opening the sites
himself and telling us what we had missed. That works and it does not scale: the
next zone is another few hundred venues, and nobody can browse them. The misses
were not invisible, though -- every one of them had the same machine-readable
signature in our own data. We published a WINDOW and ZERO ITEMS. A card that
says 'happy hour 4-6' and cannot name a single thing you can buy is the shape of
a scraper failure, and we already had 107 of them on file.

So the scraper reports its own holes, ranked by CLASS. The class is the unit of
work: 'capital-hours' was one line and fixed two venues, one FRC adapter fixed
North Italia and covers its sibling brands. Reading the list venue by venue is
the thing we are trying to stop doing.

This reads what is already on disk. It fetches nothing and decides nothing.
"""

import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ingest"))

import extract_deals as ex  # noqa: E402

HITS = os.path.join(REPO, "data", "crawl_hits.json")
DEALS = os.path.join(REPO, "data", "deals_extracted.json")

MONEY = re.compile(r"\$\s?\d")
# A quote that is the row of menu TAB LABELS, not menu. This is what North
# Italia handed back for a page whose entire happy-hour menu was in the HTML the
# whole time: we read the page chrome and stopped. Three or more menu-section
# words in a row, no price, no schedule.
TAB_WORDS = ("lunch", "dinner", "brunch", "dessert", "kids", "happy hour",
             "drinks", "menu", "catering", "wine", "cocktails", "specials")


def is_chrome(quote):
    low = quote.lower()
    if MONEY.search(quote):
        return False
    return sum(1 for w in TAB_WORDS if w in low) >= 3


def classify(venue_hits, pages, images=()):
    """Why this venue has a window and no items -- the class of work, not the fix.

    Ordered most-specific first. Each name says what to go and look at, and a
    class holding many venues is worth an adapter; a class holding one is worth
    a look and probably not a code change.
    """
    ok_pages = [p for p in pages if p.get("result", "").startswith("ok")]
    if pages and not ok_pages:
        if any("robots" in p.get("result", "") for p in pages):
            return "robots-refused"
        return "fetch-failed"
    quotes = [h["quote"] for h in venue_hits]
    # The words are pixels. No parser reaches these and saying 'no price
    # published' about them is wrong twice: the venue DID publish the menu, and
    # the work is a vision pass, not a regex.
    if images and not any(MONEY.search(q) for q in quotes):
        return "menu-is-a-picture"
    if any(is_chrome(q) for q in quotes):
        return "chrome-only"
    priced = [q for q in quotes if MONEY.search(q)]
    if priced:
        return "priced-but-unreadable"
    if any(re.search(r"\.pdf", p.get("url", ""), re.I) for p in ok_pages):
        return "menu-is-a-document"
    if len(quotes) <= 2:
        return "nothing-but-the-hours"
    return "no-price-published"


# What a person should do with each class, so the report is a queue and not a
# tally. 'One venue' classes are not worth code; a class with a dozen venues in
# it is the next adapter.
ADVICE = {
    "robots-refused": "the site refuses our crawler -- nothing to fix in the parser",
    "fetch-failed": "every fetch errored; check the UA and the redirect chain",
    "chrome-only": "we read the nav and stopped -- the menu is elsewhere in the page "
                   "or behind a tab. This was North Italia.",
    "priced-but-unreadable": "prices ARE in the quotes and the extractor refused them "
                             "-- a label pattern or a category, one venue at a time",
    "menu-is-a-document": "the menu is a PDF we reached but read nothing out of",
    "nothing-but-the-hours": "the hours quote is all we ever got -- likely a JS menu "
                             "or an API. This was The Capital Grille.",
    "no-price-published": "several quotes, no dollar sign anywhere -- the venue may "
                          "genuinely not publish prices. AUDIT THIS CLASS BEFORE "
                          "SIZING IT: 24 of 36 turned out to have prices in the raw "
                          "HTML (2026-09-01)",
    "menu-is-a-picture": "the venue posted its happy hour as an IMAGE -- the words are "
                         "pixels and no parser reaches them. This is the vision pass.",
}

# Why a venue publishes a window and names no item, when somebody has looked and
# recorded the answer. Same file the build's ratchet reads: a venue in here is
# accounted for and is reported below the line, never as a miss.
VERDICTS = os.path.join(REPO, "data", "menu_verdicts.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--class", dest="klass", help="show only this class, with URLs")
    ap.add_argument("--limit", type=int, default=12, help="venues listed per class")
    args = ap.parse_args()

    hits = json.load(open(HITS, encoding="utf-8"))
    deals = json.load(open(DEALS, encoding="utf-8"))
    by_lid = {v["lid"]: v for v in deals["venues"] if "lid" in v}

    verdicts = {}
    if os.path.exists(VERDICTS):
        verdicts = json.load(open(VERDICTS, encoding="utf-8")).get("venues", {})
    holes, published, accounted = {}, 0, []
    for lid, v in by_lid.items():
        for deal in v["deals"]:
            published += 1
            if deal.get("items"):
                continue
            row = hits.get(lid) or {}
            if str(lid) in verdicts:
                accounted.append((v["name"], verdicts[str(lid)].get("verdict", "?")))
                continue
            k = classify(row.get("hits") or [], row.get("pages") or [],
                         row.get("menu_images") or ())
            holes.setdefault(k, []).append((v["name"], v.get("website") or ""))

    total = sum(len(x) for x in holes.values())
    print(f"{total} of {published} published windows name NO item at all"
          f" ({len(accounted)} more are accounted for below)\n")
    for k, rows in sorted(holes.items(), key=lambda kv: -len(kv[1])):
        if args.klass and k != args.klass:
            continue
        print(f"== {k}  ({len(rows)} venue(s))")
        print(f"   {ADVICE.get(k, '')}")
        shown = rows if args.klass else rows[: args.limit]
        for name, site in sorted(shown):
            print(f"     {name[:42]:44s} {site[:60]}")
        if len(rows) > len(shown):
            print(f"     ... and {len(rows) - len(shown)} more "
                  f"(--class {k} for all of them)")
        print()

    if accounted and not args.klass:
        print(f"== accounted for  ({len(accounted)} venue(s))")
        print("   somebody looked and recorded why -- data/menu_verdicts.json")
        for name, why in sorted(accounted)[: args.limit]:
            print(f"     {name[:42]:44s} {why}")
        print()


if __name__ == "__main__":
    main()
