#!/usr/bin/env python3
"""The events reader's grounding gate: nothing the model says reaches the
queue unless its quote is in the model's own transcript and the shape holds."""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ingest"))

from read_events_venue import ground  # noqa: E402

TODAY, UNTIL = "2026-09-04", "2026-09-18"
TRANSCRIPT = ("Live Acoustic Music every Friday & Saturday from 7 pm - 10 pm. "
              "Friday September 4th - Rhythm & Blondes. Saturday September 5th - Tucker Michaels.")


def read(events, transcript=TRANSCRIPT):
    return {"found": True, "transcript": transcript, "events": events}


class Ground(unittest.TestCase):
    def test_quoted_events_are_kept(self):
        kept, dropped = ground(read([
            {"date": "2026-09-04", "act": "Rhythm & Blondes", "kind": "live_music",
             "start": "19:00", "end": "22:00", "cover_usd": None, "kitchen_open": None,
             "quote": "Friday September 4th - Rhythm & Blondes"},
        ]), TODAY, UNTIL)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])
        self.assertEqual(kept[0]["start"], "19:00")
        self.assertIsNone(kept[0]["cover_usd"])

    def test_an_invented_quote_is_dropped(self):
        kept, dropped = ground(read([
            {"date": "2026-09-11", "act": "The Dead Flowers", "kind": "live_music",
             "quote": "Friday September 11th - The Dead Flowers"},
        ]), TODAY, UNTIL)
        self.assertEqual(kept, [])
        self.assertIn("quote not in transcript", dropped[0])

    def test_quote_match_ignores_whitespace_and_case(self):
        kept, _ = ground(read([
            {"date": "2026-09-05", "act": "Tucker Michaels", "kind": "live_music",
             "quote": "saturday september 5th -  tucker michaels"},
        ]), TODAY, UNTIL)
        self.assertEqual(len(kept), 1)

    def test_outside_the_window_is_dropped(self):
        kept, dropped = ground(read([
            {"date": "2026-10-04", "act": "Rhythm & Blondes", "kind": "live_music",
             "quote": "Rhythm & Blondes"},
            {"date": "2026-09-01", "act": "Rhythm & Blondes", "kind": "live_music",
             "quote": "Rhythm & Blondes"},
        ]), TODAY, UNTIL)
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 2)

    def test_bad_shapes_are_dropped_not_fixed(self):
        kept, dropped = ground(read([
            {"date": "2026-09-05", "act": "Tucker Michaels", "kind": "live_music",
             "start": "7pm", "quote": "Tucker Michaels"},
            {"date": "2026-09-05", "act": "Tucker Michaels", "kind": "rave",
             "quote": "Tucker Michaels"},
            {"date": "2026-09-05", "act": "", "kind": "live_music", "quote": "Tucker Michaels"},
        ]), TODAY, UNTIL)
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 3)

    def test_kitchen_only_when_stated(self):
        kept, _ = ground(read([
            {"date": "2026-09-05", "act": "Tucker Michaels", "kind": "live_music",
             "kitchen_open": "maybe", "quote": "Tucker Michaels"},
        ]), TODAY, UNTIL)
        self.assertIsNone(kept[0]["kitchen_open"])


if __name__ == "__main__":
    unittest.main()
