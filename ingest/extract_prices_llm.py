#!/usr/bin/env python3
"""Read prices off the quotes a deal was already built from -- and nothing else.

    python ingest/extract_prices_llm.py --limit 8    # one batch, to eyeball
    python ingest/extract_prices_llm.py              # every venue missing prices
    python ingest/extract_prices_llm.py --show       # print what was kept

Most cards read "Window published without prices." because ingest/extract_deals.py
reads items with a regex (`$5 drafts`) and a bar that writes "Drafts are five
dollars during happy hour" publishes a price that regex cannot see. This pass
puts a language model over the SAME quotes and writes data/deals_prices_llm.json,
a sidecar of items keyed by venue id.

Two rules bound it, and they are the whole design:

  * PRICES ONLY. It never sees, proposes, or alters a window. The days and times
    on every card still come from the deterministic extractor and its meridiem
    rules, so the "no meridiem => refused, never guessed" guarantee is untouched.
    A venue with no validated window is not in this pass's input at all.
  * EVERY ITEM CARRIES THE SPAN IT CAME FROM, and that span is checked against
    the quote here, in code. A model that returns a price the venue never
    published fails `verify()` and is dropped -- so the sidecar cannot contain a
    number that is not literally in the venue's own text.

It runs on `claude -p`, which is authenticated with the Claude subscription
already on this machine, rather than an API key this repo does not have. That
call carries a large fixed system prompt before it reads anything of ours, so
venues go up in batches -- a per-venue call would be ~100x the cost for the same
answer.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_deals import HITS, SITES, one_per_osm, slug  # noqa: E402
from validate_pa import BANNED, CATEGORIES  # noqa: E402

BUNDLES = os.path.join(REPO, "web", "data")
OUT = os.path.join(REPO, "data", "deals_prices_llm.json")

BATCH = 8            # venues per model call
MAX_QUOTE = 2400     # chars of quote text per venue
MAX_ITEMS = 6        # what the card can show without becoming a menu
MODEL = "opus"

PROMPT = """\
You are reading text that bars in Pennsylvania published on their own websites,
and pulling out the happy-hour PRICES.

For each venue below, return the priced items its text actually states. Do NOT
return days, times, or anything about when the happy hour runs -- that is
already known and is not your job.

Rules:
- Only report a price the text states. Never infer, average, or round one.
- `evidence` must be an EXACT substring copied from that venue's text, short,
  and must contain the price. It is checked programmatically; if it is not a
  literal substring the item is discarded.
- `price_usd` is a dollar amount off the text ("$5", "5 dollars", "five
  dollars" -> 5.0). Use `discount_pct` instead when the text states a
  percentage or says half price/half off (-> 50). Exactly one of the two.
- `label` is the thing being sold, 1-3 words, as the venue names it
  ("drafts", "house wine", "wings"). Not a sentence.
- `category` is exactly one of: {categories}
- Skip anything that is not a happy-hour price: regular menu prices, gift
  cards, event tickets, catering, merchandise, prices at other locations.
- If a venue's text states no price, return an empty items list for it.
- At most {max_items} items per venue, the cheapest and most representative.

Return ONLY a JSON array, no prose and no code fence:
[{{"id": "<venue id>", "items": [
  {{"category": "draft", "label": "drafts", "price_usd": 5.0,
    "evidence": "$5 drafts"}}
]}}]

VENUES:
{venues}
"""


def norm(text):
    """Whitespace-insensitive form, so an evidence check is not defeated by the
    line breaks the crawler joined with ' / '."""
    return re.sub(r"\s+", " ", text).strip().lower()


def published():
    """{venue_id: deal} for machine-extracted deals that have no prices yet.

    Hand-verified seed venues are skipped outright: a person read those pages,
    and this pass is not allowed to add to their reading.
    """
    out = {}
    for fn in sorted(os.listdir(BUNDLES)):
        if not fn.startswith("zone-"):
            continue
        for v in json.load(open(os.path.join(BUNDLES, fn), encoding="utf-8"))["venues"]:
            for deal in v["deals"]:
                if deal.get("verified_by") == "auto_extract" and not deal.get("items"):
                    out[v["id"]] = deal
    return out


def quotes_by_venue():
    """{venue_id: joined quote text} -- the same text extract_deals.py read.

    The venue id is derived from name+address exactly as the extractor derives
    it, so this joins to the published corpus without a second id scheme.
    """
    hits = json.load(open(HITS, encoding="utf-8"))
    sites = json.load(open(SITES, encoding="utf-8"))
    out = {}
    for lid, v in one_per_osm(hits, sites):
        if not v["hits"]:
            continue
        vid = slug(v["osm_name"] or v["name"], v["address"])
        text = "\n".join(h["quote"] for h in v["hits"])
        out.setdefault(vid, text[:MAX_QUOTE])
    return out


def ask(batch):
    """One `claude -p` call over a list of (id, text). Returns parsed JSON."""
    venues = "\n\n".join(f"--- id: {vid}\n{text}" for vid, text in batch)
    prompt = PROMPT.format(categories=", ".join(sorted(CATEGORIES)),
                           max_items=MAX_ITEMS, venues=venues)
    # `claude` is a .cmd shim on Windows, which subprocess will not find on its
    # own, and the prompt goes in on stdin rather than argv so a batch is never
    # bounded by the command-line length limit.
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("`claude` is not on PATH -- this pass runs on the CLI, "
                           "not on an API key")
    proc = subprocess.run(
        [exe, "-p", "--model", MODEL, "--output-format", "json"],
        input=prompt, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p exited {proc.returncode}: {proc.stderr[:300]}")
    envelope = json.loads(proc.stdout)
    body = envelope.get("result") or ""
    # A code fence is the one wrapper worth tolerating; anything else that is
    # not JSON is a failed batch, not something to salvage by guessing.
    m = re.search(r"\[.*\]", body, re.S)
    if not m:
        raise ValueError(f"no JSON array in reply: {body[:200]}")
    return json.loads(m.group(0))


def verify(item, text):
    """(clean_item, None) if the venue really published this, else (None, why).

    This is the check that makes the pass safe to ship. The model is a reader,
    not a source: nothing it returns reaches a card unless the price is sitting
    in the venue's own sentence, spelled the way the item claims.
    """
    ev = item.get("evidence") or ""
    if not isinstance(ev, str) or len(ev) < 3:
        return None, "no evidence"
    if norm(ev) not in norm(text):
        return None, "evidence not in the quote"
    if item.get("category") not in CATEGORIES:
        return None, f"category {item.get('category')!r}"
    label = (item.get("label") or "").strip()
    if not 1 <= len(label) <= 30:
        return None, "label length"
    for pat in BANNED:
        if re.search(pat, label, re.I):
            return None, f"unlawful claim /{pat}/"

    price, pct = item.get("price_usd"), item.get("discount_pct")
    if (price is None) == (pct is None):
        return None, "needs exactly one of price_usd / discount_pct"

    low = norm(ev)
    if price is not None:
        price = float(price)
        if not 0 < price <= 99:
            return None, f"implausible price {price}"
        # The digits have to be in the sentence. '$5', '$5.00' and '5 dollars'
        # are the three ways these pages write it; a price the text spells only
        # in words ('five dollars') is left behind rather than accepted on the
        # model's say-so, because there is nothing here to check it against.
        forms = {f"${price:g}", f"${price:.2f}", f"{price:g} dollar"}
        if not any(f in low for f in forms):
            return None, f"price {price:g} not written in the evidence"
        clean = {"category": item["category"], "label": label, "price_usd": price}
    else:
        pct = float(pct)
        if not 0 < pct < 100:
            return None, f"implausible discount {pct}"
        if not (f"{pct:g}%" in low or "half" in low):
            return None, f"discount {pct:g} not written in the evidence"
        clean = {"category": item["category"], "label": label, "discount_pct": pct}
    return clean, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N venues")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--rejects", action="store_true")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    need, quotes = published(), quotes_by_venue()
    todo = [(vid, quotes[vid]) for vid in sorted(need) if vid in quotes]
    missing = len(need) - len(todo)
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(need)} published venues have a window but no prices; "
          f"{len(todo)} have quotes to re-read"
          + (f" ({missing} could not be joined back to a crawl hit)" if missing else ""))

    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    kept_n, rejects = 0, []
    for i in range(0, len(todo), BATCH):
        batch = todo[i : i + BATCH]
        try:
            replies = ask(batch)
        except Exception as e:  # noqa: BLE001 -- a failed batch is not a failed run
            print(f"  batch {i // BATCH + 1}: {type(e).__name__}: {e}")
            continue
        texts = dict(batch)
        for reply in replies:
            vid = reply.get("id")
            if vid not in texts:
                rejects.append(("?", f"reply names a venue not in the batch: {vid!r}"))
                continue
            kept = []
            for item in (reply.get("items") or [])[:MAX_ITEMS]:
                clean, why = verify(item, texts[vid])
                if clean:
                    kept.append(clean)
                else:
                    rejects.append((vid, f"{why}: {json.dumps(item)[:100]}"))
            if kept:
                out[vid] = kept
                kept_n += len(kept)
        print(f"  batch {i // BATCH + 1}/{-(-len(todo) // BATCH)}: "
              f"{len(batch)} venues, {kept_n} item(s) kept so far")
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)

    print(f"\n{kept_n} verified item(s) across {len(out)} venue(s) -> {OUT}")
    print(f"{len(rejects)} item(s) refused")
    if args.show:
        for vid, items in sorted(out.items()):
            shown = ", ".join(
                f"{i['label']} "
                + (f"${i['price_usd']:g}" if "price_usd" in i else f"{i['discount_pct']:g}% off")
                for i in items
            )
            print(f"  {vid[:40]:<42} {shown[:80]}")
    if args.rejects:
        for vid, why in rejects:
            print(f"  REFUSED {vid[:30]:<32} {why}")


if __name__ == "__main__":
    main()
