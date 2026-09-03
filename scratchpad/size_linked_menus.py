"""Sizing probe: of the venues that publish a window and NO items, how many
link their happy-hour menu as an image the new anchor-text rule can now see?

Read-only. One fetch per venue, of the page the window was already read from.
Writes nothing into data/.
"""
import json, re, sys, os, glob, gzip, urllib.request, concurrent.futures as cf
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ingest'))
import crawl_sites as cs

UA = "happy-hour-finder-ingest/1.0 (+https://paulrenzi.github.io/happy-hour-finder/)"
h = json.load(open('data/crawl_hits.json', encoding='utf-8'))
PRICE = re.compile(r'\$\s?\d|\d+\s?%\s?off|half.?price')

targets = []
for lid, name, site, src in json.load(open('scratchpad/noitem.json', encoding='utf-8')):
    v = h.get(str(lid)) or {}
    hits = v.get('hits') or []
    if not hits or any(PRICE.search(q.get('quote', '')) for q in hits):
        continue
    if v.get('menu_images'):
        continue
    if src:
        targets.append((lid, name, src))
print(f'{len(targets)} venues to probe (window on file, no price text, no image found)')

def probe(t):
    lid, name, url = t
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Encoding': 'gzip'})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read(3_000_000)
            if r.headers.get('Content-Encoding') == 'gzip':
                raw = gzip.decompress(raw)
            html = raw.decode('utf-8', 'replace')
    except Exception as e:
        return (lid, name, url, 'FETCH-FAIL: %s' % type(e).__name__, [])
    return (lid, name, url, 'ok', cs.menu_images(html, url, self_named=True))

hit = []
with cf.ThreadPoolExecutor(max_workers=5) as ex:
    for lid, name, url, status, imgs in ex.map(probe, targets):
        if imgs:
            hit.append((lid, name, imgs))
            print('  HIT %-38s %s' % (name[:38], imgs[0]))
        elif status != 'ok':
            print('  ..  %-38s %s' % (name[:38], status))
print()
print('%d of %d now expose a happy-hour menu image the old rule could not see' % (len(hit), len(targets)))
json.dump(hit, open('scratchpad/linked_menu_hits.json', 'w'), indent=1)
