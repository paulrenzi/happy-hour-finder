"""Print what a 'silent' venue's happy-hour page actually says.

No inference, no regex verdict -- the visible text, so a human (or a model) can
see WHY there is no price on a page whose URL is /happy-hour.
"""
import json, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ingest"))
import crawl_sites as cs
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONEY = re.compile(r"\$\s?\d")
WORD_PRICE = re.compile(
    r"\d+\s*(?:%|percent)\s*off|half.?(?:price|off)|two.for|\bbogo\b|"
    r"\b\d{1,2}\s*(?:dollars?|bucks)\b|^\s*\d{1,2}(?:\.\d\d)?\s*$|"
    r"\b\d+\s*off\b|complimentary|free\b", re.I)


def main():
    urls = sys.argv[1:]
    if not urls:
        rows = json.load(open(os.path.join(REPO, "scratchpad", "the_silent.json"),
                              encoding="utf-8"))
        urls = [r[2] for r in rows if re.search(r"happy.?hour|specials|menus?$", r[2], re.I)]
    robots = {}
    for u in urls:
        print("\n" + "=" * 74)
        print(u)
        print("=" * 74)
        if not cs.allowed(u, robots):
            print("  [robots]")
            continue
        try:
            html, err, landed = cs.get(requests.Session(), u)
        except Exception as e:  # noqa: BLE001
            print("  [error %s]" % type(e).__name__)
            continue
        if err:
            print("  [%s]" % err)
            continue
        lines, stacks, emph = cs.text_lines_emph(html)
        imgs = cs.menu_images(html, landed or u, self_named=True)
        wp = [l for l in lines if WORD_PRICE.search(l)]
        print("  %d visible lines | %d menu images | %d worded-price lines" % (
            len(lines), len(imgs), len(wp)))
        if imgs:
            for s in imgs[:5]:
                print("    IMG %s" % s)
        for l in lines[:60]:
            print("   | %s" % l[:110])


main()
