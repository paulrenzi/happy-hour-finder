#!/usr/bin/env python3
"""An agent reads one venue's EVENTS calendar, the way a person does.

    python ingest/read_events_venue.py --zone phoenixville --show
    python ingest/read_events_venue.py --lids run.lids --show --post
    python ingest/read_events_venue.py --zone phoenixville --force

Sibling of agent_read_venue.py, pointed at the other half of the night
(PLAYBOOK-NIGHT-OUT.md). The Fenix on Bridge St publishes its bands as a JPEG
of a calendar; Twelve78 as Facebook event embeds; JamBase lists neither. The
four fields nobody carries -- start, set length, cover, kitchen open -- are
what this asks for, and it reports only what the venue printed.

One `claude -p` session per venue with WebFetch, Read and curl. The model
returns events for the next HORIZON days. Deterministic code keeps the jobs it
is good at: the grounding gate (every event's `quote` must be a substring of
the model's own transcript), the shape check, and the post to the Worker's
review queue. Nothing reaches a card until a person approves it in the queue
(worker: GET /admin/events?status=pending).

Writes:
  data/events_reads.json   every read, keyed by licence id -- the evidence
  --post                   also POST the grounded rows to $SUBMIT_API/admin/events
                           as status `pending`. Without it nothing leaves the PC.
"""

import argparse
import concurrent.futures as cf
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = os.path.join(REPO, "data", "venue_base.json")
SITES = os.path.join(REPO, "data", "venue_sites.json")
BUNDLES = os.path.join(REPO, "web", "data")
READS = os.path.join(REPO, "data", "events_reads.json")
WORK = os.path.join(REPO, "data", "events_reads")
MODEL = os.environ.get("HHF_AGENT_MODEL", "opus")
MAX_TURNS = int(os.environ.get("HHF_MAX_TURNS", "14"))
HORIZON = 14
KINDS = {"live_music", "trivia", "dj", "comedy", "other"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CLOCK_RE = re.compile(r"^([01]\d|2[0-4]):[0-5]\d$")

PROMPT = """You are reading one bar's EVENTS for a listings site that publishes only
what the venue itself put in writing. Work like a person would.

Venue: {name}
Address: {address}
Website: {website}
Today: {today}. Report events dated {today} through {until} only.
Scratch directory for downloads: {workdir}

Do this:
1. WebFetch the website. Look for events, live music, entertainment, calendar,
   what's on, trivia. Follow the link. A calendar is very often a PICTURE (jpg,
   png) or a PDF: download it with curl into the scratch directory, e.g.
   curl -sL -o "{workdir}/calendar.jpg" "<url>", then Read that file to look
   at it. If the page embeds Facebook events, read what the embed shows.
2. Stop when you have found where the venue states its events, or after the
   obvious places (home, events, calendar, music, this location's page) gave
   nothing. Do not guess URLs the site never linked. Do not read other
   locations' calendars for this one.

You are a reader, not an author. Every act, date, time and price must be
printed by the venue in what you read. A standing line like "live acoustic
music every Friday and Saturday 7-10pm" counts: expand it into one event per
date inside the window, each quoting that line. If a start time is not
printed, leave start null. If no cover is printed, leave cover_usd null --
do NOT write 0 unless "no cover" or "free" is printed. kitchen_open is 1 only
if the venue says food is served during the event, 0 only if it says the
kitchen closes, else null.

Transcribe the events section into `transcript` verbatim. Each event's `quote`
is the exact substring of the transcript it came from; it is checked
character-for-character and the event is dropped if it is not there.

Times are 24-hour "HH:MM". Dates are "YYYY-MM-DD".

Reply with ONE JSON object and nothing else. No prose, no code fence.

{{
  "found": true or false,
  "source_url": "URL of the page, PDF or image the transcript was read from, or \\"\\"",
  "kind": "page" | "image" | "pdf" | "none",
  "path_taken": ["one short line per fetch or download"],
  "why_not": "if found is false, one sentence; else \\"\\"",
  "transcript": "the events section, verbatim, in reading order",
  "events": [
    {{
      "date": "YYYY-MM-DD",
      "act": "name as printed",
      "kind": "live_music" | "trivia" | "dj" | "comedy" | "other",
      "start": "HH:MM" or null,
      "end": "HH:MM" or null,
      "cover_usd": number or null,
      "kitchen_open": 1 | 0 | null,
      "quote": "exact substring of transcript"
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


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def ground(read, today, until):
    """Keep only events whose quote is in the transcript and whose shape holds.

    Returns (kept, dropped). Pure: tested in tests/test_events_reader.py.
    """
    transcript = norm(read.get("transcript", ""))
    kept, dropped = [], []
    for ev in read.get("events") or []:
        if not isinstance(ev, dict):
            dropped.append("not an object")
            continue
        q = norm(ev.get("quote", ""))
        act = (ev.get("act") or "").strip()
        date = (ev.get("date") or "").strip()
        why = None
        if not q or q not in transcript:
            why = "quote not in transcript"
        elif not act:
            why = "no act"
        elif not DATE_RE.match(date) or not (today <= date <= until):
            why = f"date {date!r} outside {today}..{until}"
        elif ev.get("kind") not in KINDS:
            why = f"kind {ev.get('kind')!r}"
        elif any(ev.get(k) not in (None, "") and not CLOCK_RE.match(str(ev.get(k)))
                 for k in ("start", "end")):
            why = "bad clock"
        elif ev.get("cover_usd") not in (None, "") and not isinstance(ev.get("cover_usd"), (int, float)):
            why = "cover not a number"
        if why:
            dropped.append(f"{act or '?'} {date}: {why}")
            continue
        kept.append({
            "date": date, "act": act[:120], "kind": ev["kind"],
            "start": ev.get("start") or None, "end": ev.get("end") or None,
            "cover_usd": ev.get("cover_usd") if ev.get("cover_usd") != "" else None,
            "kitchen_open": ev.get("kitchen_open") if ev.get("kitchen_open") in (0, 1) else None,
            "quote": (ev.get("quote") or "")[:500],
        })
    return kept, dropped


class TurnsExhausted(RuntimeError):
    def __init__(self, msg, cost, turns):
        super().__init__(msg)
        self.cost, self.turns = cost, turns


def run_agent(lid, venue, today, until):
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("`claude` is not on PATH -- this runs on the CLI subscription")
    workdir = os.path.join(WORK, lid)
    os.makedirs(workdir, exist_ok=True)
    prompt = PROMPT.format(name=venue["name"], address=venue["address"],
                           website=venue["website"], workdir=workdir.replace("\\", "/"),
                           today=today, until=until)
    proc = subprocess.run(
        [exe, "-p", "--model", MODEL, "--output-format", "json",
         "--max-turns", str(MAX_TURNS),
         "--allowedTools", "WebFetch,Read,Bash(curl:*)",
         "--setting-sources", "", "--exclude-dynamic-system-prompt-sections"],
        input=prompt, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900)
    # A non-zero exit is not an empty result: the envelope still prints.
    reply = None
    if proc.stdout.strip():
        try:
            reply = json.loads(proc.stdout)
        except json.JSONDecodeError:
            reply = None
    if reply is None:
        raise RuntimeError(f"claude -p exited {proc.returncode}: {(proc.stderr or proc.stdout)[:300]}")
    if proc.returncode != 0 and not (reply.get("result") or ""):
        raise TurnsExhausted(
            f"exited {proc.returncode} after {reply.get('num_turns')} turns, "
            f"${float(reply.get('total_cost_usd') or 0):.2f} spent",
            float(reply.get("total_cost_usd") or 0), int(reply.get("num_turns") or 0))
    body = reply.get("result") or ""
    m = re.search(r"\{.*\}", body, re.S)
    if not m:
        raise ValueError(f"no JSON object in reply: {body[:200]}")
    return json.loads(m.group(0)), float(reply.get("total_cost_usd") or 0), int(reply.get("num_turns") or 0)


def one(lid, venue, today, until):
    try:
        read, cost, turns = run_agent(lid, venue, today, until)
    except TurnsExhausted as err:
        return lid, {"read_at": today, "model": MODEL, "cost_usd": round(err.cost, 4),
                     "turns": err.turns, "found": False, "kind": "exhausted",
                     "why_not": str(err), "path_taken": [], "transcript": "",
                     "events": [], "kept": [], "dropped": []}
    except (RuntimeError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as err:
        return lid, {"error": f"{type(err).__name__}: {str(err)[:300]}", "read_at": today}
    kept, dropped = ([], []) if not read.get("found") else ground(read, today, until)
    return lid, {
        "read_at": today, "model": MODEL, "cost_usd": round(cost, 4), "turns": turns,
        "found": bool(read.get("found")), "kind": read.get("kind", ""),
        "source_url": read.get("source_url", ""), "why_not": read.get("why_not", ""),
        "path_taken": read.get("path_taken") or [],
        "transcript": read.get("transcript", ""),
        "events": read.get("events") or [],     # raw -- evidence
        "kept": kept, "dropped": dropped,
    }


def bundle_sites():
    """Websites the BUILT bundles carry, for venues `venue_sites.json` lacks.

    A venue can reach the board with a website and never get a `venue_sites`
    row -- 33 of the 471 published venues are in exactly that state, 118 North
    in Wayne among them. Without this the reader silently skips a venue whose
    site we publish on its own card, and prints "0 venue(s) to read", which
    reads as "this town has no calendars" rather than "I could not see it".

    Both files per zone, deal-bearing first, so where a venue is in both it is
    the board's copy that wins: `zone-<id>.json` is the venues WITH a window,
    `venues-<id>.json` is every other licensed premises.
    """
    out = {}
    for pat in ("venues-*.json", "zone-*.json"):
        for path in sorted(glob.glob(os.path.join(BUNDLES, pat))):
            try:
                doc = json.load(open(path, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows = doc.get("venues", doc) if isinstance(doc, dict) else doc
            if not isinstance(rows, list):
                continue
            for v in rows:
                if isinstance(v, dict) and v.get("lid") and v.get("website"):
                    out[str(v["lid"])] = v["website"]
    return out


def population(args):
    base, sites = load(BASE), load(SITES)
    fallback = bundle_sites()
    lids = []
    if args.lids:
        lids = [x.strip() for x in open(args.lids, encoding="utf-8") if x.strip() and not x.startswith("#")]
    else:
        lids = [lid for lid, v in base.items() if v.get("zone_id") == args.zone]
    out, skipped = [], []
    for lid in lids:
        v, s = base.get(lid), sites.get(lid) or {}
        website = s.get("website") or fallback.get(lid)
        if not v or not website:
            skipped.append(lid)
            continue
        out.append((lid, {"name": v["name"], "address": v.get("address", ""),
                          "website": website, "zone_id": v.get("zone_id")}))
    # Say what was dropped. A silent skip here is indistinguishable from a town
    # that publishes no calendars, and the difference is the whole finding.
    if skipped:
        print(f"skipped {len(skipped)} of {len(lids)} -- no website on file: "
              + ", ".join(skipped[:10]) + (" ..." if len(skipped) > 10 else ""))
    if args.limit:
        out = out[: args.limit]
    return out


def post_rows(rows):
    """Send grounded rows to the Worker's review queue. Needs SUBMIT_API and
    ADMIN_TOKEN from this repo's .env (never another repo's)."""
    env = {}
    p = os.path.join(REPO, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if "=" in line and not line.startswith("#"):
                k, v = line.rstrip("\n").split("=", 1)
                env[k.strip()] = v.strip()
    api, tok = env.get("SUBMIT_API"), env.get("ADMIN_TOKEN")
    if not api or not tok:
        raise RuntimeError("SUBMIT_API and ADMIN_TOKEN must be in happy-hour-finder/.env")
    req = urllib.request.Request(
        api.rstrip("/") + "/admin/events", method="POST",
        data=json.dumps({"events": rows}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Admin-Token": tok})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lids", help="file of licence ids, one per line")
    g.add_argument("--zone", help="every venue with a website in this zone")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--force", action="store_true", help="re-read venues already on file")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--rejects", action="store_true")
    ap.add_argument("--post", action="store_true",
                    help="POST grounded rows to the Worker review queue (status pending)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("! ANTHROPIC_API_KEY is set; it outranks the CLI login. Unset it first.", file=sys.stderr)
        return 1

    today = datetime.date.today().isoformat()
    until = (datetime.date.today() + datetime.timedelta(days=HORIZON)).isoformat()
    reads = load(READS)
    # A calendar rots in a week; an events read older than that is re-read.
    stale = (datetime.date.today() - datetime.timedelta(days=6)).isoformat()
    todo = [(lid, v) for lid, v in population(args)
            if args.force or lid not in reads or "error" in reads[lid]
            or reads[lid].get("read_at", "") < stale]
    print(f"{len(todo)} venue(s) to read, model {MODEL}, {args.workers} at a time, "
          f"window {today}..{until}\n")
    spent, hit, to_post = 0.0, 0, []

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(one, lid, v, today, until) for lid, v in todo]
        for n, fut in enumerate(cf.as_completed(futs), 1):
            lid, rec = fut.result()
            venue = dict(todo)[lid]
            name = venue["name"][:34]
            with _lock:
                reads[lid] = rec
                save(READS, reads)
            spent += rec.get("cost_usd", 0)
            if "error" in rec:
                print(f"[{n}/{len(todo)}] {name:<36} !! {rec['error'][:90]}")
                continue
            kept = rec.get("kept") or []
            hit += 1 if kept else 0
            tag = (f"{rec['kind']:<5} {len(kept)} event(s)" if rec["found"]
                   else f"none  -- {rec['why_not'][:60]}")
            print(f"[{n}/{len(todo)}] {name:<36} {tag}  ${rec['cost_usd']:.2f} {rec['turns']}t")
            if rec["found"]:
                print(f"      {rec['source_url'][:110]}")
            for ev in kept:
                to_post.append({**ev, "lid": lid, "zone_id": venue.get("zone_id"),
                                "source_kind": "image" if rec["kind"] == "image" else "page",
                                "source_url": rec.get("source_url", "")})
                if args.show:
                    when = ev["start"] or "--:--"
                    cov = "" if ev["cover_usd"] is None else f"  ${ev['cover_usd']:g}"
                    print(f"      {ev['date']} {when}  {ev['act']}{cov}")
            if args.rejects:
                for d in rec.get("dropped") or []:
                    print(f"      x {d}")

    print(f"\n{hit} of {len(todo)} venue(s) had events; {len(to_post)} grounded row(s); "
          f"about ${spent:.2f} of subscription-metered model time -> {READS}")
    if args.post and to_post:
        out = post_rows(to_post)
        print(f"posted: {out.get('inserted')} pending, {len(out.get('errors') or [])} refused. "
              f"Review: $SUBMIT_API/admin/events?status=pending")
    elif to_post:
        print("Nothing posted (no --post). Rows are on file only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
