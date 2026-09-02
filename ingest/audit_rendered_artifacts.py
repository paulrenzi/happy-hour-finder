#!/usr/bin/env python3
"""Inventory the things a visitor can actually see on pages already crawled.

    python ingest/audit_rendered_artifacts.py --zone upper_darby_lansdowne
    python ingest/audit_rendered_artifacts.py --lids lids.txt

This is deliberately *not* another text crawl.  ``crawl_sites.py`` is good at
turning an already-readable sentence into evidence, but a restaurant can put
its menu in a lazy image, a PDF viewer, an iframe, or an API-backed widget.  A
static HTML parser cannot honestly report that it inspected any of those.

For each page already reached (and still allowed by robots.txt), this script
renders it, scrolls it to trigger lazy content, and records every visible
image, document, iframe/object/embed, menu-like link, and browser network
resource.  It never publishes a deal.  The resulting ledger is the worklist
for the visual/PDF/widget readers, with an explicit disposition for each asset
rather than an invisible filename filter.
"""

import argparse
import collections
import json
import os
import re
import sys
import time
import urllib.parse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawl_sites import OUT as HITS, SITES, UA, allowed, save_page  # noqa: E402

AUDIT = os.path.join(REPO, "data", "rendered_artifacts.json")


def url_kind(url, tag=""):
    """A conservative reading queue class, never a claim that it is a menu."""
    # A CMS image endpoint frequently has no .jpg suffix (Casey's is
    # `/pluto-images/.../<uuid>?w=560`).  The DOM element is stronger evidence
    # of media type than the URL spelling, and is exactly what the old
    # filename-only collector threw away.
    if tag in {"img", "source"}:
        return "image"
    path = urllib.parse.urlsplit(url).path.lower()
    if path.endswith(".pdf") or "pdf" in path:
        return "document"
    if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")):
        return "image"
    if tag in {"iframe", "embed", "object"}:
        return "embedded"
    return "link"


def candidate(asset):
    """Whether an artifact merits a reader; name is ranking evidence only.

    Every asset remains in the ledger.  This flag is intentionally broader
    than the old filename gate: PDFs and embedded widgets are readable even
    when their URL is an opaque CMS id.
    """
    if asset["kind"] in {"document", "embedded"}:
        return True
    # Once the rendered page itself calls the section a happy hour, every
    # visible image in that section is a reader candidate.  A vision reader
    # can reject its hero photo; a filename filter cannot recover a menu whose
    # CMS assigned it an opaque name.
    if asset["kind"] == "image" and asset.get("visible") and asset.get("page_happy_hour_path"):
        return True
    words = " ".join(str(asset.get(k, "")) for k in
                     ("url", "alt", "title", "text", "context", "nearby")).lower()
    return bool(re.search(r"\b(?:happy|hour|special|menu|drink|food|bar|cocktail)\b", words))


def page_urls(hits, only, zone, sites):
    """Unique pages successfully reached by the existing crawler, by licence."""
    out, seen = [], set()
    for lid, row in sorted(hits.items()):
        if only is not None and lid not in only:
            continue
        if zone and (sites.get(lid) or {}).get("zone_id") != zone:
            continue
        for p in row.get("pages") or []:
            url = p.get("url")
            result = str(p.get("result") or "")
            if not url or not result.startswith(("ok,", "rendered")):
                continue
            key = (lid, url)
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def inspect_page(page):
    """Return the rendered, lazy-loaded DOM inventory from one Playwright page."""
    # Scroll in bounded viewport steps.  `loading=lazy` assets have no useful
    # `src` until they intersect the viewport, so page.content() at the top is
    # not a visitor-equivalent view of the page.
    height = page.evaluate("document.documentElement.scrollHeight")
    step = max(page.viewport_size["height"] - 80, 400)
    for y in range(0, min(height, 80_000), step):
        page.evaluate("y => window.scrollTo(0, y)", y)
        page.wait_for_timeout(180)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(250)
    return page.evaluate("""() => {
      const absolute = value => { try { return new URL(value, document.baseURI).href; }
                                  catch (_) { return null; } };
      const srcset = value => (value || '').split(',').map(x => x.trim().split(/\\s+/)[0])
        .filter(Boolean).map(absolute).filter(Boolean);
      const assets = [], seen = new Set();
      const add = (tag, attr, value, node, extra = {}) => {
        const url = absolute(value);
        if (!url || /^data:|^javascript:/i.test(url)) return;
        const rect = node.getBoundingClientRect();
        const key = [tag, attr, url].join('|');
        if (seen.has(key)) return; seen.add(key);
        assets.push({tag, attr, url,
          alt: node.getAttribute('alt') || '', title: node.getAttribute('title') || '',
          text: (node.innerText || node.textContent || '').trim().slice(0, 300),
          context: (node.outerHTML || '').replace(/\\s+/g, ' ').slice(0, 700),
          nearby: (() => { let p = node; for (let i = 0; p && i < 4; i++, p = p.parentElement) {
            const t = (p.innerText || '').trim(); if (t) return t.slice(0, 700); } return ''; })(),
          visible: rect.width > 0 && rect.height > 0,
          ...extra});
      };
      for (const n of document.querySelectorAll('a[href], iframe[src], embed[src], object[data]'))
        add(n.tagName.toLowerCase(), n.tagName === 'a' ? 'href' : (n.tagName === 'object' ? 'data' : 'src'),
            n.tagName === 'a' ? n.href : (n.src || n.data), n);
      for (const n of document.querySelectorAll('img, source')) {
        const v = n.currentSrc || n.getAttribute('src') || n.getAttribute('data-src') ||
                  n.getAttribute('data-lazy-src') || n.getAttribute('data-original');
        if (v) add(n.tagName.toLowerCase(), 'src', v, n);
        for (const u of srcset(n.getAttribute('srcset') || n.getAttribute('data-srcset'))) add(n.tagName.toLowerCase(), 'srcset', u, n);
      }
      for (const n of [...document.querySelectorAll('*')].slice(0, 10000)) {
        const style = getComputedStyle(n).backgroundImage || '';
        for (const m of style.matchAll(/url\\(["']?([^"')]+)["']?\\)/gi)) add(n.tagName.toLowerCase(), 'background-image', m[1], n);
      }
      return {title: document.title, text: (document.body?.innerText || '').slice(0, 20000), assets};
    }""")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zone")
    ap.add_argument("--lids", help="licence ids, one per line")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    only = ({x.strip() for x in open(args.lids, encoding="utf-8") if x.strip()}
            if args.lids else None)
    hits = json.load(open(HITS, encoding="utf-8"))
    sites = json.load(open(SITES, encoding="utf-8"))
    todo = page_urls(hits, only, args.zone, sites)
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} previously reached page(s) to render and inventory")

    from playwright.sync_api import sync_playwright
    robots, out = {}, {}
    with sync_playwright() as pw:
        browser = pw.webkit.launch()
        try:
            for n, (lid, url) in enumerate(todo, 1):
                if not allowed(url, robots):
                    out[f"{lid}::{url}"] = {"lid": lid, "url": url, "status": "robots-disallowed", "assets": []}
                    continue
                page = browser.new_page(user_agent=UA, viewport={"width": 1440, "height": 900})
                network = []
                def response(res):
                    ctype = (res.headers.get("content-type") or "").lower()
                    if any(x in ctype for x in ("json", "pdf", "image", "javascript")):
                        network.append({"url": res.url, "content_type": ctype.split(";")[0]})
                page.on("response", response)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(1_000)
                    seen = inspect_page(page)
                    path = urllib.parse.urlsplit(url).path.lower()
                    page_happy_hour_path = "hour" in path and "hours" not in path
                    # Put the rendered, visitor-visible words into the cache
                    # consumed by the existing window and item readers.  This
                    # is intentionally full text, not the regex-selected
                    # quotes, so a menu widget cannot disappear before a
                    # reader gets a chance to inspect it.
                    save_page(lid, url, seen["title"], seen["text"].splitlines(), rendered=True)
                    assets = []
                    for a in seen["assets"]:
                        a["page_happy_hour_path"] = page_happy_hour_path
                        a["kind"] = url_kind(a["url"], a["tag"])
                        a["candidate"] = candidate(a)
                        assets.append(a)
                    out[f"{lid}::{url}"] = {"lid": lid, "url": url, "status": "ok",
                                                "title": seen["title"], "text": seen["text"],
                                                "assets": assets, "network": network}
                    print(f"[{n}/{len(todo)}] {lid} {len(assets)} artifact(s), "
                          f"{sum(a['candidate'] for a in assets)} reader candidate(s)")
                except Exception as e:  # a broken rendering must be visible in the ledger
                    out[f"{lid}::{url}"] = {"lid": lid, "url": url, "status": f"error: {type(e).__name__}", "assets": []}
                    print(f"[{n}/{len(todo)}] {lid} ERROR {type(e).__name__}")
                finally:
                    page.close()
                    time.sleep(0.2)
        finally:
            browser.close()
    with open(AUDIT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    kinds = collections.Counter(a["kind"] for row in out.values() for a in row.get("assets", []))
    print(f"wrote {len(out)} page(s) -> {AUDIT}; artifacts: {dict(kinds)}")


if __name__ == "__main__":
    main()
