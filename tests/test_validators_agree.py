"""The two PA validators must never disagree.

ingest/validate_pa.py gates the bundle build. worker/validate_pa.js gates
auto-approval inside the Worker, where there is no Python. Two implementations
of a legal rule is a liability: the day they drift, one of them publishes
something the other would have refused, and nothing reports it.

So this runs BOTH over the same corpus -- every deal the site ships plus the
edge cases each rule exists for -- and compares the error lists character for
character. It is the reason the JS port keeps Python's exact wording.
"""

import json
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ingest"))

from validate_pa import validate_deal, validate_food_combo_count  # noqa: E402

DATA = os.path.join(REPO, "data")

# One deal per rule, shaped so exactly that rule fires. A corpus of only
# shipped deals would be all-passing, and two implementations agree trivially
# when neither ever rejects anything.
EDGE_CASES = [
    {"note": "clean happy hour", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "17:00", "end": "19:00"}],
     "items": [{"category": "draft", "label": "Drafts", "price_usd": 5}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "midnight is legal", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 7, "start": "22:00", "end": "24:00"}],
     "items": [{"category": "cocktail", "label": "Rita", "price_usd": 6}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "past midnight", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "22:00", "end": "25:00"}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "wraps backwards", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "22:00", "end": "02:00"}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "over 4h in a day, split", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "11:00", "end": "14:00"},
                 {"dow": 1, "start": "17:00", "end": "20:30"}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "exactly 4h is fine", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "17:00", "end": "19:00"},
                 {"dow": 1, "start": "22:00", "end": "24:00"}],
     "items": [{"category": "draft", "label": "Drafts", "price_usd": 5}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "over 24h a week", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": d, "start": "15:00", "end": "19:00"} for d in range(1, 8)],
     "items": [{"category": "draft", "label": "Drafts", "price_usd": 5}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "daily_special skips the caps", "type": "daily_special",
     "confidence": "verified",
     "windows": [{"dow": d, "start": "11:00", "end": "23:00"} for d in range(1, 8)],
     "items": [{"category": "draft", "label": "Drafts", "price_usd": 5}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "no windows", "type": "happy_hour", "confidence": "verified",
     "windows": [], "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "malformed window", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "5pm", "end": "7pm"}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "dow out of range", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 0, "start": "17:00", "end": "19:00"},
                 {"dow": 8, "start": "17:00", "end": "19:00"}],
     "items": [{"category": "draft", "label": "Drafts", "price_usd": 5}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "unknown type and confidence", "type": "brunch", "confidence": "certain",
     "windows": [{"dow": 1, "start": "17:00", "end": "19:00"}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "banned claims", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "17:00", "end": "19:00"}],
     "items": [{"category": "draft", "label": "Bottomless mimosas", "price_usd": 5},
               {"category": "well", "label": "2 for 1 wells", "price_usd": 4}],
     "fine_print": "All-you-can-drink and unlimited refills, free drink with entree",
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "item with no price", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "17:00", "end": "19:00"}],
     "items": [{"category": "wine", "label": "House red"}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "unknown category", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "17:00", "end": "19:00"}],
     "items": [{"category": "dessert", "label": "Cake", "price_usd": 3}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "no source at all", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "17:00", "end": "19:00"}],
     "items": [{"category": "draft", "label": "Drafts", "price_usd": 5}],
     "source": {}},
    {"note": "roundup missing everything", "type": "happy_hour", "confidence": "likely",
     "windows": [{"dow": 1, "start": "17:00", "end": "19:00"}],
     "items": [{"category": "draft", "label": "Drafts", "price_usd": 5}],
     "source": {"kind": "roundup", "url": "https://example.com/x"}},
    {"note": "roundup done right", "type": "happy_hour", "confidence": "unconfirmed",
     "windows": [{"dow": 1, "start": "17:00", "end": "19:00"}],
     "items": [{"category": "draft", "label": "Drafts", "price_usd": 5}],
     "source": {"kind": "roundup", "url": "https://example.com/x",
                "outlet": "Philly Mag", "published": "2026-06-01"}},
    {"note": "fractional hours print like Python", "type": "happy_hour",
     "confidence": "verified",
     "windows": [{"dow": 3, "start": "16:00", "end": "20:30"}],
     "items": [{"category": "draft", "label": "Drafts", "price_usd": 5}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "quote in a label", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "17:00", "end": "19:00"}],
     "items": [{"category": "shot", "label": "Mike's \"famous\" shot"}],
     "source": {"kind": "photo", "photo_id": "abc"}},
    {"note": "apostrophe in a label", "type": "happy_hour", "confidence": "verified",
     "windows": [{"dow": 1, "start": "17:00", "end": "19:00"}],
     "items": [{"category": "shot", "label": "Henny's Nirvana"}],
     "source": {"kind": "photo", "photo_id": "abc"}},
]


def shipped_deals():
    deals = []
    for name in os.listdir(DATA):
        if not name.startswith("deals_") or not name.endswith(".json"):
            continue
        payload = json.load(open(os.path.join(DATA, name), encoding="utf-8"))
        for venue in payload.get("venues", []):
            deals.extend(venue.get("deals", []))
    return deals


def js_verdicts(deals, venue_groups):
    """Run worker/validate_pa.js over the same input and hand back its answers."""
    script = """
      import { validateDeal, validateFoodComboCount } from "%s";
      let raw = "";
      process.stdin.on("data", (d) => (raw += d));
      process.stdin.on("end", () => {
        const input = JSON.parse(raw);
        process.stdout.write(JSON.stringify({
          deals: input.deals.map(validateDeal),
          groups: input.groups.map(validateFoodComboCount),
        }));
      });
    """ % (
        "file:///" + os.path.join(REPO, "worker", "validate_pa.js").replace("\\", "/")
    )
    out = subprocess.run(
        [_node(), "--input-type=module", "-e", script],
        input=json.dumps({"deals": deals, "groups": venue_groups}),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"the JS validators would not run:\n{out.stderr}")
    return json.loads(out.stdout)


def _node():
    return "node"


class ValidatorsAgree(unittest.TestCase):
    def test_the_two_implementations_return_identical_errors(self):
        deals = shipped_deals() + EDGE_CASES
        # Every venue's deals, so the food-combo cap has something to count.
        groups = []
        for name in os.listdir(DATA):
            if name.startswith("deals_") and name.endswith(".json"):
                payload = json.load(open(os.path.join(DATA, name), encoding="utf-8"))
                groups.extend(v.get("deals", []) and [v["deals"]] or []
                              for v in payload.get("venues", []))
        groups = [g[0] for g in groups if g]
        groups.append(EDGE_CASES)

        js = js_verdicts(deals, groups)

        for deal, got in zip(deals, js["deals"]):
            want = validate_deal(deal)
            self.assertEqual(
                want, got,
                f"disagreement on {deal.get('note') or deal.get('type')}: "
                f"python={want} js={got}",
            )
        for group, got in zip(groups, js["groups"]):
            self.assertEqual(validate_food_combo_count(group), got)

    def test_the_corpus_actually_exercises_the_rules(self):
        # An all-passing corpus makes the comparison above meaningless: two
        # implementations that never reject anything always agree.
        rejected = [d for d in EDGE_CASES if validate_deal(d)]
        self.assertGreaterEqual(len(rejected), 10)
        self.assertTrue(any(not validate_deal(d) for d in EDGE_CASES),
                        "the corpus must contain deals that PASS too")


if __name__ == "__main__":
    unittest.main()
