"""Sizing probe for THE 78 -- venues that publish an hour and gave us nothing to read.

Read-only. Writes nothing into data/. Answers one question per route, over the
whole population, before a line of ingest code is written:

  A. THE HOP. crawl_one follows a happy-hour page's links one level deeper only
     when they are .pdf (crawl_sites.py, "for u in candidate_links(...): if not
     .pdf: continue"). How many of the 78 link an HTML menu page from the page
     their window was read on, whose text carries priced item lines?
  B. THE SHELL. How many come back with almost no visible text -- prices in JS?
  C. THE REFUSALS. How many answer 403 / robots / error at all?
  D. IMAGES. How many expose a menu image on the HOPPED page (not the seed)?

Usage: python scratchpad/size_the_hop.py [--limit N]
"""
import json, os, re, sys, threading, urllib.parse, concurrent.futures as cf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ingest"))
import crawl_sites as cs
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POP = os.path.join(REPO, "scratchpad", "the80.json")
OUT = os.path.join(REPO, "scratchpad", "hop_sizing.json")

HOP_CAP = 3          # HTML links followed per venue, one level past the hh page
PRICED_FLOOR = 3     # priced lines that make a document worth reading
SHELL_FLOOR = 40     # cs.RENDER_LINE_FLOOR is the crawl's own shell test

MONEY = re.compile(r"\$\s?\d")
HH = re.compile(r"happy\s*hour|social\s*hour|power\s*hour|appy\s*hour", re.I)

_robots = {}
_lock = threading.Lock()


def allowed(url):
    with _lock:
        return cs.allowed(url, _robots)


def priced_lines(lines):
    """Lines a menu reader would take: a name then a price, or a worded price."""
    out = []
    for ln in lines:
        if cs.MENU_ITEM_RE.search(ln) or (MONEY.search(ln) and len(ln) < 90):
            out.append(ln.strip())
    return out


def fetch(session, url):
    if not allowed(url):
        return None, "robots"
    try:
        html, err, landed = cs.get(session, url)
    except Exception as e:  # noqa: BLE001
        return None, "error:" + type(e).__name__
    if err:
        return None, err
    return html, landed


def one(row):
    lid, name, site, src = row
    r = {"lid": lid, "name": name, "seed": src, "seed_status": "", "seed_lines": 0,
         "shell": False, "hops": [], "best": 0, "best_url": "", "best_hh": False,
         "images": [], "n_links": 0, "hopped": 0}
    session = requests.Session()
    html, landed = fetch(session, src)
    if html is None:
        r["seed_status"] = landed
        return r
    r["seed_status"] = "ok"
    lines, _stacks, _emph = cs.text_lines_emph(html)
    r["seed_lines"] = len(lines)
    r["shell"] = len(lines) < SHELL_FLOOR
    town = None
    try:
        base = json.load(open(os.path.join(REPO, "data", "crawl_hits.json"),
                              encoding="utf-8")) if False else None
    except Exception:  # noqa: BLE001
        base = None
    town = _towns.get(str(lid))
    # The crawl already fetched these; a hop that lands on one recovers nothing.
    seen = {u.rstrip("/") for u in _fetched.get(str(lid), ())}
    seen.add(src.rstrip("/"))
    cands = [u for u in cs.candidate_links(html, landed or src, town)
             if not re.search(r"\.pdf($|\?)", u, re.I)]
    r["n_links"] = len(cands)
    for u in cands[:HOP_CAP]:
        if u.rstrip("/") in seen:
            r["hops"].append({"url": u, "status": "already crawled"})
            continue
        seen.add(u.rstrip("/"))
        r["hopped"] += 1
        h2, land2 = fetch(session, u)
        if h2 is None:
            r["hops"].append({"url": u, "status": land2})
            continue
        l2, _s2, _e2 = cs.text_lines_emph(h2)
        p = priced_lines(l2)
        names_hh = bool(HH.search("\n".join(l2)[:20000]))
        r["hops"].append({"url": u, "status": "ok", "lines": len(l2),
                          "priced": len(p), "hh": names_hh,
                          "sample": p[:6]})
        if len(p) > r["best"]:
            r["best"], r["best_url"], r["best_hh"] = len(p), u, names_hh
        for s in cs.menu_images(h2, land2 or u, self_named=True):
            if s not in r["images"]:
                r["images"].append(s)
    return r


def main():
    global _towns, _fetched
    pop = json.load(open(POP, encoding="utf-8"))
    hits = json.load(open(os.path.join(REPO, "data", "crawl_hits.json"), encoding="utf-8"))
    _towns, _fetched = {}, {}
    for lid, name, site, src in pop:
        v = hits.get(str(lid)) or {}
        _towns[str(lid)] = cs.town_re(v.get("address"))
        _fetched[str(lid)] = [p["url"] for p in (v.get("pages") or [])
                              if str(p.get("result", "")).startswith("ok")]
    if "--limit" in sys.argv:
        pop = pop[: int(sys.argv[sys.argv.index("--limit") + 1])]
    print("probing %d venues, up to %d HTML hops each\n" % (len(pop), HOP_CAP), flush=True)

    res = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for i, r in enumerate(ex.map(one, pop), 1):
            res.append(r)
            tag = "  "
            if r["best"] >= PRICED_FLOOR:
                tag = "HIT"
            print("%s %-34s seed=%-22s lines=%3d hops=%d best=%2d %s" % (
                tag, r["name"][:34], r["seed_status"][:22], r["seed_lines"],
                r["hopped"], r["best"], r["best_url"][:60]), flush=True)
            if i % 20 == 0:
                print("   ... %d/%d" % (i, len(pop)), flush=True)

    tmp = OUT + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)

    n = len(res)
    hit = [r for r in res if r["best"] >= PRICED_FLOOR]
    hit_hh = [r for r in hit if r["best_hh"]]
    shells = [r for r in res if r["seed_status"] == "ok" and r["shell"]]
    dead = [r for r in res if r["seed_status"] != "ok"]
    imgs = [r for r in res if r["images"]]
    nolinks = [r for r in res if r["seed_status"] == "ok" and not r["n_links"]]

    print("\n" + "=" * 72)
    print("POPULATION: %d venues that publish an hour and gave us nothing to read" % n)
    print("-" * 72)
    print("A. THE HOP   %3d gain a linked HTML page carrying >=%d priced lines" % (len(hit), PRICED_FLOOR))
    print("             %3d of those also name a happy hour on that page" % len(hit_hh))
    print("B. THE SHELL %3d seed pages came back under %d visible lines" % (len(shells), SHELL_FLOOR))
    print("C. REFUSED   %3d seed pages did not answer at all" % len(dead))
    print("D. IMAGES    %3d expose a menu image on a HOPPED page" % len(imgs))
    print("   (%d seed pages linked no candidate at all)" % len(nolinks))
    print("=" * 72)
    if dead:
        print("\nrefusals:")
        for r in dead:
            print("   %-34s %s" % (r["name"][:34], r["seed_status"][:50]))
    if hit:
        print("\nthe hop, best first:")
        for r in sorted(hit, key=lambda x: -x["best"]):
            print("\n  %s  (%d priced lines, names hh=%s)" % (r["name"], r["best"], r["best_hh"]))
            print("    %s" % r["best_url"])
            for h in r["hops"]:
                if h.get("url") == r["best_url"]:
                    for s in h.get("sample", []):
                        print("       %s" % s[:100])


main()
