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

from validate_pa import (  # noqa: E402
    MAX_HOURS_PER_DAY,
    minutes,
    MAX_HOURS_PER_WEEK,
    validate_deal,
    window_hours,
)

HITS = os.path.join(REPO, "data", "crawl_hits.json")
SITES = os.path.join(REPO, "data", "venue_sites.json")
OUT = os.path.join(REPO, "data", "deals_extracted.json")
COORDS = os.path.join(REPO, "data", "venue_coords.json")
PAGES = os.path.join(REPO, "data", "pages")
WINDOWS_LLM = os.path.join(REPO, "data", "windows_pages_llm.json")
TRANSCRIPTS = os.path.join(REPO, "data", "menu_image_transcripts.json")


def norm(text):
    """Whitespace-insensitive form, so an evidence check is not defeated by the
    line breaks the crawler joined with ' / '."""
    return re.sub(r"\s+", " ", text).strip().lower()


def page_spans():
    """{lid: (url, [span])} written by ingest/read_windows_llm.py, RE-CHECKED here.

    A span only survives if it is still a literal substring of a page we hold
    for that venue. The sidecar is not evidence of itself: it was verified when
    it was written, the page may have changed since, and a file on disk is the
    easiest thing in this pipeline to be wrong about. No model runs here.
    """
    if not os.path.exists(WINDOWS_LLM):
        return {}
    side = json.load(open(WINDOWS_LLM, encoding="utf-8"))
    if not side or not os.path.isdir(PAGES):
        return {}
    text_by_lid = {}
    for fn in os.listdir(PAGES):
        if not fn.endswith(".json"):
            continue
        page = json.load(open(os.path.join(PAGES, fn), encoding="utf-8"))
        lid = str(page.get("lid"))
        if lid in side:
            text_by_lid.setdefault(lid, []).append(
                norm("\n".join(page.get("lines") or [])))
    out = {}
    for lid, rec in side.items():
        live = [sp for sp in rec.get("spans") or []
                if any(norm(sp) in t for t in text_by_lid.get(lid, []))]
        if live:
            out[lid] = (rec.get("url", ""), live)
    return out


def picture_spans(scripts):
    """{venue_id: (image_url, [span])} from the vision pass's transcripts.

    A span is a line that names the happy hour plus the two lines under it,
    which is where a menu sheet states its hours ("Happy Hour" / "( Wednesday
    through Friday 3pm to 6pm )"). The rest of the sheet -- the lunch special
    that runs "open to 4pm", the Sunday brunch -- is never a candidate. The
    span is converted by windows_from(), unmodified, so the picture is held
    to exactly the grammar a crawled quote is.
    """
    out = {}
    for vid, rec in (scripts or {}).items():
        # Every sheet the venue posted, not only the last one read: the hours
        # sit on one of them and the food on another.
        images = dict(rec.get("images") or {})
        if rec.get("url") and rec.get("transcript"):
            images.setdefault(rec["url"], rec["transcript"])
        for url, transcript in images.items():
            lines = [ln.strip() for ln in (transcript or "").splitlines() if ln.strip()]
            spans = [" ".join(lines[i:i + 3]) for i, ln in enumerate(lines)
                     if len(ln) <= 40 and HH_RE.search(ln)]
            if spans:
                out[vid] = (url, spans)
                break
    return out


DOW = {"mon": 1, "monday": 1, "tue": 2, "tues": 2, "tuesday": 2, "wed": 3,
       "weds": 3, "wednesday": 3, "thu": 4, "thur": 4, "thurs": 4,
       "thursday": 4, "fri": 5, "friday": 5, "sat": 6, "saturday": 6,
       "sun": 7, "sunday": 7}
DAY_RE = "|".join(sorted(DOW, key=len, reverse=True))
# 'til is written with an apostrophe as often as without, on either side of
# the l: Tommy's Tavern + Tap publishes "3 PM TIL' 6 PM" on its happy hour
# page and "4 PM 'TIL CLOSE" on its location page, and neither parsed, so a
# venue whose whole schedule was on the page stated no schedule at all.
DASH = r"(?:-|\u2013|\u2014|to|thru|through|[\u2019']?til[\u2019']?l?[\u2019']?|until)"

# A day is routinely written PLURAL -- 'Fridays', 'Wednesdays, Thursdays &
# Fridays' -- and `days_in('Fridays')` returned the empty set, so a venue that
# named its day in the ordinary English way stated no schedule and published
# nothing. The trailing s is optional on both ends of a range and on a single
# day alike; no weekday is another word with an s on it, so this cannot
# over-match.
#
# The separator may also carry the venue's punctuation: 'MON.-THURS.' abbreviates
# with periods, and requiring whitespace between the day and the dash did not
# merely miss it -- RANGE_RE failed, SINGLE_RE then matched both ends
# independently, and days_in returned {Mon, Thu}, SILENTLY DROPPING TUESDAY AND
# WEDNESDAY. A range we cannot read has to fail as a range, never decay into two
# single days, which is what the abbreviation guard below also exists to prevent.
RANGE_RE = re.compile(
    rf"\b({DAY_RE})s?\.?\s*{DASH}\s*({DAY_RE})s?\b", re.I)
SINGLE_RE = re.compile(rf"\b({DAY_RE})s?\b", re.I)

# The other way a menu writes its days: one- and two-letter codes, in a range
# ('M-F', 'Tu-F') or a slash list ('W/Th/Fr'). These cannot go in DOW, because
# a bare 'M' or 'F' in prose is not a day and DOW is matched against whole
# pages.
#
# 'T' and 'S' are genuinely ambiguous -- Tuesday or Thursday, Saturday or
# Sunday -- and no amount of looking at the letter decides it. So a construction
# containing one is REFUSED WHOLE rather than read for the codes around it: a
# partial answer here is a card that names the wrong days, which is worse than
# the card we do not publish. Same rule as a happy-hour section that fails short.
DAY_CODE = {"m": 1, "mo": 1, "tu": 2, "tue": 2, "w": 3, "we": 3, "th": 4,
            "thu": 4, "f": 5, "fr": 5, "sa": 6, "su": 7}
AMBIGUOUS_CODE = ("t", "s")
_CODE = r"[A-Za-z]{1,3}"
CODE_RANGE_RE = re.compile(rf"\b({_CODE})\s*(?:-|\u2013|\u2014)\s*({_CODE})\b")
CODE_LIST_RE = re.compile(rf"\b({_CODE})(?:\s*/\s*({_CODE})){{1,6}}\b")


def _code(tok):
    """The weekday a short code names, 0 if it is ambiguous, None if not a code."""
    t = tok.lower().rstrip(".")
    if t in AMBIGUOUS_CODE:
        return 0
    return DAY_CODE.get(t)


def code_days(text):
    """Weekdays named by an abbreviation range or slash list, or set()."""
    for m in CODE_RANGE_RE.finditer(text):
        a, b = _code(m.group(1)), _code(m.group(2))
        if a == 0 or b == 0:
            return set()          # ambiguous: refuse the construction whole
        if a and b:
            return {(a - 1 + i) % 7 + 1 for i in range((b - a) % 7 + 1)}
    for m in CODE_LIST_RE.finditer(text):
        toks = [t for t in re.split(r"\s*/\s*", m.group(0)) if t]
        got = [_code(t) for t in toks]
        if any(g is None for g in got):
            continue              # not a day list at all -- a path, a fraction
        if any(g == 0 for g in got):
            return set()          # ambiguous: refuse the construction whole
        return set(got)
    return set()
# "EVERY. SINGLE. DAY." is Bonefish's own words for seven days a week, and
# days_in() returned the empty set on it -- so the document we could not
# reach would have been refused for naming no day even once we could.
EVERYDAY_RE = re.compile(r"\b(?:daily|every ?day|every\W{0,3}single\W{0,3}day|all week|7 days a week|seven days)\b", re.I)
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

# A bar publishes its lunch, brunch and dinner service in exactly the shape of a
# happy hour, on the same page, often in the same sentence: Barbuzzo's is
# 'LUNCH: Saturday & Sunday - 12pm-4pm'. Four hours is lawful, so the statutory
# cap cannot catch it -- and a lunch menu published as a happy hour is a wrong
# claim, which is worse than a missing one. A clause that names a different meal
# states that meal's hours, whatever else the quote says.
MEAL_RE = re.compile(
    r"\b(?:lunch|brunch|breakfast|dinner|supper|kitchen (?:hours|open)|"
    r"menu served|(?:open|serving)\s+(?:daily|from))\b", re.I)

# Which of two windows on one day is the happy hour is not decidable from the
# clock -- taking the longer picked the bar's opening hours, the shorter picked
# its 10pm late-night, the earlier picked its lunch. The page already says which
# is which, so the deciding fact is the WORD, not the time.
HH_RE = re.compile(r"happy\s*hour|social hour|power hour", re.I)

# A fragment that states a schedule rather than naming a thing you can buy. The
# same test crawl_sites makes; a list of item names contains none of this.
CONTEXT_RE = re.compile(
    r"\d{1,2}(?::\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.)|\bmon|\btue|\bwed|\bthu|\bfri|\bsat|\bsun", re.I)
# A price on a line of its own, as the crawler emits it. Mirrors BARE_PRICE_RE
# in crawl_sites.py.
BARE_PRICE_RE = re.compile(r"^\$\s?\d{1,3}(?:\.\d{1,2})?$")

# A price and the thing it buys. The dollar sign may be followed by a space --
# Squarespace and BentoBox both print '$ 10' -- and the cents may be written
# with a single digit ('$5.5'). Neither form was readable, and both are how a
# real menu prints money: the Gypsy Saloon's entire happy hour is spaced, and
# the venue read as one that publishes no prices at all.
PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:\.\d{1,2})?)\s*([A-Za-z][\w\s&'-]{1,28})")
HALF_RE = re.compile(r"half.?price(?:d)?\s+([A-Za-z][\w\s&'-]{1,28})", re.I)
# A venue that prints the item FIRST and the price after it -- 'BEER $5',
# 'Blue Moon draft $4'. PRICE_RE cannot read that form at all, so every such
# price used to be read as belonging to whatever item came NEXT, one item too
# far along. Anchored to the END of the quote, which is the one position where
# the side is not in doubt: the price closes the line, so the item is what
# precedes it. A price in the MIDDLE of a line is left alone -- that is the
# ambiguous case, and it is not answered by guessing.
TRAILING_PRICE_RE = re.compile(
    r"([A-Za-z][\w\s&'-]{1,28}?)\s\$\s?(\d{1,3}(?:\.\d\d)?)\s*$")

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
             r"pizza|pizzas|taco|tacos|oyster|oysters|burger|burgers|snack|snacks|"
             r"small plate|small plates|nacho|nachos|fries|pretzel"),
]


def items_from_hits(hits, lead_url):
    """The priced items for a deal, from every quote entitled to contribute one.

    Until now this was fed only the quotes that state a SCHEDULE, because those
    are the quotes that become windows. But a price line almost never states a
    schedule: the venue prints its hours once, at the top, and the prices under
    them. Paladar's '$4.50 Draft Beer' was crawled, stored in crawl_hits.json
    and then silently dropped for exactly that reason -- and 59 of the 146
    priceless venues were in the same position, with the price already on disk.

    So a quote also contributes when it came from the SAME PAGE as the schedule
    we published. That page is the one the venue itself put its happy hour on,
    which is the argument the URL key always made; a price from any other page
    is the dinner menu and is still refused. The quote had to clear the crawl's
    own containment before it could be stored at all, so this widens which
    stored quotes are read, never what may be stored.

    Read ONE QUOTE AT A TIME, never over the quotes joined together. Joining
    them invents an adjacency the page never had: 'Beef Quesadilla $7' and
    'Blue Moon draft $4' are two separate lines on the Great American Pub's
    menu, and joined with a space PRICE_RE reads '$7 Blue Moon draft' and
    published the draft at $7 when the pub charges $4. 35 items on 20 venues
    were priced across such a boundary, Estia's beer among them -- $8 on the
    board, $5 on its own PDF. A quote is the unit the crawl vouched for, and
    the price pass may not reach past its edge.
    """
    # A page that HAS a happy-hour section has already answered which of its
    # lines are happy-hour lines, and the URL test must not overrule it.
    # Tommy's Tavern + Tap prints its happy hour and, further down the SAME
    # page, a 'WEEKDAY SPECIALS' block running 4pm to close. Containment
    # correctly left that block outside the section -- and then `url ==
    # lead_url` let every line of it back in, and half-price Wednesday sangria
    # published as a seven-day 3-6pm happy hour item, on the wrong days, at a
    # price the venue does not charge then. The fallback is for pages where
    # containment found NOTHING; where it found something, it is the authority.
    contained = {h["url"] for h in hits if h.get("hh")}
    out, seen = [], set()
    for h in hits:
        if h["url"] in contained and not h.get("hh"):
            continue
        # `hh` is the crawl saying this line sat inside the venue's OWN
        # happy-hour section. That is the containment the URL test was standing
        # in for, and it is stronger: it survives the venue printing its hours
        # on one page and its menu on another, which is what left Mia Ragazza,
        # the Gypsy Saloon and 20-odd others with a window and an empty card
        # while both halves sat in crawl_hits.json. See mark_hh in crawl_sites.
        if not (h.get("hh") or h["url"] == lead_url or windows_from(h["quote"])):
            continue
        for item in items_in(h["quote"]):
            if item["label"].lower() in seen:
                continue
            seen.add(item["label"].lower())
            out.append(item)
    # No cap. The card folds after 3 and keeps the rest behind "+N more",
    # so the display never needed one -- the cap only threw away menu we had
    # already read. It cut in quote order, which cost Yard House its entire
    # half-off pizza section (Paul, 2026-09-01).
    return out


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
    if not out:
        # Only when the spelled-out grammar found nothing: a page that says
        # 'Monday' says it in DOW, and the codes are the fallback for the page
        # that only ever writes 'M-F'.
        out |= code_days(text)
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
            # '12pm' is the one hour that can mean either end of the day, and
            # The SideCar's 'LATE NIGHT HAPPY HOUR FRIDAY ONLY 10-12PM' is the
            # shape that exposes it: read as noon it forced the start back to
            # 10am and published a Friday morning happy hour. A start that has
            # to be pm cannot end at noon, so the noon is midnight.
            if emer == "pm" and eh == 12:
                end = 24 * 60
            else:
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


# '$2 Off Wine by the Glass' is not a $2 glass of wine, and PRICE_RE reads it as
# one -- label 'Off Wine by the Glass', category wine, price $2.00. So the form
# has to be told apart from a price, and it was, by refusing it outright: the
# note here said the pipeline had no field for a dollars-off discount. That was
# true when it was written and is not true now -- `amount_off_usd` is checked by
# ingest/validate_pa.py AND worker/validate_pa.js, rendered by itemParts() and
# ranked by itemValue(). The refusal outlived its reason, and it cost Lansdale
# Tavern, W Tavern, Black Horse and Interstate their entire happy hour: every
# line those venues publish is '$1 off draft beer'. The amount is now read as
# what the venue said it was -- a discount -- and never as a price.
OFF_RE = re.compile(r"^off\b", re.I)
# The same line, read instead of refused. Anchored at the dollar amount so the
# word 'off' has to belong to THIS price; 'Off' further along a dish name is not
# a discount.
AMOUNT_OFF_RE = re.compile(
    r"\$\s?(\d{1,3}(?:\.\d{1,2})?)\s*off\s+([A-Za-z][\w\s&'-]{1,40})", re.I)


# A quote the crawler built from a PRICED SECTION HEADING and one item under
# it: 'SNACKS $7.50-7.75 each / $7.50-7.75 Traditional Guacamole'. The heading
# is carried along because it answers the question the noun list cannot: a
# guacamole is food because the venue filed it under SNACKS, not because
# 'guacamole' is a word we happen to know. See heading_prices() in crawl_sites.
# 64, not 40: a real dish name runs longer than a drink's does, and the cap was
# silently deleting 'WOOD-GRILLED CORN, AGED CHEDDAR AND SPICED BACON' -- a
# length limit rejecting a valid item is the same silent drop as the (R) was.
# The comma is allowed because wine is named with one and nothing else is:
# 'SANTA JULIA, PINOT GRIGIO' is one item, not two, and without the comma the
# whole wine list of a venue drops out with no error raised anywhere.
SECTION_ITEM_RE = re.compile(
    r"^\$\s?(\d{1,3}(?:\.\d{1,2})?)(?:\s?-\s?\$?\s?(\d{1,3}(?:\.\d{1,2})?))?"
    r"\s+([A-Za-z][\w\s&',()-]{1,64})$")

# The same shape, for a section the venue discounts instead of pricing: Yard
# House's 'HH 1/2 OFF SELECT APPS' names no price at all, and the price its own
# menu API carries for each dish is the FULL one. Publishing that number would
# put $14.99 on the board for a $7.50 spinach dip -- the '$X off' mistake again,
# with the digits sitting right there looking like an answer. The discount is
# what the venue stated, so the discount is what we publish.
SECTION_OFF_RE = re.compile(r"^(\d{1,2})% Off\s+([A-Za-z][\w\s&'()-]{1,64})$", re.I)


# A quote that arrives already classified, because its source said what the item
# was instead of leaving us to infer it from the heading. The noun whitelist is
# for pages where inference is all we have; where a structured menu states
# isBeverageItem, asking the word list again can only lose items it has never
# heard of. See darden_category() in crawl_sites.
# The board's whole vocabulary -- a marker naming anything else is ignored rather
# than trusted, so a source cannot invent a category by asserting one.
CATEGORIES = {"draft", "bottle_can", "wine", "well", "call", "cocktail", "shot", "food"}

CAT_MARKER = re.compile(r"^\[cat:([a-z_]+)\]\s*")


def strip_category_marker(text):
    m = CAT_MARKER.match(text)
    if not m:
        return text, None
    cat = m.group(1)
    return text[m.end():], cat if cat in CATEGORIES else None


def section_items(text):
    """[item] for a 'priced heading / item' quote, or [] if this is not one.

    A range is published AS a range. '$7.50-7.75 each' is what the venue said
    and it is what the card says; picking either end would be stating a price
    for a dish that does not have it.
    """
    text, cat = strip_category_marker(text)
    parts = [p.strip() for p in text.split(" / ")]
    # The price on a line of its own between the heading and the dish. A themed
    # menu emits three blocks, not two -- the Gypsy Saloon's happy hour is
    # 'bites / $ 10 / Mini French Fry Board', and read as two parts it is not a
    # section quote at all and the whole venue goes unpriced. Only a BARE price
    # may be the middle part, so nothing else can be folded away.
    if len(parts) == 3 and BARE_PRICE_RE.match(parts[1]):
        parts = [parts[0], parts[1] + " " + parts[2]]
    if len(parts) != 2:
        return []
    if not cat:
        cat = category_of(parts[0])
    if not cat:
        return []
    m = SECTION_ITEM_RE.match(parts[1])
    if not m:
        off = SECTION_OFF_RE.match(parts[1])
        if not off:
            return []
        pct = int(off.group(1))
        label = off.group(2).strip(" -'")
        if not 0 < pct < 100:
            return []
        return [{"category": cat, "label": label, "discount_pct": pct}]
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    label = m.group(3).strip(" -'")
    if not 0 < lo <= hi <= 99 or OFF_RE.search(label):
        return []
    item = {"category": cat, "label": label, "price_usd": lo}
    if hi != lo:
        item["price_max"] = hi
    return [item]


# A price stated once for a LIST the venue then names, all in one quote:
# '$6 sips / House Red / House White / Draft Beers / Seasonal Sangria', or Hard
# Rock's '-$8 Nachos, Tupelo Dippers, Jumbo Pretzels'. The price is not repeated
# on any of them, so PRICE_RE reads the first name and nothing else, and a
# four-item happy hour publishes one item. The adjacency is not invented here:
# the crawler already vouched that these lines are ONE box on the page.
LIST_HEAD_RE = re.compile(r"^-?\s?\$\s?(\d{1,3}(?:\.\d{1,2})?)\s*(.*)$")
LIST_ITEM_MAX = 40
LIST_CAP = 12


def _comma_items(part):
    """A comma-separated part split into item names, or left whole if it is prose."""
    pieces = [x.strip() for x in part.split(",")]
    if len(pieces) < 2:
        return [part]
    for x in pieces:
        head = re.sub(r"^-?\s?\$\s?\d{1,3}(?:\.\d{1,2})?\s*", "", x)
        if not head[:1].isupper() or len(head.split()) > 4:
            return [part]
    return pieces


def shared_price_items(text, cat_hint=None):
    """[item] when one price at the head of a quote owns the names after it."""
    text, marked = strip_category_marker(text)
    parts = [x.strip() for x in text.split(" / ") if x.strip()]
    # A comma separates the items on Hard Rock's list AND the ingredients in
    # CO-OP's wing description -- 'Wings / House-made hot sauce, fermented
    # vegetables, blue cheese'. Reading the second as a list publishes 'blue
    # cheese $12', a thing the venue does not sell. So a comma only splits when
    # EVERY piece is named the way a menu names a dish: capitalised, and short.
    # A single lowercase fragment means it is prose, and prose is left whole.
    parts = [x for p_ in parts for x in _comma_items(p_)]
    if len(parts) < 2:
        return []
    m = LIST_HEAD_RE.match(parts[0])
    if not m:
        return []
    price = float(m.group(1))
    if not 0 < price <= 99:
        return []
    # The head may name the kind of thing ('$6 sips') or nothing at all ('-$8').
    head_cat = marked or cat_hint or category_of(m.group(2)) or category_of(parts[0])
    # What follows the price on the head part may be the KIND ('$6 sips') or the
    # first item itself ('-$8 Nachos'). It is offered as an item either way: a
    # kind-word carries no category of its own and drops out, and Hard Rock's
    # nachos are not silently the one item on the list nobody reads.
    names = ([m.group(2).strip()] if m.group(2).strip() else []) + parts[1:]
    out, seen = [], set()
    for name in names[:LIST_CAP]:
        if "$" in name or len(name) > LIST_ITEM_MAX or not re.search(r"[A-Za-z]{3}", name):
            return []          # not a list of names; do not guess at it
        if CONTEXT_RE.search(name):
            return []          # a schedule line rode along; this is not a list
        # A name a menu would print, not a sentence about one. Fava's quote is
        # 'Shrimp Cocktail * / 3 shrimp, cocktail sauce' -- the second block is
        # the description of the first, and as an item it reads '$10 3 shrimp,
        # cocktail sauce'. The venue capitalises what it sells.
        if not name[:1].isupper():
            continue
        cat = category_of(name) or head_cat
        if not cat or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"category": cat, "label": name.strip(" -'"), "price_usd": price})
    return out if len(out) >= 2 else []


def items_in(text):
    section = section_items(text)
    if section:
        return section
    shared = shared_price_items(text)
    if shared:
        return shared
    out, seen = [], set()
    for m in AMOUNT_OFF_RE.finditer(text):
        # The sentence carries on past the thing being discounted -- '$5 off our
        # Lounge Menu and Signature Cocktails during happy hour'. The card has
        # room for the noun, not the clause.
        label = re.split(r"\s+/\s+|\s+during\s+|\s+all\s+day\b", m.group(2))[0]
        label = re.sub(r"\s+(?:and|&|or)$", "", label.strip()).strip(" -'")
        cat = category_of(label)
        if cat and label.lower() not in seen:
            seen.add(label.lower())
            out.append({"category": cat, "label": label,
                        "amount_off_usd": float(m.group(1))})
    for m in PRICE_RE.finditer(text):
        # '$6.50 Mojitos & Margaritas' is ONE priced label, and splitting it at
        # the '&' handed category_of the word 'Mojitos', which no noun matches --
        # so a line the whitelist would have accepted on 'margaritas' was thrown
        # away by our own truncation. The split still runs, because '$5 Wings and
        # Fries' really is better labelled 'Wings', but it is now a FALLBACK: the
        # whole label is offered first and the shortened one only if that fails.
        whole = m.group(2).strip().strip(" -'")
        first = re.split(r"\s+(?:and|or|&)\s+", whole)[0].strip(" -'")
        label = whole if category_of(whole) else first
        if OFF_RE.search(label):
            continue
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
    m = TRAILING_PRICE_RE.search(text)
    if m:
        label = m.group(1).strip(" -'")
        cat = category_of(label)
        if cat and label.lower() not in seen:
            seen.add(label.lower())
            out.append({"category": cat, "label": label, "price_usd": float(m.group(2))})
    # No cap. The card folds after 3 and keeps the rest behind "+N more",
    # so the display never needed one -- the cap only threw away menu we had
    # already read. It cut in quote order, which cost Yard House its entire
    # half-off pizza section (Paul, 2026-09-01).
    return out


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


# A DATED thing is not a weekly thing. This guard exists only for the rule
# below it: a quote that names a calendar date or a holiday is one night, and
# reading it as 'every day' would put a Toys For Tots night on 14 December and a
# bartaco Fourth of July party on the board as a standing happy hour, seven days
# a week, forever.
ONE_OFF_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{1,2}(?:st|nd|rd|th)?\b|"
    r"\b\d{1,2}(?:st|nd|rd|th)\s+of\s+\w+|"
    r"\b(?:new year|christmas|thanksgiving|halloween|easter|valentine|"
    r"st\.?\s*patrick|cinco de mayo|super bowl|fourth of july|4th of july)\b|"
    r"\btonight\b|\bthis (?:friday|saturday|sunday|week|weekend)\b",
    re.I)


def _hours(w):
    """How long a window runs, in hours; 24:00 is midnight."""
    h1, m1 = map(int, w["start"].split(":"))
    h2, m2 = map(int, w["end"].split(":"))
    return (h2 * 60 + m2 - h1 * 60 - m1) / 60.0


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
            if MEAL_RE.search(piece):
                # Not this venue's happy hour, and the days it names belong to
                # the meal -- so they must not carry forward either.
                pending = set()
                continue
            here = days_in(piece)
            if here:
                pending = here
            win = window_in(piece)
            if win and pending:
                out += [{"dow": d, "start": win[0], "end": win[1]} for d in sorted(pending)]
                pending = set()
    if out:
        return out
    # A happy hour stated as a CLOCK AND NO DAYS is a happy hour every day.
    #
    # This is an inference and it is written down as one. 23 venues published a
    # window and nothing else -- Tommy's Tavern + Tap says "HAPPY HOUR / 3 PM
    # TIL' 6 PM" and never names a day anywhere on the page -- and refusing them
    # published nothing at all, which is not the safer answer, it is just the
    # invisible one. A venue that limits its happy hour to weekdays SAYS SO;
    # Tommy's own page proves it, heading the block below its daily happy hour
    # 'WEEKDAY SPECIALS'. Silence about days is the venue saying every day.
    #
    # Two guards keep the inference off anything that is not a standing weekly
    # deal: a MEAL clause (lunch and brunch are published in this exact shape)
    # and a DATE, which is the difference between a happy hour and a party.
    if len(quote) <= 200 and len(TIME_RE.findall(quote)) == 1 \
            and HH_RE.search(quote) and not MEAL_RE.search(quote) \
            and not ONE_OFF_RE.search(quote) and not days_in(quote):
        win = window_in(quote)
        if win:
            return [{"dow": d, "start": win[0], "end": win[1]}
                    for d in range(1, 8)]
    # An event listing writes the days last ('Happy Hour / 4:30 PM - 6:30 PM /
    # Friday'), which reading forwards can never pair up. Falling back to the
    # whole quote is only safe while there is exactly one time range in it --
    # otherwise the pairing would be a guess about which days went with which.
    if len(quote) <= 200 and len(TIME_RE.findall(quote)) == 1 \
            and not MEAL_RE.search(quote):
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
    """One window per weekday.

    A day claimed twice is either one deal read twice or two different deals,
    and which it is decides what to publish:

      * They OVERLAP -- one happy hour, described twice. Veda says
        'Monday - Thursday 4:30PM - 7:00PM' on one page and 4:00 on another.
        Publish the overlap: every minute of it is claimed by both readings, so
        nobody is sent to pay full price at a discount that had not started.
      * They are DISJOINT -- two different deals, and the clock cannot say which
        is the happy hour. Cedar Point runs 5-7pm and again at 10-11pm; Veda
        serves lunch 11:30-2:30 and pours happy hour at 4:30. Taking the longer
        published opening hours, the shorter published the late-night, the
        earlier published the lunch. So the WORD decides: the window whose quote
        says 'happy hour' wins, and only when neither does does the earlier one.

    A bar also publishes its OPENING hours on the same page in the same shape --
    Sor Ynez's 'Tues - Sat 12pm - 9pm' sits one clause away from its 'Happy Hour
    Tues - Fri 4pm - 7pm', and Valley Forge Pizza's only window is 'Mon - Sun:
    11:00 AM - 10:00 PM'. Those cannot be a happy hour because the statute caps
    one, so they never win a day anything lawful claims; they are left for
    lawful_days() to drop.
    """
    def teatime(w):
        # Two genuine happy hours in one day -- Southern Cross pours at noon and
        # again at 4:30, Cedar Point at 5 and again at 10 -- and only one fits on
        # a card. Publish the one a person means when they say 'happy hour',
        # which is the one overlapping late afternoon most.
        return min(minutes(w["end"]), 19 * 60) - max(minutes(w["start"]), 16 * 60)

    def rank(w):
        # A window over the statutory cap cannot be a happy hour, and a window
        # from a quote that says 'happy hour' is one on the venue's own word.
        span = minutes(w["end"]) - minutes(w["start"])
        return (span <= MAX_HOURS_PER_DAY * 60, w.get("_hh", False))

    best = {}
    for w in windows:
        cur = best.get(w["dow"])
        if cur is None:
            best[w["dow"]] = w
            continue
        if rank(w) != rank(cur):
            best[w["dow"]] = max(w, cur, key=rank)
            continue
        lo = max(minutes(cur["start"]), minutes(w["start"]))
        hi = min(minutes(cur["end"]), minutes(w["end"]))
        if lo < hi:
            best[w["dow"]] = dict(w, start="%02d:%02d" % divmod(lo, 60),
                                  end="%02d:%02d" % divmod(hi, 60))
        elif teatime(w) != teatime(cur):
            best[w["dow"]] = max(w, cur, key=teatime)
        elif minutes(w["start"]) < minutes(cur["start"]):
            best[w["dow"]] = w
    return [{k: v for k, v in w.items() if k != "_hh"}
            for _dow, w in sorted(best.items())]


def lawful_days(windows):
    """The days of a schedule that stand on their own.

    A venue used to be discarded whole when a single day broke the statutory
    cap: Brewery Techne lost four lawful 'Tuesday thru Friday: 4pm - 6pm'
    windows because the weekend line beside them reads as 4.5 hours. One
    unlawful day is a bad reading of that day, not evidence against the others.
    """
    kept = sorted((w for w in windows if window_hours(w) <= MAX_HOURS_PER_DAY),
                  key=lambda w: w["dow"])
    while kept and sum(window_hours(w) for w in kept) > MAX_HOURS_PER_WEEK:
        kept.remove(max(kept, key=window_hours))
    return kept


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

    pages = page_spans()
    pictures = picture_spans(json.load(open(TRANSCRIPTS, encoding="utf-8"))
                             if os.path.exists(TRANSCRIPTS) else {})
    venues, stats, kept, rejects = [], collections.Counter(), [], []
    seen_ids = set()
    for lid, v in one_per_osm(hits, sites):
        # The crawl found a menu picture and the vision pass transcribed it:
        # the happy-hour lines of that transcript are candidates, and they
        # enter through windows_from() like any other. The items come from
        # the picture sidecar at bundle time.
        url, spans = pictures.get(slug(v["osm_name"] or v["name"], v["address"]),
                                  ("", []))
        pic_cands = [({"url": url, "quote": span}, ws)
                     for span in spans for ws in [windows_from(span)] if ws]
        cands = []
        for h in v["hits"]:
            ws = windows_from(h["quote"])
            if not ws:
                continue
            # A clock that runs longer than any happy hour may is the venue's
            # OPENING hours: Valley Forge Pizza's /happy-hours page says
            # "Happy Hours / Mon - Sun: 11:00 AM - 10:00 PM" and the real
            # window, Mon-Fri 4-6, is in the picture underneath. The PA
            # validators would refuse the 11-hour span later anyway; refusing
            # it here lets the picture be heard instead of the venue being
            # rejected whole.
            if all(_hours(w) > 4 for w in ws):
                stats["  quote is opening hours, not a happy hour"] += 1
                continue
            cands.append((h, ws))
        if not v["hits"]:
            stats["no quote crawled" if not pic_cands else "  window read off a menu picture"] += 1
            cands = pic_cands
        elif pic_cands and not any(HH_RE.search(h["quote"]) for h, _ in cands):
            # The picture names the happy hour and no text quote does: Molly
            # Maguire's only text with a clock is its "Late Night Menu
            # Thursdays 10pm to 11pm", and the picture says "HAPPY HOUR Monday
            # -Friday 5-7 PM". The venue's own word for the thing wins.
            stats["  window read off a menu picture"] += 1
            cands = pic_cands
        else:
            stats["venue had quotes"] += 1
        if not cands:
            # The page reader may propose a WINDOW as a verbatim span (Paul's
            # call, 2026-09-02), and this is the whole of where it lands. The
            # span was checked against the page when it was written and again
            # by page_spans() above; here it is converted by windows_from() --
            # the same parser, unmodified -- so a span with no meridiem is
            # refused exactly as a crawled quote would be. It enters as an
            # ordinary candidate, which means dedupe(), the PA validators and
            # lawful_days() all still run over it below.
            url, spans = pages.get(str(lid), ("", []))
            for span in spans:
                ws = windows_from(span)
                if ws:
                    cands.append(({"url": url, "quote": span}, ws))
            if cands:
                stats["  window read off the page"] += 1
        if not cands:
            stats["  quote states no schedule"] += 1
            if len(rejects) < args.rejects:
                rejects.append((v["osm_name"] or v["name"],
                                v["hits"][0]["quote"] if v["hits"] else "(no quote)"))
            continue

        # The richest quote names the deal; the rest of the site's quotes only
        # add windows, and their prose is not what gets shown.
        cands.sort(key=lambda c: (len({w["dow"] for w in c[1]}), len(c[0]["quote"])),
                   reverse=True)
        lead = cands[0][0]
        # Each window remembers whether the sentence it came from called itself a
        # happy hour, so dedupe() can settle a contested day on the venue's word.
        windows = dedupe([dict(w, _hh=bool(HH_RE.search(h["quote"])))
                          for h, ws in cands for w in ws])
        deal = {
            "type": "happy_hour",
            "windows": windows,
            "items": items_from_hits(v["hits"], lead["url"]),
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
            # Still unlawful: keep the days that are, drop the days that are
            # not. Then the lead quote has to be one that actually produced a
            # surviving window, or the card would show a sentence about hours
            # it no longer publishes.
            deal["windows"] = lawful_days(windows)
            survivors = {(w["dow"], w["start"], w["end"]) for w in deal["windows"]}
            live = [c for c in cands
                    if any((w["dow"], w["start"], w["end"]) in survivors for w in c[1])]
            if deal["windows"] and live:
                lead = live[0][0]
                deal["source"]["url"] = lead["url"]
                deal["source"]["quote"] = lead["quote"]
                errs = validate_deal(deal)
                if not errs:
                    stats["  kept after dropping an unlawful day"] += 1
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
