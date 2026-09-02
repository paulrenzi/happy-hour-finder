"""The shell licence that resolved to a NEIGHBOUR, and everything it cost.

Media, 2026-09-02. Six of the town's forty-four licences named a holding
company, and every one of them read as "Google has no listing for this venue".
They were not absent: Off the Rail, Maris, Tap 24, Broad Table Tavern, John's
Grille and Pairings Cigar Bar were all there, all with a website and a photo.

Three separate faults, each of which alone was enough to lose the venue.
"""

import importlib.util
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "discover_places", os.path.join(REPO, "ingest", "discover_places.py"))
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)


class ADoorWithTwoNumbersOnIt(unittest.TestCase):
    """The PLCB writes the whole frontage, Google writes the one the business
    answers to. 'DKD 109 LLC, 109-111 W STATE ST' vs 'Off the Rail - Media,
    109 W State St'."""

    def test_a_range_spans_every_number_in_it(self):
        self.assertEqual(
            dp.street_numbers("109-111 W STATE ST 2ND FLOOR, MEDIA PA 19063"),
            {"109", "111"})

    def test_a_single_number_is_still_a_set_of_one(self):
        self.assertEqual(dp.street_numbers("214 WEST STATE ST, MEDIA PA 19063"),
                         {"214"})

    def test_googles_number_is_a_member_of_the_licences_range(self):
        ours = dp.street_numbers("109-111 W STATE ST 2ND FLOOR, MEDIA PA 19063")
        self.assertIn(dp.street_number("109 W State St, Media, PA 19063, USA"), ours)

    def test_the_mall_addresses_still_read_the_street_not_the_complex(self):
        self.assertEqual(
            dp.street_numbers("THE COURT UNIT C263A  690 W DEKALB PIKE, KOP PA 19406"),
            {"690"})


class TheRescueAndItsConsumerDriftedApart(unittest.TestCase):
    """EVIDENCE_SAFE_MATCHES was the literal set {"text search", "nearby
    search"}, and resolve() has never once returned the bare string "nearby
    search". So every venue the address fallback rescued was held out of the
    crawl frontier as though a NAME had matched it -- silently, with nothing
    failing."""

    def test_both_nearby_joins_are_safe_to_crawl_for_evidence(self):
        self.assertTrue(dp.evidence_safe("nearby search at the geocode"))
        self.assertTrue(dp.evidence_safe("nearby search at the licence address"))

    def test_a_text_search_join_is_safe(self):
        self.assertTrue(dp.evidence_safe("text search"))

    def test_a_name_join_is_not(self):
        self.assertFalse(dp.evidence_safe("name agrees, same town (addresses differ)"))
        self.assertFalse(dp.evidence_safe(None))


class TheNearbySearchAsksForTheNearest(unittest.TestCase):
    """Ranked by popularity, 120 m of State Street returned the ten best-known
    bars in Media and not the shell-licensed rooftop we were standing on."""

    def test_the_request_asks_for_distance_order(self):
        sent = {}

        def fake_post(_key, _url, body):
            sent.update(body)
            return [{"displayName": {"text": "Off the Rail - Media"},
                     "formattedAddress": "109 W State St, Media, PA 19063, USA"}]

        real, dp.post = dp.post, fake_post
        try:
            got = dp.nearby_search("k", 39.9, -75.4, "109-111 W STATE ST, MEDIA PA")
        finally:
            dp.post = real
        self.assertEqual(sent.get("rankPreference"), "DISTANCE")
        self.assertEqual(got["displayName"]["text"], "Off the Rail - Media")

    def test_a_neighbour_at_the_wrong_number_is_still_refused(self):
        def fake_post(_key, _url, _body):
            return [{"displayName": {"text": "Sligo Irish Pub"},
                     "formattedAddress": "113 W State St, Media, PA 19063, USA"}]

        real, dp.post = dp.post, fake_post
        try:
            self.assertIsNone(
                dp.nearby_search("k", 39.9, -75.4, "109-111 W STATE ST, MEDIA PA"))
        finally:
            dp.post = real


if __name__ == "__main__":
    unittest.main()
