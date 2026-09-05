"""Prove `near=` actually re-orders the board, and says what it ordered from.

The feature is a link dead-shows emits: open this town's board sorted by
distance from the show's venue. Three things have to be true at once, and only
the first is visible from the code:

  1. the cards come out in ascending distance FROM THE LINK'S COORDINATE,
  2. the page says so -- every "0.4 mi" on the board is from a concert hall the
     reader may be nowhere near, and the default headline promises "near you",
  3. and the origin survives writeHash(), which rewrites the URL wholesale on
     the first control change.

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

ZONE = "king_of_prussia"


def origin_for(zone):
    """A real venue in the zone to sort around, and its coordinate.

    Derived from the shipped bundle rather than hardcoded: a fixture pinned to
    one venue rots the moment that venue's licence lapses out of the board.
    """
    board = json.load(open(os.path.join(WEB, "data", f"zone-{zone}.json"),
                           encoding="utf-8"))
    for v in board["venues"]:
        if v.get("lat") is not None and v.get("lng") is not None:
            return v
    raise SystemExit(f"near_check: no coordinated venue in {zone}")


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  (skipped: playwright not installed)")
        return 0

    anchor = origin_for(ZONE)
    # A name with an apostrophe and a space where possible: `from=` is
    # percent-encoded by the linker and read back through URLSearchParams, and
    # a label that survives that round trip is the whole proof of the decode.
    label = anchor["name"]
    near = f"{anchor['lat']:.6f},{anchor['lng']:.6f}"

    with sync_playwright() as pw:
        try:
            browser = pw.webkit.launch()
        except Exception as exc:
            print(f"  (skipped: webkit not installed -- {str(exc).splitlines()[0]})")
            return 0

        def serve(route):
            rel = route.request.url[len(BASE):].split("?")[0] or "index.html"
            path = os.path.join(WEB, *rel.split("/"))
            if not os.path.isfile(path):
                return route.fulfill(status=404, body="not found")
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if path.endswith(".js"):
                ctype = "text/javascript"
            route.fulfill(status=200, content_type=ctype, body=open(path, "rb").read())

        def open_board(hash_url, seed_origin=None):
            """A FRESH page per URL.

            The app reads its hash once, at boot -- there is no hashchange
            listener. Reusing one page and goto()-ing between hashes is a
            same-document navigation, so every result after the first describes
            the FIRST url. That produced 12 of 15 false failures once already.
            """
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.route(BASE + "**", serve)
            # Any fetch the page makes that we do not stub is a hang or a
            # console error in a sandbox with no network.
            # The two live overlays have DIFFERENT shapes -- deals.json's
            # `venues` is a list, events.json's is a map. Feeding one body to
            # both throws "{} is not iterable" out of boot(), which reads as a
            # page error on every check including the ones that should pass.
            page.route("**/live/deals.json", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body='{"venues":[]}'))
            page.route("**/live/events.json", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body='{"venues":{}}'))
            if seed_origin:
                page.add_init_script(
                    "localStorage.setItem('origin', JSON.stringify(%s))"
                    % json.dumps({**seed_origin, "at": 10 ** 13})
                )
            page.goto(BASE + hash_url, wait_until="load")
            page.wait_for_timeout(3500)
            return page, errs

        failures = []

        def check(cond, msg):
            if not cond:
                failures.append(msg)

        # The board bands rows by when the deal is on -- "Live now", "Starting
        # soon", "Later today" -- and ranks by distance INSIDE each band. That
        # is the real contract: a bar that is open now outranks a nearer one
        # that is shut, in every sort. Asserting one globally ascending list
        # would be asserting a product decision that was never made, and would
        # fail against a board that is behaving correctly.
        SECTIONED = """() => {
             const out = []; let sec = null;
             for (const n of document.querySelectorAll('#feed > *')) {
               if (n.classList.contains('sec')) { sec = n.textContent; continue; }
               if (!n.classList.contains('card')) continue;
               const t = n.textContent || '';
               // fmtMiles() prints "here" under a tenth of a mile, so the
               // anchor venue itself has no digits to match.
               const m = t.match(/(\\d+(?:\\.\\d+)?)\\s*mi\\b/);
               const mi = m ? Number(m[1]) : (/\\bhere\\b/.test(t) ? 0 : null);
               if (mi !== null) out.push([sec, mi]);
             }
             return out;
           }"""

        def by_section(page):
            rows = page.evaluate(SECTIONED)
            groups = {}
            for sec, mi in rows:
                groups.setdefault(sec, []).append(mi)
            return rows, groups

        # ---- 1. the board sorts from the link's coordinate ----------------
        page, errs = open_board(f"#z={ZONE}&near={near}&from={label}")
        check(not errs, f"page errors on the near= link: {errs[:2]}")

        head = page.text_content("#sectionHeadline") or ""
        check(label in head,
              f"headline does not name the origin: {head!r} lacks {label!r}")
        check("near you" not in head.lower(),
              f"headline still promises the reader's own location: {head!r}")

        check(page.eval_on_selector("#sort", "s => s.value") == "nearest",
              "the sort control does not read 'Nearest' -- the board would be "
              "ordered by distance while the picker claimed otherwise")

        rows, groups = by_section(page)
        check(len(rows) >= 3,
              f"only {len(rows)} cards carried a distance -- nothing to prove "
              "an order with")
        for sec, mi in groups.items():
            check(mi == sorted(mi),
                  f"cards under {sec!r} are not in ascending distance: {mi[:8]}")

        # The anchor is itself a venue on this board, so somewhere in the list
        # is a card zero miles from the origin -- and under the link's origin it
        # must lead its own section. This is the assertion that would fail if
        # `near=` were parsed and then ignored.
        allm = [mi for _, mi in rows]
        check(allm and min(allm) < 0.2,
              f"no card is at the origin, but the origin IS a venue on this "
              f"board -- nearest anywhere is {min(allm) if allm else None} mi")
        anchor_sec = next((s for s, mi in rows if mi < 0.2), None)
        check(anchor_sec is not None and groups[anchor_sec][0] < 0.2,
              f"the venue at the origin does not lead its own section "
              f"({anchor_sec!r} starts at {groups.get(anchor_sec, [None])[0]})")

        # ---- 2. it survives writeHash() ----------------------------------
        # Changing a control rewrites the URL from state. If near= is dropped
        # there, the board stays sorted while the URL forgets, and a share of
        # that link comes back sorted from nothing.
        page.select_option("#sort", "value")
        page.wait_for_timeout(400)
        page.select_option("#sort", "nearest")
        page.wait_for_timeout(600)
        url = page.evaluate("location.hash")
        check("near=" in url, f"near= was dropped from the url on a control "
                              f"change: {url!r}")
        check(label.split()[0] in page.text_content("#sectionHeadline"),
              "the headline forgot the origin after a control change")
        page.close()

        # ---- 3. a stored 'Near me' location must NOT win over the link ----
        # restoreLocation() runs after readHash() at boot. A reader who used
        # Near me in the last 12 hours would otherwise open this link and get
        # the board ranked from their own kitchen, headline still naming the
        # venue -- silent, and wrong in the one way the link exists to prevent.
        far = {"lat": anchor["lat"] + 0.5, "lng": anchor["lng"] + 0.5}
        page, errs = open_board(f"#z={ZONE}&near={near}&from={label}",
                                seed_origin=far)
        check(not errs, f"page errors with a stored origin: {errs[:2]}")
        srows, _ = by_section(page)
        smiles = [mi for _, mi in srows]
        check(smiles and min(smiles) < 0.2,
              f"a stored location overrode the link's origin: nearest card "
              f"anywhere is {min(smiles) if smiles else None} mi, and the "
              "origin is a venue on this board")
        page.close()

        # ---- 4. no near= is still the ordinary board ----------------------
        page, errs = open_board(f"#z={ZONE}")
        check(not errs, f"page errors on the plain board: {errs[:2]}")
        plain = page.text_content("#sectionHeadline") or ""
        check("near you" in plain.lower(),
              f"the plain board's headline changed: {plain!r}")
        page.close()

        # ---- 5. a junk coordinate is refused, not ranked from (0,0) -------
        page, errs = open_board(f"#z={ZONE}&near=banana&from={label}")
        check(not errs, f"page errors on a junk near=: {errs[:2]}")
        junk = page.text_content("#sectionHeadline") or ""
        check("near you" in junk.lower(),
              f"a junk coordinate was accepted as an origin: {junk!r}")
        page.close()

        browser.close()

    if failures:
        print("near_check FAILED")
        for f in failures:
            print("  - " + f)
        return 1
    print(f"near_check ok: board sorts from {label}, says so, and keeps it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
