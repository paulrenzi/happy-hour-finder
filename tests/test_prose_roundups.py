"""The roundup that has no headings, and the site chrome that ate the ones
that did (2026-09-02, DELCO.today / Media).

Four cleanly dated DELCO.today articles matched ZERO venues while naming Azie
and Off the Rail with clocks in plain English. Two independent reasons, both
pinned here.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ingest"))

from crawl_roundups import (  # noqa: E402
    is_heading, mentions, outlet_chrome, subject_venue, venue_index,
)

SITES = {
    "58431": {"name": "AZIE RESTAURANT", "osm_name": "Azie Media",
              "address": "217-219 W STATE ST, MEDIA PA 19063", "zone_id": "media"},
    "101350": {"name": "DKD 109 LLC", "osm_name": "Off the Rail - Media",
               "address": "109-111 W STATE ST, MEDIA PA 19063", "zone_id": "media"},
    "108693": {"name": "MEDIADIVE LLC", "osm_name": "State Street Pub",
               "address": "37 E STATE ST, MEDIA PA 19063", "zone_id": "media"},
    "64352": {"name": "BARNIEU RESTAURANT GROUP LLC", "osm_name": "Tap 24",
              "address": "36-38 W STATE ST, MEDIA PA 19063", "zone_id": "media"},
}
INDEX = venue_index(SITES, "media")

AZIE = ("Azie in Media has a happy hour on weekdays from 4 to 6 PM, and an "
        "indoor and outdoor bar area with scenic views of Media.")
RAIL = ("Off the Rail , also in Media, has $3 domestic beers during happy "
        "hours weeknights, 4 to 6 PM, enjoyed at its rooftop bar with views "
        "of State Street below.")


class AVenueNamedInsideASentence(unittest.TestCase):
    def test_the_subject_of_a_happy_hour_sentence_is_matched(self):
        self.assertEqual(subject_venue(AZIE, INDEX)["lid"], "58431")
        self.assertEqual(subject_venue(RAIL, INDEX)["lid"], "101350")

    def test_a_venue_named_late_in_the_sentence_is_not_its_subject(self):
        # 🛑 The whole hazard in one line. 'views of State Street below' names
        # State Street Pub, three doors from Off the Rail and on the same
        # board. Publishing $3 domestic beers under it is worse than
        # publishing nothing, and position is what refuses it.
        self.assertNotEqual(subject_venue(RAIL, INDEX)["lid"], "108693")

    def test_a_sentence_that_does_not_say_happy_hour_names_nobody(self):
        self.assertIsNone(subject_venue(
            "Azie in Media serves dinner from 5 PM.", INDEX))

    def test_a_one_word_name_is_never_enough(self):
        # 'Sedona it is.' must stay not-Sedona, however the sentence reads.
        index = venue_index({"9": {"name": "SEDONA", "osm_name": "Sedona",
                                   "address": "44 W GAY ST, WEST CHESTER PA 19380",
                                   "zone_id": "west_chester"}}, "west_chester")
        self.assertIsNone(subject_venue(
            "Sedona it is, for happy hour from 4 to 6 PM.", index))

    def test_two_venues_in_one_sentence_is_an_ambiguity_not_a_choice(self):
        self.assertIsNone(subject_venue(
            "Azie Media and Tap 24 both run a happy hour, 4 to 6 PM.", INDEX))

    def test_a_prose_article_with_no_headings_still_yields_its_venues(self):
        text = "\n".join(["Time to Take in the View", AZIE, RAIL])
        got = {v["lid"]: v for v in mentions(text, INDEX)}
        self.assertEqual(set(got), {"58431", "101350"})
        # The quote is the SENTENCE, not the paragraph: a paragraph can carry
        # two bars, and each would then wear the other's clock.
        self.assertEqual(got["101350"]["quotes"], [RAIL])
        self.assertEqual(got["101350"]["joined_by"], "sentence")


class SiteChromeIsNotAVenue(unittest.TestCase):
    NAV = ["Commerce", "Community", "Search", "Partner / Advertise",
           "About DELCO Today", "Sign Up"]

    def test_a_line_on_every_page_of_an_outlet_is_navigation(self):
        pages = ["\n".join(self.NAV + [AZIE]), "\n".join(self.NAV + [RAIL])]
        chrome = outlet_chrome(pages)
        self.assertTrue(set(self.NAV) <= chrome)
        self.assertNotIn(AZIE, chrome)

    def test_every_one_of_those_lines_would_otherwise_pass_as_a_heading(self):
        # Which is the mechanism: they queue up ahead of the article and eat
        # the paragraphs under it.
        self.assertTrue(all(is_heading(ln) for ln in self.NAV))

    def test_a_line_carrying_a_deal_is_never_chrome_however_often_it_repeats(self):
        line = "Happy Hour 4 to 6 PM with $3 domestic beers"
        self.assertNotIn(line, outlet_chrome([line + "\nA", line + "\nB"]))

    def test_one_page_teaches_us_nothing_about_an_outlets_chrome(self):
        self.assertEqual(outlet_chrome(["\n".join(self.NAV)]), set())

    def test_chrome_lines_are_dropped_before_the_heading_queue_forms(self):
        text = "\n".join(self.NAV + [AZIE])
        self.assertEqual([v["lid"] for v in mentions(text, INDEX, chrome=set(self.NAV))],
                         ["58431"])


if __name__ == "__main__":
    unittest.main()
