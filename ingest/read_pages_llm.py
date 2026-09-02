#!/usr/bin/env python3
"""Read a happy-hour PAGE the way a person would, instead of matching it.

    python ingest/read_pages_llm.py --limit 4 --show   # one batch, to eyeball
    python ingest/read_pages_llm.py                    # every cached page
    python ingest/read_pages_llm.py --model haiku      # measure a cheaper model
    python ingest/read_pages_llm.py --reverify         # re-check, no model calls

This is the pass ingest/crawl_sites.py caches pages FOR, and it exists because
of what a rule engine cannot do. crawl_sites.py is two thousand lines of regex
and DOM rules, and ingest/extract_prices_llm.py -- the only model in the
pipeline before this one -- reads the QUOTES those rules already produced. A
page the rules threw away is therefore invisible to every model we run.

Sullivan's King of Prussia is the whole argument. Its happy-hour page states
four price bands and twenty-six dishes. The crawler now reads nineteen of them.
Then extract_deals.py asks category_of() -- a hand-typed noun whitelist -- and
keeps TWO: "Beef Wellington Bites", because "bites" is a word somebody typed in,
and "Jumbo Shrimp Cocktail", filed as a COCKTAIL. A shrimp cocktail, published
on the board as a drink. "A5 Wagyu Nigiri" and "Cheesesteak Eggrolls" match no
word in the list and are dropped without a line in any log.

No regex fixes that. Knowing a wagyu nigiri is food and a shrimp cocktail is not
a drink is a judgement, and until this file there was nowhere in this pipeline
that a judgement could be made (Paul, 2026-09-01: "there's no intelligence
running over pages, that's a mistake").

The safety argument is unchanged from extract_prices_llm.py, and is the reason
this is shippable:

  * ITEMS ONLY. This pass never sees, proposes or alters a WINDOW. Days and
    times still come from the deterministic extractor and its meridiem rules,
    so "no meridiem => refused, never guessed" is untouched. The sidecar it
    writes fills exactly the slot data/deals_prices_llm.json fills.
  * EVERY ITEM CARRIES THE SPAN IT CAME FROM, checked against the page here, in
    code, by the same verify() the price pass uses. A model that returns a price
    the venue never published is dropped. The model is a reader, not a source.

It runs on `claude -p`, authenticated with the Claude Max subscription on this
machine -- there is no API key in this repo and none is wanted. That call bills
a large fixed harness on EVERY invocation (28,272 tokens; 9,407 with LEAN_ARGS),
so what this pass costs is driven by the NUMBER OF CALLS, not by the size of the
model. Batch size is the lever. See the measured table in extract_prices_llm.py
before reaching for a cheaper model, and note what it says about haiku: 15% of
the items lost, and recall swinging 55/45/46 across identical runs.
"""

import argparse
import json
import os
import re
import urllib.parse
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_deals import HITS, SITES, one_per_osm, slug  # noqa: E402
from extract_prices_llm import ask_with, verify  # noqa: E402
from validate_pa import CATEGORIES  # noqa: E402

PAGES = os.path.join(REPO, "data", "pages")
OUT = os.path.join(REPO, "data", "deals_pages_llm.json")

# A page, not a handful of quotes. Sullivan's menu is 195 lines and the useful
# part is most of them, so the per-venue budget is far larger than the price
# pass's 2,400 -- and the batch correspondingly smaller. The two multiply, and
# their product is what one call costs.
MAX_PAGE = 7000
BATCH = int(os.environ.get("HHF_PAGE_BATCH", "5"))
MODEL = os.environ.get("HHF_PAGE_MODEL", "sonnet")

PROMPT = """\
You are reading pages that bars and restaurants in Pennsylvania published on
their own websites. Each page below is one venue's happy hour page or menu.

Return every item the page offers ON THE HAPPY HOUR, with the price it states.

What makes this hard, and what you are here for:
- A page often states a price ONCE, as a heading, over a list of dishes that do
  not repeat it. "$25" followed by five dishes prices all five at $25.
- The page names the dish; it does not say what KIND of thing it is. You do.
  A "Jumbo Shrimp Cocktail" is FOOD, not a cocktail. "A5 Wagyu Nigiri" is food.
  An "Espresso Martini" is a cocktail. Read the dish, not the words in it.
- Descriptions sit under dish names. "Seared A5 Wagyu, Sushi Rice, Truffle
  Ponzu" is not an item; it describes the item above it.

Rules:
- Only report a price the page states. Never infer, average or round one.
- `evidence` must be an EXACT substring copied from that page, short, and must
  contain the price. It is checked programmatically; if it is not a literal
  substring the item is discarded. Where the price sits on a heading above the
  item, the evidence may be that heading.
- `price_usd` is a dollar amount. Use `discount_pct` instead when the page
  states a percentage, or says half price / half off (-> 50). Exactly one.
- Ignore "$5 OFF" lines entirely -- a discount is not a price, and this pass has
  no field for one. The rule engine already reads those.
- `label` is the item, named as the venue names it.
- `category` is exactly one of: {categories}
- Skip anything not on the happy hour: the dinner menu, brunch, catering, gift
  cards, event tickets, prices at other locations, and any dish sitting under a
  heading that names a DIFFERENT menu.
- If a page prices nothing, return an empty items list for it. An empty answer
  is a real answer; never manufacture items to fill one.
- Return EVERY item the page prices. Do not choose a representative subset and
  do not stop early -- the board folds long lists itself, so a dropped item is
  simply lost.

Return ONLY a JSON array, no prose and no code fence:
[{{"id": "<page id>", "items": [
  {{"category": "food", "label": "A5 Wagyu Nigiri", "price_usd": 25.0,
    "evidence": "$25"}}
]}}]

PAGES:
{venues}
"""


def cached_pages():
    """[(page_id, venue_slug, url, text)] for every happy-hour page on disk.

    Keyed by the venue SLUG, not by the licence id, because the slug is what the
    sidecar contract uses: build_bundles.py looks a sidecar up by the slug
    extract_deals.py derives from name+address. See the note in
    extract_prices_llm.published() about what reading the id instead cost.
    """
    if not os.path.isdir(PAGES):
        return []
    hits = json.load(open(HITS, encoding="utf-8"))
    sites = json.load(open(SITES, encoding="utf-8"))
    by_lid = {lid: slug(v["osm_name"] or v["name"], v["address"])
              for lid, v in one_per_osm(hits, sites)}
    out = []
    for fn in sorted(os.listdir(PAGES)):
        if not fn.endswith(".json"):
            continue
        page = json.load(open(os.path.join(PAGES, fn), encoding="utf-8"))
        vid = by_lid.get(str(page.get("lid")))
        if not vid:
            continue
        text = "\n".join(page.get("lines") or [])[:MAX_PAGE]
        if len(text) < 40 or not worth_reading(page.get("url", ""), text):
            continue
        out.append((fn[:-5], vid, page.get("url", ""), text))
    return out


# Two prices. One number on a page is a phone number, a year, a street address
# or a single teaser; a MENU states several.
PRICEY_RE = re.compile(r"\$\s?\d")


def worth_reading(url, text):
    """Whether this cached page could hold a menu, before spending a call on it.

    crawl_sites.py caches a page whenever HH_HEADING_RE matches anywhere in it,
    which is the right rule for the cache -- cheap, and a page not kept cannot
    be reconsidered -- and the wrong rule for the model. The words "happy hour"
    appear in the NAV of every restaurant site on the internet, so the first
    King of Prussia run put 47 pages up and 41 of them were a bottle shop's
    homepage, a corporate-events page and the like. The model answered every one
    of them correctly, with nothing, at full price.

    So: the venue's own URL calls it an hour, or the page states at least two
    prices under a happy-hour heading. Both are the page making a claim about
    itself. A page that passes neither has not been judged to be menu-less --
    it is simply not worth a call, and it stays in the cache for a rule that
    knows better later.
    """
    if HH_URL_RE.search(urllib.parse.urlsplit(url).path):
        return True
    return len(PRICEY_RE.findall(text)) >= 2 and HH_TEXT_RE.search(text) is not None


HH_URL_RE = re.compile(r"hour(?!s)", re.I)
HH_TEXT_RE = re.compile(r"happy\s*hour|social hour|power hour|bar bites", re.I)


def reverify(out, todo):
    """Re-run verify() over what is already on file. No model calls.

    A page changes and an item we published stops being something the venue
    says. The sidecar is not evidence of itself.
    """
    by_vid = {}
    for _, vid, _, text in todo:
        by_vid.setdefault(vid, []).append(text)
    dropped = 0
    for vid in list(out):
        pages = by_vid.get(vid) or []
        kept = [it for it in out[vid]
                if any(verify(it, t, menu=True)[0] for t in pages)]
        dropped += len(out[vid]) - len(kept)
        if kept:
            out[vid] = kept
        else:
            del out[vid]
    write(out)
    print(f"{dropped} item(s) no longer verify and were dropped; "
          f"{sum(len(v) for v in out.values())} remain")


def write(out):
    with open(OUT + ".new", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    os.replace(OUT + ".new", OUT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N pages")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--rejects", action="store_true")
    ap.add_argument("--model", default=MODEL, help="sonnet (default), haiku, opus")
    ap.add_argument("--batch", type=int, default=BATCH, help="pages per model call")
    ap.add_argument("--reverify", action="store_true",
                    help="re-check the sidecar against the pages on disk, no model calls")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    todo = cached_pages()
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} cached happy-hour page(s) to read "
          f"[model {args.model}, batch {args.batch}]")

    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    if args.reverify:
        return reverify(out, todo)

    texts = {pid: text for pid, _, _, text in todo}
    owner = {pid: vid for pid, vid, _, _ in todo}
    kept_n, rejects = 0, []
    batches = -(-len(todo) // args.batch)
    for i in range(0, len(todo), args.batch):
        batch = [(pid, text) for pid, _, _, text in todo[i : i + args.batch]]
        try:
            replies = ask_with(batch, PROMPT, args.model,
                               categories=", ".join(sorted(CATEGORIES)))
        except Exception as e:  # noqa: BLE001 -- a failed batch is not a failed run
            print(f"  batch {i // args.batch + 1}: {type(e).__name__}: {e}")
            continue
        for reply in replies:
            pid = reply.get("id")
            if pid not in texts:
                rejects.append(("?", f"reply names a page not in the batch: {pid!r}"))
                continue
            for item in (reply.get("items") or []):
                # menu=True: a menu names its dishes in full and often prints
                # the price with no dollar sign. Same check, menu spelling.
                clean, why = verify(item, texts[pid], menu=True)
                if not clean:
                    rejects.append((pid, f"{why}: {json.dumps(item)[:100]}"))
                    continue
                items = out.setdefault(owner[pid], [])
                if not any(x["label"].lower() == clean["label"].lower() for x in items):
                    items.append(clean)
                    kept_n += 1
        print(f"  batch {i // args.batch + 1}/{batches}: "
              f"{len(batch)} page(s), {kept_n} item(s) kept so far")
        write(out)

    print(f"\n{kept_n} verified item(s) across {len(out)} venue(s) -> {OUT}")
    print(f"{len(rejects)} item(s) refused")
    if args.show:
        for vid, items in sorted(out.items()):
            shown = ", ".join(
                f"{i['label']} "
                + (f"${i['price_usd']:g}" if "price_usd" in i
                   else f"{i['discount_pct']:g}% off")
                for i in items)
            print(f"  {vid[:38]:<40} {shown[:100]}")
    if args.rejects:
        for pid, why in rejects:
            print(f"  REFUSED {pid[:28]:<30} {why}")


if __name__ == "__main__":
    main()
