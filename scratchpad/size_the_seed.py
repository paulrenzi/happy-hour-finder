"""Is the price ON the page we already fetched?

The 78 were bucketed on what crawl_hits.json CAPTURED -- `hits` quotes with no
"$" in them. Captured is not the same as present. This asks the page itself.

Read-only, one fetch per venue, writes nothing into data/.
"""
import json, os, re, sys, threading, concurrent.futures as cf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ingest"))
import crawl_sites as cs
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "scratchpad", "seed_sizing.json")

MONEY = re.compile(r"\$\s?\d")
HH = re.compile(r"happy\s*hour|social\s*hour|power\s*hour|appy\s*hour", re.I)

_robots = {}
_lock = threading.Lock()


def one(row):
    lid, name, site, src = row
    r = {"lid": lid, "name": name, "url": src, "status": "", "lines": 0,
         "money_lines": 0, "item_lines": 0, "hh_lines": 0, "hh_sections": 0,
         "money_in_hh": 0, "sample": [], "hh_sample": []}
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
    r["lines"] = len(lines)
    money = [i for i, ln in enumerate(lines) if MONEY.search(ln)]
    items = [i for i, ln in enumerate(lines) if cs.MENU_ITEM_RE.search(ln)]
    r["money_lines"], r["item_lines"] = len(money), len(items)
    r["sample"] = [lines[i].strip()[:90] for i in money[:8]]
    # Which of those sit inside a section the VENUE labelled a happy hour --
    # the same containment the reader uses.
    try:
        hh = cs.hh_sections(html, "\n".join(lines))
    except Exception:  # noqa: BLE001
        hh = frozenset()
    hh = set(hh) if hh else set()
    r["hh_lines"] = len(hh)
    inside = [i for i in money if i in hh]
    r["money_in_hh"] = len(inside)
    r["hh_sample"] = [lines[i].strip()[:90] for i in inside[:8]]
    return r


def main():
    pop = json.load(open(os.path.join(REPO, "scratchpad", "the80.json"), encoding="utf-8"))
    if "--limit" in sys.argv:
        pop = pop[: int(sys.argv[sys.argv.index("--limit") + 1])]
    print("asking %d seed pages what they actually contain\n" % len(pop), flush=True)
    res = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(one, pop):
            res.append(r)
            print("%-34s %-14s lines=%4d  $lines=%3d  item=%3d  hh=%3d  $inHH=%3d" % (
                r["name"][:34], r["status"][:14], r["lines"], r["money_lines"],
                r["item_lines"], r["hh_lines"], r["money_in_hh"]), flush=True)
    tmp = OUT + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)

    n = len(res)
    ok = [r for r in res if r["status"] == "ok"]
    any_money = [r for r in ok if r["money_lines"] > 0]
    lots = [r for r in ok if r["money_lines"] >= 3]
    in_hh = [r for r in ok if r["money_in_hh"] > 0]
    print("\n" + "=" * 72)
    print("OF THE %d 'nothing to read' VENUES, the page we already fetch:" % n)
    print("  %3d answered ok" % len(ok))
    print("  %3d carry a dollar price SOMEWHERE on that page" % len(any_money))
    print("  %3d carry three or more" % len(lots))
    print("  %3d carry one INSIDE a section the venue labels a happy hour" % len(in_hh))
    print("=" * 72)
    if in_hh:
        print("\npriced lines already inside a happy-hour section:")
        for r in sorted(in_hh, key=lambda x: -x["money_in_hh"]):
            print("\n  %s  (%d)" % (r["name"], r["money_in_hh"]))
            print("    %s" % r["url"])
            for s in r["hh_sample"]:
                print("       %s" % s)


main()
