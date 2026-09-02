"""A window must agree with the quote printed under it -- and the three ways
that stopped being true (2026-09-02).

Paul found Penn Taproom's 4:30-6:00 card sitting above a quote that reads
"4:30 to 6:30 PM". Nothing in 449 tests could see it, because every validator
asked whether a deal was well formed or whether its quote was present in the
source -- never whether the two AGREE.

Building the check turned up three live causes on the shipped board, all of
which produced a window NOBODY ever published.
"""

import importlib.util
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ingest"))

from extract_deals import (  # noqa: E402
    another_branch, days_in, place_names, venue_city, windows_from, HEDGE_RE,
)

_spec = importlib.util.spec_from_file_location(
    "window_quote_check", os.path.join(REPO, "tests", "window_quote_check.py"))
wq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wq)


class AWordWeDoNotKnowReadsAsSilence(unittest.TestCase):
    """And silence about days means DAILY, so a gap in the day vocabulary is
    not a miss -- it is a wrong card. DELCO.today: 'Off the Rail ... has $3
    domestic beers during happy hours weeknights, 4 to 6 PM' shipped Saturday
    and Sunday."""

    def test_weeknights_is_monday_to_friday(self):
        self.assertEqual(days_in("happy hours weeknights, 4 to 6 PM"), {1, 2, 3, 4, 5})

    def test_weeknight_singular_too(self):
        self.assertEqual(days_in("every weeknight"), {1, 2, 3, 4, 5})

    def test_weekdays_is_unchanged(self):
        self.assertEqual(days_in("weekdays from 4 to 6"), {1, 2, 3, 4, 5})

    def test_a_weekend_is_still_a_weekend(self):
        self.assertEqual(days_in("weekend nights"), {6, 7})

    def test_seven_nights_a_week_is_every_day(self):
        # Social Hour reached the right card only by falling THROUGH to the
        # every-day inference -- right answer, no evidence.
        self.assertEqual(days_in("Social Hour | 7 Nights A Week 4:30pm to 6pm"),
                         {1, 2, 3, 4, 5, 6, 7})


class TheGuardForTheNextWordWeDoNotKnow(unittest.TestCase):
    """Two synonyms were each found by a wrong card in public. The third will
    be too, unless a quote we could not read stops inferring seven days."""

    def test_an_unknown_week_word_publishes_no_window(self):
        # Invented on purpose: this is the shape of the next 'weeknights'.
        self.assertEqual(
            windows_from("Happy Hour throughout the trading week, 4 - 6 pm"), [])

    def test_school_nights_publishes_no_window(self):
        self.assertEqual(
            windows_from("Happy Hour on school nights, 4 - 6 pm"), [])

    def test_a_late_night_happy_hour_still_ships(self):
        # 'night' as a modifier on the DEAL is not a limit on the WEEK, and
        # six real cards in the corpus are written this way.
        got = windows_from("Late Night Happy Hour 10pm-11pm!")
        self.assertEqual(sorted({w["dow"] for w in got}), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(got[0]["start"], "22:00")

    def test_a_known_week_word_is_untouched(self):
        got = windows_from("Happy hours weeknights, 4 to 6 PM")
        self.assertEqual(sorted({w["dow"] for w in got}), [1, 2, 3, 4, 5])


class TheOtherBranchOfTheSameBusiness(unittest.TestCase):
    """Spasso Italian Grill's site carries Media's 'MONDAY - FRIDAY 4:00 -
    6:00 PM' and Philadelphia's 'Tuesday - Friday 5-7PM'. Both were pooled
    into the Media licence, the overlap was published, and the Media board
    said 5-6 PM over a quote saying 4:00."""

    PLACES = {"media", "philadelphia", "university city", "glen mills"}

    def hit(self, quote, url="https://x.example/happy-hour"):
        return {"quote": quote, "url": url}

    def test_a_quote_labelled_with_another_town_is_refused(self):
        self.assertTrue(another_branch(
            self.hit("Philadelphia | Happy Hour / Every Tuesday - Friday 5-7PM"),
            "media", self.PLACES))

    def test_the_venues_own_label_is_kept(self):
        self.assertFalse(another_branch(
            self.hit("Media | Happy Hour / Every MONDAY - FRIDAY 4:00 - 6:00 PM"),
            "media", self.PLACES))

    def test_a_district_counts_as_a_branch_label(self):
        # Santucci's North Broad card shipped its University City hours.
        self.assertTrue(another_branch(
            self.hit("University City Happy Hour (21+ only) / Weekdays, 4-6 PM"),
            "philadelphia", self.PLACES))

    def test_a_quote_naming_no_place_is_kept(self):
        self.assertFalse(another_branch(
            self.hit("North Broad Street Happy Hour (21+): / Monday - Friday 4 PM - 7 PM"),
            "philadelphia", self.PLACES))

    def test_a_town_named_deep_in_the_prose_is_not_a_branch_label(self):
        # A branch label opens the line. Buried, it is just a sentence.
        self.assertFalse(another_branch(
            self.hit("Happy Hour 4-6pm, a short drive from Philadelphia"),
            "media", self.PLACES))

    def test_the_url_path_labels_it_too(self):
        self.assertTrue(another_branch(
            self.hit("Happy Hour / Tuesday - Friday 5-7PM",
                     "https://x.example/philadelphia-happy-hour"),
            "media", self.PLACES))

    def test_the_venues_own_town_in_the_url_path_is_kept(self):
        self.assertFalse(another_branch(
            self.hit("Happy Hour! / 04:00 PM - 06:00 PM",
                     "https://x.example/philadelphia-fairmount-pier-bar-happy-hours"),
            "philadelphia", self.PLACES))

    def test_a_national_chains_OTHER_city_is_refused(self):
        # Other Half Brewing's PHILADELPHIA licence shipped Buffalo, New
        # York's happy hour. 'buffalo' is in no Chester County zone, so our own
        # vocabulary had nothing to object with.
        self.assertTrue(another_branch(
            self.hit("OH...Another Happy Hour @ Buffalo / Daily Happy Hour at "
                     "Other Half Buffalo Tuesday-Friday 4pm-6pm",
                     "https://otherhalfbrewing.com/event/clone-ohanother-happy-"
                     "hour-buffalo-2026-09-15/"),
            "philadelphia", self.PLACES))

    def test_the_same_chains_OWN_city_page_is_kept(self):
        self.assertFalse(another_branch(
            self.hit("Philly Happy Hour / Happy Hour 4pm-6pm Monday to Thursday "
                     "in the Philly Taproom!",
                     "https://otherhalfbrewing.com/event/philly-happy-hour/"),
            "philadelphia", self.PLACES))

    def test_an_ordinary_word_that_is_also_a_us_town_is_not_a_branch_label(self):
        # 🛑 A gazetteer was tried here and cost 27 cards to win 2: '/happy-hour/'
        # is refused by one, because Happy, Texas exists.
        for path in ("https://x.example/happy-hour/",
                     "https://x.example/menu/happy-hour-menu",
                     "https://x.example/westchester"):
            self.assertFalse(another_branch(
                self.hit("Happy Hour Monday-Friday 4-6pm", path),
                "west chester", self.PLACES), path)

    def test_a_city_is_read_off_a_plcb_style_address(self):
        self.assertEqual(venue_city("217-219 W State St, Media PA 19063"), "media")
        self.assertEqual(venue_city("1102 Baltimore Pike Suite 101, Glen Mills PA 19342"),
                         "glen mills")

    def test_the_vocabulary_holds_the_parts_of_a_compound_zone_name(self):
        # 'Philadelphia - University City / West' held no entry for the thing
        # a restaurant actually writes on its page.
        self.assertIn("university city", place_names())


class AReviewIsNotTheVenueSpeaking(unittest.TestCase):
    """Pier Bar embeds 'Good happy hour spot (M-F 5-7p) with a cute theme...'
    on its own homepage. None of the first-person hedges matched it, so its
    5-7 was intersected with the bar's own 4-6 into a 5-6 nobody stated."""

    def test_a_third_person_review_is_hedged_out(self):
        self.assertTrue(HEDGE_RE.search(
            "Good happy hour spot (M-F 5-7p) with a cute theme and lots of "
            "nice outdoor shaded seating. If you like the food at Fare"))

    def test_the_venue_stating_its_own_hours_is_not(self):
        self.assertFalse(HEDGE_RE.search("Happy Hour : Monday - Friday from 4-6pm"))
        self.assertTrue(windows_from("Happy Hour : Monday - Friday from 4-6pm"))


class TheCheckItself(unittest.TestCase):
    def deal(self, quote, windows, quotes=None):
        src = {"quote": quote}
        if quotes:
            src["quotes"] = quotes
        return {"windows": windows, "source": src}

    VENUE = {"zone_id": "doylestown", "name": "Penn Taproom"}

    def test_the_card_that_started_this_fails(self):
        got = wq.check_deal(self.VENUE, self.deal(
            "Happy Hour 4:30 to 6:30 PM",
            [{"dow": 1, "start": "16:30", "end": "18:00"}]))
        self.assertEqual(len(got), 1)

    def test_the_same_card_with_the_right_end_passes(self):
        self.assertEqual(wq.check_deal(self.VENUE, self.deal(
            "Happy Hour 4:30 to 6:30 PM",
            [{"dow": 1, "start": "16:30", "end": "18:30"}])), [])

    def test_a_weekend_published_off_a_weeknights_quote_fails(self):
        got = wq.check_deal(self.VENUE, self.deal(
            "$3 domestic beers during happy hours weeknights, 4 to 6 PM",
            [{"dow": d, "start": "16:00", "end": "18:00"} for d in range(1, 8)]))
        self.assertTrue(any("weekdays only" in c for c in got))

    def test_a_quote_naming_both_halves_of_the_week_may_ship_all_seven(self):
        self.assertEqual(wq.check_deal(self.VENUE, self.deal(
            "Monday - Friday 4 PM - 7 PM / Saturday - Sunday 4 PM - 7 PM",
            [{"dow": d, "start": "16:00", "end": "19:00"} for d in range(1, 8)])), [])

    def test_a_price_is_not_a_clock(self):
        # '$6 TITO'S MIXED DRINKS' read as six o'clock, and a quote with no
        # clock in it at all looked like one that disagreed.
        self.assertIsNone(wq.clocks_in("THURSDAY $6 TITO'S MIXED DRINKS $8 MARTINIS"))

    def test_midnight_written_as_12am_is_both_ends_of_the_day(self):
        self.assertIn(24 * 60, wq.clocks_in("Friday - Saturday: 10pm - 12am"))

    def test_until_close_is_not_judged(self):
        self.assertIsNone(wq.clocks_in("Happy Hour 4pm until close"))

    def test_the_whole_evidence_set_is_read_not_just_the_printed_line(self):
        # Bar Bombon's day happy hour and its night one are two lines and one
        # card; judged against either alone the card contradicts itself.
        self.assertEqual(wq.check_deal(self.VENUE, self.deal(
            "Day Happy Hour Specials / Thursday-Friday, 3pm-6pm",
            [{"dow": 5, "start": "15:00", "end": "18:00"},
             {"dow": 6, "start": "21:00", "end": "23:00"}],
            quotes=["Day Happy Hour Specials / Thursday-Friday, 3pm-6pm",
                    "Night Happy Hour Specials / Friday-Saturday, 9pm-11pm"])), [])


if __name__ == "__main__":
    unittest.main()
