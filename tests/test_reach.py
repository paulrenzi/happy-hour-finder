"""The reach pass: a model may only pick a URL it was shown, only quote a line
that is on the page, and a searched venue is a candidate until confirmed.

    python -m unittest tests.test_reach -v
"""
import json
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ingest"))

import reach_llm as rl  # noqa: E402
import report_coverage as rc  # noqa: E402
import extract_deals as ex  # noqa: E402


class ThePickerMayOnlyChooseWhatItWasShown(unittest.TestCase):
    HOME = "https://www.slyfoxbeer.com/"
    HTML = '''
      <nav><a href="/">Home</a><a href="/phoenixville">Phoenixville</a>
      <a href="/pottstown">Pottstown</a><a href="https://toasttab.com/x">Order</a>
      <a href="/menu.pdf">Menu</a><a href="/logo.png">x</a>
      <a href="mailto:a@b.c">mail</a><a href="/phoenixville">dup</a></nav>'''

    def test_inventory_is_same_domain_deduped_and_without_assets(self):
        inv = rl.inventory(self.HTML, self.HOME, sitemap=["https://www.slyfoxbeer.com/happy-hour"])
        urls = [u for _, u in inv]
        self.assertEqual(urls, ["https://www.slyfoxbeer.com/phoenixville",
                                "https://www.slyfoxbeer.com/pottstown",
                                "https://www.slyfoxbeer.com/menu.pdf",
                                "https://www.slyfoxbeer.com/happy-hour"])
        self.assertEqual(inv[0][0], "Phoenixville")
        self.assertEqual(inv[-1][0], "(sitemap)")

    def test_an_invented_url_is_discarded(self):
        inv = {"36841": rl.inventory(self.HTML, self.HOME)}
        reply = [{"id": "36841",
                  "happy_hour": ["https://www.slyfoxbeer.com/happy-hour-invented",
                                 "https://www.slyfoxbeer.com/menu.pdf"],
                  "location": ["https://www.slyfoxbeer.com/phoenixville"]}]
        picked = rl.pick(reply, inv)
        self.assertEqual(picked["36841"]["happy_hour"], ["https://www.slyfoxbeer.com/menu.pdf"])
        self.assertEqual(picked["36841"]["location"], ["https://www.slyfoxbeer.com/phoenixville"])

    def test_an_empty_answer_is_not_a_row(self):
        inv = {"1": rl.inventory(self.HTML, self.HOME)}
        self.assertEqual(rl.pick([{"id": "1", "happy_hour": [], "location": []}], inv), {})
        self.assertEqual(rl.pick([{"id": "9", "happy_hour": ["x"]}], inv), {})

    def test_the_pick_cap_holds(self):
        inv = {"1": [("a", f"https://x.com/{i}") for i in range(10)]}
        reply = [{"id": "1", "happy_hour": [f"https://x.com/{i}" for i in range(10)]}]
        self.assertEqual(len(rl.pick(reply, inv)["1"]["happy_hour"]), rl.PICK_CAP)


class TheVerdictMayOnlyQuoteThePage(unittest.TestCase):
    LINES = ["DAILY SPECIALS", "​ Tuesday-Friday: Appy Hour",
             "$2 off select appetizers and $1 wings from 3PM-6PM (dine-in only)",
             "Saturday: $11 Mystery Pitcher"]

    def test_a_line_on_the_page_comes_back_as_the_page_spells_it(self):
        got = rl.grounded(["tuesday-friday: appy hour"], self.LINES)
        self.assertEqual(got, ["Tuesday-Friday: Appy Hour"])

    def test_a_paraphrase_is_dropped(self):
        got = rl.grounded(["Appy Hour Tue-Fri 3-6"], self.LINES)
        self.assertEqual(got, [])

    def test_a_substring_of_a_line_is_kept(self):
        got = rl.grounded(["$1 wings from 3PM-6PM"], self.LINES)
        self.assertEqual(got, ["$1 wings from 3PM-6PM"])

    def test_junk_is_dropped_and_order_is_kept(self):
        got = rl.grounded([None, "", "x", "Saturday: $11 Mystery Pitcher",
                           "DAILY SPECIALS", "DAILY SPECIALS"], self.LINES)
        self.assertEqual(got, ["Saturday: $11 Mystery Pitcher", "DAILY SPECIALS"])

    def test_the_grammar_reads_a_grounded_quote_like_a_crawled_one(self):
        quote = " / ".join(rl.grounded(
            ["Tuesday-Friday: Appy Hour", "$2 off select appetizers and $1 wings from 3PM-6PM (dine-in only)"],
            self.LINES))
        wins = ex.windows_from(quote)
        self.assertEqual(sorted(w["dow"] for w in wins), [2, 3, 4, 5])
        self.assertEqual({(w["start"], w["end"]) for w in wins}, {("15:00", "18:00")})


class ASearchedVenueIsMatchedOnAddressFirst(unittest.TestCase):
    BASE = [("36841", {"name": "Sly Fox", "address": "520 Kimberton Rd, Phoenixville PA 19460"}),
            ("1", {"name": "Liberty Union Bar & Grill", "address": "519 Kimberton Rd, Phoenixville PA 19460"}),
            ("2", {"name": "Bistro on Bridge", "address": "212 Bridge St, Phoenixville PA 19460"}),
            ("3", {"name": "The Analog Room", "address": "212 Bridge St, Phoenixville PA 19460"})]

    def place(self, name, addr):
        return {"displayName": {"text": name}, "formattedAddress": addr}

    def test_google_spelling_matches_plcb_spelling_on_number_and_zip(self):
        p = self.place("Sly Fox Brewhouse & Eatery", "520 Kimberton Rd, Phoenixville, PA 19460, USA")
        self.assertEqual(rl.match_place(p, self.BASE), "36841")

    def test_two_licences_at_one_address_are_told_apart_by_name(self):
        p = self.place("The Analog Room", "212 Bridge St, Phoenixville, PA 19460, USA")
        self.assertEqual(rl.match_place(p, self.BASE), "3")

    def test_a_stranger_matches_nothing(self):
        p = self.place("Grid Iron Sports Bar", "934 Township Line Rd, Phoenixville, PA 19460, USA")
        self.assertIsNone(rl.match_place(p, self.BASE))

    def test_town_is_read_off_the_licence_address(self):
        self.assertEqual(rl.town_of("520 Kimberton Rd, Phoenixville PA 19460"), "Phoenixville")
        self.assertEqual(rl.town_of("175 Town Center Rd, King Of Prussia PA 19406"), "King Of Prussia")
        self.assertEqual(rl.town_of(""), "")


class NotALicenseeWeHoldMustMeanIt(unittest.TestCase):
    """Two ways the town search called a venue missing that we already had.

    This is the count Paul asked about, so the instrument reporting it has to be
    right before the number means anything. Four of West Chester's twelve
    "NOT A LICENSEE WE HOLD" lines were ours; two were these.
    """

    ROWS = [
        ("126237", {"name": "The Stone Tavern",
                    "address": "1227 W Chester Pk, West Chester PA 19380"}),
        ("59213", {"name": "Limoncello",
                   "address": "5-7-9 N Walnut St, West Chester PA 19380"}),
        ("99999", {"name": "Bar Avalon",
                   "address": "400 Elsewhere Rd, Pottstown PA 19464"}),
    ]
    ZIPS = {"19380", "19382"}

    @staticmethod
    def place(name, address):
        return {"displayName": {"text": name}, "formattedAddress": address}

    def test_a_house_range_keeps_its_last_number(self):
        # '5-7-9 N Walnut St' is the licence; '9 N Walnut St' is the sign. Only
        # the first two numbers were read, so the one Google uses was lost.
        self.assertEqual(rl.house_numbers("5-7-9 N Walnut St"),
                         {"5", "7", "9"})
        self.assertEqual(rl.house_numbers("208-212 Main St"), {"208", "212"})
        self.assertEqual(rl.house_numbers("1227 W Chester Pk"), {"1227"})

    def test_the_venue_at_a_three_part_range_is_found(self):
        self.assertEqual(
            rl.match_place(self.place("Limoncello West Chester",
                                      "9 N Walnut St, West Chester, PA 19380, USA"),
                           self.ROWS, self.ZIPS),
            "59213")

    def test_google_and_the_plcb_may_disagree_on_a_zip_inside_one_town(self):
        # 19382 to Google, 19380 on the licence, both West Chester. Requiring
        # them equal turned a venue on our own board into a venue we do not
        # hold. The name test is still exact and both ZIPs must be the zone's.
        self.assertEqual(
            rl.match_place(self.place("The Stone Tavern",
                                      "1227 West Chester Pike, West Chester, PA 19382, USA"),
                           self.ROWS, self.ZIPS),
            "126237")

    def test_a_zip_outside_the_zone_still_does_not_match(self):
        self.assertIsNone(
            rl.match_place(self.place("The Stone Tavern",
                                      "1227 Some Pike, Reading, PA 19601, USA"),
                           self.ROWS, self.ZIPS))

    def test_a_venue_we_really_do_not_hold_is_still_reported_missing(self):
        self.assertIsNone(
            rl.match_place(self.place("Bier and Loathing",
                                      "113 W Market St, West Chester, PA 19382, USA"),
                           self.ROWS, self.ZIPS))


class CoverageDividesByConfirmedRowsOnly(unittest.TestCase):
    def test_candidates_are_not_in_the_denominator(self):
        rows = [{"lid": "1", "confirmed": True}, {"lid": "2", "confirmed": True},
                {"lid": "3", "confirmed": False}, {"name": "no lid", "confirmed": True}]
        cards, confirmed, misses = rc.coverage(rows, {"1": {}, "3": {}})
        self.assertEqual((cards, len(confirmed)), (1, 2))
        self.assertEqual([m["lid"] for m in misses], ["2"])

    def test_no_rows_is_no_number(self):
        self.assertEqual(rc.coverage([], {"1": {}})[:1], (0,))


class EverySheetAVenuePostedIsReadForHours(unittest.TestCase):
    def test_the_hours_on_the_first_sheet_survive_a_second_sheet(self):
        scripts = {"v": {"url": "https://x/page_2.png", "transcript": "FOOD MENU\nWings $10",
                         "images": {"https://x/page_1.png": "HAPPY HOUR\nMon-Fri 4-6pm\n$4 drafts",
                                    "https://x/page_2.png": "FOOD MENU\nWings $10"}}}
        got = ex.picture_spans(scripts)
        self.assertEqual(got["v"][0], "https://x/page_1.png")
        self.assertIn("HAPPY HOUR Mon-Fri 4-6pm $4 drafts", got["v"][1])

    def test_the_old_one_transcript_shape_still_reads(self):
        scripts = {"v": {"url": "https://x/a.png", "transcript": "Happy Hour\nWed-Fri 3pm to 6pm"}}
        self.assertEqual(ex.picture_spans(scripts)["v"][0], "https://x/a.png")


if __name__ == "__main__":
    unittest.main()
