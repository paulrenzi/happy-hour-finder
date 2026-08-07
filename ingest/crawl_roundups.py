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

import requests

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
    """name_core -> venue record, for the article's zone only when given."""
    index = {}
    for lid, v in sites.items():
        if zone_id and v.get("zone_id") != zone_id:
            continue
        core = name_core(v.get("name"))
        if core:
            index.setdefault(core, dict(v, lid=lid))
    return index


def mentions(text, index):
    """Venues this article names, each with the deal quotes around the mention.

    Matching is on the venue name because a roundup carries no address -- which
    is precisely why this lane is capped at "unconfirmed" and scoped to the
    article's own zone. A one-word core ("Taku", "Bluebird") is too weak to
    stand alone in prose and is skipped rather than guessed at.
    """
    lines = text.split("\n")
    lowered = [ln.lower() for ln in lines]
    found = {}
    for core, venue in index.items():
        if len(core.split()) < MIN_NAME_WORDS:
            continue
        needle = core
        for i, ln in enumerate(lowered):
            if needle not in re.sub(r"[^\w\s]", " ", ln):
                continue
            # The deal is rarely on the same line as the name -- a roundup entry
            # is a heading plus a paragraph. Read the block, not the line.
            block = "\n".join(lines[i:i + 6])
            qs = quotes(block)
            if qs:
                found.setdefault(venue["lid"], {
                    "lid": venue["lid"], "name": venue["name"],
                    "address": venue["address"], "zone_id": venue.get("zone_id"),
                    "quotes": [],
                })
                for q in qs:
                    if q not in found[venue["lid"]]["quotes"]:
                        found[venue["lid"]]["quotes"].append(q)
            break
    return list(found.values())


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
    if not fresh_enough(published, today):
        return {"url": url, "outlet": article["outlet"], "published": published,
                "dropped": "undated" if not published else f"older than {ROUNDUP_MAX_AGE_DAYS}d"}
    text = visible_text(html)
    hits = mentions(text, venue_index(sites, article.get("zone_id")))
    return {
        "url": url,
        "outlet": article["outlet"],
        "published": published,
        "zone_id": article.get("zone_id"),
        "venues": hits,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help=f"write {os.path.relpath(OUT, REPO)} (default is a dry run)")
    args = ap.parse_args()

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
            print(f"  keep  {article['outlet']:<24} {hit['published']}  "
                  f"{len(hit['venues'])} venues  {article['url']}")

    kept = [h for h in out if not h.get("dropped")]
    print(f"\n{len(kept)}/{len(out)} articles inside the {ROUNDUP_MAX_AGE_DAYS}-day window, "
          f"{sum(len(h['venues']) for h in kept)} venue mentions with a deal quote")
    if args.write:
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump({"built_at": datetime.date.today().isoformat(), "articles": out},
                      fh, indent=1)
        print(f"wrote {os.path.relpath(OUT, REPO)}")
    else:
        print("dry run -- pass --write to save")


if __name__ == "__main__":
    main()
