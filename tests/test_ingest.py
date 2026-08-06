#!/usr/bin/env python3
"""Validators, decay ladder and geocode parsing.

    python -m unittest discover -s tests -v

These guard the two places bad data reaches users: a deal that should never have
been published (the PA validators) and a deal that is quietly too old to trust
(the decay ladder).
"""

import datetime
import json
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ingest"))

from build_bundles import decay  # noqa: E402
from crawl_sites import candidate_links, quotes, visible_text  # noqa: E402
from discover_sites import plcb_key, site_of, street_core  # noqa: E402
from extract_deals import days_in, items_in, window_in, windows_from  # noqa: E402
from fetch_og_images import inline_images, og_image  # noqa: E402
from fetch_venue_photos import IMG_DIR, photo_dest  # noqa: E402
from geocode_venues import split_address, strip_range, strategies  # noqa: E402
from validate_pa import validate_deal, validate_food_combo_count  # noqa: E402


def deal(**over):
    """A minimal publishable happy hour; override one field per test."""
    base = {
        "type": "happy_hour",
        "windows": [{"dow": 1, "start": "16:00", "end": "18:00"}],
        "items": [{"category": "draft", "label": "drafts", "price_usd": 5.0}],
        "confidence": "likely",
        "source": {"kind": "venue_site", "url": "https://example.com"},
    }
    base.update(over)
    return base


class PaValidators(unittest.TestCase):
    def test_a_plain_happy_hour_passes(self):
        self.assertEqual(validate_deal(deal()), [])

    def test_the_four_hour_daily_cap_is_a_boundary_not_a_range(self):
        exactly_four = deal(windows=[{"dow": 1, "start": "14:00", "end": "18:00"}])
        self.assertEqual(validate_deal(exactly_four), [], "4h exactly is legal")

        over = deal(windows=[{"dow": 1, "start": "14:00", "end": "18:30"}])
        self.assertTrue(any("4h/day" in e for e in validate_deal(over)))

    def test_the_weekly_cap_counts_across_days(self):
        # 7 days x 4h = 28h, over the 24h/week cap even though no single day is.
        week = deal(
            windows=[{"dow": d, "start": "14:00", "end": "18:00"} for d in range(1, 8)]
        )
        errs = validate_deal(week)
        self.assertTrue(any("24h/week" in e for e in errs), errs)

    def test_midnight_is_legal_but_past_midnight_is_not(self):
        # PA allows a discount to run to midnight; 24:00 is how the corpus says so.
        self.assertEqual(validate_deal(deal(windows=[{"dow": 5, "start": "22:00", "end": "24:00"}])), [])

        past = validate_deal(deal(windows=[{"dow": 5, "start": "22:00", "end": "25:00"}]))
        self.assertTrue(any("past midnight" in e for e in past))

        # An end at or before the start is a window that wraps into the morning.
        wrap = validate_deal(deal(windows=[{"dow": 5, "start": "22:00", "end": "02:00"}]))
        self.assertTrue(any("past midnight" in e for e in wrap))

    def test_unlawful_claims_are_refused_whatever_the_source_said(self):
        for claim in ["all you can drink", "bottomless mimosas", "free drink with entree",
                      "2 for 1 wells", "unlimited wings"]:
            errs = validate_deal(deal(items=[{"category": "draft", "label": claim, "price_usd": 5.0}]))
            self.assertTrue(any("unlawful" in e for e in errs), f"{claim!r} should be refused")

    def test_the_daily_special_is_exempt_from_the_four_hour_cap(self):
        # One beverage type may run open-to-close, so an 8h window is fine here.
        all_day = deal(type="daily_special", windows=[{"dow": 2, "start": "11:00", "end": "23:00"}])
        self.assertEqual(validate_deal(all_day), [])

    def test_a_deal_needs_a_time_and_a_source(self):
        self.assertTrue(any("no windows" in e for e in validate_deal(deal(windows=[]))))
        self.assertTrue(any("no source" in e for e in validate_deal(deal(source={}))))

    def test_an_item_with_neither_price_nor_discount_is_rejected(self):
        errs = validate_deal(deal(items=[{"category": "draft", "label": "drafts"}]))
        self.assertTrue(any("neither a price nor a discount" in e for e in errs))

    def test_at_most_two_food_combos_a_day(self):
        combo = deal(type="food_combo", windows=[{"dow": 3, "start": "16:00", "end": "18:00"}])
        self.assertEqual(validate_food_combo_count([combo, combo]), [])
        self.assertTrue(validate_food_combo_count([combo, combo, combo]))


class DecayLadder(unittest.TestCase):
    """A deal never disappears, it demotes -- deleting looks like a bug to the
    user who saw it yesterday. SPEC section 6."""

    TODAY = datetime.date(2026, 8, 1)

    def demote(self, confidence, days_old):
        seen = (self.TODAY - datetime.timedelta(days=days_old)).isoformat()
        return decay(confidence, seen, self.TODAY)

    def test_fresh_stays_put(self):
        self.assertEqual(self.demote("likely", 0), ("likely", 0))

    def test_likely_becomes_unconfirmed_after_45_days(self):
        self.assertEqual(self.demote("likely", 45)[0], "likely", "45 is not yet over 45")
        self.assertEqual(self.demote("likely", 46)[0], "unconfirmed")

    def test_anything_over_120_days_is_hidden(self):
        self.assertEqual(self.demote("likely", 120)[0], "unconfirmed")
        self.assertEqual(self.demote("likely", 121)[0], "hidden")
        self.assertEqual(self.demote("unconfirmed", 121)[0], "hidden")

    def test_operator_verified_and_disputed_do_not_decay(self):
        # An operator confirmation and a user dispute are both standing facts.
        self.assertEqual(self.demote("verified", 300)[0], "verified")
        self.assertEqual(self.demote("disputed", 300)[0], "disputed")


class Geocoding(unittest.TestCase):
    def test_address_splitting(self):
        self.assertEqual(
            split_address("800 Spring Mill Ave, Conshohocken PA 19428"),
            {"street": "800 Spring Mill Ave", "city": "Conshohocken", "state": "PA", "zip": "19428"},
        )
        self.assertIsNone(split_address("nowhere in particular"))

    def test_house_number_ranges_are_reduced_to_the_first_number(self):
        # '30-32 E State St' and '7-15 S High St' both missed until this ran.
        self.assertEqual(strip_range("30-32 E State St"), "30 E State St")
        self.assertEqual(strip_range("7-15 S High St"), "7 S High St")
        self.assertEqual(strip_range("324 W Swedesford Rd"), "324 W Swedesford Rd")

    def test_every_strategy_keeps_the_zip(self):
        # '324 W Swedesford Rd' exists in both 19312 and 19341, thirty miles
        # apart, so a query that drops the ZIP silently returns the wrong town.
        forms = list(strategies("324 W Swedesford Rd, Berwyn PA 19312"))
        self.assertTrue(forms)
        for label, params in forms:
            blob = " ".join(str(v) for v in params.values())
            self.assertIn("19312", blob, f"strategy {label} dropped the ZIP")


class SeedCorpus(unittest.TestCase):
    """The shipped corpus itself, not just the code that checks it."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO, "data", "deals_seed.json"), encoding="utf-8") as fh:
            cls.seed = json.load(fh)
        with open(os.path.join(REPO, "data", "venue_coords.json"), encoding="utf-8") as fh:
            cls.coords = json.load(fh)
        # The coordinate cache covers everything that ships, and since the
        # crawler started feeding the corpus that is the seed plus the
        # machine-extracted venues -- both are published, so both are audited.
        cls.corpus = list(cls.seed["venues"])
        extracted = os.path.join(REPO, "data", "deals_extracted.json")
        if os.path.exists(extracted):
            with open(extracted, encoding="utf-8") as fh:
                cls.corpus += json.load(fh)["venues"]

    def test_every_seeded_deal_passes_the_validators(self):
        for venue in self.seed["venues"]:
            for d in venue["deals"]:
                self.assertEqual(validate_deal(d), [], f"{venue['name']} publishes an invalid deal")

    def test_every_seeded_venue_has_a_coordinate(self):
        # Only the seed is required to be complete. A machine-extracted venue
        # whose OSM element carried no centre still publishes -- it just cannot
        # be ranked by distance, which the build prints a count of.
        for venue in self.seed["venues"]:
            self.assertTrue(venue["id"] in self.coords, f"{venue['name']} was never geocoded")

    def test_no_venue_resolved_outside_the_disc(self):
        for venue in self.corpus:
            at = self.coords.get(venue["id"])
            if at:
                self.assertTrue(39.6 < at["lat"] < 40.6 and -76.0 < at["lng"] < -74.8,
                                f"{venue['name']} resolved outside the 20-mile disc")

    def test_geocode_records_keep_the_address_they_were_asked_for(self):
        # The audit trail that makes a wrong match findable later.
        by_id = {v["id"]: v for v in self.corpus}
        for vid, at in self.coords.items():
            self.assertTrue(vid in by_id, f"{vid}: a coordinate no corpus venue claims")
            self.assertEqual(at["queried"], by_id[vid]["address"],
                             f"{vid}: cached coordinate is for a different address than the seed now lists")


class Zones(unittest.TestCase):
    """Zone membership is hand-maintained data, and venues.csv is gitignored, so
    a typo here is invisible until a whole township silently goes unzoned."""

    @classmethod
    def setUpClass(cls):
        cls.zones = json.load(open(os.path.join(REPO, "data", "zones.json"), encoding="utf-8"))

    def test_every_zone_is_reachable(self):
        for z in self.zones["zones"]:
            self.assertTrue(z.get("municipalities") or z.get("zips"),
                            f"{z['id']} claims no municipality and no ZIP -- nothing can land in it")
            for key in ("id", "name", "anchor"):
                self.assertTrue(z.get(key), f"{z.get('id')} is missing {key}")

    def test_ids_are_unique(self):
        ids = [z["id"] for z in self.zones["zones"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate zone id")

    def test_no_municipality_or_zip_is_claimed_twice(self):
        # seed_plcb takes the first match, so a double claim silently hands the
        # venues to whichever zone happens to be listed first.
        seen_m, seen_z = {}, {}
        for z in self.zones["zones"]:
            for mun, county in z.get("municipalities", []):
                key = (mun.lower(), county.lower())
                self.assertNotIn(key, seen_m,
                                 f"{mun}, {county} is in both {seen_m.get(key)} and {z['id']}")
                seen_m[key] = z["id"]
            for zp in z.get("zips", []):
                self.assertNotIn(zp, seen_z,
                                 f"ZIP {zp} is in both {seen_z.get(zp)} and {z['id']}")
                seen_z[zp] = z["id"]

    def test_municipalities_name_a_county_in_scope(self):
        # A county outside the scope list can never match a kept row.
        scope = set(self.zones["counties_in_scope"])
        for z in self.zones["zones"]:
            for mun, county in z.get("municipalities", []):
                self.assertIn(county, scope, f"{z['id']}: {mun} is in out-of-scope {county}")

    def test_a_zip_zone_is_a_philadelphia_zone(self):
        # ZIPs name zones only inside Philadelphia (SPEC section 2); elsewhere a
        # ZIP straddles the municipal line the zone is actually drawn on.
        for z in self.zones["zones"]:
            for zp in z.get("zips", []):
                self.assertTrue(zp.startswith("191"),
                                f"{z['id']}: {zp} is not a Philadelphia ZIP")


class SiteDiscovery(unittest.TestCase):
    """The OSM join is on address, and a bad address key fails silently -- it
    just yields no match, which is indistinguishable from 'OSM doesn't know it'."""

    def test_the_two_sources_spellings_reduce_to_one_key(self):
        # The PLCB writes 'RIDGE PK', OSM writes 'Ridge Pike'; they are one road.
        self.assertEqual(street_core("W Lancaster Avenue"), street_core("LANCASTER AVE"))
        self.assertEqual(street_core("Ridge Pike"), street_core("W RIDGE PK"))
        self.assertEqual(street_core("MacDade Boulevard"), street_core("MACDADE BLVD"))

    def test_a_street_named_for_a_suffix_survives(self):
        # 'W St Rd' is West Street Road. Popping every suffix word erases it.
        self.assertTrue(street_core("W ST RD"))
        self.assertEqual(street_core("W ST RD"), street_core("West Street Road"))

    def test_a_plain_address_parses(self):
        self.assertEqual(plcb_key("929-931 MACDADE BLVD, COLLINGDALE PA 19023-3720"),
                         ("19023", "929", "macdade"))

    def test_a_plaza_name_does_not_supply_the_house_number(self):
        # 'STORES 15 & 16' precedes the real number; taking the first number
        # keys the venue to a building that does not exist.
        self.assertEqual(
            plcb_key("ROXBORO MARKET SQ SHOPPING CENTER STORES 15 & 16  8919 RIDGE AVE, "
                     "PHILADELPHIA PA 19128"),
            ("19128", "8919", "ridge"))

    def test_an_address_with_no_number_is_refused_not_guessed(self):
        self.assertIsNone(plcb_key("BALTIMORE PIKE, CONCORDVILLE PA 19331"))
        self.assertIsNone(plcb_key("nowhere in particular"))

    def test_a_website_is_only_taken_from_a_url_field(self):
        self.assertEqual(site_of({"website": "https://x.com"}), "https://x.com")
        self.assertEqual(site_of({"contact:website": "https://y.com"}), "https://y.com")
        self.assertIsNone(site_of({"website": "see facebook"}), "not a fetchable URL")
        self.assertIsNone(site_of({"phone": "+1 610-555-0100"}))


class CrawlExtraction(unittest.TestCase):
    """What the crawler keeps becomes the quoted evidence under a published
    deal, so a mangled quote is a claim the venue did not make."""

    def test_entities_and_line_structure_survive(self):
        text = visible_text("<div>HAPPY HOUR</div><p>Monday &#8211; Friday 4pm to 6pm</p>")
        self.assertEqual(text, "HAPPY HOUR\nMonday – Friday 4pm to 6pm")

    def test_script_and_style_bodies_are_not_text(self):
        self.assertEqual(visible_text("<style>.happy hour{}</style><p>Open daily</p>"),
                         "Open daily")

    def test_a_heading_pulls_in_the_window_on_the_next_line(self):
        # 'HAPPY HOUR' alone is not a deal; the times are the deal, and they are
        # routinely a separate element.
        q = quotes("HAPPY HOUR\nMonday - Friday 4pm to 6pm\nunrelated line")
        self.assertTrue(any("4pm to 6pm" in x for x in q), q)

    def test_happy_unqualified_is_not_a_hit(self):
        self.assertEqual(quotes("Book your Happy Birthday party with us"), [])
        self.assertEqual(quotes("We are happy to host your event, 4pm to 6pm"), [])

    def test_only_same_host_pages_are_followed(self):
        html = ('<a href="/happy-hour">Happy Hour</a>'
                '<a href="https://facebook.com/specials">Specials</a>'
                '<a href="/menu.pdf">Menu</a>')
        links = candidate_links(html, "https://bar.example/")
        self.assertEqual(links, ["https://bar.example/happy-hour"])


class PhotoPaths(unittest.TestCase):
    """The photo lane costs money per call, so its paths are pinned before it runs."""

    def test_bytes_land_in_the_directory_the_run_creates(self):
        dest, _rel = photo_dest("coyote-crossing")
        self.assertEqual(os.path.dirname(dest), IMG_DIR,
                         "download writes outside the only directory makedirs creates")

    def test_the_manifest_path_is_relative_to_the_web_root(self):
        # app.js does img.src = photo.file, resolved against web/ -- not the repo.
        dest, rel = photo_dest("coyote-crossing")
        self.assertEqual(rel, "img/venues/coyote-crossing.jpg")
        self.assertEqual(os.path.join(REPO, "web", rel.replace("/", os.sep)), dest)


class DealExtraction(unittest.TestCase):
    """What a regex may and may not conclude from a sentence on a bar's website.

    Rule 2 is that we never render a claim the source didn't make, and every
    test here is a way a parser invents one.
    """

    def test_a_day_range_expands_to_every_day_in_it(self):
        self.assertEqual(days_in("Monday - Friday"), {1, 2, 3, 4, 5})

    def test_a_day_range_may_wrap_through_the_weekend(self):
        # 'Sunday - Friday' is a real six-day happy hour, not a reversed typo.
        self.assertEqual(days_in("Sunday - Friday: 4pm - 6pm"), {7, 1, 2, 3, 4, 5})

    def test_the_start_inherits_the_ends_meridiem(self):
        # '4 - 6 pm' is how it is written on every chalkboard in the state.
        self.assertEqual(window_in("Happy Hour 4 - 6 pm"), ("16:00", "18:00"))

    def test_an_inherited_meridiem_that_inverts_the_window_crosses_noon(self):
        self.assertEqual(window_in("11 - 2 pm"), ("11:00", "14:00"))

    def test_a_window_with_no_meridiem_at_all_is_refused(self):
        # 'Monday - Thursday 4:30 - 6:00' reads as 4:30pm to a person and
        # 4:30am to a parser. Guessing it right most of the time is still
        # publishing a time the venue never wrote.
        self.assertEqual(windows_from("Happy Hour Monday - Thursday 4:30 - 6:00"), [])

    def test_midnight_is_the_end_of_the_day_not_the_start(self):
        self.assertEqual(window_in("Late Night 11pm-12am"), ("23:00", "24:00"))

    def test_days_carry_forward_across_the_crawlers_line_joins(self):
        # The crawler joins lines with ' / ', and a happy-hour block routinely
        # puts the heading, the days and the times on three separate lines.
        got = windows_from("HAPPY HOUR / Sunday - Friday: / 4:30pm - 6:30pm")
        self.assertEqual(len(got), 6)
        self.assertEqual(got[0], {"dow": 1, "start": "16:30", "end": "18:30"})

    def test_days_stated_after_the_time_are_still_paired(self):
        # An event listing writes them last; reading only forwards loses it.
        got = windows_from("Happy Hour / 04:30 PM - 06:30 PM / Friday August 7th")
        self.assertEqual(got, [{"dow": 5, "start": "16:30", "end": "18:30"}])

    def test_a_hedged_chain_page_publishes_nothing_about_this_address(self):
        self.assertEqual(
            windows_from("Happy Hour times vary by location, Monday-Friday 3-6pm"), [])

    def test_a_customer_review_is_not_the_venue_speaking(self):
        self.assertEqual(
            windows_from("I have found my new happy hour spot, Mon-Fri 4-6pm"), [])

    def test_a_price_is_only_kept_when_its_noun_is_recognised(self):
        got = items_in("Sip $8 wines, enjoy $7 bites, $12 parking validation")
        self.assertEqual([(i["category"], i["price_usd"]) for i in got],
                         [("wine", 8.0), ("food", 7.0)])

    def test_an_extracted_deal_still_has_to_pass_the_pa_validators(self):
        # 10am-2:30pm is 4.5h, over the statutory daily cap -- the extractor
        # runs the same validator the build does, while the quote is still
        # attached to say why.
        d = deal(windows=windows_from("Happy Hour Saturday & Sunday: 10am - 2:30pm"))
        self.assertTrue(any("4h/day" in e for e in validate_deal(d)))


class PhotoSourcing(unittest.TestCase):
    """Which image on a venue's page may stand in as a photo of the venue."""

    def test_the_share_image_is_absolutised_against_the_page(self):
        html = '<meta property="og:image" content="/img/bar.jpg">'
        self.assertEqual(og_image(html, "https://bar.example/menu"),
                         "https://bar.example/img/bar.jpg")

    def test_a_vector_logo_is_not_a_photograph(self):
        self.assertIsNone(og_image('<meta name="twitter:image" content="/logo.svg">',
                                   "https://bar.example/"))

    def test_chrome_is_skipped_when_scanning_a_page_for_a_photo(self):
        html = ('<img src="/logo.png"><img src="/spacer.gif">'
                '<img src="/tacos.jpg"><img src="https://x.test/facebook-icon.png">')
        self.assertEqual(inline_images(html, "https://bar.example/"),
                         ["https://bar.example/tacos.jpg"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
