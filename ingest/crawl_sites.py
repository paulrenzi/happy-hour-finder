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
# Sentences worth keeping alongside the match: a window or a price. '4p' counts
# -- a bar writes the hour that way as readily as '4pm', and CONTEXT_RE not
# knowing it is why Pepperoncini's quote came back as 'Happy Hour / mon - fri /
# $2 OFF': the day line and the price line were picked up and the line that
# actually held the window, '4p - 6p', was invisible.
TIME_CONTEXT_RE = re.compile(r"\d{1,2}(?::\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.|[ap]\b)", re.I)
CONTEXT_RE = re.compile(
    TIME_CONTEXT_RE.pattern + r"|\$\d|mon|tue|wed|thu|fri|sat|sun", re.I)

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
        #
        # Two slots, and the window gets first refusal on them: a day line and
        # a price line were filling both while the hours sat just below, and the
        # venue was then dropped for stating no schedule. Neither the span nor
        # the slot count moved -- reaching further down the page pulled in the
        # NEXT block's hours instead (Fogo de Chao's '$6 Beers' line acquired
        # the dining room's 3:00-9:30, which is not a happy hour and fails the
        # four-hour cap), so only the ordering within the slots changed.
        if not CONTEXT_RE.search(ln):
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
    return out[:12]


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


def get(session, url):
    r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA},
                    allow_redirects=True)
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
    pages, hits = [], []
    queue = [venue["website"]]
    fetched = 0
    while queue and fetched < PAGE_CAP:
        url = queue.pop(0)
        if not allowed(url, robots):
            pages.append({"url": url, "result": refusal(url, robots)})
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
            # The sitemap used to be consulted only when the page linked
            # nothing at all, which missed the commoner shape: a page that
            # links three menus and no happy hour. City Works' King of Prussia
            # page offers a food menu, a second food menu and a charity event,
            # so the budget was spent on entrees while /happy-hour/ sat in the
            # sitemap unread. Linked pages still go first -- they are better
            # ordered -- and the sitemap only ever returns happy-hour and
            # specials URLs, so this tops up rather than replaces.
            if not any(re.search(r"happy.?hour|special", u, re.I) for u in queue):
                extra = [u for u in sitemap_links(session, url, robots)
                         if u not in queue]
                queue = (extra + queue)[: PAGE_CAP - 1]
    return pages, hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N venues")
    ap.add_argument("--zone", help="only venues in this zone id")
    ap.add_argument("--recrawl", action="store_true", help="revisit venues already recorded")
    # A fix to candidate_links only changes the answer for the sites it applies
    # to, and recrawling all 800 to reach the 66 on a sibling host would cost
    # hours of somebody else's bandwidth for pages we already hold.
    ap.add_argument("--match", help="only venues whose website matches this regex")
    args = ap.parse_args()

    import requests

    sites = json.load(open(SITES, encoding="utf-8"))
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    session = requests.Session()
    robots, stats = {}, collections.Counter()

    todo = [(lid, v) for lid, v in sorted(sites.items())
            if (not args.zone or v["zone_id"] == args.zone)
            and (not args.match or re.search(args.match, v["website"], re.I))
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
