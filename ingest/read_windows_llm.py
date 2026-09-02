#!/usr/bin/env python3
"""Read the WINDOW off a page, as a verbatim span the deterministic parser converts.

    python ingest/read_windows_llm.py --show --rejects   # every eligible page
    python ingest/read_windows_llm.py --lids run.lids    # one scoped town run
    python ingest/read_windows_llm.py --reverify         # re-check, no model calls

Paul's call, 2026-09-02, on the decision the previous handoff was blocked on:
the page reader MAY propose a window. This file is the shape that was approved,
and every part of that shape is load-bearing:

  * the model returns a VERBATIM SPAN and nothing else. It states no time, no
    day, no start and no end. There is no field here for one.
  * the span is checked against the venue's own cached page IN CODE, here, by
    the same norm()/substring test the item pass uses -- and again in
    extract_deals.py before a window built from it reaches a card, so the
    sidecar is never evidence of itself.
  * the span is converted by windows_from() -- THE EXISTING DETERMINISTIC
    PARSER, unmodified. So "no meridiem => refused, never guessed", the MEAL
    guard, the ONE_OFF date guard, the clause splitter and the PA validators
    all still stand between a page and a card. A span the parser refuses
    produces no window, and that refusal is the same refusal as before.

That is a reader proposing EVIDENCE, not a source stating a FACT -- the same
distinction the item pass has shipped on since 2026-09-01.

WHY IT EXISTS. extract_deals.py corpus-wide: 366 venues had quotes, 208 kept,
and 154 stated no schedule -- larger than every other hole class combined. The
seven KoP-adjacent towns were then run end to end; sonnet read 138 verified
items across 12 venues with 0 refused, and the board gained ONE card, because
a venue with items and no window gets no card. The windows were in the pages we
had already fetched: Blue Bell Inn 4:30-6:30 PM, il Granaio 4-6:30, Autograph
Brasserie 7-9:30, Bistro on Bridge to 6:00, StoneRose 6pm. Three inside PDFs.
A rule engine decided what a schedule looks like; these venues did not spell it
that way.

ELIGIBILITY IS THE 154, NOT THE CORPUS. A venue that already has a window is
never sent -- it costs a call to re-learn what we hold, and it puts the model
near a card that is already right. Only a venue whose quotes produced NO window
is eligible, which is the hole class this pass was authorised for.
"""

import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_deals import HITS, SITES, one_per_osm, windows_from  # noqa: E402
from extract_prices_llm import ask_with, norm  # noqa: E402

PAGES = os.path.join(REPO, "data", "pages")
OUT = os.path.join(REPO, "data", "windows_pages_llm.json")

# A window sentence is short and there are few of them, so a page can be read
# at the same budget as the item pass and the batch can be larger.
MAX_PAGE = 7000
BATCH = int(os.environ.get("HHF_WINDOW_BATCH", "6"))
MODEL = os.environ.get("HHF_WINDOW_MODEL", "sonnet")

# The span has to be short enough that windows_from() can still tell which days
# go with which times -- that parser's own fallbacks are bounded at 200 for
# exactly this reason, and a span longer than that would arrive already
# ambiguous. It is also the difference between quoting a sentence and quoting
# a page.
MAX_SPAN = 200

PROMPT = """\
You are reading pages that bars and restaurants in Pennsylvania published on
their own websites. Each page below is one venue's happy hour page or menu.

Find where the page states WHEN its happy hour runs, and copy that text out
verbatim. You are not being asked what the hours ARE. You are being asked to
point at the sentence that says so.

Rules:
- `evidence` must be an EXACT substring copied from that page, character for
  character, at most {max_span} characters. It is checked programmatically
  against the page; if it is not a literal substring it is discarded.
- Copy the SMALLEST span that carries both the days and the times. If the days
  and the times sit on separate lines, include both lines and what lies between
  them, and nothing else.
- If the page states days but no clock time, or a clock time but no days,
  return the span anyway -- something downstream knows what to do with each.
- Do NOT convert, normalise, expand or tidy anything. Do not write "4:00 PM"
  where the page wrote "4pm". Do not write "Monday-Friday" where the page wrote
  "M-F". A single changed character discards the answer.
- Do NOT return a span for anything that is not the standing happy hour: lunch
  and brunch hours, kitchen or bar OPENING hours, a dated event, a holiday
  party, a private-events page, or hours at another location.
- Some pages state more than one happy hour ("Mon-Fri 4-6 and late night
  Fri-Sat 10-12"). Return one span for each, in `evidence_extra`.
- If the page does not state when its happy hour runs, return an empty
  `evidence`. An empty answer is a real answer, and it is the right one far
  more often than it looks. Never point at a sentence that is nearly right.

Return ONLY a JSON array, no prose and no code fence:
[{{"id": "<page id>", "evidence": "Happy Hour Monday - Friday 4-6pm",
   "evidence_extra": []}}]

PAGES:
{venues}
"""


def needy_lids(only=None):
    """The lids of venues that HAVE quotes and whose quotes state no schedule.

    This is the 154, computed the same way extract_deals.py counts them -- by
    running the real parser over the real quotes rather than by reading a
    number out of a report. A venue whose window we already hold is not here,
    and is never sent to the model.
    """
    hits = json.load(open(HITS, encoding="utf-8"))
    sites = json.load(open(SITES, encoding="utf-8"))
    out = set()
    for lid, v in one_per_osm(hits, sites):
        # A scoped rendered-artifact audit may have found its first readable
        # text in a JavaScript widget.  It has no regex quote yet, which used
        # to make it ineligible for the very reader that can point at its
        # verbatim window.  The scope is the safety boundary: it is supplied
        # by the audited LIDs, not a corpus-wide invitation to guess.
        if ((v["hits"] or (only and str(lid) in only))
                and not any(windows_from(h["quote"]) for h in v["hits"])):
            out.add(str(lid))
    return out


def cached_pages(only=None):
    """[(page_id, lid, url, text)] for every cached page of a window-needy venue.

    Keyed by LID, not by the venue slug the item sidecar uses, because the
    consumer is different: extract_deals.py reads this one, and at the point it
    needs a window it is iterating lids -- it has not yet decided which venue
    holds the bare slug when two collide.
    """
    if not os.path.isdir(PAGES):
        return []
    needy = needy_lids(only)
    out = []
    for fn in sorted(os.listdir(PAGES)):
        if not fn.endswith(".json"):
            continue
        page = json.load(open(os.path.join(PAGES, fn), encoding="utf-8"))
        lid = str(page.get("lid"))
        if lid not in needy or (only and lid not in only):
            continue
        text = "\n".join(page.get("lines") or [])[:MAX_PAGE]
        if len(text) < 40 or not TIME_ISH_RE.search(text):
            continue
        out.append((fn[:-5], lid, page.get("url", ""), text))
    return out


# A page with no clock on it anywhere cannot be hiding a window, and a call
# spent on it buys a correct empty answer at full price. This is the window
# pass's equivalent of worth_reading() in read_pages_llm.py, and it is the
# cheapest filter there is: the page must write a time.
TIME_ISH_RE = re.compile(r"\b\d{1,2}(:\d\d)?\s*(?:[ap]\.?m\.?)\b|\b\d{1,2}\s*[-–]\s*\d{1,2}\s*[ap]\.?m\.?",
                         re.I)


def check(span, text):
    """(span, None) when the venue really wrote this, else (None, why).

    The whole safety argument for this pass sits in these ten lines and in
    windows_from() downstream. Nothing here reads a time; this only decides
    whether the words are the venue's.
    """
    if not isinstance(span, str):
        return None, "no evidence"
    span = span.strip()
    if len(span) < 4:
        return None, "no evidence"
    if len(span) > MAX_SPAN:
        return None, f"span too long ({len(span)} chars)"
    if norm(span) not in norm(text):
        return None, "evidence not in the page"
    if not windows_from(span):
        # Not a rejection of the model -- the deterministic parser looked at
        # this sentence and declined to read a window out of it, which is the
        # same answer it would have given the crawler. Recording it as a reject
        # is how a refused meridiem stays VISIBLE instead of becoming silence.
        return None, "parser reads no window from the span"
    return span, None


def reverify(out, todo):
    """Re-check every span on file against the page on disk. No model calls."""
    by_lid = {}
    for _, lid, _, text in todo:
        by_lid.setdefault(lid, []).append(text)
    dropped = 0
    for lid in list(out):
        pages = by_lid.get(lid) or []
        kept = [s for s in out[lid]["spans"]
                if any(check(s, t)[0] for t in pages)]
        dropped += len(out[lid]["spans"]) - len(kept)
        if kept:
            out[lid]["spans"] = kept
        else:
            del out[lid]
    write(out)
    print(f"{dropped} span(s) no longer verify and were dropped; "
          f"{sum(len(v['spans']) for v in out.values())} remain")


def write(out):
    with open(OUT + ".new", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    os.replace(OUT + ".new", OUT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N pages")
    ap.add_argument("--lids", help="file of licence ids, one per line (a scoped run)")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--rejects", action="store_true")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--reverify", action="store_true",
                    help="re-check the sidecar against the pages on disk, no model calls")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    only = None
    if args.lids:
        only = {l.strip() for l in open(args.lids, encoding="utf-8") if l.strip()}
    todo = cached_pages(only)
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} cached page(s) of window-needy venue(s) to read "
          f"[model {args.model}, batch {args.batch}]")

    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    if args.reverify:
        return reverify(out, todo)

    texts = {pid: text for pid, _, _, text in todo}
    owner = {pid: lid for pid, lid, _, _ in todo}
    urls = {pid: url for pid, _, url, _ in todo}
    kept_n, rejects = 0, []
    batches = -(-len(todo) // args.batch) if todo else 0
    for i in range(0, len(todo), args.batch):
        batch = [(pid, text) for pid, _, _, text in todo[i : i + args.batch]]
        try:
            replies = ask_with(batch, PROMPT, args.model, max_span=MAX_SPAN)
        except Exception as e:  # noqa: BLE001 -- a failed batch is not a failed run
            print(f"  batch {i // args.batch + 1}: {type(e).__name__}: {e}")
            continue
        for reply in replies:
            pid = reply.get("id")
            if pid not in texts:
                rejects.append(("?", f"reply names a page not in the batch: {pid!r}"))
                continue
            spans = [reply.get("evidence")] + list(reply.get("evidence_extra") or [])
            for span in spans:
                if span in (None, ""):
                    continue
                clean, why = check(span, texts[pid])
                if not clean:
                    rejects.append((pid, f"{why}: {json.dumps(span)[:110]}"))
                    continue
                rec = out.setdefault(owner[pid], {"url": urls[pid], "spans": []})
                if clean not in rec["spans"]:
                    rec["spans"].append(clean)
                    kept_n += 1
        print(f"  batch {i // args.batch + 1}/{batches}: "
              f"{len(batch)} page(s), {kept_n} span(s) kept so far")
        write(out)

    print(f"\n{kept_n} verified span(s) across {len(out)} venue(s) -> {OUT}")
    print(f"{len(rejects)} span(s) refused")
    if args.show:
        for lid, rec in sorted(out.items()):
            for span in rec["spans"]:
                ws = windows_from(span)
                days = ",".join(str(w["dow"]) for w in ws)
                print(f"  {lid:<10} dow {days:<16} {ws[0]['start']}-{ws[0]['end']}  "
                      f"{span[:60]!r}")
    if args.rejects:
        for pid, why in rejects:
            print(f"  REFUSED {pid[:28]:<30} {why}")


if __name__ == "__main__":
    main()
