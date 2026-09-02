#!/usr/bin/env python3
"""THE MODEL READS THE MENU -- and the regex grammar becomes its validator.

    python ingest/read_menus_llm.py ask   --lids run.lids [--show] [--rejects]
    python ingest/read_menus_llm.py build [--show]

Every other model pass in this repo reads something a regex already chose.
`reach_llm links` picks a URL, `reach_llm verdict` quotes lines that
`windows_from()` then parses, `read_pages_llm` prices lines a rule engine kept.
So a venue whose page states its happy hour in a phrasing the grammar has not
met ships nothing, and the run calls that correct. Paul, 2026-09-02: *"the model
needs to read menus. how am i explaining this basic fact after this much work
based on a goal that requires them to be read?"*

This pass is the answer. It hands a model the WHOLE of every page we saved for
a venue and the WHOLE of every menu picture we transcribed, and asks for the
deals on it as rows:

    {kind, days, start, end, items: [{label, price}], quote}

`kind` is one of SPEC's three -- `happy_hour`, `daily_special`, `food_combo`.
**A daily special is a happy-hour item and goes on the card** (Paul, same day:
"they are happy hour items"). The deliberate refusal of day-specials pages in
extract_prices_llm.vouched() and read_pages_llm.worth_reading() is what kept Sly
Fox's card short; `kind` replaces it, so a Margherita-Monday price can never
land under a happy-hour heading -- it lands under its own.

WHAT THE MODEL IS STILL NOT ALLOWED TO DO. It is a reader, not a source, and
nothing it returns reaches a card on its own say-so:

  * `quote` must be a literal substring of the source document. Checked here
    when the answer is written, and checked AGAIN in `build` against the file
    on disk -- the sidecar is not evidence of itself.
  * the clock must be IN the quote. `start`/`end` come back as 24h strings and
    each has to be spelled somewhere in the quote it was read from.
  * every day must be IN the quote -- as a name, an abbreviation, a code, or a
    word like "daily"/"weekdays". The one exception is the settled rule the
    grammar already carries: a clock, no day token at all and no date is a deal
    that runs every day.
  * every item's price must sit in its own evidence span, and that span in the
    source. Same rule extract_prices_llm.verify() applies, same reason.
  * `validate_pa.validate_deal()` runs over the finished deal, so PA's 4h/day
    and 24h/week caps, the midnight cutoff and the banned-claims list all still
    decide. A `happy_hour` longer than 4h is the venue's OPENING hours and is
    refused here too, before the validators, with that name on it.

The grammar in extract_deals is imported and used, but only ever to REFUSE --
`windows_from()` is never asked what a window is any more. That is the whole
change: the reader is the model, the regex is the validator.
"""

import argparse
import datetime
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extract_deals as ed  # noqa: E402
from extract_prices_llm import LEAN_ARGS, ask_with  # noqa: E402
from validate_pa import validate_deal, validate_food_combo_count  # noqa: E402

PAGES = os.path.join(REPO, "data", "pages")
BASE = os.path.join(REPO, "data", "venue_base.json")
TRANSCRIPTS = os.path.join(REPO, "data", "menu_image_transcripts.json")
SIDECAR = os.path.join(REPO, "data", "deals_menus_llm.json")
OUT = os.path.join(REPO, "data", "deals_menus.json")

MODEL = os.environ.get("HHF_MENU_MODEL", "sonnet")
BATCH = int(os.environ.get("HHF_MENU_BATCH", "3"))
DOC_CAP = 9000          # chars of one page or transcript handed to the model
QUOTE_CAP = 700         # a quote may be a whole menu block, not a whole page
HEADING_CAP = 120       # the venue's own name for the deal, as it prints it
ADJACENT = 300          # chars between a happy hour and the clock line it owns
CALENDAR_MIN = 3        # printings of one heading that make a calendar recurring
CALENDAR_LOOKBACK = 600 # chars back to the date header an entry sits under
MAX_DEALS = 8           # deals one document may state
MAX_ITEMS = 40
TODAY = datetime.date.today().isoformat()

KINDS = ("happy_hour", "daily_special", "food_combo")

# THE HEADING IS THE GUARD, AND IT WAS BOUGHT WITH A $50 PRIME RIB.
#
# The first run of this pass over Ambler read William Penn Inn's dinner PDF and
# returned three `daily_special` rows -- Tue-Fri 5:00-6:30, Saturday 4:30-5:30,
# Sunday 3:00-4:00 -- with ten entrees at $35 to $50 under each. Every one of
# them was grounded: the clock is on the page, the days are on the page, the
# prices are on the page. It is a recurring, time-bounded, priced offer and it
# is still not a thing to put on this board, because the heading two lines above
# it reads "WILLIAM PENN INN PRIX FIXE". It is the dinner service, served early.
#
# A wrong item is worse than a missing one, so the model now has to return the
# venue's OWN heading for each deal, checked as a literal substring like every
# other span here, and a heading that names a meal service is refused whatever
# `kind` the model chose. The list is a BLOCKLIST on purpose: a whitelist of
# deal words would refuse "Wing Wednesday", and refusing is the invisible
# answer, not the safe one.
NOT_A_DEAL_RE = re.compile(
    r"prix.?fixe|table d.?h[oô]te|tasting menu|early (?:bird|dining)|"
    r"(?:dinner|lunch|breakfast|brunch|dessert|kids?|children)'?s? menu|"
    r"catering|banquet|wedding|private (?:party|event|dining)|"
    r"gift card|rewards? (?:club|program)", re.I)
ZW_RE = re.compile("[​‌‍﻿]")
_SYS = ("You read restaurant menus and web pages and report the deals they "
        "state. Answer with JSON only.")


def _args():
    out = list(LEAN_ARGS)
    out[out.index("--system-prompt") + 1] = _SYS
    return out


def ask(batch, template, **fields):
    import extract_prices_llm as ep
    saved = ep.LEAN_ARGS
    ep.LEAN_ARGS = _args()
    try:
        return ask_with(batch, template, MODEL, **fields)
    finally:
        ep.LEAN_ARGS = saved


PROMPT = """\
Each block below is ONE document from a bar or restaurant in Pennsylvania: the
visible text of a page from its own website, or the transcript of a menu it
posted as a picture.

Report EVERY recurring, time-bounded deal the document states. There are three
kinds and all three count:

- `happy_hour`  -- a recurring discount window on drinks and/or food, whatever
  the venue calls it: "Happy Hour", "Appy Hour", "Social Hour", "Bar Bites 3-6",
  "Drink Specials", "Late Night", "Hoppy Hour", "Power Hour".
- `daily_special` -- a deal that runs on a named day or days: "Taco Tuesday $3
  tacos", "Wing Wednesday", "$9 growlers Wednesdays", "Sunday $2 off Bloody
  Marys". These COUNT. Report them.
- `food_combo` -- a food-plus-drink deal at one price: "$12 cheesesteak + pint",
  "burger and a beer $15".

NOT a deal: regular opening hours, a standing menu with its normal prices, a
brunch service, a one-off dated event, a private-party package, a loyalty club,
a gift card.

For each deal return:
- `kind`: one of happy_hour, daily_special, food_combo.
- `days`: the weekdays it runs, as numbers, Monday=1 ... Sunday=7. If the
  document states a time and names NO day anywhere, return an empty list --
  that is read as every day. Never guess a day the document does not state.
- `start`, `end`: 24-hour "HH:MM". Midnight is "24:00". Both must be times the
  document actually states.
- `clock_quote`: for a deal whose own text names NO time. Two cases. A calendar
  or specials page states the deal on one line and its hours on the next
  ("Happy Hour (Bars and High Tops ONLY!) ..." then "04:30 PM - 06:30 PM") --
  copy that clock line here. And a `daily_special` like "Wednesday: $9 Select
  Growlers" runs the whole day the venue is open -- copy the document's own
  hours line for that day ("Tuesday- Saturday 11:30AM- 9:00PM"). Either way copy
  it EXACTLY and put the times in `start` and `end`. Leave it out whenever the
  deal states its own times.
- `items`: the priced things this deal offers, as
  `{{"label", "price", "category", "evidence"}}`.
  `label` is the thing being sold as the venue names it. `price` is the dollar
  amount as a number ("$5" -> 5). A deal stated as a REDUCTION rather than a
  price uses one of the other two instead and leaves `price` out:
  "half price wings" -> `discount_pct` 50, "20% off drafts" -> `discount_pct` 20,
  "$2 off Bloody Marys" -> `amount_off` 2. Report those; a discount is an item.
  `evidence` is a SHORT exact substring of the document containing that price.
  `category` is exactly one of: {categories}. It matters on the card: a Bloody
  Mary filed as `food` is a wrong item, and a wrong item is worse than a
  missing one.
  An empty list is fine -- a stated window with no prices is still a deal.
- `heading`: the venue's OWN name for this deal, copied EXACTLY as the document
  prints it -- the heading or title line the deal sits under ("HAPPY HOUR",
  "Appy Hour", "Bar Bites", "Wing Wednesday", "WILLIAM PENN INN PRIX FIXE").
  Copy it character for character; it is checked as a literal substring and a
  deal without one is discarded. If the document gives the block no heading at
  all, use the line that names the offer.
- `quote`: an EXACT substring of the document, copied character for character,
  that states this deal's days and times. Keep it short but complete; it may
  span several lines. It is checked programmatically as a literal substring and
  the days and clock must be inside it, so do not paraphrase, do not merge
  distant lines, and do not tidy the spelling or the punctuation.

If the document states no deal at all, return an empty `deals` list. An empty
answer is a real answer and is often the right one.

Return ONLY a JSON array, no prose and no code fence:
[{{"id": "<id>", "deals": [
  {{"kind": "happy_hour", "days": [1,2,3,4,5], "start": "16:00", "end": "18:00",
    "heading": "HAPPY HOUR", "quote": "Happy Hour Monday-Friday 4-6pm",
    "items": [{{"label": "drafts", "price": 5, "category": "draft",
                "evidence": "$5 drafts"}}]}}
]}}]

DOCUMENTS:
{venues}
"""


# ---- the source documents --------------------------------------------------


def clean(s):
    return ZW_RE.sub("", s or "")


def transcripts_by_slug():
    if not os.path.exists(TRANSCRIPTS):
        return {}
    return json.load(open(TRANSCRIPTS, encoding="utf-8"))


def documents(lid, base, scripts):
    """[(kind, url, text)] -- every page we saved and every menu picture we
    transcribed for this venue. Not only the pages a regex liked, and not only
    the venues with no hit: the verdict pass's `not v["hits"]` gate is the same
    defect in miniature and it is not repeated here."""
    out = []
    prefix = f"{lid}__"
    if os.path.isdir(PAGES):
        for fn in sorted(os.listdir(PAGES)):
            if not fn.startswith(prefix) or not fn.endswith(".json"):
                continue
            page = json.load(open(os.path.join(PAGES, fn), encoding="utf-8"))
            lines = [ln for ln in (page.get("lines") or []) if ln.strip()]
            if len(lines) < 3:
                continue
            out.append(("page", page.get("url", ""), "\n".join(lines)))
    v = base.get(lid) or {}
    rec = scripts.get(ed.slug(v.get("name", ""), v.get("address", ""))) or {}
    images = dict(rec.get("images") or {})
    if rec.get("url") and rec.get("transcript"):
        images.setdefault(rec["url"], rec["transcript"])
    for url, text in images.items():
        if (text or "").strip():
            out.append(("image", url, text))
    return out


# ---- the validators --------------------------------------------------------


def in_source(span, source):
    """The span, as the SOURCE spells it, or None. Zero-width padding is a Wix
    habit a model does not copy and a person cannot see, so it is not part of
    the comparison (the same rule reach_llm.grounded() uses)."""
    span, source = clean(span), clean(source)
    if not span.strip():
        return None
    if span in source:
        return span
    return span if ed.norm(span) in ed.norm(source) else None


def clock_in(hhmm, quote):
    """Is this 24h time spelled in the quote, in any of the ways a menu spells
    it? '16:00' is published as '4', '4pm', '4:00 PM', '16:00', '04:00 PM'."""
    if not re.fullmatch(r"\d{1,2}:\d{2}", hhmm or ""):
        return False
    h, m = (int(x) for x in hhmm.split(":"))
    text = ed.norm(quote)
    h12 = h % 12 or 12
    # ZERO-PADDED 12-HOUR IS A REAL SPELLING AND IT WAS MISSING. A specials
    # calendar prints "04:30 PM - 06:30 PM", and without the padded form the
    # only candidates were "16:30" and "4:30" -- the first absent, the second
    # refused by the (?<!\d) lookbehind because a 0 sits in front of it. Every
    # venue that writes its hours that way was refused, silently, as "correct".
    forms = {f"{h}:{m:02d}", f"{h:02d}:{m:02d}", f"{h12}:{m:02d}", f"{h12:02d}:{m:02d}"}
    if m == 0:
        forms |= {str(h12), f"{h12:02d}", f"{h12}:00", f"{h12} o'clock"}
        if h == 24:
            forms |= {"midnight", "12", "12:00"}
        if h == 12:
            forms.add("noon")
    want_pm = 12 <= h < 24
    for f in forms:
        # (?![\d:]) rather than (?!\d): the bare-hour form "11" otherwise matches
        # INSIDE "11:00 am", and the meridiem test below then sees ":" as "no
        # meridiem stated" and accepts it -- so an 11am opening time evidenced
        # an 11pm window.
        for mt in re.finditer(rf"(?<!\d){re.escape(f)}(?![\d:])", text):
            # A meridiem printed right after the time has to AGREE with the
            # 24-hour value the model claimed, or "04:30 AM" happily evidences a
            # 4:30 PM happy hour. Noon is the one place 12 is already pm.
            after = text[mt.end():mt.end() + 6]
            mer = re.match(r"\s*([ap])\.?m?\.?\b", after)
            if mer and (mer.group(1) == "p") != want_pm and not (h == 12 and want_pm):
                continue
            return True
    return False


def clock_near(quote, start, end, source):
    """The stretch of document beside this deal that spells both of its times.

    Returns the span, or None. A calendar page prints the deal on one line and
    "04:30 PM - 06:30 PM" on the next; a menu prints the heading, the hours and
    then the list. Either way the hours are within a couple of lines, and a
    window that wide cannot reach the opening-hours block at the top of the page.
    """
    if not (re.fullmatch(r"\d{1,2}:\d{2}", start or "")
            and re.fullmatch(r"\d{1,2}:\d{2}", end or "")):
        return None
    hay = ed.norm(clean(source))
    needle = ed.norm(clean(quote))
    at = hay.find(needle)
    while at >= 0:
        lo = max(0, at - ADJACENT)
        hi = min(len(hay), at + len(needle) + ADJACENT)
        window = hay[lo:hi]
        if clock_in(start, window) and clock_in(end, window):
            return window
        at = hay.find(needle, at + 1)
    return None


def day_header(quote, source):
    """(span, days) for the nearest weekday named BEFORE this deal, or (None, set()).

    A specials CALENDAR states the day once, as the header over the entry:

        Tuesday September 1st
        BYOW Tuesdays | ...                       04:30 PM - 09:00 PM
        Happy Hour (Bars and High Tops ONLY!) ... 04:30 PM - 06:30 PM
        Wednesday September 2nd

    The happy-hour line therefore names no day at all, and requiring the day
    inside the quote refused The Copper Crow's real weekday happy hour five
    times over -- once per day it runs. Bridget's Steakhouse in Ambler is the
    same layout, so this is a page CLASS, not a venue.

    Backwards only, and the NEAREST one, because that is how a calendar reads:
    an entry belongs to the header above it, never the one below. A symmetric
    window would straddle the next day's header and could hand a Tuesday deal
    Wednesday's name.
    """
    hay = ed.norm(clean(source))
    needle = ed.norm(clean(quote))
    at = hay.find(needle)
    if at < 0:
        return None, set()
    before = hay[max(0, at - CALENDAR_LOOKBACK):at]
    last, days = None, set()
    for mt in re.finditer(ed.SINGLE_RE, before):
        here = ed.days_in(mt.group(0))
        if here:
            last, days = mt.group(0), here
    if not last:
        return None, set()
    return before[before.rfind(last):][:80].strip() or last, days



def repeats(heading, source):
    """How many times this heading appears in the document.

    A DATE IN THE QUOTE MEANS ONE-OFF ONLY IF THE DEAL HAPPENS ONCE. The Copper
    Crow publishes its standing happy hour on a specials CALENDAR: the same
    "Happy Hour (Bars and High Tops ONLY!)" under Tuesday September 1st,
    Wednesday September 2nd, and so on, each with its own prices and its own
    4:30-6:30 clock line. ONE_OFF_RE saw a date and refused all five, and a real
    weekday happy hour with five priced items was lost -- as it was for
    Bridget's Steakhouse in Ambler, the same page format.

    A party is announced once. A standing deal on a calendar is printed on every
    date it runs, so the venue's own heading repeating across the document is
    the evidence, and it is counted here rather than claimed by the model.
    """
    hay, needle = ed.norm(clean(source)), ed.norm(clean(heading))
    if len(needle) < 6:
        return 0
    return hay.count(needle)


def adjacent(quote, clock_quote, source):
    """Do these two spans sit within ADJACENT chars of each other in the source?

    Measured on the normalised text, because that is the form both spans were
    matched in, and against every occurrence of the deal quote: a calendar
    repeats one happy hour under seven dates, and only one of them is beside
    the clock line the model picked.
    """
    hay = ed.norm(clean(source))
    needle, clk = ed.norm(clean(quote)), ed.norm(clean(clock_quote))
    at_clk = hay.find(clk)
    if at_clk < 0:
        return False
    start = 0
    while True:
        at = hay.find(needle, start)
        if at < 0:
            return False
        # Either order: the clock line may sit above the deal or below it.
        if at <= at_clk:
            if at_clk - (at + len(needle)) <= ADJACENT:
                return True
        elif at - (at_clk + len(clk)) <= ADJACENT:
            return True
        start = at + 1


def days_in(quote):
    """The weekdays the quote itself names -- the grammar's own reader, used
    here ONLY to check the model, never to decide what the deal is."""
    return ed.days_in(quote)


# A location prefix, the way a chain's events calendar writes one:
#   "Pottstown - Trivia Every Wednesday!"
#   "Drexel Hill - Quizzo Tuesday"
# The town, then a dash or pipe or colon, at the start of a line.
LOC_PREFIX_RE = re.compile(
    r"(?:^|\n)\s*([A-Z][A-Za-z.']*(?:\s+[A-Z][A-Za-z.']*){0,2})\s*[-‐-―|:]\s*\S")

_TOWNS = None


def corpus_towns():
    """Every town the licence base names, lower-cased. Read once."""
    global _TOWNS
    if _TOWNS is None:
        base = json.load(open(BASE, encoding="utf-8"))
        towns = set()
        for v in base.values():
            m = re.search(r",\s*([A-Za-z][A-Za-z .']*?)\s+PA\b", v.get("address") or "")
            if m:
                towns.add(m.group(1).strip().lower())
        _TOWNS = towns
    return _TOWNS


def town_of(address):
    m = re.search(r",\s*([A-Za-z][A-Za-z .']*?)\s+PA\b", address or "")
    return m.group(1).strip().lower() if m else ""


def another_towns_row(text, address):
    """The OTHER town this text is headed with, or None.

    A chain publishes one events calendar for every location it owns, and each
    row is prefixed with the town it belongs to. Artillery Brewing's page gave
    the WEST CHESTER card "Pottstown - Trivia Every Wednesday!" and "Drexel Hill
    - Quizzo Tuesday". Both were correctly grounded -- those words really are on
    that page -- and both were the wrong thing, which is the failure no
    grounding check can see. The venue's own town is the discriminator.

    Deliberately narrow: only a town the licence base actually knows, only in
    the prefix position, and never the venue's own town. A section label like
    "Wings - $5" names no town and is untouched.
    """
    mine = town_of(address)
    towns = corpus_towns()
    for m in LOC_PREFIX_RE.finditer(text or ""):
        cand = m.group(1).strip().lower()
        if cand in towns and cand != mine:
            return m.group(1).strip()
    return None


def vet(row, source, url, address=None):
    """(deal, None) if the document really states this, else (None, why).

    Every refusal names what failed, because a pass whose misses are unnamed is
    the instrument this repo has been burned by twice.
    """
    kind = row.get("kind")
    if kind not in KINDS:
        return None, f"kind {kind!r}"

    heading = in_source((row.get("heading") or "")[:HEADING_CAP], source)
    if not heading:
        return None, "heading is not in the document"
    if NOT_A_DEAL_RE.search(heading):
        return None, f"heading is a meal service, not a deal: {heading[:40]!r}"
    if ed.MEAL_RE.search(heading):
        return None, f"heading names a meal: {heading[:40]!r}"

    quote = in_source((row.get("quote") or "")[:QUOTE_CAP], source)
    if not quote:
        return None, "quote is not in the document"
    if address:
        elsewhere = (another_towns_row(row.get("heading") or "", address)
                     or another_towns_row(quote, address))
        if elsewhere:
            return None, f"this row belongs to the {elsewhere} location, not ours"
    if ed.HEDGE_RE.search(quote):
        return None, "quote hedges ('check with us', 'see our socials')"
    if ed.ONE_OFF_RE.search(quote) and repeats(heading, source) < CALENDAR_MIN:
        return None, "quote names a DATE -- a party, not a standing deal"
    # The MEAL guard belongs on the venue's own HEADING, which is checked above.
    # On the quote it is a trap: a calendar's day-block puts the happy hour and
    # the lunch deal in the same few lines, so a quote that correctly spans the
    # happy hour picks up the word "lunch" from its neighbour and the venue's
    # real happy hour is refused as a lunch service. The venue's own word for
    # the thing wins -- so this only bites when the heading does NOT say it is
    # a happy hour.
    if ed.MEAL_RE.search(quote) and kind == "happy_hour"             and not ed.HH_RE.search(heading):
        return None, "quote is a meal service and the heading does not say happy hour"

    start, end = row.get("start"), row.get("end")
    clock_src, clock_quote, day_quote = quote, None, None
    if not (clock_in(start, quote) and clock_in(end, quote)):
        # A DAILY SPECIAL ROUTINELY STATES NO TIME. Sly Fox's card was short
        # because of exactly this: "Wednesday: $9 Select Growlers" carries a day
        # and a price and no clock, because the special runs the whole day the
        # pub is open -- and the pub's hours are stated further up the same page
        # ("Tuesday- Saturday" / "11:30AM- 9:00PM"). Refusing it published
        # nothing, which is the invisible answer rather than the safe one.
        #
        # So the clock may be grounded in a SECOND span of the same document,
        # and the card records which one. A happy hour may never use it: a happy
        # hour that does not state its own hours is not one we can publish, and
        # a 9-hour "happy hour" is the venue's opening hours by any other name.
        cq = in_source((row.get("clock_quote") or "")[:QUOTE_CAP], source)
        if not cq or not (clock_in(start, cq) and clock_in(end, cq)):
            # The model was ASKED for the clock line and routinely does not send
            # one, so the program goes and finds it: the text immediately around
            # this deal, in the document, that spells both times. That is a
            # stronger grounding than the model's own span, not a weaker one --
            # code located it and code checked it, and it cannot be a line the
            # model invented. If nothing beside the deal states the hours, the
            # deal is refused exactly as before.
            cq = clock_near(quote, start, end, source)
        if not cq:
            return None, f"clock {start}-{end} is not spelled in the quote"
        # A HAPPY HOUR MAY USE THE SECOND SPAN ONLY IF IT IS RIGHT BESIDE IT.
        #
        # An events-calendar page states the deal on one line and its clock on
        # the next: The Copper Crow's specials page reads "Happy Hour (Bars and
        # High Tops ONLY!) - $5 per birria taco ..." and then, as its own line,
        # "04:30 PM - 06:30 PM". The venue IS stating its happy hour's hours; it
        # is a two-line layout, and refusing it lost a real 4:30-6:30 happy hour
        # with five priced items on every weekday. Bridget's Steakhouse in
        # Ambler is the same page format, so this is a class, not a venue.
        #
        # Proximity is what makes the span belong to THIS deal. Without it a
        # happy hour would borrow the opening hours from the top of the page,
        # which is the exact confusion the over-4h rule below exists to catch.
        # A daily special has no such neighbour -- "Wednesday: $9 Select
        # Growlers" is nowhere near the pub's hours block -- so it still reads
        # anywhere in the document.
        if kind == "happy_hour" and not adjacent(quote, cq, source):
            return None, (f"clock {start}-{end} is not in the quote, and the span "
                          f"that has it is not beside it")
        clock_src, clock_quote = cq, cq

    days = [d for d in (row.get("days") or []) if isinstance(d, int) and 1 <= d <= 7]
    said = days_in(quote)
    if days:
        missing = sorted(set(days) - said)
        # A quote may name the days in a form days_in() cannot read -- that is
        # the whole reason this pass exists -- but then the model must not be
        # claiming days out of thin air either. The compromise the grammar
        # already makes elsewhere: accept the model's days when the quote names
        # SOME day the grammar agrees with, or names an everyday/weekday word.
        spread = ed.EVERYDAY_RE.search(quote) or ed.WEEKDAY_RE.search(quote) \
            or ed.WEEKEND_RE.search(quote)
        if missing and not said and not spread:
            # On a calendar page the day is the header ABOVE the entry, so the
            # program goes and reads it rather than refusing the deal. Gated on
            # the heading repeating, which is what makes a page a calendar: an
            # ordinary page has no header to borrow and is refused as before.
            span, header_days = (None, set())
            if repeats(heading, source) >= CALENDAR_MIN:
                span, header_days = day_header(quote, source)
            if not header_days or set(days) - header_days:
                return None, f"days {days} are not named in the quote"
            day_quote = span
    else:
        # A clock and no day at all is every day -- the rule extract_deals
        # settled and wrote down, applied here unchanged.
        if said:
            return None, "the model returned no days for a quote that names days"
        if ed.ONE_OFF_RE.search(quote):
            return None, "no days, and the quote names a date"
        days = list(range(1, 8))

    windows = [{"dow": d, "start": start, "end": end} for d in sorted(set(days))]
    if kind == "happy_hour" and all(ed._hours(w) > 4 for w in windows):
        # Valley Forge Pizza's /happy-hours page says "Happy Hours / Mon - Sun:
        # 11:00 AM - 10:00 PM". That is when the doors are open.
        return None, "over 4h -- these are the venue's OPENING hours"

    items, refused = [], []
    for it in (row.get("items") or [])[:MAX_ITEMS]:
        item, why = vet_item(it, quote, source)
        if item:
            items.append(item)
        else:
            refused.append(f"{(it.get('label') or '?')[:24]}: {why}")

    deal = {
        "type": kind,
        "windows": windows,
        "items": items,
        "confidence": "unconfirmed",
        "last_verified_at": TODAY,
        "verified_by": "menu_read_llm",
        # The URL goes on BEFORE the validators run: "no source -- every deal
        # must be auditable" is one of them, and filling it in afterwards
        # refused every deal this pass read on its first run.
        "source": {"kind": "venue_site", "url": url, "quote": quote,
                   "heading": heading},
    }
    if clock_quote:
        deal["source"]["clock_quote"] = clock_quote
    if day_quote:
        deal["source"]["day_quote"] = day_quote
    errs = validate_deal(deal)
    if errs:
        return None, errs[0]
    if refused:
        deal["_refused_items"] = refused
    return deal, None


def vet_item(it, quote, source):
    """The same bargain extract_prices_llm.verify() makes: a price reaches a
    card only when it is sitting in the venue's own sentence."""
    label = (it.get("label") or "").strip()
    if not 1 <= len(label) <= 60:
        return None, "label length"
    price, pct = it.get("price"), it.get("discount_pct")
    off = it.get("amount_off") if it.get("amount_off") is not None         else it.get("amount_off_usd")
    if price is None and it.get("price_usd") is not None:
        price = it.get("price_usd")
    if price is None and pct is None and off is None:
        return None, "no price and no discount"
    ev = in_source((it.get("evidence") or "")[:200], source) or in_source(quote, source)
    if not ev:
        return None, "evidence is not in the document"
    hay = ed.norm(ev)
    if price is not None:
        try:
            price = float(price)
        except (TypeError, ValueError):
            return None, "price is not a number"
        if not 0 < price <= 99:
            return None, f"price {price} out of range"
        # The price as a menu spells it: '5', '5.00', '5.0'.
        forms = {f"{price:g}", f"{price:.2f}"}
        if not any(re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", hay) for f in forms):
            return None, "the price is not in its own evidence"
    # A menu writes a half off three ways and only one of them is the word:
    # Sedona Taphouse's Sunday brunch says "1/2 off Bottles + Cans", and the
    # item was refused as unevidenced while the evidence was in the quote.
    if pct is not None and not re.search(r"\d\s*%|half|1\s*/\s*2", hay):
        return None, "the discount is not in its own evidence"
    if off is not None:
        try:
            off = float(off)
        except (TypeError, ValueError):
            return None, "amount off is not a number"
        if not 0 < off <= 99:
            return None, f"amount off {off} out of range"
        if not re.search(rf"(?<![\d.]){re.escape(f'{off:g}')}(?![\d])\s*(?:dollars?\s*)?off"
                         rf"|off\s*\$?\s*{re.escape(f'{off:g}')}(?![\d])", hay):
            return None, "the amount off is not in its own evidence"
    # The model names the category; category_of() -- a hand-typed noun
    # whitelist -- is the fallback, not the decision. It filed Well Crafted's
    # Bloody Mary, Bellini and Old Fashioned as `food` on this pass's first run.
    cat = it.get("category")
    if cat not in ed.CATEGORIES:
        cat = ed.category_of(label) or "food"
    out = {"label": label, "category": cat, "evidence": ev[:200]}
    if price is not None:
        out["price_usd"] = price
    if pct is not None:
        out["discount_pct"] = pct
    if off is not None:
        out["amount_off_usd"] = off
    return out, None


# ---- ask -------------------------------------------------------------------


def scoped(args, base):
    if args.lids:
        only = [ln.strip() for ln in open(args.lids, encoding="utf-8") if ln.strip()]
    elif args.zone:
        only = [lid for lid, v in base.items() if v.get("zone_id") == args.zone]
    else:
        sys.exit("--lids or --zone: this pass is never run over the whole corpus")
    return [lid for lid in only if lid in base]


def ask_cmd(args):
    base = json.load(open(BASE, encoding="utf-8"))
    scripts = transcripts_by_slug()
    held = json.load(open(SIDECAR, encoding="utf-8")) if os.path.exists(SIDECAR) else {}

    todo = []
    for lid in scoped(args, base):
        for n, (kind, url, text) in enumerate(documents(lid, base, scripts)):
            key = f"{lid}|{kind}|{url}"
            if key in held and not args.force:
                continue
            todo.append((key, lid, kind, url, text))
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} document(s) across {len({t[1] for t in todo})} venue(s), "
          f"{BATCH} per call [model {MODEL}]\n")

    kept_total, refused = 0, []
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        batch = [(f"{n}", f"{kind}: {url}\n\n{text[:DOC_CAP]}")
                 for n, (_, _, kind, url, text) in enumerate(chunk, i)]
        by_id = {f"{n}": row for n, row in enumerate(chunk, i)}
        try:
            reply = ask(batch, PROMPT, categories=", ".join(sorted(ed.CATEGORIES)))
        except Exception as e:  # noqa: BLE001 -- one failed batch is not a failed run
            print(f"  !! batch {i // BATCH + 1}: {type(e).__name__}: {e}"[:200])
            continue
        answered = {str(r.get("id")): r for r in (reply or []) if isinstance(r, dict)}
        for vid, (key, lid, kind, url, text) in by_id.items():
            rows = (answered.get(vid) or {}).get("deals") or []
            deals, why = [], []
            for row in rows[:MAX_DEALS]:
                deal, bad = vet(row, text, url,
                                base[lid].get("address"))
                if deal:
                    deals.append(deal)
                else:
                    why.append(f"{row.get('kind')}: {bad}")
            held[key] = {"read_at": TODAY, "lid": lid, "doc": kind, "url": url,
                         "deals": deals, "refused": why}
            kept_total += len(deals)
            name = (base[lid].get("name") or lid)[:32]
            mark = f"** {len(deals)} deal(s)" if deals else "--"
            print(f"  {lid:<8} {name:<34} {kind:<6} {mark}")
            if args.show:
                for d in deals:
                    dows = ",".join(str(w["dow"]) for w in d["windows"])
                    print(f"           {d['type']:<14} dow {dows:<16} "
                          f"{d['windows'][0]['start']}-{d['windows'][0]['end']}  "
                          f"{len(d['items'])} item(s)")
                    print(f"             {d['source']['quote'][:110]!r}")
            refused += [(lid, name, w) for w in why]
        save(held, SIDECAR)

    print(f"\n{kept_total} deal(s) grounded -> {SIDECAR}")
    for lid, name, w in refused[: args.rejects]:
        print(f"  REFUSED {name[:26]:<28} {w[:96]}")
    print("Now run: python ingest/read_menus_llm.py build")


def save(doc, path):
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True, ensure_ascii=False)
    os.replace(tmp, path)


# ---- build -----------------------------------------------------------------


def build_cmd(args):
    """Re-check every grounded deal against the document ON DISK and write the
    venue rows build_bundles merges. No model runs here: the sidecar was
    verified when it was written, the page may have changed since, and a file on
    disk is the easiest thing in this pipeline to be wrong about."""
    if not os.path.exists(SIDECAR):
        sys.exit(f"{SIDECAR} does not exist -- run `ask` first")
    side = json.load(open(SIDECAR, encoding="utf-8"))
    base = json.load(open(BASE, encoding="utf-8"))
    scripts = transcripts_by_slug()

    by_lid, stale = {}, 0
    for key, rec in sorted(side.items()):
        lid = rec.get("lid")
        if lid not in base or not rec.get("deals"):
            continue
        live = {url: text for _, url, text in documents(lid, base, scripts)}
        text = live.get(rec.get("url"))
        if text is None:
            stale += len(rec["deals"])
            continue
        for deal in rec["deals"]:
            if not in_source(deal["source"]["quote"], text):
                stale += 1
                continue
            # Re-checked here too, so a row already on the sidecar from before
            # this guard existed is dropped rather than shipped once more.
            if (another_towns_row(deal["source"].get("heading") or "",
                                  base[lid].get("address"))
                    or another_towns_row(deal["source"]["quote"],
                                         base[lid].get("address"))):
                stale += 1
                continue
            by_lid.setdefault(lid, []).append({k: v for k, v in deal.items()
                                               if not k.startswith("_")})

    venues, dropped = [], 0
    for lid, deals in sorted(by_lid.items()):
        b = base[lid]
        deals = dedupe_deals(deals)
        errs = validate_food_combo_count(deals)
        if errs:
            deals = [d for d in deals if d["type"] != "food_combo"]
            print(f"  {b['name'][:34]:<36} {errs[0]} -- combos dropped")
        if not deals:
            dropped += 1
            continue
        venues.append({
            "id": ed.slug(b.get("name", ""), b.get("address", "")),
            "lid": lid,
            "name": b.get("name", ""),
            "plcb_name": b.get("plcb_name", ""),
            "address": b.get("address", ""),
            "zone_id": b.get("zone_id", ""),
            "license_type": b.get("license_type", ""),
            "website": b.get("website", ""),
            "deals": deals,
        })
        if args.show:
            kinds = ", ".join(f"{d['type']}({len(d['items'])})" for d in deals)
            print(f"  {b['name'][:34]:<36} {kinds}")

    save({"_comment": "Deals a MODEL read off whole pages and menu transcripts "
                      "(ingest/read_menus_llm.py). Every quote re-checked against "
                      "the document on disk by `build`. Grounding and the PA "
                      "validators are in that file.",
          "as_of": TODAY, "venues": venues}, OUT)
    print(f"\n{sum(len(v['deals']) for v in venues)} deal(s) across {len(venues)} "
          f"venue(s) -> {OUT}")
    if stale:
        print(f"  {stale} deal(s) dropped: the document no longer says it")
    if dropped:
        print(f"  {dropped} venue(s) left with nothing publishable")


def dedupe_deals(deals):
    """One deal per (kind, days, clock); the richest reading of it wins.

    The same happy hour is routinely stated on three pages of one site -- the
    home page, the menu and the specials page -- and three identical cards is
    not three deals.
    """
    best = {}
    for d in deals:
        key = (d["type"], tuple(sorted(w["dow"] for w in d["windows"])),
               d["windows"][0]["start"], d["windows"][0]["end"])
        held = best.get(key)
        if held is None or len(d["items"]) > len(held["items"]):
            best[key] = d
    # Then one deal per (kind, item list). A venue that runs the same happy-hour
    # menu at two different times states it as two blocks -- il Granaio's
    # "TUESDAY - FRIDAY 4PM - 6:30PM" and "SATURDAY & SUNDAY 2PM - 4:30PM" over
    # one price list -- and that is one deal with two windows, not two cards'
    # worth of the same twelve items. Both quotes are kept, joined the way
    # crawl_sites joins the lines of a section, so each window still says where
    # it was read.
    merged = {}
    for d in sorted(best.values(), key=lambda d: (d["type"], d["windows"][0]["start"])):
        key = (d["type"], tuple(sorted(i["label"].lower() for i in d["items"])))
        held = merged.get(key)
        if held is None:
            merged[key] = d
            continue
        held["windows"] += [w for w in d["windows"] if w not in held["windows"]]
        if d["source"]["quote"] not in held["source"]["quote"]:
            held["source"]["quote"] += " / " + d["source"]["quote"]
    out = list(merged.values())
    for d in out:
        d["windows"].sort(key=lambda w: (w["dow"], w["start"]))
    return sorted(out, key=lambda d: (d["type"], d["windows"][0]["start"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ask")
    p.add_argument("--lids", help="file of licence ids, one per line")
    p.add_argument("--zone", help="every venue in this zone id")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--force", action="store_true", help="re-read documents on file")
    p.add_argument("--show", action="store_true")
    p.add_argument("--rejects", type=int, default=0)
    p.set_defaults(fn=ask_cmd)
    p = sub.add_parser("build")
    p.add_argument("--show", action="store_true")
    p.set_defaults(fn=build_cmd)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args.fn(args)


if __name__ == "__main__":
    main()
