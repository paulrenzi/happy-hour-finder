"""Last untested route: are the prices PIXELS?

menu_images() only takes an image whose filename, alt text or anchor words name
a menu. A venue that posts its happy-hour board as IMG_4471.jpg on a page whose
URL is /happy-hour has published it, and no filename rule can see that.

This counts, per venue, every image on a page that names the hour -- ignoring
what the file is called -- and reports the ones big enough to be a menu board.

Read-only. Fetches image HEADERS only (Range: first 32KB) to size them; never
downloads a menu, never writes into data/.
"""
import json, os, re, sys, struct, threading, urllib.parse, concurrent.futures as cf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ingest"))
import crawl_sites as cs
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "scratchpad", "pixel_sizing.json")

IMG_SRC = re.compile(r'<img\s[^>]*?src=["\']([^"\']+)["\']', re.I)
SRCSET = re.compile(r'<(?:img|source)\s[^>]*?srcset=["\']([^"\']+)["\']', re.I)
BG = re.compile(r'url\((["\']?)(https?://[^)"\']+\.(?:jpe?g|png|webp))\1\)', re.I)
SKIP = re.compile(r"logo|icon|favicon|sprite|avatar|badge|arrow|spinner|"
                  r"pixel|tracking|\.svg($|\?)|\.gif($|\?)", re.I)
IMGEXT = re.compile(r"\.(jpe?g|png|webp)($|\?)", re.I)

MIN_PX = 600          # a menu board is not a thumbnail
MIN_BYTES = 40_000

_robots = {}
_lock = threading.Lock()


def dims(head):
    """(w, h) from the first bytes of a PNG / JPEG / WEBP, or None."""
    try:
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        if head[:2] == b"\xff\xd8":
            i = 2
            while i < len(head) - 9:
                if head[i] != 0xFF:
                    i += 1
                    continue
                m = head[i + 1]
                if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                         0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", head[i + 5:i + 9])
                    return w, h
                if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
                    i += 2
                    continue
                i += 2 + struct.unpack(">H", head[i + 2:i + 4])[0]
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            if head[12:16] == b"VP8X":
                w = int.from_bytes(head[24:27], "little") + 1
                h = int.from_bytes(head[27:30], "little") + 1
                return w, h
    except Exception:  # noqa: BLE001
        pass
    return None


def measure(session, url):
    try:
        r = session.get(url, timeout=20, stream=True,
                        headers={"User-Agent": cs.UA, "Range": "bytes=0-32767"})
        if r.status_code not in (200, 206):
            return None
        head = r.raw.read(32768, decode_content=True)
        r.close()
        total = r.headers.get("Content-Range", "")
        size = int(total.split("/")[-1]) if "/" in total else \
            int(r.headers.get("Content-Length") or 0)
        return {"url": url, "bytes": size, "wh": dims(head)}
    except Exception:  # noqa: BLE001
        return None


def images_on(html, page_url):
    out, seen = [], set()
    for m in IMG_SRC.finditer(html):
        out.append(m.group(1))
    for m in SRCSET.finditer(html):
        for part in m.group(1).split(","):
            u = part.strip().split()[0] if part.strip() else ""
            if u:
                out.append(u)
    for m in BG.finditer(html):
        out.append(m.group(2))
    keep = []
    for u in out:
        full = urllib.parse.urljoin(page_url, u.strip()).split("#")[0]
        if not IMGEXT.search(full) or SKIP.search(full) or full in seen:
            continue
        seen.add(full)
        keep.append(full)
    return keep[:25]


def one(row):
    lid, name, site, src = row
    r = {"lid": lid, "name": name, "url": src, "status": "", "hh_page": False,
         "n_images": 0, "big": [], "already": []}
    with _lock:
        ok = cs.allowed(src, _robots)
    if not ok:
        r["status"] = "robots"
        return r
    try:
        html, err, landed = cs.get(requests.Session(), src)
    except Exception as e:  # noqa: BLE001
        r["status"] = "error:" + type(e).__name__
        return r
    if err:
        r["status"] = err
        return r
    r["status"] = "ok"
    lines, _s, _e = cs.text_lines_emph(html)
    try:
        hh = set(cs.hh_sections(html, "\n".join(lines)) or ())
    except Exception:  # noqa: BLE001
        hh = set()
    r["hh_page"] = bool(hh) or cs.page_is_hh(src)
    if not r["hh_page"]:
        return r
    r["already"] = list(cs.menu_images(html, landed or src, self_named=True))
    cand = [u for u in images_on(html, landed or src) if u not in r["already"]]
    r["n_images"] = len(cand)
    session = requests.Session()
    for u in cand[:12]:
        m = measure(session, u)
        if not m:
            continue
        w, h = (m["wh"] or (0, 0))
        if max(w, h) >= MIN_PX or m["bytes"] >= MIN_BYTES:
            r["big"].append(m)
    return r


def main():
    pop = json.load(open(os.path.join(REPO, "scratchpad", "the80.json"), encoding="utf-8"))
    if "--limit" in sys.argv:
        pop = pop[: int(sys.argv[sys.argv.index("--limit") + 1])]
    print("looking for menu boards the filename rule cannot see, over %d venues\n" % len(pop),
          flush=True)
    res = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(one, pop):
            res.append(r)
            tag = "HIT" if r["big"] else "   "
            print("%s %-34s %-12s hh_page=%-5s imgs=%2d big=%d" % (
                tag, r["name"][:34], r["status"][:12], r["hh_page"],
                r["n_images"], len(r["big"])), flush=True)
    tmp = OUT + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)

    hh = [r for r in res if r["hh_page"]]
    hit = [r for r in res if r["big"]]
    print("\n" + "=" * 74)
    print("%d of %d venues gave us a page that names the hour" % (len(hh), len(res)))
    print("%d of those carry an image big enough to be a menu board that" % len(hit))
    print("   menu_images() does not take (filename/alt/anchor name nothing)")
    print("=" * 74)
    for r in sorted(hit, key=lambda x: -len(x["big"])):
        print("\n  %s  (%d)" % (r["name"], len(r["big"])))
        print("    %s" % r["url"])
        for m in r["big"][:4]:
            print("      %-10s %s" % (("%dx%d" % m["wh"]) if m["wh"] else "%dKB" % (m["bytes"] // 1024),
                                      m["url"][:90]))


main()
