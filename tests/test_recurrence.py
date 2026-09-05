"""A standing weekly show, told from a one-off by the venue's own words.

PLAYBOOK-NIGHT-OUT.md §15. Every quote below is verbatim from a real read.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ingest"))

from recurrence import collapse_weekly, infers_weekly, repeats_on_one_weekday  # noqa: E402


class InfersWeekly(unittest.TestCase):
    def test_a_rule_with_no_date_is_a_rule(self):
        # Flip and Baileys, Wayne. The model derived 9/10 and 9/17 from this.
        self.assertTrue(infers_weekly("Thursdays 7pm-9pm"))
        self.assertTrue(infers_weekly(
            "Come by from 10pm-12am every friday and buy a $20 cup to enjoy $1 drinks!"))
        self.assertTrue(infers_weekly("TRIVIA WEDNESDAYS"))
        self.assertTrue(infers_weekly("Quizzo Night every Tuesday"))
        self.assertTrue(infers_weekly("Live music Saturday nights"))

    def test_a_printed_date_is_not_a_rule(self):
        # 118 North books named touring acts on named nights. A Saturday show
        # is not a claim that there is one every Saturday.
        self.assertFalse(infers_weekly(
            "Sat Sep 05\nGlam Rock\nCreem Circus + The Sound Minds\nDoors: 7:00 PM"))
        self.assertFalse(infers_weekly("September 11: Joe Miralles"))
        self.assertFalse(infers_weekly("9/7\nMonday 4pm-9pm\nGirl Dinner"))

    def test_both_halves_are_required(self):
        # A weekday word alone is not a rule, and a rule word alone is not one
        # either -- the pair is what carries the meaning.
        self.assertFalse(infers_weekly("Thursday"))
        self.assertFalse(infers_weekly("Doors: 7:00 PM"))
        self.assertFalse(infers_weekly(""))
        self.assertFalse(infers_weekly(None))


class CollapseWeekly(unittest.TestCase):
    def rows(self):
        return [
            {"act": "Music Bingo", "date": "2026-09-10", "quote": "Thursdays 7pm-9pm", "recurs": None},
            {"act": "Music Bingo", "date": "2026-09-17", "quote": "Thursdays 7pm-9pm", "recurs": None},
            {"act": "Joe Miralles", "date": "2026-09-11", "quote": "September 11: Joe Miralles", "recurs": None},
        ]

    def test_the_copies_of_one_rule_collapse_to_one_row(self):
        out = collapse_weekly(self.rows())
        self.assertEqual(len(out), 2)
        bingo = [r for r in out if r["act"] == "Music Bingo"]
        self.assertEqual(len(bingo), 1)
        self.assertEqual(bingo[0]["recurs"], "weekly")
        self.assertEqual(bingo[0]["date"], "2026-09-10", "keeps the FIRST occurrence")

    def test_a_one_off_is_left_exactly_as_it_was(self):
        out = collapse_weekly(self.rows())
        joe = [r for r in out if r["act"] == "Joe Miralles"][0]
        self.assertIsNone(joe["recurs"])
        self.assertEqual(joe["date"], "2026-09-11")

    def test_out_of_order_copies_still_keep_the_earliest_date(self):
        rows = list(reversed(self.rows()))
        bingo = [r for r in collapse_weekly(rows) if r["act"] == "Music Bingo"][0]
        self.assertEqual(bingo["date"], "2026-09-10")

    def test_the_same_act_on_two_weekdays_is_two_rules(self):
        # Saloon 151 runs Live DJ on more than one night. Collapsing on act
        # alone would silently delete a night the bar actually publishes.
        rows = [
            {"act": "Live DJ", "date": "2026-09-11", "quote": "Live DJ every Friday", "recurs": None},
            {"act": "Live DJ", "date": "2026-09-12", "quote": "Live DJ every Saturday", "recurs": None},
        ]
        self.assertEqual(len(collapse_weekly(rows)), 2)

    def test_a_model_declared_weekly_is_honoured_without_inference(self):
        rows = [{"act": "Karaoke", "date": "2026-09-10", "quote": "Doors 8pm", "recurs": "weekly"}]
        self.assertEqual(collapse_weekly(rows)[0]["recurs"], "weekly")


class RepeatsOnOneWeekday(unittest.TestCase):
    """The model's own expansion is evidence, where the quote is too narrow."""

    def test_the_same_act_twice_on_one_weekday_with_no_date_is_a_rule(self):
        # Saloon 151. The "Mondays:" heading is a line above the quote, so
        # quote-only inference sees nothing -- but the model expanded it.
        rows = [
            {"act": "Quizzo", "date": "2026-09-08", "quote": "Quizzo Starts at 7pm", "recurs": None},
            {"act": "Quizzo", "date": "2026-09-15", "quote": "Quizzo Starts at 7pm", "recurs": None},
        ]
        out = collapse_weekly(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["recurs"], "weekly")
        self.assertEqual(out[0]["date"], "2026-09-08")

    def test_a_dated_quote_is_never_promoted_by_repetition(self):
        # A room that books a named act on two Saturdays is not a weekly rule.
        rows = [
            {"act": "Los Straitjackets", "date": "2026-09-05",
             "quote": "Sat Sep 05 Los Straitjackets", "recurs": None},
            {"act": "Los Straitjackets", "date": "2026-09-12",
             "quote": "Sat Sep 12 Los Straitjackets", "recurs": None},
        ]
        self.assertEqual(len(collapse_weekly(rows)), 2)
        self.assertTrue(all(r["recurs"] is None for r in collapse_weekly(rows)))

    def test_one_occurrence_alone_is_not_a_rule(self):
        rows = [{"act": "Quizzo", "date": "2026-09-08", "quote": "Quizzo at 7pm", "recurs": None}]
        self.assertEqual(collapse_weekly(rows)[0]["recurs"], None)

    def test_the_same_act_on_two_different_weekdays_is_not_repetition(self):
        rows = [
            {"act": "Live DJ", "date": "2026-09-11", "quote": "Live DJ 10pm", "recurs": None},
            {"act": "Live DJ", "date": "2026-09-12", "quote": "Live DJ 10pm", "recurs": None},
        ]
        self.assertEqual(repeats_on_one_weekday(rows), set())
        self.assertEqual(len(collapse_weekly(rows)), 2)


if __name__ == "__main__":
    unittest.main()
