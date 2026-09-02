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
# 🔑 DELAWARE, researched and signed off 2026-09-02 (Paul). It was deliberately
# absent until then, and the note it replaces said filling it in needed a named
# authority and a sign-off rather than a guess. Both are recorded below.
#
# The finding that matters, and the reason PA's numbers could not have been
# copied across: DELAWARE SETS NO HOUR CAP AND NO CUTOFF. There is no 4h/day,
# no 24h/week, no midnight rule. Its rule is about the SHAPE of the offer, not
# its length -- 4 Del. Admin. Code § 908 Rule 3.0 "Prohibited Practices"
# (eff. 02/01/16) forbids two-or-more-drinks-for-the-price-of-one (3.1.1.5),
# unlimited consumption for a set price (3.1.1.7), giving alcohol away
# (3.1.1.1) and selling below cost (3.1.1.3). Food-and-drink combinations are
# not restricted.
#
# So a lawful Wilmington happy hour can run five hours, and PA's cap would have
# suppressed it; and PA's `banned` list happens to cover DE's prohibitions
# almost exactly, which is precisely the coincidence that would have made
# copying look like it worked.
#
# 🛑 The rule for the NEXT state is unchanged: no entry means no publishing.
RULES = {
    "PA": {
        "max_hours_per_day": MAX_HOURS_PER_DAY,
        "max_hours_per_week": MAX_HOURS_PER_WEEK,
        "max_food_combos_per_day": 2,
        "banned": None,          # filled in below, once BANNED exists
        "authority": "PA Acts 57 & 86 of 2024",
    },
    "DE": {
        # None is not "unknown" here -- it is the researched finding that the
        # statute sets no limit. An unknown state has no entry at all.
        "max_hours_per_day": None,
        "max_hours_per_week": None,
        "max_food_combos_per_day": None,
        "banned": None,          # filled in below, once DE_BANNED exists
        "authority": "4 Del. Admin. Code § 908 Rule 3.0 (Prohibited Practices), "
                     "eff. 02/01/16; Delaware OABCC",
        "signed_off_by": "Paul, 2026-09-02",
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

# Delaware's own list, from Rule 3.1.1. Written out rather than aliased to
# BANNED: they agree today by coincidence, not by derivation, and aliasing them
# would make one state's amendment silently amend the other's.
DE_BANNED = [
    r"all[- ]you[- ]can[- ]drink",   # 3.1.1.7 unlimited consumption, set price
    r"bottomless",                   # 3.1.1.7
    r"unlimited",                    # 3.1.1.7
    r"free drink",                   # 3.1.1.1 giving alcoholic beverages
    r"two for one|2 for 1|2-for-1",  # 3.1.1.5 two or more for the price of one
    r"open bar",                     # 3.1.1.7, per the OABCC FAQ
]
RULES["DE"]["banned"] = DE_BANNED

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


def validate_deal(deal, state="PA"):
    """Return a list of failure strings. Empty list means publishable.

    🛑 The hour caps and the banned list come from RULES[state], not from this
    module's PA constants. Those constants were read directly here for as long
    as every venue was in Pennsylvania, which meant the RULES table existed and
    was consulted by exactly one caller -- so adding Delaware to it would have
    changed nothing, and a lawful five-hour Wilmington happy hour would still
    have been refused for breaking a Pennsylvania cap.

    A state with no entry fails here as well as at the door in
    build_bundles.py. Two closed doors on the same question is the intent: this
    one is reached by the extractors, and an unpublishable deal is better
    refused where its quote is still attached.
    """
    errs = []
    rules = rules_for(state)
    if rules is None:
        return [f"no ruleset for state {state!r}; its law has not been encoded "
                f"(see validate_pa.RULES)"]
    max_day = rules.get("max_hours_per_day")
    max_week = rules.get("max_hours_per_week")
    banned = rules.get("banned") or []

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
        if max_day is not None:
            for dow, hrs in per_day.items():
                if hrs > max_day:
                    errs.append(f"day {dow}: {hrs:g}h exceeds the "
                                f"{max_day:g}h/day cap")
        if max_week is not None:
            total = sum(per_day.values())
            if total > max_week:
                errs.append(f"{total:g}h/week exceeds the {max_week:g}h/week cap")

    text = " ".join(
        [deal.get("fine_print") or ""] + [i.get("label", "") for i in deal.get("items") or []]
    ).lower()
    for pat in banned:
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
        # A venue that prices a whole block at once states a RANGE -- Paladar's
        # happy-hour snacks are '$7.50-7.75 each'. The range is published as a
        # range because neither end is the price of any particular dish, so
        # choosing one would put a number on a card the venue never charged.
        hi = item.get("price_max")
        if hi is not None:
            lo = item.get("price_usd")
            if lo is None:
                errs.append(f"item {item.get('label')!r} has a price_max and no price")
            elif not lo < hi <= 99:
                errs.append(f"item {item.get('label')!r} has a price range {lo}-{hi} "
                            "that is not a range")

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
