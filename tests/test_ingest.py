#!/usr/bin/env python3
"""Validators, decay ladder and geocode parsing.

    python -m unittest discover -s tests -v

These guard the two places bad data reaches users: a deal that should never have
been published (the PA validators) and a deal that is quietly too old to trust
(the decay ladder).
"""

import collections
import csv
import datetime
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "ingest"))

from build_bundles import (CACHE_LINE, collapse_name_collisions, decay,  # noqa: E402
                           norm_name, shell_digest, sw_cache_name)
import build_bundles  # noqa: E402
import audit_rendered_artifacts  # noqa: E402
import crawl_sites  # noqa: E402
import extract_deals  # noqa: E402
import fetch_venue_photos  # noqa: E402
import exclusions  # noqa: E402
import report_holes  # noqa: E402
import read_pages_llm  # noqa: E402
from crawl_roundups import (address_keys, fresh_enough, mentions,  # noqa: E402
                            published_date, quote_names_another_door, venue_index)
from crawl_sites import (candidate_links, crawl_one, hh_sections,  # noqa: E402
                         reached_nothing,
                         item_beside, menu_images, quotes, registrable,
                         text_lines, visible_text)
from discover_places import HAND_DROPPED  # noqa: E402
from review_photos import merge_mode, superseded  # noqa: E402
from discover_sites import collapse_shared, name_core, plcb_key, site_of, street_core  # noqa: E402
import guess_sites  # noqa: E402
from guess_sites import candidates  # noqa: E402
from guess_sites import verify as guess_verify  # noqa: E402
import extract_deals  # noqa: E402
from extract_deals import (  # noqa: E402
    clauses,
    days_in,
    dedupe,
    items_in,
    lawful_days,
    one_sided,
    refused_source_urls,
    window_in,
    windows_from,
)
import extract_prices_llm  # noqa: E402
from extract_prices_llm import verify  # noqa: E402
from fetch_og_images import asset_allowed, css_images, inline_images, og_image  # noqa: E402
from fetch_venue_photos import (  # noqa: E402
    IMG_DIR, absorbed_lids, name_agrees, photo_dest,
)
from geocode_venues import split_address, strip_range, strategies  # noqa: E402
from validate_pa import (rules_for, state_of, validate_deal,  # noqa: E402
                         validate_food_combo_count)


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


class RenderedArtifactAudit(unittest.TestCase):
    """The visual audit inventories artifacts; it does not trust filenames."""

    def test_opaque_pdf_and_iframe_are_reader_candidates(self):
        pdf = {"url": "https://cdn.example/assets/7142", "tag": "a"}
        pdf["kind"] = audit_rendered_artifacts.url_kind(pdf["url"], pdf["tag"])
        frame = {"url": "https://order.example/widget/abc", "tag": "iframe"}
        frame["kind"] = audit_rendered_artifacts.url_kind(frame["url"], frame["tag"])
        self.assertEqual(pdf["kind"], "link")
        self.assertTrue(audit_rendered_artifacts.candidate(frame))
        # A generic opaque link is not silently promoted; the browser's
        # response content-type turns an actual PDF into a document work item.
        self.assertFalse(audit_rendered_artifacts.candidate(pdf))

    def test_every_previously_read_page_is_audit_scope(self):
        hits = {
            "1": {"pages": [{"url": "https://x.example/", "result": "ok, 0 quote(s)"},
                              {"url": "https://x.example/menu", "result": "404 text/html"}]},
            "2": {"pages": [{"url": "https://y.example/", "result": "rendered: 3 lines -> 80"}]},
        }
        sites = {"1": {"zone_id": "z"}, "2": {"zone_id": "other"}}
        self.assertEqual(audit_rendered_artifacts.page_urls(hits, None, "z", sites),
                         [("1", "https://x.example/")])

    def test_a_visible_opaque_image_on_a_happy_hour_page_is_read(self):
        asset = {"url": "https://cdn.example/uploads/918273", "tag": "img",
                 "kind": "image", "visible": True, "page_happy_hour_path": True}
        self.assertTrue(audit_rendered_artifacts.candidate(asset))

    def test_an_img_endpoint_without_a_filename_is_an_image(self):
        self.assertEqual(
            audit_rendered_artifacts.url_kind("https://bar.example/assets/uuid?w=560", "img"),
            "image")

    def test_responsive_variants_are_one_visual_work_item(self):
        from extract_menu_images import image_key
        self.assertEqual(image_key("https://x.example/menu-300x150.jpg"),
                         image_key("https://x.example/menu.jpg"))
        self.assertEqual(image_key("https://x.example/opaque?w=80&dpr=1"),
                         image_key("https://x.example/opaque?w=240&dpr=3"))


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


class OfflineFallback(unittest.TestCase):
    """A dropped request must cost that request, never the whole page."""

    def _sw(self):
        return open(os.path.join(REPO, "web", "sw.js"), encoding="utf-8").read()

    def _app(self):
        return open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()

    def test_only_a_navigation_falls_back_to_the_shell(self):
        # The worker used to answer ANY uncached miss with index.html. A phone
        # that dropped one data/zone-*.json got HTML back, r.json() threw, and
        # boot() died before drawing a single control -- a fully styled page
        # frozen on "Loading..." with empty filters. Seen on a real iPhone.
        sw = self._sw()
        self.assertIn('e.request.mode === "navigate"', sw)
        hit = sw.index('caches.match("index.html")')
        guard = sw.index('e.request.mode === "navigate"')
        self.assertLess(guard, hit, "the shell fallback is not gated on navigation")

    def test_the_board_does_not_load_all_or_nothing(self):
        # Promise.all over 38 zone bundles rejected the entire board when any
        # one of them failed. loadZoneDeals catches per zone and reports what is
        # missing instead.
        app = self._app()
        self.assertNotIn("index.zones.map((z) => fetch(", app)
        self.assertIn("async function loadZoneDeals", app)
        self.assertIn("noteMissingZones", app)

    def test_the_controls_are_drawn_before_the_bundles(self):
        # The difference between "loading" and "broken": the filters come from
        # the index alone and need no bundle at all.
        app = self._app()
        boot = app[app.index("async function boot()"):]
        self.assertLess(
            boot.index("buildControls()"),
            boot.index("loadZoneDeals(index.zones)"),
            "buildControls must not wait on the zone bundles",
        )

    def test_a_failed_boot_says_so(self):
        app = self._app()
        self.assertIn("boot().catch(", app)


class SubmitNameIndex(unittest.TestCase):
    """The file the submit picker resolves a typed name against.

    Without it the picker can only see what the app has already fetched -- 169
    venues with hours plus whichever town was opened -- so it answers "no match"
    about venues we have held all along, and a missing route reads exactly like
    a missing record. These assert the index covers what the bundles cover, so a
    build cannot quietly ship a picker that is blind to most of the corpus.
    """

    @classmethod
    def setUpClass(cls):
        data = os.path.join(REPO, "web", "data")
        with open(os.path.join(data, "name-index.json"), encoding="utf-8") as fh:
            cls.index = json.load(fh)
        with open(os.path.join(data, "lid-zone.json"), encoding="utf-8") as fh:
            cls.lid_zone = json.load(fh)

    def test_it_holds_every_venue_the_bundles_ship(self):
        # Measured against the SHIPPED bundles -- the artifact a reader actually
        # gets -- not against the index's own length, which would only prove the
        # index equals itself.
        #
        # Keyed on each venue's primary licence ID, deliberately. lid-zone.json
        # also carries `also_lids`: a venue holding two licences. Those resolve
        # to a venue that IS indexed, and listing it twice under two licence
        # numbers would hand the submitter a choice with no answer.
        shipped = set()
        data = os.path.join(REPO, "web", "data")
        for name in os.listdir(data):
            if not (name.startswith("venues-") or name.startswith("zone-")):
                continue
            with open(os.path.join(data, name), encoding="utf-8") as fh:
                for venue in json.load(fh)["venues"]:
                    shipped.add(str(venue["lid"]))

        self.assertGreater(len(shipped), 2000, "the bundles did not load")
        indexed = {row[0] for row in self.index["venues"]}
        missing = shipped - indexed
        self.assertEqual(missing, set(),
                         f"{len(missing)} venue(s) cannot be found by name in the "
                         f"submit picker, e.g. {sorted(missing)[:5]}")

    def test_a_second_licence_does_not_offer_the_same_bar_twice(self):
        indexed = {row[0] for row in self.index["venues"]}
        unresolvable = {lid for lid in self.lid_zone if lid not in indexed}
        aliases = set()
        data = os.path.join(REPO, "web", "data")
        for name in os.listdir(data):
            if not (name.startswith("venues-") or name.startswith("zone-")):
                continue
            with open(os.path.join(data, name), encoding="utf-8") as fh:
                for venue in json.load(fh)["venues"]:
                    aliases.update(str(a) for a in (venue.get("also_lids") or []))
        self.assertTrue(
            unresolvable <= aliases,
            f"a LID the site can route to is absent from the picker and is not a "
            f"second licence: {sorted(unresolvable - aliases)[:5]}")

    def test_every_row_can_be_told_apart_on_screen(self):
        # A LID, a name, and something a human can use to choose between two
        # bars with the same name. A row missing any of those is a row that
        # attaches a menu to the wrong venue with nothing on the card to show it.
        for lid, name, address, zone in self.index["venues"]:
            self.assertTrue(lid and name.strip(), f"unusable row: {lid!r} {name!r}")
            self.assertTrue(address.strip() or zone,
                            f"{name!r} ({lid}) offers nothing to tell it apart")

    def test_the_zone_of_every_row_has_a_readable_name(self):
        names = self.index["zone_names"]
        for row in self.index["venues"]:
            self.assertIn(row[3], names,
                          f"{row[1]!r} sits in zone {row[3]!r}, which has no name "
                          "to show the submitter")


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

    # The market, as boxes. The first is the 20-mile disc around King of
    # Prussia; the second is northern Delaware, added 2026-09-02 and NOT a
    # widening of the first -- Middletown DE sits below the disc's southern
    # edge, and a single box big enough for both would swallow half of
    # Maryland.
    #
    # 🔑 This is the only check in the repo that looks at where a venue
    # actually IS, and it earned that on its first Delaware run: a Places text
    # search for "brewery in Hockessin, Delaware" returned Crooked Hammock
    # Brewery in LEWES, ninety miles south on the ocean, plus sixteen more from
    # Rehoboth, Dover and Smyrna. Every one is genuinely in Delaware, which is
    # all the seeder's state test asked -- Places widens a query it cannot
    # satisfy locally, and a small state is a small enough haystack to succeed.
    MARKET_BOXES = [
        ((39.6, 40.6), (-76.0, -74.8)),      # King of Prussia, 20 miles
        ((39.35, 39.92), (-75.90, -75.35)),  # northern Delaware + MOT
    ]

    def test_no_venue_resolved_outside_the_market(self):
        for venue in self.corpus:
            at = self.coords.get(venue["id"])
            if at:
                self.assertTrue(
                    any(lo < at["lat"] < hi and wlo < at["lng"] < whi
                        for (lo, hi), (wlo, whi) in self.MARKET_BOXES),
                    f"{venue['name']} resolved outside every market box")

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
        # A Delaware zone claims no municipality and no ZIP, on purpose: there
        # is no PLCB export to match against, so its rows arrive from
        # data/venues_de.csv already carrying their zone_id. The requirement is
        # the same one -- something can land in it -- asked of the file that
        # actually feeds it.
        de_zones = collections.Counter()
        de_csv = os.path.join(REPO, "data", "venues_de.csv")
        if os.path.exists(de_csv):
            with open(de_csv, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    de_zones[row["zone_id"]] += 1
        for z in self.zones["zones"]:
            if z.get("state") == "DE":
                self.assertTrue(de_zones[z["id"]],
                                f"{z['id']} is a DE zone with no rows in venues_de.csv "
                                f"-- run ingest/seed_places_de.py")
            else:
                self.assertTrue(z.get("municipalities") or z.get("zips"),
                                f"{z['id']} claims no municipality and no ZIP "
                                f"-- nothing can land in it")
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
            pages, hits, _ = crawl_one(session, venue, {})
        fetched = [p["url"] for p in pages]
        self.assertIn("https://bar.example/happy-hour", fetched)
        # The linked menus are still crawled -- this tops up, it does not replace.
        self.assertIn("https://bar.example/food-menu", fetched)
        self.assertTrue(hits)

    def test_a_menu_pdf_one_hop_past_the_happy_hour_page_is_reached(self):
        # Black Powder Tavern. We had their HOURS -- read straight off their
        # happy-hour page -- and no menu, because the PDF holding the items and
        # prices is linked from that page rather than the homepage, one hop
        # further in than the crawler went. The venue then looked covered,
        # because it had a card.
        pages_by_url = {
            "https://bpt.example/": '<a href="/happy-hour/">Happy Hour</a>',
            "https://bpt.example/happy-hour/":
                "Happy Hour Monday - Friday 4:00 p.m. to 6:00 p.m."
                '<a href="/uploads/HH.pdf">View our Happy Hour menu</a>',
        }

        def get(url, **kw):
            r = unittest.mock.Mock(status_code=200)
            if url.endswith(".pdf"):
                r.headers = {"content-type": "application/pdf"}
                r.content = b"%PDF-fake"
                return r
            if url.endswith("sitemap.xml"):
                r.status_code = 404
                r.headers = {"content-type": "text/html"}
                r.text = ""
                return r
            r.headers = {"content-type": "text/html; charset=utf-8"}
            r.text = pages_by_url.get(url, "")
            return r

        session = unittest.mock.Mock(get=get)
        menu = ("Served Monday - Friday 4:00 p.m. - 6:00 p.m.\n"
                "CAJUN NACHOS $8\nDRAFT BEERS $6")
        with unittest.mock.patch.object(crawl_sites, "allowed", lambda u, c: True), \
                unittest.mock.patch.object(crawl_sites, "DELAY", 0), \
                unittest.mock.patch.object(crawl_sites, "pdf_text", lambda blob: menu):
            pages, hits, _ = crawl_one(session, {"website": "https://bpt.example/"}, {})

        self.assertIn("https://bpt.example/uploads/HH.pdf", [p["url"] for p in pages])
        quoted = " | ".join(h["quote"] for h in hits)
        self.assertIn("CAJUN NACHOS $8", quoted)
        self.assertIn("DRAFT BEERS $6", quoted)

    def test_the_menu_pdf_does_not_cost_the_page_budget(self):
        # Going one level deeper on the SAME budget just means missing something
        # else, which is the trade PAGE_CAP was sized against. The four HTML
        # fetches every venue used to get are still four.
        home = ('<a href="/happy-hour/">Happy Hour</a><a href="/menu">Menu</a>'
                '<a href="/specials">Specials</a><a href="/drinks">Drinks</a>')

        def get(url, **kw):
            r = unittest.mock.Mock(status_code=200)
            if url.endswith(".pdf"):
                r.headers = {"content-type": "application/pdf"}
                r.content = b"%PDF-fake"
                return r
            r.headers = {"content-type": "text/html; charset=utf-8"}
            r.text = (home if url == "https://bar.example/"
                      else '<a href="/uploads/HH.pdf">Happy Hour Menu</a>')
            return r

        session = unittest.mock.Mock(get=get)
        with unittest.mock.patch.object(crawl_sites, "allowed", lambda u, c: True), \
                unittest.mock.patch.object(crawl_sites, "DELAY", 0), \
                unittest.mock.patch.object(crawl_sites, "pdf_text", lambda b: "WINGS $9"):
            pages, _, _ = crawl_one(session, {"website": "https://bar.example/"}, {})

        urls = [p["url"] for p in pages]
        html_pages = [u for u in urls if not u.endswith(".pdf")]
        self.assertEqual(len(html_pages), crawl_sites.PAGE_CAP, html_pages)
        self.assertLessEqual(len([u for u in urls if u.endswith(".pdf")]),
                             crawl_sites.DOC_CAP)

    def test_a_priced_menu_line_counts_only_inside_a_linked_menu(self):
        # 'CAJUN NACHOS $8' names no deal word, so DEAL_RE will never match it --
        # and widening DEAL_RE would let every dinner entree on every site
        # through. The looser rule is scoped to the document the venue itself
        # called its happy hour.
        page = "CAJUN NACHOS $8\nFILET MIGNON $44"
        self.assertEqual(quotes(page), [])
        self.assertIn("CAJUN NACHOS $8", quotes(page, menu_doc=True))

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
        got = windows_from("Happy Hour / 04:30 PM - 06:30 PM / Friday")
        self.assertEqual(got, [{"dow": 5, "start": "16:30", "end": "18:30"}])

    def test_a_dated_event_is_one_evening_and_never_a_weekly_window(self):
        # 🛑 REVERSED 2026-09-02, and the old expectation is in the line above
        # with its date taken off. This used to assert that "Friday August 7th"
        # published a window every Friday. It does not: that is ONE Friday, and
        # a card claiming a standing weekly happy hour off it is a claim the
        # venue never made and is stale within the week.
        #
        # Braeloch Brewing (Kennett Square) is the case that exposed it. Its
        # whole site is an events calendar -- 'Happy Hour / Fri, Sep 4 /
        # 2pm-6pm', 'Happy Hour / Sat, Sep 19 / 6pm-9pm', seven of them, every
        # one a real party and none a weekly schedule. Read as weekdays, three
        # different Fridays were then INTERSECTED into a Friday 5-6pm the
        # brewery has never once run.
        for dated in ("Happy Hour / Sat, Sep 19 / 6pm-9pm",
                      "Fri, Sep 4 Happy Hour 2pm-6pm",
                      "Happy Hour / 04:30 PM - 06:30 PM / Friday August 7th",
                      "Happy Hour 4-6pm on 9/19"):
            self.assertEqual(windows_from(dated), [], dated)

    def test_an_explicit_day_range_beats_the_word_daily_in_one_clause(self):
        # "Daily Happy Hour at Other Half Buffalo Tuesday-Friday 4pm-6pm" is
        # one clause making both claims, and 'daily' won -- so the card said
        # seven days over a quote that says four.
        self.assertEqual(
            sorted(extract_deals.days_in(
                "Daily Happy Hour at Other Half Tuesday-Friday 4pm-6pm")),
            [2, 3, 4, 5])

    def test_daily_still_wins_when_no_range_disputes_it(self):
        self.assertEqual(sorted(extract_deals.days_in("Happy Hour daily 4-6pm")),
                         [1, 2, 3, 4, 5, 6, 7])

    def test_N_dated_entries_at_ONE_clock_is_a_schedule(self):
        """An events-calendar CMS is how a lot of bars publish, and refusing it
        whole cost The Pullman a real card. The discriminator is the CLOCK."""
        def hit(q):
            return {"url": "https://x.example/events", "quote": q}
        pullman = [hit("Happy Hour / 04:30 PM - 06:30 PM / Wednesday September 2nd"),
                   hit("Happy Hour / 04:30 PM - 06:30 PM / Thursday September 3rd"),
                   hit("Happy Hour / 04:30 PM - 06:30 PM / Friday September 4th")]
        got, quotes, urls = extract_deals.recurring_windows(pullman)
        self.assertEqual(sorted(w["dow"] for w in got), [3, 4, 5])
        self.assertEqual({(w["start"], w["end"]) for w in got}, {("16:30", "18:30")})
        self.assertEqual(len(quotes), 3)

    def test_two_dates_is_a_coincidence_not_a_schedule(self):
        def hit(q):
            return {"url": "https://x.example/events", "quote": q}
        got, _q, _u = extract_deals.recurring_windows(
            [hit("Happy Hour / Sat, Sep 5 / 6pm-9pm"),
             hit("Happy Hour / Sat, Sep 19 / 6pm-9pm")])
        self.assertEqual(got, [])

    def test_a_calendar_of_DIFFERENT_clocks_publishes_only_what_repeats(self):
        # Braeloch Brewing: 2-6 once, 6-9 twice, 5-8 four times. Only the
        # Friday 5-8 is a weekly happy hour, and only it ships.
        def hit(q):
            return {"url": "https://x.example/events", "quote": q}
        got, _q, _u = extract_deals.recurring_windows([
            hit("Fri, Sep 4 Happy Hour 2pm-6pm"),
            hit("Happy Hour / Sat, Sep 5 / 6pm-9pm"),
            hit("Happy Hour / Fri, Sep 11 / 5pm-8pm"),
            hit("Happy Hour / Sat, Sep 19 / 6pm-9pm"),
            hit("Happy Hour / Fri, Sep 25 / 5pm-8pm"),
            hit("Happy Hour / Fri, Oct 2 / 5pm-8pm"),
            hit("Happy Hour / Fri, Oct 9 / 5pm-8pm"),
        ])
        self.assertEqual([(w["dow"], w["start"], w["end"]) for w in got],
                         [(5, "17:00", "20:00")])

    def test_the_same_date_written_twice_is_still_one_date(self):
        def hit(q):
            return {"url": "https://x.example/events", "quote": q}
        got, _q, _u = extract_deals.recurring_windows(
            [hit("Happy Hour / Fri, Sep 11 / 5pm-8pm")] * 4)
        self.assertEqual(got, [])

    def test_a_SEASON_is_not_a_date(self):
        # The guard has to be narrower than ONE_OFF_RE, which matches a bare
        # month-and-number -- and that is exactly what 86 West's seasonal line
        # looks like. Using ONE_OFF_RE per clause would take its card off the
        # board.
        got = windows_from("Half Price Drinks / mon - sun / january - march 4-7pm")
        self.assertEqual(len(got), 7)
        self.assertEqual({(w["start"], w["end"]) for w in got}, {("16:00", "19:00")})

    def test_a_hedged_chain_page_publishes_nothing_about_this_address(self):
        self.assertEqual(
            windows_from("Happy Hour times vary by location, Monday-Friday 3-6pm"), [])

    def test_another_countrys_chain_offer_is_not_a_pa_happy_hour(self):
        self.assertEqual(
            windows_from("Happy Hour pricing available for Canada locations only. 2 - 5 pm"), [])

    def test_a_locationless_disclaimer_refuses_its_entire_page(self):
        hits = [
            {"url": "https://brand.example/happy-hour", "quote": "Enjoy Happy Hour 3-6pm"},
            {"url": "https://brand.example/happy-hour", "quote": "Only available at participating locations"},
            {"url": "https://brand.example/happy-hour-ca", "quote": "Happy Hour Monday-Friday 2-5pm"},
        ]
        self.assertEqual(refused_source_urls(hits),
                         {"https://brand.example/happy-hour", "https://brand.example/happy-hour-ca"})

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


class PlacesNameAgreement(unittest.TestCase):
    """A right address is not a right subject."""

    def place(self, name):
        return {"displayName": {"text": name}}

    def test_the_apartment_block_a_bar_sits_inside_is_refused(self):
        # Justop is on the ground floor of 1720 Fairmount Ave, so the address
        # matches perfectly and Google returns the building. A photograph of an
        # apartment block on a bar's card is read as the whole board being
        # careless -- which is what it would be.
        venue = {"name": "Justop", "plcb_name": "JUSTOP LLC",
                 "address": "1720 Fairmount Ave, Philadelphia PA 19130"}
        self.assertFalse(name_agrees(venue, self.place("1720 Fairmount Luxury Apartments")))

    def test_the_same_bar_under_a_longer_google_name_is_kept(self):
        venue = {"name": "Philadelphia Live! Hotel", "plcb_name": "LIVE CASINO"}
        self.assertTrue(name_agrees(venue, self.place("Live! Casino & Hotel Philadelphia")))
        venue = {"name": "Brickside Grille", "plcb_name": "BRICKSIDE GRILLE"}
        self.assertTrue(name_agrees(venue, self.place("Brickside Grille")))

    def test_two_names_sharing_only_a_business_type_do_not_agree(self):
        venue = {"name": "The Black Horse Tavern", "plcb_name": "BLACK HORSE"}
        self.assertFalse(name_agrees(venue, self.place("Wellington Square Tavern")))


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


def _photo_deal(submitted, photo_id, start="16:00"):
    return {
        "type": "happy_hour",
        "windows": [{"dow": 1, "start": start, "end": "18:00"}],
        "items": [],
        "source": {"kind": "photo", "photo_id": photo_id, "submitted": submitted},
    }


class MenuSupersession(unittest.TestCase):
    """A photo of the menu is how a customer corrects us, so approving one has
    to REPLACE what it contradicts. The original filter dropped the incoming
    submission's own deals and kept every stale one, so a venue grew a second,
    contradictory happy hour every time somebody reported the first was wrong."""

    def test_an_older_photo_is_replaced(self):
        old = _photo_deal("2026-06-01T18:00:00.000Z", "old-1")
        sub = {"id": "new-1", "submitted_at": "2026-08-31T21:58:23.288Z"}
        self.assertEqual(superseded([old], sub), [])

    def test_pages_of_the_same_menu_add_up(self):
        # Three pages of one menu are three submissions minutes apart. If the
        # second replaced the first, a multi-page happy hour could never be
        # published whole -- only its last page would survive.
        page1 = _photo_deal("2026-08-31T21:58:00.000Z", "p1")
        sub = {"id": "p2", "submitted_at": "2026-08-31T22:01:00.000Z"}
        self.assertEqual(superseded([page1], sub), [page1])

    def test_reapproving_one_photo_replaces_its_own_deals(self):
        mine = _photo_deal("2026-08-31T21:58:00.000Z", "p1")
        sub = {"id": "p1", "submitted_at": "2026-08-31T21:58:00.000Z"}
        self.assertEqual(superseded([mine], sub), [])

    def test_a_non_photo_deal_is_never_eaten(self):
        seeded = {"type": "happy_hour", "windows": [], "items": [],
                  "source": {"kind": "venue_site"}}
        sub = {"id": "new-1", "submitted_at": "2026-08-31T21:58:23.288Z"}
        self.assertEqual(superseded([seeded], sub), [seeded])

    def test_an_unreadable_timestamp_supersedes_rather_than_accumulates(self):
        # Failing open here means duplicate contradictory windows on a live
        # card, which is the exact defect this function exists to stop.
        old = _photo_deal("2026-06-01T18:00:00.000Z", "old-1")
        sub = {"id": "new-1", "submitted_at": "not a timestamp"}
        self.assertEqual(superseded([old], sub), [])


class MenuPagesAddedLater(unittest.TestCase):
    """Six hours cannot tell a second page photographed the next day from a
    menu that changed. The reviewer is asked, and the answer rides on the deal
    -- so the two readers of it, the live overlay and the nightly fold, cannot
    reach different conclusions about the same board."""

    def test_a_reviewer_saying_it_adds_keeps_hours_a_year_older(self):
        old = _photo_deal("2026-06-01T18:00:00.000Z", "old-1")
        sub = {"id": "new-1", "submitted_at": "2026-08-31T21:58:23.288Z"}
        self.assertEqual(superseded([old], sub, "add"), [old])

    def test_adding_still_replaces_the_photos_own_deals(self):
        # Approving one photo twice must not double its hours on the card.
        mine = _photo_deal("2026-08-31T21:58:00.000Z", "p1")
        sub = {"id": "p1", "submitted_at": "2026-08-31T21:58:00.000Z"}
        self.assertEqual(superseded([mine], sub, "add"), [])

    def test_add_mode_does_not_need_a_readable_timestamp(self):
        # The answer came from a person, so the clock has nothing left to say.
        old = _photo_deal("2026-06-01T18:00:00.000Z", "old-1")
        sub = {"id": "new-1", "submitted_at": "not a timestamp"}
        self.assertEqual(superseded([old], sub, "add"), [old])

    def test_no_answer_means_replace(self):
        # Every photo approved before this question existed, and any path that
        # forgets to ask, has to land on the answer that leaves a card honest.
        self.assertEqual(merge_mode({}), "replace")
        self.assertEqual(merge_mode({"deals": [_photo_deal("2026-06-01T18:00:00.000Z", "x")]}), "replace")

    def test_the_answer_is_read_off_the_deal(self):
        deal = _photo_deal("2026-06-01T18:00:00.000Z", "x")
        deal["source"]["merge"] = "add"
        self.assertEqual(merge_mode({"deals": [deal]}), "add")


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
            body, err, _landed = crawl_sites.get(self._session(403), "https://x.test/")
        ug.assert_called_once()
        self.assertIsNone(err)
        self.assertIn("from urllib", body)

    def test_a_200_is_never_refetched(self):
        with unittest.mock.patch.object(crawl_sites, "urllib_get") as ug:
            body, err, _landed = crawl_sites.get(self._session(200), "https://x.test/")
        ug.assert_not_called()
        self.assertIn("from requests", body)

    def test_the_fallbacks_headers_answer_to_a_lowercase_lookup(self):
        """A real fetch recorded as '200 ?' because the dict was case-sensitive."""
        plain = crawl_sites._Plain(200, {"content-type": "text/html"}, b"<p>hi</p>")
        with unittest.mock.patch.object(crawl_sites, "urllib_get",
                                        return_value=plain):
            body, err, _landed = crawl_sites.get(self._session(403), "https://x.test/")
        self.assertIsNone(err, "content-type lookup must not miss on case")

    def test_a_failing_fallback_keeps_the_original_refusal(self):
        with unittest.mock.patch.object(crawl_sites, "urllib_get",
                                        side_effect=OSError("nope")):
            body, err, _landed = crawl_sites.get(self._session(403), "https://x.test/")
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
        # 400k held until 2026-09-02, when every card gained a storefront photo
        # (213 of 214, ~80 bytes each of path and attribution). That is the
        # board getting richer, not the base leaking in; the base is a
        # megabyte and would still trip this.
        # 500k held until 2026-09-03, when 27 venues an agent hand-read
        # arrived at once with their full menus (202 items across Wilmington,
        # Newark and West Chester). Same reason again: the deals got richer.
        # The base is 1.3MB, so it still cannot hide under this number.
        boot = sum(os.path.getsize(os.path.join(REPO, "web", "data", f"zone-{z['id']}.json"))
                   for z in self.index["zones"])
        self.assertLess(boot, 600_000, "the boot payload has grown a venue base again")

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


class OneBarOneCard(unittest.TestCase):
    """Two licences in one building, one of them wearing the other's name.

    Six bars painted twice on the live board. The PLCB has a second licence at
    the same address -- the Giant next door, the Marriott upstairs -- the name
    match gave it the bar's trade name, and the crawl hung the bar's hours on
    both. The signal that they are one bar is that both deals were read off the
    SAME page.
    """

    def venue(self, lid, name, url, plcb=None, deals=True, address=None):
        v = {"id": lid, "lid": lid, "name": name, "zone_id": "z",
             "plcb_name": plcb or name, "deals": []}
        if address:
            v["address"] = address
        if deals:
            v["deals"] = [{"type": "happy_hour", "source": {"url": url}}]
        return v

    def test_the_same_page_under_the_same_name_is_one_bar(self):
        a = self.venue("119303", "PJ Whelihan's", "https://pjspub.com/wynnewood")
        b = self.venue("73040", "PJ Whelihan's", "https://pjspub.com/wynnewood",
                       plcb="THE GIANT COMPANY LLC")
        n = collapse_name_collisions({"z": [a, b]})
        self.assertEqual(n, 1)
        # One card keeps the hours; the other goes back to being a supermarket
        # with no published window, and its licence rides along on the card so
        # a correction quoting it still lands.
        self.assertEqual(len(a["deals"]), 1)
        self.assertEqual(b["deals"], [])
        self.assertEqual(b["name"], "THE GIANT COMPANY LLC")
        self.assertIn("73040", a["also_lids"])

    def test_a_real_second_branch_keeps_its_card(self):
        # Same name, same town, its OWN page: two real bars. Merging those is a
        # far worse error than listing one twice, so the page has to agree.
        a = self.venue("1", "P.J. Whelihan's", "https://pjspub.com/conshohocken")
        b = self.venue("2", "P.J. Whelihan's", "https://pjspub.com/blue-bell")
        self.assertEqual(collapse_name_collisions({"z": [a, b]}), 0)
        self.assertTrue(a["deals"] and b["deals"])

    def test_same_door_merges_when_the_source_urls_differ(self):
        a = self.venue("1", "Amada", "https://amada.example/specials",
                       address="555 E Lancaster Ave, Radnor PA 19087")
        b = self.venue("2", "Amada", "https://amada.example/radnor",
                       plcb="FLEMINGS PRIME STEAKHOUSE",
                       address="Radnor Center 555 E Lancaster Ave, Radnor PA 19087")
        self.assertEqual(collapse_name_collisions({"z": [a, b]}), 1)
        self.assertEqual(b["deals"], [])

    def test_two_licences_merge_while_a_third_branch_is_left_alone(self):
        # The case that made the first version of this merge nobody: asking
        # what ALL THREE share finds nothing.
        a = self.venue("117317", "P.J. Whelihan's", "https://pjspub.com/consho")
        b = self.venue("69227", "P.J. Whelihan's", "https://pjspub.com/consho",
                       plcb="WEIS MARKETS INC")
        c = self.venue("50385", "P.J. Whelihan's Pub and Restaurant",
                       "https://pjspub.com/blue-bell")
        self.assertEqual(collapse_name_collisions({"z": [a, b, c]}), 1)
        self.assertEqual(b["deals"], [])
        self.assertTrue(c["deals"])

    def test_punctuation_is_not_a_different_bar(self):
        self.assertEqual(norm_name("PJ Whelihan's"),
                         norm_name("P. J. Whelihan's Pub + Restaurant"))
        self.assertNotEqual(norm_name("Amada"), norm_name("Armada"))


class ARealBranchMustSayWhichOneItIs(unittest.TestCase):
    """The half the merge deliberately left undone.

    collapse_name_collisions() refuses to merge two genuine bars, which is
    right. But Newark, DE ships a Red Robin on Pulaski Hwy and another on
    W Main St, three miles apart, and the two cards were identical down to
    the window -- so a reader could not tell which one they were tapping.
    Whatever collision SURVIVES the merge is a branch, and gets its street.
    """

    def venue(self, lid, name, address):
        return {"id": lid, "lid": lid, "name": name, "zone_id": "z",
                "plcb_name": name, "address": address, "deals": []}

    def test_two_real_branches_each_get_their_street(self):
        a = self.venue("1", "Red Robin", "2496 Pulaski Hwy, Newark, DE 19702")
        b = self.venue("2", "Red Robin", "101 W Main St, Newark, DE 19702")
        self.assertEqual(build_bundles.name_the_surviving_branches({"z": [a, b]}), 2)
        self.assertEqual(a["branch"], "Pulaski Hwy")
        self.assertEqual(b["branch"], "W Main St")

    def test_a_bar_with_no_namesake_is_left_alone(self):
        a = self.venue("1", "Black Powder Tavern", "1164 Valley Forge Rd, Wayne PA")
        self.assertEqual(build_bundles.name_the_surviving_branches({"z": [a]}), 0)
        self.assertNotIn("branch", a)

    def test_a_label_that_would_repeat_is_not_applied(self):
        # Two rows we cannot separate stay unlabelled: a street printed twice
        # tells a reader less than no street at all.
        a = self.venue("1", "Dandan", "100 Sugartown Rd, Devon PA")
        b = self.venue("2", "Dandan", "Ste 4, 100 Sugartown Rd, Devon PA")
        self.assertEqual(build_bundles.name_the_surviving_branches({"z": [a, b]}), 0)

    def test_the_house_number_is_not_the_label(self):
        self.assertEqual(build_bundles.street_of("2496 Pulaski Hwy, Newark, DE"),
                         "Pulaski Hwy")
        self.assertEqual(build_bundles.street_of("101-A W Main St, Newark"),
                         "W Main St")


class MenuPricesOnAHappyHourPage(unittest.TestCase):
    """A price and the thing it is for, printed in separate blocks.

    Bloom Southern Kitchen's happy-hour page holds thirty prices and our crawl
    kept three quotes, none of them priced: the theme puts the item name and its
    price in different DOM blocks, so visible_text emits '$ 5' alone. Neither
    DEAL_RE nor MENU_ITEM_RE can match that line, and on its own it deserves
    nothing -- '$ 5' names no product.
    """

    PAGE = "Small Plates\n$ 5\nNashville Deviled Eggs\nchives, fresno chile\n"

    def test_an_ordinary_page_still_ignores_a_bare_price(self):
        # The containment is the whole safety argument: on a page the venue did
        # not call its happy hour, these lines are the dinner menu.
        self.assertEqual(quotes(self.PAGE), [])

    def test_a_happy_hour_page_keeps_the_price_with_its_neighbours(self):
        got = quotes(self.PAGE, hh_page=True)
        self.assertTrue(any("$ 5" in q and "Nashville Deviled Eggs" in q for q in got),
                        got)

    def test_both_neighbours_are_kept_because_the_order_is_not_stable(self):
        # Bloom prints the price above its item; other themes print it below.
        # Naming the wrong one is a wrong price on a card, so the crawl keeps
        # the material and the reviewed price pass decides.
        q = [x for x in quotes(self.PAGE, hh_page=True) if "$ 5" in x][0]
        self.assertIn("Small Plates", q)
        self.assertIn("Nashville Deviled Eggs", q)


class MenuPostedAsAPicture(unittest.TestCase):
    """Malbec publishes its entire happy-hour menu as a JPG exported from a PDF.

    The page has real hours in text and not one dollar sign anywhere in its
    HTML, so the venue reads as covered while its menu is invisible.
    """

    HTML = ('<img src="/wp-content/uploads/2026/06/MalbecStk_HH_May_2026-pdf.jpg">'
            '<img src="/wp-content/uploads/2026/06/MalbecStk_HH_May_2026-pdf-300x150.jpg">'
            '<img src="/wp-content/uploads/2020/04/cropped-IMG_2939-180x180.jpg">')

    def test_the_menu_image_is_found_and_made_absolute(self):
        got = menu_images(self.HTML, "http://malbec.example/happyhour/")
        self.assertEqual(
            got,
            ["http://malbec.example/wp-content/uploads/2026/06/"
             "MalbecStk_HH_May_2026-pdf.jpg"])

    def test_a_theme_size_variant_is_not_a_second_menu(self):
        # A WordPress theme emits the same upload at six widths. They are one
        # menu, and only the full-size one is legible.
        self.assertEqual(len(menu_images(self.HTML, "http://malbec.example/happyhour/")), 1)

    def test_page_furniture_is_not_a_menu(self):
        # The logo and the favicon are on every page; the filename is the only
        # signal that held up, because alt text and nearby copy let a hero shot
        # of people drinking through.
        self.assertEqual(menu_images('<img src="/uploads/cropped-IMG_2939.jpg">',
                                     "http://x.example/happyhour/"), [])


class APrintedMenuOmitsTheDollarSign(unittest.TestCase):
    """'COCONUT MOJITO 9' is a price. The whole sheet is a price list.

    verify()'s rule that the digits must appear as '$9' is right for a sentence
    on a web page and rejected all eighteen of Malbec's real items.
    """

    def test_a_signless_price_is_accepted_on_a_menu(self):
        item = {"category": "cocktail", "label": "Coconut Mojito",
                "price_usd": 9.0, "evidence": "COCONUT MOJITO 9"}
        clean, why = verify(dict(item), "COCONUT MOJITO 9", menu=True)
        self.assertIsNotNone(clean, why)

    def test_a_signless_price_is_still_refused_on_a_web_page(self):
        item = {"category": "cocktail", "label": "Coconut Mojito",
                "price_usd": 9.0, "evidence": "COCONUT MOJITO 9"}
        self.assertIsNone(verify(dict(item), "COCONUT MOJITO 9")[0])

    def test_a_price_is_never_read_out_of_a_longer_number(self):
        # 5 must not be found inside '15'. This is the check that makes the
        # signless form safe to accept at all.
        item = {"category": "food", "label": "mussels", "price_usd": 5.0,
                "evidence": "Half Dozen Mussels - marinara sauce 15"}
        self.assertIsNone(
            verify(dict(item), "Half Dozen Mussels - marinara sauce 15", menu=True)[0])

    def test_a_menu_may_name_its_dishes_in_full(self):
        item = {"category": "food", "price_usd": 16.0,
                "label": "Malbec Burger served with French fries or house salad",
                "evidence": "Served with French Fries or House Salad 16"}
        clean, why = verify(dict(item), "Served with French Fries or House Salad 16",
                            menu=True)
        self.assertIsNotNone(clean, why)


class ASecondLicenceIsNotACard(unittest.TestCase):
    """A collapsed licence must never cost a Places lookup.

    build_bundles folds a second PLCB licence at one address into the bar's
    card. The loser keeps its LICENSEE name -- GIANT, Weis Markets,
    Philadelphia Marriott -- and stays a key in board-by-lid.json, so the
    photo pass searched Google for a supermarket and bought its storefront.
    Six of those were billed. None could ever appear: the winning card keeps
    its own picture.
    """

    def _zones(self, venues):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "web", "data"))
        with open(os.path.join(d, "web", "data", "zone-x.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"venues": venues}, fh)
        return d

    def test_a_ridealong_licence_is_named(self):
        d = self._zones([{"lid": "1", "also_lids": ["73040", "69227"]},
                         {"lid": "2"}])
        with unittest.mock.patch("fetch_venue_photos.REPO", d):
            self.assertEqual(absorbed_lids(), {"73040", "69227"})

    def test_a_card_with_no_second_licence_contributes_nothing(self):
        d = self._zones([{"lid": "1"}, {"lid": "2", "also_lids": []}])
        with unittest.mock.patch("fetch_venue_photos.REPO", d):
            self.assertEqual(absorbed_lids(), set())

    def test_the_winning_lid_is_not_swept_up_with_its_losers(self):
        # The guard skips lookups. If it named the winner too, the bar itself
        # would be refused a photograph forever.
        d = self._zones([{"lid": "44269", "also_lids": ["44268"]}])
        with unittest.mock.patch("fetch_venue_photos.REPO", d):
            self.assertEqual(absorbed_lids(), {"44268"})


def _w(dow, start, end, hh=True):
    return {"dow": dow, "start": start, "end": end, "_hh": hh}


class ADayClaimedTwice(unittest.TestCase):
    """A bar publishes more than one window for one day all the time, and the
    clock alone cannot say which is the happy hour. Every tie-break tried on the
    times alone published something false: longest gave Valley Forge Pizza's
    'Mon - Sun: 11:00 AM - 10:00 PM' opening hours, shortest gave Cedar Point's
    10pm late-night instead of its 5pm happy hour, earliest gave Veda's lunch.
    """

    def test_two_readings_that_overlap_publish_only_the_overlap(self):
        # Veda says 4:30 on one page and 4:00 on another. Sending somebody at
        # 4:00 to a discount that starts at 4:30 makes them pay full price.
        got = dedupe([_w(1, "16:00", "19:00"), _w(1, "16:30", "19:00")])
        self.assertEqual(got, [{"dow": 1, "start": "16:30", "end": "19:00"}])

    def test_the_overlap_is_taken_whichever_order_they_arrive_in(self):
        a = dedupe([_w(1, "16:30", "19:00"), _w(1, "16:00", "19:00")])
        b = dedupe([_w(1, "16:00", "19:00"), _w(1, "16:30", "19:00")])
        self.assertEqual(a, b)

    def test_a_second_happy_hour_later_the_same_night_does_not_win(self):
        # Cedar Point pours at 5 and again at 10. Only one fits on a card, and
        # 'happy hour' to a person at teatime is the first one.
        got = dedupe([_w(2, "22:00", "23:00"), _w(2, "17:00", "19:00")])
        self.assertEqual(got, [{"dow": 2, "start": "17:00", "end": "19:00"}])

    def test_a_noon_happy_hour_does_not_hide_the_afternoon_one(self):
        # Southern Cross runs a genuine noon 'brunch happy hour' AND a 4:30 one.
        got = dedupe([_w(3, "12:00", "14:00"), _w(3, "16:30", "18:30")])
        self.assertEqual(got, [{"dow": 3, "start": "16:30", "end": "18:30"}])

    def test_opening_hours_never_beat_a_happy_hour(self):
        # The window over the statutory cap is the bar's opening hours; it holds
        # the day only while nothing lawful claims it.
        got = dedupe([_w(4, "11:00", "22:00"), _w(4, "16:00", "18:00")])
        self.assertEqual(got, [{"dow": 4, "start": "16:00", "end": "18:00"}])

    def test_the_venues_own_word_outranks_a_window_that_never_claimed_one(self):
        got = dedupe([_w(5, "12:00", "15:00", hh=False), _w(5, "17:00", "19:00")])
        self.assertEqual(got, [{"dow": 5, "start": "17:00", "end": "19:00"}])

    def test_no_private_marker_reaches_the_published_deal(self):
        for w in dedupe([_w(1, "16:00", "18:00")]):
            self.assertNotIn("_hh", w)


class AnotherMealIsNotAHappyHour(unittest.TestCase):
    """Four hours of lunch is lawful, so the statutory cap cannot catch it -- and
    a lunch menu published as a happy hour is a wrong claim, which is worse than
    a missing one. Barbuzzo's weekend LUNCH and Sor Ynez's saturday Brunch both
    reached the board that way."""

    def test_a_lunch_clause_states_lunchs_hours(self):
        got = windows_from("HAPPY HOUR: Mon - Fri 5pm-7pm / "
                           "LUNCH: Saturday & Sunday - 12pm-4pm")
        self.assertEqual({w["dow"] for w in got}, {1, 2, 3, 4, 5})

    def test_the_brunch_window_beside_a_happy_hour_is_left_behind(self):
        got = windows_from("Tues - Fri 4pm - 7pm • saturday Brunch 12pm-4pm")
        self.assertEqual({w["dow"] for w in got}, {2, 3, 4, 5})

    def test_a_meal_clause_does_not_lend_its_days_to_a_later_time(self):
        # The days named by the meal belong to the meal, so they must not carry
        # forward and pair themselves with the next window on the line.
        self.assertEqual(windows_from("Dinner: Monday - Thursday / 5pm - 10pm"), [])

    def test_bar_bites_can_still_be_the_happy_hour(self):
        # Firebirds' happy hour IS called Bar Bites. Refusing the phrase cost a
        # real card; only a clause naming a SERVICE window is excluded.
        got = windows_from("Happy Hour / Join us for Bar Bites and Drink Specials "
                           "every Monday-Friday from 2PM-6PM")
        self.assertEqual({w["dow"] for w in got}, {1, 2, 3, 4, 5})


class OneUnlawfulDayIsNotEvidenceAgainstTheOthers(unittest.TestCase):
    """A venue used to be discarded whole when a single day broke the statutory
    cap. Bar Hygge lost four lawful 'Tuesday thru Friday: 4pm - 6pm' windows
    because the weekend line beside them reads as 4.5 hours."""

    def test_the_lawful_days_survive_their_neighbour(self):
        ws = [{"dow": d, "start": "16:00", "end": "18:00"} for d in (2, 3, 4, 5)]
        ws += [{"dow": d, "start": "10:00", "end": "14:30"} for d in (6, 7)]
        self.assertEqual([w["dow"] for w in lawful_days(ws)], [2, 3, 4, 5])

    def test_a_week_over_the_cap_sheds_its_longest_days_first(self):
        ws = [{"dow": d, "start": "12:00", "end": "16:00"} for d in range(1, 8)]
        ws[0] = {"dow": 1, "start": "12:00", "end": "13:00"}
        kept = lawful_days(ws)
        self.assertLessEqual(sum((int(w["end"][:2]) - int(w["start"][:2]))
                                 for w in kept), 24)
        self.assertIn(1, [w["dow"] for w in kept])

    def test_nothing_lawful_leaves_nothing(self):
        self.assertEqual(lawful_days([{"dow": 1, "start": "11:00", "end": "22:00"}]), [])



class WhichSideOfTheJoinTheItemIsOnIsREADOFFTHETREE(unittest.TestCase):
    """A price and its item are the lines the page put in ONE box.

    quotes() has to join a bare price line to a neighbour, because '$8' and its
    dish are on separate lines and each is worthless alone. WHICH neighbour is
    not a rule -- it differs by page, and both of these are real:

        CO-OP     'Deviled Eggs / with capers and everything spice / $ 8'
                  -- the item is ABOVE. The Wings below it are $12.
        Chili's   '$3 / Bud Light 16 oz'
                  -- the item is BELOW.

    Reading the item as the one after the price priced CO-OP's wings at $8 when
    they are $12 -- a WRONG price on a real bar, which is the one failure this
    containment exists to prevent -- so for a while the joined quote was made
    deliberately unreadable and 40 venues stayed unpriced.

    The text cannot answer it. The markup can: both venues wrap the price and
    its item in one element and the next item in another. So text_lines() now
    also returns the element chain each line was found in, item_beside() reads
    the item out of the price's own box, and the pairing happens at CRAWL time
    -- the extractor cannot recover what the crawler threw away.

    The fixtures below carry the real pages' NESTING, not a flat remembering of
    them: a fixture written from memory of a page is not the page, and a flat
    one would make every line a sibling and hide the whole mechanism.
    """

    # CO-OP: <li class="menu-item"> holding name, description and price, and
    # the NEXT item -- $12 Wings -- in an <li> of its own.
    COOP = ("<h2>Happy Hour</h2><p>Weekdays from 3pm - 6pm</p><ul>"
            "<li><div><p>Deviled Eggs</p></div>"
            "<p>with capers and everything spice</p><p><strong>$ 8</strong></p></li>"
            "<li><div><p>Wings</p></div>"
            "<p>House-made hot sauce, blue cheese</p><p><strong>$ 12</strong></p></li>"
            "</ul>")

    # Chili's: one <div> per price, holding the price and the beers it covers.
    CHILIS = ("<div>Happy Hour</div><div>MONDAY-THURSDAY</div><div>3-6pm</div>"
              "<div><div>$3</div><div><div>Bud Light 16 oz</div>"
              "<div>Miller Lite 16 oz</div></div></div>"
              "<div><div>$4</div><div><div>Modelo 16 oz</div></div></div>")

    def _quotes(self, html):
        lines, stacks = text_lines(html)
        text = "\n".join(lines)
        return quotes(text, hh_lines=hh_sections(html, text), stacks=stacks)

    def test_the_item_above_the_price_is_the_one_priced(self):
        got = self._quotes(self.COOP)
        self.assertIn("$8 Deviled Eggs", " | ".join(got))
        # 'Deviled Eggs' names no noun the price pass recognises, so it is left
        # out of the item list -- a separate containment, and not this one. What
        # matters here is that no item comes back priced at the eggs' $8.
        self.assertEqual([i["price_usd"] for i in items_in(" ".join(got))], [12.0])

    def test_the_next_item_down_keeps_its_own_price(self):
        # The $8/$12 error: the wings are in the NEXT box and are never $8.
        wings = [q for q in self._quotes(self.COOP) if "Wings" in q]
        self.assertEqual(len(wings), 1, wings)
        self.assertIn("$12 Wings", wings[0])
        self.assertNotIn("$8", wings[0])

    def test_the_item_below_the_price_is_the_one_priced(self):
        got = self._quotes(self.CHILIS)
        self.assertIn("$3 Bud Light 16 oz", " | ".join(got))
        self.assertNotIn("$3 Modelo", " | ".join(got))

    def test_a_price_alone_in_a_box_too_big_to_be_an_item_is_refused(self):
        # Every line a sibling of every other: the box the price shares with a
        # neighbour is the whole page, which is not an item. Refusing leaves the
        # venue unpriced, which is the correct answer to a question the page has
        # not answered -- and the quote stays unreadable to the price pass.
        flat = ("<h2>Happy Hour</h2><p>Weekdays 3pm - 6pm</p>"
                "<p>Deviled Eggs</p><p>$ 8</p><p>Wings</p><p>$ 12</p>"
                "<p>Cheese Board</p><p>$ 24</p><p>Nachos</p><p>$ 9</p>"
                "<p>Fries</p><p>$ 6</p><p>Olives</p><p>$ 7</p>")
        lines, stacks = text_lines(flat)
        i = lines.index("$ 8")
        self.assertIsNone(item_beside(i, lines, stacks))
        self.assertEqual(items_in(" ".join(self._quotes(flat))), [])

    def test_the_glued_quote_is_still_refused_by_the_price_pass(self):
        # The old shape, still on disk in crawl_hits.json for every venue not
        # yet re-crawled. It must keep meaning 'we do not know'.
        self.assertEqual(items_in("with capers and everything spice / $ 8 / Wings"),
                         [])

    def test_the_adjacent_form_still_reads(self):
        self.assertEqual(items_in("$6 margaritas")[0]["label"], "margaritas")


class AFailedFetchIsNotAnAnswerAboutTheVenue(unittest.TestCase):
    """A re-crawl that could not read a page must not erase what we hold.

    The Stray Dog Tavern published a happy hour and eight quotes. One
    ConnectTimeout during the 2026-09-01 re-crawl replaced the record with an
    empty one and the venue left the board. 'hits: []' is indistinguishable
    from a venue that publishes nothing, so the loss was silent.
    """

    def test_every_page_erroring_is_a_failed_crawl(self):
        self.assertTrue(reached_nothing([{"url": "x", "result": "error: ConnectTimeout"}]))

    def test_one_page_read_is_a_real_answer(self):
        self.assertFalse(reached_nothing([{"url": "x", "result": "error: 404"},
                                          {"url": "y", "result": "ok"}]))

    def test_a_venue_with_no_pages_at_all_is_not_called_a_failure(self):
        # No website to try is a fact about the venue, not about the network.
        self.assertFalse(reached_nothing([]))



class AShellHomepageIsWorthOneRender(unittest.TestCase):
    """The render gate used to be keyed on the thing the failure destroys.

    It required an hour-named URL AND a page under the line floor. A shell
    homepage's URL names no hour, and a shell yields no links, so the
    hour-named URL was never discovered and the gate could never fire on the
    class it existed for: across all 390 no-quote venues, zero pages had ever
    been rendered (2026-09-02). A seed page of a venue with no quote is now
    worth one render, and the rendered HTML feeds the link harvest.
    """

    def setUp(self):
        self._saved = dict(crawl_sites._render)
        crawl_sites._render.update({"on": True, "used": 0})

    def tearDown(self):
        crawl_sites._render.update(self._saved)

    def test_a_shell_seed_page_of_a_quoteless_venue_renders(self):
        self.assertTrue(crawl_sites.render_wanted("https://bar.example/", ["x"] * 3,
                                                  depth=1, quoted=False))

    def test_a_shell_seed_page_of_a_venue_already_quoted_does_not(self):
        self.assertFalse(crawl_sites.render_wanted("https://bar.example/", ["x"] * 3,
                                                   depth=1, quoted=True))

    def test_a_shell_deeper_in_still_needs_an_hour_named_url(self):
        self.assertFalse(crawl_sites.render_wanted("https://bar.example/menu",
                                                   ["x"] * 3, depth=2, quoted=False))
        self.assertTrue(crawl_sites.render_wanted("https://bar.example/happy-hour",
                                                  ["x"] * 3, depth=2, quoted=True))

    def test_a_page_read_in_full_is_never_rendered(self):
        # Measured at zero yield for King of Prussia (2026-09-01); the floor keeps it.
        self.assertFalse(crawl_sites.render_wanted("https://bar.example/", ["x"] * 80,
                                                   depth=1, quoted=False))

    def test_the_cap_and_the_switch_still_bound_it(self):
        crawl_sites._render["on"] = False
        self.assertFalse(crawl_sites.render_wanted("https://bar.example/", [], 1, False))
        crawl_sites._render.update({"on": True, "used": crawl_sites.RENDER_CAP})
        self.assertFalse(crawl_sites.render_wanted("https://bar.example/", [], 1, False))

    def test_the_rendered_seed_is_where_the_hour_named_link_comes_from(self):
        # Fetched: a Laravel-style shell, no links. Rendered: the real homepage
        # linking /happy-hour. The crawl must find that page through the render.
        shell = "<html><body><div id=app></div><script src=a.js></script></body></html>"
        full = "<html><body>" + "".join(
            "<p>Welcome to the bar, line %d of the homepage text</p>" % i
            for i in range(40)) + '<a href="/happy-hour">Happy Hour</a></body></html>'

        def get(url, **kw):
            r = unittest.mock.Mock(status_code=200,
                                   headers={"content-type": "text/html; charset=utf-8"})
            # The happy-hour page itself reads in full, so only the seed renders.
            hh = "Happy Hour 4pm - 6pm<br>" + "<p>a menu line</p>" * 40
            r.text = shell if url == "https://bar.example/" else hh
            return r

        session = unittest.mock.Mock(get=get)
        rendered = []

        def render(url):
            rendered.append(url)
            return full

        with unittest.mock.patch.object(crawl_sites, "allowed", lambda u, c: True),                 unittest.mock.patch.object(crawl_sites, "DELAY", 0),                 unittest.mock.patch.object(crawl_sites, "render", render),                 unittest.mock.patch.object(crawl_sites, "sitemap_links",
                                           lambda *a: []),                 unittest.mock.patch.object(crawl_sites, "save_page", lambda *a, **k: None):
            pages, hits, _ = crawl_one(session, {"website": "https://bar.example/"}, {})
        self.assertEqual(rendered, ["https://bar.example/"])
        results = [p["result"] for p in pages]
        self.assertTrue(any(r.startswith("rendered: ") for r in results), results)
        self.assertIn("https://bar.example/happy-hour", [p["url"] for p in pages])
        self.assertTrue(hits)

    def test_a_blocked_happy_hour_page_gets_the_bounded_browser_retry(self):
        session = unittest.mock.Mock()
        session.get.return_value = unittest.mock.Mock(status_code=403,
                                                       headers={"content-type": "text/html"},
                                                       text="blocked")
        rendered = "Happy Hour Monday - Friday 3pm - 6pm $5 drafts"
        with unittest.mock.patch.object(crawl_sites, "allowed", lambda u, c: True), \
                unittest.mock.patch.object(crawl_sites, "DELAY", 0), \
                unittest.mock.patch.object(crawl_sites, "render", lambda u: rendered), \
                unittest.mock.patch.object(crawl_sites, "sitemap_links", lambda *a: []), \
                unittest.mock.patch.object(crawl_sites, "save_page", lambda *a, **k: None):
            pages, hits, _ = crawl_one(session,
                                        {"website": "https://bar.example/happy-hour"}, {})
        self.assertTrue(any(p["result"].startswith("rendered after 403") for p in pages))
        self.assertTrue(hits)


class TheVenuesOwnTownPageIsTheVenue(unittest.TestCase):
    """Sly Fox /phoenixville and Sedona /locations/phoenixville-pa/ hold the
    happy hour and match no LINK_WORD. A link naming the venue's own town is
    the venue's page and ranks first."""

    HTML = ('<a href="/beereventservices">Events</a>'
            '<a href="https://www.slyfoxbeer.com/phoenixville">Phoenixville</a>'
            '<a href="/menu">Menu</a>')

    def test_town_link_ranks_first(self):
        town = crawl_sites.town_re("520 Kimberton Rd, Phoenixville PA 19460")
        got = candidate_links(self.HTML, "https://www.slyfoxbeer.com/", town)
        self.assertEqual(got[0], "https://www.slyfoxbeer.com/phoenixville")
        self.assertEqual(len(got), 3)

    def test_hyphenated_locations_slug(self):
        town = crawl_sites.town_re("131 Bridge St, Phoenixville PA 19460")
        html = '<a href="/locations/phoenixville-pa/">Our Location</a>'
        got = candidate_links(html, "https://sedonataphouse.com/", town)
        self.assertEqual(got, ["https://sedonataphouse.com/locations/phoenixville-pa/"])

    def test_multi_word_town(self):
        town = crawl_sites.town_re("160 N Gulph Rd, King of Prussia PA 19406")
        for slug in ("king-of-prussia", "kingofprussia", "King_of_Prussia"):
            self.assertTrue(town.search("/locations/" + slug), slug)
        self.assertFalse(town.search("/kingston"))

    def test_no_town_is_the_old_rule(self):
        self.assertIsNone(crawl_sites.town_re("no address"))
        got = candidate_links(self.HTML, "https://www.slyfoxbeer.com/", None)
        self.assertEqual(got, ["https://www.slyfoxbeer.com/beereventservices",
                               "https://www.slyfoxbeer.com/menu"])

    def test_a_menu_card_anchor_is_a_link(self):
        # 220 characters of image div and heading inside the <a>: Sedona's PDF.
        html = ('<a href="/wp-content/uploads/HappyHourMenu_PhxWC.pdf"> '
                '<div class="menu-card__image" style="background-image: url('
                'https://sedonataphouse.com/wp-content/uploads/2019/01/'
                'kobe-sliders-fries-beer-2-600x450.jpg)"></div> '
                '<h3>Happy Hour Menu</h3> </a>')
        got = candidate_links(html, 'https://sedonataphouse.com/locations/phoenixville-pa/')
        self.assertEqual(got, ['https://sedonataphouse.com/wp-content/uploads/HappyHourMenu_PhxWC.pdf'])

    def test_another_town_is_not_ours(self):
        town = crawl_sites.town_re("520 Kimberton Rd, Phoenixville PA 19460")
        html = '<a href="/pottstown">Pottstown</a>'
        self.assertEqual(candidate_links(html, "https://www.slyfoxbeer.com/", town), [])


class AnImageThatNamesItselfTheHappyHour(unittest.TestCase):
    """Revival's menu is "Revival HH.png" on a Wix page; Rivertown's is
    Happy-Hour-Specials.png on /menu/. Both are the menu, on any page."""

    def test_standalone_hh_token_and_percent20(self):
        html = '<img src="https://static.wixstatic.com/media/x~mv2.png/v1/fill/Revival%20HH.png">'
        got = menu_images(html, "https://www.revivalpizzapub.com/happy-hour-menu")
        self.assertEqual(len(got), 1)
        self.assertIn("Revival HH.png", got[0])

    def test_hh_inside_a_word_is_not_the_token(self):
        html = '<img src="/img/shhh-quiet.png">'
        self.assertEqual(menu_images(html, "https://x.example/happy-hour"), [])

    def test_self_named_only_on_a_menu_page(self):
        html = ('<img src="/2026/07/Happy-Hour-Specials-791x1024.png">'
                '<img src="/2026/07/weekly-specials.png">')
        got = menu_images(html, "https://rivertowntaps.com/menu/", self_named=True)
        self.assertEqual(got, ["https://rivertowntaps.com/2026/07/Happy-Hour-Specials.png"])

    def test_hh_page_keeps_the_wider_rule(self):
        html = ('<img src="/2026/07/Happy-Hour-Specials.png">'
                '<img src="/2026/07/weekly-specials.png">')
        self.assertEqual(len(menu_images(html, "https://x.example/happy-hour/")), 2)


class ARedirectAcrossLocationsIsRefused(unittest.TestCase):
    """meetatgrain.com/locationsmenus 302s to /newark.

    Grain H2O is in Bear, DE. It was seeded at its own page, followed the
    index link, landed on NEWARK's page and published Newark's Mon-Fri 3-6pm
    on its own card -- live on the board. Every downstream gate passed,
    because the quote really is on the page really fetched. A wrong card is
    worse than a miss, and this class produces only wrong cards.
    """

    def setUp(self):
        self._held = crawl_sites._towns["slugs"]
        crawl_sites._towns["slugs"] = {"newark", "bear", "king-of-prussia", "media"}

    def tearDown(self):
        crawl_sites._towns["slugs"] = self._held

    BEAR = "1000 Pulaski Hwy, Bear DE 19701"

    def test_the_redirect_that_made_the_wrong_card(self):
        self.assertEqual(
            crawl_sites.landed_in_another_town("https://meetatgrain.com/locationsmenus",
                                      "https://meetatgrain.com/newark", self.BEAR),
            "newark")

    def test_the_venues_own_town_is_not_another_town(self):
        self.assertIsNone(
            crawl_sites.landed_in_another_town("https://meetatgrain.com/locationsmenus",
                                      "https://meetatgrain.com/bear", self.BEAR))

    def test_an_honest_redirect_is_not_refused(self):
        # Most redirects are normalisation, and refusing those would cost the
        # board far more than the class this guard exists for.
        for landed in ("https://meetatgrain.com/newark-menu/",
                       "http://meetatgrain.com/newark/index.html"):
            self.assertIsNone(
                crawl_sites.landed_in_another_town("https://meetatgrain.com/newark", landed,
                                          "1 Main St, Newark DE 19711"), landed)
        self.assertIsNone(
            crawl_sites.landed_in_another_town("http://x.com/happy-hour",
                                      "https://www.x.com/happy-hour/", self.BEAR))

    def test_a_word_that_is_not_a_town_is_left_alone(self):
        self.assertIsNone(
            crawl_sites.landed_in_another_town("https://x.com/locations",
                                      "https://x.com/specials", self.BEAR))

    def test_the_town_still_names_the_page_one_level_up(self):
        self.assertEqual(
            crawl_sites.landed_in_another_town(
                "https://x.com/locations",
                "https://x.com/locations/newark/happy-hour", self.BEAR),
            "newark")

    def test_an_asset_path_is_not_a_town_even_when_it_spells_one(self):
        # 'Media' is a town in this corpus and also half the asset paths on the
        # web. A wrong refusal costs a real venue its hours, so the town has to
        # name the PAGE -- the end of the path, not any segment in it.
        self.assertIsNone(
            crawl_sites.landed_in_another_town("https://x.com/hh",
                                      "https://x.com/media/logo-2x.png", self.BEAR))

    def test_a_town_is_read_out_of_any_state_not_only_pennsylvania(self):
        # The PA-only reader went silent in Delaware -- which is where the bar
        # this guard protects is.
        self.assertEqual(crawl_sites.town_slug("520 Kimberton Rd, Phoenixville PA 19460"),
                         "phoenixville")
        # The comma before the state is optional and BOTH forms are in the
        # corpus. Requiring it absent read every Delaware address as townless,
        # so the guard's vocabulary was empty exactly where it was needed.
        self.assertEqual(crawl_sites.town_slug(self.BEAR), "bear")
        self.assertEqual(
            crawl_sites.town_slug("3006 Summit Harbour Pl, Bear, DE 19701"), "bear")
        self.assertEqual(crawl_sites.town_slug("1 Rt 1, King of Prussia PA 19406"),
                         "king-of-prussia")
        self.assertIsNone(crawl_sites.town_slug(""))


class AnImageTheVenueLinkedUnderTheWords(unittest.TestCase):
    """Grain names its happy-hour poster after the TOWN -- /s/Newark.png -- so no
    filename rule can see it. The venue says what the file is by wrapping the
    words around the link: <a href="/s/Newark.png">Happy Hours</a>. Eleven priced
    items sat behind that link while the card published a window and nothing else.
    """

    def test_the_link_label_names_the_file(self):
        html = '<a href="/s/Newark.png" target="_blank"><em>Happy Hours</em></a>'
        got = menu_images(html, "https://meetatgrain.com/newark", self_named=True)
        self.assertEqual(got, ["https://meetatgrain.com/s/Newark.png"])

    def test_a_caption_near_a_photo_is_still_not_a_menu(self):
        html = '<div><img src="/img/hero-4433.jpg"><p>Happy Hour every day</p></div>'
        self.assertEqual(menu_images(html, "https://x.example/happy-hour/"), [])

    def test_prose_that_happens_to_link_a_photo_is_not_a_menu(self):
        html = ('<a href="/x/party.jpg">Come join us for happy hour on the '
                'patio every Friday night</a>')
        self.assertEqual(menu_images(html, "https://x.example/happy-hour/"), [])

    def test_another_menu_linked_the_same_way_is_not_the_happy_hour(self):
        html = '<a href="/s/Dinner.png">Dinner Menu</a><a href="/s/G.png">View fullsize</a>'
        self.assertEqual(menu_images(html, "https://x.example/happy-hour/"), [])

    def test_the_href_must_be_an_image(self):
        html = '<a href="/happy-hour">Happy Hours</a>'
        self.assertEqual(menu_images(html, "https://x.example/"), [])


class APunOnTheThingIsTheThing(unittest.TestCase):
    """Sly Fox calls it "Appy Hour" and never says happy hour."""

    TEXT = ("DAILY SPECIALS\nTuesday-Friday: Appy Hour\n"
            "$2 off select appetizers and $1 wings from 3PM-6PM (dine-in only)\n")

    def test_heading_and_quote(self):
        self.assertTrue(crawl_sites.HH_HEADING_RE.search("Tuesday-Friday: Appy Hour"))
        qs = quotes(self.TEXT)
        self.assertTrue(any("3PM-6PM" in q for q in qs), qs)


class TheDayAboveTheHeadingOwnsIt(unittest.TestCase):
    """Sly Fox lists its specials as day / name / detail / time, one per
    line, so the day under a time is the NEXT special's heading."""

    LINES = ['thursday', '$12 burger & a pint', 'tuesday-friday', 'appy hour',
             'on wings & select apps', '3:00pm-6:00pm', 'saturday',
             'mystery pitcher']

    def test_saturday_is_not_the_appy_hours(self):
        qs = quotes(chr(10).join(self.LINES))
        q = [x for x in qs if 'appy hour' in x][0]
        self.assertEqual(q, 'tuesday-friday / appy hour / 3:00pm-6:00pm')
        ws = extract_deals.windows_from(q)
        self.assertEqual({w['dow'] for w in ws}, {2, 3, 4, 5})

    def test_no_day_above_keeps_the_forward_rule(self):
        q = quotes(chr(10).join(['HAPPY HOUR', 'mon - fri', '4pm - 6pm']))[0]
        self.assertEqual(q, 'HAPPY HOUR / mon - fri / 4pm - 6pm')


class ALigatureIsNotADifferentWord(unittest.TestCase):
    def test_off_set_as_one_glyph(self):
        self.assertEqual(crawl_sites.pdf_clean('$20 O\ufb00 Reserve Wines / Tru\ufb04e Fries'),
                         '$20 Off Reserve Wines / Truffle Fries')


class ADaysSpecialsAreNotTheHappyHoursPrices(unittest.TestCase):
    """Revival's card said $6 margaritas: Margherita Monday off /daily-specials."""

    def test_vouched(self):
        v = extract_prices_llm.vouched
        self.assertFalse(v({"url": "https://r.example/daily-specials", "quote": "x"}))
        self.assertTrue(v({"url": "https://r.example/daily-specials", "quote": "x", "hh": True}))
        self.assertTrue(v({"url": "https://r.example/happy-hour", "quote": "x"}))
        self.assertFalse(v({"url": "https://r.example/menus/weekly_specials.pdf", "quote": "x"}))


class AMenuPictureCanStateTheHours(unittest.TestCase):
    """Rivertown Taps publishes nothing in text; its happy hour is a PNG on
    /menu/ that says "( Wednesday through Friday 3pm to 6pm )". The vision
    pass keeps its transcript, and the deal extractor runs windows_from()
    over the happy-hour lines of it and nothing else."""

    SCRIPT = ("Happy Hour\n( Wednesday through Friday 3pm to 6pm )\n"
              "$10 Classic Cocktails\n-Margarita\nLunch Special\n"
              "( Wednesday through Sunday open to 4pm )\n$15 Pasta & Salad Combo\n"
              "Sunday Brunch\nBrunch served every Sunday from 11am - 2pm")

    def test_only_the_happy_hour_lines_are_spans(self):
        got = extract_deals.picture_spans(
            {"rivertown-taps-phoenixville": {"url": "https://x/hh.png", "transcript": self.SCRIPT}})
        url, spans = got["rivertown-taps-phoenixville"]
        self.assertEqual(url, "https://x/hh.png")
        self.assertEqual(len(spans), 1)
        self.assertNotIn("Brunch", spans[0])
        ws = extract_deals.windows_from(spans[0])
        self.assertEqual({w["dow"] for w in ws}, {3, 4, 5})
        self.assertEqual({(w["start"], w["end"]) for w in ws}, {("15:00", "18:00")})

    def test_a_sheet_with_no_happy_hour_line_proposes_nothing(self):
        self.assertEqual(extract_deals.picture_spans(
            {"v": {"url": "u", "transcript": "Lunch Special\nopen to 4pm"}}), {})


class ADaysSpecialsPageIsNotWorthAHappyHourRead(unittest.TestCase):
    """Revival's /daily-specials says HAPPY HOUR MENU in its nav and states
    seven prices. The page reader must not spend a call on it."""

    TEXT = 'HAPPY HOUR MENU / MARGHERITA MONDAY / $6 margaritas / $8 martinis'

    def test_refused_by_its_own_url(self):
        wr = read_pages_llm.worth_reading
        self.assertFalse(wr('https://r.example/daily-specials', self.TEXT))
        self.assertTrue(wr('https://r.example/happy-hour-menu', self.TEXT))
        self.assertTrue(wr('https://r.example/menus', self.TEXT))


class OneNumberSaysWhatAShellIs(unittest.TestCase):
    """report_holes names the shell class; crawl_sites owns the fix for it.

    While each carried its own constant (40 in the report, 25 in the gate) there
    was a band of pages reported to a human as "the headless tier, and it is the
    same fix for all of them" that the render gate then refused. Chikara Sushi's
    36-line homepage sat in it.
    """

    def test_the_report_and_the_gate_agree(self):
        import report_holes
        self.assertIs(report_holes.SHELL_LINES, crawl_sites.RENDER_LINE_FLOOR)


class TheHeadingIsTheContainment(unittest.TestCase):
    """What replaces the URL as the key to the looser price rules.

    65 of the 84 priceless board cards came from a page whose URL names neither
    happy-hour nor specials, and the prices were on it the whole time. Chili's
    puts its happy hour on the LOCATION page; CO-OP puts it a third of the way
    down /menus, between 'Mid Day' and 'Dinner'. The URL cannot see either.

    So the key becomes the page's own heading -- and the boundaries of the
    section it opens are the entire safety argument, because the same page also
    holds the dinner menu. These are the boundaries, written before the harvest.

    The boundary is asserted on hh_sections() rather than on quotes(), because
    quotes() answers a different question: DEAL_RE matches the words 'Happy
    Hour' wherever they appear, section or no section, and always did. What is
    new here is only WHICH LINES are allowed the looser priced-line rules.
    """

    def _in_section(self, html):
        """The lines the containment admits, as text."""
        text = visible_text(html)
        lines = text.split("\n")
        return [lines[i] for i in sorted(hh_sections(html, text))]

    # CO-OP's /menus, cut to shape: a real <h2> opens the happy hour and the
    # next <h2> closes it. The dinner price below is the one that must not be
    # harvested -- the Deviled Eggs are $8 at happy hour and $12 at Mid Day, so
    # a section that runs on does not merely add noise, it prints a WRONG PRICE.
    COOP = ("<h2>Mid Day</h2><p>Daily from 2pm - 4pm</p>"
            "<p>Deviled Eggs</p><p>$ 12</p>"
            "<h2>Happy Hour</h2><p>Weekdays from 3pm - 6pm</p>"
            "<h3>Food Specials</h3><p>Deviled Eggs</p><p>$ 8</p>"
            "<h3>Drink Specials</h3><p>Select Beer</p><p>$ 5</p>"
            "<h2>Dinner</h2><p>Served 4pm to 10pm</p>"
            "<p>Cheese Board</p><p>$ 24</p>")

    def test_the_section_opens_at_the_heading_that_names_it(self):
        got = self._in_section(self.COOP)
        self.assertIn("$ 8", got)
        self.assertIn("$ 5", got)

    def test_a_sub_heading_does_not_close_its_own_section(self):
        # Found on the real CO-OP page, not in a fixture: the happy hour is an
        # <h2> and it is divided into <h3> 'Food Specials' and 'Drink Specials'.
        # Closing on the next heading of ANY rank closed the section on its own
        # first sub-heading and harvested one line. A section is closed by a
        # heading of the same rank or higher -- which is what rank is for.
        got = self._in_section(self.COOP)
        self.assertIn("$ 8", got)
        self.assertIn("$ 5", got)
        self.assertIn("Drink Specials", got)
        self.assertNotIn("$ 24", got)

    def test_the_section_closes_at_the_next_heading(self):
        # $ 24 is dinner. It sits BELOW the happy hour on the same page.
        self.assertNotIn("$ 24", self._in_section(self.COOP))

    def test_the_section_does_not_reach_backwards(self):
        # $ 12 is the same dish at its Mid Day price, printed ABOVE the heading.
        # A price above the heading is not in the section the heading opened.
        self.assertNotIn("$ 12", self._in_section(self.COOP))

    def test_the_happy_hour_price_is_harvested_with_its_item(self):
        text = visible_text(self.COOP)
        got = quotes(text, hh_lines=hh_sections(self.COOP, text))
        self.assertTrue(any("$ 8" in q and "Deviled Eggs" in q for q in got), got)
        self.assertFalse(any("$ 24" in q for q in got), got)

    # El Vez lists all six menus as nav links, 'Happy Hour' among them, and then
    # prints the lunch and dinner menus in full. A nav link is not a heading:
    # if it opened a section, every price on the page would be a happy-hour
    # price. The right outcome here is NOTHING, not a wrong answer.
    ELVEZ = ("<h2>Menus</h2>"
             "<a>Lunch</a><a>Dinner</a><a>Happy Hour</a><a>Kid's Menu</a>"
             "<h3>Appetizers</h3><p>Tuna Tostadas $18</p>"
             "<h3>Entrees</h3><p>Carne Asada $34</p>")

    def test_a_nav_link_named_happy_hour_opens_nothing(self):
        self.assertEqual(self._in_section(self.ELVEZ), [])

    # Chili's location page has NO heading tags anywhere -- the whole page is
    # divs. Its happy hour is nonetheless a heading in every sense a reader
    # cares about: a short line naming the thing, with the window under it and
    # the prices under that. A page with no headings at all falls back to the
    # short standalone line, and the section is then capped rather than closed,
    # because there is no next heading to close it on.
    CHILIS = ("<div>Hours of Operation</div><div>SUNDAY - THURSDAY</div>"
              "<div>11:00 AM - 10:00 PM</div>"
              "<div>Happy Hour</div><div>MONDAY-THURSDAY</div><div>3-6pm</div>"
              "<div>$3</div><div>Bud Light 16 oz</div>"
              "<div>$5</div><div>House Red &amp; White Wine</div>")

    def test_a_page_with_no_headings_falls_back_to_the_standalone_line(self):
        got = self._in_section(self.CHILIS)
        self.assertIn("$3", got)
        self.assertIn("$5", got)
        self.assertNotIn("11:00 AM - 10:00 PM", got)   # above the heading

    def test_the_fallback_price_reaches_the_quote_with_its_item(self):
        html = self.CHILIS
        text = visible_text(html)
        got = quotes(text, hh_lines=hh_sections(html, text))
        self.assertTrue(any("$3" in q and "Bud Light" in q for q in got), got)
        self.assertTrue(any("$5" in q and "House Red" in q for q in got), got)

    def test_the_fallback_is_refused_when_the_page_does_have_headings(self):
        # The same divs, with one real heading elsewhere on the page. Once a
        # page proves it marks its headings up, an unmarked line is not one --
        # otherwise El Vez's nav would open a section on every menu page.
        self.assertEqual(self._in_section("<h1>Our Menus</h1>" + self.CHILIS), [])

    def test_a_sentence_is_not_a_heading(self):
        # 'Join us for the best HAPPY HOUR in town, every day!' is prose. Prose
        # that names the happy hour is everywhere; it must not unlock a page.
        page = ("<div>Join us for the best HAPPY HOUR in town, every day!</div>"
                "<div>Cheese Board</div><div>$ 24</div>")
        self.assertEqual(self._in_section(page), [])

    def test_the_section_is_capped_so_a_runaway_cannot_eat_the_menu(self):
        # No heading follows, so nothing closes the section. The cap does.
        page = "<div>Happy Hour</div>" + "".join(
            "<div>Course %d</div><div>$ %d</div>" % (i, 100 + i) for i in range(60))
        got = self._in_section(page)
        self.assertIn("$ 100", got)
        self.assertNotIn("$ 159", got)

    def test_an_unmarked_nav_strip_is_closed_by_the_menu_it_sits_beside(self):
        # The fallback's real hazard: a page with no marked headings whose only
        # mention of the happy hour is a nav strip, with a dinner menu under it.
        # Nothing here is a heading tag, so the fallback DOES open a section --
        # and the very next nav item closes it before a price is reached.
        page = ("<div>Menus</div><div>Happy Hour</div><div>Dinner</div>"
                "<div>Steak</div><div>$ 42</div><div>Salmon</div><div>$ 34</div>")
        self.assertEqual(self._in_section(page), [])

    def test_an_ordinary_page_is_unchanged_when_no_heading_names_it(self):
        # The guarantee the URL key gave us, kept: a page that never names its
        # happy hour harvests nothing, exactly as before.
        page = ("<h2>Dinner</h2><p>Cheese Board</p><p>$ 24</p>"
                "<h2>Dessert</h2><p>Churros</p><p>$ 9</p>")
        text = visible_text(page)
        self.assertEqual(hh_sections(page, text), set())
        self.assertEqual(quotes(text, hh_lines=hh_sections(page, text)), [])


class APricedQuoteWithNoClockIsStillAPrice(unittest.TestCase):
    """Paladar's '$4.50 Draft Beer' was crawled, stored, and then dropped.

    items_in() is fed only from the quotes that state a SCHEDULE, because those
    are the ones that become windows. A price line rarely states a schedule --
    the venue printed the hours once, at the top, and the prices under them. So
    the price was on disk the whole time and never reached the card. 59 of the
    146 priceless venues are in exactly this position and need no crawl at all.

    The containment: an unscheduled priced quote counts only when it came from
    the SAME PAGE as the schedule we published. That is the page the venue
    itself put its happy hour on, which is the argument the URL key always made.
    """

    HH = "https://x.test/happy-hour/"

    def _hits(self, *pairs):
        return [{"url": u, "quote": q} for u, q in pairs]

    def test_a_price_from_the_lead_page_reaches_the_card(self):
        items = extract_deals.items_from_hits(
            self._hits((self.HH, "HAPPY HOUR / Monday-Friday 4-6:30pm"),
                       (self.HH, "$4.50 Draft Beer")), self.HH)
        self.assertIn(4.5, [i.get("price_usd") for i in items])

    def test_a_price_from_another_page_does_not(self):
        # The dinner menu lives at /menus and its prices are not the deal.
        items = extract_deals.items_from_hits(
            self._hits((self.HH, "HAPPY HOUR / Monday-Friday 4-6:30pm"),
                       ("https://x.test/menus", "$34 draft steak")), self.HH)
        self.assertEqual([i.get("price_usd") for i in items], [])

    def test_the_scheduled_quote_still_contributes_its_own_prices(self):
        items = extract_deals.items_from_hits(
            self._hits((self.HH, "HAPPY HOUR 4-6pm / $5 drafts")), self.HH)
        self.assertIn(5.0, [i.get("price_usd") for i in items])



class LateNightEndingAtTwelve(unittest.TestCase):
    """'LATE NIGHT HAPPY HOUR FRIDAY ONLY 10-12PM' read as noon forced the start
    back to 10am and published a Friday MORNING happy hour."""

    def test_a_pm_start_cannot_end_at_noon(self):
        self.assertEqual(window_in("10-12PM"), ("22:00", "24:00"))

    def test_a_window_that_really_does_cross_noon_still_does(self):
        self.assertEqual(window_in("11 - 2 pm"), ("11:00", "14:00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ASectionMustNotCloseOnTheHappyHoursOWNSUBHEADING(unittest.TestCase):
    """The containment closed the section on lines the happy hour itself owns.

    hh_sections() opens at a heading naming the happy hour and closes at the
    next heading naming anything else. Two kinds of heading were closing it that
    are not another menu at all, and both were found by reading the pages Paul
    sent rather than by the suite:

      Paladar    <h3>DRINKS</h3> -- a SUBDIVISION, but SUBDIVISION_RE spelled
                 its nouns singular, so `drink` did not match 'DRINKS'. The
                 section closed one line after it opened and all six of the
                 venue's prices sat outside it. The asymmetry was accidental:
                 `snack` and `bite` already survived in the plural through the
                 trailing branch, and `drink` did not.

      Sullivan's <h2>Available in the bar, Monday-Thursday 3pm-6pm</h2> -- the
                 happy hour's OWN HOURS, marked up as a heading. It closed the
                 section on the line after the open and put the whole menu out
                 of reach. No menu is titled with a clock time.

    The fixtures carry the real pages' nesting: the prices are in their own
    boxes below the subheading, which is the arrangement that was being lost.
    """

    PALADAR = ("<h1>Happy Hour</h1>"
               "<h3>HAPPY HOUR DETAILS</h3>"
               "<div><p>Monday-Friday</p><p>from 4-6:30pm in the Bar</p></div>"
               "<h3>DRINKS</h3>"
               "<div><p>$4.50 Draft Beer</p></div>"
               "<div><p>$6.50 Sangrias (White or Red)</p></div>")

    SULLIVANS = ("<h1>King Of Prussia Happy Hour Menu</h1>"
                 "<h2>Available in the bar, Monday-Thursday 3pm-6pm</h2>"
                 "<div><p>$8 Select Red, White &amp; Sparkling Wines</p></div>")

    def section(self, html):
        lines, _ = crawl_sites.text_lines(html)
        inside = crawl_sites.hh_sections(html, "\n".join(lines))
        return [lines[i] for i in sorted(inside)]

    def test_a_plural_subdivision_heading_does_not_close_the_section(self):
        kept = self.section(self.PALADAR)
        self.assertIn("$4.50 Draft Beer", kept)
        self.assertIn("$6.50 Sangrias (White or Red)", kept)

    def test_the_singular_and_plural_forms_agree(self):
        for word in ("DRINK", "DRINKS", "COCKTAIL", "COCKTAILS",
                     "BEER", "BEERS", "WINE", "WINES", "SHOT", "SHOTS"):
            self.assertTrue(crawl_sites.SUBDIVISION_RE.search(word), word)

    def test_a_heading_that_states_the_hours_does_not_close_the_section(self):
        self.assertIn("$8 Select Red, White & Sparkling Wines",
                      self.section(self.SULLIVANS))

    def test_a_dinner_menu_heading_still_closes_it(self):
        html = (self.PALADAR.replace("<h3>DRINKS</h3>", "<h3>DINNER</h3>"))
        self.assertNotIn("$4.50 Draft Beer", self.section(html))


class APriceWrittenFIRSTIsStillAPricedMenuLine(unittest.TestCase):
    """MENU_ITEM_RE is anchored to the end of the line and reads price-LAST only.

    A venue that prints '$4.50 Draft Beer' publishes exactly as much as one that
    prints 'Draft Beer $4.50', and the crawler could not see the first form at
    all -- Paladar has six priced lines on its own happy-hour page and only the
    one DEAL_RE happened to match on the word 'Draft' was ever stored. The
    extractor grew the mirror of this (TRAILING_PRICE_RE) a session earlier; the
    crawler did not, so the lines were thrown away one step before it.

    Scoped to `loose` exactly as MENU_ITEM_RE is, so the containment argument is
    unchanged: on an arbitrary page neither form is read.
    """

    def test_a_price_first_line_is_kept_inside_a_happy_hour_section(self):
        text = "Happy Hour\n$6.50 Sangrias (White or Red)"
        self.assertTrue(any("Sangrias" in q for q in
                            crawl_sites.quotes(text, hh_lines={1})))

    def test_it_is_refused_on_a_page_that_named_nothing(self):
        text = "Our Menu\n$6.50 Sangrias (White or Red)"
        self.assertFalse(any("Sangrias" in q for q in crawl_sites.quotes(text)))


class AnAmountOFFIsNotAPrice(unittest.TestCase):
    """'$2 Off Wine by the Glass' is not a $2 glass of wine.

    PRICE_RE read it as one -- label 'Off Wine by the Glass', category wine,
    price $2.00 -- and 17 items across 13 venues were live on the board in that
    shape: Lansdale Tavern's card said 'off draft beer $1.00'. The moment the
    crawler stopped discarding these lines the count would have grown.

    The model pass makes the identical mistake and verify() could not catch it,
    because both the '$5' and the 'martinis' really are in Sullivan's own text:
    it returned a $5 martini for '$5 Off Select Martinis'. The check is that the
    number is written somewhere as a PRICE, not only as an amount off.

    The pipeline DOES have a dollars-off field -- `amount_off_usd`, checked by
    both validators, rendered by itemParts() and ranked by itemValue() -- so the
    line is now read as the discount it is. What must never happen is the
    number arriving as a PRICE, and that is what these tests hold.
    """

    def test_the_deterministic_pass_reads_it_as_a_discount_not_a_price(self):
        got = extract_deals.items_in("$2 Off Wine by the Glass")
        self.assertEqual(got, [{"category": "wine", "label": "Wine by the Glass",
                                "amount_off_usd": 2.0}])
        self.assertNotIn("price_usd", got[0])
        got = extract_deals.items_in("$1 off drafts")
        self.assertEqual(got, [{"category": "draft", "label": "drafts",
                                "amount_off_usd": 1.0}])

    def test_a_real_price_on_the_same_page_is_untouched(self):
        got = extract_deals.items_in("$4.50 Draft Beer")
        self.assertEqual([(i["label"], i["price_usd"]) for i in got],
                         [("Draft Beer", 4.5)])

    def test_a_word_merely_starting_with_off_is_not_an_off(self):
        self.assertEqual(extract_deals.category_of("Offal Plate"), None)


class TheModelPassAlsoMustNotReadAnOFFAsAPrice(unittest.TestCase):
    """verify() checks the digits are in the venue's text, not what they mean.

    Sullivan's page says '$5 Off Select Martinis'. The model returned a $5
    martini and every existing check passed it, because both the '$5' and the
    'martinis' really are in the venue's own sentence -- which is the whole
    safety argument of this pass, and it is not enough on its own. It shipped
    into data/deals_prices_llm.json on the first run of this session.
    """

    TEXT = ("King Of Prussia Happy Hour Menu / $5 Off Select Martinis / "
            "$8 Select Red, White & Sparkling Wines")

    def test_an_amount_only_ever_written_as_off_is_refused(self):
        clean, why = verify({"category": "cocktail", "label": "martinis",
                             "price_usd": 5.0,
                             "evidence": "$5 Off Select Martinis"}, self.TEXT)
        self.assertIsNone(clean)
        self.assertIn("OFF", why)

    def test_a_real_price_in_the_same_text_still_passes(self):
        clean, why = verify(
            {"category": "wine", "label": "wine", "price_usd": 8.0,
             "evidence": "$8 Select Red, White & Sparkling Wines"}, self.TEXT)
        self.assertEqual(why, None)
        self.assertEqual(clean["price_usd"], 8.0)

    def test_a_price_written_both_ways_is_kept(self):
        text = "$5 Off Martinis / Draft Beer $5"
        clean, why = verify({"category": "draft", "label": "draft beer",
                             "price_usd": 5.0,
                             "evidence": "Draft Beer $5"}, text)
        self.assertEqual(why, None)


class ADiscountHeadingDoesNotPriceTheLinesUnderIt(unittest.TestCase):
    """Two Stones heads its happy-hour drafts '$2 OFF' and its cocktails '$3 OFF'.

    heading_prices() read the '$2' off that heading and stamped it, as a PRICE,
    on every draft beneath it; the extractor then read '$2 OFF / $2.00 Delco
    Lager' as a two-dollar beer. Four Two Stones cards carried 20 such prices
    on the live board (Paul, 2026-09-02: "im still seeing things missing").
    The amount still travels down; the word 'off' now travels with it, and the
    extractor reads the older on-disk form under that heading the same way.
    """

    HTML = ("<div><h3>Happy Hour</h3>"
            "<div><h4>$2 OFF</h4><p>Delco Lager</p><p>Pony Boi</p></div>"
            "<div><h4>$3 OFF</h4><p>The Mule</p></div></div>")

    def quotes(self):
        lines, stacks, emph = crawl_sites.text_lines_emph(self.HTML)
        text = "\n".join(lines)
        hh = frozenset(range(len(lines)))
        head = crawl_sites.heading_prices(self.HTML, text, hh, stacks)
        return crawl_sites.quotes(text, hh_lines=hh, stacks=stacks, emph=emph,
                                  head_prices=head)

    def test_the_crawler_carries_the_word_off_down_with_the_amount(self):
        found = self.quotes()
        self.assertIn("$2 OFF / $2.00 off Delco Lager", found)
        self.assertIn("$3 OFF / $3.00 off The Mule", found)
        self.assertNotIn("$2 OFF / $2.00 Delco Lager", found)

    def test_the_extractor_reads_it_as_a_discount(self):
        self.assertEqual(
            extract_deals.items_in("$2 OFF / $2.00 off Delco Lager"),
            [{"category": "draft", "label": "Delco Lager", "amount_off_usd": 2.0}])

    def test_the_older_on_disk_form_under_that_heading_is_a_discount_too(self):
        self.assertEqual(
            extract_deals.items_in("$3 OFF / $3.00 The Mule"),
            [{"category": "cocktail", "label": "The Mule", "amount_off_usd": 3.0}])

    def test_a_priced_heading_is_untouched(self):
        self.assertEqual(
            extract_deals.items_in("SNACKS $7.50 each / $7.50 Traditional Guacamole"),
            [{"category": "food", "label": "Traditional Guacamole", "price_usd": 7.5}])


class APageThatShipsItselfToItsOwnJavaScript(unittest.TestCase):
    """McGlynn's Pub, 2026-09-02, named by Paul. Twenty-two visible lines and
    the whole happy hour in window.POPMENU_APOLLO_STATE. Four sessions had
    answered this shape with a per-platform adapter; this reads it with no
    platform knowledge at all."""

    SHELL = (
        '<html><body><div>Welcome</div>'
        '<script>window.POPMENU_APOLLO_STATE = {"MenuSection:9":{'
        '"name":"Happy Hour Food Specials",'
        '"description":"Monday-Friday, 4-6PM at the bar",'
        '"slug":"/happy-hour","color":"#ffffff",'
        '"img":"https://cdn.example.com/a.png"},'
        '"items":["Draft Beer $4","Wings"]};</script></body></html>'
    )

    def test_the_window_is_recovered_from_the_embedded_state(self):
        got = crawl_sites.embedded_json_lines(self.SHELL)
        self.assertIn("Monday-Friday, 4-6PM at the bar", got)
        self.assertIn("Happy Hour Food Specials", got)

    def test_urls_colours_and_single_words_are_not_prose(self):
        got = crawl_sites.embedded_json_lines(self.SHELL)
        self.assertNotIn("https://cdn.example.com/a.png", got)
        self.assertNotIn("#ffffff", got)
        self.assertNotIn("/happy-hour", got)
        self.assertNotIn("Wings", got)   # one word is a label, not a sentence

    def test_a_page_with_no_embedded_object_yields_nothing(self):
        self.assertEqual(crawl_sites.embedded_json_lines("<p>plain</p>"), [])

    def test_the_harvest_never_reaches_the_regex_quote_passes(self):
        # The strings are stored for the MODEL. An unlabelled bag of strings
        # given to quotes() would fabricate deals, so the crawler must not
        # find a quote in a page whose only content is embedded.
        lines, stacks, emph = crawl_sites.text_lines_emph(self.SHELL)
        found = crawl_sites.quotes("\n".join(lines), stacks=stacks, emph=emph)
        self.assertEqual(found, [])

    def test_the_saved_page_marks_where_the_embedded_text_begins(self):
        import tempfile, json as _json, os as _os
        old = crawl_sites.PAGES
        try:
            crawl_sites.PAGES = tempfile.mkdtemp()
            crawl_sites.save_page("L1", "https://x.co/hh", "t", ["Welcome"],
                                  embedded=["Monday-Friday, 4-6PM at the bar"])
            fn = _os.path.join(crawl_sites.PAGES,
                               crawl_sites.page_key("L1", "https://x.co/hh"))
            page = _json.load(open(fn, encoding="utf-8"))
        finally:
            crawl_sites.PAGES = old
        self.assertEqual(page["visible_lines"], 1)
        self.assertEqual(page["embedded"], 1)
        self.assertIn("[the page's embedded data, not visible text]",
                      page["lines"])
        self.assertIn("Monday-Friday, 4-6PM at the bar", page["lines"])


class AVenueThatPublishesItsHoursAsDATANotAsAPage(unittest.TestCase):
    """Darden's sites have nothing in their HTML for any parser here to read.

    yardhouse.com/happy-hour is a 2,694-byte Next.js shell behind an Akamai bot
    manager: __NEXT_DATA__ carries empty pageProps and every line of the menu
    arrives from JavaScript. Yard House, Seasons 52, Eddie V's and The Capital
    Grille -- four King of Prussia venues -- all came back with nothing, and it
    read as 'this bar published no happy hour' when in fact it published one and
    we could not see it. Rendering the page in a real browser does not fix it
    either: /happy-hour will not show anything until you pick a location.

    Its own API answers, with one header and no browser, and states the hours as
    structured data under hourCode 'HH'. That is the venue speaking about
    itself, so it is turned back into a quote and run through the same extractor
    and the same validators as a line scraped off a page. The point of the
    grouping below is that days sharing a window are named in ONE sentence:
    the extractor reads days and a time out of a single quote, so a quote per
    day would have published only one of the five.
    """

    REST = {"restaurantHours": [
        {"day": d, "hoursInfo": [
            {"hourCode": "HH", "startTime": "3:30 PM", "endTime": "6:00 PM"},
            {"hourCode": "OP", "startTime": "11:00 AM", "endTime": "11:30 PM"},
        ]} for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
    ] + [
        {"day": "Saturday", "hoursInfo": [
            {"hourCode": "LNHH", "startTime": "10:00 PM", "endTime": "12:00 PM"},
        ]},
    ]}

    def test_a_darden_location_url_is_recognised(self):
        self.assertEqual(
            crawl_sites.darden_ref("https://www.yardhouse.com/locations/pa/"
                                   "king-of-prussia/kop-mall/8371?cmpid=br:yh"),
            ("yardhouse.com", "8371"))

    def test_a_brand_on_a_mobile_host_is_still_recognised(self):
        self.assertEqual(
            crawl_sites.darden_ref("https://m.thecapitalgrille.com/locations/"
                                   "pa/king-of-prussia/king-of-prussia/8043"),
            ("thecapitalgrille.com", "8043"))

    def test_an_ordinary_venue_is_left_alone(self):
        self.assertIsNone(
            crawl_sites.darden_ref("https://paladarlatinkitchen.com/happy-hour/"))

    def test_days_sharing_a_window_are_named_in_one_quote(self):
        self.assertEqual(
            crawl_sites.darden_lines(self.REST),
            ["Happy Hour / Monday, Tuesday, Wednesday, Thursday, Friday"
             " / 3:30 PM - 6:00 PM"])

    def test_only_the_happy_hour_code_is_read(self):
        line = crawl_sites.darden_lines(self.REST)[0]
        self.assertNotIn("11:00 AM", line)
        self.assertNotIn("10:00 PM", line)

    def test_the_quote_survives_the_ordinary_extractor(self):
        got = extract_deals.windows_from(crawl_sites.darden_lines(self.REST)[0])
        self.assertEqual(sorted(w["dow"] for w in got), [1, 2, 3, 4, 5])
        self.assertEqual({(w["start"], w["end"]) for w in got},
                         {("15:30", "18:00")})


class WhoseLawIsThisDealBeingJudgedBy(unittest.TestCase):
    """validate_deal() enforces PENNSYLVANIA's Acts 57 & 86, not liquor law.

    The 4h/day cap, the 24h/week cap, the midnight cutoff, the 2 food+drink
    combos per day and the BANNED list are all PA's numbers, and every deal on
    the board is gated on them. That was safe while every venue sat in one of
    five PA counties. It stops being safe the moment Wilmington is published:
    judging a Delaware bar by Pennsylvania's statute can SUPPRESS a lawful DE
    deal and, worse, PUBLISH one PA would have banned. The hazard runs in both
    directions, which is why a default of 'assume PA' is the wrong shape.

    So the rules are a table keyed by state and a state with no entry has no
    ruleset. Delaware was deliberately absent until 2026-09-02, when it was
    researched to a named authority (4 Del. Admin. Code s 908 Rule 3.0) and
    signed off by Paul.

    The finding is the point: DELAWARE SETS NO HOUR CAP AND NO CUTOFF. Copying
    PA's numbers across -- the thing the comment forbade -- would have refused
    a lawful five-hour Wilmington happy hour, and would have looked right,
    because the two states' BANNED lists happen to agree.
    """

    def test_the_state_is_read_off_the_address(self):
        self.assertEqual(
            state_of("700 W DEKALB PK, KING OF PRUSSIA PA 19406"), "PA")
        self.assertEqual(
            state_of("1201 N Market St, Wilmington DE 19801"), "DE")

    def test_an_address_naming_no_state_is_not_assumed_to_be_pa(self):
        self.assertIsNone(state_of("somewhere with no state"))
        self.assertIsNone(state_of(""))
        self.assertIsNone(state_of(None))

    def test_a_state_we_have_not_researched_has_no_ruleset(self):
        self.assertIsNotNone(rules_for("PA"))
        self.assertIsNotNone(rules_for("DE"))
        for unknown in ("NJ", "MD", "NY", None):
            self.assertIsNone(rules_for(unknown))

    def test_delaware_carries_its_own_authority_and_a_sign_off(self):
        de = rules_for("DE")
        self.assertIn("908", de["authority"])
        self.assertTrue(de.get("signed_off_by"))

    def test_delaware_sets_no_hour_cap_and_pa_still_does(self):
        self.assertIsNone(rules_for("DE")["max_hours_per_day"])
        self.assertIsNone(rules_for("DE")["max_hours_per_week"])
        self.assertEqual(rules_for("PA")["max_hours_per_day"], 4.0)

    def test_a_five_hour_window_is_lawful_in_delaware_and_not_in_pennsylvania(self):
        long_deal = deal(windows=[{"dow": 3, "start": "16:00", "end": "21:00"}])
        self.assertEqual(validate_deal(long_deal, "DE"), [])
        self.assertTrue(any("4h/day" in e for e in validate_deal(long_deal, "PA")))

    def test_a_state_with_no_ruleset_refuses_the_deal_here_too(self):
        errs = validate_deal(deal(), "NJ")
        self.assertTrue(any("no ruleset" in e for e in errs))
        self.assertTrue(any("no ruleset" in e for e in validate_deal(deal(), None)))

    def test_delaware_still_refuses_what_delaware_law_bans(self):
        for claim in ("all-you-can-drink wings", "bottomless mimosas",
                      "2 for 1 drafts", "open bar"):
            errs = validate_deal(
                deal(items=[{"category": "draft", "label": claim, "price_usd": 5.0}]),
                "DE")
            self.assertTrue(errs, f"{claim!r} is lawful in DE?")

    def test_the_pa_ruleset_still_carries_pas_own_numbers(self):
        pa = rules_for("PA")
        self.assertEqual(pa["max_hours_per_day"], 4.0)
        self.assertEqual(pa["max_hours_per_week"], 24.0)
        self.assertEqual(pa["max_food_combos_per_day"], 2)
        self.assertIn("Acts 57 & 86", pa["authority"])


class AGateOnlyAtWRITETimeCannotFixWhatIsALREADYWritten(unittest.TestCase):
    """verify() runs when an item is first read, and the sidecar is trusted after.

    That is why three `$X off` labels stayed on the LIVE board after the guard
    that refuses them had already shipped: `data/deals_prices_llm.json` was
    written before the guard existed, and build_bundles.py consults the file
    precisely because everything in it was checked once. Black Horse Tavern's
    "$1 off pints during Happy Hour" was published as `pints $1.00` by a build
    that ran entirely correct code.

    So verify() has to be re-runnable over the file it already wrote. The
    general shape: when you tighten a gate, ask what is already through it.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.out = os.path.join(self.dir, "prices.json")
        self.patches = [
            unittest.mock.patch.object(extract_prices_llm, "OUT", self.out),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def _run(self, sidecar, quotes):
        with open(self.out, "w", encoding="utf-8") as fh:
            json.dump(sidecar, fh)
        with unittest.mock.patch.object(
                extract_prices_llm, "quotes_by_venue", lambda: quotes):
            extract_prices_llm.reverify(unittest.mock.Mock())
        return json.load(open(self.out, encoding="utf-8"))

    def test_an_amount_off_already_in_the_sidecar_is_dropped(self):
        kept = self._run(
            {"black-horse": [{"category": "draft", "label": "pints",
                              "price_usd": 1.0}]},
            {"black-horse": "$1 off pints during Happy Hour"})
        self.assertEqual(kept, {})

    def test_a_real_price_already_in_the_sidecar_survives(self):
        kept = self._run(
            {"sullivans": [{"category": "food", "label": "Angry Shrimp",
                            "price_usd": 20.0}]},
            {"sullivans": "Happy Hour\nAngry Shrimp $20"})
        self.assertEqual(list(kept), ["sullivans"])
        self.assertEqual(kept["sullivans"][0]["price_usd"], 20.0)

    def test_a_venue_with_no_quotes_left_is_dropped_not_kept_on_trust(self):
        kept = self._run(
            {"gone": [{"category": "food", "label": "fries", "price_usd": 5.0}]},
            {})
        self.assertEqual(kept, {})

    def test_the_previous_sidecar_is_kept_because_hits_are_written_mid_crawl(self):
        self._run({"gone": [{"category": "food", "label": "fries",
                             "price_usd": 5.0}]}, {})
        back = json.load(open(self.out + ".bak", encoding="utf-8"))
        self.assertEqual(list(back), ["gone"])

    def test_an_item_it_cannot_reconstruct_evidence_for_is_kept_not_dropped(self):
        """'50% off' is written 'half price' and carries no 50 anywhere.

        A reconstruction that finds no candidate line is a failure of the
        reconstruction, not a verdict on the item -- and the item passed a real
        verify() once. Dropping here would delete good published data on an
        artifact, which is how a first attempt at this silently binned 15 live
        items across 10 venues.
        """
        kept = self._run(
            {"pj-whelihan": [{"category": "food", "label": "wings and starters",
                              "discount_pct": 50.0}]},
            {"pj-whelihan": "Happy Hour: half price wings and starters"})
        self.assertEqual(list(kept), ["pj-whelihan"])


class TheMenuRatchetRefusesARisingNumberOfSilentWindows(unittest.TestCase):
    """A window that names no item is the shape of a scraper failure, and the
    count of ones nobody has explained may not rise.

    This is the only part of the menu work that survives into the next zone: the
    parser fixes travel, but nothing else stops a new area from arriving with a
    hundred cards that name nothing and shipping them quietly. The budget is a
    ratchet -- every fix lowers it, and raising it is a decision somebody makes
    on purpose. Both answers are exercised here because a guard whose refusal
    has never been observed is decoration.
    """

    def zones(self, n_silent, n_full=1):
        vs = [{"id": f"s{i}", "lid": f"s{i}", "name": f"Silent {i}",
               "deals": [{"items": []}]} for i in range(n_silent)]
        vs += [{"id": f"f{i}", "lid": f"f{i}", "name": f"Full {i}",
                "deals": [{"items": [{"label": "drafts"}]}]} for i in range(n_full)]
        return {"a_zone": vs}

    def test_it_passes_at_the_ceiling(self):
        # 3 silent of 4 venues.
        holes = build_bundles.menu_ratchet(self.zones(3), {}, 0.75,
                                           out=lambda *_: None)
        self.assertEqual(holes, ["Silent 0", "Silent 1", "Silent 2"])

    def test_it_refuses_above_it(self):
        with self.assertRaises(SystemExit) as e:
            build_bundles.menu_ratchet(self.zones(4), {}, 0.75, out=lambda *_: None)
        self.assertIn("REFUSED", str(e.exception))

    def test_growth_at_the_same_rate_is_not_a_regression(self):
        """The reason this is a share and not a count.

        As a count it refused when reading days properly admitted 28 venues that
        had published nothing at all before -- no venue lost an item and two
        gained one, and the build still refused. A guard that fires on progress
        gets its number bumped until it means nothing.
        """
        build_bundles.menu_ratchet(self.zones(30, 10), {}, 0.75,
                                   out=lambda *_: None)

    def test_a_zone_that_names_nothing_still_refuses(self):
        with self.assertRaises(SystemExit):
            build_bundles.menu_ratchet(self.zones(40, 10), {}, 0.75,
                                       out=lambda *_: None)

    def test_a_recorded_verdict_accounts_for_a_venue(self):
        verdicts = {"s0": {"verdict": "no-menu-published"}}
        holes = build_bundles.menu_ratchet(self.zones(2), verdicts, 0.34,
                                           out=lambda *_: None)
        self.assertEqual(holes, ["Silent 1"])


class APlatformIsRecognisedByWhatItPublishes(unittest.TestCase):
    """The adapters triggered on hostnames somebody had typed in.

    That is how North Italia was found by Paul opening the site rather than by
    us: a sibling brand on the SAME menu platform misses in complete silence,
    and the next zone repeats it with brands nobody here has heard of. So the
    trigger is the platform's own signature -- the markup FRC prints, and the
    location-URL shape Darden's API answers on.
    """

    def test_frc_markup_names_the_platform_on_an_unknown_brand(self):
        self.assertTrue(crawl_sites.frc_markup(
            '<h4 class="menu-item-name">Pizza</h4><span class="menu-item-price">12</span>'))
        self.assertTrue(crawl_sites.frc_markup('<div data-section-slug="eat">'))
        self.assertFalse(crawl_sites.frc_markup("<p>Happy hour 4-6</p>"))

    def test_a_darden_shaped_url_is_probed_on_a_brand_we_never_listed(self):
        # The API either answers with a restaurant or it does not; the guess
        # costs one 404 and can publish nothing wrong.
        self.assertEqual(
            crawl_sites.darden_ref(
                "https://www.somebrand.com/locations/pa/king-of-prussia/kop-mall/8371"),
            ("somebrand.com", "8371"))

    def test_a_listed_brand_still_works_without_the_full_shape(self):
        self.assertEqual(
            crawl_sites.darden_ref("https://www.yardhouse.com/locations/pa/x/y/8371"),
            ("yardhouse.com", "8371"))

    def test_an_ordinary_location_page_is_not_darden(self):
        self.assertIsNone(crawl_sites.darden_ref(
            "https://locations.pjspub.com/pa/hatfield/190-forty-foot-road"))


class APriceCanBeSpelledOutInWords(unittest.TestCase):
    """Tommy's Tavern + Tap, King of Prussia, found by Paul 2026-09-01.

    A complete sixteen-item happy hour menu, published in plain text, with NOT
    ONE DOLLAR SIGN on the page: 'EIGHT DOLLARS' heads the food and the drinks
    are 'five dollar house wines' and 'two dollars off all draft beers'. Every
    money rule we have is anchored on '$', so the whole page read as silence.
    """

    def test_the_words_become_the_numeral(self):
        self.assertEqual(crawl_sites.word_prices("EIGHT DOLLARS"), "$8")
        self.assertEqual(crawl_sites.word_prices("five dollar house wines"),
                         "$5 house wines")

    def test_the_word_off_survives_so_it_lands_on_the_discount_rule(self):
        self.assertEqual(crawl_sites.word_prices("two dollars off all draft beers"),
                         "$2 off all draft beers")

    def test_a_number_that_is_not_a_price_is_left_alone(self):
        self.assertEqual(crawl_sites.word_prices("four cheese pizza"),
                         "four cheese pizza")


class ADayIsWrittenTheWayPeopleWriteDays(unittest.TestCase):
    """The day grammar read 'Mon-Fri' and nothing else people actually type."""

    def test_a_plural_day_is_a_day(self):
        self.assertEqual(extract_deals.days_in("Fridays"), {5})
        self.assertEqual(
            extract_deals.days_in("Wednesdays, Thursdays, & Fridays"), {3, 4, 5})

    def test_abbreviations_in_a_range_and_a_slash_list(self):
        self.assertEqual(extract_deals.days_in("M-F 4-6pm"), {1, 2, 3, 4, 5})
        self.assertEqual(extract_deals.days_in("W/Th/Fr"), {3, 4, 5})

    def test_an_ambiguous_code_refuses_the_whole_construction(self):
        # 'T' is Tuesday or Thursday and nothing decides it. Reading the codes
        # around it would name the wrong days on a real card.
        self.assertEqual(extract_deals.days_in("T-F"), set())
        self.assertEqual(extract_deals.days_in("T/W/Th"), set())

    def test_a_slash_that_is_not_a_day_list_is_not_read_as_one(self):
        self.assertEqual(extract_deals.days_in("open 24/7"), set())
        self.assertEqual(extract_deals.days_in("and/or"), set())

    def test_a_range_written_with_periods_does_not_decay_into_two_days(self):
        # This returned {Mon, Thu} -- a WRONG answer, silently dropping Tuesday
        # and Wednesday -- because RANGE_RE failed and SINGLE_RE then matched
        # both ends on their own.
        self.assertEqual(extract_deals.days_in("MON.-THURS. 11AM-11PM"),
                         {1, 2, 3, 4})

    def test_til_is_written_with_an_apostrophe(self):
        self.assertEqual(extract_deals.window_in("3 PM TIL' 6 PM"),
                         ("15:00", "18:00"))


class AClockWithNoDaysIsEveryDay(unittest.TestCase):
    """23 venues stated a happy hour window and never named a day.

    Refusing them published nothing, which is not the safer answer -- it is the
    invisible one. A venue that limits its happy hour to weekdays says so.
    """

    def test_a_dayless_happy_hour_runs_all_week(self):
        got = extract_deals.windows_from("HAPPY HOUR / 3 PM TIL' 6 PM")
        self.assertEqual(sorted(w["dow"] for w in got), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(got[0]["start"], "15:00")

    def test_a_dated_event_is_not_a_weekly_deal(self):
        self.assertEqual(extract_deals.windows_from(
            "Toys For Tots Happy Hour: Dec. 14th / 5-8pm"), [])
        self.assertEqual(extract_deals.windows_from(
            "this 4th of July we are celebrating with happy hour 3-6pm"), [])

    def test_a_meal_service_is_not_a_happy_hour(self):
        self.assertEqual(extract_deals.windows_from(
            "LUNCH: 12pm-4pm happy hour prices"), [])

    def test_opening_hours_are_not_a_happy_hour(self):
        self.assertEqual(extract_deals.windows_from("open 11am-10pm"), [])


class OnePriceStandsAboveTheDishesItCovers(unittest.TestCase):
    """Tommy's food is '$8' on its own line and then four dishes, three times.

    Nothing in the page's TREE joins them -- it is Wix, and every line sits in
    its own absolutely-positioned branch -- so item_beside() found a box holding
    the price alone and twelve dishes went unpublished.
    """

    LINES = ["EAT", "$8", "GARLIC FLATBREAD", "SPICY TUNA ROLL",
             "PERSONAL CLASSIC PIZZA", "​", "$9", "Tavern Taquitos",
             "LOADED NACHOS", "​", "DINNER", "$40", "Dry Aged Ribeye"]

    def test_the_price_owns_the_lines_until_the_blank(self):
        got = crawl_sites.stacked_prices(self.LINES, set(range(10)))
        self.assertEqual(got[0], "[cat:food] $8 / GARLIC FLATBREAD / "
                                 "SPICY TUNA ROLL / PERSONAL CLASSIC PIZZA")
        self.assertEqual(got[1], "[cat:food] $9 / Tavern Taquitos / LOADED NACHOS")

    def test_it_never_leaves_the_happy_hour_section(self):
        # The Dry Aged Ribeye is outside hh_lines. Reading by page order is only
        # safe inside the section; outside it this rule walks the dinner menu.
        got = crawl_sites.stacked_prices(self.LINES, set(range(10)))
        self.assertNotIn("Ribeye", " ".join(got))

    def test_the_venues_own_heading_gives_the_category(self):
        # 'Garlic Flatbread' and 'Tavern Taquitos' are on nobody's word list of
        # food nouns. The page said EAT.
        got = crawl_sites.stacked_prices(self.LINES, set(range(10)))
        self.assertTrue(all(q.startswith("[cat:food] ") for q in got))

    def test_a_lone_name_is_left_to_the_ordinary_priced_line_rule(self):
        self.assertEqual(
            crawl_sites.stacked_prices(["$8", "GARLIC FLATBREAD"], {0, 1}), [])


class ContainmentBeatsTheUrlOnAPageThatHasASection(unittest.TestCase):
    """Tommy's prints WEEKDAY SPECIALS below its happy hour, on the same page.

    hh_sections correctly left that block outside the section -- and then
    `url == lead_url` let every line of it back in, and half-price Wednesday
    sangria published as a seven-day 3-6pm happy-hour item.
    """

    def test_an_uncontained_line_on_a_contained_page_is_refused(self):
        hits = [{"url": "u", "quote": "[cat:wine] $6 sangria", "hh": True},
                {"url": "u", "quote": "HALF PRICE WINE LIST"}]
        got = extract_deals.items_from_hits(hits, "u")
        self.assertEqual([i["label"] for i in got], ["sangria"])

    def test_the_url_still_carries_a_page_with_no_section_at_all(self):
        hits = [{"url": "u", "quote": "$6 sangria"}]
        got = extract_deals.items_from_hits(hits, "u")
        self.assertEqual([i["label"] for i in got], ["sangria"])


class ExclusionsTest(unittest.TestCase):
    """The two doors onto the board.

    The bug this class exists to stop: 'Hotel (Liquor)' is a LICENCE, held by
    178 venues of which only 87 are hotels. Filtering on it deletes working
    taverns. Every keep-case below is a real venue that was on the board.
    """

    def test_bald_birds_is_banned_under_any_trade_name(self):
        self.assertTrue(exclusions.excluded(
            "Bald Birds Brewing Company - King of Prussia",
            "BALD BIRDS BREWING COMPANY", "Brewery"))
        self.assertTrue(exclusions.excluded(
            "Bald Birds Brewing", "BALD BIRDS BREWING COMPANY", ""))

    def test_a_hotel_brand_goes_whatever_its_licence_says(self):
        for name in ("Courtyard by Marriott", "Hilton Philadelphia",
                     "DoubleTree Suites", "Homewood Suites Valley Forge"):
            self.assertEqual(exclusions.excluded(name, "", "Restaurant"),
                             "hotel", name)

    def test_a_tavern_on_a_hotel_licence_stays(self):
        for name in ("The Olde Black Horse Tavern and Motel",
                     "The Stray Dog Tavern", "Joseph Ambler Inn",
                     "CO-OP Restaurant & Bar", "Panorama"):
            self.assertIsNone(
                exclusions.excluded(name, name.upper(), "Hotel (Liquor)"), name)

    def test_the_hotel_word_alone_is_not_enough_without_the_licence(self):
        self.assertIsNone(exclusions.excluded("The Hotel Bar", "", "Restaurant"))
        self.assertEqual(
            exclusions.excluded("Valley Forge Hotel", "", "Hotel (Liquor)"),
            "hotel")


class SilentClassTest(unittest.TestCase):
    """Why a venue publishes NO window -- the population 15x larger than holes."""

    def test_no_row_and_no_pages_are_both_never_crawled(self):
        self.assertEqual(report_holes.classify_silent(None), "never-crawled")
        self.assertEqual(report_holes.classify_silent({"pages": []}),
                         "never-crawled")

    def test_a_page_with_no_line_count_is_not_guessed_at(self):
        row = {"pages": [{"url": "u", "result": "ok, 0 quote(s)"}]}
        self.assertEqual(report_holes.classify_silent(row),
                         "crawled-before-the-line-count")

    def test_two_hundred_ok_and_no_text_is_a_javascript_shell(self):
        row = {"pages": [{"url": "u", "result": "ok, 0 quote(s)", "lines": 11}]}
        self.assertEqual(report_holes.classify_silent(row), "page-is-a-shell")

    def test_the_venue_answering_is_not_a_hole(self):
        row = {"pages": [{"url": "u", "result": "ok, 1 quote(s)", "lines": 300}],
               "hits": [{"quote": "While we don't have a traditional happy hour"}]}
        self.assertEqual(report_holes.classify_silent(row),
                         "venue-says-it-has-none")
        row["hits"] = [{"quote": "Every hour is happy here!"}]
        self.assertEqual(report_holes.classify_silent(row),
                         "venue-says-it-has-none")

    def test_a_full_page_saying_happy_hour_with_no_clock_is_its_own_class(self):
        row = {"pages": [{"url": "u", "result": "ok, 1 quote(s)", "lines": 300,
                          "hh": True}],
               "hits": [{"quote": "happy hour $2 off any beer"}]}
        self.assertEqual(report_holes.classify_silent(row),
                         "says-happy-hour-no-window")

    def test_robots_and_fetch_failures_are_told_apart(self):
        self.assertEqual(report_holes.classify_silent(
            {"pages": [{"url": "u", "result": "robots.txt refused"}]}),
            "robots-refused")
        self.assertEqual(report_holes.classify_silent(
            {"pages": [{"url": "u", "result": "HTTP 403"}]}), "fetch-failed")


class FrontierIsTheUnionOfBothSiteSources(unittest.TestCase):
    """The crawl frontier must queue every website we hold, from either source.

    venue_base takes a website from Google Places OR the OSM join, so Places
    could hand us a site the frontier never saw. Those venues reported as
    'never-crawled' and read exactly like a venue with no website at all --
    The Cheesecake Factory, Tommy Bahama and Wegmans in King of Prussia.
    """

    def _frontier(self, sites, base):
        import json
        import unittest.mock
        real = open

        def fake_open(path, *a, **k):
            import io
            if path == crawl_sites.SITES:
                return io.StringIO(json.dumps(sites))
            if path == crawl_sites.BASE:
                return io.StringIO(json.dumps(base))
            return real(path, *a, **k)

        with unittest.mock.patch("builtins.open", fake_open):
            return crawl_sites.frontier()

    def test_a_places_only_website_enters_the_frontier(self):
        out = self._frontier(
            {}, {"1": {"name": "Cheesecake", "zone_id": "kop",
                       "address": "a", "website": "https://cheesecake.example"}})
        self.assertIn("1", out)
        self.assertEqual(out["1"]["website"], "https://cheesecake.example")

    def test_both_urls_are_kept_where_the_two_sources_disagree(self):
        # Neither source is reliably better -- bartaco's good page is base's,
        # Pizzeria Vetri's is sites'. So both are crawled rather than chosen
        # between: sites' is the start, base's rides along in also_urls.
        out = self._frontier(
            {"1": {"name": "Paladar", "osm_name": None, "address": "a",
                   "zone_id": "kop",
                   "website": "https://paladar.example/happy-hour/"}},
            {"1": {"name": "Paladar", "zone_id": "kop", "address": "a",
                   "website": "https://paladar.example/"}})
        self.assertEqual(out["1"]["website"],
                         "https://paladar.example/happy-hour/")
        self.assertEqual(out["1"]["also_urls"], ["https://paladar.example/"])

    def test_an_agreeing_url_adds_no_second_seed(self):
        same = "https://one.example/"
        out = self._frontier(
            {"1": {"name": "One", "osm_name": None, "address": "a",
                   "zone_id": "kop", "website": same}},
            {"1": {"name": "One", "zone_id": "kop", "address": "a",
                   "website": same}})
        self.assertNotIn("also_urls", out["1"])

    def test_a_venue_with_no_website_is_not_queued(self):
        out = self._frontier({}, {"1": {"name": "No Site", "zone_id": "kop"}})
        self.assertEqual(out, {})


class TheMenuAPagePublishesAsData(unittest.TestCase):
    """schema.org Menu blocks: the happy hour stated for machines."""

    def _ld(self, doc):
        return ('<html><head><script type="application/ld+json">'
                + json.dumps(doc) + "</script></head><body>x</body></html>")

    def test_a_named_happy_hour_menu_yields_its_hours_and_its_items(self):
        # Pizzeria Vetri's shape, and the reason the venue read as silent: the
        # visible page says only the words 'Happy Hour' behind a JS tab.
        html = self._ld({
            "@context": "https://schema.org", "@type": "Menu",
            "name": "Happy Hour", "description": "Weekdays: 4 PM - 6 PM",
            "hasMenuSection": [{
                "@type": "MenuSection", "name": "$7 Spritzes",
                "hasMenuItem": [{"@type": "MenuItem", "name": "Aperol Spritz",
                                 "offers": {"@type": "Offer", "price": "7"}}]}]})
        out = crawl_sites.jsonld_quotes(html)
        self.assertIn("Happy Hour: Weekdays: 4 PM - 6 PM", out)
        self.assertIn("$7 Spritzes", out)
        self.assertIn("Aperol Spritz $7", out)

    def test_a_menu_that_is_not_the_happy_hour_is_passed_over(self):
        # The regular dinner menu published as happy hour items is the worst
        # failure available here: the full price, presented as a deal.
        html = self._ld({"@type": "Menu", "name": "Dinner",
                         "description": "Nightly from 5",
                         "hasMenuSection": [{"@type": "MenuSection",
                                             "name": "Entrees"}]})
        self.assertEqual(crawl_sites.jsonld_quotes(html), [])

    def test_a_menu_nested_under_a_restaurant_is_still_found(self):
        # @graph and hasMenu both nest; a flat pass finds the Restaurant and
        # misses the Menu hanging off it.
        html = self._ld({"@graph": [{"@type": "Restaurant", "name": "V",
                                     "hasMenu": {"@type": "Menu",
                                                 "name": "Happy Hour",
                                                 "description": "M-F 4-6"}}]})
        self.assertIn("Happy Hour: M-F 4-6", crawl_sites.jsonld_quotes(html))

    def test_malformed_json_does_not_take_the_page_with_it(self):
        html = ('<script type="application/ld+json">{not json</script>'
                + self._ld({"@type": "Menu", "name": "Happy Hour",
                            "description": "M-F 4-6"}))
        self.assertIn("Happy Hour: M-F 4-6", crawl_sites.jsonld_quotes(html))

    # ---- the same standard, shipped somewhere else ----------------------
    #
    # A page can publish its whole happy hour as schema.org and still read as
    # silent to us, because we only ever looked inside a script tag. McGlynn's
    # Pub ships six priced sections -- one of them 'Happy Hour', with its
    # window and four items -- as an ESCAPED JSON string inside the state its
    # React front end boots from. Its four real ld+json tags carry Restaurant
    # records only, and the visible page is a 25-line shell, two lines of which
    # read 'Load More Content'. Every menu we could not see was blamed on
    # rendering; this one was in our hands, in the standard, unread.

    def _state(self, doc):
        """The doc as a page's own JavaScript state carries it: a JSON
        document serialised as a STRING inside another JSON document."""
        return ('<html><body><script>window.__STATE__='
                + json.dumps({"page": {"menu": json.dumps(doc)}})
                + "</script>Load More Content</body></html>")

    def test_a_menu_shipped_to_javascript_is_read_like_one_in_a_script_tag(self):
        html = self._state({
            "@context": "https://schema.org/", "@type": "Menu",
            "name": "Food & Drink Specials",
            "hasMenuSection": [{
                "@type": "MenuSection", "name": "Happy Hour",
                "description": "Happy Hour Bites - Monday through Friday 4 pm - 6 pm",
                "hasMenuItem": [
                    {"@type": "MenuItem", "name": "Loaded Tater Tots",
                     "offers": {"@type": "Offer", "price": "5.0"}},
                    {"@type": "MenuItem", "name": "Pretzels & Mustards",
                     "offers": {"@type": "Offer", "price": "5.0"}}]}]})
        out = crawl_sites.jsonld_quotes(html)
        self.assertIn(
            "Happy Hour: Happy Hour Bites - Monday through Friday 4 pm - 6 pm",
            out)
        self.assertIn("Loaded Tater Tots $5.0", out)
        self.assertIn("Pretzels & Mustards $5.0", out)

    def test_a_happy_hour_section_is_read_inside_a_menu_named_something_else(self):
        # The common shape. Requiring the MENU to carry the name passed over a
        # section that had said its own name, in the standard, with prices.
        html = self._ld({
            "@type": "Menu", "name": "Food & Drink Specials",
            "hasMenuSection": [{"@type": "MenuSection", "name": "Happy Hour",
                                "description": "Mon-Fri 4 pm - 6 pm",
                                "hasMenuItem": [
                                    {"@type": "MenuItem", "name": "Wings",
                                     "offers": {"price": "9"}}]}]})
        out = crawl_sites.jsonld_quotes(html)
        self.assertIn("Happy Hour: Mon-Fri 4 pm - 6 pm", out)
        self.assertIn("Wings $9", out)

    def test_a_section_that_does_not_name_itself_is_still_somebody_dinner(self):
        # The guard does not weaken by moving down a level.
        html = self._ld({
            "@type": "Menu", "name": "Dinner",
            "hasMenuSection": [{"@type": "MenuSection", "name": "Entrees",
                                "description": "Nightly from 5",
                                "hasMenuItem": [
                                    {"@type": "MenuItem", "name": "Steak",
                                     "offers": {"price": "38"}}]}]})
        self.assertEqual(crawl_sites.jsonld_quotes(html), [])

    def test_an_unparseable_embedded_blob_does_not_take_the_page_with_it(self):
        html = ('<script>window.x="{' + chr(92) + '"@context' + chr(92)
                + '":not json";</script>'
                + self._state({"@context": "https://schema.org/",
                               "@type": "Menu", "name": "Happy Hour",
                               "description": "M-F 4-6"}))
        self.assertIn("Happy Hour: M-F 4-6", crawl_sites.jsonld_quotes(html))


class TheClockInTheBoxNextDoor(unittest.TestCase):
    """A window that lives in a sibling cell, not on the deal's own line."""

    ROW = ('<div class="row"><div class="col-sm-8">{deal}</div>'
           '<div class="col-sm-4">{clock}</div></div>')

    def _boxed(self, body):
        lines, stacks, _ = crawl_sites.text_lines_emph(
            "<html><body><section>" + body + "</section></body></html>")
        return crawl_sites.boxed_windows(lines, stacks)

    def test_the_deal_and_the_clock_are_joined_across_the_row(self):
        out = self._boxed(self.ROW.format(deal="Happy Hour! $2 OFF any beer",
                                          clock="04:00 PM - 06:00 PM"))
        self.assertEqual(out, ["Happy Hour! $2 OFF any beer 04:00 PM - 06:00 PM"])

    def test_a_clock_never_reaches_into_the_row_above(self):
        # Peppers lists every day as its own row. An ancestor-based box made
        # the whole section one box and paired the happy hour with the previous
        # row's 4-9pm, which belongs to that day's other special.
        out = self._boxed(
            self.ROW.format(deal="Wing Night $1 wings", clock="04:00 PM - 09:00 PM")
            + self.ROW.format(deal="Happy Hour! $2 OFF any beer",
                              clock="04:00 PM - 06:00 PM"))
        self.assertEqual(out, ["Happy Hour! $2 OFF any beer 04:00 PM - 06:00 PM"])

    def test_a_bare_clock_with_no_deal_in_its_row_is_left_alone(self):
        self.assertEqual(
            self._boxed(self.ROW.format(deal="Kitchen hours",
                                        clock="04:00 PM - 06:00 PM")), [])

    def test_a_deal_that_states_its_own_clock_is_not_given_a_second_one(self):
        self.assertEqual(
            self._boxed(self.ROW.format(deal="Happy Hour 3-5pm daily",
                                        clock="04:00 PM - 06:00 PM")), [])


class TheOtherTownsPageServedAtOurs(unittest.TestCase):
    """A chain's canonical tag naming a location that is not this one."""

    def _canon(self, href):
        return f'<html><head><link rel="canonical" href="{href}"/></head></html>'

    def test_a_canonical_naming_another_location_refuses_the_page(self):
        # City Works serves Frisco, Texas' complete happy hour page at the King
        # of Prussia URL. Every gate we have would pass the window it states.
        self.assertEqual(
            crawl_sites.wrong_location(
                self._canon("https://cw.example/locations/frisco/happy-hour-menu/"),
                "https://cw.example/locations/king-of-prussia/happy-hour/"),
            "frisco")

    def test_our_own_canonical_is_not_a_refusal(self):
        self.assertIsNone(crawl_sites.wrong_location(
            self._canon("https://cw.example/locations/king-of-prussia/"),
            "https://cw.example/locations/king-of-prussia/happy-hour/"))

    def test_a_page_with_no_location_in_its_url_is_not_judged(self):
        # Most of the corpus is single-site venues with no /locations/ path at
        # all, and a rule that refuses those refuses nearly everything.
        self.assertIsNone(crawl_sites.wrong_location(
            self._canon("https://bar.example/happy-hour/"),
            "https://bar.example/happy-hour/"))


class OnePageFailingIsNotTheVenueGoingQuiet(unittest.TestCase):
    """A recrawl must not delete what a failed fetch could not re-read."""

    HELD = {"pages": [{"url": "https://g.example/drinks", "result": "ok, 5 quote(s)"},
                      {"url": "https://g.example/", "result": "ok, 0 quote(s)"}],
            "hits": [{"url": "https://g.example/drinks", "quote": "$5 drafts"},
                     {"url": "https://g.example/", "quote": "Happy Hour 4-6"}]}

    def test_quotes_from_a_page_that_errored_are_carried_forward(self):
        # Gullifty's shipped a card with nothing on it because one
        # ConnectionError on a recrawl dropped all five of its items. The
        # window survived, so no count moved and nothing looked wrong.
        now = [{"url": "https://g.example/", "result": "ok, 0 quote(s)"},
               {"url": "https://g.example/drinks", "result": "error: ConnectionError"}]
        carried, notes = crawl_sites.keep_failed_pages(now, self.HELD)
        self.assertEqual([h["quote"] for h in carried], ["$5 drafts"])
        self.assertIn("KEPT what we held", notes[0]["result"])

    def test_a_page_read_fine_this_run_carries_nothing_forward(self):
        # The page answered. Its answer is the current one, empty or not --
        # otherwise a venue could never drop a deal it stopped offering.
        now = [{"url": "https://g.example/drinks", "result": "ok, 0 quote(s)"}]
        self.assertEqual(crawl_sites.keep_failed_pages(now, self.HELD), ([], []))

    def test_a_url_that_failed_but_also_succeeded_carries_nothing(self):
        # Both seeds point at the same page and one attempt errored; we still
        # READ it, so it speaks for itself.
        now = [{"url": "https://g.example/drinks", "result": "error: ConnectionError"},
               {"url": "https://g.example/drinks", "result": "ok, 0 quote(s)"}]
        self.assertEqual(crawl_sites.keep_failed_pages(now, self.HELD), ([], []))

    def test_a_clean_run_does_no_work(self):
        now = [{"url": "https://g.example/", "result": "ok, 1 quote(s)"}]
        self.assertEqual(crawl_sites.keep_failed_pages(now, self.HELD), ([], []))

    def test_a_venue_we_held_nothing_for_carries_nothing(self):
        now = [{"url": "https://g.example/drinks", "result": "error: Timeout"}]
        self.assertEqual(crawl_sites.keep_failed_pages(now, {}), ([], []))



class AChainsMenuLivesOnACdnHostUnderAnInternalName(unittest.TestCase):
    """Bonefish Grill Willow Grove: 3:00-6:30PM every day, ~15 priced items,
    published only as BSH-1_0626.pdf on bonefishgrill-<hash>.a02.azurefd.net.

    We had already fetched the page that links it. Five gates each dropped it on
    their own, and every gate reported success -- which is why the town read as
    correctly empty. Each assertion below is one of them.
    """

    HTML = (
        '<div class="Menus">'
        '  <div class="Menus-item"><img alt="" itemprop="thumbnailUrl">'
        '    Catering Menu'
        '    <a class="Menus-menuItem" href="https://brandbar-9f2c1a.a02.azurefd.net'
        '/menu/BSH-1_0626.pdf" target="_blank">Let&#39;s Go!</a></div>'
        '  <div class="Menus-item"><img alt="" itemprop="thumbnailUrl">'
        '    Social Hour Menu'
        '    <a class="Menus-menuItem" href="https://brandbar-9f2c1a.a02.azurefd.net'
        '/menu/BFGBrunchMenuT62.pdf">Let&#39;s Go!</a></div>'
        '</div>'
        '<div class="Event"><h2>WHAT&#39;S BETTER THAN HAPPY HOUR? NEW SOCIAL HOUR!'
        ' EVERY. SINGLE. DAY.</h2>'
        '<div class="Event-description">Enjoy delicious new menu items and'
        ' irresistible hand-crafted cocktails starting at $7, available every'
        ' single day.</div>'
        '<a class="Event-cta" href="https://brandbar-9f2c1a.a02.azurefd.net'
        '/menu/BSH-1_0626.pdf">Let&#39;s Go!</a></div>'
    )
    PAGE = "https://locations.brandbar.com/pennsylvania/willow-grove/1015-easton-road"
    DOC = "https://brandbar-9f2c1a.a02.azurefd.net/menu/BSH-1_0626.pdf"

    def test_a_document_on_the_brands_own_cdn_is_not_a_foreign_link(self):
        # registrable() reads azurefd.net, not brandbar.com, so the only menu
        # this venue publishes was dropped before anything looked at its words.
        self.assertTrue(crawl_sites.same_site(self.DOC, "brandbar.com", is_doc=True))

    def test_an_html_page_on_that_host_is_still_foreign(self):
        # The widening is for documents only. A page on someone else's host is
        # someone else's page, and that is the test this must not weaken.
        self.assertFalse(crawl_sites.same_site(
            "https://brandbar-9f2c1a.a02.azurefd.net/specials", "brandbar.com"))

    def test_an_unrelated_cdn_is_still_foreign(self):
        self.assertFalse(crawl_sites.same_site(
            "https://cdn.squarespace.com/menu/hh.pdf", "brandbar.com", is_doc=True))

    def test_the_link_survives_and_ranks_with_the_named_documents(self):
        links = candidate_links(self.HTML, self.PAGE)
        self.assertIn(self.DOC, links)
        # Rank 0 is the group a page named an hour; it beats every ordinary
        # link. On the live page this document is first outright.
        self.assertLess(links.index(self.DOC), 2)

    def test_the_page_names_the_document_even_though_the_filename_cannot(self):
        # BSH is the chain's SKU for its own Social Hour, so HH_DOC_RE has
        # nothing to match and the linking page is not a happy-hour page --
        # both halves of the queue rule were false.
        self.assertFalse(crawl_sites.HH_DOC_RE.search(self.DOC))
        self.assertFalse(crawl_sites.url_names_hh(self.PAGE, 1))
        self.assertIn(self.DOC, crawl_sites.hh_named_docs(self.HTML, self.PAGE))

    def test_a_shuffled_carousel_can_name_the_wrong_document_too(self):
        """The accepted cost, pinned so nobody discovers it as a surprise.

        This fixture is the pathological case: "Social Hour Menu" sits directly
        above the BRUNCH link, so the brunch menu is named as well. Nothing in
        the markup distinguishes a shuffled carousel from a correct one, so the
        choice is which way to be wrong -- and one wasted PDF fetch, bounded by
        DOC_CAP, against losing the only document that states a venue's happy
        hour is not a close call. A brunch menu naming no hour is then refused
        by the reader, where a miss would have been silent.

        What must always hold is that the RIGHT document is among them.
        """
        named = crawl_sites.hh_named_docs(self.HTML, self.PAGE)
        self.assertIn(self.DOC, named)
        self.assertLessEqual(len(named), crawl_sites.DOC_CAP)

    def test_every_single_day_is_seven_days(self):
        # The clock always parsed. The days did not, so even with the document
        # in hand the deal would have been refused for naming no day.
        line = "3:00PM - 6:30PM   |    EVERY. SINGLE. DAY."
        self.assertEqual(extract_deals.window_in(line), ("15:00", "18:30"))
        self.assertEqual(extract_deals.days_in(line), {1, 2, 3, 4, 5, 6, 7})


class APossessiveIsNotADifferentBar(unittest.TestCase):
    """Four of the nine photo refusals in Willow Grove were punctuation.

    The name Google holds carries the apostrophe the sign over the door has;
    the licensee typed it without. Splitting on the mark left 'richie' facing
    'richies' with nothing in common, and the venue got no photo and no website.
    """

    @staticmethod
    def agrees(ours, theirs):
        return fetch_venue_photos.name_agrees(
            {"name": ours, "plcb_name": ""}, {"displayName": {"text": theirs}})

    def test_the_apostrophe_is_not_a_difference(self):
        self.assertTrue(self.agrees("Richies Bar & Grill", "Richie's Bar & Grill"))
        self.assertTrue(self.agrees("Magerks", "MaGerk's Pub & Grill"))

    def test_the_spacing_is_not_a_difference(self):
        self.assertTrue(self.agrees("Na Brasa", "NaBrasa Brazilian Steakhouse"))

    def test_two_different_bars_are_still_two_bars(self):
        # The guard exists because an apartment block shares a bar's address.
        self.assertFalse(self.agrees("Amada", "Armada Cafe"))
        self.assertFalse(self.agrees(
            "Justop", "1720 Fairmount Luxury Apartments"))

class ABareLabelIsNotAClaim(unittest.TestCase):
    """'Happy Hour' as a nav link must never claim the clock beside it."""

    ROW = ('<div class="row"><div class="c8">{deal}</div>'
           '<div class="c4">{clock}</div></div>')

    def _boxed(self, body):
        lines, stacks, _ = crawl_sites.text_lines_emph(
            "<html><body><section>" + body + "</section></body></html>")
        return crawl_sites.boxed_windows(lines, stacks)

    def test_a_bare_happy_hour_label_beside_opening_hours_is_refused(self):
        # Black Powder Tavern's home page: the label sits in a row of opening
        # hours. Pairing them manufactured lunch and brunch as happy hours, and
        # one OUTRANKED the venue's own 'Monday through Friday from 4:00 p.m.
        # until 6:00 p.m.' -- turning a correct Mon-Fri window into every day,
        # cited to a quote saying 11:30 to 4.
        self.assertEqual(self._boxed(
            self.ROW.format(deal="Happy Hour", clock="11:30 a.m. to 4:00 p.m.")), [])

    def test_a_line_that_states_a_price_is_still_read(self):
        out = self._boxed(self.ROW.format(deal="Happy Hour! $2 OFF any beer",
                                          clock="04:00 PM - 06:00 PM"))
        self.assertEqual(out, ["Happy Hour! $2 OFF any beer 04:00 PM - 06:00 PM"])

    def test_a_sentence_without_a_price_is_still_read(self):
        out = self._boxed(self.ROW.format(
            deal="Happy Hour in the tavern and on the patio",
            clock="04:00 PM - 06:00 PM"))
        self.assertEqual(len(out), 1)

    def test_states_a_deal_judges_what_survives_removing_the_words(self):
        self.assertFalse(crawl_sites.states_a_deal("Happy Hour"))
        self.assertFalse(crawl_sites.states_a_deal("HAPPY HOUR!"))
        self.assertTrue(crawl_sites.states_a_deal("Happy Hour $5 drafts"))
        self.assertTrue(
            crawl_sites.states_a_deal("Happy Hour in the tavern and patio"))


class RoundupHeadingShapes(unittest.TestCase):
    """A list heading is often "<Venue> - <why it made the list>".

    BUCKSCO.Today's Doylestown piece (2026-08-12) heads its entries "86 West -
    Best for Groups and Drinks". The tail pushed every one of them past
    HEADING_WORDS, so no heading was seen, the prose under it was filed to no
    venue, and the town's only roundup quote was the address line in the card
    block at the foot of the article.
    """

    def test_a_dash_suffixed_heading_is_a_heading(self):
        import crawl_roundups as cr
        for line in ("86 West - Best for Groups and Drinks",
                     "86 West — Best for Groups and Drinks",
                     "Maxwell's On Main (MOMs) – Best Rooftop Experience"):
            self.assertTrue(cr.is_heading(line), line)

    def test_the_venue_name_is_the_part_before_the_dash(self):
        import crawl_roundups as cr
        self.assertEqual(cr.heading_text("86 West - Best for Groups and Drinks"),
                         "86 West")
        self.assertEqual(cr.heading_text("Farmhouse Tavern"), "Farmhouse Tavern")

    def test_prose_with_a_dash_in_it_is_still_not_a_heading(self):
        # The sentence test stays on the WHOLE line. Splitting first would let
        # a paragraph pass on its short opening clause.
        import crawl_roundups as cr
        for line in ("Open since 1953 - the longest running tavern in town, "
                     "it offers outdoor seating and a solid pub menu.",
                     "Happy hour runs Monday through Friday from 4:30 to 6:30."):
            self.assertFalse(cr.is_heading(line), line)


class ASuppliedTradeNameCanBeTheLegalEntity(unittest.TestCase):
    """Google lists FACENDA SPIRITS LLC in Doylestown under its paperwork.

    The base left a Places/OSM name alone on the rule that it "is already the
    trade name" -- and so shipped the one thing a card may never show. The sign
    over a door never ends in LLC.
    """

    def test_an_entity_suffixed_trade_name_is_stripped(self):
        from build_venue_base import _trade
        self.assertEqual(_trade("FACENDA SPIRITS LLC"), "Facenda Spirits")
        self.assertEqual(_trade("Facenda Spirits LLC"), "Facenda Spirits")

    def test_a_real_trade_name_is_left_exactly_as_given(self):
        from build_venue_base import _trade
        for name in ("86 West", "Chambers 19 Bistro & Bar", "The Hattery Stove & Still"):
            self.assertEqual(_trade(name), name)

    def test_words_that_belong_on_a_sign_are_never_stripped(self):
        # CO, COMPANY and GROUP are in ENTITY_SUFFIX_RE because they end a PLCB
        # LICENSEE. They are also real words on real signs, and reusing that
        # regex on a SUPPLIED name turned `Bagels & Co.` into `Bagels &`.
        from build_venue_base import _trade
        for name in ("Wrong Crowd Beer Company", "Victory Brewing Company",
                     "Bagels & Co.", "Hi-Lo Taco Co.", "Wissahickon Brewing Co",
                     "Whole Foods Market Group", "Sunset Hill Brewing Company"):
            self.assertEqual(_trade(name), name)

    def test_no_trade_name_at_all_falls_through(self):
        from build_venue_base import _trade
        self.assertIsNone(_trade(None))
        self.assertIsNone(_trade("  "))


class RoundupAddressJoin(unittest.TestCase):
    """A roundup DOES carry an address, and it is the stronger key.

    BUCKSCO.Today's Doylestown piece (2026-08-12) names two bars with real
    clocks that no name could join: Maxwell's On Main sits on the licence
    '37 N MAIN STREET ENTERPRISES LLC' and Penn Taproom on 'PA GRILL ROOM LLC'.
    The article puts '37 N Main St, Doylestown, PA 18901' under Maxwell's
    heading in a card block at the foot, and opens Penn Taproom's prose with
    'Located at 80 W State Street'. Both are the acceptance test for the join.
    """

    BASE = {
        "63165": {"lid": "63165", "name": "37 N Main Street Enterprises",
                  "plcb_name": "37 N MAIN STREET ENTERPRISES LLC", "named_by": "plcb",
                  "address": "37-39 N Main St, Doylestown PA 18901", "zone_id": "doylestown"},
        "63321": {"lid": "63321", "name": "PA Grill Room", "plcb_name": "PA GRILL ROOM LLC",
                  "named_by": "plcb", "address": "80 W State St, Doylestown PA 18901",
                  "zone_id": "doylestown"},
        "129847": {"lid": "129847", "name": "Station 142 Stage + Bar + Kitchen",
                   "plcb_name": "FTROOP142 LLC", "named_by": "osm",
                   "address": "142 E Market St, West Chester PA 19382", "zone_id": "west_chester"},
        "1": {"lid": "1", "name": "Lascala's Fire", "plcb_name": "LASCALA'S FIRE", "named_by": "osm",
              "address": "44 W Gay St, West Chester PA 19380", "zone_id": "west_chester"},
        "2": {"lid": "2", "name": "Sedona Taphouse", "plcb_name": "WCTHG LL LLC", "named_by": "osm",
              "address": "44 W Gay St, West Chester PA 19380", "zone_id": "west_chester"},
    }

    ARTICLE = """7 Idyllic Outdoor Dining Options in Doylestown
Penn Taproom – Best Downtown Patio
Located at 80 W State Street right in the heart of downtown, Penn Taproom seats roughly 70 guests outside.
Happy hour runs Monday through Friday from 4:30 to 6:30 PM and Sunday from 3 to 5 PM, with half-price drafts.
Maxwell’s On Main (MOMs) – Best Rooftop Experience
Maxwell’s On Main is one of those restaurants that rewards repeat visits.
Happy hour runs daily from 5 to 7 PM. Priced at mid-range, and reservations are recommended for weekend evenings.
03 — Best Rooftop Experience
Maxwell’s On Main (MOMs)
37 N Main St, Doylestown, PA 18901
(215) 340-1880
Visit Maxwell’s On Main’s Website ↗
"""

    def hits(self, text, zone="doylestown", sites=None):
        import crawl_roundups as cr
        return {h["lid"]: h for h in cr.mentions(
            text, venue_index(sites or {}, zone), cr.address_index(self.BASE, zone))}

    def test_the_card_block_address_joins_the_shell_licence(self):
        h = self.hits(self.ARTICLE)["63165"]
        self.assertEqual(h["joined_by"], "address")
        self.assertEqual(h["name"], "Maxwell’s On Main (MOMs)", "the sign, not the shell")
        self.assertEqual(h["plcb_name"], "37 N MAIN STREET ENTERPRISES LLC")
        self.assertTrue(any(q.startswith("Happy hour runs daily") for q in h["quotes"]),
                        "the prose section's paragraph reaches the venue")

    def test_an_address_in_the_prose_joins_too(self):
        h = self.hits(self.ARTICLE)["63321"]
        self.assertEqual(h["name"], "Penn Taproom")
        self.assertTrue(any("4:30 to 6:30" in q for q in h["quotes"]))

    def test_without_the_address_index_nothing_changes(self):
        import crawl_roundups as cr
        self.assertEqual(cr.mentions(self.ARTICLE, venue_index({}, "doylestown")), [])

    def test_a_range_licence_meets_the_single_number_on_the_sign(self):
        import crawl_roundups as cr
        self.assertEqual(cr.address_keys("37-39 N Main St, Doylestown PA 18901"),
                         {("37", "main"), ("39", "main")})
        self.assertEqual(cr.address_keys("5-7-9 N Walnut St, West Chester PA 19380"),
                         {("5", "walnut"), ("7", "walnut"), ("9", "walnut")})
        self.assertEqual(cr.address_keys("2100 Lower State Rd, Doylestown, PA 18901"),
                         {("2100", "lower state")})
        self.assertEqual(cr.address_keys("County Line Rd East Of Bethlehem Pk"), set())

    def test_the_join_is_scoped_to_the_articles_zone(self):
        text = "Maxwell’s On Main (MOMs)\n37 N Main St, Doylestown, PA 18901\n"
        self.assertEqual(self.hits(text, zone="west_chester"), {})

    def test_two_licences_at_one_door_are_refused(self):
        # 44 W Gay St is Lascala's Fire AND Sedona Taphouse.
        text = "Some New Bar\n44 W Gay St, West Chester, PA 19380\nHappy hour 4 to 6.\n"
        self.assertEqual(self.hits(text, zone="west_chester"), {})

    def test_a_live_trade_name_that_disagrees_refuses_the_join(self):
        # County Lines, May 2024: 'Serum Kitchen & Taphouse' at 142 E Market
        # St. Google now reads that door as 'Station 142'. A card under a name
        # the building stopped using is worse than a miss.
        text = "Serum Kitchen & Taphouse\nHappy Hour 4 to 6 at 142 E Market St.\n"
        self.assertEqual(self.hits(text, zone="west_chester"), {})

    def test_a_live_trade_name_that_agrees_joins(self):
        text = "Station 142\nHappy Hour 4 to 6 at 142 E Market St.\n"
        self.assertIn("129847", self.hits(text, zone="west_chester"))

    def test_a_heading_the_name_index_resolves_is_never_rerouted(self):
        # The address is a fallback. A heading the name index already owns
        # keeps its paragraphs even when they carry a different door.
        sites = {"9": {"name": "PENN TAPROOM", "osm_name": None,
                       "address": "1 Other St, Doylestown PA 18901", "zone_id": "doylestown"}}
        got = self.hits(self.ARTICLE, sites=sites)
        self.assertIn("9", got)
        self.assertNotIn("63321", got)


class ARoundupParagraphNamingAnotherDoorIsRefused(unittest.TestCase):
    """The name join owns the heading, so nobody checked the door it prints.

    County Lines (May 2024) wrote 'Newcomer Serum Kitchen & Taphouse offers
    Happy Hour all working week long, 4 to 6 ... 142 E. Market St.' That
    paragraph joined by NAME to lid 101307, the licence at 30 N Church St,
    which is SLOW HAND -- a different building three streets away (142 E
    Market is Station 142, and is its own row in RoundupAddressJoin.BASE).
    West Chester shipped Slow Hand's licence under Serum's name, with Serum's
    Monday-to-Friday window, and Slow Hand is CLOSED Mondays.

    Re-routing is still refused at crawl time (the test above). This refuses
    at PUBLISH time instead, which is the only gate that can act on a deal
    already baked into data/deals_roundup.json.
    """

    def test_a_paragraph_printing_another_door_is_refused(self):
        self.assertTrue(quote_names_another_door(
            "Newcomer Serum Kitchen & Taphouse offers Happy Hour all working "
            "week long, 4 to 6. 142 E. Market St.",
            "30 N Church St, West Chester PA 19380"))

    def test_a_paragraph_printing_its_own_door_is_kept(self):
        self.assertFalse(quote_names_another_door(
            "Located at 80 W State Street right in the heart of downtown, "
            "Penn Taproom seats roughly 70 guests outside.",
            "80 W State St, Doylestown PA 18901"))

    def test_a_paragraph_printing_no_door_is_kept(self):
        # Silence is not disagreement. Most roundup paragraphs name no address
        # at all, and refusing those would empty the board.
        self.assertFalse(quote_names_another_door(
            "Happy hour runs daily from 5 to 7 PM.",
            "37-39 N Main St, Doylestown PA 18901"))

    def test_an_unparsed_venue_address_never_refuses(self):
        # Two doors are only evidence when BOTH parse. A venue whose own
        # address we cannot read must not have its deals dropped on a
        # comparison that never happened.
        self.assertFalse(quote_names_another_door(
            "Great spot. 142 E. Market St.", "Suite 3, no street here"))

    def test_a_shouted_licence_address_is_still_read(self):
        # ADDRESS_RE is built from a title-case suffix list and the BASE
        # shouts: '40 E MARKET ST'. Without re.I the guard was blind to its
        # own corpus -- it read no door at all, so it could never disagree.
        self.assertEqual(address_keys("40 E MARKET ST, WEST CHESTER PA 19382"),
                         {("40", "market")})
        self.assertTrue(quote_names_another_door(
            "Serum Kitchen & Taphouse, 142 E. Market St.",
            "30 N CHURCH ST, WEST CHESTER PA 19380"))

    def test_slow_hand_ships_under_its_own_name_and_no_roundup_deal(self):
        board = json.load(open(os.path.join(
            REPO, "web", "data", "venues-west_chester.json"), encoding="utf-8"))
        venues = board["venues"] if isinstance(board, dict) else board
        row = next(v for v in venues if str(v.get("lid")) == "101307")
        self.assertEqual(row["name"], "Slow Hand")
        self.assertEqual(row["deals"], [],
                         "the Serum roundup deal is back on Slow Hand's licence")


class ARoundupClockKeepsItsMinutes(unittest.TestCase):
    """'4:30 to 6:30 PM' shipped as 4:30-6:00, and nothing raised.

    pmify() adds the meridiem a roundup omits. The minutes on the END of its
    range were optional, so the pattern matched the '4:30 to 6' inside
    '4:30 to 6:30 PM' and rewrote the sentence to '4:30 pm - 6 pm:30 PM'. Penn
    Taproom's card then carried a half-hour the article does not claim. A
    wrong window is worse than a missing one.
    """

    def test_a_range_that_already_has_its_meridiem_is_left_alone(self):
        from extract_roundups import pmify
        for text in ("Happy hour runs Monday through Friday from 4:30 to 6:30 PM",
                     "5 to 7 PM", "3 to 5 PM", "4:30 to 6:30 p.m."):
            self.assertEqual(pmify(text), text)

    def test_a_bare_range_still_gets_one(self):
        from extract_roundups import pmify
        self.assertEqual(pmify("Happy Hour runs Tuesday to Friday, 4 to 6."),
                         "Happy Hour runs Tuesday to Friday, 4 pm - 6 pm.")
        self.assertEqual(pmify("Happy Hour 4:30 to 6:30, weekdays"),
                         "Happy Hour 4:30 pm - 6:30 pm, weekdays")

    def test_the_penn_taproom_quote_reads_end_to_end(self):
        from extract_roundups import windows_in_paragraph
        got = windows_in_paragraph(
            "Happy hour runs Monday through Friday from 4:30 to 6:30 PM and "
            "Sunday from 3 to 5 PM, with half-price drafts and discounted "
            "appetizers, though those deals apply to the bar area only.")
        weekday = [w for w in got if w["dow"] in (1, 2, 3, 4, 5)]
        self.assertEqual(len(weekday), 5)
        for w in weekday:
            self.assertEqual((w["start"], w["end"]), ("16:30", "18:30"))
        self.assertEqual([(w["start"], w["end"]) for w in got if w["dow"] == 7],
                         [("15:00", "17:00")])


class ACutLabelIsNotAWord(unittest.TestCase):
    """The item regexes cap a label at 29 characters.

    'half-price drafts and discounted appetizers' arrived as 'drafts and
    discounted appetiz' -- four words, so the prose guard passed it, and the
    last one is not a word. The price is on the first noun.
    """

    def test_a_conjoined_pair_is_cut_at_the_conjunction(self):
        from extract_roundups import tidy_items
        got = tidy_items([{"category": "draft", "label": "drafts and discounted appetiz",
                           "discount_pct": 50}])
        self.assertEqual([i["label"] for i in got], ["drafts"])

    def test_a_single_noun_is_untouched(self):
        from extract_roundups import tidy_items
        for label in ("select drafts", "house wine", "wine by the glass", "martinis"):
            got = tidy_items([{"category": "draft", "label": label, "price_usd": 5.0}])
            self.assertEqual([i["label"] for i in got], [label], label)


class TheSelectorGuardsTheWholeChain(unittest.TestCase):
    """A website walks venue_sites -> venue_base -> web/data before needy sees it.

    The guard written on 2026-09-02 for Doylestown compared only the first
    pair. On Media the next day the base WAS rebuilt and the bundles were not,
    so the guard stayed silent while needy named 9 venues where there were 26 --
    the same silent scope cap, one link along. A guard on one link of a chain
    is not a guard on the chain.
    """

    def test_every_link_of_the_chain_is_watched(self):
        import needy
        pairs = {(a, b) for a, b, _ in needy.STALE_CHAIN}
        self.assertIn(("data/venue_sites.json", "data/venue_base.json"), pairs)
        self.assertIn(("data/venue_base.json", "web/data/index.json"), pairs)

    def test_a_stale_link_anywhere_raises_the_warning(self):
        import needy, tempfile, time
        with tempfile.TemporaryDirectory() as d:
            for rel in ("data/venue_sites.json", "data/venue_base.json",
                        "web/data/index.json"):
                p = os.path.join(d, *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "w").write("{}")
                time.sleep(0.01)
            old_repo, needy.REPO = needy.REPO, d
            try:
                # In order: nothing is stale.
                self.assertFalse(self._warns(needy))
                # Touch the base alone: the bundles are now behind it.
                os.utime(os.path.join(d, "data", "venue_base.json"), None)
                self.assertTrue(self._warns(needy), "a stale BUNDLE must warn")
                # Touch the sites alone: the base is now behind it.
                os.utime(os.path.join(d, "data", "venue_sites.json"), None)
                self.assertTrue(self._warns(needy), "a stale BASE must warn")
            finally:
                needy.REPO = old_repo

    @staticmethod
    def _warns(needy):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            got = needy.warn_if_base_is_stale()
        return got and "INVISIBLE" in buf.getvalue()


class ANeighbourAtTheSameHouseNumberIsNotTheVenue(unittest.TestCase):
    """Media, 2026-09-02: THE FROSTED MUG is 527 E Baltimore PIKE.

    Places answered with the ACME Markets at 527 E Baltimore AVE -- two real
    and different Media streets that share a house number. The names agree on
    nothing, so the row shipped a bar's licence under a supermarket's name,
    website and photo.
    """

    def test_the_frosted_mug_stays_dropped(self):
        from discover_places import HAND_DROPPED
        self.assertIn("95653", HAND_DROPPED)

    def test_it_is_not_in_the_frontier(self):
        sites = json.load(open(os.path.join(REPO, "data", "venue_sites.json"),
                               encoding="utf-8"))
        self.assertNotIn("95653", sites)

    def test_no_media_venue_ships_under_a_supermarket(self):
        base = json.load(open(os.path.join(REPO, "data", "venue_base.json"),
                              encoding="utf-8"))
        v = base.get("95653")
        if v:
            self.assertNotIn("acme", (v.get("name") or "").lower())


class AHandDropIsHonouredByEveryReader(unittest.TestCase):
    """Two files read data/places_venues.json, and a drop must reach both.

    discover_places.merge_sites() keeps a rejected join out of the crawl
    frontier. build_venue_base.py reads the Places record DIRECTLY, so The
    Frosted Mug -- dropped from the frontier on 2026-09-02 -- kept taking its
    name, website and photo from the ACME Markets at the other Baltimore
    street. A drop applied in one of two readers is not a drop.
    """

    def test_the_base_takes_nothing_from_a_dropped_places_record(self):
        base = json.load(open(os.path.join(REPO, "data", "venue_base.json"),
                              encoding="utf-8"))
        from discover_places import HAND_DROPPED
        places = json.load(open(os.path.join(REPO, "data", "places_venues.json"),
                                encoding="utf-8"))
        for lid in HAND_DROPPED:
            v = base.get(lid)
            if not v or lid not in places:
                continue
            claimed = (places[lid].get("places_name") or "").lower()
            self.assertNotEqual((v.get("name") or "").lower(), claimed,
                                f"{lid} still carries the dropped Places name")
            self.assertFalse(v.get("website"), f"{lid} still carries a website")


class ATrailingPriceLabelIsCutOnAWordBoundary(unittest.TestCase):
    """The label runs backwards from the price and is capped at 29 characters.

    'Housemade Buffalo Cauliflower Bites $6' shipped State Street Pub an item
    called 'ade Buffalo Cauliflower Bites' (Media, 2026-09-02) -- the mirror
    of the roundup's 'drafts and discounted appetiz'. A label short by a whole
    word is a miss; one short by three letters is a wrong thing on a card.
    """

    def test_a_long_dish_name_is_cut_at_a_word(self):
        from extract_deals import TRAILING_PRICE_RE
        m = TRAILING_PRICE_RE.search("Housemade Buffalo Cauliflower Bites $6")
        self.assertEqual(m.group(1), "Buffalo Cauliflower Bites")

    def test_a_label_that_fits_is_untouched(self):
        from extract_deals import TRAILING_PRICE_RE
        for text, label in (("Volcano Fries $7", "Volcano Fries"),
                            ("BBQ Pulled Pork Nachos $7", "BBQ Pulled Pork Nachos"),
                            ("Margaritas $5", "Margaritas")):
            self.assertEqual(TRAILING_PRICE_RE.search(text).group(1), label, text)

    def test_no_shipped_item_label_starts_mid_word(self):
        # The whole board, not just this one venue: a cut label is invisible
        # unless somebody reads the card.
        import glob
        bad = []
        for path in glob.glob(os.path.join(REPO, "web", "data", "zone-*.json")):
            with open(path, encoding="utf-8") as fh:
                venues = json.load(fh)["venues"]
            for v in venues:
                for d in v.get("deals", []):
                    for it in d.get("items", []):
                        q = (d.get("source") or {}).get("quote") or ""
                        label = it["label"]
                        i = q.find(label)
                        if i > 0 and q[i - 1].isalpha():
                            bad.append((v["name"], label))
        self.assertEqual(bad, [], "item labels cut mid-word")


class WindowHalfHeldTest(unittest.TestCase):
    """A stranded read is not one situation, and 'no window' hid that.

    MadMacs prints a clock and no day; Slow Hand prints days and no clock.
    Those are different things to go and find out, and the strand warning
    said the same sentence about both for two sessions running.
    """

    def half(self, *prose):
        read = {"deals": [{"fine_print": p} for p in prose]}
        return build_bundles.window_half_held(read)

    def test_clock_without_days(self):
        self.assertEqual(
            self.half("3:30 to 6:30 Bar Side & Bar Side High Tops"),
            "clock, no days")

    def test_days_without_clock(self):
        self.assertEqual(
            self.half("Tuesday through Friday. Bar prices, short list."),
            "days, no clock")

    def test_nothing_held(self):
        self.assertEqual(self.half("Void where prohibited by law."), "neither")
        self.assertEqual(self.half(""), "neither")
        self.assertEqual(build_bundles.window_half_held({}), "neither")

    def test_a_shouted_corpus_is_still_read(self):
        # ADDRESS_RE shipped without re.I and read no address at all on a
        # SHOUTING base. Same trap, same file, so pin it here.
        self.assertEqual(self.half("MON-FRI 4-6PM"), "both -- unparsed")
        self.assertEqual(self.half("MAD HAPPY HOURS 3:30 TO 6:30"),
                         "clock, no days")

    def test_the_two_live_strands_classify_as_measured(self):
        # Read by hand off data/agent_reads/<lid>/ raw HTML and PDF, 2026-09-04.
        path = os.path.join(REPO, "data", "agent_reads.json")
        with open(path, encoding="utf-8") as fh:
            reads = json.load(fh)
        self.assertEqual(
            build_bundles.window_half_held(reads["DE40aae10689"]),
            "clock, no days", "MadMacs")
        self.assertEqual(
            build_bundles.window_half_held(reads["101307"]),
            "days, no clock", "Slow Hand")
