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

# Claims that are unlawful in PA, so we never render them regardless of source.
BANNED = [
    r"all[- ]you[- ]can[- ]drink",
    r"bottomless",
    r"free drink",
    r"two for one|2 for 1|2-for-1",
    r"unlimited",
]

TYPES = {"happy_hour", "daily_special", "food_combo"}
CATEGORIES = {"draft", "bottle_can", "wine", "well", "call", "cocktail", "shot", "food"}
CONFIDENCE = {"verified", "likely", "unconfirmed", "disputed"}


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

    if not deal.get("source", {}).get("url") and not deal.get("source", {}).get("photo_id"):
        errs.append("no source -- every deal must be auditable")

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
