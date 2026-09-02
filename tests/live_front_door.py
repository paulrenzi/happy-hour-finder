"""Is the work actually ON THE LIVE SITE, seen the way a person sees it?

Every other check in this repo answers a smaller question. `render_check.py` runs
the LOCAL page. Fetching `data/zone-*.json` proves a file shipped. Neither proves
the board a visitor opens draws the work -- and three sessions running, "it's
live" was reported off one of those smaller answers and was wrong.

So this one, and only this one, is allowed to be quoted as "it is live":

  * it opens the REAL origin at its ROOT, not a deep link to a JSON file,
  * in a FRESH context -- no service worker, no HTTP cache, i.e. a new visitor,
  * it drives the zone picker the way a person does,
  * and it compares what is PAINTED against the LOCAL built bundle, so a push
    that never deployed and a deploy that never paints both fail here.

Expected names come from the built file, never from the command line: a typed
name carries a straight apostrophe and the board carries a curly one, and that
punctuation mismatch once made this very check cry wolf about Ryan's Pub.

    python tests/live_front_door.py west_chester
"""
import io
import json
import os
import re
import sys

SITE = os.environ.get("HHF_SITE", "https://paulrenzi.github.io/happy-hour-finder/")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def flat(s):
    """Fold to letters+digits: apostrophes, dashes and case are not identity."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def main(zone):
    local_path = os.path.join(REPO, "web", "data", "zone-%s.json" % zone)
    with io.open(local_path, encoding="utf-8") as fh:
        local = json.load(fh)
    want = [v["name"] for v in local["venues"]]
    want_items = sum(len(d.get("items") or [])
                     for v in local["venues"] for d in v.get("deals") or [])

    from playwright.sync_api import sync_playwright

    fails, errs = [], []
    with sync_playwright() as p:
        browser = p.webkit.launch()
        page = browser.new_context().new_page()   # fresh: no SW, no cache
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(SITE, wait_until="networkidle", timeout=90000)

        opts = page.eval_on_selector_all(
            "#zone option", "els=>els.map(e=>e.value)")
        if zone not in opts:
            fails.append("the live picker does not offer %r" % zone)
        else:
            page.select_option("#zone", zone)
            page.wait_for_timeout(3000)

        body = page.inner_text("body")
        painted = page.eval_on_selector_all(
            ".venue, .card, article",
            "els=>els.filter(e=>(e.innerText||'').trim()).length")
        missing = [n for n in want if flat(n) not in flat(body)]
        if missing:
            fails.append("built locally but NOT painted live: %s" % ", ".join(missing))
        if errs:
            fails.append("page errors: %s" % errs)

        print("site      :", SITE)
        print("zone      :", zone)
        print("built     : %d venues, %d items" % (len(want), want_items))
        print("painted   : %d blocks, body %d chars" % (painted, len(body)))
        print("named live: %d of %d" % (len(want) - len(missing), len(want)))
        browser.close()

    for f in fails:
        print("FAIL:", f)
    print("\n%s" % ("LIVE — the built bundle is on the site and paints"
                    if not fails else "NOT LIVE — see the failures above"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "west_chester"))
