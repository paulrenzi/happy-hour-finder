"""The page reader may propose a WINDOW, and these are the limits on that.

Paul approved the shape on 2026-09-02: verbatim span, verified in code,
converted by the existing deterministic parser. Each test below pins one half
of that sentence, because the value of the pass is entirely in what it REFUSES.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "ingest"))

from extract_deals import windows_from  # noqa: E402
import read_windows_llm as R  # noqa: E402

PAGE = ("BLUE BELL INN\nHAPPY HOUR\nMonday - Friday 4 - 6pm | Bar Area Only\n"
        "Oysters 2 each\nLate night tues-fri from 9 to 11\n")


class SpanMustBeTheVenuesOwnWords(unittest.TestCase):
    def test_a_span_the_page_really_contains_is_kept(self):
        span, why = R.check("Monday - Friday 4 - 6pm", PAGE)
        self.assertIsNone(why)
        self.assertEqual(windows_from(span),
                         [{"dow": d, "start": "16:00", "end": "18:00"}
                          for d in range(1, 6)])

    def test_a_span_the_page_does_not_contain_is_refused(self):
        # The model tidying "4 - 6pm" into "4:00 PM - 6:00 PM" is the exact
        # failure this pass is built to catch: a plausible, correct-looking
        # time that the venue never wrote.
        self.assertEqual(R.check("Monday - Friday 4:00 PM - 6:00 PM", PAGE)[1],
                         "evidence not in the page")

    def test_whitespace_does_not_defeat_the_check(self):
        # The crawler joins lines; a span copied across a line break is still
        # the venue's own words.
        self.assertIsNone(R.check("HAPPY HOUR Monday - Friday 4 - 6pm", PAGE)[1])

    def test_a_span_longer_than_a_sentence_is_refused(self):
        self.assertIn("too long", R.check("x" * (R.MAX_SPAN + 1) + PAGE, PAGE)[1])

    def test_an_empty_or_junk_span_is_refused(self):
        self.assertEqual(R.check("", PAGE)[1], "no evidence")
        self.assertEqual(R.check(None, PAGE)[1], "no evidence")


class TheParserStillDecides(unittest.TestCase):
    """The model proposes evidence; windows_from() alone reads a time."""

    def test_no_meridiem_is_still_refused_even_though_the_page_wrote_it(self):
        # Cornerstone Bistro, 2026-09-02: "tues-fri from 3:30-5:30" is really
        # on the page and the span passes every check above. The deterministic
        # parser declines it because nothing says pm, and that refusal is the
        # whole reason this pass is safe to ship.
        self.assertEqual(R.check("tues-fri from 9 to 11", PAGE)[1],
                         "parser reads no window from the span")

    def test_a_start_with_no_end_is_refused(self):
        # Bonefish Grill: "Happy Hour starts at 3:30pm daily." A card renders
        # `Live until ${w.end}` and there is no end here to render.
        page = "Happy Hour starts at 3:30pm daily."
        self.assertEqual(R.check(page, page)[1],
                         "parser reads no window from the span")


class OnlyTheHoleClassIsEligible(unittest.TestCase):
    def test_a_venue_that_already_has_a_window_is_never_sent(self):
        # Eligibility is computed by running the real parser over the real
        # quotes, not by reading a count out of a report. A venue we already
        # hold a window for costs a call to re-learn what we have.
        needy = R.needy_lids()
        self.assertTrue(needy)
        import json
        from extract_deals import HITS, SITES, one_per_osm
        hits = json.load(open(HITS, encoding="utf-8"))
        sites = json.load(open(SITES, encoding="utf-8"))
        for lid, v in one_per_osm(hits, sites):
            if str(lid) in needy:
                self.assertFalse(any(windows_from(h["quote"]) for h in v["hits"]),
                                 f"{lid} already has a window and is eligible")


if __name__ == "__main__":
    unittest.main()
