/* The time math is the part that can be wrong invisibly: a card shown on the
   wrong day still looks like a correct card. Run with:

       node --test tests/

   Dates are built with explicit local components. `new Date(2026, 6, 31, 17, 0)`
   is Fri 31 Jul 2026, 5:00pm -- asserted below rather than assumed. */

import test from "node:test";
import assert from "node:assert/strict";
import {
  dowOf, mins, fmtClock, fmtMins, itemParts, haversineMiles, driveMinutes, fmtMiles,
  dealValue, cheapestPrice, FILTERS, windowFor, nextOccurrence, groupFor, GROUP,
  buildFeed, summarizeWindows, usableMinutes, ageDays, effectiveConfidence,
} from "../web/lib.js";

const FRI_5PM = new Date(2026, 6, 31, 17, 0);
const FRI_11AM = new Date(2026, 6, 31, 11, 0);
const SUN_11AM = new Date(2026, 7, 2, 11, 0);

test("the fixtures are the weekdays this file claims", () => {
  assert.equal(FRI_5PM.getDay(), 5, "31 Jul 2026 must be a Friday");
  assert.equal(SUN_11AM.getDay(), 0, "2 Aug 2026 must be a Sunday");
});

test("dowOf converts JS Sunday=0 to ISO Sunday=7", () => {
  assert.equal(dowOf(SUN_11AM), 7);
  assert.equal(dowOf(new Date(2026, 7, 3, 9, 0)), 1); // Monday
  assert.equal(dowOf(FRI_5PM), 5);
});

test("mins and fmtClock round-trip the formats real bundles contain", () => {
  assert.equal(mins("16:00"), 960);
  assert.equal(mins("24:00"), 1440);
  assert.equal(fmtClock("16:00"), "4pm");
  assert.equal(fmtClock("16:30"), "4:30pm");
  assert.equal(fmtClock("09:00"), "9am");
  assert.equal(fmtClock("12:00"), "12pm");
  assert.equal(fmtClock("00:00"), "12am");
  // PA caps discounts at midnight, so 24:00 is a real value in the corpus.
  assert.equal(fmtClock("24:00"), "midnight");
});

test("fmtMins reads like a person", () => {
  assert.equal(fmtMins(42), "42 min");
  assert.equal(fmtMins(60), "1h");
  assert.equal(fmtMins(95), "1h 35m");
});

test("itemParts separates the number from the words", () => {
  assert.deepEqual(itemParts({ price_usd: 5, label: "drafts" }), { amount: "$5", label: "drafts" });
  assert.deepEqual(itemParts({ price_usd: 7.5, label: "cocktails" }), { amount: "$7.50", label: "cocktails" });
  assert.deepEqual(itemParts({ discount_pct: 50, label: "pints" }), { amount: "50% off", label: "pints" });
  assert.deepEqual(itemParts({ amount_off_usd: 2, label: "pours" }), { amount: "$2 off", label: "pours" });
  assert.deepEqual(itemParts({ label: "no price" }), { amount: "", label: "no price" });
});

/* ---- geography -------------------------------------------------------- */

test("haversine matches a known suburban distance", () => {
  const kop = { lat: 40.089, lng: -75.396 };
  const media = { lat: 39.91743, lng: -75.38833 }; // Iron Hill Media, geocoded
  const d = haversineMiles(kop, media);
  assert.ok(d > 11 && d < 12.5, `KoP->Media should be ~11.9 mi, got ${d.toFixed(2)}`);
  assert.equal(Math.round(haversineMiles(kop, kop)), 0);
});

test("driveMinutes is an estimate that never returns zero", () => {
  assert.ok(driveMinutes(0) >= 1);
  assert.ok(driveMinutes(12) > driveMinutes(3));
});

test("fmtMiles drops the decimal for street-centroid matches", () => {
  assert.equal(fmtMiles(3.24, true), "3.2 mi");
  assert.equal(fmtMiles(3.24, false), "~3 mi");
  assert.equal(fmtMiles(0.05), "here");
});

/* ---- value ------------------------------------------------------------ */

test("dealValue takes the best item, not the average", () => {
  const deal = { items: [{ category: "draft", price_usd: 7 }, { category: "draft", discount_pct: 50 }] };
  assert.equal(dealValue(deal), 50);
  assert.equal(dealValue({ items: [] }), 0);
});

test("cheapestPrice can be asked for drinks only", () => {
  const deal = {
    items: [
      { category: "food", price_usd: 1 },
      { category: "draft", price_usd: 5 },
      { category: "wine", price_usd: 7 },
    ],
  };
  assert.equal(cheapestPrice(deal), 1);
  assert.equal(cheapestPrice(deal, ["draft", "wine"]), 5);
  assert.equal(cheapestPrice({ items: [{ category: "draft", discount_pct: 50 }] }), null);
});

test("the under-$5 filter is about drinks, not $1 oysters", () => {
  const oystersOnly = { items: [{ category: "food", price_usd: 1 }, { category: "draft", price_usd: 6 }] };
  assert.equal(FILTERS.cheap.test(oystersOnly), false);
  assert.equal(FILTERS.food.test(oystersOnly), true);
  assert.equal(FILTERS.cheap.test({ items: [{ category: "draft", price_usd: 4 }] }), true);
});

/* ---- freshness -------------------------------------------------------- */

test("age is computed at read time, not frozen into the bundle", () => {
  const deal = { confidence: "likely", last_verified_at: "2026-07-31" };
  assert.equal(ageDays(deal, FRI_5PM), 0);
  assert.equal(ageDays(deal, new Date(2026, 7, 10, 12, 0)), 10);
  // The bug this prevents: a bundle built once and served for months would
  // otherwise keep reporting the age it had on build day.
  assert.equal(ageDays(deal, new Date(2026, 9, 1, 12, 0)), 62);
  assert.equal(ageDays({ confidence: "likely" }, FRI_5PM), null);
});

test("the decay ladder demotes on the same boundaries as the Python builder", () => {
  const at = (days) => new Date(2026, 6, 31 + days, 12, 0);
  const likely = { confidence: "likely", last_verified_at: "2026-07-31" };
  assert.equal(effectiveConfidence(likely, at(45)), "likely");
  assert.equal(effectiveConfidence(likely, at(46)), "unconfirmed");
  assert.equal(effectiveConfidence(likely, at(120)), "unconfirmed");
  assert.equal(effectiveConfidence(likely, at(121)), "hidden");

  // An operator confirmation and a user dispute are standing facts.
  for (const c of ["verified", "disputed"]) {
    assert.equal(effectiveConfidence({ confidence: c, last_verified_at: "2026-07-31" }, at(300)), c);
  }
});

test("a deal that has decayed out never reaches the feed", () => {
  const stale = {
    id: "stale", name: "Stale", zone_id: "z",
    deals: [{ ...HH, last_verified_at: "2026-01-01" }],
  };
  assert.equal(buildFeed([stale], FRI_5PM).length, 0);
});

/* ---- windows ---------------------------------------------------------- */

const HH = {
  confidence: "likely",
  items: [{ category: "draft", price_usd: 5 }],
  windows: [
    { dow: 5, start: "16:00", end: "18:00" }, // Friday
    { dow: 6, start: "14:00", end: "16:00" }, // Saturday
  ],
};

test("windowFor finds a live window and its remaining minutes", () => {
  const hit = windowFor(HH, FRI_5PM);
  assert.equal(hit.live, true);
  assert.equal(hit.until, 60);
});

test("windowFor sees a window starting inside the lookahead", () => {
  const hit = windowFor(HH, new Date(2026, 6, 31, 15, 0));
  assert.equal(hit.live, false);
  assert.equal(hit.startsIn, 60);
});

test("windowFor returns null once the day's windows are over or far off", () => {
  assert.equal(windowFor(HH, new Date(2026, 6, 31, 19, 0)), null);
  assert.equal(windowFor(HH, FRI_11AM), null, "11am is >3h before a 4pm window");
  assert.equal(windowFor(HH, SUN_11AM), null, "no Sunday window");
});

test("nextOccurrence never dead-ends -- it rolls to the next day that has one", () => {
  // 11am Friday: today's 4pm window is still ahead.
  const sameDay = nextOccurrence(HH, FRI_11AM);
  assert.equal(sameDay.dayAhead, 0);
  assert.equal(sameDay.startsIn, 5 * 60);

  // 7pm Friday: Friday is spent, so Saturday 2pm is next.
  const tomorrow = nextOccurrence(HH, new Date(2026, 6, 31, 19, 0));
  assert.equal(tomorrow.dayAhead, 1);
  assert.equal(tomorrow.startsIn, 19 * 60);

  // Sunday 11am: nothing until Friday, five days out. This is the case that
  // used to render an empty page.
  const nextWeek = nextOccurrence(HH, SUN_11AM);
  assert.equal(nextWeek.dayAhead, 5);
  assert.equal(nextWeek.live, false);
});

test("nextOccurrence still reports a live window as live", () => {
  const hit = nextOccurrence(HH, FRI_5PM);
  assert.equal(hit.live, true);
  assert.equal(hit.until, 60);
  assert.equal(hit.dayAhead, 0);
});

test("nextOccurrence returns null for a deal that never runs", () => {
  assert.equal(nextOccurrence({ windows: [] }, FRI_5PM), null);
});

/* ---- the ranking fix -------------------------------------------------- */

test("a live deal you cannot reach in time is demoted, not promoted", () => {
  const endingSoon = { live: true, until: 8, startsIn: 0, dayAhead: 0 };
  assert.equal(groupFor(endingSoon, 25), GROUP.UNREACHABLE, "8 min left, 25 min away");
  assert.equal(groupFor(endingSoon, 3), GROUP.LIVE, "8 min left, 3 min away");
  // With no location we cannot know, so we must not claim it.
  assert.equal(groupFor(endingSoon, null), GROUP.LIVE);
});

test("groupFor separates soon, later today, and another day", () => {
  assert.equal(groupFor({ live: false, startsIn: 45, dayAhead: 0 }, null), GROUP.SOON);
  assert.equal(groupFor({ live: false, startsIn: 400, dayAhead: 0 }, null), GROUP.LATER);
  assert.equal(groupFor({ live: false, startsIn: 1500, dayAhead: 1 }, null), GROUP.UPCOMING);
});

/* ---- the feed --------------------------------------------------------- */

const near = {
  id: "near", name: "Near Bar", zone_id: "z", lat: 40.089, lng: -75.396,
  deals: [{ ...HH, windows: [{ dow: 5, start: "16:00", end: "17:10" }] }],
};
const far = {
  id: "far", name: "Far Bar", zone_id: "z", lat: 39.91743, lng: -75.38833,
  deals: [{ ...HH, windows: [{ dow: 5, start: "16:00", end: "21:00" }] }],
};

test("ranking counts the deal you would actually get, not the minutes on the clock", () => {
  // "Near Bar" is next door but ends in 10 min, so you would get 7 usable
  // minutes. "Far Bar" is 12 miles off and runs another 4 hours. Ranking by
  // raw minutes-remaining -- the naive reading of "urgency" -- puts Near on
  // top, and that is the wrong answer to "where can I go right now".
  const rows = buildFeed([near, far], FRI_5PM, { origin: { lat: 40.089, lng: -75.396 } });
  assert.equal(rows.length, 2);
  assert.equal(rows[0].v.id, "far");
  assert.equal(usableMinutes(rows[1].hit, rows[1].driveMin), 7);
});

test("but a good deal nearby beats a longer one across the county", () => {
  // The case that caught a bad weighting: 90 minutes left three minutes away is
  // obviously better than four hours left forty minutes away, and an early
  // draft of the score preferred the far one.
  const closeAndDecent = {
    id: "close", name: "Close", zone_id: "z", lat: 40.089, lng: -75.396,
    deals: [{ ...HH, windows: [{ dow: 5, start: "16:00", end: "18:30" }] }],
  };
  const rows = buildFeed([far, closeAndDecent], FRI_5PM, {
    origin: { lat: 40.089, lng: -75.396 },
  });
  assert.equal(rows[0].v.id, "close");
});

test("a live deal that ends before you could arrive sorts to the bottom", () => {
  const fleeting = {
    id: "fleeting", name: "Fleeting", zone_id: "z", lat: 39.91743, lng: -75.38833,
    deals: [{ ...HH, windows: [{ dow: 5, start: "16:00", end: "17:05" }] }],
  };
  const rows = buildFeed([fleeting, far], FRI_5PM, { origin: { lat: 40.089, lng: -75.396 } });
  assert.equal(rows[rows.length - 1].v.id, "fleeting");
  assert.equal(rows[rows.length - 1].group, GROUP.UNREACHABLE);
});

test("buildFeed honours zone and filter, and never returns a disputed deal", () => {
  const disputed = {
    id: "d", name: "Disputed", zone_id: "z", deals: [{ ...HH, confidence: "disputed" }],
  };
  assert.equal(buildFeed([disputed], FRI_5PM).length, 0);
  assert.equal(buildFeed([near, far], FRI_5PM, { zone: "other" }).length, 0);
  assert.equal(buildFeed([near, far], FRI_5PM, { filter: "food" }).length, 0);
});

test("buildFeed still answers on a Sunday morning", () => {
  const rows = buildFeed([near, far], SUN_11AM);
  assert.equal(rows.length, 2, "the old windowFor path returned nothing here");
  assert.ok(rows.every((r) => r.group === GROUP.UPCOMING));
});

test("sort=nearest puts the closest first regardless of timing", () => {
  const rows = buildFeed([far, near], FRI_5PM, {
    origin: { lat: 40.089, lng: -75.396 }, sort: "nearest",
  });
  assert.equal(rows[0].v.id, "near");
});

/* ---- schedule copy ---------------------------------------------------- */

test("summarizeWindows collapses a week into one readable line", () => {
  const weekday = [1, 2, 3, 4, 5].map((dow) => ({ dow, start: "16:00", end: "18:00" }));
  assert.equal(summarizeWindows(weekday), "Mon–Fri 4pm–6pm");

  const split = [
    ...weekday,
    { dow: 6, start: "14:00", end: "16:00" },
    { dow: 7, start: "14:00", end: "16:00" },
  ];
  assert.equal(summarizeWindows(split), "Mon–Fri 4pm–6pm · Sat, Sun 2pm–4pm");

  assert.equal(
    summarizeWindows([{ dow: 3, start: "16:00", end: "18:00" }]),
    "Wed 4pm–6pm"
  );
});
