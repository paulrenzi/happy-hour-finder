"""Read-only: how many BOARD cards were built off a page that redirected away?

Writes nothing. Fetches each published venue's own source URLs once, follows
redirects, and asks landed_in_another_town() -- the guard now in crawl_sites --
whether the page we read was another branch's.
"""
import json, sys, time
sys.path.insert(0, "ingest")
import crawl_sites as cs
import requests

sites = cs.frontier()
cs._towns["slugs"] = {t for t in (cs.town_slug(v.get("address")) for v in sites.values()) if t}
deals = json.load(open("data/deals_extracted.json", encoding="utf-8"))

urls = {}
for v in deals["venues"]:
    for d in v.get("deals") or []:
        u = (d.get("source") or {}).get("url")
        if u:
            urls.setdefault(v["lid"], set()).add(u)

s = requests.Session()
wrong, moved, checked, failed = [], 0, 0, 0
for lid, us in sorted(urls.items()):
    addr = (sites.get(lid) or {}).get("address")
    for u in sorted(us):
        checked += 1
        try:
            _, err, landed = cs.get(s, u)
        except Exception as e:
            failed += 1
            continue
        if landed != u:
            moved += 1
        sent = cs.landed_in_another_town(u, landed, addr)
        if sent:
            wrong.append((lid, (sites.get(lid) or {}).get("name"), u, landed, sent))
            print("WRONG", lid, (sites.get(lid) or {}).get("name"), u, "->", landed, flush=True)
        time.sleep(0.4)

print(f"\nchecked {checked} source URLs, {failed} unreachable, {moved} redirected, "
      f"{len(wrong)} landed in another town")
json.dump(wrong, open("scratchpad/redirect_class.json", "w", encoding="utf-8"), indent=1)
