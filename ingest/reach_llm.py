#!/usr/bin/env python3
"""Intelligence over a town's REACH -- the human minute, done by the machine.

    python ingest/reach_llm.py links   --lids run.lids [--show]   # which link is the happy hour
    python ingest/reach_llm.py verdict --lids run.lids [--show]   # does this page state one
    python ingest/reach_llm.py town phoenixville [--spend]        # what the web says the town has

A scoped Phoenixville run ended "no card added, both refusals correct", and
Paul found five published happy hours in one minute: Revival, Rivertown Taps,
Sly Fox, Sedona Taphouse, Valley Forge Pizza. Every one was a hole in REACH --
a page or a picture the crawl never put in front of any reader -- and every one
was then fixed with one more regex. That does not scale: each miss teaches us
one pattern, and the next town has new ones. This file puts a model at the
three places the crawler was using a pattern list:

  links    The venue's link inventory (every anchor on the homepage plus the
           sitemap, text and URL) goes to a model with one question: which of
           these is the happy-hour page or menu, and which is THIS town's
           location page. Replaces LINK_WORDS/town_re ranking, which is a list
           we grew one miss at a time. Answers are queued as depth-1 seeds by
           crawl_sites.py, ahead of everything it would have guessed.

  verdict  A fetched page the regex called "no happy hour" goes to a model with
           one question: does this page state a happy hour under ANY name --
           appy hour, social hour, bar bites 3-6 -- and quote the lines that
           say when. Every line is checked in code as a literal substring of
           the page; a line that is not there is dropped. Kept lines are filed
           as ordinary crawl quotes, and the UNCHANGED window grammar decides
           what they mean. The model never writes a window.

  town     Google Places is asked what "happy hour in <town>" returns, and the
           answer is matched to the venues we hold. It seeds the town's ground
           truth (data/ground_truth/<zone>.json) and names the class no other
           instrument can see: a venue that publishes a happy hour and is not
           in our reach at all.

The safety argument is the one every model pass here makes: the model is a
reader, not a source. A picked URL must be in the inventory it was shown; a
quoted line must be on the page; a searched venue is a CANDIDATE until a
person or a card confirms it. Cost is the number of calls, not the model
size: a town of 30 sites is 30/BATCH link calls and 30/BATCH verdict calls.
"""

import argparse
import collections
import datetime
import json
import os
import re
import sys
import urllib.parse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crawl_sites as cs  # noqa: E402
from extract_deals import HH_RE, norm  # noqa: E402
from extract_prices_llm import LEAN_ARGS, ask_with  # noqa: E402

HITS = cs.OUT
BASE = cs.BASE
PAGES = cs.PAGES
LINKS_OUT = os.path.join(REPO, "data", "reach_links.json")
VERDICTS_OUT = os.path.join(REPO, "data", "reach_verdicts.json")
GROUND_DIR = os.path.join(REPO, "data", "ground_truth")

MODEL = os.environ.get("HHF_REACH_MODEL", "sonnet")
BATCH = int(os.environ.get("HHF_REACH_BATCH", "5"))
INVENTORY_CAP = 120   # link lines per venue; a nav is 20, a chain sitemap 2,000
PAGE_CAP = 6000       # chars of page text per venue for a verdict
PICK_CAP = 3          # URLs the picker may queue per kind
TODAY = datetime.date.today().isoformat()
ZW_RE = re.compile("[\u200b\u200c\u200d\ufeff]")

# extract_prices_llm's transport, with its price-reading system prompt swapped
# for a reach-reading one. The flag list itself is shared on purpose -- see the
# 3x note beside LEAN_ARGS -- so only the one string differs.
_SYS = "You read restaurant websites and answer questions about them. Answer with JSON only."


def _args():
    out = list(LEAN_ARGS)
    out[out.index("--system-prompt") + 1] = _SYS
    return out


def ask(batch, template, **fields):
    import extract_prices_llm as ep
    saved = ep.LEAN_ARGS
    ep.LEAN_ARGS = _args()
    try:
        return ask_with(batch, template, MODEL, **fields)
    finally:
        ep.LEAN_ARGS = saved


def scoped(args):
    only = None
    if args.lids:
        only = {ln.strip() for ln in open(args.lids, encoding="utf-8") if ln.strip()}
    sites = cs.frontier()
    return {lid: v for lid, v in sorted(sites.items())
            if (only is None or lid in only)
            and (not args.zone or v.get("zone_id") == args.zone)}


def town_of(address):
    m = re.search(r",\s*([A-Za-z][A-Za-z .']*?)\s+PA\b", address or "")
    return m.group(1).strip() if m else ""


# ---- links -----------------------------------------------------------------

LINKS_PROMPT = """\
Each block below is one bar or restaurant in Pennsylvania: its name, its town,
and the links found on its home page and in its sitemap, one per line as
"TEXT -> URL".

For each venue answer two questions, using ONLY URLs that appear in its list:
1. `happy_hour`: which links most likely lead to the page, menu or PDF that
   states the venue's happy hour, drink specials or bar specials? Venues name
   this many ways: "Happy Hour", "Appy Hour", "Social Hour", "Specials",
   "Bar Bites", "Late Night", "Daily Deals", a menu PDF. Up to {cap}, best first.
2. `location`: if this is a multi-location brand, which link is the location
   page for THIS venue's town (the town named in the block)? Up to {cap}.

Rules:
- Copy each URL EXACTLY as it appears after "->". A URL not in the list is
  discarded by the program. Never invent or edit a URL.
- Skip links to other locations, catering, events, gift cards, jobs, social
  media, ordering platforms and the home page itself.
- An empty list is a real answer. Do not fill it with the food menu unless
  nothing better exists; a plain menu link is acceptable as the LAST choice.

Return ONLY a JSON array, no prose and no code fence:
[{{"id": "<id>", "happy_hour": ["<url>"], "location": ["<url>"]}}]

VENUES:
{venues}
"""


def inventory(html, page_url, sitemap=()):
    """[(text, url)] -- every same-domain link, deduped, in page order."""
    host = cs.registrable(urllib.parse.urlsplit(page_url).netloc)
    out, seen = [], set()
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.{0,400}?)</a>',
                         html, re.I | re.S):
        href = m.group(1).strip()
        text = cs.WS_RE.sub(" ", cs.MARKUP_RE.sub(" ", m.group(2))).strip()
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        full = urllib.parse.urljoin(page_url, href).split("#")[0]
        if cs.registrable(urllib.parse.urlsplit(full).netloc) != host:
            continue
        if re.search(r"\.(jpg|jpeg|png|gif|svg|webp|css|js|ico|zip)$", full, re.I):
            continue
        if full in seen or full.rstrip("/") == page_url.rstrip("/"):
            continue
        seen.add(full)
        out.append((text[:80], full))
    for u in sitemap:
        if u not in seen:
            seen.add(u)
            out.append(("(sitemap)", u))
    return out[:INVENTORY_CAP]


def pick(reply, inventories):
    """{id: {"happy_hour": [...], "location": [...]}} -- only URLs we showed."""
    out = {}
    for row in reply or []:
        vid = str(row.get("id", ""))
        allowed = {u for _, u in inventories.get(vid, [])}
        if not allowed:
            continue
        keep = {}
        for kind in ("happy_hour", "location"):
            urls = [u for u in (row.get(kind) or []) if isinstance(u, str) and u in allowed]
            keep[kind] = list(dict.fromkeys(urls))[:PICK_CAP]
        if keep["happy_hour"] or keep["location"]:
            out[vid] = keep
    return out


def links(args):
    import requests
    session = requests.Session()
    robots = {}
    venues = scoped(args)
    held = json.load(open(LINKS_OUT, encoding="utf-8")) if os.path.exists(LINKS_OUT) else {}
    todo = [(lid, v) for lid, v in venues.items()
            if v.get("website") and (args.force or lid not in held)]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} venue(s) to pick links for, {BATCH} per call\n")

    inventories, names = {}, {}
    for lid, v in todo:
        url = v["website"]
        if not cs.allowed(url, robots):
            print(f"  {lid:<8} {v['name'][:36]:<38} -- {cs.refusal(url, robots)}")
            continue
        try:
            html, err = cs.get(session, url)
        except Exception as e:  # noqa: BLE001 -- one dead host is not a failed run
            html, err = None, type(e).__name__
        if not html:
            print(f"  {lid:<8} {v['name'][:36]:<38} -- {err}")
            continue
        try:
            extra = cs.sitemap_links(session, url, robots)
        except Exception:  # noqa: BLE001
            extra = []
        inv = inventory(html, url, extra)
        if not inv:
            held[lid] = {"asked_at": TODAY, "inventory": 0, "happy_hour": [], "location": []}
            continue
        inventories[lid] = inv
        names[lid] = (v.get("osm_name") or v["name"], town_of(v.get("address")))

    ids = list(inventories)
    for i in range(0, len(ids), BATCH):
        chunk = ids[i:i + BATCH]
        batch = [(lid, f"name: {names[lid][0]}\ntown: {names[lid][1] or '?'}\nlinks:\n"
                       + "\n".join(f"{t or '-'} -> {u}" for t, u in inventories[lid]))
                 for lid in chunk]
        try:
            reply = ask(batch, LINKS_PROMPT, cap=PICK_CAP)
        except Exception as e:  # noqa: BLE001 -- one failed batch is not a failed run
            print(f"  !! batch {i // BATCH + 1}: {type(e).__name__}: {e}"[:200])
            continue
        picked = pick(reply, inventories)
        for lid in chunk:
            row = picked.get(lid, {"happy_hour": [], "location": []})
            held[lid] = {"asked_at": TODAY, "inventory": len(inventories[lid]), **row}
            flag = f"{len(row['happy_hour'])} hh, {len(row['location'])} town" \
                if row["happy_hour"] or row["location"] else "--"
            print(f"  {lid:<8} {names[lid][0][:36]:<38} {flag}")
            if args.show:
                for u in row["happy_hour"]:
                    print(f"           hh   {u}")
                for u in row["location"]:
                    print(f"           town {u}")
        tmp = LINKS_OUT + ".new"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(held, fh, indent=1, sort_keys=True)
        os.replace(tmp, LINKS_OUT)
    print(f"\n{len(held)} venue(s) on file -> {LINKS_OUT}")
    print("Now run: python ingest/crawl_sites.py --lids <file> --recrawl --render")


# ---- verdict ---------------------------------------------------------------

VERDICT_PROMPT = """\
Each block below is the visible text of one page from a bar or restaurant's
own website in Pennsylvania.

For each page: does it state a HAPPY HOUR -- a recurring, time-bounded deal on
drinks or food? Venues name it many ways: "Happy Hour", "Appy Hour", "Social
Hour", "Bar Bites 3-6", "Drink Specials Mon-Fri 4-6", "Late Night Happy Hour".
Regular opening hours, a brunch, a dinner menu, an events calendar and a
one-off event are NOT a happy hour.

If it does, return `lines`: the lines that state WHEN it runs (days and times)
and WHAT it offers, copied EXACTLY as they appear on the page. Each line is
checked programmatically as a literal substring of the page; a line that is
not there is discarded. Copy the line, do not paraphrase or merge lines.
Return at most 8 lines, the schedule line first.

If it does not, return an empty `lines`. An empty answer is a real answer.

Return ONLY a JSON array, no prose and no code fence:
[{{"id": "<id>", "states_happy_hour": true, "lines": ["Tuesday-Friday: Appy Hour", "$2 off select appetizers 3PM-6PM"]}}]

PAGES:
{venues}
"""


def pages_for(lid):
    """[(url, text, lines)] for every page we hold for this venue."""
    out = []
    if not os.path.isdir(PAGES):
        return out
    prefix = f"{lid}__"
    for fn in sorted(os.listdir(PAGES)):
        if not fn.startswith(prefix) or not fn.endswith(".json"):
            continue
        page = json.load(open(os.path.join(PAGES, fn), encoding="utf-8"))
        lines = page.get("lines") or []
        out.append((page.get("url", ""), "\n".join(lines), lines))
    return out


def grounded(reply_lines, lines):
    """The model's lines that are literally on the page, as the page spells them."""
    # Zero-width spaces are what a Wix page pads its lines with (Sly Fox's
    # "\u200b Tuesday-Friday: Appy Hour"); a model does not copy them and a
    # person cannot see them, so they are not part of the comparison.
    clean = lambda s: ZW_RE.sub("", s).strip()  # noqa: E731
    by_norm = {norm(clean(ln)): clean(ln) for ln in lines if clean(ln)}
    text = norm(clean("\n".join(lines)))
    out = []
    for cand in reply_lines or []:
        if not isinstance(cand, str) or len(clean(cand)) < 3:
            continue
        key = norm(clean(cand))
        if key in by_norm:
            out.append(by_norm[key])
        elif key in text:
            out.append(clean(cand))
    return list(dict.fromkeys(out))


def verdict(args):
    hits = json.load(open(HITS, encoding="utf-8"))
    venues = scoped(args)
    held = json.load(open(VERDICTS_OUT, encoding="utf-8")) if os.path.exists(VERDICTS_OUT) else {}
    todo = []
    for lid, v in venues.items():
        rec = hits.get(lid)
        if not rec or (rec.get("hits") and not args.force):
            continue
        for url, text, lines in pages_for(lid):
            key = f"{lid} {url}"
            if key in held and not args.force:
                continue
            if len(lines) < 5:
                continue
            todo.append((lid, url, text[:PAGE_CAP], lines, v))
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} page(s) to judge across {len({t[0] for t in todo})} venue(s), "
          f"{BATCH} per call\n")

    added = 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        batch = [(f"{lid}|{n}", f"url: {url}\n{text}") for n, (lid, url, text, _, _) in
                 enumerate(chunk, i)]
        by_id = {f"{lid}|{n}": (lid, url, lines, v)
                 for n, (lid, url, _, lines, v) in enumerate(chunk, i)}
        try:
            reply = ask(batch, VERDICT_PROMPT)
        except Exception as e:  # noqa: BLE001
            print(f"  !! batch {i // BATCH + 1}: {type(e).__name__}: {e}"[:200])
            continue
        answered = {str(r.get("id")): r for r in (reply or []) if isinstance(r, dict)}
        for vid, (lid, url, lines, v) in by_id.items():
            row = answered.get(vid) or {}
            keep = grounded(row.get("lines"), lines) if row.get("states_happy_hour") else []
            held[f"{lid} {url}"] = {"asked_at": TODAY, "url": url,
                                    "states_happy_hour": bool(row.get("states_happy_hour")),
                                    "lines": keep}
            name = (v.get("osm_name") or v["name"])[:36]
            if not keep:
                why = "no happy hour" if not row.get("states_happy_hour") else "lines not on page"
                print(f"  {lid:<8} {name:<38} -- {why}")
                continue
            # One quote, the way crawl_sites joins a section: the grammar in
            # extract_deals reads 'A / B / C' exactly as it reads a crawled hit.
            quote = " / ".join(keep)
            rec = hits[lid]
            if not any(h.get("quote") == quote for h in rec.get("hits") or []):
                rec.setdefault("hits", []).append(
                    {"url": url, "quote": quote, "hh": True, "by": "reach_llm"})
                added += 1
            print(f"  {lid:<8} {name:<38} ** {len(keep)} line(s)")
            if args.show:
                for ln in keep:
                    print(f"           {ln[:100]}")
        tmp = VERDICTS_OUT + ".new"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(held, fh, indent=1, sort_keys=True)
        os.replace(tmp, VERDICTS_OUT)
        tmp = HITS + ".new"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(hits, fh, indent=1, sort_keys=True)
        os.replace(tmp, HITS)
    print(f"\n{added} quote(s) added to {HITS}")
    print("Now run: python ingest/extract_deals.py && python ingest/build_venue_base.py "
          "&& python ingest/build_bundles.py")


# ---- town ------------------------------------------------------------------

SEARCH = "https://places.googleapis.com/v1/places:searchText"
USD_PER_SEARCH = 0.032  # Google Places Text Search, Pro tier, list price


def street_key(address):
    """('520', '19460') -- the house number and zip, which is what two spellings
    of one address agree on. A PLCB range ('208-212 Bridge St') is keyed on
    its LAST number, which is the one the sign over the door uses."""
    num = re.match(r"\s*(\d+)(?:\s*-\s*(\d+))?[A-Za-z]?\b", address or "")
    zipc = re.search(r"\b(\d{5})(?:-\d{4})?\b", address or "")
    house = (num.group(2) or num.group(1)).lower() if num else ""
    return (house, zipc.group(1) if zipc else "")


def house_numbers(address):
    """Every number a range spans, so '208-212' meets '212' AND '208'.

    A range can have more than two parts: Limoncello's licence reads
    '5-7-9 N Walnut St' and Google calls it '9 N Walnut St', so reading only the
    first two numbers lost the very one the sign uses -- and the venue read as
    'NOT A LICENSEE WE HOLD' in a town where we hold it.
    """
    num = re.match(r"\s*(\d+(?:\s*-\s*\d+)*)[A-Za-z]?\b", address or "")
    if not num:
        return set()
    return {n.strip() for n in num.group(1).split("-")}


def name_key(name):
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    s = re.sub(r"\b(the|restaurant|bar|grill|grille|pub|tavern|and|of|inc|llc|"
               r"lounge|kitchen|brewing|brewery|company|co)\b", " ", s)
    return " ".join(s.split())


def match_place(place, base_rows, zips=()):
    """The base LID this Places row is, or None. Address first, then name.

    `zips` is the ZIP set of the zone being searched. Google and the PLCB do
    not always agree on a ZIP -- The Stone Tavern is 19382 to Google and 19380
    on its licence, both West Chester -- and requiring them to be equal turned
    a venue we hold into a venue we do not. Inside one zone that difference is
    not evidence of a different bar, and the name test is still exact.
    """
    addr = place.get("formattedAddress", "")
    key = street_key(addr)
    if key[0]:
        same = [lid for lid, v in base_rows
                if key[1] == street_key(v.get("address"))[1]
                and key[0] in house_numbers(v.get("address"))]
        if len(same) == 1:
            return same[0]
        if same:
            nk = name_key(place["displayName"]["text"])
            by_name = [lid for lid in same
                       if nk and (nk in name_key(dict(base_rows)[lid]["name"])
                                  or name_key(dict(base_rows)[lid]["name"]) in nk)]
            return by_name[0] if by_name else same[0]
    nk = name_key(place["displayName"]["text"])
    zipc = key[1]
    local = set(zips)
    cands = [lid for lid, v in base_rows
             if nk and name_key(v["name"]) == nk
             and (not zipc or zipc in (v.get("address") or "")
                  or (zipc in local and street_key(v.get("address"))[1] in local))]
    return cands[0] if len(cands) == 1 else None


def load_ground(zone):
    path = os.path.join(GROUND_DIR, f"{zone}.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return {"zone_id": zone, "rows": []}


def save_ground(zone, doc):
    os.makedirs(GROUND_DIR, exist_ok=True)
    path = os.path.join(GROUND_DIR, f"{zone}.json")
    doc["rows"].sort(key=lambda r: (not r.get("confirmed"), r.get("name", "").lower()))
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def town(args):
    import requests
    key = None
    env = os.path.join(REPO, ".env")
    if os.path.exists(env):
        for line in open(env, encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k == "GOOGLE_PLACES_API_KEY" and v:
                key = v.strip().strip("\"'")
    key = key or os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        sys.exit("GOOGLE_PLACES_API_KEY missing from happy-hour-finder/.env")

    base = json.load(open(BASE, encoding="utf-8"))
    rows = [(lid, v) for lid, v in base.items() if v.get("zone_id") == args.zone]
    towns = collections.Counter(town_of(v.get("address")) for _, v in rows)
    zone_zips = {street_key(v.get("address"))[1] for _, v in rows} - {""}
    rows = [(lid, v) for lid, v in base.items()
            if v.get("zone_id") == args.zone
            or street_key(v.get("address"))[1] in zone_zips]
    towns = [t for t, _ in towns.most_common() if t][:4]
    queries = [f"happy hour in {t}, PA" for t in towns]
    print(f"{args.zone}: {len(rows)} licensees across {', '.join(towns)}")
    print(f"{len(queries)} search(es) -- about ${len(queries) * USD_PER_SEARCH:.2f} "
          "at Google list price")
    if not args.spend:
        print("\nNothing spent. Re-run with --spend to search.")
        return

    doc = load_ground(args.zone)
    by_lid = {r.get("lid"): r for r in doc["rows"] if r.get("lid")}
    zips = zone_zips
    found, unmatched, elsewhere, seen = 0, [], 0, set()
    for q in queries:
        r = requests.post(SEARCH, headers={
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,"
                                "places.websiteUri,places.primaryType"},
            json={"textQuery": q, "pageSize": 20}, timeout=30)
        r.raise_for_status()
        places = r.json().get("places", [])
        print(f"\n'{q}': {len(places)} place(s)")
        for p in places:
            name = p["displayName"]["text"]
            if p.get("id") in seen:
                continue
            seen.add(p.get("id"))
            lid = match_place(p, rows, zips)
            site = p.get("websiteUri") or ""
            if lid:
                found += 1
                row = by_lid.get(lid)
                if not row:
                    row = {"lid": lid, "name": base[lid]["name"], "confirmed": False}
                    doc["rows"].append(row)
                    by_lid[lid] = row
                row.setdefault("candidate_from", []).append(f"google_places: {q}")
                row["candidate_from"] = sorted(set(row["candidate_from"]))
                row.setdefault("website", site)
                have = "website on file" if base[lid].get("website") else "NO WEBSITE ON FILE"
                print(f"  {lid:<8} {base[lid]['name'][:34]:<36} {have}")
            elif street_key(p.get("formattedAddress", ""))[1] not in zips:
                elsewhere += 1
            else:
                unmatched.append((name, p.get("formattedAddress", ""), site))
                print(f"  {'?':<8} {name[:34]:<36} NOT A LICENSEE WE HOLD  {p.get('formattedAddress','')[:40]}")
    doc.setdefault("searched", []).append({"at": TODAY, "queries": queries,
                                          "matched": found, "unmatched": len(unmatched)})
    if unmatched:
        doc["unmatched"] = [{"name": n, "address": a, "website": s} for n, a, s in unmatched]
    path = save_ground(args.zone, doc)
    print(f"\n{found} matched to a licensee, {len(unmatched)} not, "
          f"{elsewhere} outside the zone's zips (ignored) -> {path}")
    print("Candidates are NOT confirmed. Confirm each with the URL that states the "
          "happy hour, then: python ingest/report_coverage.py", args.zone)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("links", links), ("verdict", verdict)):
        p = sub.add_parser(name)
        p.add_argument("--lids", help="file of licence ids, one per line")
        p.add_argument("--zone", help="only venues in this zone id")
        p.add_argument("--limit", type=int, default=0)
        p.add_argument("--force", action="store_true", help="re-ask venues already on file")
        p.add_argument("--show", action="store_true")
        p.set_defaults(fn=fn)
    p = sub.add_parser("town")
    p.add_argument("zone")
    p.add_argument("--spend", action="store_true", help="actually call Google")
    p.set_defaults(fn=town)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args.fn(args)


if __name__ == "__main__":
    main()
