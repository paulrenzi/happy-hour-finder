#!/usr/bin/env python3
"""Read dated local roundups and turn them into leads (SPEC section 3).

A venue's own page is almost never dated, so "is this from the last 4 months?"
is unanswerable from it. A roundup carries a publish date, which is the only
clean way to make Paul's recency rule a HARD GATE rather than a hope.

Paul's call, 2026-08-06 -- two decisions this module exists to enforce:

  1. A roundup is NOT the venue speaking. Its deals ship in their own tier,
     `source.kind: "roundup"`, with the outlet and publish date named on the
     card, capped at "unconfirmed" however specific the prose is, and they never
     outrank the venue's own page for the same bar.
  2. Anything published more than 120 days ago is not ingested AT ALL. The
     vista.today Phoenixville piece is from October 2024 and is discarded here,
     not demoted downstream.

     REVISED 2026-09-02 (Paul, after the West Chester re-analysis): the age is
     a LABEL, not a discard. Ten of the town's silent venues were looked at by
     hand and NONE of them publish their happy hour on their own site in any
     form we could read -- while one County Lines piece (May 2024) names 27 of
     them with days, clocks and prices. Discarding it published nothing, which
     is the invisible answer, not the safe one. So an old article is kept,
     `stale_days` is written on the hit, and the card names the outlet AND the
     month it was published so the reader can weigh it. fresh_enough() still
     exists and still answers the 120-day question; it just no longer decides.

Writes data/roundup_hits.json -- one entry per article, each with the outlet,
the publish date, and the venue mentions that carried a deal quote.

    python ingest/crawl_roundups.py                 # dry run, prints what it would keep
    python ingest/crawl_roundups.py --write
"""

import argparse
import datetime
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.parse

# requests is imported inside main(), not here: the date gate and the mention
# matcher are pure functions the test suite imports, and CI has no requests.
# A module-level import made a locally-green gate fail the deploy.

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawl_sites import DELAY, TIMEOUT, UA, allowed, quotes, visible_text  # noqa: E402
from discover_sites import name_agrees, name_core, street_core  # noqa: E402
from validate_pa import ROUNDUP_MAX_AGE_DAYS  # noqa: E402

SOURCES = os.path.join(REPO, "data", "roundup_sources.json")
SITES = os.path.join(REPO, "data", "venue_sites.json")
BASE = os.path.join(REPO, "data", "venue_base.json")
OUT = os.path.join(REPO, "data", "roundup_hits.json")

# A roundup names a venue in prose, so the address join the venue lane uses is
# not available. Requiring the article's own zone keeps "Bistro on Bridge" from
# matching a same-named bar three counties away.
MIN_NAME_WORDS = 2

DATE_META = (
    r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+name=["\'](?:article:published_time|datePublished|pubdate|date)["\'][^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
    r'<time[^>]+datetime=["\']([^"\']+)',
)

JSONLD_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
PROSE_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2}),\s+(\d{4})\b", re.I)
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def _iso(value):
    m = ISO_RE.search(value or "")
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def jsonld_dates(html):
    """Every datePublished in the page's JSON-LD blocks.

    A block that fails to parse is skipped rather than aborting the page: many
    local-news CMSes emit one malformed block alongside three good ones.
    """
    out = []
    for block in JSONLD_RE.findall(html):
        try:
            data = json.loads(html_mod.unescape(block))
        except Exception:  # noqa: BLE001 -- a broken block is not a dateless page
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key in ("datePublished", "dateCreated", "uploadDate"):
                    if isinstance(node.get(key), str):
                        out.append(node[key])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return out


def published_date(html):
    """The article's publish date as YYYY-MM-DD, or None.

    None is a REFUSAL, not a default: an undated article cannot be gated on
    recency, which is the only reason this lane is allowed to publish at all.
    A modified date is never accepted in place of a publish date -- a CMS that
    re-stamps every page nightly would wave the whole archive through the gate.
    """
    for value in jsonld_dates(html):
        got = _iso(value)
        if got:
            return got
    for pat in DATE_META:
        m = re.search(pat, html, re.I)
        if m:
            got = _iso(m.group(1))
            if got:
                return got
    m = PROSE_DATE_RE.search(visible_text(html)[:4000])
    if m:
        try:
            return datetime.date(int(m.group(3)), MONTHS[m.group(1).lower()],
                                 int(m.group(2))).isoformat()
        except ValueError:
            return None
    return None


def fresh_enough(published, today=None):
    """The hard gate. An undated article is never fresh."""
    if not published:
        return False
    today = today or datetime.date.today()
    age = (today - datetime.date.fromisoformat(published)).days
    # A future date is a CMS scheduling artefact rather than a stale article, so
    # it passes -- the gate exists to catch OLD, and a negative age is not old.
    return age <= ROUNDUP_MAX_AGE_DAYS


def venue_index(sites, zone_id=None):
    """name_core -> venue record, for the article's zone only when given.

    Both names a venue carries are indexed: the licensee name ("THE RAMS HEAD
    BAR & GRILL") and the trade name the site join found ("Santino's Tap &
    Table"). A roundup uses the sign over the door, which is the second one.
    """
    index = {}
    for lid, v in sites.items():
        if zone_id and v.get("zone_id") != zone_id:
            continue
        for name in (v.get("name"), v.get("osm_name")):
            core = name_core(name)
            if core:
                index.setdefault(core, dict(v, lid=lid))
    return index


# The address join (2026-09-02). "A roundup carries no address" was the
# premise of matching on name alone, and BUCKSCO.Today's Doylestown piece
# disproved it: a card block at the foot of the article puts '37 N Main St,
# Doylestown, PA 18901' as a paragraph under the heading 'Maxwell's On Main
# (MOMs)', and the prose section opens 'Located at 80 W State Street'. Neither
# bar could be named -- Maxwell's licence is the shell '37 N MAIN STREET
# ENTERPRISES LLC', Penn Taproom's is 'PA GRILL ROOM LLC' -- and both had
# real clocks. A house number and a street inside the article's own zone is
# STRONGER evidence than a name, so it widens yield without loosening the
# grounding. It is a fallback: a heading the name index resolves is never
# re-routed by an address.
STREET_SUFFIX = (r"St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive|"
                 r"Pike|Pk|Hwy|Highway|Way|Ct|Court|Pl|Place|Sq|Square|Pkwy|Parkway|"
                 r"Tpke|Turnpike|Cir|Circle|Ter|Terrace")
# re.I because the BASE is where this index is built from, and a PLCB licence
# address is often shouted -- '40 E MARKET ST'. Without it the suffix list,
# written in title case, could not see its own corpus: 4 base venues parsed to
# no door at all, and every all-caps address was invisible to the door check
# below. A guard that cannot see the thing is not green, it is blind.
ADDRESS_RE = re.compile(
    r"\b(\d+(?:-\d+)*)[A-Za-z]?\s+((?:[NSEW]\.?\s+)?[A-Za-z][A-Za-z.']*"
    r"(?:\s+[A-Za-z][A-Za-z.']*){0,3}?\s+(?:" + STREET_SUFFIX + r")\b\.?)", re.I)


def address_keys(address):
    """{(house, street core)} for every number a range spans -- '37-39 N Main
    St' meets '37 N Main St, Doylestown, PA 18901' AND '39 N Main St'."""
    m = ADDRESS_RE.search(address or "")
    if not m:
        return set()
    core = street_core(m.group(2))
    return {(n, core) for n in m.group(1).split("-") if n} if core else set()


def quote_names_another_door(quote, address):
    """True when the paragraph a roundup deal was read from prints a street
    address, and it is not this venue's.

    The address join above is a FALLBACK -- a heading the name index resolved
    is never re-routed by an address -- so nothing ever checked a name-joined
    paragraph against the door it prints. County Lines (May 2024) wrote up
    'Serum Kitchen & Taphouse ... 142 E. Market St.' and it joined by name to
    the licence at 30 N Church St, which is Slow Hand. The card shipped Slow
    Hand's licence under Serum's name, with Serum's Monday-to-Friday 4-to-6
    window -- and Slow Hand is CLOSED Mondays. A customer standing outside on
    a Monday is the failure this refuses.

    Refusing, not re-routing: absent beats publishing under another business's
    name, the same rule HAND_DROPPED keeps in discover_places. Two doors are
    only evidence when BOTH parse -- an unparsed address is silence, not
    disagreement.
    """
    own = address_keys(address)
    if not own:
        return False
    printed = set()
    for m in ADDRESS_RE.finditer(quote or ""):
        core = street_core(m.group(2))
        if core:
            printed |= {(n, core) for n in m.group(1).split("-") if n}
    return bool(printed) and not (printed & own)


def address_index(base, zone_id=None):
    """(house, street core) -> [venue], for the article's zone only when given.

    Built from the BASE, not the site join: the venue whose licence is a shell
    is exactly the one no site was ever found for, so it is not in
    venue_sites.json at all. Two licences at one door (44 W Gay St is Lascala's
    AND Sedona) index as a list of two, and the join refuses the key.
    """
    index = {}
    for lid, v in (base or {}).items():
        if zone_id and v.get("zone_id") != zone_id:
            continue
        for key in address_keys(v.get("address")):
            index.setdefault(key, []).append(dict(v, lid=lid))
    return index


def address_venue(heading, paragraphs, index):
    """The one venue whose door the paragraphs name, or None.

    A door outlives its tenants. On the first corpus run this joined 'Serum
    Kitchen & Taphouse' (County Lines, May 2024) to 142 E Market St, where
    Google now reads the sign as 'Station 142', and 'Split Rail Tavern' (2021)
    to the door that is Bierhaul today. Both would have shipped a card under a
    name the building stopped using -- the stale-join shape HandCorrectedJoins
    already names. So where the base carries a trade name a LIVE source read
    off the door (OSM, Places) and it does not agree with the heading, the join
    is refused. A licence-only name ('PA GRILL ROOM LLC', '37 N MAIN STREET
    ENTERPRISES LLC') is the shell the join exists to see through, and is
    never held against the heading.
    """
    for para in paragraphs:
        for m in ADDRESS_RE.finditer(para):
            core = street_core(m.group(2))
            hits = []
            for n in m.group(1).split("-"):
                for v in index.get((n, core), []):
                    if v not in hits:
                        hits.append(v)
            if len(hits) != 1:
                continue
            v = hits[0]
            if v.get("named_by", "plcb") != "plcb" and not name_agrees(heading, v["name"]):
                continue
            return v
    return None


# A roundup is a list: a heading that IS the venue's name, then a paragraph
# about it. A heading is short, is not a sentence, and carries no clause
# punctuation -- "The Social" is a heading, "Sedona it is." is not.
HEADING_MAX = 60
HEADING_WORDS = 7

# The site's own furniture, learned from the outlet rather than listed by hand.
# DELCO.today's page template emits about a hundred short lines -- 'Commerce',
# 'Community', 'Search', 'Partner / Advertise', 'This field is hidden when
# viewing the form' -- every one of which passes is_heading(). They queue up
# ahead of the article and eat its paragraphs, which is why four cleanly dated
# Media articles matched zero venues. A line that appears on EVERY page from
# one outlet is navigation, not a venue; the venues do not repeat.
#
# The guard is on the CONTENT, not on a page count: a line carrying a price, a
# clock or the words 'happy hour' is never chrome however often it repeats, so
# two articles from an outlet that share a paragraph cannot silence it.
CHROME_MIN_PAGES = 2
NOT_CHROME_RE = re.compile(r"\$|\d\s*(?::\d\d)?\s*(?:am|pm)\b|happy\s*hour", re.I)


def outlet_chrome(texts):
    """Lines every one of an outlet's pages carries -- its navigation."""
    texts = [t for t in texts if t]
    if len(texts) < CHROME_MIN_PAGES:
        return set()
    seen = {}
    for t in texts:
        for ln in {ln.strip() for ln in t.split("\n") if ln.strip()}:
            seen[ln] = seen.get(ln, 0) + 1
    return {ln for ln, n in seen.items()
            if n == len(texts) and not NOT_CHROME_RE.search(ln)}


# A period only ends a sentence when something follows it: 'Wrong Crowd Beer
# Co.' is a heading, 'Sedona it is. The' is not.
NOT_HEADING_RE = re.compile(r"[.!?]\s|[,;:]|\b(?:runs?|from|until|with)\b|\$", re.I)


# Several outlets write a list heading as "<Venue> - <why it made the list>":
# BUCKSCO.Today's Doylestown piece heads its entries "86 West - Best for Groups
# and Drinks". The tail pushed the line past HEADING_WORDS, so the heading was
# never seen, the prose under it went to no venue, and the only quote the town
# produced was the address line in the article's card block at the foot. The
# venue name is the part before the dash.
DASH_SPLIT_RE = re.compile(r"\s+[–—-]\s+")


def heading_text(line):
    """A heading line reduced to the venue name it opens with."""
    return DASH_SPLIT_RE.split(line, 1)[0].strip() if line else line


def is_heading(line):
    # The sentence test stays on the WHOLE line -- splitting first would let a
    # prose sentence with a dash in it pass on its short opening clause.
    if not line or NOT_HEADING_RE.search(line):
        return False
    core = heading_text(line)
    return len(core) <= HEADING_MAX and len(core.split()) <= HEADING_WORDS


def _heading_venue(line, index):
    """The venue this heading is FOR, or None.

    Matching is on the whole heading, never a substring of prose: 'Sedona
    Taphouse' the heading is Sedona; 'Sedona it is.' the sentence is not. A
    one-word core ('Teca', 'Artillery') is allowed here for exactly that
    reason -- the line is the name and nothing else.
    """
    core = name_core(line)
    if not core:
        return None
    hit = index.get(core)
    if hit:
        return hit
    # 'Kildare's Irish Pub' vs 'Kildare's', 'Más Mexicali Cantina' vs 'Mas
    # Mexicali': one core contains the other. The smaller side must be two
    # real words -- on one word, the site's 'Shop' menu link matched SHOP RITE.
    words = set(core.split())
    best = None
    for vcore, v in index.items():
        vwords = set(vcore.split())
        if words <= vwords or vwords <= words:
            shared = words & vwords
            if len(shared) >= 2 and any(len(w) >= 4 for w in shared) \
                    and (best is None or len(shared) > best[0]):
                best = (len(shared), v)
    return best[1] if best else None


# ---------------------------------------------------------------- prose lists
#
# Not every roundup is a list. DELCO.today writes its happy-hour pieces as
# paragraphs that name the bar INSIDE a sentence -- 'Azie in Media has a happy
# hour on weekdays from 4 to 6 PM', 'Off the Rail, also in Media, has $3
# domestic beers during happy hours weeknights, 4 to 6 PM' -- and the heading
# matcher cannot see either one, because there is no heading.
#
# 🛑 The danger this shape carries is the reason the heading rule existed: a
# venue's name turns up in prose that is not about it. In the Off the Rail
# sentence above, 'views of State Street below' names State Street Pub, three
# doors down and on the same board. Publishing $3 domestic beers under that bar
# is worse than publishing nothing at all. Three narrowings, together:
#
#   1. The sentence must say happy hour. Same containment rule as the rest.
#   2. The venue's name core must be MULTI-WORD and every word of it present.
#      One word is never enough -- 'Sedona it is.' stays not-Sedona.
#   3. The name must be the sentence's SUBJECT: its first matched word inside
#      the opening few. 'State Street' sits at word 26 of that sentence and is
#      refused on position alone, which is the guard that actually does the
#      work, since a happy-hour sentence names its bar first.
#
# Two venues both qualifying in one sentence is an ambiguity, not a choice, and
# the sentence is dropped.
SUBJECT_MAX_WORDS = 6
WORD_RE = re.compile(r"[a-z0-9]+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def sentences(paragraph):
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(paragraph or "") if s.strip()]


def subject_venue(sentence, index):
    """The venue a happy-hour sentence is ABOUT, or None."""
    from extract_deals import HH_RE

    if not HH_RE.search(sentence):
        return None
    words = WORD_RE.findall(sentence.lower())
    best = []
    for core, v in index.items():
        parts = [w for w in core.split() if len(w) >= 2]
        if len(parts) < 2:
            continue
        at = []
        for w in parts:
            hit = next((i for i, t in enumerate(words) if t.startswith(w)), None)
            if hit is None:
                break
            at.append(hit)
        if len(at) != len(parts) or min(at) > SUBJECT_MAX_WORDS:
            continue
        best.append((min(at), v))
    return best[0][1] if len(best) == 1 else None


def mentions(text, index, addr_index=None, chrome=frozenset()):
    """Venues this article names, each with the paragraph the article wrote.

    A roundup is a heading (the venue's name) followed by one paragraph. The
    paragraph is the quote, whole: the deal is a sentence in it -- 'Happy
    Hour runs Monday through Friday, 5 to 7, with $5 Tito's' -- and
    cherry-picking lines with the crawl's DEAL_RE lost the days from the
    clock.

    Headings and paragraphs do not strictly alternate. The County Lines page
    repeats a heading ('Sedona Taphouse' twice) and, worse, PAIRS them --
    'Santino's' / 'Sterling Pig' / Santino's paragraph / 'Sterling Pig' /
    Sterling Pig's paragraph -- so a fixed 'next six lines' window filed
    Santino's deal under Sterling Pig and Stove & Tap's under The Social. So:
    headings queue up, a paragraph goes to the OLDEST heading still waiting,
    and a heading that repeats the one before it is the same heading. A
    heading we do not hold (a section title, a bar outside the base) still
    takes its turn in the queue, so the paragraph under it is discarded
    rather than handed to the previous bar.

    Matching is on the venue name first. A heading no name resolves is kept
    with its paragraphs, and a SECOND pass joins it by the street address
    those paragraphs carry (the card block at the foot of the article, or a
    'Located at 80 W State Street' in the prose) -- see address_index(). The
    two halves of one entry are far apart in the document, which is why it
    is a second pass and not a wider window. The hit carries the article's
    heading as its name: the sign over the door, where the licence is a shell.
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()
             and ln.strip() not in chrome]
    found, queue, prev_heading, last = {}, [], None, None
    orphans, last_head = {}, None

    def record(venue, ln, name=None, joined_by=None):
        if venue is None:
            return None
        rec = found.setdefault(venue["lid"], {
            "lid": venue["lid"], "name": name or venue["name"],
            "plcb_name": venue.get("plcb_name") or venue["name"],
            "address": venue["address"], "zone_id": venue.get("zone_id"),
            "quotes": [],
        })
        if joined_by:
            rec["joined_by"] = joined_by
        if ln not in rec["quotes"]:
            rec["quotes"].append(ln)
        return rec

    def names(heading):
        # 'Opa Taverna' -> opa; 'Santino's Tap & Table' -> santino, table.
        # A paragraph writes "Opa's", "at Santino's": prefix match on a word.
        return [w for w in name_core(heading).split() if len(w) >= 3 and w != "s"]

    for ln in lines:
        if is_heading(ln):
            head = heading_text(ln)
            if head == prev_heading:
                continue
            prev_heading = head
            queue.append((head, _heading_venue(head, index)))
            continue
        if queue:
            # The paragraph goes to the queued heading it NAMES, newest first
            # -- Santino's paragraph says Santino's even when Sterling Pig's
            # heading sits between them. Anything queued before that heading
            # never got a paragraph (a section title) and is dropped. A
            # paragraph naming none of them belongs to the newest heading.
            low = ln.lower()
            pick = len(queue) - 1
            for i in range(len(queue) - 1, -1, -1):
                if any(re.search(r"\b" + re.escape(w), low) for w in names(queue[i][0])):
                    pick = i
                    break
            heading, venue = queue[pick]
            queue = queue[pick + 1:]
            last_head = heading
            last = record(venue, ln)
            if venue is None:
                orphans.setdefault(heading, []).append(ln)
        elif last is not None and prev_heading is not None:
            # A second paragraph under the same heading.
            record({"lid": last["lid"], "name": last["name"],
                    "plcb_name": last.get("plcb_name"),
                    "address": last["address"], "zone_id": last["zone_id"]}, ln)
        elif last_head is not None and last_head in orphans:
            orphans[last_head].append(ln)
    # Second pass: the headings nobody could name, joined by the door.
    for heading, paras in orphans.items():
        venue = address_venue(heading, paras, addr_index or {})
        if venue is None or venue["lid"] in found:
            continue
        for ln in paras:
            record(venue, ln, name=heading, joined_by="address")
    # Third pass: the article that has no headings at all, and names its bars
    # inside sentences. The QUOTE is the sentence, not the line: a paragraph
    # can carry two bars, and handing each the whole paragraph would put the
    # other one's clock on its card.
    for ln in lines:
        for s in sentences(ln):
            venue = subject_venue(s, index)
            if venue is None or venue["lid"] in found:
                continue
            record(venue, s, joined_by="sentence")
    return [v for v in found.values() if v["quotes"]]


def fetch_one(session, article, robots):
    """One article -> its visible text and publish date, or why it was dropped.

    Split out from the read so that EVERY page of an outlet is in hand before
    any of them is matched: the chrome an outlet repeats is only knowable
    across its pages, and it has to be known before the first match runs.
    """
    url = article["url"]
    stub = {"url": url, "outlet": article["outlet"]}
    if not allowed(url, robots):
        return dict(stub, dropped="robots.txt")
    r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA}, allow_redirects=True)
    if r.status_code != 200:
        return dict(stub, dropped=f"http {r.status_code}")
    published = published_date(r.text)
    if not published:
        # Still a refusal: the card must name the month, and an undated page
        # cannot be labelled at all.
        return dict(stub, published=None, dropped="undated")
    return dict(stub, published=published, text=visible_text(r.text))


def crawl_one(session, article, sites, robots, today=None, base=None, chrome=frozenset()):
    """One article -> a hit, or a dict saying why it was dropped."""
    got = fetch_one(session, article, robots)
    if got.get("dropped"):
        return got
    return read_one(article, got["text"], got["published"], sites,
                    today=today, base=base, chrome=chrome)


def read_one(article, text, published, sites, today=None, base=None, chrome=frozenset()):
    """The pure half: an article's text -> its venue mentions."""
    today = today or datetime.date.today()
    hits = mentions(text, venue_index(sites, article.get("zone_id")),
                    address_index(base, article.get("zone_id")), chrome=chrome)
    return {
        "url": article["url"],
        "outlet": article["outlet"],
        "published": published,
        "stale_days": max(0, (today - datetime.date.fromisoformat(published)).days),
        "fresh": fresh_enough(published, today),
        "zone_id": article.get("zone_id"),
        "venues": hits,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help=f"write {os.path.relpath(OUT, REPO)} (default is a dry run)")
    args = ap.parse_args()

    import requests

    if not os.path.exists(SOURCES):
        print(f"no {os.path.relpath(SOURCES, REPO)} -- nothing to crawl")
        return
    articles = json.load(open(SOURCES, encoding="utf-8"))["articles"]
    sites = json.load(open(SITES, encoding="utf-8"))
    base = json.load(open(BASE, encoding="utf-8")) if os.path.exists(BASE) else {}
    session = requests.Session()
    robots = {}
    out, last_host = [], None

    # Fetch every page first. The chrome pass needs an outlet's whole set.
    fetched = []
    for article in articles:
        host = urllib.parse.urlsplit(article["url"]).netloc
        if host == last_host:
            time.sleep(DELAY)
        last_host = host
        try:
            fetched.append(fetch_one(session, article, robots))
        except Exception as e:  # noqa: BLE001 -- one dead outlet is not a failed run
            fetched.append({"url": article["url"], "outlet": article["outlet"],
                            "dropped": str(e)[:120]})

    chrome_by_outlet = {}
    for outlet in {a["outlet"] for a in articles}:
        texts = [g.get("text") for a, g in zip(articles, fetched)
                 if a["outlet"] == outlet and g.get("text")]
        chrome_by_outlet[outlet] = outlet_chrome(texts)

    for article, got in zip(articles, fetched):
        if got.get("dropped"):
            hit = got
        else:
            hit = read_one(article, got["text"], got["published"], sites, base=base,
                           chrome=chrome_by_outlet.get(article["outlet"], frozenset()))
        out.append(hit)
        if hit.get("dropped"):
            print(f"  drop  {article['outlet']:<24} {hit['dropped']}  {article['url']}")
        else:
            age = "" if hit["fresh"] else f"  (STALE: {hit['stale_days']}d old, labelled on the card)"
            print(f"  keep  {article['outlet']:<24} {hit['published']}  "
                  f"{len(hit['venues'])} venues  {article['url']}{age}")

    kept = [h for h in out if not h.get("dropped")]
    fresh = [h for h in kept if h["fresh"]]
    print(f"\n{len(kept)}/{len(out)} articles dated ({len(fresh)} inside the "
          f"{ROUNDUP_MAX_AGE_DAYS}-day window), "
          f"{sum(len(h['venues']) for h in kept)} venue mentions")
    if args.write:
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump({"built_at": datetime.date.today().isoformat(), "articles": out},
                      fh, indent=1)
        print(f"wrote {os.path.relpath(OUT, REPO)}")
    else:
        print("dry run -- pass --write to save")


if __name__ == "__main__":
    main()
