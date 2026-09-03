"""Sizing probe: THE PRICE WITH NO DOLLAR SIGN.

The Quoin publishes a full happy-hour menu -- 'Peroni, Italian Pale Lager 4.7%'
then '. . . 6'. Every price rule in this repo is anchored on '$':
BARE_PRICE_RE is r"^\\$\\s?\\d{1,3}...", MENU_ITEM_RE ends in "\\$\\s?\\d", DEAL_RE's
price alternatives all start "\\$". A dot-leader menu is invisible to all of them
and reads to the pipeline as a venue that published no price.

This asks how many of the 78 write their prices that way. Three shapes, all
counted only INSIDE a happy-hour section (or on an hour-named page), which is
the containment that stops a dinner menu being read as a deal.

  1 LEADER  a line that is only a dot leader and a number:   '. . . 6'
  2 TRAIL   an item line ending in a bare number:            'Peroni Lager  6'
  3 ALONE   a line that is only a small number:              '6'

Read-only. Writes nothing into data/.
"""
import json, os, re, sys, threading, concurrent.futures as cf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ingest"))
import crawl_sites as cs
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "scratchpad", "bare_price_sizing.json")

# A leader is the venue drawing a line from the dish to its price.
LEADER = re.compile(r"^[\s.·•…–—_-]{2,}\s*(\d{1,3}(?:\.\d{1,2})?)\s*$")
ALONE = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,2})?)\s*$")
# 'Peroni, Italian Pale Lager 4.7% . . . 6' on ONE line, or 'Draft Beers   6'.
TRAIL = re.compile(r"^(?P<name>[A-Za-z][^$]{3,70}?)"
                   r"(?:[\s.·•…]{2,}|\s{2,})"
                   r"(?P<price>\d{1,3}(?:\.\d{1,2})?)\s*$")
MONEY = re.compile(r"\$\s?\d")
# Things that look like a trailing price and are not one.
NOT_A_PRICE = re.compile(r"\d\s*%\s*$|\bABV\b|\b(19|20)\d\d\s*$|\boz\b|\bml\b", re.I)
NAMEY = re.compile(r"[A-Za-z]{3}")

PRICE_MIN, PRICE_MAX = 1.0, 99.0
FLOOR = 3          # priced lines that make a venue a real recovery

_robots = {}
_lock = threading.Lock()


def plausible(p):
    try:
        v = float(p)
    except ValueError:
        return False
    return PRICE_MIN <= v <= PRICE_MAX


def read(lines, idx):
    """[(shape, item, price)] for the given line indices."""
    out = []
    idx = sorted(idx)
    inside = set(idx)
    for i in idx:
        ln = lines[i].strip()
        if not ln or MONEY.search(ln):
            continue
        m = TRAIL.match(ln)
        if m and plausible(m.group("price")) and not NOT_A_PRICE.search(ln) \
                and NAMEY.search(m.group("name")):
            out.append(("TRAIL", m.group("name").strip(), m.group("price")))
            continue
        m = LEADER.match(ln) or ALONE.match(ln)
        if not m or not plausible(m.group(1)):
            continue
        # A price with a leader belongs to the nearest naming line above it,
        # inside the same section. Without one it is a page number or a count.
        name = ""
        for j in range(i - 1, max(-1, i - 4), -1):
            if j not in inside:
                break
            prev = lines[j].strip()
            if not prev or ALONE.match(prev) or LEADER.match(prev):
                continue
            if NAMEY.search(prev) and len(prev) <= 90:
                name = prev
            break
        if name:
            out.append(("LEADER" if LEADER.match(ln) else "ALONE", name, m.group(1)))
    return out


def one(row):
    lid, name, site, src = row
    r = {"lid": lid, "name": name, "url": src, "status": "", "contained": 0,
         "found": [], "shapes": {}, "hh_lines": 0}
    with _lock:
        ok = cs.allowed(src, _robots)
    if not ok:
        r["status"] = "robots"
        return r
    try:
        html, err, landed = cs.get(requests.Session(), src)
    except Exception as e:  # noqa: BLE001
        r["status"] = "error:" + type(e).__name__
        return r
    if err:
        r["status"] = err
        return r
    r["status"] = "ok"
    lines, stacks, emph = cs.text_lines_emph(html)
    try:
        hh = set(cs.hh_sections(html, "\n".join(lines)) or ())
    except Exception:  # noqa: BLE001
        hh = set()
    # An hour-named URL is the venue's own claim that the whole page is the
    # happy hour -- the same rule crawl_one applies at page_is_hh().
    if not hh and cs.page_is_hh(src):
        hh = set(range(len(lines)))
    r["hh_lines"] = len(hh)
    got = read(lines, hh)
    r["contained"] = len(got)
    r["found"] = [{"shape": s, "item": i[:70], "price": p} for s, i, p in got[:12]]
    for s, _i, _p in got:
        r["shapes"][s] = r["shapes"].get(s, 0) + 1
    return r


def main():
    pop = json.load(open(os.path.join(REPO, "scratchpad", "the80.json"), encoding="utf-8"))
    if "--limit" in sys.argv:
        pop = pop[: int(sys.argv[sys.argv.index("--limit") + 1])]
    print("sizing the dollar-less price over %d venues\n" % len(pop), flush=True)
    res = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(one, pop):
            res.append(r)
            tag = "HIT" if r["contained"] >= FLOOR else "   "
            print("%s %-34s %-12s hh_lines=%4d  priced=%3d %s" % (
                tag, r["name"][:34], r["status"][:12], r["hh_lines"],
                r["contained"], r["shapes"] or ""), flush=True)
    tmp = OUT + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)

    hit = [r for r in res if r["contained"] >= FLOOR]
    some = [r for r in res if r["contained"] > 0]
    items = sum(r["contained"] for r in hit)
    print("\n" + "=" * 74)
    print("OF %d venues that publish an hour and 'no price at all':" % len(res))
    print("  %3d carry >=%d prices written WITHOUT a dollar sign, inside their hour" % (len(hit), FLOOR))
    print("  %3d carry at least one" % len(some))
    print("  %3d items in total from the %d" % (items, len(hit)))
    print("=" * 74)
    for r in sorted(hit, key=lambda x: -x["contained"]):
        print("\n  %s  (%d)" % (r["name"], r["contained"]))
        print("    %s" % r["url"])
        for f in r["found"][:8]:
            print("      %-6s %-58s %s" % (f["shape"], f["item"], f["price"]))


main()
