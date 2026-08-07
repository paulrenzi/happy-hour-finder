"""The address join in discover_places.py, pinned at the shape that broke it.

Every failure mode here reads downstream as "Google has no listing for this
venue" rather than as a comparison bug, which is what made the original one
expensive: all twelve King of Prussia mall venues looked absent from Places when
the join had simply never run.
"""

import importlib.util
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "discover_places", os.path.join(REPO, "ingest", "discover_places.py")
)
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)


class StreetNumberReadsTheStreetNotTheString(unittest.TestCase):
    def test_a_premises_address_leading_with_its_complex_still_yields_the_street_number(self):
        # The PLCB writes the mall before the street. Reading leading digits
        # returns None here, and None never equals anything Google sends back.
        for addr, want in [
            ("THE COURT UNIT C263A  690 W DEKALB PIKE, KING OF PRUSSIA PA 19406", "690"),
            ("KING OF PRUSSIA PLAZA 205 MALL BLVD, KING OF PRUSSIA PA 19406-2924", "205"),
            ("THE PAVILION AT KING OF PRUSSIA 640 W. DEKALB PK #1250, KOP PA 19406", "640"),
            ("THE PLAZA AT KING OF PRUSSIA 160 N GULPH RD STE 233, KOP PA 19406", "160"),
        ]:
            self.assertEqual(dp.street_number(addr), want, addr)

    def test_a_unit_code_containing_digits_is_not_read_as_a_street_number(self):
        self.assertEqual(dp.street_number("THE COURT UNIT C263A 690 W DEKALB PIKE"), "690")

    def test_both_sides_of_the_join_agree_on_the_same_address(self):
        ours = "KING OF PRUSSIA PLAZA 205 MALL BLVD, KING OF PRUSSIA PA 19406-2924"
        theirs = "205 Mall Blvd, King of Prussia, PA 19406, USA"
        self.assertEqual(dp.street_number(ours), dp.street_number(theirs))


class NameFallbackStaysNarrow(unittest.TestCase):
    def test_a_corporate_suffix_does_not_block_a_real_match(self):
        self.assertTrue(dp.name_agrees(
            "THE CHEESECAKE FACTORY RESTAURANTS INC", "The Cheesecake Factory",
            "570 MALL BLVD A5, KING OF PRUSSIA PA 19406",
            "640 W Dekalb Pike Ste 1200, King of Prussia, PA 19406, USA"))

    def test_two_different_venues_in_one_town_do_not_match(self):
        self.assertFalse(dp.name_agrees(
            "TOMMY'S TAVERN + TAP", "Tommy Bahama Marlin Bar",
            "160 N GULPH RD, KING OF PRUSSIA PA 19406",
            "350 Mall Blvd, King of Prussia, PA 19406, USA"))

    def test_the_same_name_in_another_town_does_not_match(self):
        # Iron Hill has ten locations; without the ZIP guard the name alone would
        # bind a Phoenixville licence to a King of Prussia listing.
        self.assertFalse(dp.name_agrees(
            "IRON HILL BREWERY", "Iron Hill Brewery",
            "130 E BRIDGE ST, PHOENIXVILLE PA 19460",
            "160 N Gulph Rd, King of Prussia, PA 19406, USA"))

    def test_locality_reads_a_zip_from_an_address_with_no_clean_city_segment(self):
        self.assertEqual(
            dp.locality("...690 W DEKALB PIKE, KING OF PRUSSIA PA 19406"), {"19406"})


class GeocodeDetection(unittest.TestCase):
    def test_a_street_address_result_with_no_site_or_photo_is_a_geocode(self):
        place = {"displayName": {"text": "940 Township Line Rd"}}
        self.assertTrue(dp.looks_like_a_geocode(place, "940 TOWNSHIP LINE RD, PHOENIXVILLE PA"))

    def test_a_real_business_at_that_address_is_not(self):
        place = {"displayName": {"text": "Grid Iron Sports Bar"},
                 "websiteUri": "https://example.com"}
        self.assertFalse(dp.looks_like_a_geocode(place, "940 TOWNSHIP LINE RD, PHOENIXVILLE PA"))


if __name__ == "__main__":
    unittest.main()
