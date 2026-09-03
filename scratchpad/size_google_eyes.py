"""Sizing probe: THE SOURCE THAT EXISTS WHEN THE VENUE WRITES NOTHING.

44 of the 78 'hour but no items' venues publish no price anywhere on their own
site (FINDING-THE-78-...). Their customers do: a diner photographs the
happy-hour chalkboard and it lands on the venue's Google listing, and a
reviewer writes "$5 margaritas at happy hour". Neither is on the website, so
no crawler change can reach either. This asks Google's listing for both.

Per venue, ONE Places Text Search (photos + reviews ride the same call), up to
ten photo downloads, and one vision read per photo on the `claude` CLI
subscription -- the same reader ingest/extract_photo_deals.py already uses on
submitted photos. A photo counts only if the model sees a menu/board/sign that
NAMES a happy hour AND carries a price. A review counts only if one sentence
carries both.

Google list price: $0.032 per search + $0.007 per photo => ~$0.10 a venue.
Nothing is called without --spend. Every response is cached under
scratchpad/google_eyes/ so a re-run is free. Nothing is written into data/.

    python scratchpad/size_google_eyes.py --zone center_city            # price it
    python scratchpad/size_google_eyes.py --zone center_city --spend    # do it
    python scratchpad/size_google_eyes.py --zone center_city --report   # cached only
"""
import json, os, re, sys, shutil, subprocess, threading, concurrent.futures as cf

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ingest"))
import fetch_venue_photos as fvp   # name_agrees, load_key
import requests

CACHE = os.path.join(REPO, "scratchpad", "google_eyes")
OUT = os.path.join(REPO, "scratchpad", "google_eyes_sizing.json")
SEARCH = "https://places.googleapis.com/v1/places:searchText"
MASK = ("places.id,places.displayName,places.formattedAddress,places.websiteUri,"
        "places.photos,places.reviews")
USD_SEARCH, USD_PHOTO = 0.032, 0.007
PHOTOS_PER_VENUE = 10
MAX_W = 1200          # a chalkboard has to be legible
VISION_MODEL = os.environ.get("HHF_VISION_MODEL", "sonnet")

HH = re.compile(r"happy\s*hour|social\s*hour|power\s*hour|appy\s*hour", re.I)
MONEY = re.compile(r"\$\s?\d")

PROMPT = """Read the image at this path with your Read tool: {path}

You are a reader, not an author. Answer about what is PRINTED or WRITTEN in
the image only. Reply with ONE JSON object and nothing else, no code fence:

{{
  "kind": one of "menu_board" (chalkboard / letterboard / sign),
          "printed_menu" (paper or laminated menu, table tent, flyer),
          "screen" (a TV or website shown on a screen),
          "other" (food, room, people, storefront, anything not a menu),
  "names_happy_hour": true if the words "happy hour" (or "social hour",
          "power hour") are visible, else false,
  "hh_lines": ["every visible line that names the happy hour or its days and
          times, verbatim"],
  "priced_lines": ["every visible line that carries a price, verbatim, up to
          twenty. A price is a number a customer pays -- $5, 5, 5.50, 'half
          price'. Not an ABV, a year, an ounce count or a phone number."]
}}
"""

_lock = threading.Lock()


def population(zone, limit):
    vb = json.load(open(os.path.join(REPO, "data", "venue_base.json"), encoding="utf-8"))
    pop = json.load(open(os.path.join(REPO, "scratchpad", "the80.json"), encoding="utf-8"))
    rows = []
    for lid, name, site, src in pop:
        v = vb.get(lid)
        if not v or (zone and v.get("zone_id") != zone):
            continue
        rows.append({"lid": lid, "name": v["name"], "plcb_name": v.get("plcb_name", ""),
                     "address": v["address"], "zone": v["zone_id"], "site": site, "src": src})
    return rows[:limit] if limit else rows


def cached(lid):
    p = os.path.join(CACHE, lid + ".json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def save(lid, doc):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, lid + ".json")
    with open(p + ".new", "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(p + ".new", p)


def search(key, venue):
    r = requests.post(SEARCH, headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": MASK},
                      json={"textQuery": f"{venue['name']}, {venue['address']}",
                            "maxResultCount": 3}, timeout=30)
    r.raise_for_status()
    for p in r.json().get("places", []):
        if fvp.name_agrees(venue, p):
            return p
    return None


def download(key, photo_name, dest):
    if os.path.exists(dest):
        return True
    r = requests.get(f"https://places.googleapis.com/v1/{photo_name}/media",
                     params={"maxWidthPx": MAX_W, "key": key}, timeout=60)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        return False
    with open(dest + ".new", "wb") as fh:
        fh.write(r.content)
    os.replace(dest + ".new", dest)
    return True


def look(path):
    """One vision read. Same CLI shape as extract_photo_deals.ask()."""
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("`claude` not on PATH")
    proc = subprocess.run(
        [exe, "-p", "--model", VISION_MODEL, "--output-format", "json",
         "--allowedTools", "Read", "--setting-sources", "",
         "--exclude-dynamic-system-prompt-sections"],
        input=PROMPT.format(path=path), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("claude -p exited %d: %s" % (proc.returncode, proc.stderr[:200]))
    body = json.loads(proc.stdout).get("result") or ""
    m = re.search(r"\{.*\}", body, re.S)
    if not m:
        raise ValueError("no JSON in reply: " + body[:120])
    return json.loads(m.group(0))


def review_hits(place):
    out = []
    for rv in place.get("reviews") or []:
        text = (rv.get("text") or {}).get("text") or ""
        for sent in re.split(r"(?<=[.!?])\s+|\n", text):
            if HH.search(sent) and MONEY.search(sent):
                out.append({"when": rv.get("relativePublishTimeDescription", ""),
                            "quote": sent.strip()[:220]})
    return out


def one(venue, key, spend):
    lid = venue["lid"]
    doc = cached(lid) or {"lid": lid, "name": venue["name"], "zone": venue["zone"],
                          "status": "", "place": None, "reviews": [], "photos": []}
    if doc["place"] is None and spend and doc["status"] != "no_match":
        try:
            p = search(key, venue)
        except Exception as e:  # noqa: BLE001
            doc["status"] = "error:" + type(e).__name__
            save(lid, doc)
            return doc
        if not p:
            doc["status"] = "no_match"
            save(lid, doc)
            return doc
        doc["place"] = {"id": p.get("id"), "name": p["displayName"]["text"],
                        "address": p.get("formattedAddress", ""), "site": p.get("websiteUri", ""),
                        "n_photos": len(p.get("photos") or []),
                        "n_reviews": len(p.get("reviews") or [])}
        doc["reviews"] = review_hits(p)
        doc["photos"] = [{"name": ph["name"], "file": "", "read": None}
                         for ph in (p.get("photos") or [])[:PHOTOS_PER_VENUE]]
        doc["status"] = "ok"
        save(lid, doc)
    if doc["place"] is None:
        return doc
    pdir = os.path.join(CACHE, lid)
    os.makedirs(pdir, exist_ok=True)
    for i, ph in enumerate(doc["photos"]):
        dest = os.path.join(pdir, "%02d.jpg" % i)
        if not ph["file"] and spend and download(key, ph["name"], dest):
            ph["file"] = dest
        if ph["file"] and ph["read"] is None:
            try:
                ph["read"] = look(ph["file"])
            except Exception as e:  # noqa: BLE001
                ph["read"] = {"error": type(e).__name__ + ": " + str(e)[:120]}
            save(lid, doc)
    return doc


def verdict(doc):
    boards = [ph for ph in doc["photos"] if ph.get("read")
              and ph["read"].get("kind") in ("menu_board", "printed_menu", "screen")
              and ph["read"].get("names_happy_hour") and ph["read"].get("priced_lines")]
    return boards, doc.get("reviews") or []


def main():
    zone = sys.argv[sys.argv.index("--zone") + 1] if "--zone" in sys.argv else ""
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    spend = "--spend" in sys.argv
    pop = population(zone, limit)
    fresh = [v for v in pop if not cached(v["lid"])]
    cost = len(fresh) * (USD_SEARCH + PHOTOS_PER_VENUE * USD_PHOTO)
    print("%d venues%s; %d not yet cached -> about $%.2f at Google list price, "
          "plus %d vision reads on the %s subscription" % (
              len(pop), " in " + zone if zone else "", len(fresh), cost,
              len(fresh) * PHOTOS_PER_VENUE, VISION_MODEL), flush=True)
    if not spend and "--report" not in sys.argv:
        print("Nothing spent. Re-run with --spend.")
        return
    key = fvp.load_key() if spend else None
    if spend and not key:
        sys.exit("GOOGLE_PLACES_API_KEY missing from happy-hour-finder/.env")

    res = []
    with cf.ThreadPoolExecutor(max_workers=int(os.environ.get("EYES_WORKERS","3"))) as ex:
        for doc in ex.map(lambda v: one(v, key, spend), pop):
            res.append(doc)
            boards, revs = verdict(doc)
            tag = "HIT" if boards or revs else "   "
            nread = sum(1 for ph in doc["photos"] if ph.get("read"))
            print("%s %-34s %-9s photos=%2d read=%2d hh_boards=%d hh_reviews=%d" % (
                tag, doc["name"][:34], doc["status"][:9], len(doc["photos"]), nread,
                len(boards), len(revs)), flush=True)
    with open(OUT + ".new", "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    os.replace(OUT + ".new", OUT)

    ok = [d for d in res if d["status"] == "ok"]
    by_photo = [d for d in res if verdict(d)[0]]
    by_review = [d for d in res if verdict(d)[1]]
    either = {d["lid"] for d in by_photo} | {d["lid"] for d in by_review}
    print("\n" + "=" * 74)
    print("OF %d venues that publish an hour and no price on their site:" % len(res))
    print("  %3d matched a Google listing" % len(ok))
    print("  %3d have a customer PHOTO of a happy-hour board WITH prices" % len(by_photo))
    print("  %3d have a REVIEW sentence naming happy hour AND a price" % len(by_review))
    print("  %3d either" % len(either))
    print("=" * 74)
    for d in res:
        boards, revs = verdict(d)
        if not boards and not revs:
            continue
        print("\n  %s" % d["name"])
        for ph in boards[:2]:
            rd = ph["read"]
            print("    PHOTO %s  %s" % (rd["kind"], " | ".join(rd.get("hh_lines") or [])[:100]))
            for ln in (rd.get("priced_lines") or [])[:5]:
                print("          %s" % ln[:90])
        for rv in revs[:2]:
            print("    REVIEW (%s) %s" % (rv["when"], rv["quote"][:150]))


main()
