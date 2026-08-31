"""A tab that has been sitting open must not still be showing this afternoon.

Paul, at 7:33pm: "several listings under today are no longer available." The
board renders once at load and on a 30-second timer -- and a timer is exactly
what a backgrounded tab, a slept laptop, or a discarded-and-restored tab does
not get. So the page came back painted with whatever it said hours ago: a
3-6pm window still reading "Live now" at half past seven, which is the one
thing this product exists not to do.

This moves the wall clock forward WITHOUT letting a single timer fire -- the
slept-laptop case -- and asserts the board restamps itself on wake.

Serves web/ through Playwright's router, so it tests the working tree with no
listening socket. Skips if the browser is not installed.
"""

import mimetypes
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "web")
BASE = "https://hhf.test/"
AFTERNOON = "2026-09-01T20:00:00Z"  # 4:00pm ET, the middle of happy hour
EVENING = "2026-09-02T00:05:00Z"    # 8:05pm ET, after nearly all of it is over


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  (skipped: playwright not installed)")
        return 0

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:
            print(f"  (skipped: chromium not installed -- {str(exc).splitlines()[0]})")
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

        ctx = browser.new_context(
            viewport={"width": 390, "height": 844}, timezone_id="America/New_York"
        )
        page = ctx.new_page()
        page.route(BASE + "**", serve)
        page.clock.install(time=AFTERNOON)
        page.goto(BASE, wait_until="networkidle")
        page.clock.run_for(3000)

        def live_count():
            m = re.search(r"(\d+)\s+happy hour", page.inner_text("#heroCount"))
            return int(m.group(1)) if m else 0

        afternoon = live_count()
        if afternoon < 5:
            print(f"  FAIL: expected a busy 4pm board, got {afternoon} live")
            return 1

        # The wall clock moves; no timer fires. This is the slept laptop.
        page.clock.set_system_time(EVENING)
        stale = page.inner_text("#clock")

        page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_timeout(300)
        woken, live_now = page.inner_text("#clock"), live_count()
        browser.close()

    if "8:05" not in woken:
        print(f"  FAIL: the board still reads {woken!r} at 8:05pm (was {stale!r})")
        return 1
    if live_now >= afternoon:
        print(f"  FAIL: {live_now} live at 8:05pm, same as the 4pm board")
        return 1
    print(f"  ok   woke to {woken}: {afternoon} live at 4pm -> {live_now} at 8:05pm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
