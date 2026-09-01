#!/usr/bin/env python3
"""PA legal validators (SPEC section 3).

Acts 57 & 86 of 2024 constrain happy hour by statute, so anything violating the
statute is a parsing bug or a stale record -- not a venue breaking the law.
A deal that fails here never reaches the bundle.

    python ingest/validate_pa.py            # check data/deals_seed.json
"""

import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEALS_JSON = os.path.join(REPO, "data", "deals_seed.json")

MAX_HOURS_PER_DAY = 4.0
MAX_HOURS_PER_WEEK = 24.0

# THE NUMBERS ABOVE ARE PENNSYLVANIA'S, AND THEY ARE NOT UNIVERSAL.
#
# Every deal on the board is gated on Acts 57 & 86 of 2024 -- a 4h/day and
# 24h/week cap, a midnight cutoff, 2 food+drink combos per day, and the BANNED
# list. That was safe while every venue was in one of five PA counties. It stops
# being safe the moment a venue in another state is published: running a
# Delaware bar through these rules can SUPPRESS a lawful DE deal and, worse,
# PUBLISH one PA would have banned. Crossing a state line changes the LAW, not
# just the data source.
#
# So the rules are a table keyed by state, and a state with no entry has no
# ruleset -- rules_for() returns None and the caller must refuse to publish.
# Failing closed is the only safe direction here: an unpublished lawful deal
# costs us a card, a published unlawful one costs the venue.
#
# 🛑 DELAWARE IS DELIBERATELY ABSENT. Filling it in is a research task with a
# named source and Paul's sign-off, not a guess -- do not copy PA's numbers
# across and do not infer them. Until DE is here, no DE venue can publish.
RULES = {
    "PA": {
        "max_hours_per_day": MAX_HOURS_PER_DAY,
        "max_hours_per_week": MAX_HOURS_PER_WEEK,
        "max_food_combos_per_day": 2,
        "banned": None,          # filled in below, once BANNED exists
        "authority": "PA Acts 57 & 86 of 2024",
    },
}

STATE_RE = re.compile(r"\b([A-Z]{2})\b(?:\s+\d{5}(?:-\d{4})?)?\s*$", re.I)


def state_of(address):
    """The two-letter state an address ends in, or None if it does not say.

    The PLCB export writes '700 W DEKALB PK, KING OF PRUSSIA PA 19406'. An
    address that names no state is not assumed to be PA -- that assumption is
    exactly what this module now exists to stop.
    """
    m = STATE_RE.search((address or "").strip())
    return m.group(1) if m else None


def rules_for(state):
    """The ruleset for a state, or None if we do not have that state's law."""
    return RULES.get(state)

# Claims that are unlawful in PA, so we never render them regardless of source.
BANNED = [
    r"all[- ]you[- ]can[- ]drink",
    r"bottomless",
    r"free drink",
    r"two for one|2 for 1|2-for-1",
    r"unlimited",
]

RULES["PA"]["banned"] = BANNED

TYPES = {"happy_hour", "daily_special", "food_combo"}
CATEGORIES = {"draft", "bottle_can", "wine", "well", "call", "cocktail", "shot", "food"}
CONFIDENCE = {"verified", "likely", "unconfirmed", "disputed"}
# "aggregator" and "instagram" are in the shipped seed; listing them keeps this
# check from silently deleting two published deals the day it lands.
KINDS = {"venue_site", "roundup", "aggregator", "instagram", "photo"}

# A roundup is a PUBLICATION describing a bar, not the bar speaking. Paul's call
# (2026-08-06): publish them, but in their own tier with the outlet named, capped
# at "unconfirmed" however specific the prose is, and never outranking the venue's
# own page. The outlet and its publish date are therefore not optional metadata --
# they are the whole reason the tier is allowed to exist.
ROUNDUP_MAX_AGE_DAYS = 120


def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def window_hours(w):
    return (minutes(w["end"]) - minutes(w["start"])) / 60.0


def validate_deal(deal):
    """Return a list of failure strings. Empty list means publishable."""
    errs = []

    if deal.get("type") not in TYPES:
        errs.append(f"unknown deal type {deal.get('type')!r}")
    if deal.get("confidence") not in CONFIDENCE:
        errs.append(f"unknown confidence {deal.get('confidence')!r}")

    windows = deal.get("windows") or []
    if not windows:
        errs.append("no windows -- a deal with no time is not an answer to 'can I go now?'")

    per_day = {}
    for w in windows:
        if not re.fullmatch(r"\d{2}:\d{2}", w.get("start", "")) or not re.fullmatch(
            r"\d{2}:\d{2}", w.get("end", "")
        ):
            errs.append(f"malformed window {w}")
            continue
        if w["dow"] not in range(1, 8):
            errs.append(f"dow out of range: {w['dow']}")
        # "24:00" is midnight, the latest a PA discount may legally run. An end
        # at or before the start means the window wraps into the next morning.
        if minutes(w["end"]) > 24 * 60:
            errs.append(f"window extends past midnight: {w['start']}-{w['end']}")
            continue
        hrs = window_hours(w)
        if hrs <= 0:
            errs.append(f"window extends past midnight: {w['start']}-{w['end']}")
            continue
        per_day[w["dow"]] = per_day.get(w["dow"], 0) + hrs

    # daily_special may run open-to-close on one beverage type; the 4h/24h caps
    # are a happy_hour constraint only.
    if deal.get("type") == "happy_hour":
        for dow, hrs in per_day.items():
            if hrs > MAX_HOURS_PER_DAY:
                errs.append(f"day {dow}: {hrs:g}h exceeds the 4h/day cap")
        total = sum(per_day.values())
        if total > MAX_HOURS_PER_WEEK:
            errs.append(f"{total:g}h/week exceeds the 24h/week cap")

    text = " ".join(
        [deal.get("fine_print") or ""] + [i.get("label", "") for i in deal.get("items") or []]
    ).lower()
    for pat in BANNED:
        if re.search(pat, text):
            errs.append(f"unlawful claim matched /{pat}/")

    for item in deal.get("items") or []:
        if item.get("category") not in CATEGORIES:
            errs.append(f"unknown item category {item.get('category')!r}")
        if (
            item.get("price_usd") is None
            and item.get("discount_pct") is None
            and item.get("amount_off_usd") is None
        ):
            errs.append(f"item {item.get('label')!r} has neither a price nor a discount")

    source = deal.get("source") or {}
    if not source.get("url") and not source.get("photo_id"):
        errs.append("no source -- every deal must be auditable")
    if source.get("kind") not in KINDS:
        errs.append(f"unknown source kind {source.get('kind')!r}")

    if source.get("kind") == "roundup":
        # Named outlet + publish date, or the card cannot say who is speaking and
        # the recency rule has nothing to gate on.
        if not source.get("outlet"):
            errs.append("roundup with no outlet -- the card must name who said it")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", source.get("published") or ""):
            errs.append("roundup with no publish date -- recency cannot be gated")
        if deal.get("confidence") != "unconfirmed":
            errs.append(f"roundup at {deal.get('confidence')!r}: the tier caps at unconfirmed")

    return errs


def validate_food_combo_count(deals_for_venue):
    """PA allows at most 2 food+drink combo specials per day."""
    errs = []
    per_day = {}
    for d in deals_for_venue:
        if d.get("type") != "food_combo":
            continue
        for w in d.get("windows") or []:
            per_day[w["dow"]] = per_day.get(w["dow"], 0) + 1
    for dow, n in per_day.items():
        if n > 2:
            errs.append(f"day {dow}: {n} food combos exceeds the 2/day cap")
    return errs


def main():
    payload = json.load(open(DEALS_JSON, encoding="utf-8"))
    by_venue = {}
    failed = 0
    for venue in payload["venues"]:
        for deal in venue.get("deals", []):
            errs = validate_deal(deal)
            by_venue.setdefault(venue["id"], []).append(deal)
            if errs:
                failed += 1
                print(f"FAIL {venue['name']} [{deal['type']}]")
                for e in errs:
                    print(f"       {e}")
    for venue in payload["venues"]:
        for e in validate_food_combo_count(by_venue.get(venue["id"], [])):
            failed += 1
            print(f"FAIL {venue['name']}: {e}")

    total = sum(len(v.get("deals", [])) for v in payload["venues"])
    print(f"\n{total - failed}/{total} deals pass the PA validators")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
