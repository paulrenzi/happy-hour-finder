"""Accounts, RUN in a real engine against a stubbed Worker.

Signing in, saving a place, filtering the board down to what you saved, and
writing a private note on a bar and on one night at it -- asserted on the
painted page, because every one of those is a claim the SCREEN makes and only
the screen can be wrong about.

The Worker is stubbed here rather than called: what is being tested is that the
board asks the right thing and believes the answer. worker/accounts.js is
tested separately in tests/accounts.test.mjs.

Skips if the browser is not installed.
"""

import json
import mimetypes
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "web")
BASE = "https://hhf.test/"
SESSION = "test-session-token-0123456789abcdef"

# A Wayne bar with published hours, so the card it paints is a deal card.
SAVED_LID = "17574"       # Black Powder Tavern


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  (skipped: playwright not installed)")
        return 0

    # What the stub Worker holds. The page's writes land here, and /account/me
    # is served from it, so the test can assert on what the SERVER was told
    # rather than only on what the screen says.
    store = {"favorites": [], "notes": {}}

    with sync_playwright() as pw:
        try:
            browser = pw.webkit.launch()
        except Exception as exc:
            print(f"  (skipped: webkit not installed -- {str(exc).splitlines()[0]})")
            return 0

        # ONE context, many pages: localStorage is per-context, and the
        # session and the saved-list cache have to survive from one navigation
        # to the next exactly as they do for a reader who reopens the board.
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        errors = []

        def serve(route):
            rel = route.request.url[len(BASE):].split("?")[0] or "index.html"
            path = os.path.join(WEB, *rel.split("/"))
            if not os.path.isfile(path):
                return route.fulfill(status=404, body="not found")
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if path.endswith(".js"):
                ctype = "text/javascript"
            route.fulfill(status=200, content_type=ctype, body=open(path, "rb").read())


        def account(route):
            req = route.request
            url = req.url
            # An unauthenticated read must 401 -- the page signs itself out on
            # that, and this check would rather see it than a silent success.
            auth = req.headers.get("authorization", "")
            if url.endswith("/account/me"):
                if auth != f"Bearer {SESSION}":
                    return route.fulfill(status=401, content_type="application/json",
                                         body='{"error":"Sign in first."}')
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({
                                         "email": "paul@example.com",
                                         "favorites": store["favorites"],
                                         "notes": [{"kind": k.split(":")[0],
                                                    "id": k.split(":", 1)[1], "body": b}
                                                   for k, b in store["notes"].items()],
                                     }))
            if url.endswith("/account/favorite"):
                body = json.loads(req.post_data or "{}")
                lid = str(body.get("lid"))
                if body.get("on"):
                    if lid not in store["favorites"]:
                        store["favorites"].append(lid)
                elif lid in store["favorites"]:
                    store["favorites"].remove(lid)
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({"lid": lid, "on": bool(body.get("on"))}))
            if url.endswith("/account/note"):
                body = json.loads(req.post_data or "{}")
                key = f"{body.get('kind')}:{body.get('id')}"
                if body.get("body"):
                    store["notes"][key] = body["body"]
                else:
                    store["notes"].pop(key, None)
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({"saved": bool(body.get("body"))}))
            return route.fulfill(status=404, content_type="application/json", body="{}")

        # A FRESH PAGE per URL, not a second goto.
        #
        # The board reads its whole state -- the town, the chip, and the
        # sign-in token -- out of the #hash AT BOOT, and goto() between two
        # hash URLs of one document does not reload. A second goto would
        # navigate the address bar and run none of the code this check is
        # about, silently. (A reload instead aborts the zone fetches already in
        # flight and reports them as page errors.)
        def board(frag):
            p = ctx.new_page()
            p.on("pageerror", lambda e: errors.append(str(e)))
            p.route(BASE + "**", serve)
            p.route("**/live/deals.json", lambda r: r.fulfill(
                status=200, content_type="application/json", body='{"venues":[]}'))
            p.route("**/live/confirmations.json", lambda r: r.fulfill(
                status=200, content_type="application/json", body='{"deals":[]}'))
            p.route("**/live/events.json", lambda r: r.fulfill(
                status=200, content_type="application/json", body='{"venues":{}}'))
            p.route("**/account/**", account)
            p.goto(BASE + frag, wait_until="load")
            p.wait_for_timeout(2800)
            return p

        bad = []

        # ---- 1. signed out: the Saved chip is not offered ----------------
        page = board("#z=wayne_radnor")
        chips = page.evaluate(
            """() => [...document.querySelectorAll("#filters .chip")].map((c) => c.textContent)""")
        if "Saved" in chips:
            bad.append(f"signed out, the Saved chip was offered: {chips}")
        if not page.evaluate("""() => !!document.querySelector("#feed .btn.save")"""):
            bad.append("no card carried a Save control")

        # ---- 2. the sign-in link signs you in ---------------------------
        # The session arrives in the FRAGMENT, exactly as worker/accounts.js
        # redirects it, and must be consumed out of the address bar.
        page.close()
        page = board(f"#z=wayne_radnor&signin={SESSION}")
        if SESSION in page.url:
            bad.append(f"the session token was left in the address bar: {page.url}")
        chips = page.evaluate(
            """() => [...document.querySelectorAll("#filters .chip")].map((c) => c.textContent)""")
        if "Saved" not in chips:
            bad.append(f"signed in, the Saved chip is still missing: {chips}")

        # ---- 3. saving a bar, and the Saved chip showing only it --------
        saved_name = page.evaluate(
            """(lid) => {
                 const cards = [...document.querySelectorAll("#feed article.card")];
                 for (const c of cards) {
                   const b = c.querySelector(".btn.save");
                   if (!b) continue;
                   if (c.querySelector(".name").textContent.includes("Black Powder")) {
                     b.click();
                     return c.querySelector(".name").textContent;
                   }
                 }
                 return null;
               }""", SAVED_LID)
        page.wait_for_timeout(1200)
        if store["favorites"] != [SAVED_LID]:
            bad.append(f"the Worker was told {store['favorites']}, not ['{SAVED_LID}']")

        page.evaluate(
            """() => [...document.querySelectorAll("#filters .chip")]
                      .find((c) => c.textContent === "Saved").click()""")
        page.wait_for_timeout(1200)
        names = page.evaluate(
            """() => [...document.querySelectorAll("#feed article.card .name")].map((n) => n.textContent)""")
        if names != [saved_name]:
            bad.append(f"the Saved board shows {names}, and one bar was saved: {saved_name}")

        # ---- 4. a private note on the bar -------------------------------
        page.evaluate("""() => document.querySelector("#feed article.card .shot").click()""")
        page.wait_for_timeout(800)
        typed = "Ask for the back room."
        wrote = page.evaluate(
            """(text) => {
                 const ta = document.querySelector("#sheetBody .noteBox textarea");
                 if (!ta) return null;
                 ta.value = text;
                 ta.dispatchEvent(new Event("blur"));
                 return ta.id;
               }""", typed)
        page.wait_for_timeout(1200)
        if not wrote:
            bad.append("the venue sheet offered no note box to a signed-in reader")
        elif store["notes"].get(f"venue:{SAVED_LID}") != typed:
            bad.append(f"the note the Worker was sent is {store['notes']!r}")

        # ---- 5. the note survives a reload, from the cache and the wire --
        page.close()
        page = board("#z=wayne_radnor&f=saved")
        page.evaluate("""() => document.querySelector("#feed article.card .shot").click()""")
        page.wait_for_timeout(800)
        back = page.evaluate(
            """() => (document.querySelector("#sheetBody .noteBox textarea") || {}).value""")
        if back != typed:
            bad.append(f"after a reload the note read {back!r}, not {typed!r}")

        browser.close()

    if errors:
        bad.insert(0, f"uncaught page error: {errors[0]}")
    if bad:
        for b in bad:
            print("  FAIL " + b)
        return 1
    print(f"  ok   signed in, saved 1 bar, filtered to it, and its note survived a reload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
