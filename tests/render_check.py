"""Load the real page in a real engine and assert the board actually paints.

Every check we had was blind to the outage that mattered: HTTP 200 on every
file, every export present, node --check clean -- and a page where nothing ran.
This one asks the only question that counts: are there venues on the board?

Serves web/ through Playwright's router, so it tests the working tree with no
listening socket. Skips if the browser is not installed.
"""

import json
import mimetypes
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "web")
BASE = "https://hhf.test/"
# A real King of Prussia venue with no published hours, so the overlay has to do
# the whole job: find it in the zone base the app has not loaded yet, fetch that
# zone, and patch the deal in.
OVERLAY_LID = "92150"  # bartaco, King of Prussia -- no hours published


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

        # The live overlay, served here rather than from the real Worker: the
        # point is to prove the app APPLIES it, and a test that depends on a
        # deployed service tells you about the network, not the code.
        overlay = {
            "venues": [{
                "lid": OVERLAY_LID,
                "zone_id": "king_of_prussia",
                "deals": [{
                    "type": "happy_hour",
                    "windows": [{"dow": d, "start": "15:00", "end": "17:00"}
                                for d in range(1, 8)],
                    "items": [{"category": "draft", "label": "OVERLAY PROBE DRAFT",
                               "price_usd": 3}],
                    "confidence": "unconfirmed",
                    "last_verified_at": "2026-08-31",
                    "source": {"kind": "photo", "photo_id": "probe",
                               "submitted": "2026-08-31T23:00:00Z"},
                }],
            }]
        }
        page.route(
            "**/live/deals.json",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(overlay)
            ),
        )

        page.goto(BASE, wait_until="load")
        page.wait_for_timeout(3500)

        checks = page.evaluate(
            """() => ({
                 days: document.querySelector("#days").children.length,
                 zones: document.querySelector("#zone").options.length,
                 feed: document.querySelector("#feed").children.length,
                 kicker: document.querySelector("#sectionKicker").textContent,
                 overlay: document.body.innerText.includes("OVERLAY PROBE DRAFT"),
                 // Every card that claims a happy hour, and its identity as a
                 // READER sees it: the name, the town and the window. Nothing
                 // compared the build's own count to what the page paints, so
                 // one bar painting twice was invisible to us and obvious to
                 // anyone scrolling.
                 cards: [...document.querySelectorAll("#feed article.card")]
                   .filter((c) => !c.classList.contains("card-unknown"))
                   .map((c) => [".name", ".zone", ".ends"]
                     .map((sel) => c.querySelector(sel)?.textContent).join(" | ")),
                 // The prices a card actually shows, per bar. Counting CARDS was
                 // blind to the only failure anyone reported: a venue whose menu
                 // we read correctly, painting a card with nothing on it. Folded
                 // items count -- they are in the DOM behind one toggle -- but an
                 // empty list does not.
                 itemsByName: Object.fromEntries(
                   [...document.querySelectorAll("#feed article.card")]
                     .filter((c) => !c.classList.contains("card-unknown"))
                     .map((c) => [
                       [".name", ".zone"].map((sel) =>
                         c.querySelector(sel)?.textContent?.trim()).join(" @ "),
                       [...c.querySelectorAll("ul.items li")].map((li) =>
                         li.textContent.trim()),
                     ])),
               })"""
        )
        browser.close()

    bad = []
    if errors:
        bad.append(f"uncaught page error: {errors[0]}")
    if checks["days"] < 1:
        bad.append("the Day chips never rendered")
    if checks["zones"] < 2:
        bad.append("the Zone picker never filled")
    if checks["feed"] < 1:
        bad.append("the feed is empty")
    if "LOADING" in checks["kicker"].upper():
        bad.append(f'the board is still saying "{checks["kicker"]}"')
    if not checks["overlay"]:
        bad.append("an approved deal from the live overlay never reached the page")

    # The count the build declares, against the count the page paints. One
    # overlay probe is added on top, and it is for a venue with no hours, so it
    # is a card the bundles did not ship.
    with open(os.path.join(WEB, "data", "index.json"), encoding="utf-8") as fh:
        declared = sum(z["with_deals"] for z in json.load(fh)["zones"])
    painted = len(checks["cards"])
    if painted != declared + 1:
        bad.append(f"the build ships {declared} venues with hours (+1 overlay probe) "
                   f"and the page painted {painted} cards")
    # Every venue the build gives items to must SHOW them. The board painting
    # 174 cards said nothing about this, so a venue whose menu we parsed
    # perfectly could ship a blank card and every test stayed green.
    painted_items = checks["itemsByName"]
    shipped = {}
    for fn in sorted(os.listdir(os.path.join(WEB, "data"))):
        if not fn.startswith("zone-"):
            continue
        with open(os.path.join(WEB, "data", fn), encoding="utf-8") as fh:
            zone = json.load(fh)
        for venue in zone["venues"]:
            for deal in venue.get("deals") or []:
                # Keyed on name AND town: three Chickie's & Pete's are three
                # bars, and keying on the name alone made one of them answer
                # for another one's menu.
                if deal.get("items"):
                    key = f"{venue['name'].strip()} @ {zone['name']}"
                    shipped[key] = deal["items"]
    blank = sorted(n for n, items in shipped.items()
                   if items and not painted_items.get(n))
    if blank:
        bad.append(f"{len(blank)} venue(s) ship items and painted an empty card: "
                   f"{blank[:3]}")
    # And the labels have to be the venue's own, not some other bar's.
    for name, items in sorted(shipped.items()):
        got = " || ".join(painted_items.get(name) or [])
        want = str(items[0].get("label") or "").strip()
        if want and got and want.lower() not in got.lower():
            bad.append(f"{name!r} ships {want!r} first and its card shows {got[:60]!r}")
            break

    dupes = sorted({c for c in checks["cards"] if checks["cards"].count(c) > 1})
    if dupes:
        bad.append(f"the same bar is on the board twice: {dupes[:3]}")

    for line in bad:
        print(f"  FAIL {line}")
    if not bad:
        print(f"  ok   {len(shipped)} venues ship items and all painted them; "
              f"board: {checks['zones'] - 1} zones, "
              f"{checks['feed']} feed rows, {painted} deal cards and no bar twice, "
              f"kicker {checks['kicker']!r}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
