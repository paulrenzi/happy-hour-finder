#!/usr/bin/env python3
"""Read the happy hour off a submitted menu photo (SPEC sections 3, 8, 9).

Pulls pending photo submissions from the Worker, puts a vision model over each
one, checks what comes back, and posts the proposal back onto the row. It never
publishes anything -- a proposal only reaches the site after a person approves
it in ingest/review_photos.py and the bundles are rebuilt.

This runs on the `claude` CLI against Paul's Max subscription, exactly like
ingest/extract_prices_llm.py. There is no API key anywhere in this repo. The
photo is written to disk and the CLI is told to read it with its Read tool,
because that is how you hand an image to `claude -p`.

Three checks stand between the model and the board, in this order:

1. Grounding. The model returns a verbatim `transcript` of the menu text along
   with the deals, and every item carries the `quote` it was read from. An item
   whose quote is not actually in the transcript is dropped. Same rule as
   extract_prices_llm.py: the model is a reader, not an author, and a price
   nobody printed is the failure that matters most here.
2. The PA legal validators (ingest/validate_pa.py). Unchanged from every other
   lane -- a photo does not get a softer standard than a website.
3. A person. Always.

    python ingest/extract_photo_deals.py            # every pending submission
    python ingest/extract_photo_deals.py --limit 5
    python ingest/extract_photo_deals.py --dry-run  # extract, print, post nothing

Needs happy-hour-finder/.env (this repo's own -- never another repo's):
    SUBMIT_API=https://hhf-submit.<subdomain>.workers.dev
    ADMIN_TOKEN=<the wrangler secret of the same name>
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validate_pa import CATEGORIES, validate_deal, validate_food_combo_count  # noqa: E402

MODEL = os.environ.get("HHF_VISION_MODEL", "opus")
# Gitignored. The CLI reads the image off disk, and review_photos.py reuses the
# same cache so a reviewer is not re-downloading what was just fetched.
PHOTO_DIR = os.path.join(REPO, "data", "photos")

PROMPT = """Read the image at this path with your Read tool: {path}

You are transcribing a happy hour menu for a listings site that publishes only
what the venue itself put in writing.

You are a reader, not an author. Every price, time and item you report must be
printed on the menu in the photo. If the menu says "select drafts", say select
drafts, not "all drafts". If a price is smudged or cut off, leave it out. If the
days are not printed, return no windows rather than guessing the usual ones. An
omission costs us one deal; an invention costs us the reader's trust, and the
reader is standing in a bar holding their phone.

Transcribe the whole menu into `transcript` first, verbatim. Then read the deals
back out of that transcript, and set each item's `quote` to the exact substring
you took it from. A quote that is not character-for-character inside the
transcript is discarded automatically, so do not paraphrase it.

Times are 24-hour "HH:MM". Days are 1=Monday through 7=Sunday. Midnight at the
end of a window is "24:00".

Pennsylvania caps happy hour at 4 hours a day and 24 a week, and forbids
all-you-can-drink, two-for-one, bottomless and free-drink offers. If the menu
advertises one of those, transcribe it as printed and let the validators handle
it -- do not clean it up.

Reply with ONE JSON object and nothing else. No prose, no code fence.

{{
  "is_menu": true or false -- true only if this shows a printed or written menu,
             board or sign listing food or drink specials,
  "rejection_reason": "if is_menu is false, one sentence on what it actually
             shows; otherwise an empty string",
  "concerns": ["anything a human reviewer must see before this is published:
             identifiable people, a receipt or card number, anything unrelated
             to a menu. Empty list if none."],
  "venue_name_on_menu": "the venue name printed on the menu, verbatim, or \\"\\"",
  "transcript": "every word visible on the menu, verbatim, in reading order",
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
          "quote": "the exact substring of transcript this came from"
        }}
      ],
      "fine_print": "any conditions printed on the menu, or \\"\\""
    }}
  ]
}}
"""


def env_file():
    """This repo's own .env only. Never shopify-analytics/.env."""
    path = os.path.join(REPO, ".env")
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


USER_AGENT = "happy-hour-finder-ingest/1.0 (+https://paulrenzi.github.io/happy-hour-finder/)"


def api(env, path, method="GET", body=None):
    req = urllib.request.Request(
        env["SUBMIT_API"].rstrip("/") + path,
        method=method,
        headers={
            "X-Admin-Token": env["ADMIN_TOKEN"],
            # Cloudflare answers the default Python-urllib agent with a 1010
            # block, so every admin call -- and therefore the whole review
            # pipeline -- came back 403 before this line existed.
            "User-Agent": USER_AGENT,
        },
    )
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode("utf-8")
    with urllib.request.urlopen(req, timeout=60) as res:
        raw = res.read()
        return raw if res.headers.get("Content-Type", "").startswith("image/") else json.loads(raw)


def fetch_photo(env, sub):
    os.makedirs(PHOTO_DIR, exist_ok=True)
    ext = {"image/png": "png", "image/webp": "webp"}.get(sub["content_type"], "jpg")
    path = os.path.join(PHOTO_DIR, f"{sub['id']}.{ext}")
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(api(env, f"/admin/photo/{sub['id']}"))
    return path


def ask(path, prompt=None):
    """One `claude -p` call over one photo. Returns the parsed JSON object.

    `prompt` lets a caller hand in a variant of PROMPT (extract_menu_images
    adds the price-band rule); it must still carry the {path} and
    {categories} slots."""
    # `claude` is a .cmd shim on Windows, which subprocess will not find on its
    # own. The prompt goes in on stdin: the shim is a batch file and mangles a
    # multi-line argument, which fails by returning exit 0 and a wrong answer.
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("`claude` is not on PATH -- this pass runs on the CLI "
                           "subscription, not on an API key")
    proc = subprocess.run(
        [exe, "-p", "--model", MODEL, "--output-format", "json",
         # Read is the only tool it needs, and the only one it gets: this is
         # pointed at an image a stranger uploaded, so nothing here should be
         # able to run a command or write a file.
         "--allowedTools", "Read",
         # The harness itself is the bulk of a `claude -p` call -- a nine-token
         # prompt bills 28,272 input tokens of system prompt and tool schemas.
         # This pass reads one image and answers; it has no use for this repo's
         # CLAUDE.md or the dynamic prompt sections, and paying for them once
         # per submitted photo adds up. Read is still granted above.
         "--setting-sources", "",
         "--exclude-dynamic-system-prompt-sections"],
        input=(prompt or PROMPT).format(path=path, categories=", ".join(sorted(CATEGORIES))),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p exited {proc.returncode}: {proc.stderr[:300]}")
    body = json.loads(proc.stdout).get("result") or ""
    m = re.search(r"\{.*\}", body, re.S)
    if not m:
        raise ValueError(f"no JSON object in reply: {body[:200]}")
    return json.loads(m.group(0))


def norm(text):
    """Whitespace and case only. A quote check that also ignored punctuation
    would pass '$5 drafts' against 'no $5 drafts', which is the point of
    checking at all."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def ground(read):
    """Drop every item whose quote is not in the transcript. Returns the kept
    deals and a list of what went and why, which the reviewer sees."""
    transcript = norm(read.get("transcript"))
    kept, dropped = [], []
    for deal in read.get("deals") or []:
        items = []
        for item in deal.get("items") or []:
            quote = norm(item.get("quote"))
            if quote and quote in transcript:
                items.append({k: v for k, v in item.items() if v is not None})
            else:
                dropped.append(f"{item.get('label')!r}: quote not in the transcript")
        deal = dict(deal, items=items)
        # A window with no priced items is still an answer to "can I go now?",
        # so it ships and the app renders it as a window without prices. A deal
        # with neither is nothing.
        if deal["items"] or deal.get("windows"):
            kept.append(deal)
    return kept, dropped


def to_records(deals, sub, today):
    """Shape the model's deals like every other deal in the corpus."""
    out = []
    for deal in deals:
        rec = {
            "type": deal.get("type", "happy_hour"),
            "windows": deal.get("windows") or [],
            "items": [{k: v for k, v in i.items() if k != "quote"} for i in deal["items"]],
            "confidence": "unconfirmed",  # a photo is never self-verifying
            "last_verified_at": today,
            "verified_by": "photo_submission",
            "source": {"kind": "photo", "photo_id": sub["id"], "submitted": sub["submitted_at"]},
        }
        if deal.get("fine_print"):
            rec["fine_print"] = deal["fine_print"]
        out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = dict(os.environ)
    env.update(env_file())
    for key in ("SUBMIT_API", "ADMIN_TOKEN"):
        if not env.get(key):
            print(f"missing {key} -- see the docstring", file=sys.stderr)
            return 1
    if os.environ.get("ANTHROPIC_API_KEY"):
        # An exported key silently outranks the CLI login, so a pass that should
        # be running on the subscription quietly bills an API account instead.
        print("! ANTHROPIC_API_KEY is set in this shell. It outranks the `claude` "
              "login and this pass will bill an API key. Unset it first.",
              file=sys.stderr)
        return 1

    today = datetime.date.today().isoformat()
    pending = api(env, "/admin/queue?status=pending")["submissions"]
    if args.limit:
        pending = pending[: args.limit]
    if not pending:
        print("nothing pending")
        return 0
    print(f"{len(pending)} pending submission(s), model {MODEL}\n")

    for sub in pending:
        print(f"{sub['id'][:8]}  {sub['venue_name'] or sub['lid']}")
        try:
            read = ask(fetch_photo(env, sub))
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as err:
            print(f"    ! {err}")  # transient: leave it pending, try next run
            continue
        except (RuntimeError, ValueError, subprocess.TimeoutExpired,
                json.JSONDecodeError) as err:
            print(f"    ! {type(err).__name__}: {err}")
            if not args.dry_run:
                api(env, f"/admin/extract/{sub['id']}", "POST", {"error": str(err)[:2000]})
            continue

        if not read.get("is_menu"):
            reason = read.get("rejection_reason", "")
            print(f"    not a menu: {reason}")
            if not args.dry_run:
                api(env, f"/admin/extract/{sub['id']}", "POST",
                    {"extracted": {"is_menu": False, "reason": reason,
                                   "concerns": read.get("concerns") or [], "deals": []}})
            continue

        deals, dropped = ground(read)
        publishable, rejected = [], list(dropped)
        for rec in to_records(deals, sub, today):
            errs = validate_deal(rec)
            if errs:
                rejected.append(f"{rec['type']}: {errs[0]}")
            else:
                publishable.append(rec)
        for err in validate_food_combo_count(publishable):
            rejected.append(err)
            publishable = []

        proposal = {
            "is_menu": True,
            "venue_name_on_menu": read.get("venue_name_on_menu", ""),
            "concerns": read.get("concerns") or [],
            "transcript": read.get("transcript", ""),
            "deals": publishable,
            "rejected": rejected,
        }
        print(f"    {len(publishable)} deal(s) pass, {len(rejected)} dropped")
        for line in rejected:
            print(f"      - {line}")
        for concern in proposal["concerns"]:
            print(f"      ! {concern}")
        if args.dry_run:
            print(json.dumps(proposal, indent=1)[:1500])
        else:
            api(env, f"/admin/extract/{sub['id']}", "POST", {"extracted": proposal})

    print("\nNothing is published yet. Review with: python ingest/review_photos.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
