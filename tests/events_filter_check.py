"""The Live music chip, RUN in a real engine, over an events overlay we control.

Two faults Paul reported off the live board on 2026-09-05:

  1. events of the wrong kind bleeding into the live-shows filter -- the chip
     asked "does this bar have a band in the next fortnight" and the card then
     printed whichever event came next, so "Live music" advertised Quizzo;
  2. no night-first order -- a show a week out sat above one on tonight, and
     distance never got to break the tie inside a night.

Both are only visible on the painted page: buildFeed can be right while the
card prints something else. So this asks the page, in the browser, with a
location granted -- the path where distance decides the order.

Serves web/ through Playwright's router, like tests/render_check.py, and stubs
every network fetch the page makes. Skips if the browser is not installed.
"""

import json
import mimetypes
import os
import sys
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "web")
BASE = "https://hhf.test/"

# Real Wayne venues, so the overlay lands on venues the board has actually
# loaded. Coordinates are the shipped ones; the origin below is 118 North's
# doorstep, so "nearest" has a known answer.
ORIGIN = {"lat": 40.044905, "lng": -75.38814839999999}
NEAR_LID = "66143"    # 118 North -- the origin itself
MID_LID = "131343"    # Anthony's Coal Fired, ~0.4 mi
FAR_LID = "17574"     # Black Powder Tavern, ~4 mi


def overlay(today, next_week):
    """A band tonight far away, a band tonight next door, a quiz next door
    tonight, and a band next week next door. One right order, and one right
    line on every card."""
    def row(rid, lid, day, kind, act, start):
        return {"id": rid, "lid": lid, "zone_id": "wayne_radnor", "date": day,
                "start": start, "end": None, "set_minutes": None, "act": act,
                "kind": kind, "cover_usd": None, "kitchen_open": None,
                "source_kind": "page", "source_url": "https://example.test/",
                "recurs": None, "until": None}
    return {"venues": {
        FAR_LID: [row("far-band", FAR_LID, today, "live_music", "FAR BAND", "21:00")],
        MID_LID: [row("mid-band", MID_LID, today, "live_music", "MID BAND", "21:00")],
        # The same venue runs a quiz tonight and plays next week: under the
        # music chip it must offer the BAND, and be filed under next week.
        NEAR_LID: [
            row("near-quiz", NEAR_LID, today, "trivia", "NEAR QUIZ", "21:00"),
            row("near-band", NEAR_LID, next_week, "live_music", "NEAR BAND", "21:00"),
        ],
    }}


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  (skipped: playwright not installed)")
        return 0

    # Tonight as the BROWSER will compute it, and late enough that a 9pm show
    # is still ahead of the clock the page reads.
    today = date.today().isoformat()
    next_week = (date.today() + timedelta(days=6)).isoformat()

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
            route.fulfill(status=200, content_type=ctype,
                          body=open(path, "rb").read())

        page.route(BASE + "**", serve)
        # Every off-origin fetch the page makes is stubbed: one left live turns
        # this into a test of the network.
        page.route("**/live/deals.json",
                   lambda r: r.fulfill(status=200, content_type="application/json",
                                       body='{"venues":[]}'))
        page.route("**/live/confirmations.json",
                   lambda r: r.fulfill(status=200, content_type="application/json",
                                       body='{"deals":[]}'))
        page.route("**/live/events.json",
                   lambda r: r.fulfill(status=200, content_type="application/json",
                                       body=json.dumps(overlay(today, next_week))))

        page.goto(BASE, wait_until="load")
        # A location, granted the way the app stores one: the order this test is
        # about is the one distance decides.
        page.evaluate(
            """(o) => localStorage.setItem("origin", JSON.stringify(
                 { lat: o.lat, lng: o.lng, at: Date.now() }))""", ORIGIN)
        # goto() between two #hash URLs of one document does NOT reload, and
        # the hash is read at boot -- so the second navigation is followed by an
        # explicit reload or the board comes up unfiltered.
        page.goto(BASE + "#z=wayne_radnor&f=music", wait_until="load")
        page.reload(wait_until="load")
        page.wait_for_timeout(3500)

        seen = page.evaluate(
            """() => ({
                 sections: [...document.querySelectorAll("#feed p.sec")].map(
                   (e) => e.textContent),
                 kicker: document.querySelector("#sectionKicker").textContent,
                 hero: document.querySelector("#heroCount").textContent,
                 cards: [...document.querySelectorAll("#feed article.card")].map((c) => ({
                   name: c.querySelector(".name")?.textContent,
                   tonight: c.querySelector(".tonight")?.textContent || "",
                 })),
               })""")
        browser.close()

    bad = []
    if errors:
        bad.append(f"uncaught page error: {errors[0]}")

    names = [c["name"] for c in seen["cards"]]
    lines = [c["tonight"] for c in seen["cards"]]

    # 1. Only live music, and every card says WHICH band -- not the quiz the
    #    same venue is running tonight.
    if not lines or not all("BAND" in t for t in lines):
        bad.append("a card under Live music printed something that is not a band: "
                   + "; ".join(f"{n}: {t or '(no line)'}" for n, t in zip(names, lines)))
    if any("QUIZ" in t for t in lines):
        bad.append("the trivia night bled into the live-shows filter")

    # 2. Tonight leads, nearest first inside the night, and next week is last.
    order = [t.split(" · ")[1].split(" ")[0] + " " + t.split(" · ")[1].split(" ")[1]
             if " · " in t else t for t in lines]
    want = ["MID BAND", "FAR BAND", "NEAR BAND"]
    if order != want:
        bad.append(f"the board is ordered {order}, and tonight-then-nearest is {want}")
    if seen["sections"][:1] != ["Tonight"]:
        bad.append(f"the first section is {seen['sections'][:1]}, not ['Tonight']")
    if len(set(seen["sections"])) != len(seen["sections"]):
        bad.append(f"a night's header printed twice: {seen['sections']}")

    # 3. The two summary lines count shows, not happy hours.
    if "tonight" not in seen["hero"].lower() or "tonight" not in seen["kicker"].lower():
        bad.append(f"the summary lines still talk about happy hours: "
                   f"{seen['hero']!r} / {seen['kicker']!r}")

    if bad:
        for b in bad:
            print("  FAIL " + b)
        return 1
    print(f"  ok   Live music: {seen['kicker']} -- " + "; ".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
