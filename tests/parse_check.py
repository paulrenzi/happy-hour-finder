"""Parse every shipped module in a REAL browser engine.

`node --check` reported web/app.js as OK while it contained a string literal
broken across a real newline, so the deployed site could not parse its own
entry point and NOTHING ran -- a fully styled page with empty controls, for a
day, while status codes and export names all looked fine. Node is not the
engine anyone visits this site with. WebKit is.

Skips itself if the browser is not installed, so it never blocks a run that
only touches ingest.
"""

import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = ["lib.js", "app.js", "sw.js"]


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  (skipped: playwright not installed)")
        return 0

    bad = []
    with sync_playwright() as pw:
        try:
            browser = pw.webkit.launch()
        except Exception as exc:
            print(f"  (skipped: webkit not installed -- {str(exc).splitlines()[0]})")
            return 0
        page = browser.new_page()
        page.goto("about:blank")
        for name in MODULES:
            src = io.open(os.path.join(REPO, "web", name), encoding="utf-8").read()
            # A blob module cannot resolve "./lib.js", so a resolution complaint
            # means the file PARSED -- which is all this checks.
            res = page.evaluate(
                """async (src) => {
                     const u = URL.createObjectURL(
                       new Blob([src], { type: "text/javascript" }));
                     try { await import(u); return "ok"; }
                     catch (e) { return e.message || String(e); }
                   }""",
                src,
            )
            ok = res == "ok" or "does not resolve to a valid URL" in res
            print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f" -- {res}"))
            if not ok:
                bad.append(name)
        browser.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
