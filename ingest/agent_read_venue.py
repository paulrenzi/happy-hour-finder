#!/usr/bin/env python3
"""An agent hand-reads one venue's happy hour, the way a person does.

    python ingest/agent_read_venue.py --lids run.lids --show --rejects
    python ingest/agent_read_venue.py --zone newark_de --show
    python ingest/agent_read_venue.py --lids run.lids --force     # re-read

WHY THIS EXISTS. The Greene Turtle, Christiana, 2026-09-03. Its happy hour is
one button on the location page, "Happy Hour Menu", pointing at a JPG: Monday
to Friday 3-6, $3 shots, $5 cocktails, $7 bites, 23 items. A person finds it
in three moves. The crawler had captured that JPG the night before and a
separate, hand-run reader had never been pointed at it; when it was, a regex
gate refused all 23 items because the price is printed once over each column.
Fourteen hand-typed commands with regex gates between them is not a process
that finds a menu. A reader with judgement is.

So: ONE model call per venue, with the tools a person uses -- fetch a page,
follow the link that says happy hour, download the PDF or picture, look at it
-- and the model decides what the venue published. The deterministic code
keeps only the jobs it is good at: naming the venue, the grounding gate (every
item's quote and price span must be character-for-character in the model's
own transcript), the PA/DE validators, and the human review before anything
ships. Nothing the model says reaches a card on its own say-so.

Runs on the `claude` CLI subscription like every other model pass here. The
model gets WebFetch, Read and curl, nothing else: it can look, it cannot
write or run anything. Downloads land under data/agent_reads/<lid>/.

Writes:
  data/agent_reads.json   every read: source URL, kind, transcript, raw deals,
                          cost -- the evidence, keyed by licence id
  data/deals_agent.json   verified PRICED ITEMS ONLY, keyed by licence id,
                          merged into cards by build_bundles.py under the same
                          rule as the other sidecars: items, never windows.
                          The window a venue publishes stays the deterministic
                          extractor's; the agent's window reading is kept in
                          agent_reads.json for a future decision.
"""

import argparse
import concurrent.futures as cf
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_menu_images import items_from  # noqa: E402
from validate_pa import CATEGORIES  # noqa: E402

BASE = os.path.join(REPO, "data", "venue_base.json")
READS = os.path.join(REPO, "data", "agent_reads.json")
OUT = os.path.join(REPO, "data", "deals_agent.json")
WORK = os.path.join(REPO, "data", "agent_reads")
MODEL = os.environ.get("HHF_AGENT_MODEL", "opus")
MAX_TURNS = 14

PROMPT = """You are hand-reading one bar's happy hour for a listings site that
publishes only what the venue itself put in writing. Work like a person would.

Venue: {name}
Address: {address}
Website: {website}
Scratch directory for downloads: {workdir}

Do this:
1. WebFetch the website. Look for the happy hour: a section on the page, a
   link or button that says happy hour / specials / menu, a location page for
   THIS address if the site covers several locations.
2. Follow the link. If it is a page, WebFetch it. If it is a PDF or an image
   (jpg/png/webp), download it with curl into the scratch directory, e.g.
   curl -sL -o "{workdir}/menu.jpg" "<url>", then Read that file to look at it.
   A menu is often a picture; its words are pixels until you look.
3. Stop as soon as you have found where the venue states its happy hour, or
   after you have tried the obvious places (home page, menu page, specials
   page, this location's page) and found nothing. Do not guess a URL that the
   site never linked to. Do not read other locations' menus for this one.

You are a reader, not an author. Every price, time and item you report must
be printed by the venue in the page or picture you read. If it says "select
drafts", say select drafts. If a price is cut off, leave it out. If days are
not printed, return no windows. An omission costs one deal; an invention costs
the reader's trust.

Transcribe the happy-hour section into `transcript` verbatim. Where a price is
printed once as a header or badge over a GROUP of items ("$3" above a column
of shots), transcribe that price where it stands, then the items under it;
every one of those items has that price. Then read the deals out of the
transcript. Each item's `quote` is the exact substring of the transcript it
came from, and `price_quote` is the exact substring where THAT item's price is
printed -- its own line if the price is on it, otherwise the header or badge
that governs it, e.g. "$3". Both are checked character-for-character against
the transcript and dropped if they are not there, so never paraphrase.

Times are 24-hour "HH:MM". Days are 1=Monday through 7=Sunday. Midnight at the
end of a window is "24:00".

Reply with ONE JSON object and nothing else. No prose, no code fence.

{{
  "found": true or false -- true only if you found the venue's own statement
           of a happy hour (hours, items, or both),
  "source_url": "the URL of the page, PDF or image the transcript was read
           from, or \\"\\"",
  "kind": "page" | "pdf" | "image" | "none",
  "path_taken": ["one short line per fetch or download you made"],
  "why_not": "if found is false, one sentence on what the site offered
           instead; else \\"\\"",
  "venue_name_on_menu": "the venue name as printed, or \\"\\"",
  "transcript": "the happy-hour section, verbatim, in reading order",
  "deals": [
    {{
      "type": "happy_hour" | "daily_special" | "food_combo",
      "windows": [{{"dow": 1-7, "start": "16:00", "end": "18:00"}}],
      "items": [
        {{
          "category": one of: {categories},
          "label": "short description as printed",
          "price_usd": number or null,
          "discount_pct": number or null,
          "quote": "exact substring of transcript",
          "price_quote": "exact substring of transcript where this price is printed"
        }}
      ],
      "fine_print": "conditions printed with the happy hour, or \\"\\""
    }}
  ]
}}
"""

_lock = threading.Lock()


def load(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def save(path, doc):
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True, ensure_ascii=False)
    os.replace(tmp, path)


def tiers(zone, base):
    """Split a zone's venues by the evidence we ALREADY hold on each one.

    A blanket --zone run reads every website in the town at the same price,
    including the ones the crawl has already shown have nothing to read.
    Measured on newark_de 2026-09-03: of 153 needy venues, 10 had a menu
    image captured and never read, 25 had a happy-hour quote on the page,
    and 118 had a website and no hh-shaped evidence of any kind -- 77% of
    the spend against the population that publishes no price anywhere.

    🔑 Order a run by the evidence, cheapest and richest first, and measure
    the hit rate of each tier before paying for the next.

      A  a menu image is captured and unread   -- we already paid to fetch it
      B  the crawl quoted happy hour on a page -- something is there to read
      C  a website, and no evidence at all     -- a blind read
    """
    hits = load(os.path.join(REPO, "data", "crawl_hits.json"))
    site2lid = {}
    for lid, v in base.items():
        w = (v.get("website") or "").rstrip("/").lower()
        if w:
            site2lid.setdefault(w, lid)
    a, b = set(), set()
    for v in hits.values():
        if v.get("zone_id") != zone:
            continue
        lid = site2lid.get((v.get("website") or "").rstrip("/").lower())
        if not lid:
            continue
        (a if v.get("menu_images") else b if v.get("hits") else set()).add(lid)
    return a, b


def population(args):
    base = load(BASE)
    if args.lids:
        only = [ln.strip() for ln in open(args.lids, encoding="utf-8") if ln.strip()]
        rows = [(lid, base[lid]) for lid in only if lid in base]
    else:
        rows = [(lid, v) for lid, v in base.items() if v.get("zone_id") == args.zone]
    rows = [(lid, v) for lid, v in rows if v.get("website")]

    if args.needy or args.tier:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import needy as _needy
        _needy.warn_if_base_is_stale()
        zones = {v.get("zone_id") for _, v in rows}
        keep = set()
        for z in zones:
            keep |= {lid for lid, _n, _w in _needy.needy(z)}
        rows = [(lid, v) for lid, v in rows if lid in keep]

    if args.tier:
        want = set(args.tier.upper())
        zone = args.zone or (rows[0][1].get("zone_id") if rows else None)
        a, b = tiers(zone, base) if zone else (set(), set())
        pick = set()
        if "A" in want:
            pick |= a
        if "B" in want:
            pick |= b
        rows = ([(lid, v) for lid, v in rows if lid in pick] if want <= {"A", "B"}
                else [(lid, v) for lid, v in rows if lid in pick or lid not in a | b])
    return rows[: args.limit] if args.limit else rows


class TurnsExhausted(RuntimeError):
    """The session ran out of turns. A real outcome, not a transient failure.

    It carries what the attempt cost, because that money was spent whether or
    not the read returned anything, and a retry at the same --max-turns spends
    it again for the same ending.
    """

    def __init__(self, msg, cost, turns):
        super().__init__(msg)
        self.cost, self.turns = cost, turns


def run_agent(lid, venue):
    """One `claude -p` session over one venue. Returns (read, cost_usd)."""
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("`claude` is not on PATH -- this runs on the CLI subscription")
    workdir = os.path.join(WORK, lid)
    os.makedirs(workdir, exist_ok=True)
    prompt = PROMPT.format(name=venue["name"], address=venue["address"],
                           website=venue["website"], workdir=workdir.replace("\\", "/"),
                           categories=", ".join(sorted(CATEGORIES)))
    proc = subprocess.run(
        [exe, "-p", "--model", MODEL, "--output-format", "json",
         "--max-turns", str(MAX_TURNS),
         # Look, never touch: fetch pages, download with curl, read what landed.
         "--allowedTools", "WebFetch,Read,Bash(curl:*)",
         "--setting-sources", "", "--exclude-dynamic-system-prompt-sections"],
        input=prompt, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900)
    # 🛑 A NON-ZERO EXIT IS NOT AN EMPTY RESULT. The CLI exits 1 when a session
    # runs out of turns -- and still prints its whole JSON envelope, including
    # what it spent. LongHorn and Cheddar's (newark_de, 2026-09-03) failed this
    # way: `exited 1: ` with an EMPTY stderr, $0.60 of real model time each,
    # recorded as `error`, reported in the run total as $0.00, and re-read at
    # full price on every subsequent run because the lane retries errors.
    # Parse stdout first and let the envelope say what happened; only a run
    # that printed nothing parseable is an error.
    reply = None
    if proc.stdout.strip():
        try:
            reply = json.loads(proc.stdout)
        except json.JSONDecodeError:
            reply = None
    if reply is None:
        raise RuntimeError(f"claude -p exited {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[:300]}")
    if proc.returncode != 0 and not (reply.get("result") or ""):
        raise TurnsExhausted(
            f"exited {proc.returncode} after {reply.get('num_turns')} turns "
            f"(stop_reason {reply.get('stop_reason')!r}), "
            f"${float(reply.get('total_cost_usd') or 0):.2f} spent",
            float(reply.get("total_cost_usd") or 0),
            int(reply.get("num_turns") or 0))
    body = reply.get("result") or ""
    m = re.search(r"\{.*\}", body, re.S)
    if not m:
        raise ValueError(f"no JSON object in reply: {body[:200]}")
    return json.loads(m.group(0)), float(reply.get("total_cost_usd") or 0), int(reply.get("num_turns") or 0)


def one(lid, venue, today):
    try:
        read, cost, turns = run_agent(lid, venue)
    except TurnsExhausted as err:
        # Not an `error` key: this venue is DONE for this --max-turns, and a
        # retry buys the same ending again. Its cost is recorded like any read.
        return lid, {"read_at": today, "model": MODEL, "cost_usd": round(err.cost, 4),
                     "turns": err.turns, "found": False, "kind": "exhausted",
                     "why_not": str(err), "path_taken": [], "transcript": "",
                     "deals": [], "items_kept": 0, "dropped": []}, [], []
    except (RuntimeError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as err:
        return lid, {"error": f"{type(err).__name__}: {str(err)[:300]}", "read_at": today}, [], []
    items, dropped = ([], []) if not read.get("found") else items_from(read)
    rec = {
        "read_at": today, "model": MODEL, "cost_usd": round(cost, 4), "turns": turns,
        "found": bool(read.get("found")), "kind": read.get("kind", ""),
        "source_url": read.get("source_url", ""), "why_not": read.get("why_not", ""),
        "path_taken": read.get("path_taken") or [],
        "venue_name_on_menu": read.get("venue_name_on_menu", ""),
        "transcript": read.get("transcript", ""),
        "deals": read.get("deals") or [],       # raw, windows included -- evidence
        "items_kept": len(items), "dropped": dropped,
    }
    return lid, rec, items, dropped


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lids", help="file of licence ids, one per line")
    g.add_argument("--zone", help="every venue with a website in this zone")
    ap.add_argument("--needy", action="store_true",
                    help="only venues whose card has no items yet (ingest/needy.py)")
    ap.add_argument("--tier", metavar="A|B|AB|C",
                    help="select by the evidence already held: A a captured, unread "
                         "menu image; B the crawl quoted happy hour; C neither. "
                         "Implies --needy. Run A before paying for B, B before C.")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2,
                    help="parallel CLI sessions; 3 lost a quarter of reads to exit 1")
    ap.add_argument("--force", action="store_true", help="re-read venues already on file")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--rejects", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("! ANTHROPIC_API_KEY is set; it outranks the CLI login and would bill an "
              "API account. Unset it first.", file=sys.stderr)
        return 1

    reads, out = load(READS), load(OUT)
    todo = [(lid, v) for lid, v in population(args)
            if args.force or lid not in reads or "error" in reads[lid]]
    print(f"{len(todo)} venue(s) to read, model {MODEL}, {args.workers} at a time\n")
    today = datetime.date.today().isoformat()
    spent, hit = 0.0, 0

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one, lid, v, today) for lid, v in todo]
        for n, fut in enumerate(cf.as_completed(futs), 1):
            lid, rec, items, dropped = fut.result()
            venue = dict(todo)[lid]
            name = venue["name"][:34]
            with _lock:
                reads[lid] = rec
                if items:
                    # Keyed by licence id. The slug the other sidecars use
                    # collides for two branches of a chain in one town.
                    fresh = {x["label"].lower() for x in items}
                    held = [i for i in out.get(lid, []) if i.get("label", "").lower() not in fresh]
                    out[lid] = held + items
                # Written every venue: a read is slow and an interrupted run
                # must not throw away what it already paid for.
                save(READS, reads)
                save(OUT, out)
            spent += rec.get("cost_usd", 0)
            hit += 1 if items else 0
            if "error" in rec:
                print(f"[{n}/{len(todo)}] {name:<36} !! {rec['error'][:90]}")
                continue
            tag = (f"{rec['kind']:<5} {len(items)} item(s)" if rec["found"]
                   else f"none  -- {rec['why_not'][:60]}")
            print(f"[{n}/{len(todo)}] {name:<36} {tag}  ${rec['cost_usd']:.2f} {rec['turns']}t")
            if rec["found"]:
                print(f"      {rec['source_url'][:110]}")
            if args.show:
                for it in items:
                    amt = (f"${it['price_usd']:g}" if "price_usd" in it
                           else f"{it['discount_pct']:g}% off")
                    print(f"      {amt:>8}  {it['label']}")
            if args.rejects:
                for d in dropped:
                    print(f"      x {d}")

    # THIS RUN, not the whole file. `len(out)` counted every venue the sidecar
    # had ever held, so a run that found one venue reported two.
    print(f"\n{hit} of {len(todo)} venue(s) read returned items ({len(out)} on file) "
          f"-> {OUT}; reads -> {READS}; "
          f"about ${spent:.2f} of subscription-metered model time")
    print("Nothing is on the board yet: python ingest/build_bundles.py, then "
          "python tests/live_front_door.py <zone> after deploy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
