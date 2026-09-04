#!/usr/bin/env python3
"""Emit the per-zone JSON bundles the web app ships (SPEC section 9).

Reads data/deals_seed.json, drops anything the PA validators reject, applies
the confidence decay ladder (SPEC section 6), and writes web/data/.

    python ingest/build_bundles.py
"""

import datetime
import hashlib
import json
import re
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validate_pa import (rules_for, state_of, validate_deal,  # noqa: E402
                         validate_food_combo_count)
from exclusions import excluded  # noqa: E402
from discover_sites import name_agrees  # noqa: E402
from build_venue_base import pretty_name  # noqa: E402

# build_venue_base.pretty_name() already solves "AN ALL-CAPS LICENSEE NAME ->
# something a person would read on a card" for PLCB names; a menu item label
# is the same shape of problem (ALL CAPS PDF/menu text), so it reuses it
# rather than growing a second re-casing rule that could disagree with the
# first. It only acts on a string that IS all caps -- anything with real
# mixed case (a person's own reading of the sign or menu) is left alone.
de_shout = pretty_name


DEALS_JSON = os.path.join(REPO, "data", "deals_seed.json")
EXTRACTED_JSON = os.path.join(REPO, "data", "deals_extracted.json")
# Written by ingest/extract_roundups.py: a dated local article read for the
# bars it names. Lowest rank -- the outlet speaking, never the bar.
ROUNDUP_JSON = os.path.join(REPO, "data", "deals_roundup.json")
# Approved menu-photo submissions (ingest/review_photos.py). Distinct from
# PHOTOS_JSON below, which is venue hero images and has nothing to do with deals.
PHOTO_DEALS_JSON = os.path.join(REPO, "data", "deals_photo.json")
ZONES_JSON = os.path.join(REPO, "data", "zones.json")
PRICES_JSON = os.path.join(REPO, "data", "deals_prices_llm.json")
MENU_IMG_JSON = os.path.join(REPO, "data", "deals_menu_images.json")
AGENT_JSON = os.path.join(REPO, "data", "deals_agent.json")
# Written by hand, by an agent that opened the venue's own site and read the
# happy-hour menu the way a person does -- and, unlike AGENT_JSON above, it
# carries the WINDOW as well as the items. That is the whole difference. The
# sidecars can only fill items into a deal some deterministic pass already
# built, so a venue whose hours no crawler ever parsed had nothing to carry
# them and 52 paid-for items sat unpublished. A full venue row needs nothing
# to already exist. Same shape as deals_menus.json, same validators.
AGENT_VENUES_JSON = os.path.join(REPO, "data", "deals_agent_venues.json")
PAGES_JSON = os.path.join(REPO, "data", "deals_pages_llm.json")
MENUS_JSON = os.path.join(REPO, "data", "deals_menus.json")
PHOTOS_JSON = os.path.join(REPO, "data", "venue_photos.json")
COORDS_JSON = os.path.join(REPO, "data", "venue_coords.json")
BASE_JSON = os.path.join(REPO, "data", "venue_base.json")
OUT_DIR = os.path.join(REPO, "web", "data")
# Why a venue publishes a window and names no item, one line per venue, written
# by a person or by a reviewed pass. {"venues": {"<lid>": {"verdict": "...",
# "noted_at": "YYYY-MM-DD"}}}. A venue in here is ACCOUNTED FOR whatever the
# verdict says; the file exists so that "we looked and there is no menu" and
# "nobody has looked" stop being the same state.
VERDICTS = os.path.join(REPO, "data", "menu_verdicts.json")
# The ratchet. See the menu ratchet in main(). Lower it with every fix.
# The ceiling on the SHARE of published venues whose window names no item and
# carries no recorded reason.
#
# This was a COUNT, and the count was the wrong measurement. Reading days the
# way people write them ('Fridays', 'M-F', "3 PM TIL' 6 PM") admitted 28 venues
# that had published nothing at all before; 16 of them state hours and no menu,
# so the count rose 87 -> 101 and the build refused. Nothing had got worse --
# zero venues lost items, two gained them -- but a count cannot tell a
# REGRESSION from a venue that has only just arrived, and a guard that fires on
# progress gets its number bumped until it means nothing.
#
# A share can tell them apart, and it is also the thing the goal is about: when
# the scrape moves into a new zone, what matters is whether that zone's venues
# name their items at the rate the current ones do, not how many venues it has.
# 101 of 203 is 49.8%; the ceiling is the number to drive down.
HOLE_BUDGET = 0.50



def norm_addr(address):
    """Enough of an address to tell whether two records are one bar. The seed
    writes '324 W Swedesford Rd, Berwyn PA 19312' where the PLCB row the crawler
    carried says '324 WEST SWEDESFORD ROAD'; the number and the ZIP agree."""
    m = re.search(r"\b(\d{5})\b", address or "")
    # Licence exports sometimes prefix the street with the complex name
    # ("Radnor Financial Center 555 E Lancaster Ave"), so the house number
    # is not necessarily the first token.
    # '180B Mill Rd' is house 180: without the optional letter the search
    # skipped it and returned the ZIP as the house number, so P.J. Whelihan's
    # (180B) and the cinema licence in the same plaza (180) read as two doors.
    n = re.search(r"\b(\d+)[A-Za-z]?\b", address or "")
    return (n.group(1) if n else "?", m.group(1) if m else "?")


def norm_name(name):
    """Two display names are the same bar's name if they differ only in the
    punctuation a licensee typed: PJ Whelihan's / P.J. Whelihan's / P. J.
    Whelihan's Pub + Restaurant all collapse to the same key."""
    n = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    n = re.sub(r"\b(pub|restaurant|bar|grill|grille|tavern|cafe|and|the)\b", " ", n)
    # Spaces go too: a licensee typing "PJ" and another typing "P. J." is the
    # same three letters, and the source-page check below is what actually
    # guards the merge.
    return re.sub(r"[^a-z0-9]", "", n)


def deal_sources(venue):
    return {(d.get("source") or {}).get("url") for d in venue.get("deals", [])
            if (d.get("source") or {}).get("url")}


def collapse_name_collisions(by_zone):
    """One bar, one card.

    Six bars painted TWICE on the live board -- three P.J. Whelihan's, Hard Rock
    Cafe, Amada, The Post. Not a rendering bug and not two branches: the PLCB
    lists a SECOND licence in the same building (the Giant next door, the
    Marriott upstairs, the cinema in the same plaza), the name/site match gave
    that licence the bar's trade name, and the crawl then hung the bar's happy
    hour on both. premises_key could not merge them because it is deliberately
    strict -- Google gave them different place ids, and the licensee names
    ("THE GIANT COMPANY LLC") do not agree.

    So the merge happens here instead, where a much stronger signal exists: the
    two rows carry the SAME name in the same zone AND their deals were read off
    the SAME page. One web page is one bar's hours. The loser keeps its licence
    row -- it is a real premises -- but gives up the trade name it was never
    entitled to and the deals that belong next door, so it falls back to the
    'hours unknown' list under its own licensee name. Its LID rides along in
    also_lids, so a correction quoting it still lands on the right card.

    Returns the number of collisions collapsed.
    """
    collapsed = 0
    for venues in by_zone.values():
        groups = {}
        for v in venues:
            if v.get("deals"):
                groups.setdefault(norm_name(v["name"]), []).append(v)
        for rows in groups.values():
            if len(rows) < 2:
                continue
            # Sub-group by the page the hours were read off. Three P.J.
            # Whelihan's share a zone: two are one bar in Conshohocken with two
            # licences, the third is a real second branch in Blue Bell with its
            # own page. Asking what ALL of them share finds nothing and merges
            # nobody -- the question is which of them share a page.
            by_page = {}
            for v in rows:
                for url in deal_sources(v):
                    by_page.setdefault(url, []).append(v)
            for page, same in by_page.items():
                if len(same) < 2:
                    # Same name, a different page. That can be two real
                    # branches, and merging two real bars is far worse than
                    # listing one twice.
                    continue
                # One page is one bar's hours -- unless it is a CHAIN's page.
                # The Greene Turtle's two Newark branches, six miles apart,
                # both read their hours off thegreeneturtle.com/menu/ and the
                # Christiana one was folded into Main Street; the venue Paul
                # pointed at had no card. A shared page only merges rows that
                # also share a street number and ZIP, or whose address is
                # unknown. The Giant-next-door case still merges: it IS the
                # same building.
                by_door = {}
                for v in same:
                    by_door.setdefault(norm_addr(v.get("address", "")), []).append(v)
                unknown = by_door.pop(("?", "?"), [])
                doors = sorted(by_door.values(), key=len, reverse=True)
                if doors:
                    doors[0] = doors[0] + unknown
                elif unknown:
                    doors = [unknown]
                for door in doors:
                    if len(door) > 1:
                        collapsed += merge_rows(door)
            # A current name at the same street number and ZIP is a second,
            # independent identity signal.  The two crawl entries can reach
            # that one bar through different pages (for example its location
            # page and its corporate specials page), so requiring the URL to
            # agree alone lets a duplicate card through.  Names still have to
            # agree because two genuine bars can occupy one building.
            by_address = {}
            for v in rows:
                if not v.get("deals"):
                    continue
                address = norm_addr(v.get("address", ""))
                if address != ("?", "?"):
                    by_address.setdefault(address, []).append(v)
            for same in by_address.values():
                if len(same) > 1:
                    collapsed += merge_rows(same, "same name, same address")
    return collapsed


def name_the_surviving_branches(by_zone):
    """Two real branches in one town must not paint two cards a reader cannot
    tell apart.

    collapse_name_collisions() deliberately leaves same-name rows alone when
    they are two genuine bars -- merging two real bars is far worse than
    listing one twice. But it left the READER with the harder half: Newark, DE
    ships a Red Robin on Pulaski Hwy and another on W Main St, three miles
    apart, and the two cards were identical down to the window. Whichever one
    you tapped, you could not know which one you had.

    So whatever name collision SURVIVES the merge is a branch by definition,
    and it gets the one thing that separates it: its street. Returns how many
    rows were labelled.
    """
    labelled = 0
    for venues in by_zone.values():
        groups = {}
        for v in venues:
            groups.setdefault(norm_name(v["name"]), []).append(v)
        for rows in groups.values():
            if len(rows) < 2:
                continue
            streets = {v["id"]: street_of(v.get("address")) for v in rows}
            # A street only disambiguates if the streets DIFFER. Two rows we
            # could not separate stay unlabelled rather than both claiming the
            # same address -- a label that repeats is worse than none.
            if len({s for s in streets.values() if s}) < len(rows):
                continue
            for v in rows:
                v["branch"] = streets[v["id"]]
                labelled += 1
    return labelled


def street_of(address):
    """'2496 Pulaski Hwy, Newark, DE 19702' -> 'Pulaski Hwy'. The house number
    is dropped: it is noise on a card, and the street is what tells a local
    which side of town they are being sent to.

    Unit clauses go too, leading or inline. 'Ste 4, 100 Sugartown Rd' otherwise
    labels one Dandan 'Ste 4' and the other 'Sugartown Rd' -- two labels for one
    door, which reads as two bars that are not there."""
    unit = r"(?:ste|suite|unit|apt|bldg|fl|floor|rm|room|store|#)"
    segs = [s.strip() for s in str(address or "").split(",")]
    segs = [s for s in segs if s and not re.match(unit + r"\b", s, re.I)]
    head = re.sub(r"\s+" + unit + r"\b.*$", "", segs[0] if segs else "", flags=re.I)
    parts = head.split()
    while parts and re.match(r"^[\d-]+[A-Za-z]?$", parts[0]):
        parts.pop(0)
    return " ".join(parts)


def merge_rows(rows, reason="same name, same source page"):
    """One winner keeps the card; the losers give back the trade name and the
    deals, and ride along in also_lids. Returns how many were collapsed."""
    rows = [v for v in rows if v.get("deals")]
    if len(rows) < 2:
        return 0
    rows.sort(key=lambda v: (-len(v["deals"]), "photo" not in v,
                             "website" not in v, str(v["id"])))
    winner, losers = rows[0], rows[1:]
    also = list(winner.get("also_lids") or [])
    for v in losers:
        print(f"  merged: {v['name']} ({v['id']}) into {winner['id']} "
              f"-- {reason}")
        also += [str(v.get("lid") or v["id"])] + list(v.get("also_lids") or [])
        v["deals"] = []
        v.pop("also_lids", None)
        if v.get("plcb_name"):
            v["name"] = v["plcb_name"]
    winner["also_lids"] = sorted(set(also) - {str(winner.get("lid") or "")})
    return len(losers)


def decay(confidence, verified_at, today):
    """A deal never disappears, it demotes. SPEC section 6.

    The bundle ships `last_verified_at` and the confidence the source earned;
    the app re-runs this same ladder at read time (web/lib.js). Baking the
    demotion in here would freeze it at build time, so a bundle served for two
    months would keep calling a stale deal fresh. This copy exists to drop
    deals that have decayed out entirely, which is a build-time size decision.
    """
    age = (today - datetime.date.fromisoformat(verified_at)).days
    if confidence in ("verified", "disputed"):
        return confidence, age
    if age > 120:
        return "hidden", age
    if age > 45 and confidence == "likely":
        return "unconfirmed", age
    return confidence, age


# The precached shell files. data/index.json is covered by the venue count.
#
# sw.js is hashed too, but through _sw_source_for_digest, which blanks the CACHE
# line before hashing: the naive version has no fixed point, because stamping the
# name changes the bytes that produced it. Leaving it out entirely was the other
# way to break the tie, and it left a hole -- a deploy that changes ONLY the
# service worker (a caching-strategy fix, say) kept the previous cache name, so
# activate() deleted nothing and every installed device kept serving the old
# precached shell out from under the new worker.
SHELL_FILES = ("index.html", "app.js", "lib.js", "styles.css", "manifest.json")

CACHE_LINE = re.compile(r'const CACHE = "[^"]*";')


def _sw_source_for_digest():
    """sw.js with its own cache name neutralised, so hashing it terminates."""
    with open(os.path.join(REPO, "web", "sw.js"), encoding="utf-8") as fh:
        return CACHE_LINE.sub('const CACHE = "";', fh.read()).encode("utf-8")


def shell_digest():
    """A short hash of the precached shell, so a shell-only deploy still evicts.

    The date and venue count move only when the CORPUS moves. A deploy that
    changes app.js or index.html and nothing else produces the same name, the
    activate handler deletes nothing, and every already-installed device keeps
    serving the old shell out of the precache -- the exact shape of the King of
    Prussia freeze, with the corpus in the clear.
    """
    h = hashlib.sha256()
    for name in SHELL_FILES:
        with open(os.path.join(REPO, "web", name), "rb") as fh:
            # Line endings are normalised before hashing. A build run on
            # Windows against a working copy with CRLF in it produced a
            # DIFFERENT digest from the same commit on CI, where git checks the
            # files out with LF -- so the stamp the build wrote failed the test
            # that recomputes it, and the deploy never shipped.
            h.update(fh.read().replace(b"\r\n", b"\n"))
    h.update(_sw_source_for_digest())
    return h.hexdigest()[:8]


def sw_cache_name(built_at, n_published, digest=None):
    """The cache name a build of this shape must ship.

    The service worker precaches data/index.json, and its cache name is the ONLY
    thing that evicts. A hand-edited constant went four builds without changing,
    so devices kept serving an index from an older corpus -- King of Prussia read
    1 venue while the server had said 3 for hours, with nothing on either side to
    show a disagreement. The venue count rides along with the date so that a
    second build on the same day still evicts, and the shell digest so that a
    build changing only the app code evicts too.
    """
    return f"hhf-{built_at}-{n_published}-{shell_digest() if digest is None else digest}"


def stamp_service_worker(built_at, n_published):
    path = os.path.join(OUT_DIR, "..", "sw.js")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    new = re.sub(r'const CACHE = "[^"]*";',
                 f'const CACHE = "{sw_cache_name(built_at, n_published)}";', src, count=1)
    if new != src:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
        print(f"sw.js cache -> {sw_cache_name(built_at, n_published)}")


def unaccounted_holes(by_zone, verdicts):
    """Venues publishing a window that names no item and carries no verdict."""
    return sorted(
        v["name"] for vs in by_zone.values() for v in vs
        if any(not d.get("items") for d in v["deals"])
        and str(v.get("lid") or v["id"]) not in verdicts
    )


def menu_ratchet(by_zone, verdicts, budget, out=print):
    """Refuse the build if the SHARE of unexplained silent windows has RISEN.

    Separated from main() so its RED can be observed: a guard nobody has ever
    seen refuse is decoration. tests/test_ingest.py exercises both answers.
    """
    holes = unaccounted_holes(by_zone, verdicts)
    total = sum(len(vs) for vs in by_zone.values()) or 1
    share = len(holes) / total
    out(f"\n  windows naming no item, with no recorded reason: "
        f"{len(holes)} of {total} ({share:.1%}, ceiling {budget:.1%})")
    if share > budget:
        for name in holes[:20]:
            out(f"    {name}")
        raise SystemExit(
            f"\nREFUSED: {share:.1%} of venues publish a window and name no "
            f"item ({len(holes)} of {total}), and the ceiling is {budget:.1%}. "
            f"Either read their menus "
            f"(ingest/report_holes.py ranks them by class) or record a reason "
            f"per venue in data/menu_verdicts.json. Raising HOLE_BUDGET is a "
            f"decision, not a step."
        )
    return holes


def main():
    today = datetime.date.today()
    payload = json.load(open(DEALS_JSON, encoding="utf-8"))
    reserve = []

    def merge_venues(payload, more, label, rank):
        """Add venues from a lower-priority source, skipping any the higher ones
        already describe. Never merged INTO an existing venue: where two sources
        describe one bar the higher-priority source wins outright.

        The loser is not thrown away: it goes on `reserve` and publishes if the
        winner turns out to have no deal LEFT once the validators and the decay
        ladder are done with it. Dropping it outright meant a venue could win on
        priority and then publish nothing -- a photo whose hours had aged into
        `hidden` would take the crawler's still-good window off the board with
        it and the card would go blank. A stale window is a bug; a venue that
        silently loses the hours it had is worse."""
        seen, by_lid = {}, {}
        for v in payload["venues"]:
            seen.setdefault(v["id"], v)
            seen.setdefault(norm_addr(v["address"]), v)
            if v.get("lid"):
                by_lid.setdefault(str(v["lid"]), v)
        fresh, dupes = [], []
        for v in more:
            # Which venue this one lost to, kept with it: the fallback has to ask
            # whether THAT venue published, not whether this one's own licence
            # number is on the board. Two licences at one building have two
            # different numbers, so asking about its own would always say no and
            # every duplicate would publish a second card for the same bar.
            beat_by = seen.get(v["id"]) or by_lid.get(str(v.get("lid") or ""))
            if beat_by is None:
                at_addr = seen.get(norm_addr(v["address"]))
                # Same address is only the same bar when a name agrees too.
                # 44 W Gay St, West Chester is Lascala's Fire AND Sedona
                # Taphouse -- two bars, two licences, one building -- and the
                # address alone made Sedona lose to Lascala's and vanish, its
                # fully-read window never reaching the board. A corporate
                # shell ("WCTHG LL LLC") vs a trade name still agrees through
                # the plcb_name the source carries, which is what the second
                # licence case needs.
                if at_addr is not None and (
                        name_agrees(v["name"], at_addr["name"])
                        or name_agrees(v.get("plcb_name") or "", at_addr["name"])
                        or name_agrees(v["name"], at_addr.get("plcb_name") or "")
                        or name_agrees(v.get("plcb_name") or "", at_addr.get("plcb_name") or "")):
                    beat_by = at_addr
            if beat_by is None:
                fresh.append(dict(v, _rank=rank))
            else:
                dupes.append((dict(v, _rank=rank), beat_by))
        reserve.extend(dupes)
        print(f"  +{len(fresh)} {label} venues ({len(dupes)} already covered)")
        return dict(payload, venues=payload["venues"] + fresh)

    def merge(payload, path, label, rank):
        if not os.path.exists(path):
            return payload
        return merge_venues(payload, json.load(open(path, encoding="utf-8"))["venues"],
                            label, rank)

    # Priority order, highest first:
    #   deals_photo.json      a person approved a photo of the venue's own menu
    #   deals_seed.json       a person read the venue's own page
    #   deals_extracted.json  a regex read a page
    # A photo is the menu on the wall, dated, moderated by a human (SPEC section
    # 8), and it is the only source a customer can correct us with. So it now
    # outranks the hand-read seed as well as the crawler: the seed was read once,
    # months ago, and somebody standing in a bar photographing the board is
    # usually telling us it has changed since. Ranking the seed above it meant an
    # approved correction for a seeded venue was merged, counted, and then
    # silently dropped -- the submitter saw nothing change, ever. Written by
    # ingest/review_photos.py -- approving is not publishing, this build is.
    seeded = [dict(v, _rank=1) for v in payload["venues"]]
    photos = (json.load(open(PHOTO_DEALS_JSON, encoding="utf-8"))["venues"]
              if os.path.exists(PHOTO_DEALS_JSON) else [])
    print(f"  {len(photos)} photo-submitted venues (highest priority)")
    payload = dict(payload, venues=[dict(v, _rank=0) for v in photos])
    payload = merge_venues(payload, seeded, "hand-seeded", 1)
    # Written by ingest/read_menus_llm.py: a MODEL read the whole page, or the
    # whole transcript of a menu posted as a picture, and returned the deals on
    # it -- kind, days, clock and items -- each grounded in a quote checked as a
    # literal substring of that document and re-checked against the file on disk
    # at build time. It outranks the extractor because the extractor is a regex
    # grammar that ships nothing for a phrasing it has not met, and it does NOT
    # outrank a person: a hand-read seed and an approved photo still win.
    #
    # This is also the only source that can put a `daily_special` on a card.
    # An agent read the venue's own page by hand, hours and menu together. It
    # outranks every machine pass for the same reason the seed does -- something
    # looked at the page and understood it -- and loses to a person's seed and
    # to an approved photo.
    payload = merge(payload, AGENT_VENUES_JSON, "agent-read venues", 2)
    payload = merge(payload, MENUS_JSON, "model-read menus", 3)
    payload = merge(payload, EXTRACTED_JSON, "machine-extracted", 4)
    # Written by ingest/extract_roundups.py. A dated article about the town's
    # happy hours, read for the bars it names. It fills a card only where
    # nothing above it did -- and in West Chester that was most of the town,
    # because the bars do not put their happy hour on their own sites.
    payload = merge(payload, ROUNDUP_JSON, "roundup-read", 5)
    zones = json.load(open(ZONES_JSON, encoding="utf-8"))
    zone_names = {z["id"]: z["name"] for z in zones["zones"]}
    # Optional: written by ingest/fetch_venue_photos.py. A venue with no entry
    # gets the app's generated tile instead.
    # Written by ingest/extract_prices_llm.py: prices read off the same quotes
    # the deal was built from, each already checked against that quote's text.
    # It only ever fills in items -- windows are the extractor's alone.
    prices = json.load(open(PRICES_JSON, encoding="utf-8")) if os.path.exists(PRICES_JSON) else {}
    # Written by ingest/extract_menu_images.py: the same kind of answer, read
    # off a menu the venue posted as a picture instead of as text. It fills the
    # same slot under the same rule -- items only, never a window -- so the two
    # sidecars merge rather than rank. A venue appears in at most one of them:
    # having quotes to re-read and having no text at all are exclusive.
    if os.path.exists(MENU_IMG_JSON):
        for vid, items in json.load(open(MENU_IMG_JSON, encoding="utf-8")).items():
            prices.setdefault(vid, items)
    # Written by ingest/agent_read_venue.py: an agent hand-read the venue's
    # site the way a person does and the items passed the same grounding and
    # validators. Same slot, same rule -- items only, never a window.
    # Keyed by LICENCE ID, not by slug: two branches of one chain in one town
    # share a slug (the-greene-turtle-...-newark) and only the first ever got
    # the slug-keyed sidecars' items. The licence is the key that cannot collide.
    agent_items = (json.load(open(AGENT_JSON, encoding="utf-8"))
                   if os.path.exists(AGENT_JSON) else {})
    # Written by ingest/read_pages_llm.py: the same kind of answer again, read
    # off the WHOLE happy-hour page rather than off the quotes a regex had
    # already matched out of it. It fills the same slot under the same rule --
    # items only, never a window, every price checked against the venue's own
    # text by the same verify() -- so it merges rather than ranks.
    #
    # It goes FIRST of the three, because it is the only one that read the page.
    # The quote pass sees what the rule engine kept, and on a menu that is
    # routinely the wrong half of the line: The Cheesecake Factory's happy-hour
    # page yields '800 cal $10.95' to the regex, which is a real price attached
    # to a CALORIE COUNT. Where both passes have an answer for a venue, the one
    # that saw the dish name is the better answer.
    page_read = set()
    if os.path.exists(PAGES_JSON):
        read = json.load(open(PAGES_JSON, encoding="utf-8"))
        page_read = set(read)
        for vid, items in read.items():
            prices[vid] = items + [i for i in prices.get(vid, [])
                                   if not any(x["label"].lower() == i["label"].lower()
                                              for x in items)]
    photos = json.load(open(PHOTOS_JSON, encoding="utf-8")) if os.path.exists(PHOTOS_JSON) else {}
    # Written by ingest/geocode_venues.py. Without it the app still works, it
    # just cannot rank by distance or tell you whether you can make it in time.
    coords = json.load(open(COORDS_JSON, encoding="utf-8")) if os.path.exists(COORDS_JSON) else {}

    # The venue base: every licensed premises in the corpus, keyed on its PLCB
    # LID (ingest/build_venue_base.py). This is what the board is a list OF. A
    # deal is an attribute some of them have -- and the ones that don't are the
    # whole point, because a venue nobody can see is a venue nobody can correct.
    base = json.load(open(BASE_JSON, encoding="utf-8")) if os.path.exists(BASE_JSON) else {}
    # The second door. build_venue_base.py already refuses these, but the base
    # is a committed artifact and a rebuild of the SITE must not be able to put
    # a banned venue back on it just because the base is a day old.
    dropped = {}
    for lid in list(base):
        why = excluded(base[lid].get("name", ""), base[lid].get("plcb_name", ""),
                       base[lid].get("license_type", ""))
        if why:
            dropped.setdefault(why, 0)
            dropped[why] += 1
            del base[lid]
    for why in sorted(dropped):
        print(f"  {dropped[why]:>5}  venues held off the board: {why}")
    if not base:
        print("  ! data/venue_base.json missing -- shipping ONLY deal-bearing venues.\n"
              "    Run ingest/build_venue_base.py (needs data/venues.csv).")
    else:
        # A website reaches the board only through the base. Build the bundles
        # off a base older than the site frontier and the newly discovered
        # venues ship WITHOUT a website -- invisible on the card, and it blinds
        # ingest/needy.py, the selection instrument for every scoped run.
        # Doylestown, 2026-09-02: 5 needy where there were 33.
        _sites = os.path.join(REPO, "data", "venue_sites.json")
        if os.path.exists(_sites) and os.path.exists(BASE_JSON) \
                and os.path.getmtime(_sites) > os.path.getmtime(BASE_JSON):
            print("  ! data/venue_sites.json is NEWER than data/venue_base.json --\n"
                  "    websites discovered since the last base build will NOT ship.\n"
                  "    Run ingest/build_venue_base.py first, then rebuild.")

    # A second licence at one building was collapsed into the row that holds the
    # card; a deal crawled against the sibling LID belongs on that same card.
    canon = {lid: lid for lid in base}
    for lid, v in base.items():
        for other in v.get("also_lids", []):
            canon[other] = lid
    # Fallback for a deal whose LID predates the base (the hand-written seed has
    # no LID at all): the number and the ZIP, which is enough to tell two bars
    # apart and is the same key the seed/extract merge above uses.
    by_addr = {}
    for lid, v in base.items():
        by_addr.setdefault(norm_addr(v["address"]), lid)

    def base_lid_for(venue):
        lid = canon.get(str(venue.get("lid") or ""))
        return lid or by_addr.get(norm_addr(venue["address"]))

    by_zone, rejected, hidden = {}, 0, 0
    deals_by_lid, orphans = {}, []

    def surviving(venue):
        """The deals of one venue that are fit to publish: past the PA
        validators, and not decayed out from under their own age."""
        nonlocal rejected, hidden
        # WHOSE LAW? validate_deal() enforces Pennsylvania's Acts 57 & 86 -- a
        # 4h/day cap, a 24h/week cap, a midnight cutoff and PA's banned claims.
        # Those are PA's numbers. Crossing a state line changes the LAW, not
        # just the data source, so a venue in a state we have no ruleset for
        # cannot be judged here at all: running a Delaware bar through the PA
        # validators can suppress a lawful DE deal and, worse, publish one PA
        # would have banned. This is the single door onto the board, so it is
        # the one place the question has to be asked, and it fails CLOSED.
        state = state_of(venue.get("address"))
        if not rules_for(state):
            rejected += len(venue.get("deals", []))
            print(f"  rejected: {venue['name']} -- no ruleset for state "
                  f"{state!r}; its law has not been encoded (see validate_pa.RULES)")
            return []
        deals = []
        # Which of a model-read venue's deals the price sidecar fills in: ONE of
        # them, the richest happy hour. Sedona Taphouse publishes two happy-hour
        # blocks with different menus, and merging the same 24 sidecar prices
        # into both put every item on the card twice.
        model_deals = [d for d in venue.get("deals", [])
                       if d.get("verified_by") == "menu_read_llm"
                       and d.get("type") == "happy_hour"]
        sidecar_target = max(model_deals, key=lambda d: len(d.get("items") or []),
                             default=None)
        for deal in venue.get("deals", []):
            # Two sidecars can both have an answer for the same venue (a
            # quote-price re-read keyed by slug, an agent re-read keyed by
            # lid) and picking whichever is merely non-empty first meant a
            # thin 1-item quote-price entry permanently hid a fuller agent
            # re-read for the same venue -- La Porta stuck at 1 item with an
            # 8-item agent read sitting unused right behind it, 2026-09-03.
            # Take whichever sidecar actually has more.
            extra = max(prices.get(venue["id"]) or [],
                       agent_items.get(str(venue.get("lid") or "")) or [],
                       key=len) or None
            # A venue with NO items takes the sidecar outright. A venue that
            # already has some takes it only from the pass that READ THE PAGE --
            # and then the page wins, because the alternative is measurably
            # worse. Sullivan's is the case: the rule engine reads its menu and
            # `category_of()`, a hand-typed noun whitelist, keeps two of
            # nineteen dishes -- one of them "Jumbo Shrimp Cocktail", filed as a
            # COCKTAIL. Leaving the extractor's items in front meant shipping a
            # shrimp cocktail as a drink while twenty correctly-read items sat
            # in the sidecar unused. The extractor's own items are kept behind
            # the page's, deduplicated on label, so nothing is lost either way.
            read_page = venue["id"] in page_read
            # `menu_read_llm` (ingest/read_menus_llm.py) reads the page itself
            # and brings its own items, so it does not need the sidecars -- but
            # it must not LOSE them either. It outranks the extractor, and on
            # its first run that took Bistro on Bridge from 26 items to 6 and
            # Valley Forge Trattoria from 14 to 6: the same prices, verified
            # against the same pages, dropped on the floor because the venue row
            # that carried them had been outranked. The sidecar merges in BEHIND
            # the model's own items, deduped on label, and only onto a
            # `happy_hour` -- a daily special must never inherit happy-hour
            # prices it did not state.
            model_read = deal is sidecar_target
            # A re-run of ingest/agent_read_venue.py against a thin PDF/image
            # menu can find far more than the venue's existing deal has --
            # La Porta went 1 -> 8, Sedona Taphouse 1-2 -> 18 each, 2026-09-03
            # -- and the existing deal was itself `agent_read` or
            # `auto_extract` with a nonzero item count, so neither branch
            # below fired and the richer read sat in the sidecar unused. A
            # strictly bigger read from the same kind of pass wins.
            richer = extra and len(extra) > len(deal.get("items") or [])
            if extra and (model_read or (
                    deal.get("verified_by") in ("auto_extract", "agent_read") and (
                        not deal.get("items") or read_page or richer))):
                merged = extra + [i for i in (deal.get("items") or [])
                                  if not any(x["label"].lower() == i["label"].lower()
                                             for x in extra)]
                # Applied before the validators, not after, so a price the model
                # read still has to clear the same PA checks as any other item.
                if model_read:
                    # The model read the page; the sidecar only fills the gaps.
                    own = deal.get("items") or []
                    merged = own + [i for i in extra
                                    if not any(x["label"].lower() == i["label"].lower()
                                               for x in own)]
                deal = dict(deal, items=merged, items_source="llm_extract")
            errs = validate_deal(deal, state)
            if errs:
                rejected += 1
                print(f"  rejected: {venue['name']} -- {errs[0]}")
                continue
            conf, _age = decay(deal["confidence"], deal["last_verified_at"], today)
            if conf == "hidden":
                hidden += 1
                continue
            # Ship the facts (confidence as sourced, plus the absolute date) and
            # let the app derive age and any demotion when it renders. The
            # label is display text, not evidence, so it's the one field here
            # safe to reshape -- de_shout() leaves evidence/quote untouched.
            deal = dict(deal, items=[dict(i, label=de_shout(i.get("label", "")))
                                      for i in deal.get("items") or []])
            deals.append(dict(deal))
        for e in validate_food_combo_count(deals):
            print(f"  rejected: {venue['name']} -- {e}")
            deals = []
        return deals

    def place(venue, deals):
        lid = base_lid_for(venue)
        if lid is None:
            # A deal for a premises the base has never heard of. It still ships
            # -- a proven happy hour is not something to drop over a join -- but
            # it is counted, because a rising number here means the base is stale.
            orphans.append(venue["name"])
        key = lid or f"orphan:{venue['id']}"
        held = deals_by_lid.get(key)
        # Two licences at one building: the higher-priority source first, and
        # within one source the richer read rather than whichever sorted first.
        if held is None or (venue.get("_rank", 9), -len(deals)) < (
            held[0].get("_rank", 9), -len(held[1])
        ):
            deals_by_lid[key] = (venue, deals)

    for venue in payload["venues"]:
        deals = surviving(venue)
        if deals:
            place(venue, deals)

    # The duplicates merge set aside. One publishes only where the source that
    # outranked it ended up with nothing left to say.
    for venue, beat_by in reserve:
        if (base_lid_for(beat_by) or f"orphan:{beat_by['id']}") in deals_by_lid:
            continue
        deals = surviving(venue)
        if deals:
            print(f"  fallback: {venue['name']} -- {beat_by['name']} outranked it "
                  "and then published nothing")
            place(venue, deals)

    for key, (venue, deals) in deals_by_lid.items():
        b = base.get(key) or {}
        v = {
            "id": b.get("lid") or venue["id"],
            "lid": b.get("lid"),
            # The id every shared link minted before the board was keyed on LIDs.
            # #v=iron-hill-media must keep opening Iron Hill.
            "slug": venue["id"],
            # A hand-checked seed name is a person's reading of the sign; below
            # it, the trade name Places resolved beats the crawler's.
            "name": de_shout(venue["name"] if venue.get("verified_by") != "auto_extract"
                              else (b.get("name") or venue["name"])),
            "address": b.get("address") or venue["address"],
            "zone_id": venue["zone_id"],
            "website": venue.get("website") or b.get("website"),
            "plcb_name": venue.get("plcb_name") or b.get("plcb_name"),
            "license_type": b.get("license_type", ""),
        }
        at = coords.get(venue["id"])
        if at:
            v["lat"], v["lng"] = at["lat"], at["lng"]
            # A road-level match is a street centroid: good to a block, not a
            # doorway. The app rounds those distances harder.
            v["geo_precision"] = at.get("precision", "?")
        elif b.get("lat") is not None:
            v["lat"], v["lng"], v["geo_precision"] = b["lat"], b["lng"], b["geo_precision"]
        shot = photos.get(venue["id"])
        if shot and os.path.exists(os.path.join(REPO, "web", shot["file"])):
            v["photo"] = {"file": shot["file"], "attribution": shot.get("attribution", "")}
        elif b.get("photo"):
            v["photo"] = b["photo"]
        v["deals"] = deals
        # A deal can arrive from the crawl or the seed without the base, so the
        # base filter above is not enough on its own: check the venue itself.
        if excluded(v.get("name", ""), v.get("plcb_name") or "",
                    v.get("license_type", "")):
            continue
        by_zone.setdefault(venue["zone_id"], []).append(v)

    # Then every venue the corpus knows about that no source gave us a window
    # for. It ships with deals: [] and the app renders it as a card asking to be
    # filled in -- that ask IS the coverage plan.
    outside = 0
    for lid, b in base.items():
        if lid in deals_by_lid:
            continue
        if not b["zone_id"]:
            # A licence whose municipality matched no zone -- Croydon, St Peters.
            # There is no zone for a person to select, so a card for it is
            # unreachable, and shipping it invents a nameless zone in the picker.
            outside += 1
            continue
        v = {k: b[k] for k in ("lid", "name", "address", "zone_id", "license_type")
             if k in b}
        if v.get("name"):
            v["name"] = de_shout(v["name"])
        v["id"] = lid
        v["plcb_name"] = b["plcb_name"]
        for k in ("website", "lat", "lng", "geo_precision", "photo", "also_lids"):
            if k in b:
                v[k] = b[k]
        v["deals"] = []
        by_zone.setdefault(b["zone_id"], []).append(v)

    # ---- the menu ratchet ------------------------------------------------
    #
    # A published window naming no item is the signature of a scraper failure
    # (see ingest/report_holes.py). It is not always one: a venue may genuinely
    # print its hours and no menu. The difference is a thing somebody looked at
    # and recorded, and until that happens the hole is UNACCOUNTED.
    #
    # The count of unaccounted holes may not rise. That is the whole gate, and
    # it is the only part of this pipeline that survives into the next zone:
    # every fix ratchets the budget down, and a new zone that arrives with more
    # silent windows than the last one fails the build instead of shipping a
    # board full of cards that name nothing. Lower the budget when you fix
    # something; raising it is a decision, not a step.
    verdicts = {}
    if os.path.exists(VERDICTS):
        verdicts = json.load(open(VERDICTS, encoding="utf-8")).get("venues", {})
    menu_ratchet(by_zone, verdicts, HOLE_BUDGET)

    merged = collapse_name_collisions(by_zone)
    branded = name_the_surviving_branches(by_zone)

    for venues in by_zone.values():
        # Deal-bearing first, then alphabetical: the bundle order is what the app
        # falls back to whenever two rows score the same.
        venues.sort(key=lambda v: (not v["deals"], v["name"].lower(), v["id"]))

    os.makedirs(OUT_DIR, exist_ok=True)
    index = []
    for zid, venues in sorted(by_zone.items()):
        # Two files per zone, and the split is a load-time decision, not a
        # taxonomy. The app boots by fetching EVERY zone's deals so it can answer
        # "what's on right now" across the whole area -- 169 venues, small. The
        # venue base is 2,900 and would be a megabyte on a phone in a parking
        # lot, so it ships per zone and is fetched only when that zone is picked.
        dealful = [v for v in venues if v["deals"]]
        rest = [v for v in venues if not v["deals"]]
        meta = {"zone_id": zid, "name": zone_names.get(zid, zid),
                "built_at": today.isoformat()}
        path = os.path.join(OUT_DIR, f"zone-{zid}.json")
        with open(path, "w", encoding="utf-8") as fh:
            # Every zone's deal bundle is fetched at boot.  Keep it compact so
            # adding a correctly sourced card cannot inflate the initial
            # download for every visitor; the separate no-deal venue list is
            # fetched only for the selected zone and stays readable on disk.
            json.dump(dict(meta, venues=dealful), fh, separators=(",", ":"))
        rest_path = os.path.join(OUT_DIR, f"venues-{zid}.json")
        with open(rest_path, "w", encoding="utf-8") as fh:
            json.dump(dict(meta, venues=rest), fh, indent=1)
        index.append(
            {
                "id": zid,
                "name": zone_names.get(zid, zid),
                "venues": len(venues),
                # How many of them we can actually tell you the hours for. The
                # zone picker shows this, because "59 venues, 6 with hours" is
                # the honest state of the board and hiding it would be the lie.
                "with_deals": len(dealful),
                "deals": sum(len(v["deals"]) for v in venues),
            }
        )
        print(f"  {zid:<32}{len(venues):>4} venues{len(dealful):>4} with hours  "
              f"{os.path.getsize(path):>6,} + {os.path.getsize(rest_path):>7,} bytes")

    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"built_at": today.isoformat(), "zones": index}, fh, indent=1)

    # What is published, keyed by licence ID. The Worker reads this to answer one
    # question before it auto-approves a photo: does this venue already have
    # hours? Adding hours to a blank venue publishes itself; CHANGING hours that
    # are already on the board is the damaging case and waits for a person. The
    # admin page reads the same file to show a reviewer what approving replaces.
    #
    # Deliberately small -- windows and provenance, no items, no prices. It is
    # fetched by a Worker on a submission, not by a reader.
    board = {}
    for venue in (v for vs in by_zone.values() for v in vs if v["deals"]):
        entry = {
            "name": venue["name"],
            "deals": [
                {"type": d["type"], "windows": d["windows"],
                 "source": {"kind": (d.get("source") or {}).get("kind", "")}}
                for d in venue["deals"]
            ],
        }
        for key in [venue.get("lid")] + list(venue.get("also_lids") or []):
            if key:
                board[str(key)] = entry
    with open(os.path.join(OUT_DIR, "board-by-lid.json"), "w", encoding="utf-8") as fh:
        json.dump(board, fh, indent=1)

    # Licence ID -> zone, for EVERY venue including the 2,729 with no hours.
    # The live overlay needs it: a photo that auto-publishes is by definition
    # for a venue with nothing on the board, so that venue is not in any deals
    # bundle and the app has to be told which zone base to go and fetch.
    lid_zone = {}
    for venue in (v for vs in by_zone.values() for v in vs):
        for key in [venue.get("lid")] + list(venue.get("also_lids") or []):
            if key:
                lid_zone[str(key)] = venue["zone_id"]
    with open(os.path.join(OUT_DIR, "lid-zone.json"), "w", encoding="utf-8") as fh:
        json.dump(lid_zone, fh, separators=(",", ":"))

    # Every venue we hold, by name, so a submitter can find their bar.
    #
    # The submit picker used to search only what the app had in memory: the 169
    # venues with hours, plus whatever zone the reader had already opened. Type
    # "Taku" with no town picked and it answered "no match" about a venue that
    # has been in our data all along -- and a missing route reads exactly like a
    # missing record, so the person concludes we do not have their bar and
    # stops. This is the file that lets it answer honestly.
    #
    # Rows, not objects, and fetched only when the picker opens -- never at
    # boot. It is ~2,900 entries and the reader who is not submitting a photo
    # should not pay for it. Zone travels with each row because two bars share a
    # name often enough that the town is what tells them apart.
    name_index = [
        [str(v["lid"]), v["name"], v.get("address", ""), v["zone_id"]]
        for vs in by_zone.values()
        for v in vs
        if v.get("lid")
    ]
    name_index.sort(key=lambda r: (r[1].lower(), r[0]))
    with open(os.path.join(OUT_DIR, "name-index.json"), "w", encoding="utf-8") as fh:
        json.dump({"built_at": today.isoformat(),
                   "zone_names": zone_names,
                   "venues": name_index}, fh, separators=(",", ":"))

    published = [v for vs in by_zone.values() for v in vs]
    dealful = [v for v in published if v["deals"]]
    # The service worker cache name has always keyed on the count of what ships.
    # It must keep keying on the DEAL count: the venue base moves only when the
    # PLCB corpus does, so keying on it would stop evicting on a deal-only build.
    stamp_service_worker(today.isoformat(), len(dealful))
    located = sum(1 for v in published if "lat" in v)
    print(f"\n{sum(z['deals'] for z in index)} deals across {len(index)} zones"
          f"  ({rejected} rejected by validators, {hidden} decayed out)")
    print(f"{len(published)} venues ship, {len(dealful)} with a published window "
          f"({len(published) - len(dealful)} asking to be filled in)")
    if merged:
        print(f"  {merged} second licence(s) at a bar already on the board were "
              f"collapsed into its card (one bar, one card)")
    if branded:
        print(f"  {branded} venue(s) share a name with a real second branch in "
              f"their zone and now carry the street that tells them apart")
    if outside:
        print(f"  {outside} licensed venue(s) sit outside every zone and cannot be "
              f"reached in the UI -- add a zone in data/zones.json to surface them")
    # STRANDED: items that were read, passed the grounding gate and the
    # validators, cost real money, and reached no card. The sidecars merge
    # INSIDE `for deal in venue["deals"]`, so a venue with no deterministic
    # window never enters the loop -- and a venue like Lefty's Alley & Eats,
    # which exists only in venue_base.json and carries no deal row at all,
    # never reaches surviving() in the first place. Neither case errors. The
    # only symptom was a zero-byte board diff after a paid run.
    #
    # Asked HERE, against what actually shipped, because that is the only
    # place the question is answerable for both cases at once. It reports; it
    # does not fix. Publishing these needs the one thing we hold and have never
    # published -- the agent's own reading of the venue's HOURS -- and that is
    # Paul's call, not this file's.
    shipped_items = {v.get("lid") for v in published
                     for d in v.get("deals") or [] if d.get("items")}
    shipped_items |= {v["id"] for v in published
                      for d in v.get("deals") or [] if d.get("items")}
    stranded = {lid: len(items) for lid, items in agent_items.items()
                if lid not in shipped_items}
    if stranded:
        names = {str(b.get("lid")): b.get("name") for b in base.values()}
        n = sum(stranded.values())
        who = ", ".join(f"{names.get(k, k)} ({c})" for k, c in
                        list(stranded.items())[:3])
        print(f"  ! {n} verified item(s) across {len(stranded)} venue(s) were READ "
              f"AND NEVER PUBLISHED -- no window means no deal to carry them: "
              f"{who}")
    if orphans:
        print(f"  ! {len(orphans)} deal(s) matched no venue in the base "
              f"-- rebuild it: {', '.join(orphans[:3])}")
    print(f"{located}/{len(published)} venues have coordinates"
          + ("" if located == len(published) else "  -- run ingest/geocode_venues.py"))


if __name__ == "__main__":
    main()
