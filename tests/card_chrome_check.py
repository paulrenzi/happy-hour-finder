"""Look at a real card in a real engine, at phone width, and check it reads.

Everything this asserts was reported by Paul off the live site while every
existing test was green -- a toggle whose caret had been mangled into a control
character, a Directions label clipped by its own button, a card claiming
"unconfirmed" about hours a person had confirmed. None of those are logic bugs,
so no amount of unit testing sees them. They are visible only to something that
draws the page and then measures what it drew.

Serves web/ through Playwright's router, so it tests the working tree.
"""

import io
import json
import mimetypes
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "web")
BASE = "https://hhf.test/"
LID = "130467"  # Dave & Buster's King of Prussia -- 592 characters of small print
LONG = (
    "*PROMOTIONAL. Offer begins 6/2/25. Times and offers vary by location. Offer may be "
    "modified or end at any time without notice. Available in store only and not on to-go "
    "orders. Must be at least 21 to consume alcohol. Please drink responsibly. Other "
    "restrictions may apply. Void where prohibited. See store for details."
)


def stray_control_characters():
    """Scan the shipped text files for characters that cannot be typed.

    The caret on the small-print toggle was written as the CSS escape \25be and
    passed through a shell heredoc, which ate the backslash and left a literal
    0x15 in the stylesheet. Chrome drew it. WebKit dropped the whole declaration
    as invalid, so the browser check was blind to it -- and this is why the file
    itself gets read: no engine has an opinion about a byte that should not be
    in a source file at all.
    """
    bad = []
    for name in ("styles.css", "app.js", "lib.js", "index.html", "sw.js"):
        path = os.path.join(WEB, name)
        if not os.path.isfile(path):
            continue
        for lineno, line in enumerate(io.open(path, encoding="utf-8"), 1):
            for ch in line.rstrip():
                if ord(ch) < 32:
                    bad.append(f"{name}:{lineno} contains control character {ord(ch):#04x}")
                    break
    return bad


def main():
    problems = stray_control_characters()
    for line in problems:
        print(f"  FAIL {line}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  (skipped: playwright not installed)")
        return 1 if problems else 0

    with sync_playwright() as pw:
        try:
            browser = pw.webkit.launch()
        except Exception as exc:
            print(f"  (skipped: webkit not installed -- {str(exc).splitlines()[0]})")
            return 1 if problems else 0

        # A small phone, because that is where a button label runs out of room.
        page = browser.new_page(viewport={"width": 360, "height": 780})
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

        # One deal, always on, with long small print and two confirmations, so
        # every piece of card furniture under test is on the page at once.
        overlay = {
            "venues": [{
                "lid": LID,
                "zone_id": "king_of_prussia",
                "deals": [{
                    "type": "happy_hour",
                    "windows": [{"dow": d, "start": "00:00", "end": "23:59"}
                                for d in range(1, 8)],
                    # Sixteen items, because a menu that reads cleanly is a
                    # WALL of them -- Taku's was -- and the card has to fold.
                    "items": [{"category": "draft", "label": "CHROME PROBE DRAFT",
                               "price_usd": 3}]
                    + [{"category": "draft", "label": f"PROBE ITEM {i}",
                        "price_usd": 4} for i in range(15)],
                    "confidence": "unconfirmed",
                    "last_verified_at": "2026-08-31",
                    "fine_print": LONG,
                    "source": {"kind": "photo", "photo_id": "chrome-probe",
                               "submitted": "2026-08-31T23:00:00Z"},
                }],
            }],
            "confirms": {},
        }
        overlay["confirms"][f"{LID}:happy_hour|" + ",".join(
            sorted(f"{d}:00:00-23:59" for d in range(1, 8))
        )] = {"n": 2, "last": "2026-08-31"}

        page.route(
            "**/live/deals.json",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(overlay)
            ),
        )

        page.goto(BASE, wait_until="load")
        page.wait_for_timeout(3500)

        found = page.evaluate(
            """(probe) => {
                 const card = [...document.querySelectorAll(".card")]
                   .find((c) => c.textContent.includes(probe));
                 if (!card) return { found: false };
                 const fold = card.querySelector(".fineFold");
                 const itemFold = card.querySelector(".itemFold");
                 // A label wider than the box it sits in is a clipped label,
                 // whatever it happens to say.
                 const clipped = [...card.querySelectorAll(".btn")]
                   .filter((b) => b.scrollWidth > b.clientWidth + 1)
                   .map((b) => b.textContent);
                 return {
                   found: true,
                   fold: !!fold,
                   open: fold ? fold.hasAttribute("open") : null,
                   summary: fold ? fold.querySelector("summary").innerText.trim() : "",
                   // The caret that broke was drawn by a pseudo-element, which
                   // innerText cannot see. Ask the engine what it painted.
                   pseudo: fold
                     ? ["::before", "::after"].map((w) =>
                         getComputedStyle(fold.querySelector("summary"), w).content
                       ).join(" ")
                     : "",
                   summaryFullWidth: fold
                     ? fold.querySelector("summary").getBoundingClientRect().width >
                       card.getBoundingClientRect().width - 60
                     : null,
                   bodyShowsPrint: card.innerText.includes("Void where prohibited"),
                   conf: card.querySelector(".conf").textContent,
                   // Chips visible before anything is tapped, and the label on
                   // the fold that holds the rest.
                   shownItems: card.querySelectorAll(".items:not(.itemsMore) li").length,
                   hiddenItems: card.querySelectorAll(".itemsMore li").length,
                   itemFold: itemFold
                     ? itemFold.querySelector("summary").innerText.trim() : "",
                   itemFoldOpen: itemFold ? itemFold.hasAttribute("open") : null,
                   cardText: card.innerText,
                   clipped,
                   creditSpots: card.querySelectorAll(".credit").length,
                   srcNotes: card.querySelectorAll(".srcNote").length,
                 };
               }""",
            "CHROME PROBE DRAFT",
        )
        browser.close()

    bad = list(problems)
    if errors:
        bad.append(f"uncaught page error: {errors[0]}")
    if not found.get("found"):
        bad.append("the probe card never rendered")
    else:
        if not found["fold"]:
            bad.append("592 characters of small print printed without a toggle")
        if found["open"]:
            bad.append("the small print is open by default")
        if found["bodyShowsPrint"]:
            bad.append("the folded small print is showing anyway")
        # The bug: "\25be" through a shell heredoc shipped a literal 0x15.
        for ch in found["summary"] + found["pseudo"]:
            if ord(ch) < 32 or 0x7F <= ord(ch) < 0xA0:
                bad.append(f"the toggle label contains control character {ord(ch):#04x}")
        if not found["summary"]:
            bad.append("the toggle has no label")
        if found["summaryFullWidth"]:
            bad.append("the toggle is taking a whole line to itself")
        if found["clipped"]:
            bad.append(f"button label clipped at 360px: {found['clipped']}")
        if "confirmed" not in found["conf"]:
            bad.append(f"two people confirmed it and the card says {found['conf']!r}")
        if found["shownItems"] != 3:
            bad.append(f"16 items and the card shows {found['shownItems']} before the fold")
        if found["hiddenItems"] != 13:
            bad.append(f"the fold holds {found['hiddenItems']} items, expected 13")
        if found["itemFold"] != "+13 more":
            bad.append(f"the item fold reads {found['itemFold']!r}")
        if found["itemFoldOpen"]:
            bad.append("the price list is unfolded by default")
        # The word tested badly on a real reader: it was heard as a doubt about
        # the hours rather than a statement about their age.
        if "nconfirmed" in found["cardText"]:
            bad.append("the card still says 'unconfirmed' at a reader")
        if found["creditSpots"] or found["srcNotes"]:
            bad.append("the card still carries its own credit/provenance line")

    for line in bad:
        print(f"  FAIL {line}")
    if not bad:
        print(f"  ok   card reads at 360px: toggle {found['summary']!r}, "
              f"conf {found['conf']!r}, items {found['itemFold']!r}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
