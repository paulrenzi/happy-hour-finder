"""Type a bar's name into the SUBMIT picker, in a real engine, with no town
picked -- and find a venue that has never been on the board.

This is the half the board's own search cannot answer. The picker used to look
only at what the app had in memory: 169 venues with hours, plus whichever town
the reader had already opened. Typing "Taku" answered "no match" about a venue
that has been in our data all along, and from the outside a missing route reads
exactly like a missing record -- so the one person willing to photograph a menu
concludes we do not have their bar, and stops.

So the assertion is deliberately the hostile case: a cold page, NO town
selected, a venue with zero deals. And the near-collision has to stay visible --
Taku in King of Prussia against Takumi in Devon -- because the submitter picks
between them and we must never pick for them.
"""

import base64
import mimetypes
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "web")
BASE = "https://hhf.test/"
# In our data, in no town the reader has opened, and with no hours published.
PROBE = "taku"
WANT = "Taku Japanese Steakhouse"
COLLIDES = "Takumi"
# Three of them, in three towns. If the picker cannot tell them apart on screen,
# a menu goes on the wrong one and nothing on the card ever reveals it.
BRAND = "dave & buster"

# A one-pixel PNG. The lane needs a file to open; it does not need a menu.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


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

        zone = page.evaluate("() => location.hash")
        page.set_input_files("#photo", files=[
            {"name": "menu.png", "mimeType": "image/png", "buffer": PNG}])
        page.wait_for_timeout(600)
        picker = page.is_visible(".pickerInput")

        def hits(text):
            page.fill(".pickerInput", text)
            page.wait_for_timeout(700)
            return page.evaluate(
                """() => [...document.querySelectorAll(".pickerHit")].map((b) => ({
                     name: b.querySelector("b").textContent,
                     where: b.querySelector("span").textContent,
                   }))"""
            )

        found = hits(PROBE)
        brand = hits(BRAND)
        # A name we are genuinely not licensed for must say so plainly, and must
        # NOT offer a nearest guess -- the whole point of the index is that this
        # answer is now trustworthy.
        absent = hits("zzzqqnotabar")
        miss = page.evaluate(
            """() => { const p = document.querySelector(".pickerMiss");
                       return p ? p.textContent : ""; }"""
        )
        browser.close()

    names = [h["name"] for h in found]
    bad = []
    if errors:
        bad.append(f"uncaught page error: {errors[0]}")
    if "z=" in zone:
        bad.append(f"a town was already selected, so this proves nothing: {zone!r}")
    if not picker:
        bad.append("the venue picker never opened")
    if WANT not in names:
        bad.append(f"typing {PROBE!r} did not find {WANT!r}: {names}")
    if not any(COLLIDES in n for n in names):
        bad.append(f"the near-collision {COLLIDES!r} was hidden from the "
                   f"submitter: {names}")
    if names and names[0] != WANT:
        bad.append(f"{WANT!r} was not ranked first: {names}")
    if not all(h["where"].strip() for h in found):
        bad.append("a choice was offered with no address or town to tell it apart")
    brand_where = {h["where"] for h in brand}
    if len(brand) < 3 or len(brand_where) < 3:
        bad.append(f"the three {BRAND!r} venues are not separable on screen: {brand}")
    if absent:
        bad.append(f"a name we do not hold still offered a guess: {absent}")
    if "No licensed venue" not in miss:
        bad.append(f"a genuine miss did not say so plainly: {miss!r}")

    for line in bad:
        print(f"  FAIL {line}")
    if not bad:
        print(f"  ok   with no town picked, {PROBE!r} found "
              f"{[h['name'] for h in found]}; {BRAND!r} gave "
              f"{len(brand)} separable venues")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
