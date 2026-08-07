#!/usr/bin/env python3
"""Find sites for licensees OSM has no URL for, by guessing and then proving.

`discover_sites.py` can only report a website that OpenStreetMap already holds.
Measured on the seven target towns, that is where the corpus stops: the missing
venues are *in* the extract -- Dawson Street Pub, Bar Jawn, Cresson Inn and The
Grape Room are all there as amenity=pub nodes -- but 998 of the extract's named
elements carry neither an address nor a website tag, so there is nothing to
join to and nothing to crawl. OSM knows the bar exists; it does not know its URL.

So this pass supplies the URL from the only free source left: the venue's own
name. It builds domain candidates from the name, fetches each one, and keeps it
ONLY if the page proves it belongs to that venue -- the distinctive words of the
name must appear in the text AND so must the town, ZIP or street. A guess that
cannot prove itself is discarded, which is what keeps this from quietly
attaching a wrong site to a real licensee. Every acceptance is printed.

    python ingest/guess_sites.py --zone manayunk --limit 40   # bounded
    python ingest/guess_sites.py --towns                      # the seven towns
    python ingest/guess_sites.py --towns --write              # merge the wins

Without --write nothing is merged; the run is a reviewable dry run. Attempts are
cached in data/raw/site_guesses.json, so a re-run costs no requests.
"""

import argparse
import collections
import csv
import json
import os
import re
import socket
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawl_sites import visible_text  # noqa: E402  same markup rules as the crawler
from discover_sites import SUFFIXES  # noqa: E402  one spelling of 'street suffix'

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENUES_CSV = os.path.join(REPO, "data", "venues.csv")
SITES = os.path.join(REPO, "data", "venue_sites.json")
CACHE = os.path.join(REPO, "data", "raw", "site_guesses.json")
SEEDS = os.path.join(REPO, "data", "site_seeds.json")

UA = "happy-hour-finder/0.1 (+https://paulrenzi.github.io/happy-hour-finder/)"
DELAY = 1.0
TIMEOUT = 12

TOWN_ZONES = ["phoenixville", "wayne_radnor", "ardmore_bryn_mawr",
              "collegeville_trappe", "conshohocken", "manayunk"]

# Words that carry no identifying weight in a domain guess. Kept separate from
# discover_sites.NAME_NOISE: 'brewing' and 'tavern' are noise when *comparing*
# two names, but they are exactly what a bar puts in its domain.
CORP = {"inc", "llc", "l l c", "lp", "llp", "corp", "corporation", "co",
        "company", "ltd", "holdings", "holdco", "enterprises", "associates",
        "partners", "group", "hospitality", "management", "ventures", "pa",
        # Legal-entity padding, same class as 'inc': the sign outside says
        # 'Topgolf' and 'The Cheesecake Factory', not 'Topgolf USA KP LLC' or
        # 'The Cheesecake Factory Restaurants Inc'.
        "usa", "restaurants"}

# Connectives, including the 'and' that clean_name itself creates out of '&'.
# Requiring these proves nothing -- every page contains them -- and requiring
# the one we invented made 'Creeds Seafood & Steaks' unprovable by construction.
GLUE = {"and", "the", "of", "at", "on", "for"}
# A name reduced to one of these is too generic to guess from: 'grape.com' is
# not The Grape, and a false positive here is worse than a miss.
TOO_GENERIC = {"the", "bar", "pub", "tavern", "inn", "grill", "grille", "cafe",
               "restaurant", "club", "house", "kitchen", "brewery", "brewing",
               "taproom", "lounge", "hotel", "the bar", "the pub", "the inn"}

# A parked or for-sale page will happily echo whatever is in its own domain, so
# it can pass a naive name check. These phrases disqualify it outright.
PARKED_RE = re.compile(
    r"domain (?:is )?(?:for sale|parking)|buy this domain|this domain is|"
    r"parked (?:free )?(?:at|by|courtesy)|godaddy\.com/domainsearch|"
    r"hugedomains|sedoparking|namecheap\.com/domains|expired domain|"
    r"website is currently unavailable|"
    r"account suspended|default web page|welcome to nginx|apache2 ubuntu default",
    re.I)

# 'Coming soon' and 'under construction' were in the list above, and they are
# the wrong shape for it: a trading venue writes them about a new beer, a new
# location or next month's event. Bowen Arrow Winery names four wines as coming
# soon and was refused as a parked domain on the strength of it. What makes a
# placeholder a placeholder is not the phrase, it is that the phrase is nearly
# all there is -- so these only disqualify a page with almost nothing on it.
PLACEHOLDER_RE = re.compile(
    r"under construction|coming soon|launching soon|opening soon|"
    r"site is being (?:built|updated)", re.I)
PLACEHOLDER_MAX_CHARS = 1500

SUFFIX_RE = re.compile(r"\b(?:%s)\b\.?" % "|".join(CORP), re.I)

# A chain's PLCB row carries the operator's own store number -- 'SEASONS 52
# #4510', 'YARD HOUSE 8371', "EDDIE V'S #8522". It is not part of the name the
# venue puts on its building, so requiring it on the page made those licensees
# unprovable by construction: proof_tokens asked for '4510' and no page in the
# world says it. Only a '#' marker or a run of four or more digits qualifies,
# which leaves the numbers that ARE the name -- Stable 12, Catch 101 -- alone.
STORE_NO_RE = re.compile(r"\s*#\s*\d+\s*$|\s+\d{4,}\s*$")


def clean_name(name):
    """'4326 MAIN STREET HOLDCO, LLC' -> '4326 main street'."""
    n = re.sub(r"[^\w\s&']", " ", STORE_NO_RE.sub("", name or "").lower())
    n = n.replace("&", " and ").replace("'", "")
    n = SUFFIX_RE.sub(" ", n)
    return " ".join(n.split())


def candidates(name):
    """Domain stems worth trying, most likely first.

    A bar's domain is nearly always the name run together, sometimes without a
    leading 'the' and sometimes with the category word dropped, so those three
    forms cover most of it. Anything shorter than 6 characters is not a guess,
    it is a collision.
    """
    words = clean_name(name).split()
    if not words or " ".join(words) in TOO_GENERIC:
        return []
    # A name that is only a street address identifies a building, not a
    # business, so there is nothing to guess: a licensee called '4326 MAIN
    # STREET HOLDCO, LLC' is Pitchers Pub, and '4326mainstreet.com' is nobody.
    # The shape is a house number followed by a street -- '3 Sons Tavern' keeps
    # its leading number because 'tavern' is not a street suffix.
    if not any(re.search(r"[a-z]", w) for w in words):
        return []
    if words[0].isdigit() and words[-1] in SUFFIXES:
        return []
    if words[0] == "the":
        forms = [words, words[1:]]
    else:
        forms = [words, ["the"] + words]
    stems = []
    for f in forms:
        if not f:
            continue
        stems.append("".join(f))
        if len(f) > 2 and f[-1] in TOO_GENERIC:
            stems.append("".join(f[:-1]))
    out = []
    for s in stems:
        s = re.sub(r"[^a-z0-9]", "", s)
        if len(s) >= 6 and s not in out and not s.isdigit():
            out.append(s)
    return out[:4]


def seed_urls(lid):
    """Leads supplied by hand for licensees the name-stem guess cannot reach.

    A chain is invisible to the guesser by construction: daveandbusters.com
    resolves and is the right site, but its homepage never says 'King of
    Prussia', so verify() correctly refuses to place it. The stem is not the
    problem -- the location page is simply somewhere the stem cannot name.

    So the URL may come from outside (a web search, a tourism board's happy
    hour roundup), but it earns its place the same way every other candidate
    does: it is fetched, and it is kept only if the page names AND places the
    venue. A seed is a lead, not an assertion; nothing here bypasses verify().

    A seed may be a bare URL, or {"url": ..., "name": "The StoneRose"} when the
    licensee is a corporate shell. 'COLD RIVER LLC' at 822 Fayette St is the
    StoneRose, and no page of theirs will ever say 'cold river' -- so the stem
    guess cannot reach it and neither can a bare seed, because the name half of
    verify() is asking for a name the venue does not use. Supplying the trade
    name does not weaken the proof: that name still has to appear on the page,
    alongside the town, exactly as the licensee's own would. It is also what
    the card displays, so the deal ships under the name on the door instead of
    the holding company's.
    """
    if not os.path.exists(SEEDS):
        return []
    seeds = json.load(open(SEEDS, encoding="utf-8"))
    v = seeds.get(lid) or []
    if isinstance(v, (str, dict)):
        v = [v]
    return [{"url": e, "name": None} if isinstance(e, str)
            else {"url": e["url"], "name": e.get("name")} for e in v]


def proof_tokens(row, trade_name=None):
    """The words a page must show to prove it is this licensee's own site."""
    words = [w for w in clean_name(trade_name or row["name"]).split()
             if len(w) > 2 and w not in TOO_GENERIC and w not in GLUE]
    town = (row.get("municipality") or "").lower()
    town = re.sub(r"\b(twp|township|boro|borough|city|of)\b", " ", town).strip()
    # The mailing city, which is the name the venue itself prints. It is not
    # the municipality: Upper Merion Twp is the licensing authority, but every
    # bar in it says 'King of Prussia', so a page could never be placed by the
    # municipality alone. Wayne, Bryn Mawr and Gulph Mills are the same shape.
    city = re.search(r",\s*([A-Za-z][A-Za-z .'-]{2,28}?)\s+[A-Z]{2}\s+\d{5}",
                     row.get("address") or "")
    place = [p for p in [town, city.group(1).strip().lower() if city else "",
                         (row.get("zip") or "")[:5]] if p]
    street = re.search(r"\b\d+[A-Za-z]?\s+([A-Za-z][A-Za-z\s]{3,25}?)\s*,", row["address"] or "")
    if street:
        place.append(street.group(1).strip().lower())
    return words, place


def verify(text, words, place):
    """A page proves itself by naming the venue AND placing it.

    Both halves are required. The name alone is met by a chain's national site
    and by a parked page echoing its own domain; the town alone is met by every
    other business in that town.
    """
    # clean_name drops the apostrophe from the licensee, so the page has to be
    # read the same way or the two halves never meet: 'CREEDS SEAFOOD & STEAKS'
    # becomes 'creeds' and creedskop.com writes "Creed's", so a page that named
    # the venue perfectly was refused. Same for Morton's, Dave & Buster's and
    # every other possessive on the sign.
    low = " ".join(text.lower().split()).replace("’", "").replace("'", "")
    if PARKED_RE.search(low[:4000]):
        return None
    if len(low) < PLACEHOLDER_MAX_CHARS and PLACEHOLDER_RE.search(low):
        return None
    if not words:
        return None
    named = [w for w in words if re.search(r"\b%s" % re.escape(w), low)]
    # Every distinctive word, so 'Ryan's Pub' does not accept a page about Ryan.
    if len(named) < len(words):
        return None
    placed = [p for p in place if p and p in low]
    if not placed:
        return None
    return f"name({'+'.join(words)}) + {placed[0]}"


def fetch(url):
    import requests

    r = requests.get(url, timeout=TIMEOUT, allow_redirects=True,
                     headers={"User-Agent": UA})
    r.raise_for_status()
    if "html" not in r.headers.get("Content-Type", "text/html").lower():
        return None, None
    return r.url, visible_text(r.text)[:60000]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone", action="append", default=[],
                    help="restrict to a zone id (repeatable)")
    ap.add_argument("--towns", action="store_true",
                    help="shorthand for the seven target towns")
    ap.add_argument("--tier", help="restrict to a tier ('taproom' is the breweries,"
                                   " distilleries and wineries)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N licensees")
    ap.add_argument("--write", action="store_true",
                    help="merge the proven sites into data/venue_sites.json")
    ap.add_argument("--cached-only", action="store_true",
                    help="re-score pages already fetched; makes no requests")
    args = ap.parse_args()

    zones = set(args.zone) | (set(TOWN_ZONES) if args.towns else set())
    sites = json.load(open(SITES, encoding="utf-8"))
    rows = [r for r in csv.DictReader(open(VENUES_CSV, encoding="utf-8"))
            if r["lid"] not in sites and (not zones or r["zone_id"] in zones)
            and (not args.tier or r["tier"] == args.tier)]

    cache = {}
    if os.path.exists(CACHE):
        cache = json.load(open(CACHE, encoding="utf-8"))

    stats, found, tried = collections.Counter(), {}, 0
    for row in rows:
        if args.limit and tried >= args.limit:
            break
        seeds = seed_urls(row["lid"])
        cands = candidates(row["name"])
        if not (seeds or cands):
            stats["name too generic or a shell to guess from"] += 1
            continue
        tried += 1
        # Seeds first: a hand-supplied location page is more specific than any
        # stem, and it is the only lead that reaches a chain at all. The bare
        # stem before the www one, because most hosts redirect either way and
        # the ones that do not are usually apex-broken, not www-broken --
        # stable12.com times out where www.stable12.com is the live brewery.
        leads = list(seeds) + [{"url": "https://%s%s%s" % (p, s, t), "name": None}
                               for t in (".com", ".net") for p in ("", "www.")
                               for s in cands]
        for lead in leads:
            url = lead["url"]
            words, place = proof_tokens(row, lead["name"])
            host = urllib.parse.urlsplit(url).netloc
            if url in cache:
                rec = cache[url]
            elif args.cached_only:
                # A change to the proof rules re-answers every page already
                # paid for. Re-scoring the whole corpus should not cost anyone
                # a single request, or it will only ever be done on a few zones.
                stats["not fetched yet (--cached-only)"] += 1
                continue
            else:
                try:
                    socket.gethostbyname(host)
                except OSError:
                    cache[url] = rec = {"status": "no dns"}
                else:
                    time.sleep(DELAY)
                    try:
                        final, text = fetch(url)
                        rec = ({"status": "ok", "url": final, "text": text}
                               if text else {"status": "not html"})
                    except Exception as exc:
                        rec = {"status": "fetch failed",
                               "error": type(exc).__name__}
                    cache[url] = rec
            if rec.get("status") != "ok":
                continue
            why = verify(rec["text"], words, place)
            if why:
                how = "seed URL" if lead in seeds else "guessed domain"
                found[row["lid"]] = {
                    "name": row["name"], "osm_name": lead["name"],
                    "address": row["address"], "zone_id": row["zone_id"],
                    "website": rec["url"], "phone": None,
                    "opening_hours": None, "kind": None,
                    "lat": None, "lng": None, "osm": None,
                    "matched_by": f"guessed {how}, proved by {why}",
                }
                stats["PROVEN"] += 1
                shown = lead["name"] or row["name"]
                print(f"  {shown[:30]:<32} {rec['url'][:44]:<46} {why[:46]}")
                break
        else:
            stats["no candidate domain proved itself"] += 1

    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)

    print(f"\n{len(rows)} licensees with no site; {tried} guessable\n")
    for k, v in stats.most_common():
        print(f"  {v:>6}  {k}")

    if args.write and found:
        sites.update(found)
        with open(SITES, "w", encoding="utf-8") as fh:
            json.dump(sites, fh, indent=1, sort_keys=True)
        print(f"\nmerged {len(found)} into {SITES} ({len(sites)} total)")
    elif found:
        print(f"\n{len(found)} proven -- re-run with --write to merge")


if __name__ == "__main__":
    main()
