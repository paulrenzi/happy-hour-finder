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
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
import urllib.robotparser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITES = os.path.join(REPO, "data", "venue_sites.json")
OUT = os.path.join(REPO, "data", "crawl_hits.json")

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
        self.lines, self.stacks = [], []

    def _flush(self):
        line = WS_RE.sub(" ", "".join(self.buf)).strip()
        if line:
            self.lines.append(line)
            self.stacks.append(tuple(self.buf_stack or ()))
        self.buf, self.buf_stack = [], None

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
            self.buf.append(part)

    def close(self):
        super().close()
        self._flush()


def text_lines(html):
    """The visible lines and, for each, the element chain it was found in.

    Markup out, structure preserved as line breaks -- a <br> is a line break in
    a happy-hour block, and joining those lines glues 'Mon-Fri' to '4-6pm'.
    """
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
HH_HEADING_RE = re.compile(r"happy\s*hour|social hour|power hour|bar bites", re.I)
# A heading that divides a happy hour up rather than ending it. CO-OP's happy
# hour is an <h2> and so are its own 'Food Specials' and 'Drink Specials', so
# rank cannot tell a subdivision from the next menu -- the WORD can. Closing on
# the next heading of any rank closed CO-OP's section on its own first
# subdivision and harvested one line; this list is what may appear inside.
# Anything not on it closes the section, so an unrecognised heading fails the
# section SHORT, which is the safe direction: a section that runs on does not
# add noise, it publishes a wrong price.
SUBDIVISION_RE = re.compile(
    r"^(?:food|drink|bar|beer|wine|cocktail|liquor|spirit|snack|bite|share|"
    r"small|sip|draft|draught|bottle|can|shot|feature|select|our)\b|"
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


def _norm(x):
    return WS_RE.sub(" ", x).strip().lower()


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
    marked = {_norm(MARKUP_RE.sub(" ", html_mod.unescape(m.group(1))))
              for m in HEADING_TAG_RE.finditer(html)}
    marked.discard("")
    heads = [i for i, ln in enumerate(lines) if _norm(ln) in marked]

    if heads:
        opens = [i for i in heads if HH_HEADING_RE.search(lines[i])]
        # A subdivision of the happy hour does not end it; anything else does.
        closes = [i for i in heads
                  if not SUBDIVISION_RE.search(lines[i].strip())
                  and not HH_HEADING_RE.search(lines[i])]
    else:
        def headinglike(ln):
            return (len(ln) <= FALLBACK_MAX_CHARS and "$" not in ln
                    and len(ln.split()) <= FALLBACK_MAX_WORDS
                    and not ln.rstrip().endswith((".", "!", ",", ":", ";")))
        opens = [i for i, ln in enumerate(lines)
                 if headinglike(ln) and HH_HEADING_RE.search(ln)]
        closes = [i for i, ln in enumerate(lines)
                  if headinglike(ln) and MEAL_HEADING_RE.search(ln)]

    # Two happy-hour headings can nest: CO-OP's page-level 'Bar Bites & Happy
    # Hour' contains both a 'Mid Day' menu and the happy hour proper. The outer
    # one is a title, not a section -- the inner one is the venue's own, more
    # specific word for the same thing, so it wins and the outer is dropped.
    spans = {}
    for i in opens:
        spans[i] = min([j for j in closes if j > i] + [i + 1 + SECTION_CAP, len(lines)])
    out = set()
    for i, stop in spans.items():
        if any(i < j < stop for j in spans):
            continue
        out |= set(range(i + 1, stop))
    return out


def quotes(text, menu_doc=False, hh_page=False, hh_lines=frozenset(), stacks=None):
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
    for i, ln in enumerate(lines):
        inside = i in hh_lines
        loose = menu_doc or hh_page or inside
        bare = (hh_page or inside) and BARE_PRICE_RE.match(ln)
        if (not DEAL_RE.search(ln) and not bare
                and not (loose and MENU_ITEM_RE.search(ln))):
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
    return out[: 24 if (menu_doc or hh_page or hh_lines) else 12]


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
        found.append((0 if re.search(r"happy.?hour|special", full + label, re.I) else 1, full))
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
            if re.search(r"happy.?hour|special", u, re.I) and u not in seen:
                seen.add(u)
                out.append(u)
    return out


def crawl_one(session, venue, robots):
    pages, hits, images = [], [], []
    queue = [(venue["website"], 1)]
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
        # The venue's own title for the page is what unlocks the looser price
        # rules -- the same test used a few lines below to decide a menu PDF is
        # worth chasing, and the same containment.
        on_hh = bool(depth > 1 and re.search(r"happy.?hour|special", url, re.I))
        # The lines AND the element each was found in: which lines a page put in
        # one box is what says which item a bare price belongs to, and it exists
        # only here, in the markup. See item_beside().
        lines, stacks = text_lines(html)
        text = "\n".join(lines)
        # The URL is no longer the only key. A page that does not name the happy
        # hour in its address very often names it in a heading, and that heading
        # is the venue's own word for the section beneath it -- the same claim
        # the URL was standing in for, read off the page rather than the link.
        found = quotes(text, menu_doc=is_doc, hh_page=on_hh,
                       hh_lines=frozenset() if is_doc else hh_sections(html, text),
                       stacks=stacks)
        pages.append({"url": url, "result": f"ok, {len(found)} quote(s)"})
        for q in found:
            hits.append({"url": url, "quote": q})
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
        if depth > 1 and re.search(r"happy.?hour|special", url, re.I):
            queued = {u for u, _ in queue}
            for u in candidate_links(html, url):
                if re.search(r"\.pdf($|\?)", u, re.I) and u not in queued:
                    queue.append((u, depth + 1))

        if fetched == 1 and depth == 1:
            queue = [(u, 2) for u in candidate_links(html, url)[: PAGE_CAP - 1]]
            # The sitemap used to be consulted only when the page linked
            # nothing at all, which missed the commoner shape: a page that
            # links three menus and no happy hour. City Works' King of Prussia
            # page offers a food menu, a second food menu and a charity event,
            # so the budget was spent on entrees while /happy-hour/ sat in the
            # sitemap unread. Linked pages still go first -- they are better
            # ordered -- and the sitemap only ever returns happy-hour and
            # specials URLs, so this tops up rather than replaces.
            if not any(re.search(r"happy.?hour|special", u, re.I) for u, _ in queue):
                queued = {u for u, _ in queue}
                extra = [(u, 2) for u in sitemap_links(session, url, robots)
                         if u not in queued]
                queue = (extra + queue)[: PAGE_CAP - 1]
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
    args = ap.parse_args()

    only = None
    if args.lids:
        only = {ln.strip() for ln in open(args.lids, encoding="utf-8") if ln.strip()}

    import requests

    sites = json.load(open(SITES, encoding="utf-8"))
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
        pages, hits, images = crawl_one(session, v, robots)
        stats["venues crawled"] += 1
        stats["WITH A DEAL QUOTE" if hits else "nothing published"] += 1
        if reached_nothing(pages) and out.get(lid, {}).get("hits"):
            stats["KEPT (host unreachable this run)"] += 1
            print(f"[{n}/{len(todo)}] {(v['osm_name'] or v['name'])[:38]:<40} "
                  "-- unreachable, keeping what we hold")
            continue
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

    print()
    for k, c in stats.most_common():
        print(f"  {c:>5}  {k}")
    print(f"\n{len(out)} venues on file -> {OUT}")


if __name__ == "__main__":
    main()
