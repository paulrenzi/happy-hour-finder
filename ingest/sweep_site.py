"""Fetch a site's pages and print every happy-hour neighbourhood found.

    python ingest/sweep_site.py <url> [<url> ...]

Follows the site's own links whose href or text mentions happy hour, specials,
menu or drink, one level deep, and prints the text around every "happy hour"
it finds. Grounded: it prints the page's own words, never a summary.

That last part is the whole point. This found ten venues on 2026-09-03 that
WebFetch had already been pointed at and reported nothing on -- a summariser
drops a price table, and a price table is the thing we came for. Reach for
this BEFORE WebFetch when hand-reading a venue.
"""
import html
import re
import sys
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HH = re.compile(r"happy\s*hour", re.I)
CLOCK = re.compile(r"\d{1,2}(:\d{2})?\s*(am|pm)?\s*[-–—to]{1,3}\s*\d{1,2}(:\d{2})?\s*(am|pm)", re.I)
LINK = re.compile(r'href=["\']([^"\'#]+)["\'][^>]*>(.{0,120}?)<', re.I | re.S)
WANT = re.compile(r"happy|special|menu|drink|bar|taproom|events", re.I)


sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def text_of(raw):
    t = re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", " ", raw,
               flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def report(url, raw):
    t = text_of(raw)
    hits, seen = [], set()
    for m in HH.finditer(t):
        frag = t[max(0, m.start() - 180): m.start() + 320].strip()
        if frag not in seen:
            seen.add(frag)
            hits.append(frag)
    if hits:
        print("### %s" % url)
        for h in hits[:6]:
            print("   ", h)
        print()
    return bool(hits)


def main(urls):
    for url in urls:
        try:
            raw = get(url)
        except Exception as e:
            print("### %s -- %s" % (url, e))
            continue
        report(url, raw)
        base = url
        subs, seen = [], set()
        for href, label in LINK.findall(raw):
            if not WANT.search(href) and not WANT.search(label):
                continue
            u = urllib.parse.urljoin(base, href)
            if not u.startswith("http") or u in seen or u == url:
                continue
            if urllib.parse.urlparse(u).netloc != urllib.parse.urlparse(url).netloc:
                continue
            seen.add(u)
            subs.append(u)
        for u in subs[:12]:
            try:
                report(u, get(u))
            except Exception:
                pass


if __name__ == "__main__":
    main(sys.argv[1:])
