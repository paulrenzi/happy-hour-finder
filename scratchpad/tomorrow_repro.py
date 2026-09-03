"""Load the board as a reader who picked TOMORROW, and count the groups.

The report: with a location set and "Tomorrow" picked, most cards file under
"Ends before you'd get there" -- a verdict about arriving in time that cannot
mean anything about a day that has not started.
"""
import mimetypes, os, sys, json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "web")
BASE = "https://hhf.test/"

def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.webkit.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))

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
        page.route("**/live/deals.json", lambda r: r.fulfill(
            status=200, content_type="application/json", body='{"venues":[]}'))

        # Ardmore-ish, so distances are real and driveMin is not null.
        page.add_init_script(
            'try{localStorage.setItem("origin",JSON.stringify('
            '{lat:40.0093,lng:-75.2907,at:Date.now()}))}catch(e){}')

        page.goto(BASE, wait_until="load")
        page.wait_for_timeout(3500)
        for day, label in ((0, "TODAY"), (1, "TOMORROW")):
            if day:
                page.click("#days button:nth-child(2)")
                page.wait_for_timeout(1200)
            out = page.evaluate("""() => {
              const groups = {}; let cur = null;
              for (const n of document.querySelector("#feed").children) {
                if (n.matches("p.sec")) { cur = n.textContent.trim();
                    groups[cur] = groups[cur] || 0; continue; }
                if (n.matches("article.card")) groups[cur] = (groups[cur]||0)+1;
              }
              return {groups, feedKids: document.querySelector("#feed").children.length,
                      text: document.body.innerText.slice(0,400)};
            }""")
            print("== %s ==" % label)
            print(json.dumps(out["groups"], indent=2))
            print("feed children:", out["feedKids"])
        if errs:
            print("PAGE ERRORS:", errs[:3])
        browser.close()

main()
