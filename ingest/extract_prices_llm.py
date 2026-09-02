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

# norm() lives in extract_deals because extract_deals needs it too (it re-checks
# a window span against the page), and it cannot import THIS module -- this one
# already imports it. Re-exported here so the two reader passes keep importing
# it from where they always have.
from extract_deals import HITS, SITES, norm, one_per_osm, slug  # noqa: E402
from validate_pa import BANNED, CATEGORIES  # noqa: E402

BUNDLES = os.path.join(REPO, "web", "data")
OUT = os.path.join(REPO, "data", "deals_prices_llm.json")

# Measured on 40 real venues, 2026-09-01, counting BOTH directions and weighting
# by what each model actually costs. `claude -p` ships its whole agent harness on
# every call -- a nine-token prompt bills 28,272 input tokens -- so the fixed cost
# per call dwarfs the venue text, and the two levers that matter are how much
# harness rides along and how many venues share one ride:
#
#   opus   b8   207,355 in    3,954 out   54 items   $0.7564   <- what ran before
#   opus   b20   39,503 in    9,767 out   56 items   $0.3540
#   sonnet b20   39,703 in   18,481 out   54 items   $0.2660   <- here
#   haiku  b40   19,390 in   27,273 out   46 items   $0.1489
#
# Sonnet at 20 is 2.8x cheaper than the old setting for the SAME item count.
# Haiku is cheaper still and is deliberately NOT taken: it lost 15% of the items
# and its recall swung 55/45/46 across identical runs, so its saving is not one
# that can be relied on. Note also that a smaller model is not automatically
# cheaper here -- haiku spends its input saving back as output, and at batch 40
# opus beat haiku on RAW tokens and on recall at once. Batch size is the lever;
# the model is the smaller adjustment.
#
# Whatever the model, verify() still requires every price to appear literally in
# the venue's own text, so a weaker model cannot put a WRONG price on a card. The
# only thing it can cost is recall, which is the number measured above.
BATCH = int(os.environ.get("HHF_PRICE_BATCH", "20"))   # venues per model call
MAX_QUOTE = 2400     # chars of quote text per venue
# No item cap. The card folds after 3 and holds the rest behind "+N more", so
# the display never needed one; capping here only threw away menu we had read.
MODEL = os.environ.get("HHF_PRICE_MODEL", "sonnet")

# What `claude -p` may leave behind. This pass wants a reader, not an agent: it
# has no use for tools, for this repo's CLAUDE.md, or for the dynamic sections
# of the default system prompt, and each of those is input tokens on EVERY call.
# Dropping them cut a call from 28,272 tokens to 9,407 and did not cost a single
# item -- recall went UP. Kept as a list so a future flag rename fails loudly
# here rather than silently costing 3x.
LEAN_ARGS = [
    "--setting-sources", "",
    "--exclude-dynamic-system-prompt-sections",
    "--system-prompt",
    "You extract published happy-hour prices from text. Answer with JSON only.",
    "--disallowed-tools",
    "Bash", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "WebFetch",
    "WebSearch", "Task", "TodoWrite", "NotebookEdit", "BashOutput", "KillShell",
    "SlashCommand", "ExitPlanMode", "Agent", "Skill", "Artifact", "Monitor",
]

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
- Return EVERY happy-hour item the text prices. Do not choose a
  representative subset and do not stop early -- the board folds long lists
  itself, so a dropped item is simply lost.

Return ONLY a JSON array, no prose and no code fence:
[{{"id": "<venue id>", "items": [
  {{"category": "draft", "label": "drafts", "price_usd": 5.0,
    "evidence": "$5 drafts"}}
]}}]

VENUES:
{venues}
"""


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
                    # The SLUG, not the id. A shipped venue is keyed by its PLCB
                    # licence number; the sidecar this pass writes -- and the
                    # lookup build_bundles does against it -- is keyed by the
                    # slug the extractor derives from name+address. Reading the
                    # id here matched nothing at all, and the pass reported it
                    # as '119 could not be joined back to a crawl hit' and
                    # exited 0, so it read as a thin corpus rather than a bug.
                    out[v.get("slug") or v["id"]] = deal
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
    return ask_with(batch, PROMPT, MODEL,
                    categories=", ".join(sorted(CATEGORIES)))


def ask_with(batch, template, model, **fields):
    """The same call, with the prompt and the model as arguments.

    ingest/read_pages_llm.py reads whole PAGES rather than quotes and needs its
    own prompt, but the transport is identical and has to stay identical: one
    process, LEAN_ARGS, JSON out, a code fence tolerated and nothing else
    salvaged. Two copies of this would drift, and what would drift is the flag
    list whose loss silently costs 3x.
    """
    venues = "\n\n".join(f"--- id: {vid}\n{text}" for vid, text in batch)
    prompt = template.format(venues=venues, **fields)
    # `claude` is a .cmd shim on Windows, which subprocess will not find on its
    # own, and the prompt goes in on stdin rather than argv so a batch is never
    # bounded by the command-line length limit.
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("`claude` is not on PATH -- this pass runs on the CLI, "
                           "not on an API key")
    proc = subprocess.run(
        [exe, "-p", "--model", model, "--output-format", "json"] + LEAN_ARGS,
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


def verify(item, text, menu=False):
    """(clean_item, None) if the venue really published this, else (None, why).

    This is the check that makes the pass safe to ship. The model is a reader,
    not a source: nothing it returns reaches a card unless the price is sitting
    in the venue's own sentence, spelled the way the item claims.
    """
    ev = item.get("evidence") or ""
    # Three characters was right when every quote was a sentence, and wrong the
    # moment a whole PAGE became readable: a price BAND states itself as '$8' on
    # its own line and owns the four dishes under it. Tommy's Tavern lost all
    # eight of its real happy-hour items to this -- refused as "no evidence"
    # while the evidence was sitting in the page, spelled exactly as claimed.
    # The floor still bites on anything that is not a price, so an empty or
    # junk span is refused as before.
    bare_price = isinstance(ev, str) and re.fullmatch(r"\$\s?\d{1,3}(\.\d\d)?", ev.strip())
    if not isinstance(ev, str) or (len(ev) < 3 and not bare_price):
        return None, "no evidence"
    if norm(ev) not in norm(text):
        return None, "evidence not in the quote"
    if item.get("category") not in CATEGORIES:
        return None, f"category {item.get('category')!r}"
    label = (item.get("label") or "").strip()
    # A menu names its dishes in full ('Malbec Burger with French fries or
    # house salad'); a sentence on a web page yields a short label. 30 is right
    # for the latter and rejected every real item on the former.
    if not 1 <= len(label) <= (60 if menu else 30):
        return None, "label length"
    for pat in BANNED:
        if re.search(pat, label, re.I):
            return None, f"unlawful claim /{pat}/"

    price, pct = item.get("price_usd"), item.get("discount_pct")
    if (price is None) == (pct is None):
        return None, "needs exactly one of price_usd / discount_pct"

    # '$ 8' and '$8' are the same claim. A themed menu that puts the price in
    # its own block routinely emits the spaced form, and the digits-in-the-text
    # check below rejected every item on such a page -- a real price, published
    # by the venue, refused for a space. Only the gap after the sign is closed;
    # nothing else about the evidence is rewritten.
    low = re.sub(r"\$\s+(?=\d)", "$", norm(ev))
    if price is not None:
        price = float(price)
        if not 0 < price <= 99:
            return None, f"implausible price {price}"
        # The digits have to be in the sentence. '$5', '$5.00' and '5 dollars'
        # are the three ways these pages write it; a price the text spells only
        # in words ('five dollars') is left behind rather than accepted on the
        # model's say-so, because there is nothing here to check it against.
        forms = {f"${price:g}", f"${price:.2f}", f"{price:g} dollar"}
        found = any(f in low for f in forms)
        # A PRINTED MENU omits the dollar sign -- the whole sheet is a price
        # list, so it writes 'COCONUT MOJITO 9' and 'SALMON TARTARE ... 15'.
        # Requiring the sign there rejected all eighteen of Malbec's real
        # items. The rule that matters is unchanged and still enforced: the
        # number has to be sitting in the venue's own text. It is only the
        # sign that becomes optional, and only for a menu -- and the digits
        # must stand as a whole token, so 5 is never read out of '15'.
        if not found and menu:
            found = re.search(rf"(?<![\d.]){price:g}(?![\d.])", low) is not None
        if not found:
            return None, f"price {price:g} not written in the evidence"
        # The digits being present does not make them a PRICE. Sullivan's says
        # '$5 Off Select Martinis' and the model returned a $5 martini; every
        # check above passes, because both the '$5' and the 'martinis' really
        # are in the venue's own text. '$N off' is a DISCOUNT, and this pipeline
        # has no field for a dollars-off one (see OFF_RE in extract_deals.py),
        # so an amount that the evidence only ever writes as 'off' is refused
        # rather than published as the thing's price. If some occurrence of the
        # number is a plain price, that one still counts.
        hits = [m for f in forms for m in re.finditer(re.escape(f), low)]
        if hits and all(re.match(r"\s*off\b", low[m.end():]) for m in hits):
            return None, f"{price:g} is written only as an amount OFF, not a price"
        clean = {"category": item["category"], "label": label, "price_usd": price}
    else:
        pct = float(pct)
        if not 0 < pct < 100:
            return None, f"implausible discount {pct}"
        if not (f"{pct:g}%" in low or "half" in low):
            return None, f"discount {pct:g} not written in the evidence"
        clean = {"category": item["category"], "label": label, "discount_pct": pct}
    return clean, None


def evidence_candidates(item, text):
    """The lines of a venue's quotes that could be the evidence for one item.

    verify() judges an item against its `evidence` -- the venue's own sentence.
    The sidecar does NOT store evidence (a card has no use for it), so an item
    already on file cannot simply be re-judged: there is nothing to judge. So
    reverify reconstructs the candidates and lets verify() rule on each. A line
    qualifies if it carries the label and the number; if none does, the item is
    dropped, which is the same answer verify() would have given.
    """
    label = (item.get("label") or "").strip()
    if not label:
        return []
    price, pct = item.get("price_usd"), item.get("discount_pct")
    num = f"{float(price):g}" if price is not None else f"{float(pct):g}"
    out = []
    for line in text.splitlines():
        low = norm(line)
        if norm(label) in low and num in re.sub(r"\.00\b", "", low):
            out.append(line.strip())
    return out


def reverify(args):
    """Re-run verify() over the sidecar we already wrote, with no model calls.

    verify() runs at WRITE time, so a fix to it does not reach items already in
    the sidecar -- build_bundles.py trusts the file precisely because every item
    in it was checked once. That is how three `$X off` labels stayed on the live
    board after the guard that refuses them had shipped: the sidecar predated
    the guard. This makes verify() authoritative over the whole file rather than
    only over the moment an item was first read.
    """
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    quotes = quotes_by_venue()
    # This reads crawl_hits.json, which crawl_sites.py rewrites INCREMENTALLY
    # as it runs. Re-verifying against a half-written hits file drops every
    # item whose venue has not been recrawled yet, so the previous file is
    # always kept alongside.
    with open(OUT + ".bak", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(f"previous sidecar kept at {OUT}.bak")
    kept, dropped, unchecked, orphan = {}, [], [], 0
    for vid, items in sorted(out.items()):
        text = quotes.get(vid)
        if text is None:
            # No quotes to check against any more. Keeping it would be trusting
            # a check we cannot repeat, so it goes.
            orphan += 1
            dropped.append((vid, "no quotes to re-read"))
            continue
        good = []
        for item in items:
            cands = evidence_candidates(item, text)
            if not cands:
                # Nothing to judge. The item passed a real verify() once, and a
                # reconstruction that finds no candidate line is a failure of the
                # reconstruction, not a verdict on the item -- '50% off' is
                # written 'half price' and carries no 50 at all. Dropping here
                # would delete good published data on an artifact, so it stays
                # and is counted separately.
                unchecked.append((vid, json.dumps(item)[:100]))
                good.append(item)
                continue
            clean, why = None, "no candidate line passed"
            for ev in cands:
                clean, why = verify(dict(item, evidence=ev), text)
                if clean:
                    break
            if clean:
                good.append(clean)
            else:
                dropped.append((vid, f"{why}: {json.dumps(item)[:100]}"))
        if good:
            kept[vid] = good
    n_in = sum(len(v) for v in out.values())
    n_out = sum(len(v) for v in kept.values())
    print(f"re-verified {n_in} item(s) across {len(out)} venue(s): "
          f"{n_out} kept, {n_in - n_out} dropped"
          + (f" ({orphan} venue(s) no longer have quotes)" if orphan else ""))
    print(f"{len(unchecked)} item(s) could not be re-checked and were kept "
          f"(no line in the quotes carries both the label and the number)")
    for vid, why in dropped:
        print(f"  dropped {vid[:40]:<42} {why}")
    with open(OUT + ".new", "w", encoding="utf-8") as fh:
        json.dump(kept, fh, indent=1, sort_keys=True)
    os.replace(OUT + ".new", OUT)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N venues")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--rejects", action="store_true")
    ap.add_argument("--reverify", action="store_true",
                    help="re-check the items already in the sidecar against the "
                         "venue's current quotes and drop the ones that no longer "
                         "pass. No model calls.")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.reverify:
        return reverify(args)
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
            for item in (reply.get("items") or []):
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
