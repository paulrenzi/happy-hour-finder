#!/usr/bin/env python3
"""Turn a roundup's paragraphs into deals, in the roundup tier.

    python ingest/extract_roundups.py             # write data/deals_roundup.json
    python ingest/extract_roundups.py --show      # and print what was kept / refused

Reads data/roundup_hits.json (ingest/crawl_roundups.py) and writes
data/deals_roundup.json in the deals_seed shape, which build_bundles.py merges
at the LOWEST rank: a roundup never outranks the venue's own page, a photo, or
a person. Every deal it writes carries source.kind "roundup", the outlet and
the article's publish date, and is capped at "unconfirmed" -- validate_pa.py
refuses it otherwise.

Why this lane exists at all (2026-09-02): ten West Chester venues that crawled
fine and published nothing were looked at by hand. None had the deal on their
own site in any form we could read. One County Lines article had 27 of them.

THE ONE INFERENCE THIS FILE MAKES, written down: a happy-hour roundup writes
its clocks without a meridiem -- "4 to 6", "3 to 5:30" -- and the extractor
refuses those on a venue page, correctly, because "4 - 6" there could be a
lunch or a kids' menu. Inside an article whose subject is happy hours, a bare
1-11 to 1-11 range is a PM range. pmify() adds the meridiem; windows_from()
then reads it with the same grammar, unmodified, that reads a venue's page.
"""

import argparse
import datetime
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_deals import HH_RE, dedupe, items_in, slug, windows_from  # noqa: E402
from validate_pa import MAX_HOURS_PER_DAY, window_hours  # noqa: E402
from validate_pa import state_of, validate_deal  # noqa: E402

HITS = os.path.join(REPO, "data", "roundup_hits.json")
SITES = os.path.join(REPO, "data", "venue_sites.json")
OUT = os.path.join(REPO, "data", "deals_roundup.json")

# "4 to 6", "3 to 5:30", "4-6". Never after a $ or a digit (a price, a date),
# never before a unit or a percent, both ends on the 1-11 clock.
BARE_RANGE_RE = re.compile(
    r"(?<![$\d:])\b(1[01]|[1-9])(?::([0-5]\d))?\s*(?:to|-|–|—|until|till)\s*"
    r"(1[01]|[1-9])(?::([0-5]\d))?\b"
    # ':' and a digit are in the forbidden-follow set because the minutes on
    # the END of the range are OPTIONAL: without them, '4:30 to 6:30 PM'
    # matched as '4:30 to 6' and pmify rewrote it to '4:30 pm - 6 pm:30 PM',
    # shipping Penn Taproom a 4:30-6:00 window off a quote that says 6:30. A
    # range that already carries its own meridiem needs no help from this
    # lane -- windows_from reads it unchanged.
    r"(?!\s*(?::|\d|am|pm|a\.m|p\.m|[ap]\b|%|off|oz|years?|days?|people|guests|\$))",
    re.I)

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def pmify(text):
    """A bare clock range in a happy-hour article is a PM range."""
    def sub(m):
        a = m.group(1) + (":" + m.group(2) if m.group(2) else "")
        b = m.group(3) + (":" + m.group(4) if m.group(4) else "")
        return f"{a} pm - {b} pm"
    return BARE_RANGE_RE.sub(sub, text)


def sentences(paragraph):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", paragraph) if s.strip()]


def windows_in_paragraph(paragraph):
    """Windows from the sentence(s) that say 'happy hour' and carry a clock.

    Sentence by sentence, so the paragraph's other clocks (the bar's opening
    time, the trivia night) do not pair with the happy hour's days. The whole
    paragraph is tried last, for the article that puts the days in one
    sentence and the clock in the next.
    """
    out = []
    for s in sentences(paragraph):
        if not (HH_RE.search(s) or out):
            continue
        # Clause by clause, too: 'Happy Hour is Tuesday to Friday, 4 to 6,
        # and can be paired with DAILY drink specials' read as every day,
        # because 'daily' in the tail is a day word. Each clause states its
        # own days; the union is the schedule.
        for clause in re.split(r",\s+and\s+|;\s+", s):
            out += windows_from(pmify(clause))
    if not out:
        out = windows_from(pmify(paragraph))
    return dedupe(out) if out else []


# A label cut from prose that reads as a CLAUSE is not a thing you can buy:
# '$5 and the apps are half-off' gave the extractor 'and the apps are
# half-off' at $5, which is the margaritas' price on the apps. A wrong item
# is worse than a missing one, so a label that starts on a conjunction or
# carries a verb is refused whole.
CLAUSE_RE = re.compile(r"^(?:and|or|on|the|a|its|their|all)\b|\b(?:are|is|for|with|at|during)\b", re.I)


def tidy_items(items):
    """Trim the conjunction the extractor stopped on ('wine and' -> 'wine');
    refuse a label that is a clause rather than a noun."""
    keep = []
    for it in items:
        label = re.sub(r"\s+(?:and|or|&|with|plus)$", "", it["label"].strip(" ,-"))
        # The item regexes cap a label at 29 characters, so a conjoined pair
        # arrives CUT: 'half-price drafts and discounted appetizers' gave
        # 'drafts and discounted appetiz', a word that is not a word. The
        # first noun is the one the price is on and the one the card has room
        # for -- the same fallback the priced path already applies.
        label = re.split(r"\s+(?:and|or|&|plus)\s+", label)[0].strip(" ,-")
        # 'wine and cocktails and everyb' is the extractor's 30-char cut of a
        # sentence, not a noun: more than four words is prose.
        if len(label) < 3 or len(label.split()) > 4 or CLAUSE_RE.search(label):
            continue
        keep.append(dict(it, label=label))
    return keep


def month_label(iso):
    y, m, _ = iso.split("-")
    return f"{MONTHS[int(m) - 1]} {y}"


def deals_for(venue_hit, article, crawled_at):
    """One venue's paragraph(s) -> [deal] (zero or one).

    🔑 THE CONTAINMENT IS ON THE ENTRY, NOT ON THE LINE. It used to be on the
    line: a quote had to say "happy hour" itself before its clock could be
    read. Delaware Today's "A Local's Guide to Happy Hours in Wilmington"
    breaks that shape and it is a common one -- the venue's entry is three
    lines, and they divide the job:

        Catherine Rooney's
        Monday-Friday, 3:30-6:30 p.m.                    <- the CLOCK
        "...$1 off all drafts during its happy hour."    <- the WORDS
        1616 Delaware Avenue, Wilmington                 <- the door

    No single line has both, so ten Wilmington bars with exact published
    clocks were refused, and the article read as naming nothing. The venue's
    entry is the unit the article vouched for: if ANY of its lines says happy
    hour, its clock line is a happy-hour clock.

    🛑 That widens what a clock may mean, so the opening-hours guard comes
    with it: an entry whose every window is longer than any happy hour is the
    bar's opening times, and is refused. That check is a HEURISTIC, not a
    statute, so it applies in Delaware too -- where the law sets no cap and
    would not have caught it.
    """
    quotes = venue_hit["quotes"]
    contained = any(HH_RE.search(q) for q in quotes)
    for quote in quotes:
        if not contained:
            break
        windows = windows_in_paragraph(quote)
        if not windows or all(window_hours(w) > MAX_HOURS_PER_DAY for w in windows):
            continue
        deal = {
            "type": "happy_hour",
            "windows": windows,
            # Items come from every line of the entry, for the same reason:
            # the prices are in the prose and the clock is on its own line.
            "items": tidy_items([i for q in quotes for i in items_in(q)]),
            "confidence": "unconfirmed",
            # The day WE read the article and it still said this. The article's
            # own date is on the source, and on the card.
            "last_verified_at": crawled_at,
            "verified_by": "roundup_extract",
            "source": {
                "kind": "roundup",
                "url": article["url"],
                "outlet": article["outlet"],
                "published": article["published"],
                "quote": quote,
                # The whole entry, so tests/window_quote_check.py can
                # ask an honest question of a card whose clock and
                # whose words are on different lines.
                "quotes": quotes,
                "note": f"{article['outlet']}, {month_label(article['published'])}",
            },
        }
        if validate_deal(deal, state_of(venue_hit.get("address"))):
            continue
        return [deal]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not os.path.exists(HITS):
        print(f"no {os.path.relpath(HITS, REPO)} -- run ingest/crawl_roundups.py --write")
        return
    hits = json.load(open(HITS, encoding="utf-8"))
    sites = json.load(open(SITES, encoding="utf-8"))
    crawled_at = hits.get("built_at") or datetime.date.today().isoformat()

    venues, kept, refused = {}, 0, []
    # Newest article first, so where two pieces describe one bar the more
    # recent one is the deal that ships.
    articles = sorted((a for a in hits["articles"] if not a.get("dropped")),
                      key=lambda a: a["published"], reverse=True)
    for article in articles:
        for vh in article["venues"]:
            if vh["lid"] in venues:
                continue
            deals = deals_for(vh, article, crawled_at)
            if not deals:
                refused.append((vh["name"], article["published"], vh["quotes"][0][:110]))
                continue
            site = sites.get(vh["lid"], {})
            name = site.get("osm_name") or vh["name"]
            venues[vh["lid"]] = {
                "id": slug(name, vh["address"]),
                "lid": vh["lid"],
                "name": name,
                "plcb_name": site.get("name") or vh.get("plcb_name") or vh["name"],
                "address": vh["address"],
                "zone_id": vh.get("zone_id"),
                "license_type": "",
                "website": site.get("website") or "",
                "deals": deals,
            }
            kept += 1
            if args.show:
                d = deals[0]
                print(f"  KEEP  {name:<32} {article['published']}  "
                      f"{len(d['windows'])} windows  {len(d['items'])} items")

    if args.show:
        for name, published, q in refused:
            print(f"  REFUSE {name:<31} {published}  {q}")
    out = {
        "_comment": "Deals read off dated local roundups (ingest/extract_roundups.py). "
                    "The outlet speaking, not the bar: own tier, outlet + month on "
                    "the card, capped at unconfirmed, never outranks the venue's page.",
        "as_of": crawled_at,
        "venues": list(venues.values()),
    }
    with open(OUT + ".new", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    os.replace(OUT + ".new", OUT)
    print(f"{kept} venues with a roundup deal, {len(refused)} mentions refused "
          f"-> {os.path.relpath(OUT, REPO)}")


if __name__ == "__main__":
    main()
