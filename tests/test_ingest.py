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
import unittest.mock
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ingest"))

from build_bundles import CACHE_LINE, decay, shell_digest, sw_cache_name  # noqa: E402
import crawl_sites  # noqa: E402
from crawl_roundups import fresh_enough, mentions, published_date, venue_index  # noqa: E402
from crawl_sites import candidate_links, crawl_one, quotes, registrable, visible_text  # noqa: E402
from discover_places import HAND_DROPPED  # noqa: E402
from discover_sites import collapse_shared, name_core, plcb_key, site_of, street_core  # noqa: E402
import guess_sites  # noqa: E402
from guess_sites import candidates  # noqa: E402
from guess_sites import verify as guess_verify  # noqa: E402
from extract_deals import clauses, days_in, items_in, one_sided, window_in, windows_from  # noqa: E402
from extract_prices_llm import verify  # noqa: E402
from fetch_og_images import asset_allowed, css_images, inline_images, og_image  # noqa: E402
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


class RoundupTier(unittest.TestCase):
    """Paul's call, 2026-08-06: roundups publish in their OWN tier with the
    outlet named, capped at unconfirmed, and nothing older than 4 months is
    ingested at all."""

    TODAY = datetime.date(2026, 8, 6)

    def roundup(self, **over):
        src = {"kind": "roundup", "url": "https://vista.today/x",
               "outlet": "VISTA.today", "published": "2026-06-01"}
        src.update(over.pop("source", {}))
        over.setdefault("confidence", "unconfirmed")
        return deal(source=src, **over)

    def test_a_well_formed_roundup_publishes(self):
        self.assertEqual(validate_deal(self.roundup()), [])

    def test_an_unnamed_outlet_is_rejected(self):
        errs = validate_deal(self.roundup(source={"outlet": ""}))
        self.assertTrue(any("must name who said it" in e for e in errs), errs)

    def test_an_undated_roundup_is_rejected(self):
        errs = validate_deal(self.roundup(source={"published": None}))
        self.assertTrue(any("recency cannot be gated" in e for e in errs), errs)

    def test_the_tier_caps_at_unconfirmed(self):
        # A roundup may read as specifically as a menu; it is still a magazine
        # describing a bar, so it must never present as the bar speaking.
        errs = validate_deal(self.roundup(confidence="likely"))
        self.assertTrue(any("caps at unconfirmed" in e for e in errs), errs)
        errs = validate_deal(self.roundup(confidence="verified"))
        self.assertTrue(any("caps at unconfirmed" in e for e in errs), errs)

    def test_an_unknown_source_kind_is_rejected(self):
        errs = validate_deal(deal(source={"kind": "hearsay", "url": "https://x/"}))
        self.assertTrue(any("unknown source kind" in e for e in errs), errs)

    def test_the_kinds_already_in_the_seed_still_pass(self):
        # aggregator and instagram ship in data/deals_seed.json. A kinds check
        # that forgot them would silently delete published deals on the day it
        # landed, and the venue count would just quietly be smaller.
        for kind in ("venue_site", "aggregator", "instagram"):
            self.assertEqual(validate_deal(deal(source={"kind": kind, "url": "https://x/"})),
                             [], kind)

    def test_the_date_gate_drops_the_october_2024_phoenixville_piece(self):
        # The concrete case that made this a hard gate rather than a demotion.
        self.assertFalse(fresh_enough("2024-10-15", self.TODAY))
        self.assertTrue(fresh_enough("2026-06-01", self.TODAY))
        self.assertFalse(fresh_enough("2026-04-07", self.TODAY), "121 days is outside")
        self.assertTrue(fresh_enough("2026-04-08", self.TODAY), "120 days is inside")

    def test_an_undated_article_is_never_fresh(self):
        # None is a refusal. Defaulting an undated page to "today" would wave
        # the entire archive of every outlet through the gate.
        self.assertFalse(fresh_enough(None, self.TODAY))

    def test_the_publish_date_is_read_from_jsonld_meta_and_prose(self):
        ld = '<script type="application/ld+json">{"@type":"Article",' \
             '"datePublished":"2026-06-01T09:00:00-04:00"}</script>'
        self.assertEqual(published_date(ld), "2026-06-01")
        meta = '<meta property="article:published_time" content="2026-05-02T10:00:00Z">'
        self.assertEqual(published_date(meta), "2026-05-02")
        self.assertEqual(published_date("<p>Published June 3, 2026 by staff</p>"), "2026-06-03")

    def test_a_dateless_page_reports_none_rather_than_guessing(self):
        self.assertIsNone(published_date("<html><body><p>Happy hour picks</p></body></html>"))


class HandCorrectedJoins(unittest.TestCase):
    """Single-claimant mis-joins corrected by hand, pinned so a re-run of the
    address join cannot quietly take them back.

    The join is on ADDRESS, never name, because ~37% of PLCB rows carry a
    corporate shell -- so a name mismatch alone is not evidence of a mis-join.
    These are the ones where the claimed site was independently shown wrong:
    North Italia's entry pointed at locations.bonchon.com, which 404s, while the
    real site carries a happy-hour PDF the crawler reached the moment the URL
    was fixed. That one correction is the whole of King of Prussia's 3 -> 4.
    """

    CORRECTED = {
        "92272": ("NORTH ITALIA", "northitalia.com"),
        # Not a mis-join at all: the same venue, rebranded. The address join was
        # right and the SITE had gone stale, so a live happy hour was shipping
        # under "Gaucho's Prime" -- a name the building stopped using. A stale
        # join looks identical to a wrong one from inside the data.
        "113156": ("CHARKOAL'S PRIME BRAZILIZN STEAKHOUSE", "charkoals.com"),
    }

    # A neighbour in the same plaza claimed the row. Nothing is substituted:
    # absent beats publishing under another business's name. The list lives in
    # the ingest code, not here, because the Places merge has to consult it --
    # it re-added the Residence Inn on its first run, and a hand-made drop that
    # only a test knows about is one an automated step will keep undoing.
    DROPPED = HAND_DROPPED

    def test_a_neighbours_site_stays_dropped(self):
        for lid, why in self.DROPPED.items():
            self.assertNotIn(lid, self.sites, why)

    @classmethod
    def setUpClass(cls):
        cls.sites = json.load(open(os.path.join(REPO, "data", "venue_sites.json"),
                                   encoding="utf-8"))

    def test_the_corrected_sites_are_still_corrected(self):
        for lid, (name, host) in self.CORRECTED.items():
            v = self.sites[lid]
            self.assertEqual(v["name"], name, f"{lid} is no longer the venue it was")
            self.assertIn(host, v["website"], f"{lid} lost its hand-corrected website")

    def test_no_corrected_venue_still_carries_a_stale_osm_name(self):
        # The card's display name comes from osm_name, so a stale OSM node left
        # North Italia's happy hour shipping under "Bonchon Chicken" -- a venue
        # that publishes under another business's name is worse than absent.
        for lid, (name, _host) in self.CORRECTED.items():
            osm = (self.sites[lid].get("osm_name") or "").lower()
            self.assertIn(name.split()[0].lower(), osm,
                          f"{lid} display name disagrees with the venue")


class ServiceWorkerCache(unittest.TestCase):
    """The published shell must evict what the last build left on devices."""

    def test_the_cache_name_matches_the_bundle_that_shipped(self):
        # The name is the ONLY eviction trigger, and data/index.json is precached.
        # A hand-edited constant sat unchanged across four builds, so phones kept
        # serving an older zone list -- King of Prussia read 1 while the server had
        # said 3 for hours, and NOTHING on either side reported a disagreement.
        # build_bundles stamps it now; this fails if a build ships without it.
        #
        # It counts venues WITH A DEAL, not venues. The venue base is 2,900 rows
        # that move only when the PLCB corpus does, so keying on the total would
        # hold one number steady across every deal-only build -- reintroducing
        # the exact staleness this test exists to catch, on the half of the data
        # that actually changes.
        index = json.load(open(os.path.join(REPO, "web", "data", "index.json"),
                               encoding="utf-8"))
        published = sum(z["with_deals"] for z in index["zones"])
        src = open(os.path.join(REPO, "web", "sw.js"), encoding="utf-8").read()
        self.assertIn(f'const CACHE = "{sw_cache_name(index["built_at"], published)}";',
                      src, "web/sw.js was not stamped by the last build_bundles run")

    def test_a_shell_only_change_still_evicts(self):
        # The date and count move only when the CORPUS moves. Without the shell
        # digest, a deploy that changes app.js alone ships the SAME cache name,
        # activate deletes nothing, and installed devices keep the old app.js --
        # the King of Prussia freeze with the corpus in the clear.
        same_corpus = ("2026-08-06", 131)
        self.assertNotEqual(sw_cache_name(*same_corpus, digest="aaaaaaaa"),
                            sw_cache_name(*same_corpus, digest="bbbbbbbb"))

    def test_the_digest_reads_the_shipped_shell(self):
        # An instrument with a hardcoded input answers about the wrong build.
        before = shell_digest()
        path = os.path.join(REPO, "web", "app.js")
        original = open(path, "rb").read()
        try:
            open(path, "wb").write(original + b"\n// probe\n")
            self.assertNotEqual(shell_digest(), before)
        finally:
            open(path, "wb").write(original)
        self.assertEqual(shell_digest(), before)

    def test_a_service_worker_only_change_still_evicts(self):
        # sw.js used to sit OUTSIDE the digest, because hashing the file you are
        # about to stamp has no fixed point. The cost of leaving it out: a deploy
        # that changes only the caching strategy kept the old cache name, so
        # activate() deleted nothing and the new worker served the old precached
        # shell. _sw_source_for_digest blanks the CACHE line before hashing,
        # which breaks the tie without reopening the hole.
        before = shell_digest()
        path = os.path.join(REPO, "web", "sw.js")
        original = open(path, "rb").read()
        try:
            open(path, "wb").write(original + b"\n// probe\n")
            self.assertNotEqual(shell_digest(), before)
        finally:
            open(path, "wb").write(original)
        self.assertEqual(shell_digest(), before)

    def test_stamping_the_service_worker_reaches_a_fixed_point(self):
        # The reason sw.js was excluded in the first place. Writing the name in
        # must not change the name -- otherwise every build restamps forever and
        # every device evicts its whole shell on every deploy.
        path = os.path.join(REPO, "web", "sw.js")
        original = open(path, "rb").read()
        try:
            first = shell_digest()
            src = open(path, encoding="utf-8").read()
            stamped = CACHE_LINE.sub('const CACHE = "hhf-2026-01-01-1-%s";' % first, src)
            open(path, "w", encoding="utf-8", newline="").write(stamped)
            self.assertEqual(shell_digest(), first)
        finally:
            open(path, "wb").write(original)


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
        #
        # Seed last, because where both describe one venue the seed is what
        # build_bundles ships and the extracted copy is dropped. Coyote
        # Crossing is in both, spelled '800 Spring Mill Ave' by hand and '800
        # SPRINGMILL AVE' by the PLCB, and letting the dropped copy shadow the
        # seed made this assert against a record that never reaches a user.
        by_id = {v["id"]: v for v in self.corpus}
        by_id.update({v["id"]: v for v in self.seed["venues"]})
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


def _entry(name, osm_name, osm, site="https://x.test/"):
    return {"name": name, "osm_name": osm_name, "osm": osm, "website": site,
            "zone_id": "king_of_prussia"}


class SharedAddressTenants(unittest.TestCase):
    """A mall, a plaza and an airport terminal are one street address holding
    many businesses, so the address key returns the wrong tenant there."""

    def test_a_neighbours_site_is_dropped_when_several_licensees_share_one_row(self):
        out = {"a": _entry("SHAKE SHACK", "Shake Shack", "node/1"),
               "b": _entry("YARD HOUSE 8371", "Shake Shack", "node/1"),
               "c": _entry("EATALY KOP LLC", "Shake Shack", "node/1")}
        dropped = collapse_shared(out)
        self.assertEqual(sorted(out), ["a"])
        self.assertEqual(len(dropped), 2)

    def test_a_row_claimed_by_one_licensee_is_never_dropped(self):
        # The corporate-shell case: 300-E-6, INC. is Coyote Crossing, and a
        # name mismatch alone is not evidence of a mis-join.
        out = {"a": _entry("300-E-6, INC.", "Coyote Crossing", "node/9")}
        self.assertEqual(collapse_shared(out), [])
        self.assertIn("a", out)

    def test_two_licences_on_one_real_venue_both_survive(self):
        out = {"a": _entry("NEW RIDGE BREWING CO.", "New Ridge Brewing", "way/4"),
               "b": _entry("NEW RIDGE BREWING CO", "New Ridge Brewing", "way/4")}
        self.assertEqual(collapse_shared(out), [])
        self.assertEqual(sorted(out), ["a", "b"])


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

    def test_a_chain_brand_url_answers_only_when_nothing_else_does(self):
        # brand:website is the chain's page, not this location's.
        self.assertEqual(site_of({"brand:website": "https://chain.com"}),
                         "https://chain.com")
        self.assertEqual(
            site_of({"website": "https://this-one.com", "brand:website": "https://chain.com"}),
            "https://this-one.com")

    def test_the_name_key_strips_the_corporate_and_category_noise(self):
        # 'ALEKSANDAR LLC' and OSM's 'Restaurant Aleksandar' are one venue.
        self.assertEqual(name_core("ALEKSANDAR LLC"), name_core("Restaurant Aleksandar"))
        self.assertEqual(name_core("THE GREAT AMERICAN PUB"), name_core("Great American Pub"))

    def test_the_name_key_does_not_collapse_two_different_bars(self):
        self.assertNotEqual(name_core("Dawson Street Pub"), name_core("Cresson Inn"))
        # ...but it DOES collapse the two Iron Hills, which is why the join may
        # only use it when the name is unique within one locality on both sides.
        self.assertEqual(name_core("IRON HILL BREWERY"), name_core("Iron Hill Brewery"))


class GuessedSites(unittest.TestCase):
    """A guessed domain is attached to a real licensee, so the proof gate is the
    only thing standing between a hunch and a wrong website on a published card."""

    def test_a_shell_or_bare_address_yields_no_guess(self):
        self.assertEqual(candidates("4326 MAIN STREET HOLDCO, LLC"), [])
        self.assertEqual(candidates("THE PUB"), [])

    def test_a_real_name_yields_its_run_together_domain(self):
        self.assertIn("dawsonstreetpub", candidates("DAWSON STREET PUB"))
        self.assertIn("cressoninn", candidates("CRESSON-INN"))
        # The corporate tail is not part of the domain.
        self.assertIn("newridgebrewing", candidates("NEW RIDGE BREWING CO."))

    def test_a_page_must_both_name_and_place_the_venue(self):
        page = "Cresson Inn -- your neighborhood bar in Philadelphia since 1933"
        self.assertTrue(guess_verify(page, ["cresson"], ["philadelphia"]))
        # Names it, but places it somewhere else entirely.
        self.assertIsNone(guess_verify(page, ["cresson"], ["phoenixville"]))
        # Places it, but is a different business.
        self.assertIsNone(guess_verify(page, ["dawson", "street"], ["philadelphia"]))

    def test_a_parked_page_echoing_its_own_domain_is_refused(self):
        parked = "cressoninn.com -- this domain is for sale. Philadelphia. Cresson Inn."
        self.assertIsNone(guess_verify(parked, ["cresson"], ["philadelphia"]))

    def test_a_possessive_on_the_sign_still_matches_the_licensee(self):
        # clean_name drops the apostrophe from 'CREEDS SEAFOOD & STEAKS', so a
        # page writing "Creed's" was refused for not naming the venue it is.
        # Both sides have to be read the same way; three King of Prussia
        # licensees were failing on this alone, seed URL already in hand.
        page = "Creed's Seafood & Steaks, King of Prussia's steakhouse since 1982"
        self.assertTrue(guess_verify(page, ["creeds", "seafood", "steaks"],
                                     ["king of prussia"]))
        self.assertTrue(guess_verify("Morton's The Steakhouse, King of Prussia",
                                     ["mortons"], ["king of prussia"]))

    def test_coming_soon_is_a_placeholder_only_on_a_placeholder_page(self):
        # A trading venue writes 'coming soon' about next month's release.
        # Bowen Arrow Winery names four wines that way and was thrown out as a
        # parked domain; what makes a placeholder is that it is nearly all the
        # page has, not the phrase.
        stub = "Bowen Arrow Winery. Phoenixville. Launching soon!"
        self.assertIsNone(guess_verify(stub, ["bowen", "arrow"], ["phoenixville"]))
        real = ("Bowen Arrow Winery, Phoenixville. " + "Tasting room open Friday "
                "through Sunday on our 48-acre farm. " * 40 + " Coming soon: Zweigelt.")
        self.assertTrue(guess_verify(real, ["bowen", "arrow"], ["phoenixville"]))

    def test_a_store_number_is_not_part_of_the_name_to_prove(self):
        # The operator's own store number rides in the PLCB row. Requiring it
        # on the page made those licensees unprovable by construction.
        self.assertEqual(guess_sites.clean_name("SEASONS 52 #4510"), "seasons 52")
        self.assertEqual(guess_sites.clean_name("YARD HOUSE 8371"), "yard house")
        self.assertEqual(guess_sites.clean_name("RED LOBSTER #778"), "red lobster")
        # The numbers that ARE the name survive.
        self.assertEqual(guess_sites.clean_name("STABLE 12 BREWING CO"), "stable 12 brewing")
        self.assertEqual(guess_sites.clean_name("CATCH 101"), "catch 101")

    def test_a_seed_may_name_a_shells_trade_name_without_bypassing_proof(self):
        # 'COLD RIVER LLC' at 822 Fayette St is the StoneRose and no page of
        # theirs will ever say 'cold river'. The trade name is what the page
        # must then show -- it is a different question, not a weaker one.
        row = {"name": "COLD RIVER LLC", "municipality": "Conshohocken",
               "address": "822 FAYETTE ST, CONSHOHOCKEN PA 19428-1709", "zip": "19428"}
        words, place = guess_sites.proof_tokens(row, "The StoneRose")
        self.assertIn("stonerose", words)
        page = "The StoneRose, 822 Fayette Street, Conshohocken"
        self.assertTrue(guess_verify(page, words, place))
        # A neighbour on the same street is still refused.
        self.assertIsNone(guess_verify("Guppy's Good Times, Conshohocken", words, place))


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

    def test_the_hours_beat_the_price_line_into_the_quote(self):
        # Pepperoncini publishes its window in plain text and was dropped for
        # stating no schedule: the two context slots went to 'mon - fri' and
        # '$2 OFF' while '4p - 6p' sat one line further down, unrecognised as a
        # time at all. This was the largest single loss in the corpus.
        page = "\n".join(["Happy Hour", "in the bar area", "mon - fri", "4p - 6p",
                          "$2 OFF", "Our Draft Beer Selection", "$7 Wine"])
        q = quotes(page)[0]
        self.assertIn("4p - 6p", q)
        self.assertIn("mon - fri", q)
        # Page order, so the days still read before the hours.
        self.assertLess(q.index("mon - fri"), q.index("4p - 6p"))

    def test_a_match_that_already_has_context_pulls_in_nothing(self):
        # Reaching further down the page to find hours costs more than it wins:
        # Fogo de Chao's '$6 Beers' line then acquired the dining room's
        # 'Mon - Thu 3:00 PM - 9:30 PM', which is opening hours, not a happy
        # hour, and it fails the four-hour cap -- so a venue that had been
        # publishing correctly stopped. The block ends where it always ended.
        page = "\n".join(["Bar Fogo features $6 Beers and $10 Cocktails",
                          "Mon - Thu 3:00 PM - 9:30 PM",
                          "Fri 3:00 PM - 10:30 PM"])
        self.assertEqual(quotes(page), ["Bar Fogo features $6 Beers and $10 Cocktails"])

    def test_two_windows_under_one_heading_both_survive(self):
        # BOTLD states a weekday window and a weekend one on consecutive lines;
        # preferring times must not mean keeping only the first of them.
        page = "\n".join(["Happy Hour at the Cocktail Bar",
                          "Wednesday - Friday: 4pm - 6pm",
                          "Saturday & Sunday: 2pm - 4pm"])
        q = quotes(page)[0]
        self.assertIn("4pm - 6pm", q)
        self.assertIn("2pm - 4pm", q)

    def test_happy_unqualified_is_not_a_hit(self):
        self.assertEqual(quotes("Book your Happy Birthday party with us"), [])
        self.assertEqual(quotes("We are happy to host your event, 4pm to 6pm"), [])

    def test_only_same_host_pages_are_followed(self):
        html = ('<a href="/happy-hour">Happy Hour</a>'
                '<a href="https://facebook.com/specials">Specials</a>'
                '<a href="/menu-photo.jpg">Menu</a>')
        links = candidate_links(html, "https://bar.example/")
        self.assertEqual(links, ["https://bar.example/happy-hour"])

    def test_a_chains_specials_page_on_a_sibling_host_is_followed(self):
        # locations.pjspub.com holds the location; www.pjspub.com holds the
        # deals. An exact-netloc test dropped exactly the page we want.
        html = ('<a href="https://www.pjspub.com/specials">Specials</a>'
                '<a href="https://facebook.com/pjs-specials">Follow us</a>')
        links = candidate_links(
            html, "https://locations.pjspub.com/pa/conshohocken/200-ridge-pike")
        self.assertEqual(links, ["https://www.pjspub.com/specials"])

    def test_robots_is_fetched_under_a_deadline(self):
        # RobotFileParser.read() passes no timeout, so a host that accepts the
        # connection and never answers stalls the run forever -- one did, for
        # ten minutes, and from outside it looked exactly like slow progress.
        # What is pinned here is that a deadline is passed at all.
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["timeout"] = timeout
            raise OSError("timed out")

        with unittest.mock.patch("crawl_sites.urllib.request.urlopen", fake_urlopen):
            self.assertIsNone(crawl_sites.robots_for("https://slow.example", {}))
        self.assertEqual(seen["timeout"], crawl_sites.TIMEOUT)

    def test_a_robots_that_forbids_everyone_is_still_obeyed(self):
        # An unreachable robots.txt is not a ban, but a 403 on it is: that is
        # the host answering, and read() treated it that way too.
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 403, "no", {}, None)

        with unittest.mock.patch("crawl_sites.urllib.request.urlopen", fake_urlopen), \
                unittest.mock.patch("crawl_sites.time.sleep"):
            cache = {}
            self.assertFalse(crawl_sites.allowed("https://walled.example/menu", cache))
            # Retried once before believing it: a 403 is also what a WAF hands
            # anything that is not a browser.
            self.assertEqual(len(calls), 2)
            # ...and the refusal says which of the two it was. 210 of 886
            # venues were recorded as "robots.txt disallows"; re-checking the
            # ones in the three target towns, every independent venue among
            # them served a robots.txt that allows us outright, and a handoff
            # had already carried "robots.txt disallows us" forward as a fact
            # about four King of Prussia bars that in fact crawl fine.
            self.assertIn("unreadable (403)",
                          crawl_sites.refusal("https://walled.example/menu", cache))

    def test_a_real_disallow_directive_is_not_reported_as_unreadable(self):
        def fake_urlopen(req, timeout=None):
            return unittest.mock.MagicMock(
                __enter__=lambda s: unittest.mock.Mock(
                    read=lambda n: b"User-agent: *\nDisallow: /"),
                __exit__=lambda *a: False)

        with unittest.mock.patch("crawl_sites.urllib.request.urlopen", fake_urlopen):
            cache = {}
            self.assertFalse(crawl_sites.allowed("https://shut.example/menu", cache))
            self.assertEqual(crawl_sites.refusal("https://shut.example/menu", cache),
                             "robots.txt disallows")

    def test_a_pdf_happy_hour_menu_is_a_candidate_link(self):
        # Some venues publish the deal ONLY as a PDF; excluding it by extension
        # dropped the one page that named their happy hour.
        html = ('<a href="/menus/happy-hour.pdf">Happy Hour Menu</a>'
                '<a href="/logo-drink.png">drink</a>')
        links = candidate_links(html, "https://bar.example/")
        self.assertIn("https://bar.example/menus/happy-hour.pdf", links)
        self.assertNotIn("https://bar.example/logo-drink.png", links)

    def test_a_scanned_pdf_yields_no_text_rather_than_a_guess(self):
        # No extractable text must read as 'published nothing here', never as an
        # invitation to infer a deal from a filename.
        self.assertEqual(crawl_sites.pdf_text(b"not a pdf at all"), "")

    def test_sitemap_finds_a_happy_hour_page_nothing_links_to(self):
        body = ("<urlset><url><loc>https://bar.example/about</loc></url>"
                "<url><loc>https://bar.example/happy-hour</loc></url></urlset>")

        class R:
            status_code = 200
            headers = {"content-type": "application/xml"}
            text = body

        session = unittest.mock.Mock()
        session.get.return_value = R()
        with unittest.mock.patch.object(crawl_sites, "allowed", lambda u, c: True):
            found = crawl_sites.sitemap_links(session, "https://bar.example/", {})
        self.assertEqual(found, ["https://bar.example/happy-hour"])

    def test_menu_links_no_longer_suppress_the_sitemap(self):
        # The old rule consulted the sitemap only when a page linked NOTHING.
        # The commoner shape is a page that links three menus and no happy
        # hour: City Works' King of Prussia page offers a food menu, a second
        # food menu and a charity event, so the whole page budget went on
        # entrees while /happy-hour sat in the sitemap unread.
        home = ('<a href="/food-menu">Menu</a><a href="/events">Events</a>')
        sitemap = ("<urlset><url><loc>https://bar.example/happy-hour</loc>"
                   "</url></urlset>")

        def get(url, **kw):
            r = unittest.mock.Mock(status_code=200)
            if url.endswith("sitemap.xml"):
                r.headers = {"content-type": "application/xml"}
                r.text = sitemap
            else:
                r.headers = {"content-type": "text/html; charset=utf-8"}
                r.text = home if url == "https://bar.example/" else "Happy Hour 4pm - 6pm"
            return r

        session = unittest.mock.Mock(get=get)
        venue = {"website": "https://bar.example/"}
        with unittest.mock.patch.object(crawl_sites, "allowed", lambda u, c: True), \
                unittest.mock.patch.object(crawl_sites, "DELAY", 0):
            pages, hits = crawl_one(session, venue, {})
        fetched = [p["url"] for p in pages]
        self.assertIn("https://bar.example/happy-hour", fetched)
        # The linked menus are still crawled -- this tops up, it does not replace.
        self.assertIn("https://bar.example/food-menu", fetched)
        self.assertTrue(hits)

    def test_registrable_domain_ignores_subdomains_and_ports(self):
        self.assertEqual(registrable("locations.pjspub.com"), "pjspub.com")
        self.assertEqual(registrable("www.pjspub.com:443"), "pjspub.com")
        self.assertEqual(registrable("pjspub.com"), "pjspub.com")


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

    def test_a_venue_id_never_keeps_another_branchs_coordinate(self):
        # A venue id is name + city, so two Santucci's in Philadelphia collide
        # and which one holds the bare slug can change between runs. The cache
        # write was guarded on absence alone, so the slug changed hands while
        # the coordinate did not -- a pin several miles from the bar, with
        # nothing on the page to show it. Every osm_site coordinate must name
        # the address of the venue currently holding the id.
        coords = json.load(open(os.path.join(REPO, "data", "venue_coords.json"),
                                encoding="utf-8"))
        extracted = json.load(open(os.path.join(REPO, "data", "deals_extracted.json"),
                                   encoding="utf-8"))
        for v in extracted["venues"]:
            c = coords.get(v["id"])
            if c and c.get("matched_by") == "osm_site":
                self.assertEqual(
                    c["queried"], v["address"],
                    f"{v['id']}: coordinate was looked up for a different address")

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

    def test_a_single_letter_meridiem_is_the_same_claim_as_pm(self):
        # A bar writes '4p - 6p' about as often as '4pm - 6pm'.
        self.assertEqual(window_in("mon - fri 4p - 6p"), ("16:00", "18:00"))
        self.assertEqual(window_in("Happy Hour 11a - 2p"), ("11:00", "14:00"))
        # It must still end on a word boundary, or a quantity becomes a window.
        self.assertIsNone(window_in("buy 4 - 6 pizzas"))
        self.assertIsNone(window_in("seats 5 - 9 people"))

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

    def test_a_hero_painted_as_a_css_background_is_still_a_photo(self):
        # Several of these sites have no <img> at all -- the shot of the dining
        # room is a background-image on a div.
        html = ('<style>.hero{background-image:url("/img/room.jpg")}'
                '.logo{background:url(/logo.png)}</style>')
        self.assertEqual(css_images(html, "https://bar.example/"),
                         ["https://bar.example/img/room.jpg"])

    def test_an_inline_data_uri_is_not_fetched_as_a_photo(self):
        html = '<div style="background-image:url(data:image/png;base64,AAAA)"></div>'
        self.assertEqual(css_images(html, "https://bar.example/"), [])

    def test_an_escaped_ampersand_is_decoded_before_the_url_is_used(self):
        # These are image *proxy* URLs carrying their target in query params, so
        # a literal '&amp;' makes the proxy read a parameter called 'amp;w'.
        html = '<img src="/_next/image?url=%2Fbar.webp&amp;w=3840&amp;q=75">'
        self.assertEqual(inline_images(html, "https://bar.example/"),
                         ["https://bar.example/_next/image?url=%2Fbar.webp&w=3840&q=75"])

    def test_an_escaped_share_image_url_is_decoded_too(self):
        html = '<meta property="og:image" content="https://cdn.test/a.jpg?w=1&amp;h=2">'
        self.assertEqual(og_image(html, "https://bar.example/"),
                         "https://cdn.test/a.jpg?w=1&h=2")

    def test_the_sites_own_robots_still_governs_its_own_images(self):
        robots = {"https://bar.example": _Robots(False)}
        self.assertFalse(asset_allowed("https://bar.example/photos/a.jpg",
                                       "https://bar.example/", robots))

    def test_a_builders_cdn_does_not_veto_the_venues_own_share_image(self):
        # The venue's site said we may read the page, and the page names this
        # image as its own picture; the CDN's robots.txt is about crawling the
        # CDN, and it must not be able to hide a bar from its own listing.
        robots = {"https://static.wixstatic.test": _Robots(False)}
        self.assertTrue(asset_allowed("https://static.wixstatic.test/media/a.jpg",
                                      "https://bar.example/", robots))


class _Robots:
    """Stand-in for the parsed robots.txt crawl_sites caches per host."""

    def __init__(self, verdict):
        self.verdict = verdict

    def can_fetch(self, _ua, _url):
        return self.verdict


class PriceExtraction(unittest.TestCase):
    """What the LLM price pass is allowed to put on a card.

    The model is a reader, not a source: every one of these is about the price
    being present in the venue's own sentence, because that check -- not the
    model's confidence -- is what makes the pass safe to publish.
    """

    QUOTE = "Happy Hour / $5 drafts and half-price wings / Mon - Fri 4 - 6 pm"

    def item(self, **kw):
        base = {"category": "draft", "label": "drafts", "price_usd": 5.0,
                "evidence": "$5 drafts"}
        base.update(kw)
        return base

    def test_a_price_written_in_the_quote_is_kept(self):
        clean, why = verify(self.item(), self.QUOTE)
        self.assertIsNone(why)
        self.assertEqual(clean, {"category": "draft", "label": "drafts", "price_usd": 5.0})

    def test_evidence_that_is_not_in_the_quote_is_refused(self):
        _, why = verify(self.item(evidence="$5 house cocktails"), self.QUOTE)
        self.assertIn("not in the quote", why)

    def test_a_price_the_evidence_does_not_state_is_refused(self):
        # The span is real but the number is not in it -- which is exactly what
        # a plausible-sounding invented price looks like.
        _, why = verify(self.item(price_usd=4.0), self.QUOTE)
        self.assertIn("not written in the evidence", why)

    def test_line_breaks_in_the_quote_do_not_defeat_the_check(self):
        clean, why = verify(self.item(), "Happy Hour\n\n$5   drafts\nMon - Fri")
        self.assertIsNone(why)
        self.assertEqual(clean["price_usd"], 5.0)

    def test_half_price_is_read_as_a_discount(self):
        clean, why = verify(self.item(category="food", label="wings", price_usd=None,
                                      discount_pct=50, evidence="half-price wings"),
                            self.QUOTE)
        self.assertIsNone(why)
        self.assertEqual(clean, {"category": "food", "label": "wings", "discount_pct": 50.0})

    def test_an_item_needs_exactly_one_of_price_or_discount(self):
        _, why = verify(self.item(discount_pct=50), self.QUOTE)
        self.assertIn("exactly one", why)
        _, why = verify(self.item(price_usd=None), self.QUOTE)
        self.assertIn("exactly one", why)

    def test_an_unknown_category_is_refused(self):
        # Categories drive the food/drink filters, so an invented one would file
        # a bar under a tab it does not belong in.
        _, why = verify(self.item(category="dessert"), self.QUOTE)
        self.assertIn("category", why)

    def test_an_unlawful_claim_never_becomes_an_item(self):
        _, why = verify(self.item(label="bottomless drafts",
                                  evidence="$5 drafts"), self.QUOTE)
        self.assertIn("unlawful", why)

    def test_a_label_the_size_of_a_sentence_is_refused(self):
        _, why = verify(self.item(label="drafts all day every day at both of our bars"),
                        self.QUOTE)
        self.assertEqual(why, "label length")

    def test_an_item_with_no_evidence_is_refused(self):
        _, why = verify(self.item(evidence=""), self.QUOTE)
        self.assertEqual(why, "no evidence")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ForbiddenToOneClient(unittest.TestCase):
    """A 403 to requests is not a 403 to us.

    Founding Farmers, Stable 12 and 16 other hosts answered 403 to
    requests/urllib3 and 200 to urllib for the same URL and the same UA.
    """

    def _session(self, status):
        r = unittest.mock.Mock()
        r.status_code = status
        r.headers = {"content-type": "text/html"}
        r.text = "<html>from requests</html>"
        s = unittest.mock.Mock()
        s.get.return_value = r
        return s

    def test_a_403_from_requests_is_retried_with_the_other_client(self):
        plain = crawl_sites._Plain(
            200, {"content-type": "text/html; charset=utf-8"},
            b"<html>from urllib</html>")
        with unittest.mock.patch.object(crawl_sites, "urllib_get",
                                        return_value=plain) as ug:
            body, err = crawl_sites.get(self._session(403), "https://x.test/")
        ug.assert_called_once()
        self.assertIsNone(err)
        self.assertIn("from urllib", body)

    def test_a_200_is_never_refetched(self):
        with unittest.mock.patch.object(crawl_sites, "urllib_get") as ug:
            body, err = crawl_sites.get(self._session(200), "https://x.test/")
        ug.assert_not_called()
        self.assertIn("from requests", body)

    def test_the_fallbacks_headers_answer_to_a_lowercase_lookup(self):
        """A real fetch recorded as '200 ?' because the dict was case-sensitive."""
        plain = crawl_sites._Plain(200, {"content-type": "text/html"}, b"<p>hi</p>")
        with unittest.mock.patch.object(crawl_sites, "urllib_get",
                                        return_value=plain):
            body, err = crawl_sites.get(self._session(403), "https://x.test/")
        self.assertIsNone(err, "content-type lookup must not miss on case")

    def test_a_failing_fallback_keeps_the_original_refusal(self):
        with unittest.mock.patch.object(crawl_sites, "urllib_get",
                                        side_effect=OSError("nope")):
            body, err = crawl_sites.get(self._session(403), "https://x.test/")
        self.assertIsNone(body)
        self.assertTrue(err.startswith("403"))


class VenueBase(unittest.TestCase):
    """The layer the board now rests on: every licensed venue, keyed on its LID.

    The old bundle shipped only deal-bearing venues, so King of Prussia showed 6
    cards against 59 real bars and there was no way for a person to see -- let
    alone correct -- the 53 that were missing. These guard the properties that
    make the base a venue list rather than a second deal list.
    """

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO, "data", "venue_base.json"), encoding="utf-8") as fh:
            cls.base = json.load(fh)
        with open(os.path.join(REPO, "web", "data", "index.json"), encoding="utf-8") as fh:
            cls.index = json.load(fh)

    def test_every_entry_is_keyed_on_its_own_lid(self):
        for lid, v in self.base.items():
            self.assertEqual(lid, v["lid"], "the key and the record disagree")

    def test_a_warehouse_licence_is_not_a_venue(self):
        # Brewery Storage is a permit to keep beer in a building, not to serve
        # it. A card for one is an invitation to drive to a warehouse.
        for v in self.base.values():
            self.assertNotEqual(v["license_type"], "Brewery Storage")

    def test_no_two_venues_claim_the_same_premises(self):
        # One bar routinely holds several licences -- the Sheraton Valley Forge
        # is two Hotel (Liquor) rows at one address -- and a card per LICENCE
        # shows the same bar twice.
        claimed = {}
        for lid, v in self.base.items():
            for other in v.get("also_lids", []):
                self.assertNotIn(other, self.base,
                                 f"{other} was collapsed into {lid} but still ships")
                self.assertNotIn(other, claimed,
                                 f"{other} was collapsed into two venues at once")
                claimed[other] = lid

    def test_a_name_is_never_a_bare_legal_entity(self):
        # The PLCB ships the LICENSEE: `SCREWBALLS LLC`. A card whose only
        # content is a name cannot afford to print the paperwork.
        for v in self.base.values():
            self.assertFalse(v["name"].upper().endswith((" LLC", " INC", " INC.", " LP")),
                             f"{v['lid']} shows a legal entity: {v['name']}")
            self.assertTrue(v["name"].strip(), f"{v['lid']} has no name at all")

    def test_the_index_counts_venues_and_the_ones_we_can_answer_for(self):
        # "King of Prussia (6 of 59)". Shipping only one of these numbers is
        # what made the board read as either empty or complete; it is neither.
        for z in self.index["zones"]:
            self.assertIn("with_deals", z)
            self.assertLessEqual(z["with_deals"], z["venues"])
            self.assertGreater(z["venues"], 0)

    def test_a_zone_ships_its_deals_and_its_base_as_separate_files(self):
        # The split is a load-time decision: boot fetches every zone's deals
        # (169 venues) and the 2,900-venue base only for the zone you pick.
        for z in self.index["zones"]:
            deals_path = os.path.join(REPO, "web", "data", f"zone-{z['id']}.json")
            rest_path = os.path.join(REPO, "web", "data", f"venues-{z['id']}.json")
            for path in (deals_path, rest_path):
                self.assertTrue(os.path.exists(path), f"{path} was not built")
            with open(deals_path, encoding="utf-8") as fh:
                dealful = json.load(fh)["venues"]
            with open(rest_path, encoding="utf-8") as fh:
                rest = json.load(fh)["venues"]
            self.assertEqual(len(dealful), z["with_deals"])
            self.assertEqual(len(dealful) + len(rest), z["venues"])
            self.assertTrue(all(v["deals"] for v in dealful),
                            f"zone-{z['id']}.json carries a venue with no deal")
            self.assertTrue(all(not v["deals"] for v in rest),
                            f"venues-{z['id']}.json carries a deal that boot never loads")

    def test_the_boot_payload_stays_small(self):
        # Every zone's deals are fetched on load. The venue base is a megabyte
        # and must never drift back into that path -- the whole point of the
        # split is that "what's on near me" does not cost a full corpus.
        boot = sum(os.path.getsize(os.path.join(REPO, "web", "data", f"zone-{z['id']}.json"))
                   for z in self.index["zones"])
        self.assertLess(boot, 400_000, "the boot payload has grown a venue base again")

    def test_every_shipped_venue_can_be_identified_in_a_submission(self):
        # The ask on a no-hours card quotes the LID back to us. A card that
        # cannot name itself produces a report nobody can act on.
        for z in self.index["zones"]:
            with open(os.path.join(REPO, "web", "data", f"venues-{z['id']}.json"),
                      encoding="utf-8") as fh:
                for v in json.load(fh)["venues"]:
                    self.assertTrue(v.get("lid"), f"{v['id']} ships with no LID")
                    self.assertEqual(v["id"], v["lid"])
                    self.assertTrue(v.get("address"))

    def test_a_deal_venue_keeps_the_slug_its_old_links_were_shared_with(self):
        # The board is keyed on LIDs now. #v=iron-hill-media was a real shared
        # link and must still open Iron Hill.
        for z in self.index["zones"]:
            with open(os.path.join(REPO, "web", "data", f"zone-{z['id']}.json"),
                      encoding="utf-8") as fh:
                for v in json.load(fh)["venues"]:
                    self.assertTrue(v.get("slug"), f"{v['id']} dropped its legacy id")


class PrettyName(unittest.TestCase):
    """An ALL-CAPS licensee is the only thing most cards have to show."""

    def test_it_recases_without_breaking_an_apostrophe(self):
        from build_venue_base import pretty_name
        self.assertEqual(pretty_name("OHAGANS BAR & RESTAURANT"), "Ohagans Bar & Restaurant")
        # str.title() gives "Tommy'S", which looks like a bug in the one place
        # the card has nothing else to show.
        self.assertEqual(pretty_name("TOMMY'S TAVERN + TAP"), "Tommy's Tavern + Tap")

    def test_it_drops_the_legal_entity(self):
        from build_venue_base import pretty_name
        self.assertEqual(pretty_name("SCREWBALLS LLC"), "Screwballs")
        self.assertEqual(pretty_name("KOP FONDUE INC"), "KOP Fondue")

    def test_a_name_that_is_already_mixed_case_is_left_alone(self):
        # A trade name from Places or OSM is already how the sign reads.
        from build_venue_base import pretty_name
        self.assertEqual(pretty_name("Peppers By Amedeo's"), "Peppers By Amedeo's")

    def test_it_never_returns_an_empty_name(self):
        # Stripping the suffix off a name that is ONLY a suffix would leave a
        # card with no title at all.
        from build_venue_base import pretty_name
        self.assertEqual(pretty_name("LLC"), "LLC")


class TwoSchedulesOnOneLine(unittest.TestCase):
    """One segment, two schedules -- the bug that put a 5pm window on a Sunday.

    'Mon-Fri from 5-7PM & Sun-Thu from 10PM-12PM' was read as ONE schedule:
    days_in() unioned every day either clause named and window_in() took only
    the FIRST range, so Dave & Buster's published a Sunday happy hour at five
    that actually starts at ten. It affected 22 of 170 published venues, and a
    card on the wrong day still looks like a correct card.
    """

    def dows(self, quote):
        """{(start, end): {dow, ...}} -- the schedule as published."""
        out = {}
        for w in windows_from(quote):
            out.setdefault((w["start"], w["end"]), set()).add(w["dow"])
        return out

    def test_each_clause_keeps_its_own_times(self):
        got = self.dows("Happy Hour available Monday-Friday 4-6 pm "
                        "and Sunday-Thursday 10pm-12am at bar area only.")
        self.assertEqual(got[("16:00", "18:00")], {1, 2, 3, 4, 5})
        self.assertEqual(got[("22:00", "24:00")], {7, 1, 2, 3, 4})

    def test_sunday_no_longer_inherits_the_weekday_window(self):
        got = self.dows("Available Mon–Fri from 5–7PM & Sun–Thu from 10PM–12PM.*")
        self.assertNotIn(7, got.get(("17:00", "19:00"), set()),
                         "Sunday took the Mon-Fri window it is not part of")

    def test_a_weekend_clause_keeps_its_earlier_start(self):
        got = self.dows("Tuesday-Friday: 4-7pm | Saturday & Sunday: 3-6pm")
        self.assertEqual(got[("16:00", "19:00")], {2, 3, 4, 5})
        self.assertIn(7, got[("15:00", "18:00")])
        self.assertNotIn(7, got[("16:00", "19:00")])

    def test_one_schedule_naming_two_days_is_not_split(self):
        # The separator only splits when a DAY follows it, so 'Monday & Friday'
        # stays one schedule rather than becoming two.
        self.assertEqual(self.dows("Monday & Friday 4-6pm"), {("16:00", "18:00"): {1, 5}})

    def test_days_on_both_sides_of_a_time_are_refused(self):
        # 'Sunday-Thursday, 5pm-7pm Friday' is two schedules sharing a line, and
        # reading it forwards hands Sun-Thu the window that belongs to Friday.
        self.assertFalse(one_sided("Sunday-Thursday, 5pm-7pm Friday"))
        self.assertTrue(one_sided("Mon-Fri 4-6pm"))
        self.assertTrue(one_sided("4-6pm | Friday"))

    def test_a_days_last_line_with_two_clauses_states_nothing(self):
        # Forsythia writes the days AFTER the time: '5pm-8pm | Sunday-Thursday,
        # 5pm-7pm Friday'. Splitting before a day name cuts between a time and
        # the days it belongs to, so the pieces come out with days on both
        # sides -- and the forward read would hand Sun-Thu the Friday window.
        # Refusing costs a venue that was previously correct; it now shows as a
        # card asking to be filled in, which is the honest form of not knowing.
        quote = ("Happy Hour - Bar Only - 5pm-8pm | Sunday-Thursday, "
                 "5pm-7pm Friday (No HH during special events)")
        self.assertEqual(windows_from(quote), [])

    def test_an_unsplittable_segment_states_nothing(self):
        # No window is a better answer than a guessed one.
        self.assertIsNone(clauses("open 5pm-2am with Happy Hour 10pm-11pm"))
        self.assertEqual(clauses("Mon-Fri 4-6pm"), ["Mon-Fri 4-6pm"])

    def test_a_refused_segment_does_not_leak_its_days_forward(self):
        # The carry-forward is what makes multi-line blocks work; after a
        # segment we could not read, those days would pair with the wrong time.
        # Here 'Mon-Fri' is named in a segment holding two unseparable ranges,
        # so it must not be handed the 9pm window on the next line.
        self.assertEqual(
            windows_from("Mon-Fri lunch 11-2pm and dinner 5-9pm / 9pm - 11pm"), [])
