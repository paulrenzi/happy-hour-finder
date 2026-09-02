#!/usr/bin/env python3
"""Cards over the venues that ACTUALLY publish a happy hour -- the 90% number.

    python ingest/report_coverage.py phoenixville
    python ingest/report_coverage.py phoenixville --candidates   # the unconfirmed too

The funnel (report_funnel.py) divides cards by quotes, and both halves are
things WE fetched: a venue we never reached is invisible to it, which is how a
Phoenixville run reported "correct refusals" over five published happy hours.
This divides by the town's ground truth instead -- data/ground_truth/<zone>.json,
a list of venues a person (or a card) has CONFIRMED publish a happy hour, each
with the URL that states it. The number Paul asked for is cards / that list,
and the bar is 90%.

A row is confirmed when it carries `confirmed: true` and the URL. A row that
only came from a search (reach_llm.py town) is a CANDIDATE and is not in the
denominator until somebody looks: a search result is not a published happy
hour. Reads what is on disk; fetches nothing.
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUND_DIR = os.path.join(REPO, "data", "ground_truth")
BOARD = os.path.join(REPO, "web", "data", "board-by-lid.json")
BAR = 90


def coverage(rows, board):
    """(cards, confirmed_rows, misses) -- misses are confirmed rows with no card."""
    confirmed = [r for r in rows if r.get("confirmed") and r.get("lid")]
    misses = [r for r in confirmed if str(r["lid"]) not in board]
    return len(confirmed) - len(misses), confirmed, misses


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zone")
    ap.add_argument("--candidates", action="store_true",
                    help="list the unconfirmed rows a search seeded")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    path = os.path.join(GROUND_DIR, f"{a.zone}.json")
    if not os.path.exists(path):
        sys.exit(f"no ground truth for {a.zone}: build {path} first "
                 "(reach_llm.py town seeds it; a person confirms each row)")
    doc = json.load(open(path, encoding="utf-8"))
    board = json.load(open(BOARD, encoding="utf-8")) if os.path.exists(BOARD) else {}
    cards, confirmed, misses = coverage(doc.get("rows", []), board)
    cands = [r for r in doc.get("rows", []) if not r.get("confirmed")]

    if not confirmed:
        print(f"{a.zone}: 0 confirmed rows -- no denominator, no percentage")
    else:
        pct = 100.0 * cards / len(confirmed)
        verdict = "at the bar" if pct >= BAR else f"below the {BAR}% bar"
        print(f"{a.zone}: {cards} card(s) over {len(confirmed)} confirmed "
              f"happy hour(s) = {pct:.0f}%  ({verdict})")
    for r in misses:
        print(f"  MISS  {r['lid']:<8} {r.get('name', '')[:36]:<38} {r.get('url', '')}")
    if cands:
        print(f"  {len(cands)} candidate(s) not yet confirmed, not counted"
              + ("" if a.candidates else " (--candidates to list)"))
        if a.candidates:
            for r in cands:
                on = "card" if str(r.get("lid")) in board else "no card"
                print(f"    ?   {str(r.get('lid') or '-'):<8} {r.get('name', '')[:36]:<38} "
                      f"{on:<8} {r.get('website', '')}")
    for u in doc.get("unmatched") or []:
        print(f"  NOT HELD       {u.get('name', '')[:36]:<38} {u.get('address', '')[:40]}")


if __name__ == "__main__":
    main()
