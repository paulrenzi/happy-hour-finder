#!/usr/bin/env python3
"""Tell a standing weekly show from a one-off, using the venue's own words.

Read `PLAYBOOK-NIGHT-OUT.md` §15 before changing anything here.

Most of a bar's calendar is a weekly grid, not a list of gigs. Saloon 151
publishes eight standing shows, Kildare's seven; 118 North -- an actual music
room booking named touring acts -- is the exception. A reader that only knows
one-offs turns each of those into a row per week, which goes stale, costs a
re-read to refresh, and (worst) mints a new id every week so a human approval
can never stick.

The tell is in the evidence we already paid for. Flip and Baileys' Music Bingo
quotes as "Thursdays 7pm-9pm" -- a WEEKDAY and NO DATE. The model derived
9/10 and 9/17 from that rule. So:

    a quote that names a weekday as a rule, and prints no date,
    is a recurrence rule, whatever date the model attached to it.

That is checkable without asking a model a second time, which is why it lives
here as ordinary code rather than in the prompt. The prompt asks too -- this is
the floor under it, and it re-grounds reads taken before the prompt existed.
"""

import re

DAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
ABBR = "mon|tue|tues|wed|weds|thu|thur|thurs|fri|sat|sun"

# "Thursdays", "every friday", "each Sunday", "Tuesday nights", "Fri & Sat"
RULE_RE = re.compile(
    r"\b(?:(?:every|each|all)\s+(?:%s|%s)\b"
    r"|(?:%s)s\b"
    r"|(?:%s)\s+(?:night|nights|evening|evenings)\b"
    r"|weekly\b)" % (DAYS, ABBR, DAYS, DAYS),
    re.I,
)

MONTHS = ("january|february|march|april|may|june|july|august|september|october"
          "|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")

# An explicit calendar date: "September 11", "Sep 11", "9/11", "11 September".
DATE_IN_TEXT_RE = re.compile(
    r"\b(?:(?:%s)\.?\s+\d{1,2}\b"
    r"|\d{1,2}\s+(?:%s)\b"
    r"|\d{1,2}\s*/\s*\d{1,2}\b)" % (MONTHS, MONTHS),
    re.I,
)


def infers_weekly(quote):
    """True when the venue stated a RULE and printed no date to override it.

    Both halves matter. "Thursdays 7pm-9pm" is a rule. "Sat Sep 05 ... Doors
    7:00 PM" names a day AND a date, and the date wins -- a Saturday show at a
    music room is not a claim that there is one every Saturday.
    """
    q = quote or ""
    return bool(RULE_RE.search(q)) and not DATE_IN_TEXT_RE.search(q)


def repeats_on_one_weekday(rows):
    """Acts the model itself expanded onto the same weekday more than once.

    The second, stronger signal, and it needs no transcript surgery. A model
    `quote` is a narrow slice -- Saloon 151's "Quizzo Starts at 7pm" -- while the
    "Mondays:" heading that makes it a rule sits a line above, outside the quote.
    Quote-only inference therefore UNDER-detects: it caught 1 of Saloon 151's 8
    standing shows.

    But the expansion is itself evidence. A 14-day window contains each weekday
    twice, so a venue that publishes a weekly grid comes back with the same act
    on the same weekday twice over -- and the model only did that because it read
    a rule. Paired with "no date in any of those quotes", that is a rule.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        groups[(r["act"].strip().lower(), _weekday(r["date"]))].append(r)
    return {
        key for key, g in groups.items()
        if len(g) > 1 and not any(DATE_IN_TEXT_RE.search(r.get("quote") or "") for r in g)
    }


def collapse_weekly(rows):
    """Mark inferred weekly rules, and collapse the copies they were expanded to.

    A rule the model expanded into four Thursdays becomes ONE row on the
    earliest of them -- `date` is the first occurrence and carries the weekday.
    Order is preserved so the caller's output stays readable.
    """
    repeated = repeats_on_one_weekday(rows)
    seen, out = {}, []
    for r in rows:
        row = dict(r)
        if row.get("recurs") != "weekly" and (
            infers_weekly(row.get("quote"))
            or (row["act"].strip().lower(), _weekday(row["date"])) in repeated
        ):
            row["recurs"] = "weekly"
        if row.get("recurs") != "weekly":
            out.append(row)
            continue
        # One rule per venue, act and weekday. Keep the earliest date, because
        # that is the one the expansion walks forward from.
        key = (row["act"].strip().lower(), _weekday(row["date"]))
        if key in seen:
            kept = seen[key]
            if row["date"] < kept["date"]:
                kept["date"] = row["date"]
            continue
        seen[key] = row
        out.append(row)
    return out


def _weekday(iso):
    import datetime
    return datetime.date.fromisoformat(iso).weekday()
