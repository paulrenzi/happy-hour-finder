/* The night-out layer: events overlay, the card line, the signup rule, and the
   Worker's event validator. Run with:  node --test tests/ */

import test from "node:test";
import assert from "node:assert/strict";
import { applyEvents, nextEvent, eventLine, validEmail } from "../web/lib.js";
import { eventFrom, eventFingerprint } from "../worker/nightout.js";

const venue = (lid, events) => ({ id: "v" + lid, name: "A Bar", lid, events });
const ev = (id, date, extra = {}) => ({ id, lid: "111", date, act: "Rhythm & Blondes", kind: "live_music", ...extra });

test("events land on their venue and not twice", () => {
  const v = venue("111", undefined);
  const overlay = { venues: { 111: [ev("e1", "2026-09-04"), ev("e2", "2026-09-05")] } };
  assert.equal(applyEvents([v], overlay), 2);
  assert.equal(applyEvents([v], overlay), 0);
  assert.equal(v.events.length, 2);
});

test("a venue not loaded is skipped, not an error", () => {
  assert.equal(applyEvents([venue("999", [])], { venues: { 111: [ev("e1", "2026-09-04")] } }), 0);
});

test("nextEvent skips the past and returns the soonest", () => {
  const v = venue("111", []);
  applyEvents([v], { venues: { 111: [ev("b", "2026-09-06"), ev("a", "2026-09-05"), ev("old", "2026-09-01")] } });
  assert.equal(nextEvent(v, "2026-09-04").id, "a");
  assert.equal(nextEvent(v, "2026-09-07"), null);
});

/* 118 North, Wayne, Saturday 2026-09-05 -- the real rows the reader returned.
   Two sets in one night, and this board is read between 4 and 6. */
test("nextEvent skips a set that has already started today", () => {
  const v = venue("111", []);
  applyEvents([v], { venues: { 111: [
    ev("late", "2026-09-05", { act: "Creem Circus + The Sound Minds", start: "20:00" }),
    ev("early", "2026-09-05", { act: "Main Line School of Rock", start: "16:00" }),
    ev("sun", "2026-09-06", { act: "Billy Price Band", start: "19:30" }),
  ] } });
  // Before either set, the 4pm one is genuinely next.
  assert.equal(nextEvent(v, "2026-09-05", 15 * 60).id, "early");
  // At 6pm -- mid happy hour -- the 4pm set is over and the 8pm one is the answer.
  assert.equal(nextEvent(v, "2026-09-05", 18 * 60).id, "late");
  // After the last set of the night, roll to tomorrow rather than re-offering it.
  assert.equal(nextEvent(v, "2026-09-05", 22 * 60).id, "sun");
  // No clock passed = the old date-only behaviour, unchanged.
  assert.equal(nextEvent(v, "2026-09-05").id, "early");
});

/* Blank means unknown, never "already over" (rule 4). A venue that printed no
   start time must not lose its night to a clock comparison it never entered. */
test("nextEvent never skips an event whose start is unknown", () => {
  const v = venue("111", []);
  applyEvents([v], { venues: { 111: [ev("noTime", "2026-09-05", { start: null })] } });
  assert.equal(nextEvent(v, "2026-09-05", 23 * 60).id, "noTime");
});

test("the card line says only what the row says", () => {
  assert.equal(eventLine(ev("e", "2026-09-04"), "2026-09-04"), "Tonight · Rhythm & Blondes");
  assert.equal(
    eventLine(ev("e", "2026-09-05", { start: "19:00", end: "22:00", cover_usd: 5, kitchen_open: 1 }), "2026-09-04"),
    "Tomorrow · Rhythm & Blondes 7pm–10pm · $5 cover · kitchen open"
  );
  assert.equal(eventLine(ev("e", "2026-09-08", { cover_usd: 0 }), "2026-09-04"), "Tue · Rhythm & Blondes · no cover");
  // Beyond a week the day name alone is ambiguous, so the date rides along.
  assert.match(eventLine(ev("e", "2026-09-15"), "2026-09-04"), /^Tue 9\/15 · /);
  // An end without a start is not a range.
  assert.equal(eventLine(ev("e", "2026-09-04", { end: "22:00" }), "2026-09-04"), "Tonight · Rhythm & Blondes");
});

test("email rule", () => {
  assert.ok(validEmail("paul@example.com"));
  assert.ok(!validEmail("paul@example"));
  assert.ok(!validEmail("not an email"));
  assert.ok(!validEmail(""));
});

test("the Worker accepts a clean row and refuses a dirty one", () => {
  const ctx = { lid: "111", zone_id: "phoenixville", source_kind: "venue_form", status: "approved" };
  const ok = eventFrom({ date: "2026-09-05", act: "Tucker Michaels", start: "19:00", end: "22:00", cover_usd: "5", kitchen_open: "yes" }, ctx);
  assert.equal(ok.error, undefined);
  assert.equal(ok.row.cover_usd, 5);
  assert.equal(ok.row.kitchen_open, 1);
  assert.equal(ok.row.kind, "live_music");
  assert.equal(ok.row.status, "approved");

  assert.match(eventFrom({ date: "9/5", act: "x" }, ctx).error, /YYYY-MM-DD/);
  assert.match(eventFrom({ date: "2026-09-05" }, ctx).error, /act/);
  assert.match(eventFrom({ date: "2026-09-05", act: "x", start: "7pm" }, ctx).error, /HH:MM/);
  assert.match(eventFrom({ date: "2026-09-05", act: "x", kind: "rave" }, ctx).error, /kind/);
  assert.match(eventFrom({ date: "2026-09-05", act: "x", cover_usd: -1 }, ctx).error, /cover/);
  // Blank means unknown, never zero.
  assert.equal(eventFrom({ date: "2026-09-05", act: "x", cover_usd: "" }, ctx).row.cover_usd, null);
  assert.equal(eventFrom({ date: "2026-09-05", act: "x", kitchen_open: "" }, ctx).row.kitchen_open, null);
});

test("the same night from the same venue is one fingerprint", () => {
  const a = eventFingerprint({ lid: "111", date: "2026-09-05", act: "Rhythm & Blondes" });
  const b = eventFingerprint({ lid: "111", date: "2026-09-05", act: "rhythm and blondes!" });
  const c = eventFingerprint({ lid: "111", date: "2026-09-06", act: "Rhythm & Blondes" });
  assert.equal(a, b);
  assert.notEqual(a, c);
});
