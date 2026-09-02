#!/usr/bin/env python3
"""Crawl the discovered venue sites and keep only the text that names a deal.

    python ingest/crawl_sites.py --limit 25        # a bounded first pass
    python ingest/crawl_sites.py                   # the whole frontier
    python ingest/crawl_sites.py --zone west_chester

Reads data/venue_sites.json, writes data/crawl_hits.json -- one entry per venue
that published something, holding the URL, the fetch date and the *quoted*
sentences. It does not write deals. Turning a quote into a deal is a judgement
call about what a venue actually claimed, and the corpus rule is that a deal
carries the source text it came from, so extraction stays a separate reviewed
step over this file.

Politeness is not optional here: these are small restaurants on shared hosting.
robots.txt is honoured per host, one request at a time, with a delay between
them, and at most a handful of pages per venue.
"""

import argparse
import collections
import hashlib
import html as html_mod
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import unicodedata
import urllib.request
from html.parser import HTMLParser
import urllib.robotparser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITES = os.path.join(REPO, "data", "venue_sites.json")
BASE = os.path.join(REPO, "data", "venue_base.json")
OUT = os.path.join(REPO, "data", "crawl_hits.json")
# The visible text of every page that turned out to be about a happy hour, kept
# so something can READ it later without spending the venue's bandwidth again.
# crawl_hits.json holds only the lines a regex already matched, which is exactly
# the problem: a page the rules threw away is invisible to everything
# downstream, including a model. Sullivan's whole food menu -- four price bands,
# nineteen dishes -- sat on a page we had held for weeks. See
# ingest/read_pages_llm.py, which is the reader this cache exists for.
PAGES = os.path.join(REPO, "data", "pages")


def frontier():
    """Every venue whose website we hold -- from BOTH places we hold one.

    venue_sites.json is the OSM/guess join. venue_base.json takes a website
    from Google Places OR that join, so Places can hand us a site OSM never
    had, and those venues were never queued at all: they reported as
    'never-crawled', which read exactly like a venue with no website. In King
    of Prussia that was The Cheesecake Factory, Tommy Bahama and Wegmans --
    sites we already had on file and had simply never asked for.

    The union, and where BOTH have a URL and they differ, both are kept --
    venue_sites.json's as the start, base's in `also_urls`. Neither source is
    reliably the better one, which is the whole reason not to choose: bartaco's
    good page is base's (/location/kop/ states 'weekdays 3-6pm'; sites' URL is
    a 29-line shell), and Pizzeria Vetri's good page is sites'
    (/location/king-of-prussia/, against base's bare root). They disagree for
    17 venues and a rule picking either source loses the other half.
    """
    sites = json.load(open(SITES, encoding="utf-8"))
    base = json.load(open(BASE, encoding="utf-8"))
    for lid, v in base.items():
        site = v.get("website")
        if not site:
            continue
        if lid not in sites:
            sites[lid] = {"name": v["name"], "osm_name": None,
                          "address": v.get("address", ""),
                          "zone_id": v.get("zone_id"), "website": site}
        elif site != sites[lid]["website"]:
            sites[lid] = {**sites[lid], "also_urls": [site]}
    return sites

UA = "happy-hour-finder/0.1 (+https://paulrenzi.github.io/happy-hour-finder/)"
DELAY = 2.0       # seconds between requests to the same host
PAGE_CAP = 4      # homepage + up to three promising links
DOC_CAP = 2       # menu PDFs a happy-hour page links, budgeted separately
TIMEOUT = 20

# Phase 0 found the deal is as often on a /specials or /menu page as the home
# page, and that some sites name it only in a nav link.
LINK_WORDS = re.compile(
    r"happy.?hour|special|deal|drink|bar.?menu|menu|events?|promo", re.I)
# A hit has to name the thing. 'Happy' alone matches 'Happy Birthday parties'.
DEAL_RE = re.compile(
    r"happy hour|happy-hour|drink special|daily special|late night menu|"
    r"industry night|power hour|social hour|bar special|half.?price|"
    r"\$\d+(?:\.\d\d)?\s*(?:draft|drafts|beer|wells|well drinks|wine|cocktails?|"
    r"apps|appetizers|margaritas|shots)", re.I)
# Sentences worth keeping alongside the match: a window or a price. '4p' counts
# -- a bar writes the hour that way as readily as '4pm', and CONTEXT_RE not
# knowing it is why Pepperoncini's quote came back as 'Happy Hour / mon - fri /
# $2 OFF': the day line and the price line were picked up and the line that
# actually held the window, '4p - 6p', was invisible.
TIME_CONTEXT_RE = re.compile(r"\d{1,2}(?::\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.|[ap]\b)", re.I)
CONTEXT_RE = re.compile(
    TIME_CONTEXT_RE.pattern + r"|\$\d|mon|tue|wed|thu|fri|sat|sun", re.I)
# A priced line on a menu document: a name, then a price. Only ever applied to a
# document a happy-hour page linked as its menu -- on an ordinary page this
# matches the dinner menu, which is why it is not part of DEAL_RE.
MENU_ITEM_RE = re.compile(r"[A-Za-z].{2,60}?\s\$\s?\d{1,3}(?:\.\d\d)?\s*$")
# The same line with the price written FIRST -- '$4.50 Draft Beer', '$6.50
# Sangrias (White or Red)'. MENU_ITEM_RE is anchored to the end of the line and
# cannot see this form at all, so a venue that prices its menu price-first was
# read as having published nothing: Paladar has six priced lines on its own
# happy-hour page and exactly one of them, the one DEAL_RE happened to match on
# the word 'Draft', was ever stored. The extractor grew the mirror of this last
# session (TRAILING_PRICE_RE); the crawler never did, so the lines it needed
# were being thrown away one step earlier. Scoped to `loose` exactly as
# MENU_ITEM_RE is -- same containment, same safety argument.
LEADING_ITEM_RE = re.compile(r"^\$\s?\d{1,3}(?:\.\d\d)?\s+[A-Za-z].{2,60}$")
# A price sitting on a line of its own. A themed menu puts the item name and its
# price in separate blocks, so visible_text emits '$ 5' with nothing attached:
# Bloom Southern Kitchen's happy-hour page yields thirty of these and not one
# names the food it belongs to. MENU_ITEM_RE cannot match them and DEAL_RE
# should not, so on its own this line is correctly worthless -- the fix is to
# keep it WITH its neighbours and let the reviewed price pass associate them,
# which it can only do over text the crawl actually kept.
BARE_PRICE_RE = re.compile(r"^\$\s?\d{1,3}(?:\.\d\d)?$")

# An image on a happy-hour page whose filename names the thing. Malbec exports
# its happy-hour menu from a PDF to a single JPG and posts that: the page has
# real hours in text and NOT ONE dollar sign anywhere in its HTML, so the venue
# reads as covered while its entire menu is invisible. No parser fixes that --
# the words are pixels. The crawl records the URL; reading it is a separate,
# reviewed vision pass, exactly as a customer's photo submission is.
# A document whose own filename says it is the happy hour. Only ever used to
# decide whether a PDF is worth one extra request; what it then yields is read
# under the same menu_doc containment every linked menu is.
HH_DOC_RE = re.compile(
    r"(?:happy.?hour|happyhour|(?:^|[/\-_])hh[-_.]|drink.?menu|bar.?menu|specials?)"
    r"[^/]*\.pdf($|\?)", re.I)

MENU_IMG_RE = re.compile(
    r"(?:happy.?hour|_hh_|-hh-|specials?|drink.?menu|bar.?menu)[^\"'\s]*"
    r"\.(?:jpe?g|png|webp)", re.I)
IMG_CAP = 3

MARKUP_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\xa0]+")


# A close tag that ends a visible line. Matches the set the old regex pass used,
# so the text a page yields is unchanged by moving to a real parser.
BREAK_CLOSE = frozenset("p div li tr h1 h2 h3 h4 h5 h6".split())
VOID_TAGS = frozenset("br img hr input meta link source col area base embed "
                      "param track wbr".split())
DROPPED_TAGS = frozenset(("script", "style", "noscript"))
# A menu writes an item as NAME then description, and the only thing separating
# them is that the venue emphasised the name: Paladar's snacks are
# '<em>Street Tacos (2)</em> choice of Braised Beef ...'. Both halves land in one
# visible line, so without this the label is the whole sentence and no rule can
# find where the dish's name stops. The venue already answered that in markup.
EMPH_TAGS = frozenset("em strong b i".split())


class _Lines(HTMLParser):
    """visible_text's line split, plus the element each line was found inside.

    The lines are what they always were. What is new is `stacks`: for line k,
    the chain of open elements the line's first text sits in, as opaque ids.
    That chain is the only record of which lines a page put in ONE box -- and
    on a menu, one box is one item. See item_beside().
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.nid, self.dropped = [], 0, 0
        self.buf, self.buf_stack = [], None
        self.lines, self.stacks, self.emph = [], [], []
        self.em_depth, self.em_buf, self.em_first = 0, [], None

    def _flush(self):
        line = WS_RE.sub(" ", "".join(self.buf)).strip()
        if line:
            self.lines.append(line)
            self.stacks.append(tuple(self.buf_stack or ()))
            self.emph.append(WS_RE.sub(" ", self.em_first or "").strip())
        self.buf, self.buf_stack = [], None
        self.em_buf, self.em_first = [], None

    def handle_starttag(self, tag, attrs):
        if tag in DROPPED_TAGS:
            self.dropped += 1
            return
        if tag == "br":
            self._flush()
            return
        # A tag is a space between the words it separates, void or not; an
        # element that can hold text also opens a box lines can be inside.
        self.buf.append(" ")
        if tag in EMPH_TAGS:
            self.em_depth += 1
        if tag not in VOID_TAGS:
            self.nid += 1
            self.stack.append(self.nid)

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._flush()
        else:
            self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag in DROPPED_TAGS:
            self.dropped = max(0, self.dropped - 1)
            return
        if tag in VOID_TAGS:
            return
        self.buf.append(" ")
        if tag in EMPH_TAGS and self.em_depth:
            self.em_depth -= 1
            # Only the FIRST emphasised run of a line names the item; a page
            # that emphasises half its sentence gets nothing useful, and a run
            # later in the line is the description talking.
            if not self.em_depth and self.em_first is None:
                self.em_first = "".join(self.em_buf)
        if tag in BREAK_CLOSE:
            self._flush()
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self.dropped:
            return
        # A newline in the source is a line break here too, exactly as the
        # regex pass had it: 'Mon-Fri' and '4-6pm' are often only separated by
        # the newline the author typed.
        for k, part in enumerate(data.replace("\xa0", " ").split("\n")):
            if k:
                self._flush()
            if part.strip() and self.buf_stack is None:
                self.buf_stack = tuple(self.stack)
            if self.em_depth and self.em_first is None:
                self.em_buf.append(part)
            self.buf.append(part)

    def close(self):
        super().close()
        self._flush()


# A price does not have to be a numeral. Tommy's Tavern + Tap heads its happy
# hour food with 'EIGHT DOLLARS' and prices its drinks 'five dollar house wines'
# and 'two dollars off all draft beers' -- a complete, published happy hour menu
# with sixteen items and NOT ONE DOLLAR SIGN on the page. Every rule we have is
# anchored on '$', so the whole page read as silence.
#
# The fix is a normalisation, not another grammar: rewrite the words into the
# numeral ONCE, here, where every line of every page passes, and the shared-price
# heading rule, the priced-line rule and the dollars-off rule all reach it
# unchanged. Doing it as a fourth grammar would have meant three more places to
# get 'off' wrong.
#
# Bounded to twenty plus the round tens, because a happy hour price is a small
# number and 'a million dollars' is prose. The word must be followed by
# dollar/dollars/buck/bucks, so 'four cheese pizza' cannot become '$4 cheese'.
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50,
}
WORD_PRICE_RE = re.compile(
    r"\b(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) +
    r")\s+(?:dollars?|bucks?)\b", re.I)


def word_prices(line):
    """'EIGHT DOLLARS' -> '$8'. The line otherwise untouched.

    Deliberately leaves the rest of the line alone, including a trailing 'off',
    so 'two dollars off all draft beers' becomes '$2 off all draft beers' and
    lands on AMOUNT_OFF_RE exactly as a page that typed it that way would.
    """
    return WORD_PRICE_RE.sub(
        lambda m: "$%d" % NUMBER_WORDS[m.group(1).lower()], line)


def text_lines_emph(html):
    """text_lines(), plus the first emphasised run of each line.

    Kept separate from text_lines() only so the older two-value signature and
    its callers stay as they were; both come off ONE parse of the page.
    """
    p = _parse(html)
    return p.lines, p.stacks, p.emph


def _parse(html):
    p = _Lines()
    try:
        p.feed(html)
        p.close()
    except Exception:
        # The regex pass this replaced could not raise, so a page that the
        # parser chokes on must not now take the whole crawl with it. Keep the
        # lines read so far -- a partial page is what a truncated fetch has
        # always given us, and it is handled everywhere downstream.
        p._flush()
    # One chokepoint: every line every caller ever sees passes through here, so
    # a worded price is a numeral before any rule looks at it.
    p.lines = [word_prices(ln) for ln in p.lines]
    p.emph = [word_prices(e) for e in p.emph]
    return p


def text_lines(html):
    """The visible lines and, for each, the element chain it was found in.

    Markup out, structure preserved as line breaks -- a <br> is a line break in
    a happy-hour block, and joining those lines glues 'Mon-Fri' to '4-6pm'.
    """
    p = _parse(html)
    return p.lines, p.stacks


def visible_text(html):
    return "\n".join(text_lines(html)[0])


# How far up the tree a bare price may look for the box it shares with its item,
# and how many lines that box may hold. A menu item is a small element: a name,
# maybe a description, a price. Walking further finds the whole menu, where the
# nearest line is not the item -- so both caps refuse rather than reach, and the
# price stays unpaired.
ITEM_LEVELS = 4
ITEM_BOX_LINES = 8


def _labelled(line):
    return (re.search(r"[A-Za-z]{3}", line) and not BARE_PRICE_RE.match(line)
            and len(line) <= 80)


def item_beside(i, lines, stacks):
    """The item a bare price on line i belongs to, or None.

    '$8' and its dish are on separate lines and each is worthless alone, so the
    price has to be joined to a neighbour -- but WHICH neighbour differs by
    page, and getting it wrong publishes a wrong price for a real bar:

        CO-OP    'Deviled Eggs / with capers and everything spice / $ 8'
                 -- the item is ABOVE. The Wings below it are $12.
        Chili's  '$3 / Bud Light 16 oz'
                 -- the item is BELOW.

    Neither order is a rule, and no amount of looking at the two text lines can
    tell them apart. The page can: both venues put the price and its item in
    ONE element and the next item in another. CO-OP's is an <li class=menu-item>
    holding name, description and price; Chili's is a <div> holding the price
    and the three beers it covers. So the answer is not 'above' or 'below', it
    is 'inside the same box' -- read off the tree, which is why the pairing has
    to happen here at crawl time and cannot be recovered later from the text.

    Returns the first other labelled line in that box, in page order: CO-OP's
    box begins with 'Deviled Eggs', Chili's with the price itself and then
    'Bud Light 16 oz'.
    """
    stack = stacks[i] if i < len(stacks) else ()
    for depth in range(len(stack), max(0, len(stack) - ITEM_LEVELS), -1):
        anc = stack[:depth]
        lo = hi = i
        while lo - 1 >= 0 and stacks[lo - 1][:depth] == anc:
            lo -= 1
        while hi + 1 < len(stacks) and stacks[hi + 1][:depth] == anc:
            hi += 1
        if hi == lo:
            continue                     # the price alone; open the box wider
        if hi - lo + 1 > ITEM_BOX_LINES:
            return None                  # too big to be one item -- refuse
        rest = [lines[j] for j in range(lo, hi + 1) if j != i and _labelled(lines[j])]
        return rest or None
    return None


# The page's own heading, which is what unlocks the looser priced-line rules on
# a page whose URL says nothing. See hh_sections().
# A venue does not have to call it a "happy hour". Morton's brands its as
# /event/power-hour/ and bartaco calls its /kophightidehour/ -- both were read
# as ordinary pages, so the loose price rules never unlocked and bartaco's menu
# IMAGE, the only place its menu exists, was never collected. What all of them
# do say is HOUR (Paul, 2026-09-01: "make sure we are grabbing anything with
# 'hour' in the name"). 'hours' is excluded deliberately -- /hours is the
# opening-hours page, not a deal -- and the match is against the PATH only, so
# a venue merely named Hourglass Tavern does not turn its whole site into a
# happy-hour menu.
HH_PATH_RE = re.compile(r"hour(?!s)", re.I)


def url_names_hh(url, depth=1):
    """True when the venue's own URL calls this page an hour or a special.

    'special' still needs depth: a homepage is not a specials page, and
    /daily-specials prices are Monday's, not the happy hour's. An HOUR in the
    path is the venue naming the thing at any depth -- bartaco's seed URL IS
    /kophightidehour/, and requiring depth>1 was why it read as an ordinary page.
    """
    path = urllib.parse.urlsplit(url).path + "?" + (urllib.parse.urlsplit(url).query or "")
    return bool(HH_PATH_RE.search(path)
                or (depth > 1 and re.search(r"happy.?hour|special", url, re.I)))


def page_is_hh(url):
    """True when the venue's own URL says this whole PAGE is the happy hour.

    Stricter than url_names_hh(): an HOUR in the path only. '/specials' is not
    granted this -- '/daily-specials' prices are Monday's, and the quotes()
    docstring is explicit that containment is what lets a quote travel to
    another page's schedule.

    What it buys is the section. hh_sections() looks for a happy-hour HEADING,
    and a page that IS the happy-hour menu often has none -- Sullivan's
    /menus/happyhour-food-drink/ marked exactly one line, so heading_prices()
    refused all four of its price bands and twenty-six dishes stayed unread on
    a page we had fetched. A page the venue titled the happy hour is one whose
    every line is inside it.
    """
    return bool(HH_PATH_RE.search(urllib.parse.urlsplit(url).path))


HH_HEADING_RE = re.compile(r"happy\s*hour|social hour|power hour|bar bites", re.I)
# A heading that divides a happy hour up rather than ending it. CO-OP's happy
# hour is an <h2> and so are its own 'Food Specials' and 'Drink Specials', so
# rank cannot tell a subdivision from the next menu -- the WORD can. Closing on
# the next heading of any rank closed CO-OP's section on its own first
# subdivision and harvested one line; this list is what may appear inside.
# Anything not on it closes the section, so an unrecognised heading fails the
# section SHORT, which is the safe direction: a section that runs on does not
# add noise, it publishes a wrong price.
# The nouns are written singular but a menu writes them PLURAL -- Paladar's
# happy hour is subdivided by a heading that says 'DRINKS', and `drink` does not
# match it, so the section closed on the venue's own subheading and all six of its
# prices sat one line outside it. The asymmetry was accidental, not a safety
# margin: `snack` and `bite` already survive in the plural through the trailing
# branch below, and `drink` did not. The two branches now agree.
SUBDIVISION_RE = re.compile(
    r"^(?:food|drink|bar|beer|wine|cocktail|liquor|spirit|snack|bite|share|"
    r"small|sip|draft|draught|bottle|can|shot|feature|select|our)s?\b|"
    r"\b(?:specials?|bites|snacks|shareables?|small plates|by the glass)\s*$",
    re.I)
HEADING_TAG_RE = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.S | re.I)
# A section with no heading below it has nothing to close it, so it is capped.
# Chili's runs 28 lines from its heading to the last price; CO-OP's is 21. 30
# clears both and still stops well short of a dinner menu.
SECTION_CAP = 30
# A fallback heading is a LINE, not a tag, so it has to look like one: short,
# few words, no price, and not a sentence. 'Join us for the best HAPPY HOUR in
# town, every day!' is prose and must not open a section -- prose naming the
# happy hour is on every restaurant page on the internet.
FALLBACK_MAX_CHARS = 40
FALLBACK_MAX_WORDS = 5
# What closes a fallback section, where there are no marked headings to close on
# at all. Chili's location page ends its happy-hour block with 'Address'.
MEAL_HEADING_RE = re.compile(
    r"^(?:.{0,20}\b)?(?:lunch|dinner|brunch|breakfast|dessert|kid|entree|"
    r"entrée|main|catering|address|location|hours of operation|contact)\b", re.I)


# A heading that is nothing but a WEEKDAY closes the happy hour. A day-of-week
# specials block is not a happy hour and its prices are not happy-hour prices:
# Revival Pizza Pub heads its Monday block 'MONDAYS' and prints '$6 margaritas'
# under it, and with nothing to close the section on, that $6 was published as a
# 4-6pm happy-hour price on every weekday. It is the CO-OP failure again -- a
# section that runs on does not add noise, it states a price the venue does not
# charge. A heading that also states a CLOCK is the happy hour's own hours line
# and still does not close it (see the closes list).
DAY_HEADING_RE = re.compile(
    r"^(?:mon|tues?|wed(?:nes)?|thur?s?|fri|sat(?:ur)?|sun)(?:day)?s?[ !:.-]*$", re.I)


def _norm(x):
    return WS_RE.sub(" ", x).strip().lower()


def marked_headings(html, lines):
    """Indices of `lines` the page marked up itself as <h1>-<h6>."""
    marked = {_norm(MARKUP_RE.sub(" ", html_mod.unescape(m.group(1))))
              for m in HEADING_TAG_RE.finditer(html)}
    marked.discard("")
    return [i for i, ln in enumerate(lines) if _norm(ln) in marked]


def hh_sections(html, text):
    """Line indices of `text` that sit inside a happy-hour section of `html`.

    This replaces the URL as the containment key. `hh_page` asked whether the
    LINK that reached the page named the happy hour, and 65 of the 84 priceless
    board cards came from a page where the answer was no while the prices sat on
    it in plain text: Chili's puts its happy hour on the LOCATION page, and
    CO-OP puts it a third of the way down /menus.

    The containment is not weakened, only re-keyed. A section opens at a heading
    that names the happy hour and closes at the next heading that names anything
    else, so the rest of the menu is as far out of reach as it was before --
    which matters more than it sounds, because CO-OP charges $8 for the deviled
    eggs at happy hour and $12 for the same dish on the Mid Day menu directly
    above it. A section that runs on does not add noise, it publishes a WRONG
    PRICE, and that is the failure this function exists to prevent.

    A heading that states a CLOCK TIME does not close the section either. It is
    the happy hour's own hours line, marked up as a heading -- Sullivan's opens
    'King Of Prussia Happy Hour Menu' and the very next heading is 'Available in
    the bar, Monday-Thursday 3pm-6pm', which closed the section on the line after
    it opened and put the whole menu out of reach. No menu is titled with a time
    range, so this cannot let the next menu in.

    A heading is an <h1>-<h6> when the page has any. When a page has none at all
    -- Chili's location pages are divs from top to bottom -- a short standalone
    line falls back into the role, and the section is capped rather than closed
    because there is no next heading to close it on. The fallback is refused the
    moment a page proves it marks its headings up: otherwise El Vez's nav strip,
    which lists 'Happy Hour' beside Lunch and Dinner, would open a section over
    the whole dinner menu. On a nav link the failure mode has to be an empty
    section, never a wrong one.
    """
    lines = text.split("\n")
    heads = marked_headings(html, lines)
    head_set = set(heads)

    def title_end(i):
        """The last line of the TITLE that opens at line i.

        A title can be several headings in a row. Tommy's Tavern + Tap sets
        'ALL NEW' / 'HAPPY HOUR' / 'at the bar.' / "3 PM TIL' 6 PM" as four
        consecutive headings, and 'at the bar.' -- the second half of the
        venue's own title -- closed the section on the line after it opened,
        putting a sixteen-item happy hour menu out of reach. A heading
        immediately abutting the one that opened the section is part of the same
        title, not the next menu.

        Adjacency alone is not enough to be safe, so the two headings that mean
        'a different menu starts here' still close even when they abut: a MEAL
        heading and a bare WEEKDAY. Those are the two that publish a wrong price
        when a section runs past them, and neither is ever part of a happy
        hour's own title.
        """
        j = i
        while (j + 1 in head_set
               and not DAY_HEADING_RE.match(lines[j + 1].strip())
               and not MEAL_HEADING_RE.search(lines[j + 1].strip())):
            j += 1
        return j

    if heads:
        opens = [i for i in heads if HH_HEADING_RE.search(lines[i])]
        # A subdivision of the happy hour does not end it; anything else does.
        closes = [i for i in heads
                  if (DAY_HEADING_RE.match(lines[i].strip())
                      or (not SUBDIVISION_RE.search(lines[i].strip())
                          and not HH_HEADING_RE.search(lines[i])
                          and not TIME_CONTEXT_RE.search(lines[i])))]
    else:
        def headinglike(ln):
            return (len(ln) <= FALLBACK_MAX_CHARS and "$" not in ln
                    and len(ln.split()) <= FALLBACK_MAX_WORDS
                    and not ln.rstrip().endswith((".", "!", ",", ":", ";")))
        opens = [i for i, ln in enumerate(lines)
                 if headinglike(ln) and HH_HEADING_RE.search(ln)]
        closes = [i for i, ln in enumerate(lines)
                  if headinglike(ln) and (MEAL_HEADING_RE.search(ln)
                                          or DAY_HEADING_RE.match(ln.strip()))]

    # Two happy-hour headings can nest: CO-OP's page-level 'Bar Bites & Happy
    # Hour' contains both a 'Mid Day' menu and the happy hour proper. The outer
    # one is a title, not a section -- the inner one is the venue's own, more
    # specific word for the same thing, so it wins and the outer is dropped.
    spans, starts = {}, {}
    for i in opens:
        starts[i] = title_end(i)
        spans[i] = min([j for j in closes if j > starts[i]]
                       + [i + 1 + SECTION_CAP, len(lines)])
    out = set()
    for i, stop in spans.items():
        if any(i < j < stop for j in spans):
            continue
        out |= set(range(starts[i] + 1, stop))
    return out


# A price stated ONCE, on the heading that owns a block of items. Paladar
# lists its eight happy-hour snacks under '<h2>SNACKS $7.50-7.75 each</h2>' and
# not one of them carries a dollar sign, so every rule in quotes() looked
# straight past all eight. The heading is the venue answering for the whole
# block: it gives the price AND the kind of thing. The items below it are
# priced lines that simply do not repeat the number.
SECTION_PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:\.\d\d)?)\s*(?:-|\u2013|\u2014|to)\s*\$?\s?(\d{1,3}(?:\.\d\d)?)|\$\s?(\d{1,3}(?:\.\d\d)?)")
# How many lines one priced heading may speak for. A happy-hour block is a
# short list; a longer run is a menu the heading does not really own, and
# inheriting a price down it would publish a wrong price on every line of it.
SECTION_PRICE_CAP = 12
# A heading that is NOTHING but a price. Sullivan's states its whole happy-hour
# food menu as four of these -- '$25', '$20', '$15', '$10' -- each followed by
# five or six dishes, and we published two drink lines out of twenty-six items.
# The band rule below cannot use the ordinary one: on that page every DISH NAME
# is an <h3> too, so "stop at the next heading" stopped at the first dish, and
# the price sits in a sibling column to its items rather than around them, so
# the box test broke immediately as well. A bare-price heading is not a section
# title, it is a price band, and what it owns is the marked headings after it.
BARE_HEADING_PRICE_RE = re.compile(
    r"^\$\s?\d{1,3}(?:\.\d\d)?(?:\s*(?:-|–|—|to)\s*\$?\s?\d{1,3}(?:\.\d\d)?)?"
    r"(?:\s*(?:each|ea\.?|\+))?$", re.I)
# An unemphasised line has to stand as its own label, so it has to be short
# enough to BE one. A sentence is not a label.
SECTION_LABEL_MAX = 40
TITLE_RUN_RE = re.compile(r"^(?:(?:[A-Z]\S*|\(\d+\)|&)(?:\s+|$)){1,6}")


def item_label(line, emphasised):
    """The item's name on a menu line, or "" if the line does not offer one.

    Two marks, both the venue's own: the run it EMPHASISED, and failing that the
    leading run of CAPITALISED words. Neither is a guess about where a name ends
    -- when the page makes neither mark, nothing is returned and the line is left
    alone, because a sentence is not a label.
    """
    for cand in (emphasised, (TITLE_RUN_RE.match(line) or [""])[0]):
        cand = (cand or "").strip(" -'")
        if _labelled(cand) and len(cand) <= SECTION_LABEL_MAX:
            return cand
    return ""


def heading_prices(html, text, hh_lines, stacks=None):
    """{line index -> (heading index, low, high)} for lines a PRICED heading owns.

    Only inside a happy-hour section, only under a heading the page marked up
    itself, and only for lines stating no price of their own -- a line with its
    own number answers for itself and is never overridden. The run stops at the
    next heading, at the end of the section, or at the cap, whichever comes first
    -- and it never leaves the heading's own BOX. Paladar's snack heading is
    followed by its eight snacks and then by two stray words, 'Sweet' and
    'Flavors', from a widget further down the page; both sit inside the section
    and neither is a snack. The page already separates them: the heading and its
    eight items share one element, the widget does not. This is the same
    one-box-is-one-item reading item_beside() does for a bare price.
    """
    lines = text.split("\n")
    heads = marked_headings(html, lines)
    headset = set(heads)
    out = {}
    for i in heads:
        # The heading must be INSIDE a happy hour. hh_sections() puts every line
        # a happy-hour heading owns into the set, so a subdivision heading like
        # 'SNACKS $7.50-7.75 each' is in it and the next menu's heading is not.
        if i not in hh_lines:
            continue
        m = SECTION_PRICE_RE.search(lines[i])
        if not m:
            continue
        lo = float(m.group(1) or m.group(3))
        hi = float(m.group(2) or lo)
        if not 0 < lo <= hi <= 99:
            continue
        # The element holding the heading. Every line the heading speaks for
        # has to be inside it.
        box = None
        if stacks and i < len(stacks) and len(stacks[i]) >= 2:
            box = stacks[i][-2]
        # A price band: the heading says the price and NOTHING else, so its
        # items are the headings that follow, and it runs to the next PRICED
        # heading rather than to the next heading of any kind.
        if BARE_HEADING_PRICE_RE.match(lines[i].strip()):
            n = 0
            for j in range(i + 1, len(lines)):
                if j not in hh_lines or n >= SECTION_PRICE_CAP:
                    break
                if j in headset and SECTION_PRICE_RE.search(lines[j]):
                    break
                # Only the lines the page itself marked as headings. The
                # description under each dish is a <p>, and reading those as
                # items publishes half a sentence at the band's price.
                if j not in headset or not lines[j].strip():
                    continue
                out[j] = (i, lo, hi)
                n += 1
            continue
        n = 0
        for j in range(i + 1, len(lines)):
            if j in headset or j not in hh_lines or n >= SECTION_PRICE_CAP:
                break
            if box is not None and box not in (stacks[j] if j < len(stacks) else ()):
                break
            if "$" in lines[j]:
                continue
            out[j] = (i, lo, hi)
            n += 1
    return out


def quotes(text, menu_doc=False, hh_page=False, hh_lines=frozenset(), stacks=None,
           head_prices=None, emph=None, mark_hh=False):
    """The matched lines, plus a neighbour when the match itself has no time.

    menu_doc is for a document we reached BECAUSE a happy-hour page linked it as
    its menu -- the priced item lines are then the point of the document, and
    DEAL_RE will not match them: 'CAJUN NACHOS $8' names no deal word, and a
    dollar amount only counts for DEAL_RE when a drink word follows it. Widening
    DEAL_RE itself would let every dinner entree on every site through. So the
    looser rule is scoped to the document the venue itself called its happy
    hour, which is the answer stored on the record rather than guessed at here.

    hh_page is the same allowance for a PAGE the venue called its happy hour --
    /happy-hour, /specials. The containment is identical and it is the whole
    safety argument: on an arbitrary page these rules would harvest the dinner
    menu, but a page the venue titled 'Happy Hour' is one whose priced lines ARE
    the deal. 96 of the 179 venues that reached such a page came back with no
    price at all, and a sample showed the commonest reason was not that the page
    was silent -- it was that the price and the item were on separate lines and
    each was worthless alone.

    hh_lines is the same allowance again, granted per LINE instead of per page,
    to the lines a happy-hour HEADING owns -- see hh_sections(). The URL key
    could only ever answer for a whole page, and most venues do not give their
    happy hour a page.
    """
    lines = text.split("\n")
    out, seen = [], set()
    # Which of the returned quotes came from INSIDE the venue's own happy hour.
    # See mark_hh in the caller: this is the containment the crawl performed,
    # recorded so the extractor does not have to re-derive it from a URL.
    contained = {}
    for i, ln in enumerate(lines):
        inside = i in hh_lines
        loose = menu_doc or hh_page or inside
        bare = (hh_page or inside) and BARE_PRICE_RE.match(ln)
        owned = (head_prices or {}).get(i)
        if owned:
            head, lo, hi = owned
            # See item_label(): the venue's own marks say where the dish's
            # name ends, and when it makes none the line is left alone.
            label = item_label(ln, emph[i] if emph and i < len(emph) else "")
            if not label:
                continue
            price = "$%.2f" % lo + ("-%.2f" % hi if hi != lo else "")
            # The heading rides along, unchanged, because it is what says both
            # the price and the KIND of thing -- 'SNACKS' is how a guacamole is
            # known to be food without the noun list having to know the word.
            # Both halves are the venue's own text, in the venue's own order.
            q = lines[head] + " / " + price + " " + label
            if q not in seen:
                seen.add(q)
                out.append(q)
                contained[q] = True
            continue
        if (not DEAL_RE.search(ln) and not bare
                and not (loose and (MENU_ITEM_RE.search(ln)
                                   or LEADING_ITEM_RE.search(ln)))):
            continue
        if len(ln) > 400:
            continue
        block = [ln]
        if bare:
            box = item_beside(i, lines, stacks) if stacks else None
            if box:
                # The page said which lines are one item, so the quote can say
                # it too: the price first and ITS item next to it, which is the
                # only order the price pass will read. Everything else in the
                # box follows as description.
                block = ["$" + ln.lstrip("$ ") + " " + box[0]] + box[1:]
            else:
                # No tree to ask, or a box too big to be one item. Keep both
                # neighbours in page order and pair NEITHER: the ordering is not
                # stable -- CO-OP prints the price below its dish, Chili's above
                # it -- and naming the wrong one is a wrong price on a real bar's
                # card. A glued quote is deliberately unreadable to the price
                # pass, so the venue stays unpriced, which is the correct answer
                # to a question this page has not answered.
                def label(j):
                    l = lines[j] if 0 <= j < len(lines) else ""
                    return l if (re.search(r"[A-Za-z]{3}", l)
                                 and not BARE_PRICE_RE.match(l)
                                 and len(l) <= 80) else None
                block = [x for x in (label(i - 1), ln, label(i + 1)) if x]
        # A heading ('HAPPY HOUR') is frequently its own line, with the window
        # on the next one; keeping only the match would drop the entire deal.
        #
        # Two slots, and the window gets first refusal on them: a day line and
        # a price line were filling both while the hours sat just below, and the
        # venue was then dropped for stating no schedule. Neither the span nor
        # the slot count moved -- reaching further down the page pulled in the
        # NEXT block's hours instead (Fogo de Chao's '$6 Beers' line acquired
        # the dining room's 3:00-9:30, which is not a happy hour and fails the
        # four-hour cap), so only the ordering within the slots changed.
        if not bare and not CONTEXT_RE.search(ln):
            near = lines[i + 1:i + 4]
            ctx = [l for l in near if CONTEXT_RE.search(l)]
            timed = [l for l in ctx if TIME_CONTEXT_RE.search(l)]
            keep = (timed + [l for l in ctx if l not in timed])[:2]
            # Page order, so 'mon - fri' still reads before '4p - 6p'.
            block += [l for l in near if l in keep]
        q = " / ".join(block)[:400]
        if q not in seen:
            seen.add(q)
            out.append(q)
            # Deliberately NOT `loose`. `loose` includes hh_page, which is the
            # URL saying 'special' -- and '/daily-specials' is such a URL while
            # its prices are Monday's, not the happy hour's. Revival Pizza Pub
            # published '$6 margaritas' as a weekday 4-6pm price on that basis.
            # A quote may travel to another page's schedule only when the venue
            # put it inside a happy-hour SECTION, or inside a menu the venue's
            # own happy-hour page linked.
            contained[q] = bool(menu_doc or inside)
    out = out[: 24 if (menu_doc or hh_page or hh_lines) else 12]
    if mark_hh:
        return [{"quote": q, "hh": contained.get(q, False)} for q in out]
    return out


def menu_images(html, page_url):
    """Image URLs on this page that name themselves a happy-hour or drinks menu.

    Filename only. Alt text and surrounding copy were both tried and both let
    the page furniture through -- a hero shot in a <div> captioned 'Happy Hour'
    is a photograph of people drinking, not a menu. A venue that exports its
    menu to an image names the file for what it is.
    """
    out, seen = [], set()
    pat = r'''(?:src|href|data-src)=(['"])(.+?)\1'''
    for m in re.finditer(pat, html, re.I):
        href = html_mod.unescape(m.group(2))
        if not MENU_IMG_RE.search(href):
            continue
        full = urllib.parse.urljoin(page_url, href).split("#")[0]
        # A theme emits the same upload at six widths ('-300x150', '-1024x512');
        # they are one menu, and the largest is the only readable one.
        key = re.sub(r"-\d{2,4}x\d{2,4}(?=\.\w+$)", "", full)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out[:IMG_CAP]


def robots_for(base, cache):
    """The host's robots.txt, fetched under a deadline.

    RobotFileParser.read() calls urlopen with no timeout at all, so a host that
    accepts the connection and then never answers does not stall for TIMEOUT
    seconds -- it stalls forever, and it takes the whole run with it. One such
    host held a 64-venue crawl for ten minutes with no output, which from the
    outside is indistinguishable from slow progress. So fetch it here, bounded,
    and hand the lines to the parser. The 401/403 = 'stay out entirely' rule
    read() applies is kept, because that is a real answer, not a failure.
    """
    if base not in cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(urllib.parse.urljoin(base, "/robots.txt"))
        rp.unreadable = None
        for attempt in (0, 1):
            try:
                req = urllib.request.Request(rp.url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
                    rp.parse(fh.read(200_000).decode("utf-8", "replace").splitlines())
            except urllib.error.HTTPError as e:
                if e.code not in (401, 403):
                    rp = None
                    break
                # 401/403 is the convention for 'stay out entirely' and it is
                # still obeyed -- but it is ALSO what a WAF hands any client
                # that is not a browser, and that verdict was being written
                # into crawl_hits.json as if the venue had said it. 210 of 886
                # venues read as blocked; re-checking eight of them later, all
                # eight served a robots.txt that allows us outright. So retry
                # once before believing it, and record the shape of the answer
                # so a bad moment is never again mistaken for a directive.
                if attempt == 0:
                    time.sleep(DELAY)
                    continue
                rp.disallow_all = True
                rp.unreadable = e.code
            except Exception:  # noqa: BLE001 -- an unreadable robots.txt is not a ban
                rp = None
            break
        cache[base] = rp
    return cache[base]


def allowed(url, cache):
    base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))
    rp = robots_for(base, cache)
    return rp.can_fetch(UA, url) if rp else True


def refusal(url, cache):
    """Why allowed() said no, in the words of what actually happened.

    A page skipped because the host would not serve its robots.txt is not the
    same finding as a page the host told us to stay off, and crawl_hits.json is
    read as evidence -- 'robots.txt disallows us' was carried into a handoff as
    a property of four venues that in fact allow us.
    """
    base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))
    code = getattr(robots_for(base, cache), "unreadable", None)
    return (f"robots.txt unreadable ({code}), treated as disallow"
            if code else "robots.txt disallows")


def pdf_text(blob):
    """The text of a PDF menu, or '' if it cannot be read.

    A scanned-image menu yields nothing here and that is the correct answer:
    no text means no quote means no deal, rather than a guess about pixels.
    """
    try:
        import io

        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(blob))
        # A drinks menu is one or two pages; a 60-page franchise document is not
        # this venue's happy hour and is not worth the parse.
        return "\n".join(p.extract_text() or "" for p in reader.pages[:6])
    except Exception:  # noqa: BLE001 -- an unreadable menu is not a crawl failure
        return ""


class _Plain:
    """The subset of a requests response get() reads, filled in by urllib."""

    def __init__(self, status_code, headers, content):
        self.status_code, self.headers, self.content = status_code, headers, content
        self.encoding = self.apparent_encoding = None

    @property
    def text(self):
        return self.content.decode(self.encoding or "utf-8", "replace")


def urllib_get(url):
    """The same request, same UA, issued by urllib instead of requests.

    Founding Farmers, Stable 12 and a long tail of others answer 403 to
    requests/urllib3 and 200 to urllib for the identical URL and the identical
    User-Agent -- it is not our identity being refused, it is the shape of the
    connection urllib3 makes. Cycling headers does not move it (Accept,
    Accept-Encoding, Connection all tested, all 403). So this is not a browser
    disguise and not a robots bypass: robots.txt is still fetched and still
    obeyed above, and we still say who we are. It is only a second client for
    the same polite request.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
        # requests hands back a case-insensitive header map and every caller
        # here asks for 'content-type' in lower case; a plain dict answers None
        # to that and the page is discarded as '200 ?' -- a fetch that worked,
        # recorded as a failure.
        headers = {k.lower(): v for k, v in fh.headers.items()}
        return _Plain(fh.status, headers, fh.read(2_000_000))


# A page whose HTML holds no page. The Cheesecake Factory publishes its King of
# Prussia happy hour at menu.thecheesecakefactory.com/pa/king-of-prussia-46/
# happy-hour/ -- 13KB of Laravel shell, ELEVEN visible lines, a Vite bundle and
# no API behind it that answers without a browser. Every reader in this file
# returns nothing from it, correctly, because there is nothing there to read.
#
# So the page is RENDERED, and only then read -- by the same readers, with the
# same containment and the same validators. Nothing is trusted differently for
# having come through a browser; it is the same fetch with the JavaScript run.
#
# Bounded on purpose, because it is ~40x the cost of a fetch: only a page whose
# URL names an HOUR (page_is_hh) and which came back with almost no text. That
# is the shape that cannot be anything BUT a shell -- a page we read in full and
# which says nothing about a happy hour is a different answer, and rendering it
# was already measured at zero yield for King of Prussia (2026-09-01).
RENDER_LINE_FLOOR = 25
RENDER_CAP = 40          # pages per run
_render = {"on": False, "used": 0, "pw": None,
           "browser": None}


def render_wanted(url, lines):
    return (_render["on"] and _render["used"] < RENDER_CAP
            and page_is_hh(url) and len(lines) < RENDER_LINE_FLOOR)


def render(url):
    """The page's HTML after its JavaScript has run."""
    if _render["browser"] is None:
        from playwright.sync_api import sync_playwright
        _render["pw"] = sync_playwright().start()
        _render["browser"] = _render["pw"].webkit.launch()
    _render["used"] += 1
    page = _render["browser"].new_page(user_agent=UA)
    try:
        page.goto(url, timeout=30000, wait_until="networkidle")
        return page.content()
    finally:
        page.close()


def render_close():
    if _render["browser"] is not None:
        _render["browser"].close()
        _render["pw"].stop()
        _render["browser"] = _render["pw"] = None


def get(session, url):
    r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA},
                    allow_redirects=True)
    if r.status_code == 403:
        try:
            r = urllib_get(url)
        except Exception:  # noqa: BLE001 -- keep the original 403 as the answer
            pass
    ctype = r.headers.get("content-type", "")
    # A venue that publishes its happy hour as a PDF has published it. The text
    # is the venue speaking exactly as much as its HTML is, so it is read the
    # same way -- the extractor never learns which one a quote came from.
    if r.status_code == 200 and "pdf" in ctype.lower():
        text = pdf_text(r.content)
        return ("<pre>" + html_mod.escape(text) + "</pre>", None) if text \
            else (None, "pdf, no extractable text")
    if r.status_code != 200 or "html" not in ctype:
        return None, f"{r.status_code} {ctype.split(';')[0] or '?'}"
    # requests falls back to latin-1 when a page declares no charset, which
    # turns every en-dash in '5-7PM' into a replacement character.
    if "charset" not in ctype.lower():
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text[:600_000], None


def registrable(netloc):
    """'locations.pjspub.com' and 'www.pjspub.com' -> 'pjspub.com'.

    Two labels is the right approximation for this corpus: it is US bars and
    restaurants, so the multi-part public suffixes this would get wrong
    (.co.uk, .com.au) do not occur, and treating one as registrable would at
    worst let a link through to be filtered on its words instead.
    """
    return ".".join(netloc.lower().split(":")[0].split(".")[-2:])


def candidate_links(html, page_url):
    """Links whose text or href suggests a menu or specials page.

    Sibling hosts on the same registrable domain count as the same site. A
    chain puts each location on locations.<brand>.com but keeps the specials on
    www.<brand>.com, so an exact-netloc test threw away exactly the page we are
    looking for: fetching locations.pjspub.com/pa/conshohocken/200-ridge-pike
    yielded no candidates at all while dropping /specials, /drinks-menu and
    /food-menu as foreign. Those locations returned one quote where their
    same-host siblings returned four. The domain is still the venue's own, so
    this widens the host test without loosening what counts as a deal page.
    """
    host = registrable(urllib.parse.urlsplit(page_url).netloc)
    found, seen = [], set()
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.{0,120}?)</a>',
                         html, re.I | re.S):
        href, label = m.group(1), MARKUP_RE.sub(" ", m.group(2))
        if not LINK_WORDS.search(href) and not LINK_WORDS.search(label):
            continue
        full = urllib.parse.urljoin(page_url, href).split("#")[0]
        if registrable(urllib.parse.urlsplit(full).netloc) != host or full in seen:
            continue
        # .pdf is deliberately absent: a link labelled 'Happy Hour Menu' that
        # points at a PDF is the deal itself, and dropping it by extension threw
        # away the only page some venues publish it on.
        if re.search(r"\.(jpg|png|gif|zip|doc|docx)$", full, re.I):
            continue
        seen.add(full)
        # A link that says 'happy hour' outranks one that merely says 'menu'.
        found.append((0 if (url_names_hh(full, 2)
                             or re.search(r"happy.?hour|hour(?!s)|special", label, re.I))
                       else 1, full))
    return [u for _, u in sorted(found)]


def sitemap_links(session, page_url, robots):
    """Deal-page URLs from the host's sitemap, for sites that link to none.

    A page can be published and unlinked: a theme's nav holds Menu / About /
    Contact while /happy-hour exists and is reachable only from search. The
    sitemap is the venue's own index of what it published, so consulting it
    finds those pages without guessing at URLs. Only used when the homepage
    offered nothing, because when it does offer links they are better ordered.
    """
    base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(page_url))
    out, seen = [], set()
    queue, budget = [base + "/sitemap.xml"], 3
    while queue and budget:
        url = queue.pop(0)
        if url in seen or not allowed(url, robots):
            continue
        seen.add(url)
        budget -= 1
        try:
            r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
            if r.status_code != 200 or "xml" not in r.headers.get("content-type", ""):
                continue
            body = r.text[:2_000_000]
        except Exception:  # noqa: BLE001 -- no sitemap is the common case
            continue
        locs = [html_mod.unescape(m.group(1))
                for m in re.finditer(r"<loc>\s*([^<\s]+)\s*</loc>", body, re.I)]
        # An index of sitemaps points at more sitemaps; follow only the one most
        # likely to hold pages, never the whole tree of a 10,000-URL chain site.
        if "<sitemapindex" in body[:2000].lower():
            queue += [u for u in locs if re.search(r"page|post", u, re.I)][:2] or locs[:1]
            continue
        for u in locs:
            if url_names_hh(u, 2) and u not in seen:
                seen.add(u)
                out.append(u)
    return out


# Darden's brands publish their happy hour as DATA, not as a page. The site is a
# Next.js shell -- 2,694 bytes of HTML with nothing in it, behind an Akamai bot
# manager -- so every parser this file contains reads zero lines from it, and
# Yard House, Seasons 52, Eddie V's and The Capital Grille all came back from
# King of Prussia with nothing. Rendering it in a real browser does not help
# either: /happy-hour asks you to pick a location before it will show anything.
#
# The location page's own API answers directly, needs one header and no browser,
# and returns the restaurant's happy-hour hours per day under hourCode 'HH'.
# That is the venue's own structured statement of its hours -- better evidence
# than a regex over prose, not worse -- so it is turned back into a QUOTE and
# handed to the same extractor and the same validators as everything else. No
# new publishing path and no new trust tier: the crawl just learns to read one
# more format.
#
# Only the HH code is read. 'Late Night Happy Hour' carries its own code and an
# end time of '12:00 PM' meaning midnight, and is left for when there is a
# reason to want it.
DARDEN_HOSTS = ("yardhouse.com", "seasons52.com", "eddiev.com",
                "thecapitalgrille.com", "olivegarden.com", "cheddars.com",
                "bahamabreeze.com", "longhornsteakhouse.com")
# .../locations/pa/king-of-prussia/king-of-prussia-king-of-prussia-mall/8371
DARDEN_NUM_RE = re.compile(r"/locations/(?:[^/]+/){2,3}(\d{3,6})(?:[?#]|$)")
# The same shape, as the thing that says 'this is the platform' on a brand we
# have never seen: a two-letter state, a city, a location slug and a number.
DARDEN_PATH_RE = re.compile(
    r"/locations/[a-z]{2}/[a-z0-9-]+/[a-z0-9-]+/\d{3,6}(?:[?#]|$)", re.I)
DARDEN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
               "Saturday", "Sunday"]


def money(value):
    """A price the downstream label pattern can read: two decimals, or none.

    '$5.5' is neither, and All Beers at $5.50 was dropped for it with no error
    anywhere -- rstrip('0') had turned a valid half-dollar into a shape the
    pattern refuses (2026-09-01).
    """
    value = float(value)
    return "%d" % round(value) if value == int(value) else "%.2f" % value


def darden_ref(url):
    """(host, restaurant number) if this looks like a Darden location URL.

    The host list is a fast path, not the test. A typed list of brands is what
    made the FRC adapter miss a sibling brand silently, and the same trap is
    here: Darden owns more restaurants than this file names and buys more. The
    URL SHAPE -- /locations/<state>/<city>/<slug>/<number> -- is the platform's
    own, and the API either answers with a restaurant or it does not, so the
    guess costs one 404 and can never publish anything wrong. The brand list
    stays because it saves that request on the eight we know.
    """
    host = registrable(urllib.parse.urlparse(url).netloc)
    m = DARDEN_NUM_RE.search(url)
    if not m:
        return None
    if host not in DARDEN_HOSTS and not DARDEN_PATH_RE.search(url):
        return None
    return (host, m.group(1))


def darden_quotes(url):
    """The venue's happy-hour hours, read from its own API, as quoted lines.

    Days sharing one start and end are named together in a single quote, because
    the extractor reads days and a window out of ONE sentence -- a quote per day
    would publish only whichever day the lead quote happened to be.
    """
    ref = darden_ref(url)
    if not ref:
        return None, []
    host, num = ref
    api = f"https://www.{host}/api/restaurants/{num}"
    req = urllib.request.Request(api, headers={"X-Source-Channel": "WEB", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
        rest = json.load(fh)["restaurant"]
    return api, darden_lines(rest)


def darden_lines(rest):
    """The 'HH' hours of one restaurant record, as quoted lines."""
    by_window = {}
    for day in rest.get("restaurantHours") or []:
        name = day.get("day")
        if name not in DARDEN_DAYS:
            continue
        for hi in day.get("hoursInfo") or []:
            if hi.get("hourCode") != "HH":
                continue
            key = (hi.get("startTime"), hi.get("endTime"))
            if all(key):
                by_window.setdefault(key, []).append(name)
    out = []
    for (start, end), days in by_window.items():
        days.sort(key=DARDEN_DAYS.index)
        out.append(f"Happy Hour / {', '.join(days)} / {start} - {end}")
    return out


# The discount a Darden happy-hour section states in its own heading. The menu
# API gives every dish its FULL price and no happy-hour price at all, so the
# heading is the only place the deal is written down: 'HH 1/2 OFF SELECT APPS'.
# A section whose heading names no discount we can read is skipped rather than
# guessed at -- its dishes are on the happy-hour menu at a price we do not know.
DARDEN_OFF_RE = re.compile(r"(?:\b1\s*/\s*2\b|\bhalf\b)[-\s]*(?:price|off)|"
                           r"\b(\d{1,2})\s*%\s*off", re.I)
# No cap. Yard House puts 20 dishes on its happy-hour list and we take all 20:
# the card folds after 3 and keeps the rest behind "+N more", so the display was
# never the constraint. Capping here was silently costing us menu the venue's own
# API had already handed over (Paul, 2026-09-01).


def darden_off_pct(heading):
    """The percentage a section heading takes off, or None if it names none."""
    m = DARDEN_OFF_RE.search(heading or "")
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else 50


def darden_dish_name(raw):
    """A dish name the downstream label pattern can actually read.

    (R)/(TM)/* are decoration on the venue's own name, and accents and curly
    quotes are the same problem wearing a different hat: left in, the name falls
    outside the label pattern and the dish is dropped with no error anywhere.
    GARDEIN(R) WINGS went that way, and so did CoTe MAS 'ROSe AURORe'. Folding
    to ASCII also lets the noun list read ROSE as wine, which it cannot do
    through the accent.
    """
    # The asterisk is a FOOTNOTE mark ('cooked to order'), and it is not always
    # trailing: 'Petite Filet Sandwiches* (2)' carries it mid-name. Stripping it
    # only off the end left the mark inside the label pattern's charset, so the
    # dish vanished with no error -- the same silent drop as the (R) (2026-09-01).
    name = raw.replace("®", "").replace("™", "").replace("*", "")
    name = name.replace("‘", "'").replace("’", "'")
    name = name.replace("“", "").replace("”", "")
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    return name.strip().rstrip("*").strip().strip("'").strip()


# Grape varieties, so a wine list that never says the word 'wine' is still wine.
# Seasons 52 heads three glasses 'RED' and names them PINOT NOIR, MALBEC and
# CABERNET SAUVIGNON; no structural field separates a red from a cocktail, and
# guessing would put wine on the board as a cocktail. A varietal list is a closed
# real-world vocabulary, unlike the open one the food nouns try to be.
VARIETALS = re.compile(
    r"\b(pinot noir|pinot grigio|pinot gris|chardonnay|sauvignon blanc|"
    r"cabernet|cabernet sauvignon|merlot|malbec|riesling|zinfandel|syrah|shiraz|"
    r"tempranillo|sangiovese|chianti|prosecco|champagne|moscato|grenache|"
    r"rose|rioja|bordeaux|brut)\b", re.I)


def darden_category(sub, prod, head, name):
    """Which of the board's eight categories this dish is, from the API's own fields.

    isBeverageItem is a fact the venue states, so food never depends on a word
    list at all. A drink still needs its TYPE, which no field carries, so the
    section heading is read first ('COCKTAILS', 'SANGRIA', 'WHITE & ROSE'), then
    the dish name, then the varietals. If none of those answer, the drink is
    refused rather than filed under a guessed type -- a wine sold as a cocktail
    is worse on the board than a wine we left off.
    """
    configs = prod.get("configs") or {}
    if configs.get("isBeverageItem") is False:
        return "food"
    for text in (head, name):
        cat = darden_drink_category(text)
        if cat:
            return cat
    if VARIETALS.search(name) or VARIETALS.search(head):
        return "wine"
    return None


DRINK_WORDS = [
    ("draft", r"draft|drafts|draught|pint|pints|beer|beers|lager|ipa|brew"),
    ("bottle_can", r"bottle|bottles|can|cans"),
    ("wine", r"wine|wines|sangria|rose|red|white|sparkling|bubbles"),
    ("cocktail", r"cocktail|cocktails|martini|margarita|mule|spritz|highball|punch"),
    ("shot", r"shot|shots"),
    ("well", r"well|wells|rail"),
]


def darden_drink_category(text):
    low = (text or "").lower()
    for cat, pat in DRINK_WORDS:
        if re.search(rf"\b(?:{pat})\b", low):
            return cat
    return None


# What a Darden brand CALLS its happy hour in its own menu API. Seven of the
# eight say 'happy-hour'; The Capital Grille brands its as CAPITAL HOURS, slug
# 'capital-hours', and matching the literal slug therefore read its hours fine
# and returned zero dishes -- the same silent nothing as a missing venue, on a
# venue we were already crawling (Paul, 2026-09-01).
#
# This is an explicit per-brand alias and NOT a pattern over category names. A
# looser match here does not fail closed: it would file a brand's dinner menu as
# a happy hour and put full-price steaks on the board as bargains. Each new name
# gets read off the API and typed in.
DARDEN_HH_SLUGS = {"thecapitalgrille.com": ("happy-hour", "capital-hours")}
DARDEN_HH_DEFAULT = ("happy-hour",)


def darden_hh_slugs(host):
    return DARDEN_HH_SLUGS.get(host, DARDEN_HH_DEFAULT)


# The not-a-deal gate matched on product slug alone, and a brand that shortens
# the dish name on its happy-hour menu walks straight through it: The Capital
# Grille lists 'Pan-Fried Calamari' at $23 under CAPITAL HOURS and the identical
# 'Pan-Fried Calamari with Hot Cherry Peppers' at $23 on dinner, under a
# different slug. Three full-price appetizers -- a $40 caviar dip among them --
# were about to be published as happy-hour bargains. So the name is matched too,
# and the shortened form counts: an entry whose full name begins with the
# happy-hour name plus a word is the same dish (Paul, 2026-09-01).
def darden_norm(name):
    return re.sub(r"[^a-z0-9 ]", "", darden_dish_name(name or "").lower()).strip()


def darden_regular(elsewhere, names, prod, name):
    """The lowest price this venue states for this dish OFF its happy-hour menu."""
    found = [elsewhere[prod.get("slug")]] if prod.get("slug") in elsewhere else []
    key = darden_norm(name)
    if key:
        for other, value in names.items():
            if other == key or other.startswith(key + " "):
                found.append(value)
    return min(found) if found else None


def darden_menu_quotes(host, num):
    """The venue's happy-hour DISHES, from the same API that holds its hours.

    The site itself is an empty JavaScript shell -- the /happy-hour page is 2.7KB
    of loader and nothing a crawler can read -- so this is not an optimisation,
    it is the only way these eight chains say anything at all.
    """
    api = f"https://www.{host}/api/menu?restaurantNum={num}"
    req = urllib.request.Request(api, headers={"X-Source-Channel": "WEB", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
        menu = json.load(fh)
    # What the SAME dish costs on the rest of this venue's menu. Eddie V's files
    # its ordinary dinner appetizers under happy-hour untouched -- a $36 crab cake
    # is $36 at 4pm too -- so a priced happy-hour line is only a DEAL if it beats
    # every other price the venue states for that dish. Without this the board
    # would have advertised six full-price appetizers as bargains, which is the
    # '$X off' mistake once more: the digits are real, the deal is not.
    hh_slugs = darden_hh_slugs(host)
    elsewhere, names = {}, {}
    for cat in menu.get("categories") or []:
        if cat.get("slug") in hh_slugs:
            continue
        for sub in cat.get("subCategories") or []:
            for prod in sub.get("products") or []:
                value = (prod.get("price") or {}).get("value")
                slug = prod.get("slug")
                if value is None:
                    continue
                if slug:
                    elsewhere[slug] = min(value, elsewhere.get(slug, value))
                key = darden_norm(prod.get("displayName"))
                if key:
                    names[key] = min(value, names.get(key, value))
    out = []
    for cat in menu.get("categories") or []:
        if cat.get("slug") not in hh_slugs:
            continue
        for sub in cat.get("subCategories") or []:
            # The heading is folded for the same reason the dish name is: the noun
            # list downstream reads ROSE as wine and cannot read it through the
            # accent in 'WHITE & ROSE'.
            head = darden_dish_name(sub.get("displayName") or "")
            pct = darden_off_pct(head)
            if not head:
                continue
            for prod in (sub.get("products") or []):
                name = darden_dish_name(prod.get("displayName") or "")
                if not name:
                    continue
                # Darden TELLS us what the thing is, so we stop guessing from words.
                # The noun whitelist downstream exists for prose pages, where a '$8'
                # beside some text could be a deal, a gift card or a corkage fee and
                # the only evidence is the vocabulary. Here the API states it, and
                # re-deriving it from a word list threw away six flatbreads because
                # nobody had typed 'flatbread'. Carried as a marker the extractor
                # reads instead of asking category_of().
                cat_hint = darden_category(sub, prod, head, name)
                if not cat_hint:
                    continue
                mark = f"[cat:{cat_hint}] "
                if pct is not None:
                    out.append(f"{mark}{head} / {pct}% Off {name}")
                    continue
                # A Darden brand states its happy hour in ONE of TWO dialects, and we
                # were reading only the first. Yard House discounts a section it prices
                # nowhere ('HH 1/2 OFF ALL PIZZAS'), so the discount is the deal. Seasons
                # 52 does the opposite: '$8 SMALL PLATES', with each dish carrying the
                # price you actually pay. Refusing every section that names no discount
                # threw away all 21 Seasons 52 items -- a full happy-hour menu the API
                # had already handed us (Paul, 2026-09-01).
                price = (prod.get("price") or {}).get("value")
                if price is None:
                    continue
                regular = darden_regular(elsewhere, names, prod, name)
                if regular is not None and float(price) >= float(regular):
                    continue
                amount = money(price)
                out.append(f"{mark}{head} / ${amount} {name}")
    return api, out


# --- Fox Restaurant Concepts (North Italia and its sibling brands) -----------
#
# The handoff guessed this was a JavaScript menu like Darden's. It is not: the
# whole happy-hour menu is in the HTML on first byte, every tab of it, and the
# generic pass still came back with the tab LABELS and nothing else. The reason
# is one character. This platform prints its prices with no dollar sign --
# <span class="menu-item-price">8</span> -- so DEAL_RE, BARE_PRICE_RE and the
# price pass downstream all look straight past them. A bare 8 in prose is not a
# price and must not be read as one; here it is a price because the venue put it
# in a box that says so.
#
# So this is read structurally, like Darden, and for the same reason: the source
# STATES the things we would otherwise guess. One element gives the dish, one
# gives its price, and the section it sits in gives its kind. Nothing is derived
# from a word list over dish names.
FRC_HOSTS = ("northitalia.com", "flowerchild.com", "culinarydropout.com",
             "foxrc.com", "blancotacos.com", "thehenrycafe.com")
# The tab anchor names the menu; the panel carries the same id. Reading the id
# off the anchor rather than trusting class="active" means the panel is found
# whichever tab the server decided to open on.
FRC_TAB_RE = re.compile(r'href="\?menu=happy-hour"[^>]*data-menu-id="(\d+)"', re.I)
FRC_TAB_ALT_RE = re.compile(r'data-menu-id="(\d+)"[^>]*href="\?menu=happy-hour"', re.I)
FRC_PANEL_RE = r'<div class="[^"]*menu-category[^"]*" data-menu-id="%s"'
FRC_SECTION_RE = re.compile(r'data-section-slug="([^"]+)"(.*?)(?=data-section-slug=|\Z)',
                            re.S)
FRC_TITLE_RE = re.compile(r'menu-section-title">(.*?)</h3>', re.S)
FRC_ITEM_RE = re.compile(
    r'menu-item-name">(.*?)</h4>\s*<span class="menu-item-price">([^<]*)</span>', re.S)
# A happy-hour section of alcohol-free drinks. The board has eight categories and
# none of them is 'no alcohol', so these are refused outright rather than filed
# under the thing they imitate -- a Phony Negroni on the board as a cocktail is a
# customer ordering a drink that is not what they came for.
FRC_ZERO_RE = re.compile(r"zero.proof|non.alcoholic|mocktail|\bn/?a\b", re.I)
# The section headings this platform files FOOD under. A closed list of the
# source's own SECTION names, which is a different thing from the open noun list
# over dish names that this repo keeps trying to grow: it is the venue's own
# grouping, and 'Eat' answers for ten dishes at once. A heading in neither this
# list nor the drink vocabulary is REFUSED and logged by name, so an unknown
# section shows up as a line to add rather than as items silently misfiled.
FRC_FOOD_RE = re.compile(r"^(eat|food|bites|snacks|small plates|shareables|"
                         r"appetizers|starters|plates|share)$", re.I)


def frc_host(url):
    """True if this URL is on the Fox Restaurant Concepts menu platform."""
    return registrable(urllib.parse.urlparse(url).netloc) in FRC_HOSTS


# What the platform itself puts in the page. The hostname tuple above triggers
# on brands somebody typed in, and a sibling brand on the SAME platform then
# misses in complete silence -- which is how North Italia was found by hand
# rather than by us. The markup is the platform's own signature and needs
# nobody to have heard of the brand.
FRC_MARKUP_RE = re.compile(r'class="menu-item-price"|data-section-slug=', re.I)


def frc_markup(html):
    """True if this PAGE is built by the FRC menu platform, whoever owns it."""
    return bool(FRC_MARKUP_RE.search(html or ""))


def frc_text(chunk):
    """The visible text of one markup fragment."""
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", chunk or "")).strip()


def frc_category(head, name, unknown=None):
    """Which of the board's eight categories a section is, from its own heading.

    Drink type first, then varietals, then the food headings. Never the dish
    name for food: that is the word list this repo removed. A heading that
    answers none of them is refused, and its text is recorded in `unknown` so
    the next pass can see what it was rather than wonder where the items went.
    """
    if FRC_ZERO_RE.search(head or ""):
        return None
    cat = darden_drink_category(head)
    if cat:
        return cat
    if VARIETALS.search(head or "") or VARIETALS.search(name or ""):
        return "wine"
    if FRC_FOOD_RE.match((head or "").strip()):
        return "food"
    if unknown is not None and head:
        unknown.add(head)
    return None


def frc_menu_quotes(url):
    """The venue's happy-hour DISHES, read off its own menu markup.

    Every tab of every menu is in this one document, so the venue's ordinary
    prices are here too and the same not-a-deal gate Darden needs applies: a
    priced happy-hour line counts only if it BEATS the lowest price the venue
    states for that dish anywhere else on the page. North Italia's own numbers
    pass it (Zucca Chips 8 against 11, Calamari 15 against 18); the gate is here
    for the day a section is the dinner menu wearing a happy-hour heading, which
    is exactly what Eddie V's turned out to be.
    """
    page = url.split("?")[0].rstrip("/") + "/?menu=happy-hour"
    req = urllib.request.Request(page, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
        doc = fh.read().decode("utf-8", "replace")
    m = FRC_TAB_RE.search(doc) or FRC_TAB_ALT_RE.search(doc)
    if not m:
        return page, [], set()
    menu_id = m.group(1)
    start = re.search(FRC_PANEL_RE % menu_id, doc)
    if not start:
        return page, [], set()
    rest = doc[start.end():]
    nxt = re.search(r'<div class="[^"]*menu-category[^"]*" data-menu-id="', rest)
    panel = rest[: nxt.start()] if nxt else rest
    # What the same dish costs on this venue's other menus, lowest wins.
    elsewhere = {}
    for name, price in FRC_ITEM_RE.findall(doc.replace(panel, "")):
        key = frc_text(name).lower()
        try:
            value = float(price.strip())
        except ValueError:
            continue
        if key:
            elsewhere[key] = min(value, elsewhere.get(key, value))
    out, unknown = [], set()
    for sec in FRC_SECTION_RE.finditer(panel):
        slug, body = sec.group(1), sec.group(2)
        t = FRC_TITLE_RE.search(body)
        head = frc_text(t.group(1)) if t else slug.replace("-", " ")
        for raw_name, raw_price in FRC_ITEM_RE.findall(body):
            name = darden_dish_name(frc_text(raw_name))
            if not name:
                continue
            try:
                price = float(raw_price.strip())
            except ValueError:
                continue
            regular = elsewhere.get(name.lower())
            if regular is not None and price >= regular:
                continue
            cat = frc_category(head, name, unknown)
            if not cat:
                continue
            amount = money(price)
            out.append("[cat:%s] %s / $%s %s" % (cat, head, amount, name))
    return page, out, unknown


# A heading that says what KIND of thing the block below it is, in the venue's
# own words. The dish-name word list can never carry food -- 'Garlic Flatbread',
# 'Tavern Taquitos', 'Loaded Nachos' and 'Hummus Trio Dip' are on nobody's list
# of nouns -- but the venue already answered the question by heading the block
# 'EAT'. A word list is for prose; on a menu the structure states the category.
# Only the food side is mapped: a 'DRINK' heading covers six of our categories at
# once, so those lines still go to the label to be read.
HEADING_CAT = re.compile(
    r"^(?:eat|eats|food|foods|bites?|snacks?|kitchen|plates?|small plates|"
    r"shareables?|to share|munchies|apps?|appetizers?|starters?)\s*$", re.I)
# A line the venue left blank to separate one price block from the next. Wix
# writes it as a zero-width space, so it is not empty and str.strip() keeps it.
BLANK_RE = re.compile(r"^[\s\u200b\u200c\u00a0\u2060]*$")
# How many dishes one stacked price may own. Same argument as SECTION_PRICE_CAP:
# a happy-hour block is short, and a longer run is a menu the price does not own.
STACK_CAP = 12


LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S)


def ld_nodes(html):
    """Every object in the page's schema.org graph, however deeply nested.

    @graph, arrays and hasMenuSection/hasMenuItem all nest, so a flat pass over
    the top-level objects finds the Restaurant and misses the Menu hanging off
    it. A JSON document is a tree and the only honest way to read one is to
    walk it.
    """
    out = []

    def walk(node):
        if isinstance(node, dict):
            out.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for m in LD_RE.finditer(html):
        try:
            walk(json.loads(m.group(1).strip()))
        except Exception:  # noqa: BLE001 -- one malformed block is not the page
            continue
    return out


def _ld_type(node):
    t = node.get("@type")
    return {x for x in (t if isinstance(t, list) else [t]) if x}


def jsonld_quotes(html):
    """The happy hour a page publishes as DATA rather than as prose.

    Pizzeria Vetri states its entire happy hour -- the window and all three
    priced sections -- in a schema.org Menu block on /menus/, and the visible
    page says only the words 'Happy Hour' behind a JavaScript tab. We fetched
    that page, read it as prose, and reported the venue as saying happy hour
    with no window. The window was in our hands the whole time.

    This is a W3C-backed standard, not a venue quirk: the site said what it
    meant in the form meant for machines, and we were the machine that did not
    look. Read the Menu whose name or description names a happy hour, take its
    description as the hours line, and take its sections and items as the menu.

    Only a Menu that NAMES itself the happy hour is read. A restaurant's main
    Menu block is its dinner menu, and publishing that as happy hour items is
    the failure this corpus fears most -- the regular price, presented as a
    deal. So an unnamed or differently-named menu is passed over in silence.
    """
    out = []
    for node in ld_nodes(html):
        if "Menu" not in _ld_type(node):
            continue
        name = str(node.get("name") or "").strip()
        desc = str(node.get("description") or "").strip()
        if not HH_HEADING_RE.search(name):
            continue
        # The description is where these blocks put the hours: 'Weekdays: 4 PM
        # - 6 PM'. Quoted WITH the menu's own name so the extractor sees the
        # claim the way the venue made it, not a bare clock with no subject.
        if desc:
            out.append(f"{name}: {desc}")
        for sec in node.get("hasMenuSection") or []:
            if not isinstance(sec, dict):
                continue
            sname = str(sec.get("name") or "").strip()
            if sname:
                out.append(sname)
            for item in sec.get("hasMenuItem") or []:
                if not isinstance(item, dict):
                    continue
                iname = str(item.get("name") or "").strip()
                offer = item.get("offers") or {}
                if isinstance(offer, list):
                    offer = offer[0] if offer else {}
                price = (offer or {}).get("price") if isinstance(offer, dict) else None
                if iname and price:
                    out.append(f"{iname} ${price}")
                elif iname:
                    out.append(iname)
    return list(dict.fromkeys(out))


BARE_WINDOW_RE = re.compile(
    r"^\s*\d{1,2}(?::\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.)?\s*(?:-|–|—|to)\s*"
    r"\d{1,2}(?::\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.)\s*$", re.I)


def states_a_deal(line):
    """True when a line does more than NAME the happy hour.

    'Happy Hour' alone is a nav link, a tab, a page title -- it makes no claim
    about when anything happens, so it must never be joined to a clock sitting
    beside it. Black Powder Tavern's home page carries exactly that label in a
    row of opening hours, and pairing them manufactured three windows -- lunch
    11:30-4, brunch 11-3 and the real 4-6 -- one of which then OUTRANKED the
    venue's own sentence, 'Happy Hour on Monday through Friday from 4:00 p.m.
    until 6:00 p.m.'. A correct Mon-Fri window became every day of the week,
    cited to a quote that says 11:30 to 4.

    Peppers' line is 'Happy Hour! $2 OFF any bar bite | $1 OFF any beer | ...'
    -- it states a deal, and a deal is the thing a clock can belong to. So the
    test is what SURVIVES removing the words: a price, or enough other words to
    be a sentence rather than a label.
    """
    rest = HH_HEADING_RE.sub(" ", line)
    rest = re.sub(r"[^0-9A-Za-z$]+", " ", rest).strip()
    return bool(re.search(r"\$\s?\d", rest) or len(rest) >= 12)


def boxed_windows(lines, stacks):
    """Quotes for a happy hour whose CLOCK is in the box next door.

    Peppers publishes a real window and we published nothing, because the page
    is a two-column row: the deal is in one cell and '04:00 PM - 06:00 PM' is
    in its sibling. Read down the page as prose those are two unrelated lines,
    one with no time and one with no subject, and each is worthless alone.

    This is the same fact as item_beside(), one field over: which lines a page
    put in ONE box is read off the markup, and the box says the clock and the
    deal are the same claim. Joining records that merely FOLLOW each other
    invents adjacencies, so the shared box is required -- a bare clock with no
    happy-hour line in its own box is passed over, not guessed at.

    The box is the IMMEDIATE parent, not an ancestor within a few levels. On
    Peppers' page every day is a row of two cells inside one section, so an
    ancestor test made the whole section one box and paired the happy hour with
    the clock of the row ABOVE it -- publishing 4-9pm, which belongs to that
    day's other special. Two cells of the same row share a parent; two rows do
    not. That is the whole difference between the right window and a plausible
    wrong one, and it is the off-by-one this file has hit before.
    """
    out = []
    for i, line in enumerate(lines):
        if not BARE_WINDOW_RE.match(line) or len(stacks[i]) < 2:
            continue
        row = stacks[i][-2]
        for j in range(max(0, i - 4), min(len(lines), i + 5)):
            if j == i or len(stacks[j]) < 2 or stacks[j][-2] != row:
                continue
            if not HH_HEADING_RE.search(lines[j]) or not states_a_deal(lines[j]):
                continue
            if TIME_CONTEXT_RE.search(lines[j]):
                continue  # it states its own clock; it does not need this one
            out.append(f"{lines[j]} {line.strip()}")
            break
    return list(dict.fromkeys(out))


LOC_RE = re.compile(r"/locations?/([a-z0-9-]+)", re.I)
CANON_RE = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', re.I)


def wrong_location(html, url):
    """The other town's page, served at ours.

    cityworksrestaurant.com/locations/king-of-prussia/happy-hour/ returns 200
    and a complete happy-hour page that says 'the best Happy Hour in Frisco',
    canonical /locations/frisco/happy-hour-menu/. Reading a window off it would
    have published a Texas schedule under a King of Prussia bar, sourced,
    quoted and wrong -- and every gate we have would have passed it, because
    the quote is real and the fetch was clean.

    A chain that serves one location's page at another's URL has told us so in
    its own canonical tag. Believe it: when the canonical names a DIFFERENT
    location slug than the URL we asked for, this page is not about this venue.
    """
    want = LOC_RE.search(url)
    canon = CANON_RE.search(html or "")
    if not (want and canon):
        return None
    got = LOC_RE.search(canon.group(1))
    if got and got.group(1).lower() != want.group(1).lower():
        return got.group(1).lower()
    return None


def stacked_prices(lines, hh_lines):
    """Quotes for the 'one price, then the dishes it covers' layout.

    Tommy's Tavern + Tap lists its happy hour food as '$8' on its own line
    followed by four dishes, then '$9' and four more, then '$10' and four more.
    Nothing joins a price to its dishes except PAGE ORDER: the page is Wix, and
    every one of those lines sits in its own absolutely-positioned branch of the
    tree, so item_beside() -- which reads the box a price shares with its item --
    finds a box holding the price and nothing else, and the twelve dishes went
    unpublished while the page showed them in plain text.

    The venue does mark where each block ends: a blank line, written as a
    zero-width space. So a price owns the lines after it until the next blank
    line, the next price, the end of the happy-hour section, or the cap.

    Only ever inside a happy-hour section. That is what makes reading by page
    order safe here and unsafe everywhere else -- outside the section this rule
    would walk a price down the dinner menu.
    """
    out, cat, i, hh = [], None, 0, sorted(hh_lines)
    for i in hh:
        line = lines[i].strip()
        if HEADING_CAT.match(line):
            cat = "food"
            continue
        if BLANK_RE.match(lines[i]):
            continue
        if not BARE_PRICE_RE.match(line):
            # Any other heading-ish line ends the food block's claim; a dish
            # line is picked up below by the price above it, never here.
            continue
        names = []
        for j in range(i + 1, min(i + 1 + STACK_CAP, len(lines))):
            if j not in hh_lines or BLANK_RE.match(lines[j]):
                break
            nxt = lines[j].strip()
            if BARE_PRICE_RE.match(nxt) or HEADING_CAT.match(nxt):
                break
            if len(nxt) > SECTION_LABEL_MAX or not re.search(r"[A-Za-z]{3}", nxt):
                break
            names.append(nxt)
        if len(names) < 2:
            # One name is the ordinary priced line and item_beside already has
            # it. This rule exists for the LIST, and a run of one is not one.
            continue
        mark = "[cat:%s] " % cat if cat else ""
        out.append(mark + line + " / " + " / ".join(names))
    return out


def page_key(lid, url):
    return "%s__%s.json" % (lid, hashlib.sha1(url.encode()).hexdigest()[:12])


def save_page(lid, url, title, lines, rendered=False):
    """Keep a happy-hour page's visible text for the model pass to read."""
    if not lid:
        return
    os.makedirs(PAGES, exist_ok=True)
    tmp = os.path.join(PAGES, page_key(lid, url) + ".new")
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"lid": lid, "url": url, "title": title, "rendered": rendered,
                   "fetched_at": time.strftime("%Y-%m-%d"), "lines": lines},
                  fh, ensure_ascii=False)
    os.replace(tmp, os.path.join(PAGES, page_key(lid, url)))


def crawl_one(session, venue, robots):
    pages, hits, images = [], [], []
    lid = venue.get("lid") or venue.get("id") or ""
    # A Darden site has nothing to read in its HTML; its API has the hours. Asked
    # first, and the ordinary crawl still runs after -- it costs one request and
    # a venue that turns out not to be Darden is unaffected.
    try:
        api, found = darden_quotes(venue["website"])
    except Exception as e:  # noqa: BLE001 -- one dead API must not end the run
        api, found = None, []
        pages.append({"url": venue["website"], "result": f"error: darden api {type(e).__name__}"})
    if api:
        pages.append({"url": api, "result": f"ok, {len(found)} quote(s) from the venue API"})
        for q in found:
            hits.append({"url": venue["website"], "quote": q, "hh": True})
        ref = darden_ref(venue["website"])
        try:
            m_api, dishes = darden_menu_quotes(*ref)
            pages.append({"url": m_api, "result": f"ok, {len(dishes)} dish(es) from the menu API"})
            for q in dishes:
                hits.append({"url": venue["website"], "quote": q, "hh": True})
        except Exception as e:  # noqa: BLE001 -- the hours stand without the menu
            pages.append({"url": venue["website"],
                          "result": f"error: darden menu api {type(e).__name__}"})
    # A Fox Restaurant Concepts page prints its prices without a dollar sign, so
    # the generic pass reads the tab labels and stops. Read structurally instead.
    frc_done = False
    if frc_host(venue["website"]):
        frc_done = True
        try:
            f_url, dishes, unknown = frc_menu_quotes(venue["website"])
            note = "ok, %d dish(es) from the menu markup" % len(dishes)
            if unknown:
                note += "; section(s) refused, unknown kind: " + ", ".join(sorted(unknown))
            pages.append({"url": f_url, "result": note})
            # Filed under the venue's own URL, exactly as the Darden dishes are.
            # '?menu=happy-hour' is a TAB of the page the hours were read from,
            # but items_from_hits() pairs items to the schedule by exact URL, so
            # the query string alone was enough to leave all 19 dishes unattached
            # and publish the window with an empty card.
            for q in dishes:
                hits.append({"url": venue["website"], "quote": q, "hh": True})
        except Exception as e:  # noqa: BLE001 -- one dead page must not end the run
            pages.append({"url": venue["website"],
                          "result": "error: frc menu %s" % type(e).__name__})
    # We hold this venue's website in TWO places and they disagree for 17 of
    # them -- and neither source is reliably the better one. bartaco's good URL
    # (/location/kop/, which carries 'weekdays 3-6pm') is the one in
    # venue_base; Pizzeria Vetri's good URL (/location/king-of-prussia/) is the
    # one in venue_sites. Picking a winner loses one of them either way, so
    # both are seeded: they are both this venue's site, and the second costs
    # one fetch out of a budget that was being spent on the chain's /locations/
    # index anyway.
    queue = [(u, 1) for u in
             dict.fromkeys([venue["website"], *venue.get("also_urls", ())])]
    fetched = 0
    docs = 0
    while queue and (fetched < PAGE_CAP or docs < DOC_CAP):
        url, depth = queue.pop(0)
        # A menu document draws on its own budget, not the page budget. Going
        # one level deeper on the SAME budget just means missing something else,
        # which is the trade PAGE_CAP was sized against; a PDF gets its own two
        # slots instead, so the four HTML fetches every venue used to get are
        # still four. A page slot is only spent when a page slot is available.
        is_doc = depth > 1 and re.search(r"\.pdf($|\?)", url, re.I)
        if is_doc:
            if docs >= DOC_CAP:
                continue
        elif fetched >= PAGE_CAP:
            continue
        if not allowed(url, robots):
            pages.append({"url": url, "result": refusal(url, robots)})
            continue
        time.sleep(DELAY)
        if is_doc:
            docs += 1
        else:
            fetched += 1
        try:
            html, err = get(session, url)
        except Exception as e:  # noqa: BLE001 -- one dead site must not end the run
            pages.append({"url": url, "result": f"error: {type(e).__name__}"})
            continue
        if err:
            pages.append({"url": url, "result": err})
            continue
        # Before reading a word of it: is this page even about this venue? A
        # chain serving another location's page at ours is a wrong ANSWER, not
        # a miss, and it is the only failure here that no later gate catches.
        elsewhere = wrong_location(html, url)
        if elsewhere:
            pages.append({"url": url,
                          "result": f"refused: canonical says {elsewhere}, not us"})
            continue
        # The venue's own title for the page is what unlocks the looser price
        # rules -- the same test used a few lines below to decide a menu PDF is
        # worth chasing, and the same containment.
        on_hh = url_names_hh(url, depth)
        # The lines AND the element each was found in: which lines a page put in
        # one box is what says which item a bare price belongs to, and it exists
        # only here, in the markup. See item_beside().
        # A page that carries the FRC menu markup IS an FRC page, whatever the
        # brand is called. Read structurally, once per venue.
        if not frc_done and frc_markup(html):
            frc_done = True
            try:
                f_url, dishes, unknown = frc_menu_quotes(url)
                note = "ok, %d dish(es) from the menu markup (platform)" % len(dishes)
                if unknown:
                    note += "; section(s) refused, unknown kind: " + ", ".join(sorted(unknown))
                pages.append({"url": f_url, "result": note})
                for q in dishes:
                    hits.append({"url": venue["website"], "quote": q, "hh": True})
            except Exception as e:  # noqa: BLE001 -- one dead page must not end the run
                pages.append({"url": url,
                              "result": "error: frc menu %s" % type(e).__name__})
        lines, stacks, emph = text_lines_emph(html)
        rendered = False
        if render_wanted(url, lines):
            try:
                shown = render(url)
            except Exception as e:  # noqa: BLE001 -- one dead render, not the run
                pages.append({"url": url,
                              "result": "render failed: %s" % type(e).__name__})
                shown = None
            if shown:
                grown, gstacks, gemph = text_lines_emph(shown)
                # Only if the browser actually found more page than the fetch
                # did. A render returning the same shell is evidence of nothing
                # and must not relabel the page as one we read in full.
                if len(grown) > len(lines):
                    pages.append({"url": url, "result": "rendered: %d lines -> %d"
                                  % (len(lines), len(grown))})
                    html, lines, stacks, emph = shown, grown, gstacks, gemph
                    rendered = True
        text = "\n".join(lines)
        # The URL is no longer the only key. A page that does not name the happy
        # hour in its address very often names it in a heading, and that heading
        # is the venue's own word for the section beneath it -- the same claim
        # the URL was standing in for, read off the page rather than the link.
        if is_doc:
            hh_lines = frozenset()
        elif page_is_hh(url):
            hh_lines = frozenset(range(len(lines)))
        else:
            hh_lines = hh_sections(html, text)
        found = quotes(text, menu_doc=is_doc, hh_page=on_hh, hh_lines=hh_lines,
                       stacks=stacks, emph=emph, mark_hh=True,
                       head_prices=heading_prices(html, text, hh_lines, stacks))
        for q in stacked_prices(lines, hh_lines):
            hits.append({"url": url, "quote": q, "hh": True})
        # The two things the prose pass cannot see: what the page said to
        # machines, and what it said in the box next door.
        for q in jsonld_quotes(html):
            hits.append({"url": url, "quote": q, "hh": True})
        for q in boxed_windows(lines, stacks):
            hits.append({"url": url, "quote": q, "hh": True})
        # How much of the page we could actually READ, recorded alongside the
        # result. A fetch that returns 200 and 11 lines of text and a fetch that
        # returns 200 and 400 lines are the same row in this file without it,
        # and they are opposite problems: the first is a JavaScript shell we
        # cannot see into, the second is a page we read in full that does not
        # mention a happy hour. Nothing downstream could tell those apart, so
        # every silent venue looked alike and none of them could be ranked.
        # ingest/report_holes.py --silent sorts on this.
        says_hh = bool(HH_HEADING_RE.search(text))
        pages.append({"url": url, "result": f"ok, {len(found)} quote(s)",
                      "lines": len(lines),
                      "hh": says_hh})
        # Every page that turns out to be about a happy hour is kept in full.
        # The quotes below are what a regex could see; this is what was there.
        if says_hh or page_is_hh(url):
            save_page(lid, url, lines[0] if lines else "", lines,
                      rendered=bool(rendered))
        for q in found:
            # `hh` records that this line was INSIDE the venue's own happy-hour
            # section, which is the fact the extractor needs and could not get.
            # It paired a price to a schedule by exact URL, and a venue that
            # prints its hours on the home page and its menu on /menu -- Mia
            # Ragazza, and it is a common shape -- had both halves on disk and
            # published neither. The containment is not loosened by saying so:
            # the same lines are stored, and only lines the crawl already
            # vouched for may now travel between pages of the same site.
            hits.append({"url": url, "quote": q["quote"], **({"hh": True} if q["hh"] else {})})
        if on_hh:
            for src in menu_images(html, url):
                if not any(im["src"] == src for im in images):
                    images.append({"url": url, "src": src})

        # A page we fetched because it said 'happy hour' is the one place a menu
        # PDF is worth chasing: Black Powder Tavern's hours were read off their
        # happy-hour page while the items and prices sat in a PDF that page
        # linked, one hop further in than the crawler ever went. The venue then
        # looked covered, because it had a card. So a happy-hour page's own PDF
        # links are followed -- and only those, and only PDFs.
        # ...and so is a PDF that NAMES ITSELF the happy hour, wherever it is
        # linked from. Amada, Barbuzzo, Cantina Feliz and ten others post
        # 'happy-hour-menu.pdf' on the HOME page, which is depth 1 and does not
        # say 'happy hour' in its address, so the whole menu was one link away
        # and never followed. The filename is the venue's own word for the
        # document, which is the same claim the page URL was standing in for.
        queued = {u for u, _ in queue}
        on_hh_page = url_names_hh(url, depth)
        for u in candidate_links(html, url):
            if not re.search(r"\.pdf($|\?)", u, re.I) or u in queued:
                continue
            if on_hh_page or HH_DOC_RE.search(u):
                queue.append((u, depth + 1))

        if fetched == 1 and depth == 1:
            # The seeds we have NOT tried yet survive this rebuild, at the
            # front. A URL we hold on file for this venue outranks a link we
            # discovered on its homepage, and dropping them silently is what
            # left bartaco's /location/kop/ -- the only page stating 'weekdays
            # 3-6pm' -- unfetched while the budget went to the chain's
            # /locations/ index.
            seeds = [q for q in queue if q[1] == 1]
            queue = seeds + [(u, 2) for u in
                             candidate_links(html, url)[: PAGE_CAP - 1]]
            # The sitemap used to be consulted only when the page linked
            # nothing at all, which missed the commoner shape: a page that
            # links three menus and no happy hour. City Works' King of Prussia
            # page offers a food menu, a second food menu and a charity event,
            # so the budget was spent on entrees while /happy-hour/ sat in the
            # sitemap unread. Linked pages still go first -- they are better
            # ordered -- and the sitemap only ever returns happy-hour and
            # specials URLs, so this tops up rather than replaces.
            if not any(url_names_hh(u, d) for u, d in queue):
                queued = {u for u, _ in queue}
                extra = [(u, 2) for u in sitemap_links(session, url, robots)
                         if u not in queued]
                rest = [q for q in queue if q[1] != 1]
                queue = seeds + (extra + rest)[: PAGE_CAP - 1]
    return pages, hits, images[:IMG_CAP]


def reached_nothing(pages):
    """True when a crawl of a venue failed to READ a single page.

    A re-crawl overwrites whatever it finds, so a venue whose host happened to
    be down at that moment had its good record replaced by an empty one: The
    Stray Dog Tavern held eight quotes and a published happy hour, and one
    ConnectTimeout on 2026-09-01 dropped it off the board entirely. Nothing in
    the record said so -- 'hits: []' reads exactly like a venue that publishes
    nothing, which is why the loss was invisible until the board count moved.

    So a crawl that read no page is not an answer about the venue, it is an
    answer about the network, and the caller keeps what it already had.
    """
    return bool(pages) and all(str(pg.get("result", "")).startswith("error:")
                               for pg in pages)


def keep_failed_pages(pages, held):
    """Quotes from pages that errored THIS run and were read fine before.

    reached_nothing() protects the venue whose whole host was down. It does not
    protect the commoner shape: three pages read, one ConnectionError, and the
    quotes that one page held are silently gone from the board. Gullifty's lost
    all five of its items exactly that way on 2026-09-01 -- its /drink-menu
    fetch failed on a recrawl and the rebuild shipped a card with nothing on
    it. The window survived, so no count moved and nothing looked wrong.

    A fetch that errored is not an answer about that page, at any scale. So the
    per-venue rule is applied per PAGE: a URL that failed this time keeps the
    quotes we already held for it, and only a page we actually READ is allowed
    to say a page has nothing on it.
    """
    failed = {pg["url"] for pg in pages
              if str(pg.get("result", "")).startswith("error:")}
    if not failed:
        return [], []
    ok_now = {pg["url"] for pg in pages
              if not str(pg.get("result", "")).startswith("error:")}
    carried = [h for h in (held.get("hits") or [])
               if h.get("url") in failed - ok_now]
    notes = [dict(pg, result=pg["result"] + ", KEPT what we held")
             for pg in (held.get("pages") or [])
             if pg["url"] in failed - ok_now
             and not str(pg.get("result", "")).startswith("error:")]
    return carried, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N venues")
    ap.add_argument("--zone", help="only venues in this zone id")
    ap.add_argument("--recrawl", action="store_true", help="revisit venues already recorded")
    # A fix to candidate_links only changes the answer for the sites it applies
    # to, and recrawling all 800 to reach the 66 on a sibling host would cost
    # hours of somebody else's bandwidth for pages we already hold.
    ap.add_argument("--match", help="only venues whose website matches this regex")
    # Re-keying the price containment on the page's own heading only changes the
    # answer for the venues that HAVE a page we already reached and did not
    # harvest. Naming them by licence is the only honest scope: they share no
    # zone and no domain pattern, so --zone and --match cannot express the set,
    # and re-crawling all 849 to reach 130 spends other people's bandwidth on
    # pages whose answer we already hold.
    ap.add_argument("--lids", help="file of licence ids, one per line")
    # Off by default: a render costs ~40x a fetch and only a JavaScript shell at
    # a URL naming an hour is ever worth one. See render_wanted().
    ap.add_argument("--render", action="store_true",
                    help="render a happy-hour page that came back a shell (WebKit)")
    args = ap.parse_args()
    _render["on"] = args.render

    only = None
    if args.lids:
        only = {ln.strip() for ln in open(args.lids, encoding="utf-8") if ln.strip()}

    import requests

    sites = frontier()
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    session = requests.Session()
    robots, stats = {}, collections.Counter()

    todo = [(lid, v) for lid, v in sorted(sites.items())
            if (not args.zone or v["zone_id"] == args.zone)
            and (not args.match or re.search(args.match, v["website"], re.I))
            and (only is None or lid in only)
            and (args.recrawl or lid not in out)]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} venues to crawl (of {len(sites)} discovered)\n")

    for n, (lid, v) in enumerate(todo, 1):
        pages, hits, images = crawl_one(session, dict(v, lid=lid), robots)
        stats["venues crawled"] += 1
        stats["WITH A DEAL QUOTE" if hits else "nothing published"] += 1
        if reached_nothing(pages) and out.get(lid, {}).get("hits"):
            stats["KEPT (host unreachable this run)"] += 1
            print(f"[{n}/{len(todo)}] {(v['osm_name'] or v['name'])[:38]:<40} "
                  "-- unreachable, keeping what we hold")
            continue
        # One page failing is not the venue saying that page is empty.
        carried, notes = keep_failed_pages(pages, out.get(lid) or {})
        if carried:
            stats["kept quotes from a page that failed this run"] += 1
            hits = hits + carried
            pages = pages + notes
        out[lid] = {
            "name": v["name"],
            "osm_name": v["osm_name"],
            "address": v["address"],
            "zone_id": v["zone_id"],
            "website": v["website"],
            "crawled_at": time.strftime("%Y-%m-%d"),
            "pages": pages,
            "hits": hits,
            # Only present when the venue posted its menu as a picture. Absent
            # is the normal case and means nothing was found, not that the pass
            # did not run -- the crawl date on the record says when it looked.
            **({"menu_images": images} if images else {}),
        }
        flag = f"** {len(hits)} quote(s)" if hits else "--"
        print(f"[{n}/{len(todo)}] {(v['osm_name'] or v['name'])[:38]:<40} {flag}")
        # Written every venue: a crawl is slow and interrupting it must not
        # throw away the pages already paid for in wall-clock and politeness.
        with open(OUT + ".new", "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
        os.replace(OUT + ".new", OUT)

    render_close()
    if _render["used"]:
        print(chr(10) + "  %d page(s) rendered in WebKit" % _render["used"])
    print()
    for k, c in stats.most_common():
        print(f"  {c:>5}  {k}")
    print(f"\n{len(out)} venues on file -> {OUT}")


if __name__ == "__main__":
    main()
