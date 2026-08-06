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
import urllib.parse
import urllib.robotparser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITES = os.path.join(REPO, "data", "venue_sites.json")
OUT = os.path.join(REPO, "data", "crawl_hits.json")

UA = "happy-hour-finder/0.1 (+https://paulrenzi.github.io/happy-hour-finder/)"
DELAY = 2.0       # seconds between requests to the same host
PAGE_CAP = 4      # homepage + up to three promising links
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
# Sentences worth keeping alongside the match: a window or a price.
CONTEXT_RE = re.compile(
    r"\d{1,2}(?::\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.)|\$\d|mon|tue|wed|thu|fri|sat|sun",
    re.I)

TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
MARKUP_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\xa0]+")


def visible_text(html):
    """Markup out, structure preserved as newlines -- a <br> is a line break in
    a happy-hour block, and joining those lines glues 'Mon-Fri' to '4-6pm'."""
    html = TAG_RE.sub(" ", html)
    html = re.sub(r"<(br|/p|/div|/li|/tr|/h\d)[^>]*>", "\n", html, flags=re.I)
    # html.unescape, not a hand-written table: a happy-hour line is full of
    # '&#8211;' and '&rsquo;', and a missed entity lands in the quote verbatim.
    text = html_mod.unescape(MARKUP_RE.sub(" ", html)).replace("\xa0", " ")
    lines = [WS_RE.sub(" ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def quotes(text):
    """The matched lines, plus a neighbour when the match itself has no time."""
    lines = text.split("\n")
    out, seen = [], set()
    for i, ln in enumerate(lines):
        if not DEAL_RE.search(ln) or len(ln) > 400:
            continue
        block = [ln]
        # A heading ('HAPPY HOUR') is frequently its own line, with the window
        # on the next one; keeping only the match would drop the entire deal.
        if not CONTEXT_RE.search(ln):
            block += [l for l in lines[i + 1:i + 4] if CONTEXT_RE.search(l)][:2]
        q = " / ".join(block)[:400]
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out[:12]


def robots_for(base, cache):
    if base not in cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(urllib.parse.urljoin(base, "/robots.txt"))
        try:
            rp.read()
        except Exception:  # noqa: BLE001 -- an unreadable robots.txt is not a ban
            rp = None
        cache[base] = rp
    return cache[base]


def allowed(url, cache):
    base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))
    rp = robots_for(base, cache)
    return rp.can_fetch(UA, url) if rp else True


def get(session, url):
    r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA},
                    allow_redirects=True)
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or "html" not in ctype:
        return None, f"{r.status_code} {ctype.split(';')[0] or '?'}"
    # requests falls back to latin-1 when a page declares no charset, which
    # turns every en-dash in '5-7PM' into a replacement character.
    if "charset" not in ctype.lower():
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text[:600_000], None


def candidate_links(html, page_url):
    """Same-host links whose text or href suggests a menu or specials page."""
    host = urllib.parse.urlsplit(page_url).netloc
    found, seen = [], set()
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.{0,120}?)</a>',
                         html, re.I | re.S):
        href, label = m.group(1), MARKUP_RE.sub(" ", m.group(2))
        if not LINK_WORDS.search(href) and not LINK_WORDS.search(label):
            continue
        full = urllib.parse.urljoin(page_url, href).split("#")[0]
        if urllib.parse.urlsplit(full).netloc != host or full in seen:
            continue
        if re.search(r"\.(pdf|jpg|png|gif|zip|doc|docx)$", full, re.I):
            continue
        seen.add(full)
        # A link that says 'happy hour' outranks one that merely says 'menu'.
        found.append((0 if re.search(r"happy.?hour|special", full + label, re.I) else 1, full))
    return [u for _, u in sorted(found)]


def crawl_one(session, venue, robots):
    pages, hits = [], []
    queue = [venue["website"]]
    fetched = 0
    while queue and fetched < PAGE_CAP:
        url = queue.pop(0)
        if not allowed(url, robots):
            pages.append({"url": url, "result": "robots.txt disallows"})
            continue
        time.sleep(DELAY)
        fetched += 1
        try:
            html, err = get(session, url)
        except Exception as e:  # noqa: BLE001 -- one dead site must not end the run
            pages.append({"url": url, "result": f"error: {type(e).__name__}"})
            continue
        if err:
            pages.append({"url": url, "result": err})
            continue
        found = quotes(visible_text(html))
        pages.append({"url": url, "result": f"ok, {len(found)} quote(s)"})
        for q in found:
            hits.append({"url": url, "quote": q})
        if fetched == 1:
            queue = candidate_links(html, url)[: PAGE_CAP - 1]
    return pages, hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N venues")
    ap.add_argument("--zone", help="only venues in this zone id")
    ap.add_argument("--recrawl", action="store_true", help="revisit venues already recorded")
    args = ap.parse_args()

    import requests

    sites = json.load(open(SITES, encoding="utf-8"))
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    session = requests.Session()
    robots, stats = {}, collections.Counter()

    todo = [(lid, v) for lid, v in sorted(sites.items())
            if (not args.zone or v["zone_id"] == args.zone)
            and (args.recrawl or lid not in out)]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} venues to crawl (of {len(sites)} discovered)\n")

    for n, (lid, v) in enumerate(todo, 1):
        pages, hits = crawl_one(session, v, robots)
        stats["venues crawled"] += 1
        stats["WITH A DEAL QUOTE" if hits else "nothing published"] += 1
        out[lid] = {
            "name": v["name"],
            "osm_name": v["osm_name"],
            "address": v["address"],
            "zone_id": v["zone_id"],
            "website": v["website"],
            "crawled_at": time.strftime("%Y-%m-%d"),
            "pages": pages,
            "hits": hits,
        }
        flag = f"** {len(hits)} quote(s)" if hits else "--"
        print(f"[{n}/{len(todo)}] {(v['osm_name'] or v['name'])[:38]:<40} {flag}")
        # Written every venue: a crawl is slow and interrupting it must not
        # throw away the pages already paid for in wall-clock and politeness.
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)

    print()
    for k, c in stats.most_common():
        print(f"  {c:>5}  {k}")
    print(f"\n{len(out)} venues on file -> {OUT}")


if __name__ == "__main__":
    main()
