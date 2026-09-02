#!/usr/bin/env python3
"""Every published window must agree with the quote printed under it.

    python tests/window_quote_check.py

🛑 THE HOLE THIS FILLS. Every other validator in the repo asks one of two
questions: is this deal WELL FORMED, and is its quote PRESENT in the source
document. Nothing asked whether the two AGREE. So Penn Taproom shipped a
4:30-6:00 card off a quote that reads "4:30 to 6:30 PM" -- the card and its own
evidence contradicting each other in public -- and a 449-test suite was blind
to it. It was found by a person reading a card.

A wrong window is worse than a missing one, so this fails the build.

🔑 IT MUST NOT RE-USE THE GRAMMAR THAT PRODUCED THE WINDOW. Calling
windows_from() on the quote again would agree with itself by construction, and
would have passed Penn Taproom: the defect WAS in that grammar. So this reads
the quote the dumb way instead -- every clock literal in the text, every day
word in the text -- and asks whether what got published can be found there.

Two questions, both answerable without any grammar:

  CLOCKS  Both ends of a published window must be a time the quote actually
          says. 6:00 PM is not in "4:30 to 6:30 PM".
  DAYS    A quote that limits itself ("weekdays", "weeknights", "Monday
          through Friday", "M-F") must not have shipped all seven days. This
          is the other half of the same class: Off the Rail's "happy hours
          weeknights, 4 to 6 PM" shipped Saturday and Sunday, because a day
          word the grammar did not know read as no day at all, and no day at
          all means daily.

A quote with no clock literal in it at all is not judged here -- a window can
legitimately be read off a menu picture or a structured field, and the quote
beside it is then prose. That is the deliberate limit of this check.
"""

import json
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLES = os.path.join(REPO, "web", "data", "zone-*.json")

# A clock literal, read with no grammar at all: '4', '4:30', '4 pm', '4:30 PM'.
# 🛑 Never after a '$'. '$6 TITO'S MIXED DRINKS' is a price, and reading it as
# six o'clock let a quote with no clock in it at all look like a quote that
# disagreed -- five of the first run's complaints were that, and a guard whose
# red is noise gets switched off.
CLOCK_RE = re.compile(
    r"(?<![$\d])\b(\d{1,2})(?::([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?|[ap]\b)?", re.I)
# The quote is only judged when it states at least one time UNAMBIGUOUSLY --
# with a meridiem or a colon. A bare number in prose is a price, a count or a
# street number far more often than it is a clock, and a window read off a menu
# picture or a structured hours field is legitimately printed beside prose.
HAS_A_CLOCK_RE = re.compile(r"(?<![$\d])\b\d{1,2}(?::[0-5]\d|\s*[ap]\.?m?\.?\b)", re.I)

# The day contradiction this can actually see without a grammar: the quote
# limits itself to the working week and says nothing about a weekend, and the
# card shipped all seven days anyway. Deliberately narrow. A quote that names
# BOTH halves -- 'Monday - Friday 4 PM - 7 PM / Saturday - Sunday 11 AM - 2 PM'
# -- covers the week legitimately, and Veda, Santucci's, Lansdale Tavern and 86
# West were all flagged by the wider rule for doing exactly that.
WEEKDAY_ONLY_RE = re.compile(r"\bweek\s*(?:day|night)s?\b", re.I)
WEEKEND_RE = re.compile(r"\bweekends?\b|\bsat(?:ur)?(?:day)?s?\b|\bsun(?:day)?s?\b"
                        r"|\bdaily\b|\bevery ?day\b|\ball week\b|\b7 days\b", re.I)


def clocks_in(text):
    """Every minute-of-day the text could be read as saying.

    Deliberately generous: a bare '6' with a 'PM' later in the sentence is
    offered as both 06:00 and 18:00, because this check exists to catch a
    published time that appears NOWHERE in the quote, not to re-derive which
    reading was meant. Generous here means a false pass is possible and a false
    FAILURE is not, which is the right way round for a gate that blocks a ship.
    """
    text = text or ""
    if re.search(r"\bclose\b|\bclosing\b|\blast call\b", text, re.I):
        return None  # 'until close' has no clock; nothing to compare against
    if not HAS_A_CLOCK_RE.search(text):
        return None
    out = set()
    for m in CLOCK_RE.finditer(text):
        h, mm, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if h > 12 or h == 0:
            continue
        if ap.startswith("a"):
            # '12am' is BOTH ends of the day: a window that starts there starts
            # at 00:00 and one that ends there ends at 24:00. Chickie's &
            # Pete's '10pm-12am' is a correct card in three zones, and reading
            # only 00:00 called all three a contradiction.
            out |= {0, 24 * 60} if h == 12 else {h * 60 + mm}
        elif ap.startswith("p"):
            out.add((h % 12 + 12) * 60 + mm)
        else:
            out.add((h % 12) * 60 + mm)
            out.add((h % 12 + 12) * 60 + mm)
    # Midnight and noon, however the venue wrote them.
    if re.search(r"\bmidnight\b", text, re.I):
        out |= {0, 24 * 60}
    if re.search(r"\bnoon\b", text, re.I):
        out.add(12 * 60)
    return out


def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def check_deal(venue, deal):
    """[complaint] for one deal -- empty when the card and its quote agree."""
    src = deal.get("source") or {}
    # Every quote that fed a window, not only the one the card prints. One bar
    # states its day happy hour on one line and its night one on another, and
    # both are on the card; judging the card against a single line would fail
    # it for publishing what its OTHER evidence says.
    quote = " / ".join(src.get("quotes") or [src.get("quote") or ""])
    if not quote:
        return []
    windows = deal.get("windows") or []
    bad = []

    said = clocks_in(quote)
    if said:
        for w in windows:
            for edge in ("start", "end"):
                if minutes(w[edge]) not in said:
                    bad.append(f"{edge} {w[edge]} is not a time this quote states")
                    break
            if bad:
                break

    days = {w["dow"] for w in windows}
    if days & {6, 7} and WEEKDAY_ONLY_RE.search(quote) and not WEEKEND_RE.search(quote):
        bad.append("published a weekend off a quote that says weekdays only")

    return [f"{venue['zone_id']:<24} {venue['name'][:34]:<36} {b}\n"
            f"{'':24} quote: {quote[:150]}" for b in bad]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = sorted(glob.glob(BUNDLES))
    if not files:
        sys.exit("no shipped bundles -- run ingest/build_bundles.py first")
    checked, complaints = 0, []
    for path in files:
        for v in json.load(open(path, encoding="utf-8"))["venues"]:
            for d in v.get("deals") or []:
                checked += 1
                complaints += check_deal(v, d)
    for c in complaints:
        print(f"  DISAGREES  {c}")
    print(f"\n{checked} published deals, {len(complaints)} whose window "
          f"contradicts its own quote")
    if complaints:
        sys.exit(1)


if __name__ == "__main__":
    main()
