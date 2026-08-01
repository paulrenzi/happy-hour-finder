#!/usr/bin/env python3
"""Validators, decay ladder and geocode parsing.

    python -m unittest discover -s tests -v

These guard the two places bad data reaches users: a deal that should never have
been published (the PA validators) and a deal that is quietly too old to trust
(the decay ladder).
"""

import datetime
import json
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ingest"))

from build_bundles import decay  # noqa: E402
from fetch_venue_photos import IMG_DIR, photo_dest  # noqa: E402
from geocode_venues import split_address, strip_range, strategies  # noqa: E402
from validate_pa import validate_deal, validate_food_combo_count  # noqa: E402


def deal(**over):
    """A minimal publishable happy hour; override one field per test."""
    base = {
        "type": "happy_hour",
        "windows": [{"dow": 1, "start": "16:00", "end": "18:00"}],
        "items": [{"category": "draft", "label": "drafts", "price_usd": 5.0}],
        "confidence": "likely",
        "source": {"kind": "venue_site", "url": "https://example.com"},
    }
    base.update(over)
    return base


class PaValidators(unittest.TestCase):
    def test_a_plain_happy_hour_passes(self):
        self.assertEqual(validate_deal(deal()), [])

    def test_the_four_hour_daily_cap_is_a_boundary_not_a_range(self):
        exactly_four = deal(windows=[{"dow": 1, "start": "14:00", "end": "18:00"}])
        self.assertEqual(validate_deal(exactly_four), [], "4h exactly is legal")

        over = deal(windows=[{"dow": 1, "start": "14:00", "end": "18:30"}])
        self.assertTrue(any("4h/day" in e for e in validate_deal(over)))

    def test_the_weekly_cap_counts_across_days(self):
        # 7 days x 4h = 28h, over the 24h/week cap even though no single day is.
        week = deal(
            windows=[{"dow": d, "start": "14:00", "end": "18:00"} for d in range(1, 8)]
        )
        errs = validate_deal(week)
        self.assertTrue(any("24h/week" in e for e in errs), errs)

    def test_midnight_is_legal_but_past_midnight_is_not(self):
        # PA allows a discount to run to midnight; 24:00 is how the corpus says so.
        self.assertEqual(validate_deal(deal(windows=[{"dow": 5, "start": "22:00", "end": "24:00"}])), [])

        past = validate_deal(deal(windows=[{"dow": 5, "start": "22:00", "end": "25:00"}]))
        self.assertTrue(any("past midnight" in e for e in past))

        # An end at or before the start is a window that wraps into the morning.
        wrap = validate_deal(deal(windows=[{"dow": 5, "start": "22:00", "end": "02:00"}]))
        self.assertTrue(any("past midnight" in e for e in wrap))

    def test_unlawful_claims_are_refused_whatever_the_source_said(self):
        for claim in ["all you can drink", "bottomless mimosas", "free drink with entree",
                      "2 for 1 wells", "unlimited wings"]:
            errs = validate_deal(deal(items=[{"category": "draft", "label": claim, "price_usd": 5.0}]))
            self.assertTrue(any("unlawful" in e for e in errs), f"{claim!r} should be refused")

    def test_the_daily_special_is_exempt_from_the_four_hour_cap(self):
        # One beverage type may run open-to-close, so an 8h window is fine here.
        all_day = deal(type="daily_special", windows=[{"dow": 2, "start": "11:00", "end": "23:00"}])
        self.assertEqual(validate_deal(all_day), [])

    def test_a_deal_needs_a_time_and_a_source(self):
        self.assertTrue(any("no windows" in e for e in validate_deal(deal(windows=[]))))
        self.assertTrue(any("no source" in e for e in validate_deal(deal(source={}))))

    def test_an_item_with_neither_price_nor_discount_is_rejected(self):
        errs = validate_deal(deal(items=[{"category": "draft", "label": "drafts"}]))
        self.assertTrue(any("neither a price nor a discount" in e for e in errs))

    def test_at_most_two_food_combos_a_day(self):
        combo = deal(type="food_combo", windows=[{"dow": 3, "start": "16:00", "end": "18:00"}])
        self.assertEqual(validate_food_combo_count([combo, combo]), [])
        self.assertTrue(validate_food_combo_count([combo, combo, combo]))


class DecayLadder(unittest.TestCase):
    """A deal never disappears, it demotes -- deleting looks like a bug to the
    user who saw it yesterday. SPEC section 6."""

    TODAY = datetime.date(2026, 8, 1)

    def demote(self, confidence, days_old):
        seen = (self.TODAY - datetime.timedelta(days=days_old)).isoformat()
        return decay(confidence, seen, self.TODAY)

    def test_fresh_stays_put(self):
        self.assertEqual(self.demote("likely", 0), ("likely", 0))

    def test_likely_becomes_unconfirmed_after_45_days(self):
        self.assertEqual(self.demote("likely", 45)[0], "likely", "45 is not yet over 45")
        self.assertEqual(self.demote("likely", 46)[0], "unconfirmed")

    def test_anything_over_120_days_is_hidden(self):
        self.assertEqual(self.demote("likely", 120)[0], "unconfirmed")
        self.assertEqual(self.demote("likely", 121)[0], "hidden")
        self.assertEqual(self.demote("unconfirmed", 121)[0], "hidden")

    def test_operator_verified_and_disputed_do_not_decay(self):
        # An operator confirmation and a user dispute are both standing facts.
        self.assertEqual(self.demote("verified", 300)[0], "verified")
        self.assertEqual(self.demote("disputed", 300)[0], "disputed")


class Geocoding(unittest.TestCase):
    def test_address_splitting(self):
        self.assertEqual(
            split_address("800 Spring Mill Ave, Conshohocken PA 19428"),
            {"street": "800 Spring Mill Ave", "city": "Conshohocken", "state": "PA", "zip": "19428"},
        )
        self.assertIsNone(split_address("nowhere in particular"))

    def test_house_number_ranges_are_reduced_to_the_first_number(self):
        # '30-32 E State St' and '7-15 S High St' both missed until this ran.
        self.assertEqual(strip_range("30-32 E State St"), "30 E State St")
        self.assertEqual(strip_range("7-15 S High St"), "7 S High St")
        self.assertEqual(strip_range("324 W Swedesford Rd"), "324 W Swedesford Rd")

    def test_every_strategy_keeps_the_zip(self):
        # '324 W Swedesford Rd' exists in both 19312 and 19341, thirty miles
        # apart, so a query that drops the ZIP silently returns the wrong town.
        forms = list(strategies("324 W Swedesford Rd, Berwyn PA 19312"))
        self.assertTrue(forms)
        for label, params in forms:
            blob = " ".join(str(v) for v in params.values())
            self.assertIn("19312", blob, f"strategy {label} dropped the ZIP")


class SeedCorpus(unittest.TestCase):
    """The shipped corpus itself, not just the code that checks it."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO, "data", "deals_seed.json"), encoding="utf-8") as fh:
            cls.seed = json.load(fh)
        with open(os.path.join(REPO, "data", "venue_coords.json"), encoding="utf-8") as fh:
            cls.coords = json.load(fh)

    def test_every_seeded_deal_passes_the_validators(self):
        for venue in self.seed["venues"]:
            for d in venue["deals"]:
                self.assertEqual(validate_deal(d), [], f"{venue['name']} publishes an invalid deal")

    def test_every_venue_has_a_coordinate_inside_the_seed_market(self):
        for venue in self.seed["venues"]:
            self.assertIn(venue["id"], self.coords, f"{venue['name']} was never geocoded")
            at = self.coords[venue["id"]]
            self.assertTrue(39.6 < at["lat"] < 40.6 and -76.0 < at["lng"] < -74.8,
                            f"{venue['name']} resolved outside the 20-mile disc")

    def test_geocode_records_keep_the_address_they_were_asked_for(self):
        # The audit trail that makes a wrong match findable later.
        by_id = {v["id"]: v for v in self.seed["venues"]}
        for vid, at in self.coords.items():
            self.assertEqual(at["queried"], by_id[vid]["address"],
                             f"{vid}: cached coordinate is for a different address than the seed now lists")


class PhotoPaths(unittest.TestCase):
    """The photo lane costs money per call, so its paths are pinned before it runs."""

    def test_bytes_land_in_the_directory_the_run_creates(self):
        dest, _rel = photo_dest("coyote-crossing")
        self.assertEqual(os.path.dirname(dest), IMG_DIR,
                         "download writes outside the only directory makedirs creates")

    def test_the_manifest_path_is_relative_to_the_web_root(self):
        # app.js does img.src = photo.file, resolved against web/ -- not the repo.
        dest, rel = photo_dest("coyote-crossing")
        self.assertEqual(rel, "img/venues/coyote-crossing.jpg")
        self.assertEqual(os.path.join(REPO, "web", rel.replace("/", os.sep)), dest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
