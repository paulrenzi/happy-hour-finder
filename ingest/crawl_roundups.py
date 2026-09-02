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
from discover_sites import name_core  # noqa: E402
from validate_pa import ROUNDUP_MAX_AGE_DAYS  # noqa: E402

SOURCES = os.path.join(REPO, "data", "roundup_sources.json")
SITES = os.path.join(REPO, "data", "venue_sites.json")
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


# A roundup is a list: a heading that IS the venue's name, then a paragraph
# about it. A heading is short, is not a sentence, and carries no clause
# punctuation -- "The Social" is a heading, "Sedona it is." is not.
HEADING_MAX = 60
HEADING_WORDS = 7
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


def mentions(text, index):
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

    Matching is on the venue name because a roundup carries no address --
    which is precisely why this lane is capped at "unconfirmed" and scoped to
    the article's own zone.
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    found, queue, prev_heading, last = {}, [], None, None

    def record(venue, ln):
        if venue is None:
            return None
        rec = found.setdefault(venue["lid"], {
            "lid": venue["lid"], "name": venue["name"],
            "address": venue["address"], "zone_id": venue.get("zone_id"),
            "quotes": [],
        })
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
            last = record(venue, ln)
        elif last is not None and prev_heading is not None:
            # A second paragraph under the same heading.
            record({"lid": last["lid"], "name": last["name"],
                    "address": last["address"], "zone_id": last["zone_id"]}, ln)
    return [v for v in found.values() if v["quotes"]]


def crawl_one(session, article, sites, robots, today=None):
    """One article -> a hit, or a dict saying why it was dropped."""
    url = article["url"]
    if not allowed(url, robots):
        return {"url": url, "outlet": article["outlet"], "dropped": "robots.txt"}
    r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA}, allow_redirects=True)
    if r.status_code != 200:
        return {"url": url, "outlet": article["outlet"], "dropped": f"http {r.status_code}"}
    html = r.text
    published = published_date(html)
    if not published:
        # Still a refusal: the card must name the month, and an undated page
        # cannot be labelled at all.
        return {"url": url, "outlet": article["outlet"], "published": None,
                "dropped": "undated"}
    today = today or datetime.date.today()
    text = visible_text(html)
    hits = mentions(text, venue_index(sites, article.get("zone_id")))
    return {
        "url": url,
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
    session = requests.Session()
    robots = {}
    out, last_host = [], None

    for article in articles:
        host = urllib.parse.urlsplit(article["url"]).netloc
        if host == last_host:
            time.sleep(DELAY)
        last_host = host
        try:
            hit = crawl_one(session, article, sites, robots)
        except Exception as e:  # noqa: BLE001 -- one dead outlet is not a failed run
            hit = {"url": article["url"], "outlet": article["outlet"], "dropped": str(e)[:120]}
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
