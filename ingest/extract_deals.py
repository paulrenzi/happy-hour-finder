#!/usr/bin/env python3
"""Turn the crawler's quoted lines into deals, or refuse to.

    python ingest/extract_deals.py                 # write data/deals_extracted.json
    python ingest/extract_deals.py --show 30       # print what was kept
    python ingest/extract_deals.py --rejects 30    # print what was refused, and why

Reads data/crawl_hits.json (quotes, never deals -- see ingest/crawl_sites.py) and
writes data/deals_extracted.json in the same shape as the hand-verified
data/deals_seed.json. The two stay separate files on purpose: the seed was read
off a page by a person, this was read by a regex, and merging them would lose
the only thing that distinguishes them.

The bar for keeping a quote is deliberately high, because rule 2 is that we never
render a claim the source didn't make:

  * a day specification AND a time window, both present in the same quote --
    'Happy Hour' over a picture of a bar is not an answer to 'can I go now?'
  * an unambiguous meridiem. '4 - 6' is 4pm-6pm to a human reading a bar's site
    and 4am-6am to a parser, so it is dropped rather than guessed.
  * no hedge in the quote. A chain that says its times 'vary by location' has
    published nothing about THIS address, and a visitor review that mentions a
    happy hour is not the venue speaking.
  * it survives ingest/validate_pa.py unchanged. The extractor runs the same
    validators the bundle build does, so an over-long window fails here where
    the quote is still attached, instead of silently vanishing two steps later.

Every kept deal carries the sentence it came from in `source.quote`, so any
claim on the site can be read back against the text that produced it.
"""

import argparse
import collections
import datetime
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validate_pa import validate_deal  # noqa: E402

HITS = os.path.join(REPO, "data", "crawl_hits.json")
SITES = os.path.join(REPO, "data", "venue_sites.json")
OUT = os.path.join(REPO, "data", "deals_extracted.json")
COORDS = os.path.join(REPO, "data", "venue_coords.json")

DOW = {"mon": 1, "monday": 1, "tue": 2, "tues": 2, "tuesday": 2, "wed": 3,
       "weds": 3, "wednesday": 3, "thu": 4, "thur": 4, "thurs": 4,
       "thursday": 4, "fri": 5, "friday": 5, "sat": 6, "saturday": 6,
       "sun": 7, "sunday": 7}
DAY_RE = "|".join(sorted(DOW, key=len, reverse=True))
DASH = r"(?:-|–|—|to|thru|through|till|til|until)"

RANGE_RE = re.compile(rf"\b({DAY_RE})\s*(?:s)?\s*{DASH}\s*({DAY_RE})\b", re.I)
SINGLE_RE = re.compile(rf"\b({DAY_RE})\b", re.I)
EVERYDAY_RE = re.compile(r"\b(?:daily|every ?day|all week|7 days a week|seven days)\b", re.I)
WEEKDAY_RE = re.compile(r"\bweekdays?\b", re.I)
WEEKEND_RE = re.compile(r"\bweekends?\b", re.I)

# '4p - 6p' is how a bar writes it about as often as '4pm - 6pm', and requiring
# the full 'pm' meant Pepperoncini published its window in plain text -- the
# line reads 'mon - fri' then '4p - 6p' -- and was dropped for stating no
# schedule. The bare letter must still end on a word boundary, so 'buy 4 - 6
# pizzas' is not a window: the 'p' there is followed by an 'i'.
MERIDIEM = r"am|pm|a\.m\.|p\.m\.|[ap]\b"
TIME_RE = re.compile(
    rf"\b(\d{{1,2}})(?::(\d{{2}}))?\s*({MERIDIEM})?\s*"
    rf"{DASH}\s*(\d{{1,2}})(?::(\d{{2}}))?\s*({MERIDIEM})",
    re.I)

# A quote that hedges, advertises a bookable event, or is somebody's review has
# not published this venue's hours, however many times it says 'happy hour'.
HEDGE_RE = re.compile(
    r"vary by location|varies by location|contact your local|check with your|"
    r"only valid at|at participating|participating locations|coming soon|"
    r"pre.?book|book your|private events?|reserve your|"
    r"\bi (?:have|had|was|went|love|found)\b|\bwe went\b|my (?:new|favorite)\b",
    re.I)

PRICE_RE = re.compile(r"\$(\d{1,3}(?:\.\d\d)?)\s*([A-Za-z][\w\s&'-]{1,28})")
HALF_RE = re.compile(r"half.?price(?:d)?\s+([A-Za-z][\w\s&'-]{1,28})", re.I)

# The noun a price is attached to decides the category; anything unrecognised is
# not guessed into 'food', it is left out of the item list entirely.
NOUNS = [
    ("draft", r"draft|drafts|draught|pint|pints|beer|beers|lager|ipa|brew"),
    ("bottle_can", r"bottle|bottles|can|cans"),
    ("wine", r"wine|wines|glass of wine|prosecco|sangria|rose"),
    ("well", r"well drink|well drinks|wells|rail"),
    ("cocktail", r"cocktail|cocktails|martini|martinis|margarita|margaritas|"
                 r"mule|spritz|sangrias|highball"),
    ("shot", r"shot|shots"),
    ("food", r"app|apps|appetizer|appetizers|bite|bites|wing|wings|slice|"
             r"pizza|taco|tacos|oyster|oysters|burger|burgers|snack|snacks|"
             r"small plate|small plates|nacho|nachos|fries|pretzel"),
]


def days_in(text):
    """The set of weekday numbers a fragment names, 1=Mon..7=Sun."""
    if EVERYDAY_RE.search(text):
        return set(range(1, 8))
    out = set()
    if WEEKDAY_RE.search(text):
        out |= {1, 2, 3, 4, 5}
    if WEEKEND_RE.search(text):
        out |= {6, 7}
    consumed = 0
    for m in RANGE_RE.finditer(text):
        a, b = DOW[m.group(1).lower()], DOW[m.group(2).lower()]
        # Ranges wrap: a bar's 'Sunday - Friday' is six days, not a typo.
        out |= {(a - 1 + i) % 7 + 1 for i in range((b - a) % 7 + 1)}
        consumed += 1
    if not consumed:
        out |= {DOW[m.group(1).lower()] for m in SINGLE_RE.finditer(text)}
    return out


def window_in(text):
    """('16:00', '18:00') for the first unambiguous time range, else None.

    The end's am/pm is required and the start inherits it when the start has
    none, which is how '4 - 6 pm' is written on every chalkboard in the state.
    An inherited meridiem that would put the end before the start means the
    window crosses noon ('11 - 2 pm'), so the start is morning.
    """
    m = TIME_RE.search(text)
    if not m:
        return None
    sh, sm, smer, eh, em, emer = m.groups()
    sh, eh = int(sh), int(eh)
    if not 1 <= sh <= 12 or not 1 <= eh <= 12:
        return None
    # 'p' and 'a' are the same claim as 'pm' and 'am'; h24 below compares the
    # whole string, so a bare letter left unexpanded would read as morning and
    # silently turn a 4p-6p happy hour into 04:00.
    def mer(x):
        x = x.replace(".", "").lower()
        return x + "m" if x in ("a", "p") else x

    emer = mer(emer)
    smer = mer(smer) if smer else None

    def h24(h, mer):
        if mer == "pm":
            return h % 12 + 12
        return 0 if h == 12 else h

    end = h24(eh, emer) * 60 + int(em or 0)
    if smer:
        start = h24(sh, smer) * 60 + int(sm or 0)
    else:
        start = h24(sh, emer) * 60 + int(sm or 0)
        if start >= end:
            start = h24(sh, "am" if emer == "pm" else "pm") * 60 + int(sm or 0)
    if end == 0:
        end = 24 * 60          # a window ending 'at 12am' ends at midnight
    if not 0 <= start < end <= 24 * 60:
        return None
    return "%02d:%02d" % divmod(start, 60), "%02d:%02d" % divmod(end, 60)


def category_of(label):
    low = label.lower()
    for cat, pat in NOUNS:
        if re.search(rf"\b(?:{pat})\b", low):
            return cat
    return None


def items_in(text):
    out, seen = [], set()
    for m in PRICE_RE.finditer(text):
        label = re.split(r"\s+(?:and|or|&)\s+", m.group(2).strip())[0].strip(" -'")
        cat = category_of(label)
        if cat and label.lower() not in seen:
            seen.add(label.lower())
            out.append({"category": cat, "label": label, "price_usd": float(m.group(1))})
    for m in HALF_RE.finditer(text):
        label = m.group(1).strip(" -'")
        cat = category_of(label)
        if cat and label.lower() not in seen:
            seen.add(label.lower())
            out.append({"category": cat, "label": label, "discount_pct": 50})
    return out[:6]


# A second schedule starting inside one segment: '... 4-6pm & Sunday-Thursday
# 8:30-10pm', 'Tue-Fri 4-7pm | Saturday & Sunday 3-6pm'. The separator has to be
# followed by a day name, so 'Monday & Friday 4-6pm' -- one schedule naming two
# days -- is left alone.
CLAUSE_SPLIT_RE = re.compile(
    r"\s*(?:&|\band\b|\||·|•|,)\s*"
    r"(?=(?:late\s+night\s+)?(?:happy\s+hour\s+)?"
    r"(?:mon|tues?|wed|thur?s?|fri|sat|sun)[a-z]*\b)",
    re.I,
)


def clauses(segment):
    """A segment split so that each piece states at most one time range.

    'Monday-Friday 4-6 pm and Sunday-Thursday 10pm-12am' is TWO schedules in one
    line. Read as one, days_in() unions all five weekdays with Sun-Thu and
    window_in() takes only the FIRST range -- publishing Sunday 4-6pm at a bar
    whose Sunday happy hour starts at ten. That was 22 of 170 published venues.

    Returns None when the split does not resolve the segment into pieces of one
    range each, because at that point which days go with which time is a guess,
    and a card on the wrong day still looks like a correct card.
    """
    if len(TIME_RE.findall(segment)) <= 1:
        return [segment]
    parts = CLAUSE_SPLIT_RE.split(segment)
    if len(parts) < 2 or any(len(TIME_RE.findall(p)) > 1 for p in parts):
        return None
    if any(not one_sided(p) for p in parts):
        return None
    return parts


def one_sided(piece):
    """True when every day this piece names sits on ONE side of its time range.

    'Sunday-Thursday, 5pm-7pm Friday' names days on both sides, and reading it
    forwards gives Sunday-Thursday the 5-7pm that belongs to Friday -- while
    Friday, already consumed as a day, silently gets nothing. Days before the
    range ('Mon-Fri 4-6pm') or after it ('4-6pm | Friday') are both unambiguous;
    days on both sides are two schedules sharing one line.
    """
    m = TIME_RE.search(piece)
    if not m:
        return True
    return not (days_in(piece[: m.start()]) and days_in(piece[m.end():]))


def windows_from(quote):
    """[{dow,start,end}] for one quote, or [] if it does not state a schedule.

    A quote arrives from the crawler as ' / '-joined lines, and a happy-hour
    block routinely puts the heading, the days and the times on three separate
    lines -- so days seen in an earlier segment carry forward to a later segment
    that holds only a time.
    """
    if HEDGE_RE.search(quote):
        return []
    pending, out = set(), []
    for seg in re.split(r"\s/\s|;", quote):
        pieces = clauses(seg)
        if pieces is None:
            # Two schedules we cannot separate. Nothing after this can be
            # trusted to pair with days from before it either, so the carry
            # forward is dropped rather than applied to the wrong times.
            pending = set()
            continue
        for piece in pieces:
            here = days_in(piece)
            if here:
                pending = here
            win = window_in(piece)
            if win and pending:
                out += [{"dow": d, "start": win[0], "end": win[1]} for d in sorted(pending)]
                pending = set()
    if out:
        return out
    # An event listing writes the days last ('Happy Hour / 4:30 PM - 6:30 PM /
    # Friday'), which reading forwards can never pair up. Falling back to the
    # whole quote is only safe while there is exactly one time range in it --
    # otherwise the pairing would be a guess about which days went with which.
    if len(quote) <= 200 and len(TIME_RE.findall(quote)) == 1:
        win, ds = window_in(quote), days_in(quote)
        if win and ds:
            return [{"dow": d, "start": win[0], "end": win[1]} for d in sorted(ds)]
    return []


def slug(name, address):
    city = ""
    m = re.search(r",\s*(.+?)\s+[A-Z]{2}\s+\d{5}", address or "")
    if m:
        city = m.group(1)
    base = re.sub(r"[^a-z0-9]+", "-", f"{name} {city}".lower()).strip("-")
    return base[:60]


def dedupe(windows):
    """One window per weekday: the longest. Two quotes on one site describe the
    same happy hour twice far more often than they describe two of them."""
    best = {}
    for w in windows:
        cur = best.get(w["dow"])
        span = int(w["end"][:2]) * 60 - int(w["start"][:2]) * 60
        if not cur or span > cur[0]:
            best[w["dow"]] = (span, w)
    return [w for _dow, (_span, w) in sorted(best.items())]


def one_per_osm(hits, sites):
    """[(lid, crawl_hits_entry)] -- one entry per real bar, in a stable order.

    One bar can hold several licences (a restaurant licence and a hotel licence
    at one address are two PLCB rows), and the frontier joined both to the same
    OSM element -- so the OSM id, not the LID, is the venue.
    """
    by_osm, order = {}, []
    for lid, v in sorted(hits.items()):
        key = (sites.get(lid) or {}).get("osm") or lid
        if key not in by_osm:
            by_osm[key] = (lid, v)
            order.append(key)
        elif v["hits"] and not by_osm[key][1]["hits"]:
            by_osm[key] = (lid, v)
    return [by_osm[k] for k in order]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--rejects", type=int, default=0)
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    hits = json.load(open(HITS, encoding="utf-8"))
    sites = json.load(open(SITES, encoding="utf-8"))
    coords = json.load(open(COORDS, encoding="utf-8")) if os.path.exists(COORDS) else {}

    venues, stats, kept, rejects = [], collections.Counter(), [], []
    seen_ids = set()
    for lid, v in one_per_osm(hits, sites):
        if not v["hits"]:
            stats["no quote crawled"] += 1
            continue
        stats["venue had quotes"] += 1
        cands = []
        for h in v["hits"]:
            ws = windows_from(h["quote"])
            if ws:
                cands.append((h, ws))
        if not cands:
            stats["  quote states no schedule"] += 1
            if len(rejects) < args.rejects:
                rejects.append((v["osm_name"] or v["name"], v["hits"][0]["quote"]))
            continue

        # The richest quote names the deal; the rest of the site's quotes only
        # add windows, and their prose is not what gets shown.
        cands.sort(key=lambda c: (len({w["dow"] for w in c[1]}), len(c[0]["quote"])),
                   reverse=True)
        lead = cands[0][0]
        windows = dedupe([w for _, ws in cands for w in ws])
        deal = {
            "type": "happy_hour",
            "windows": windows,
            "items": items_in(" ".join(c[0]["quote"] for c in cands)),
            # A regex read this off a page nobody checked. 'likely' is what a
            # person reading the same page earns; this earns the tier below it.
            "confidence": "unconfirmed",
            "last_verified_at": v["crawled_at"],
            "verified_by": "auto_extract",
            "source": {"kind": "venue_site", "url": lead["url"], "quote": lead["quote"]},
        }
        errs = validate_deal(deal)
        if errs:
            # Windows pooled from several quotes can overrun the statutory cap
            # even when each quote alone is lawful; fall back to the lead quote.
            deal["windows"] = dedupe(cands[0][1])
            errs = validate_deal(deal)
        if errs:
            stats["  REJECTED by the PA validators"] += 1
            if len(rejects) < args.rejects:
                rejects.append((v["osm_name"] or v["name"], f"{errs[0]} :: {lead['quote'][:90]}"))
            continue

        vid = slug(v["osm_name"] or v["name"], v["address"])
        if vid in seen_ids:
            vid = f"{vid}-{lid}"
        seen_ids.add(vid)
        stats["  KEPT"] += 1
        kept.append((vid, deal))
        venues.append({
            "id": vid,
            # The LID this deal was crawled for. data/venue_base.json is keyed on
            # it, so this is what joins a deal to the venue card it belongs on --
            # without it the merge falls back to matching addresses, which is how
            # a bar ends up on the board twice.
            "lid": lid,
            "name": v["osm_name"] or v["name"],
            "plcb_name": v["name"],
            "address": v["address"],
            "zone_id": v["zone_id"],
            "license_type": "",
            "website": v["website"],
            "deals": [deal],
        })
        # OSM already placed this venue when the frontier was built, so the
        # geocoder has nothing to look up -- carry the coordinate across.
        site = sites.get(lid) or {}
        # A venue id is name + city, so two Santucci's in Philadelphia collide and
        # seen_ids decides which one holds the bare slug. That can change between
        # runs -- and then 'already cached' is a coordinate for the OTHER branch,
        # several miles away, with nothing to show it moved. A cache entry this
        # step owns is refreshed when the address it was looked up for is no
        # longer this venue's; a hand-geocoded entry is still never touched.
        held = coords.get(vid)
        stale = (held or {}).get("matched_by") == "osm_site" \
            and held.get("queried") != v["address"]
        if (vid not in coords or stale) and site.get("lat"):
            coords[vid] = {"lat": site["lat"], "lng": site["lng"], "precision": "place",
                           "matched_by": "osm_site", "osm": site.get("osm"),
                           "queried": v["address"], "resolved": site.get("osm_name") or ""}

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"_comment": "Machine-extracted from data/crawl_hits.json by "
                               "ingest/extract_deals.py. Every deal carries the quote it "
                               "was read from. Hand-verified deals live in deals_seed.json.",
                   "as_of": datetime.date.today().isoformat(),
                   "venues": venues}, fh, indent=1)
    # A venue id is derived from its name, so a re-extraction after a rename
    # would otherwise leave the old id behind as a coordinate nothing claims.
    live = {v["id"] for v in venues}
    coords = {k: c for k, c in coords.items()
              if c.get("matched_by") != "osm_site" or k in live}
    with open(COORDS, "w", encoding="utf-8") as fh:
        json.dump(coords, fh, indent=1, sort_keys=True)

    print(f"{len(hits)} venues crawled")
    for k, c in stats.most_common():
        print(f"  {c:>5}  {k}")
    print(f"\nwrote {len(venues)} venues -> {OUT}")

    for vid, deal in kept[: args.show]:
        days = ",".join(str(w["dow"]) for w in deal["windows"])
        w = deal["windows"][0]
        print(f"  {vid[:38]:<40} dow {days:<16} {w['start']}-{w['end']}  "
              f"{len(deal['items'])} item(s)")
    for name, why in rejects:
        print(f"  REJECT {name[:26]:<28} {why[:96]}")


if __name__ == "__main__":
    main()
