"""Print the section headers IN ORDER (duplicates preserved) for Today and Tomorrow."""
import mimetypes, os, json
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "web")
BASE = "https://hhf.test/"
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.webkit.launch()
    p = b.new_page(viewport={"width": 390, "height": 844})
    def serve(route):
        rel = route.request.url[len(BASE):].split("?")[0] or "index.html"
        path = os.path.join(WEB, *rel.split("/"))
        if not os.path.isfile(path):
            return route.fulfill(status=404, body="not found")
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.endswith(".js"): ctype = "text/javascript"
        route.fulfill(status=200, content_type=ctype, body=open(path,"rb").read())
    p.route(BASE + "**", serve)
    p.route("**/live/deals.json", lambda r: r.fulfill(status=200, content_type="application/json", body='{"venues":[]}'))
    p.add_init_script('try{localStorage.setItem("origin",JSON.stringify({lat:40.0093,lng:-75.2907,at:Date.now()}))}catch(e){}')
    p.goto(BASE, wait_until="load"); p.wait_for_timeout(3000)
    for day,label in ((0,"TODAY"),(1,"TOMORROW")):
        if day:
            p.click("#days button:nth-child(2)"); p.wait_for_timeout(1200)
        out = p.evaluate("""() => {
          const seq=[]; let cur=null;
          for (const n of document.querySelector("#feed").children) {
            if (n.matches("p.sec")) { cur={h:n.textContent.trim(),n:0}; seq.push(cur); continue; }
            if (n.matches("article.card") && cur) cur.n++;
          }
          const chips=[...document.querySelectorAll("#days button")].map(b=>b.textContent.trim()+(b.getAttribute("aria-pressed")==="true"?"*":""));
          return {seq, chips};
        }""")
        print("==", label, "chips:", out["chips"])
        for s in out["seq"]:
            print("   %-32s %d" % (s["h"], s["n"]))
    b.close()
