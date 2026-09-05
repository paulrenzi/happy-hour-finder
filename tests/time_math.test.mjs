/* The time math is the part that can be wrong invisibly: a card shown on the
   wrong day still looks like a correct card. Run with:

       node --test tests/

   Dates are built with explicit local components. `new Date(2026, 6, 31, 17, 0)`
   is Fri 31 Jul 2026, 5:00pm -- asserted below rather than assumed. */

import test from "node:test";
import assert from "node:assert/strict";
import {
  dowOf, mins, fmtClock, fmtMins, itemParts, sortForDisplay, haversineMiles, driveMinutes, fmtMiles,
  dealValue, cheapestPrice, FILTERS, windowFor, nextOccurrence, groupFor, GROUP,
  buildFeed, summarizeWindows, usableMinutes, ageDays, effectiveConfidence,
  GROUP_LABEL, score, dealKey, applyConfirmations, DAY_BAND,
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

test("sortForDisplay puts drinks first, food last, order otherwise stable", () => {
  const items = [
    { category: "food", label: "wings" },
    { category: "draft", label: "lager" },
    { category: "cocktail", label: "martini" },
    { category: "food", label: "nachos" },
    { category: "daily_special", label: "trivia" },
  ];
  assert.deepEqual(sortForDisplay(items).map((i) => i.label),
    ["lager", "martini", "trivia", "wings", "nachos"]);
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
  assert.equal(FILTERS.cheap.test({ items: [{ category: "draft", price_usd: 4 }] }), true);
});

/* Live music and Events are two chips because they are two questions. Wayne's
   first read returned bands, DJs, music bingo and a history lecture from four
   bars, and a reader who taps "Live music" and is handed bingo reads that as
   the board being wrong. */
test("the event filters split on kind and ask about the venue, not the deal", () => {
  const band = { date: "2026-09-12", kind: "live_music" };
  const bingo = { date: "2026-09-10", kind: "trivia" };
  const today = "2026-09-05";
  assert.equal(FILTERS.music.venueTest({ events: [band, bingo] }, today), true);
  assert.equal(FILTERS.music.venueTest({ events: [bingo] }, today), false);
  assert.equal(FILTERS.events.venueTest({ events: [bingo] }, today), true);
  assert.equal(FILTERS.events.venueTest({ events: [band] }, today), false);
  // A venue with no calendar answers "no" to both, and does not throw.
  assert.equal(FILTERS.music.venueTest({}, today), false);
  // Last night's band is not tonight's. Past dates never match.
  assert.equal(FILTERS.music.venueTest({ events: [{ date: "2026-09-01", kind: "live_music" }] }, today), false);
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

test("inside a future day, the nearer venue leads -- opening earliest is not urgency", () => {
  /* Paul, live on the phone: a brewery seventeen miles away outranked a bar
     down the street in the Tomorrow section, for the sole reason that it opened
     at 11am. Another day is not an urgency -- 11am and 4pm are both "not now",
     and once we know where the reader is standing, distance is the fact that
     actually separates them. */
  const farEarly = {
    id: "farEarly", name: "Far Early", zone_id: "z", lat: 39.91743, lng: -75.38833,
    deals: [{ ...HH, windows: [{ dow: 6, start: "11:00", end: "14:00" }] }],
  };
  const nearLate = {
    id: "nearLate", name: "Near Late", zone_id: "z", lat: 40.089, lng: -75.396,
    deals: [{ ...HH, windows: [{ dow: 6, start: "16:00", end: "18:00" }] }],
  };
  const rows = buildFeed([farEarly, nearLate], FRI_5PM, {
    origin: { lat: 40.089, lng: -75.396 },
  });
  assert.equal(rows[0].group, GROUP.UPCOMING);
  assert.equal(rows[0].v.id, "nearLate");

  // With no location we have nothing better than the clock, and we keep it.
  const blind = buildFeed([farEarly, nearLate], FRI_5PM, {});
  assert.equal(blind[0].v.id, "farEarly");
});

test("a venue we cannot place does not outrank one we can", () => {
  // 2,100 of 2,900 venues have no coordinates. Floating every one of them above
  // the bars we CAN place would undo the whole point of asking for a location.
  const placeless = {
    id: "placeless", name: "Placeless", zone_id: "z",
    deals: [{ ...HH, windows: [{ dow: 6, start: "11:00", end: "14:00" }] }],
  };
  const placed = {
    id: "placed", name: "Placed", zone_id: "z", lat: 40.089, lng: -75.396,
    deals: [{ ...HH, windows: [{ dow: 6, start: "16:00", end: "18:00" }] }],
  };
  const rows = buildFeed([placeless, placed], FRI_5PM, {
    origin: { lat: 40.089, lng: -75.396 },
  });
  assert.equal(rows[0].v.id, "placed");
});

/* THE "TOMORROW" HEADER, PRINTED TWENTY TIMES.

   The board starts a new section whenever the label changes, and the label is
   the row's day. So the ORDER has to put a day's rows together -- otherwise one
   Monday row landing between two Saturday ones prints "Tomorrow" on both sides
   of it, and a week of rows shredded the headers into twenty of them.

   The day band existed in exactly one of four paths through score(): "soonest"
   WITH a location. Every reader who had not granted location, and every reader
   who picked Nearest or Best value, got a globally ranked feed. The fixture
   below is built so the furthest day holds the nearest, cheapest and earliest
   bar there is -- if any sort ranks on its own criterion first, Monday jumps to
   the top and Saturday's header is printed twice. */
const ACROSS_DAYS = (() => {
  const here = { lat: 40.0, lng: -75.3 };
  const make = (id, dow, start, price, lat, lng) => ({
    id, name: id, zone_id: "z", lat, lng,
    deals: [{
      confidence: "likely",
      items: [{ category: "draft", price_usd: price }],
      windows: [{ dow, start, end: "23:00" }],
    }],
  });
  return {
    here,
    // Saturday is TOMORROW from FRI_5PM; Monday is three days out.
    venues: [
      make("satLate", 6, "20:00", 12, 40.30, -75.60),
      make("satMid", 6, "17:00", 9, 40.05, -75.35),
      make("sunMid", 7, "18:00", 8, 40.06, -75.36),
      // Nearest, cheapest and earliest on the board -- and the furthest away in
      // days. Every non-day criterion wants this row first.
      make("monBest", 1, "11:00", 2, 40.0, -75.3),
      make("monMid", 1, "19:00", 7, 40.07, -75.37),
    ],
  };
})();

test("a day's rows stay together, in every sort, with or without a location", () => {
  for (const sort of ["soonest", "nearest", "value"]) {
    for (const origin of [ACROSS_DAYS.here, null]) {
      const where = `${sort}/${origin ? "located" : "blind"}`;
      const rows = buildFeed(ACROSS_DAYS.venues, FRI_5PM, { sort, origin, now: FRI_5PM });
      assert.equal(rows.length, 5, where);
      assert.ok(rows.every((r) => r.group === GROUP.UPCOMING), where);

      // The days come out in calendar order and never come back.
      const seq = rows.map((r) => r.dayIndex);
      for (let i = 1; i < seq.length; i++) {
        assert.ok(seq[i] >= seq[i - 1], `${where}: day ${seq[i]} after ${seq[i - 1]} in ${seq}`);
      }
      // Which is the same thing as: a day is printed once.
      const printed = [...new Set(seq)];
      assert.deepEqual(printed, [1, 2, 3], where);
      assert.notEqual(rows[0].v.id, "monBest", `${where}: a Monday row led the feed`);
    }
  }
});

test("inside one day, the sort the reader chose still decides", () => {
  // Banding by day must not flatten the ranking -- it only scopes it.
  const monday = (rows) => rows.filter((r) => r.dayIndex === 3).map((r) => r.v.id);
  const near = buildFeed(ACROSS_DAYS.venues, FRI_5PM, {
    sort: "nearest", origin: ACROSS_DAYS.here, now: FRI_5PM,
  });
  assert.deepEqual(monday(near), ["monBest", "monMid"]);

  const value = buildFeed(ACROSS_DAYS.venues, FRI_5PM, { sort: "value", now: FRI_5PM });
  assert.deepEqual(monday(value), ["monBest", "monMid"]);

  // With no location, the clock WITHIN the day -- not minutes from now, which
  // carries the day inside it and would re-rank the calendar we just fixed.
  const blind = buildFeed(ACROSS_DAYS.venues, FRI_5PM, { sort: "soonest", now: FRI_5PM });
  assert.deepEqual(monday(blind), ["monBest", "monMid"]);
});

test("no future row can score into the next day's band or the next group's", () => {
  for (const sort of ["soonest", "nearest", "value"]) {
    for (const origin of [ACROSS_DAYS.here, null]) {
      for (const row of buildFeed(ACROSS_DAYS.venues, FRI_5PM, { sort, origin, now: FRI_5PM })) {
        const s = score(row, { sort });
        const band = Math.floor((s - GROUP.UPCOMING * 100000) / DAY_BAND);
        assert.equal(band, row.dayIndex, `${sort}: ${row.v.id} scored outside its day`);
        assert.ok(s < (GROUP.UPCOMING + 1) * 100000, `${sort}: ${row.v.id} leaked a group`);
      }
    }
  }
});

test("a row seven days out never scores into the next group's band", () => {
  /* The score is group * 100000 plus a within-group term. A window seven days
     away is 10,080 minutes of shortfall, which unclamped is 100,800 -- past the
     100,000 a group is worth -- so it sorted below an UNREACHABLE row and split
     its own day's section header in two. */
  const weekOut = {
    id: "weekOut", name: "Week Out", zone_id: "z",
    deals: [{ ...HH, windows: [{ dow: 5, start: "11:00", end: "14:00" }] }],
  };
  const rows = buildFeed([weekOut], FRI_5PM, {});
  assert.equal(rows[0].group, GROUP.UPCOMING);
  assert.ok(
    score(rows[0]) < (GROUP.UPCOMING + 1) * 100000,
    `score ${score(rows[0])} leaked into the group above`
  );
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
  assert.equal(buildFeed([near, far], FRI_5PM, { filter: "music" }).length, 0);
});

/* An event filter is a VENUE question, so a bar with a band and no published
   happy hour still gets its row -- that bar is exactly the one worth showing.
   Asking it per-deal would have dropped it. */
test("an event filter keeps a venue whose window we do not know", () => {
  const noWindow = {
    id: "band-no-hours", name: "Band, no hours", zone_id: "z", deals: [],
    events: [{ id: "e1", date: "2026-08-08", kind: "live_music", act: "A Band" }],
  };
  const rows = buildFeed([noWindow, near], FRI_5PM, { filter: "music", now: FRI_5PM });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].v.id, "band-no-hours");
  assert.equal(rows[0].deal, null);
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

/* ---- venues with no published happy hour ------------------------------

   The reframe, 2026-08-07: the board is a list of VENUES and the happy hour is
   an attribute some of them have. 2,732 of 2,901 licensed venues have no window
   anyone published, and the old feed dropped every one of them -- so King of
   Prussia showed 6 cards against 59 real bars, and a person who KNEW one of the
   missing windows had nothing on screen to correct. */

const noHours = {
  id: "133026", lid: "133026", name: "Bald Birds Brewing", zone_id: "z",
  address: "250 King Manor Dr, King Of Prussia PA 19406", deals: [],
};

test("a venue with no deals still gets a row", () => {
  const rows = buildFeed([noHours], FRI_5PM);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].group, GROUP.UNKNOWN);
  assert.equal(rows[0].deal, null, "there is no deal to describe");
  assert.equal(rows[0].hit, null, "and no window to be early or late for");
});

test("it sorts below every venue that HAS a window, including an unreachable one", () => {
  const fleeting = {
    id: "fleeting", name: "Fleeting", zone_id: "z", lat: 39.91743, lng: -75.38833,
    deals: [{ ...HH, windows: [{ dow: 5, start: "16:00", end: "17:05" }] }],
  };
  const rows = buildFeed([noHours, fleeting, near], FRI_5PM, {
    origin: { lat: 40.089, lng: -75.396 },
  });
  assert.equal(rows[rows.length - 1].v.id, "133026");
  // A real window we cannot reach is still a better answer than no window.
  assert.ok(GROUP.UNKNOWN > GROUP.UNREACHABLE);
});

test("a DEAL filter excludes it -- an empty venue cannot answer 'food deals'", () => {
  for (const f of ["food", "cheap", "drinks"]) {
    assert.equal(buildFeed([noHours], FRI_5PM, { filter: f }).length, 0, f);
  }
  assert.equal(buildFeed([noHours], FRI_5PM, { filter: "all" }).length, 1);
});

test("it still obeys the zone, and answers at every hour of the week", () => {
  assert.equal(buildFeed([noHours], FRI_5PM, { zone: "other" }).length, 0);
  // Unlike a deal, it has no schedule to fall off -- Sunday morning included.
  for (const at of [FRI_5PM, FRI_11AM, SUN_11AM]) {
    assert.equal(buildFeed([noHours], at).length, 1);
  }
});

test("scoring one never reads the deal it does not have", () => {
  // dealValue(null) and row.hit.live would both throw; the group is checked
  // before either is touched, under every sort the UI offers.
  const rows = buildFeed([noHours], FRI_5PM);
  for (const sort of ["soonest", "nearest", "value"]) {
    assert.equal(typeof score(rows[0], { sort }), "number", sort);
  }
});

test("with a location, the nearest unlisted venue comes first", () => {
  // Distance is the only fact we have about these, so it is the only ordering
  // that can be honest.
  const close = { ...noHours, id: "a", lid: "a", lat: 40.089, lng: -75.396 };
  const distant = { ...noHours, id: "b", lid: "b", lat: 39.91743, lng: -75.38833 };
  const rows = buildFeed([distant, close], FRI_5PM, { origin: { lat: 40.089, lng: -75.396 } });
  assert.equal(rows[0].v.id, "a");
});

test("the group has a label, so the section header is never blank", () => {
  assert.equal(typeof GROUP_LABEL[GROUP.UNKNOWN], "string");
  assert.ok(GROUP_LABEL[GROUP.UNKNOWN].length > 0);
});

test("a confirmation is keyed to the hours, so changed hours drop it", () => {
  const a = { type: "happy_hour", windows: [{ dow: 1, start: "16:00", end: "18:00" }] };
  const b = { type: "happy_hour", windows: [{ dow: 1, start: "17:00", end: "19:00" }] };
  const reordered = {
    type: "happy_hour",
    windows: [{ dow: 1, start: "16:00", end: "18:00" }],
  };
  assert.equal(dealKey(a), dealKey(reordered));
  assert.notEqual(dealKey(a), dealKey(b));
});

test("one person standing in the bar outranks an unconfirmed photo read", () => {
  const deal = {
    type: "happy_hour",
    windows: [{ dow: 1, start: "16:00", end: "18:00" }],
    items: [],
    confidence: "unconfirmed",
    last_verified_at: "2026-07-01",
  };
  const venues = [{ id: "77", lid: "77", deals: [deal] }];
  applyConfirmations(venues, { [`77:${dealKey(deal)}`]: { n: 3, last: "2026-08-30" } });
  assert.equal(deal.confidence, "verified");
  assert.equal(deal.confirmations, 3);
  assert.equal(deal.last_verified_at, "2026-08-30");
});

test("a disputed deal is not talked back up by a confirmation", () => {
  const deal = {
    type: "happy_hour",
    windows: [{ dow: 2, start: "16:00", end: "18:00" }],
    items: [],
    confidence: "disputed",
    last_verified_at: "2026-08-01",
  };
  const venues = [{ id: "78", lid: "78", deals: [deal] }];
  applyConfirmations(venues, { [`78:${dealKey(deal)}`]: { n: 5, last: "2026-08-30" } });
  assert.equal(deal.confidence, "disputed");
});

test("a confirmation for hours nobody published matches nothing", () => {
  const deal = {
    type: "happy_hour",
    windows: [{ dow: 3, start: "16:00", end: "18:00" }],
    items: [],
    confidence: "likely",
    last_verified_at: "2026-08-01",
  };
  const venues = [{ id: "79", lid: "79", deals: [deal] }];
  assert.equal(applyConfirmations(venues, { "79:happy_hour|9:00:00-01:00": { n: 9 } }), 0);
  assert.equal(deal.confidence, "likely");
});

/* ---- a day that is not today ------------------------------------------

   Picking "Tomorrow" used to file 210 cards as "Live now" and 71 as "Ends
   before you'd get there" -- both verdicts about the present, said of a day
   that has not started. Two causes, both here: the picker anchored a future
   day at a fixed hour and every window ENDING before that hour was read as
   already over, and the grouper had no idea the clock it was handed was a
   hypothetical. Nothing gated on either, so the board asserted it daily. */

test("no future day can produce a verdict about the present", () => {
  const deal = {
    type: "happy_hour",
    // Every day, straddling any hour a picker might anchor on.
    windows: [1, 2, 3, 4, 5, 6, 7].map((dow) => ({ dow, start: "15:00", end: "19:00" })),
    items: [{ category: "draft", label: "pint", price_usd: 4 }],
    confidence: "verified",
    last_verified_at: "2026-07-30",
  };
  const venues = [{ id: "1", lid: "1", name: "Anywhere", zone_id: "z",
                    lat: 40.01, lng: -75.29, deals: [deal] }];
  const origin = { lat: 40.0, lng: -75.3 }; // close enough that driveMin is small

  for (let dayAhead = 1; dayAhead <= 6; dayAhead++) {
    const at = new Date(FRI_5PM);
    at.setDate(at.getDate() + dayAhead);
    at.setHours(0, 0, 0, 0);
    const rows = buildFeed(venues, at, { origin, planning: true, now: FRI_5PM });
    assert.equal(rows.length, 1);
    const g = rows[0].group;
    assert.notEqual(g, GROUP.LIVE, `day +${dayAhead} claimed LIVE`);
    assert.notEqual(g, GROUP.UNREACHABLE, `day +${dayAhead} claimed UNREACHABLE`);
    assert.notEqual(g, GROUP.SOON, `day +${dayAhead} claimed SOON`);
    assert.equal(g, GROUP.UPCOMING);
  }
});

test("a day anchored at its first minute still shows its lunchtime windows", () => {
  // Saturday 11:30-15:00 -- entirely before the 4pm/5pm anchors the picker
  // used, which read it as over and rolled it forward a whole week.
  const deal = {
    type: "happy_hour",
    windows: [{ dow: 6, start: "11:30", end: "15:00" }],
    items: [],
    confidence: "likely",
    last_verified_at: "2026-07-30",
  };
  const sat = new Date(2026, 7, 1, 0, 0); // Sat 1 Aug 2026, first minute
  assert.equal(dowOf(sat), 6); // Mon=1 .. Sun=7
  const hit = nextOccurrence(deal, sat, 7);
  assert.equal(hit.dayAhead, 0, "the day's own lunchtime window must be on the day");
  assert.equal(hit.dateKey, "2026-08-01");

  // The same day anchored at 5pm cannot see it at all -- it lands next week.
  const at5 = new Date(2026, 7, 1, 17, 0);
  assert.equal(nextOccurrence(deal, at5, 7).dayAhead, 7);
});

test("a hit names its own calendar date, so a label cannot drift with the anchor", () => {
  const deal = {
    type: "happy_hour",
    windows: [{ dow: 1, start: "16:00", end: "18:00" }], // Monday
    items: [],
    confidence: "likely",
    last_verified_at: "2026-07-30",
  };
  // dayAhead is measured from the ANCHOR, so it only means "tomorrow" when the
  // anchor is today -- move the anchor and the same dayAhead names a different
  // day. That is what printed "Tomorrow" over the day after tomorrow. The date
  // is absolute and survives the move.
  const sat = new Date(2026, 7, 1, 12, 0);
  assert.equal(nextOccurrence(deal, sat, 7).dateKey, "2026-08-03");
  const nextSat = new Date(2026, 7, 8, 12, 0);
  assert.equal(nextOccurrence(deal, nextSat, 7).dateKey, "2026-08-10");
});
