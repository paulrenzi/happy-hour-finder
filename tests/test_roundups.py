"""The roundup lane after 2026-09-02: an old article is a LABELLED source, a
roundup is read heading-by-heading, and a bare clock in a happy-hour article
is a PM clock. Plus the address-collision fix that had Sedona Taphouse losing
its card to the bar downstairs."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ingest"))

from crawl_roundups import mentions, venue_index  # noqa: E402
from extract_roundups import deals_for, pmify, windows_in_paragraph  # noqa: E402
from discover_sites import name_agrees  # noqa: E402

SITES = {
    "1": {"name": "WRONG CROWD BEER CO", "osm_name": "Wrong Crowd Beer Company",
          "address": "342 HANNUM AVE, WEST CHESTER PA 19380", "zone_id": "west_chester"},
    "2": {"name": "THE RAMS HEAD BAR & GRILL", "osm_name": "Santino's Tap & Table",
          "address": "40 E MARKET ST, WEST CHESTER PA 19382", "zone_id": "west_chester"},
    "3": {"name": "SEDONA TAPHOUSE", "osm_name": "Sedona Taphouse",
          "address": "44 W GAY ST, WEST CHESTER PA 19380", "zone_id": "west_chester"},
    "4": {"name": "TECA-R", "osm_name": "Teca",
          "address": "38 E GAY ST, WEST CHESTER PA 19380", "zone_id": "west_chester"},
}

ARTICLE = """Cheers! It's Happy Hour
Relaxed
Wrong Crowd Beer Co.
Wrong Crowd Beer Co.
Wrong Crowd is located in a converted warehouse. Happy Hour runs Wednesday and Thursday, 4 to 6, and Friday, 3 to 5, when a pint is $4.
Sterling Pig Public House
The day starts happy at Sterling Pig. Happy Hour begins when the bar opens at 4.
Sedona Taphouse
When you've got a group to impress, Sedona it is. Weekdays from 4 to 6, half-price bottled beers and $6.90 wine and cocktails.
Teca
At Teca it's all about sharing. Tuesday through Friday, 4 to 6, $7 wine by the glass, $5 drafts, $7 well drinks.
"""


class HeadingBlocks(unittest.TestCase):
    def setUp(self):
        self.index = venue_index(SITES, "west_chester")
        self.found = {m["lid"]: m for m in mentions(ARTICLE, self.index)}

    def test_the_trade_name_is_indexed_not_only_the_licensee(self):
        self.assertIn("santino s tap table", self.index)
        self.assertIn("rams head", self.index)

    def test_a_heading_owns_the_paragraph_under_it_and_stops_at_the_next(self):
        self.assertIn("1", self.found)
        self.assertEqual(len(self.found["1"]["quotes"]), 1)
        self.assertIn("Wednesday and Thursday", self.found["1"]["quotes"][0])
        # Sterling Pig is not in the base, but its heading still ENDS Wrong
        # Crowd's block -- its paragraph must not be filed under Wrong Crowd.
        self.assertNotIn("Sterling Pig", " ".join(self.found["1"]["quotes"]))

    def test_a_one_word_name_matches_as_a_heading_only(self):
        # 'Teca' the heading is Teca. 'Sedona it is.' inside prose is not a heading.
        self.assertIn("4", self.found)
        self.assertIn("Tuesday through Friday", self.found["4"]["quotes"][0])
        self.assertIn("3", self.found)
        self.assertEqual(len(self.found["3"]["quotes"]), 1)

    def test_co_and_company_agree(self):
        self.assertEqual(self.found["1"]["name"], "WRONG CROWD BEER CO")


class BareClocksArePm(unittest.TestCase):
    def test_a_bare_range_gets_a_meridiem(self):
        self.assertEqual(pmify("Happy Hour 4 to 6"), "Happy Hour 4 pm - 6 pm")
        self.assertEqual(pmify("3 to 5:30, Monday"), "3 pm - 5:30 pm, Monday")

    def test_a_price_a_percent_and_a_unit_are_left_alone(self):
        self.assertEqual(pmify("$5-7 apps"), "$5-7 apps")
        self.assertEqual(pmify("2-4 people"), "2-4 people")
        self.assertEqual(pmify("4-6 pm"), "4-6 pm")
        self.assertEqual(pmify("save 5-10%"), "save 5-10%")

    def test_two_ranges_in_one_sentence_each_keep_their_days(self):
        ws = windows_in_paragraph(
            "Happy Hour runs Wednesday and Thursday, 4 to 6, and Friday, 3 to 5, when a pint is $4.")
        got = {(w["dow"], w["start"], w["end"]) for w in ws}
        self.assertEqual(got, {(3, "16:00", "18:00"), (4, "16:00", "18:00"), (5, "15:00", "17:00")})

    def test_a_deal_is_labelled_with_the_outlet_and_month(self):
        art = {"url": "https://x/y", "outlet": "County Lines Magazine", "published": "2024-05-30"}
        deals = deals_for({"quotes": ["Happy Hour runs Monday through Friday, 5 to 7, with $6 wine."]},
                          art, "2026-09-02")
        self.assertEqual(len(deals), 1)
        d = deals[0]
        self.assertEqual(d["source"]["kind"], "roundup")
        self.assertEqual(d["source"]["note"], "County Lines Magazine, May 2024")
        self.assertEqual(d["confidence"], "unconfirmed")
        self.assertEqual(d["last_verified_at"], "2026-09-02")
        self.assertEqual([i["label"] for i in d["items"]], ["wine"])

    def test_a_paragraph_with_no_clock_is_refused(self):
        art = {"url": "https://x/y", "outlet": "O", "published": "2024-05-30"}
        self.assertEqual(deals_for({"quotes": ["Happy Hour runs Tuesday to Thursday, 20% off."]},
                                   art, "2026-09-02"), [])


class TwoBarsOneBuilding(unittest.TestCase):
    """44 W Gay St is Lascala's Fire AND Sedona Taphouse. The address alone
    made Sedona a duplicate of Lascala's and it never reached the board."""

    def test_different_names_at_one_address_do_not_agree(self):
        self.assertFalse(name_agrees("Sedona Taphouse", "Lascala's Fire"))

    def test_a_shell_name_still_agrees_with_its_trade_name(self):
        self.assertTrue(name_agrees("SEDONA TAPHOUSE", "Sedona Taphouse"))


if __name__ == "__main__":
    unittest.main()
