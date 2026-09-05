"""Type a bar's name into the real page, in a real engine, and see the board
filter to it.

The matching logic has unit tests; this asks the other half of the question --
that a person can actually reach it. A search behind a button nobody can click
is not a search, and a `node --check` clean file once left this site dead for a
day, so the button is pressed here rather than reasoned about.
"""

import mimetypes
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "web")
BASE = "https://hhf.test/"
# On the board, in a town nobody has to open first, and the venue whose missing
# menu started all of this.
PROBE = "Black Powder"


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  (skipped: playwright not installed)")
        return 0

    with sync_playwright() as pw:
        try:
            browser = pw.webkit.launch()
        except Exception as exc:
            print(f"  (skipped: webkit not installed -- {str(exc).splitlines()[0]})")
            return 0

        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def serve(route):
            rel = route.request.url[len(BASE):].split("?")[0] or "index.html"
            path = os.path.join(WEB, *rel.split("/"))
            if not os.path.isfile(path):
                return route.fulfill(status=404, body="not found")
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if path.endswith(".js"):
                ctype = "text/javascript"
            route.fulfill(status=200, content_type=ctype, body=open(path, "rb").read())

        page.route(BASE + "**", serve)
        page.route("**/live/deals.json",
                   lambda r: r.fulfill(status=200, content_type="application/json",
                                       body='{"venues":[]}'))

        page.route("**/live/events.json",
                   lambda r: r.fulfill(status=200, content_type="application/json",
                                       body='{"venues":{}}'))

        page.goto(BASE, wait_until="load")
        page.wait_for_timeout(3000)

        before = page.evaluate('document.querySelectorAll("#feed .card").length')
        # The button has to be reachable at the top of the page, before the hero
        # has scrolled away -- that is why it floats instead of living in the
        # glass bar, which is hidden up there.
        clickable = page.is_visible("#menuBtn")
        page.click("#menuBtn")
        page.fill("#search", PROBE)
        page.wait_for_timeout(400)

        after = page.evaluate(
            """() => ({
                 cards: [...document.querySelectorAll("#feed .card .name")]
                          .map((n) => n.textContent),
                 note: document.querySelector("#searchNote").textContent,
                 hash: location.hash,
               })"""
        )
        browser.close()

    bad = []
    if errors:
        bad.append(f"uncaught page error: {errors[0]}")
    if not clickable:
        bad.append("the search button is not visible at the top of the page")
    if before < 2:
        bad.append("the board never painted, so filtering it proves nothing")
    if not any(PROBE.lower() in n.lower() for n in after["cards"]):
        bad.append(f"searching {PROBE!r} did not find it: {after['cards'][:5]}")
    if len(after["cards"]) >= before:
        bad.append(f"the board did not narrow: {before} cards before, "
                   f"{len(after['cards'])} after")
    # The link IS the session on this site; a search that the share button
    # cannot reproduce is a different board from the one you were reading.
    if "q=" not in after["hash"]:
        bad.append(f"the search is not in the shareable link: {after['hash']!r}")

    for line in bad:
        print(f"  FAIL {line}")
    if not bad:
        print(f"  ok   search narrowed {before} cards to {len(after['cards'])}: "
              f"{after['cards']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
