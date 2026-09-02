"""Free sizing pass: how much page is hiding in the shells' embedded JSON?

No model, no spend. Refetch each shell venue's own pages, harvest what the
page shipped to its JavaScript, and count the venues where that text states an
hour window or a price the visible page never showed.
"""
import json, os, re, sys, concurrent.futures as cf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "happy-hour-finder", "ingest"))
sys.path.insert(0, r"C:\Users\paulm\happy-hour-finder\ingest")
import crawl_sites as c

HITS = r"C:\Users\paulm\happy-hour-finder\data\crawl_hits.json"
OUT = os.path.join(os.path.dirname(__file__), "shell_sizing.json")

CLOCK = re.compile(r"\b\d{1,2}(:\d\d)?\s*(a\.?m\.?|p\.?m\.?)\b", re.I)
DASH = re.compile(r"\d\s*(-|to|until|till|\u2013)\s*\d", re.I)
MONEY = re.compile(r"\$\s?\d")
HH = re.compile(r"happy\s*hour", re.I)


def interesting(s):
    return HH.search(s) or (CLOCK.search(s) and DASH.search(s)) or MONEY.search(s)


def one(item):
    lid, name, urls = item
    sess = c.requests.Session() if hasattr(c, "requests") else None
    got, best = [], 0
    for u in urls[:6]:
        try:
            r = c.urllib_get(u)
        except Exception:
            continue
        body = getattr(r, "content", None)
        if body is None:
            continue
        html = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
        if not html.strip():
            continue
        lines, _, _ = c.text_lines_emph(html)
        best = max(best, len(lines))
        em = c.embedded_json_lines(html)
        for s in em:
            if interesting(s) and s not in got:
                got.append(s)
    return {"lid": lid, "name": name, "visible_max": best,
            "found": got[:25], "n": len(got)}


def main():
    d = json.load(open(HITS, encoding="utf-8"))
    todo = []
    for lid, v in d.items():
        pgs = [p for p in (v.get("pages") or []) if isinstance(p.get("lines"), int)]
        if not pgs or max(p["lines"] for p in pgs) >= 40:
            continue
        urls = [p["url"] for p in (v.get("pages") or []) if p.get("url", "").startswith("http")]
        seen, u2 = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u); u2.append(u)
        todo.append((lid, v.get("name"), u2))
    print("shell venues to size:", len(todo), flush=True)
    res = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, r in enumerate(ex.map(one, todo), 1):
            res.append(r)
            if r["n"]:
                print("  %-34s visible %3d  embedded-hits %d" % (r["name"][:34], r["visible_max"], r["n"]), flush=True)
            if i % 25 == 0:
                print("  ... %d/%d" % (i, len(todo)), flush=True)
    tmp = OUT + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    win = [r for r in res if r["n"]]
    print("\n=== %d of %d shell venues carry a window or a price in embedded JSON" % (len(win), len(res)))
    for r in sorted(win, key=lambda x: -x["n"])[:15]:
        print("\n%s (visible %d):" % (r["name"], r["visible_max"]))
        for s in r["found"][:5]:
            print("   ", s[:120])


main()
