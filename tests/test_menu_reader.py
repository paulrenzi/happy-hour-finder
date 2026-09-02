"""The menu reader's grounding rules, and the silent defects they were bought with.

Every case here is a real page that was refused or wrongly accepted before the
rule existed. None of them needs a model: `vet()` is handed a row and a source
document and must decide, so the whole grounding half is testable offline.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ingest"))

import read_menus_llm as rm  # noqa: E402


class ClockSpellings(unittest.TestCase):
    """clock_in() had two defects that each refused real venues in silence."""

    def test_zero_padded_twelve_hour_is_a_real_spelling(self):
        # The Copper Crow's specials calendar prints "04:30 PM - 06:30 PM". The
        # only candidates generated were "16:30" (absent) and "4:30" (refused,
        # because the (?<!\d) lookbehind sees the leading 0), so a real happy
        # hour was refused on every one of the five days it runs.
        self.assertTrue(rm.clock_in("16:30", "happy hour 04:30 pm - 06:30 pm"))
        self.assertTrue(rm.clock_in("18:30", "happy hour 04:30 pm - 06:30 pm"))

    def test_a_stated_meridiem_must_agree(self):
        # Otherwise an opening time of 4:30 AM evidences a 4:30 PM happy hour.
        self.assertFalse(rm.clock_in("16:30", "open 04:30 am - 09:00 am"))
        self.assertTrue(rm.clock_in("04:30", "open 04:30 am - 09:00 am"))

    def test_a_bare_hour_does_not_match_inside_a_longer_time(self):
        # "11" matched INSIDE "11:00 am", and the meridiem test then read the
        # ":" as "no meridiem stated" and accepted it -- so an 11am opening
        # time evidenced an 11pm window.
        self.assertFalse(rm.clock_in("23:00", "11:00 am - 2:00 pm"))
        self.assertTrue(rm.clock_in("11:00", "11:00 am - 2:00 pm"))

    def test_the_spellings_that_already_worked_still_do(self):
        for hhmm, text in (("16:00", "4-6pm"), ("15:00", "3pm-6pm"),
                           ("16:30", "mon-fri 4:30pm-6:30pm"),
                           ("24:00", "til midnight"), ("12:00", "from noon")):
            self.assertTrue(rm.clock_in(hhmm, text), (hhmm, text))


CALENDAR = (
    "Specials\n"
    "Tuesday September 1st\n"
    "Pick 2 for $25! Enjoy two select dishes from a condensed lunch menu for $25.\n"
    "11:30 AM - 02:30 PM\n"
    "Happy Hour (Bars and High Tops ONLY!) - $5 per birria taco | $5 off bottles of wine\n"
    "04:30 PM - 06:30 PM\n"
    "Wednesday September 2nd\n"
    "Happy Hour (Bars and High Tops ONLY!) - $5 off all pizzas | $5 off bottles of wine\n"
    "04:30 PM - 06:30 PM\n"
    "Thursday September 3rd\n"
    "Happy Hour (Bars and High Tops ONLY!) - $5 off all burgers | $5 off bottles of wine\n"
    "04:30 PM - 06:30 PM\n"
)

HH_ROW = {
    "kind": "happy_hour",
    "days": [2],
    "start": "16:30",
    "end": "18:30",
    "heading": "Happy Hour (Bars and High Tops ONLY!)",
    "quote": "Happy Hour (Bars and High Tops ONLY!) - $5 per birria taco | $5 off bottles of wine",
    "items": [{"label": "birria taco", "price": 5, "category": "food",
               "evidence": "$5 per birria taco"}],
}


class SpecialsCalendar(unittest.TestCase):
    """A venue publishing a standing happy hour on a dated events calendar.

    The Copper Crow (Horsham) and Bridget's Steakhouse (Ambler) are the same
    layout, and between them it cost two towns their best card.
    """

    def test_the_happy_hour_is_read(self):
        deal, why = rm.vet(dict(HH_ROW), CALENDAR, "http://x/specials")
        self.assertIsNone(why)
        self.assertEqual(deal["type"], "happy_hour")
        self.assertEqual([w["dow"] for w in deal["windows"]], [2])
        self.assertEqual(deal["windows"][0]["start"], "16:30")
        self.assertEqual(len(deal["items"]), 1)

    def test_the_clock_line_beside_it_is_the_grounding(self):
        deal, _ = rm.vet(dict(HH_ROW), CALENDAR, "http://x/specials")
        self.assertIn("04:30", deal["source"]["clock_quote"])

    def test_the_date_header_above_it_names_the_day(self):
        deal, _ = rm.vet(dict(HH_ROW), CALENDAR, "http://x/specials")
        self.assertIn("tuesday", deal["source"]["day_quote"].lower())

    def test_a_one_off_party_is_still_refused(self):
        # The exemption is the heading REPEATING, which is what makes a page a
        # calendar. A party is announced once.
        once = CALENDAR.replace(
            "Happy Hour (Bars and High Tops ONLY!)", "Halloween Bash", 1)
        row = dict(HH_ROW, heading="Halloween Bash",
                   quote="Halloween Bash - $5 per birria taco | $5 off bottles of wine")
        deal, why = rm.vet(row, once, "http://x/specials")
        self.assertIsNone(deal)
        self.assertIn("DATE", why)

    def test_the_clock_may_not_be_borrowed_from_across_the_page(self):
        # A happy hour must take its hours from beside it, or the opening hours
        # at the top of the page become a nine-hour "happy hour".
        far = ("Open daily 11:00 AM - 10:00 PM\n" + "filler line\n" * 60
               + "Happy Hour (Bars and High Tops ONLY!) - $5 tacos\n") * 3
        row = dict(HH_ROW, days=[2], start="11:00", end="22:00",
                   quote="Happy Hour (Bars and High Tops ONLY!) - $5 tacos",
                   items=[{"label": "tacos", "price": 5, "category": "food",
                           "evidence": "$5 tacos"}])
        deal, why = rm.vet(row, far, "http://x/specials")
        self.assertIsNone(deal)


class HeadingGuard(unittest.TestCase):
    """The guard that cost a $50 prime rib."""

    PRIX = ("WILLIAM PENN INN PRIX FIXE\n"
            "Tuesday through Friday 5:00 - 6:30 pm\n"
            "Roast Prime Rib of Beef $40\n")

    def test_a_prix_fixe_dinner_is_not_a_deal(self):
        row = {"kind": "daily_special", "days": [2, 3, 4, 5],
               "start": "17:00", "end": "18:30",
               "heading": "WILLIAM PENN INN PRIX FIXE",
               "quote": "Tuesday through Friday 5:00 - 6:30 pm",
               "items": [{"label": "Roast Prime Rib of Beef", "price": 40,
                          "category": "food", "evidence": "Roast Prime Rib of Beef $40"}]}
        deal, why = rm.vet(row, self.PRIX, "http://x/dinner.pdf")
        self.assertIsNone(deal)
        self.assertIn("meal service", why)

    def test_a_named_day_special_is_not_refused_by_the_blocklist(self):
        # The list is a blocklist on purpose: a whitelist of deal words refuses
        # "Wing Wednesday", and refusing is the invisible answer, not the safe one.
        src = "Wing Wednesday\nEvery Wednesday 5:00 pm - 8:00 pm\n50 cent wings\n"
        row = {"kind": "daily_special", "days": [3], "start": "17:00", "end": "20:00",
               "heading": "Wing Wednesday",
               "quote": "Every Wednesday 5:00 pm - 8:00 pm",
               "items": []}
        deal, why = rm.vet(row, src, "http://x/specials")
        self.assertIsNone(why, why)
        self.assertEqual(deal["type"], "daily_special")


class Grounding(unittest.TestCase):
    """The model is a reader, not a source."""

    SRC = "Happy Hour\nMonday-Friday 4-6pm\n$5 drafts\n"
    ROW = {"kind": "happy_hour", "days": [1, 2, 3, 4, 5], "start": "16:00",
           "end": "18:00", "heading": "Happy Hour",
           "quote": "Monday-Friday 4-6pm",
           "items": [{"label": "drafts", "price": 5, "category": "draft",
                      "evidence": "$5 drafts"}]}

    def test_a_quote_that_is_not_on_the_page_is_refused(self):
        row = dict(self.ROW, quote="Monday-Sunday 2-8pm")
        self.assertIsNone(rm.vet(row, self.SRC, "u")[0])

    def test_a_heading_that_is_not_on_the_page_is_refused(self):
        row = dict(self.ROW, heading="Sunset Social")
        self.assertIsNone(rm.vet(row, self.SRC, "u")[0])

    def test_an_item_whose_price_is_not_in_its_evidence_is_dropped(self):
        row = dict(self.ROW, items=[{"label": "drafts", "price": 3,
                                     "category": "draft", "evidence": "$5 drafts"}])
        deal, why = rm.vet(row, self.SRC, "u")
        self.assertIsNone(why)
        self.assertEqual(deal["items"], [])

    def test_an_over_four_hour_happy_hour_is_the_opening_hours(self):
        src = "Happy Hours\nMon - Sun: 11:00 AM - 10:00 PM\n"
        row = {"kind": "happy_hour", "days": [1], "start": "11:00", "end": "22:00",
               "heading": "Happy Hours", "quote": "Mon - Sun: 11:00 AM - 10:00 PM",
               "items": []}
        deal, why = rm.vet(row, src, "u")
        self.assertIsNone(deal)
        self.assertIn("OPENING hours", why)


class AChainsEventsCalendarIsEveryTownAtOnce(unittest.TestCase):
    """The West Chester card shipped Pottstown's and Drexel Hill's trivia.

    Artillery Brewing publishes one events page for all its locations, each row
    prefixed with the town it belongs to. Both deals were CORRECTLY GROUNDED --
    those words really are on that page -- and both were the wrong thing, which
    is the failure no grounding check can see. The venue's own town is the only
    discriminator, so the guard is narrow on purpose: a town the licence base
    knows, in the prefix position, that is not ours.
    """

    OURS = "333 Granite Alley, West Chester PA 19380"

    def test_another_locations_row_is_named_and_refused(self):
        self.assertEqual(
            rm.another_towns_row("Pottstown - Trivia Every Wednesday!\n"
                                 "September 2 @ 7:00 pm - 10:00 pm", self.OURS),
            "Pottstown")
        self.assertEqual(
            rm.another_towns_row("Drexel Hill - Quizzo Tuesday", self.OURS),
            "Drexel Hill")

    def test_our_own_towns_row_is_kept(self):
        self.assertIsNone(
            rm.another_towns_row("West Chester - Quizzo Tuesday", self.OURS))

    def test_a_section_label_is_not_a_town(self):
        # "Wings - $5" is the shape the prefix rule must not eat.
        for line in ("Wings - $5 during happy hour",
                     "HAPPY HOUR\nMonday - Friday 3-6pm",
                     "Draft Beer | $5",
                     "Bar Bites: half price"):
            self.assertIsNone(rm.another_towns_row(line, self.OURS), line)

    def test_vet_refuses_the_row_and_says_why(self):
        doc = ("Pottstown - Trivia Every Wednesday!\n"
               "September 2 @ 7:00 pm - 10:00 pm\n$5 pints for participants")
        row = {"kind": "daily_special", "heading": "Pottstown - Trivia Every Wednesday!",
               "quote": "Pottstown - Trivia Every Wednesday!", "days": ["wed"],
               "start": "19:00", "end": "22:00", "items": []}
        deal, why = rm.vet(row, doc, "https://artillerybrewing.com/events/", self.OURS)
        self.assertIsNone(deal)
        self.assertIn("Pottstown", why)

    def test_with_no_address_the_guard_does_not_fire(self):
        # vet() is called without an address by the offline cases above; the
        # guard must be additive, never a new way for those to fail.
        doc = "Pottstown - Trivia Every Wednesday!\n$5 pints 7-10pm Wednesday"
        row = {"kind": "daily_special", "heading": "Pottstown - Trivia Every Wednesday!",
               "quote": "Pottstown - Trivia Every Wednesday!", "days": ["wed"],
               "start": "19:00", "end": "22:00", "items": []}
        _, why = rm.vet(row, doc, "http://x/events")
        self.assertNotIn("Pottstown", why or "")


class NoStrayControlBytes(unittest.TestCase):
    """A literal backspace is what \\b becomes when an edit loses a backslash.

    Inside an r"..." regex it never matches, so the guard it belonged to stops
    existing without erroring. Two were found in this repo on 2026-09-02: one
    in this pass's meridiem check, and one that had been shipping in
    extract_deals.items_in()'s label splitter.
    """

    def test_no_source_file_contains_a_control_byte(self):
        import glob
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bad = []
        for pattern in ("ingest/*.py", "tests/*.py", "scratch/*.py", "web/*.js"):
            for path in glob.glob(os.path.join(repo, pattern)):
                raw = open(path, "rb").read()
                for byte in (8, 11, 12, 0):
                    if bytes([byte]) in raw:
                        bad.append(f"{os.path.basename(path)}: chr({byte})")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
