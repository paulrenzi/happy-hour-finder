/* The night-out layer: events overlay, the card line, the signup rule, and the
   Worker's event validator. Run with:  node --test tests/ */

import test from "node:test";
import assert from "node:assert/strict";
import { applyEvents, nextEvent, eventLine, validEmail } from "../web/lib.js";
import { eventFrom, eventFingerprint, expandRecurring, weekdayOf } from "../worker/nightout.js";

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

/* ---- recurring weekly shows (PLAYBOOK-NIGHT-OUT.md §15) ----------------- */

const weekly = (extra = {}) => ({
  id: "r1", lid: "111", date: "2026-09-10", act: "Music Bingo", kind: "trivia",
  start: "19:00", recurs: "weekly", until: "2026-10-15", ...extra,
});

test("a weekly rule and a one-off on the same day are different rows", () => {
  const rule = eventFrom({ ...weekly() }, { lid: "111", source_kind: "page", status: "pending" }).row;
  const once = eventFrom({ ...weekly(), recurs: null, until: null }, { lid: "111", source_kind: "page", status: "pending" }).row;
  assert.notEqual(eventFingerprint(rule), eventFingerprint(once));
});

test("🛑 a weekly rule keeps ONE id as its first date moves week to week", () => {
  // This is the whole reason recurrence is in the schema: keyed on `date`, a
  // re-read next Thursday minted a new id, so it landed `pending` again and the
  // human ruling could never stick.
  const a = eventFrom(weekly(), { lid: "111", source_kind: "page", status: "pending" }).row;
  const b = eventFrom({ ...weekly(), date: "2026-09-17" }, { lid: "111", source_kind: "page", status: "pending" }).row;
  assert.equal(eventFingerprint(a), eventFingerprint(b));
  assert.equal(weekdayOf("2026-09-10"), weekdayOf("2026-09-17"));
});

test("a weekly rule expands to one dated row per week in the window", () => {
  const out = expandRecurring([weekly()], "2026-09-05", "2026-09-19");
  assert.deepEqual(out.map((r) => r.date), ["2026-09-10", "2026-09-17"]);
  assert.deepEqual(out.map((r) => r.id), ["r1-2026-09-10", "r1-2026-09-17"]);
  assert.equal(out[0].rule_id, "r1");
  assert.equal(out[0].act, "Music Bingo");
});

test("expansion starts at the window, not at the rule's first date", () => {
  // A rule first seen weeks ago must still produce THIS fortnight's dates.
  const out = expandRecurring([weekly({ date: "2026-07-02", until: "2026-12-01" })], "2026-09-05", "2026-09-19");
  assert.deepEqual(out.map((r) => r.date), ["2026-09-10", "2026-09-17"]);
});

test("🛑 `until` retires a show that quietly ended -- it is not open-ended", () => {
  const out = expandRecurring([weekly({ until: "2026-09-10" })], "2026-09-05", "2026-09-19");
  assert.deepEqual(out.map((r) => r.date), ["2026-09-10"]);
  assert.equal(expandRecurring([weekly({ until: "2026-09-01" })], "2026-09-05", "2026-09-19").length, 0);
});

test("a one-off passes through expansion untouched", () => {
  const rows = [{ ...weekly(), recurs: null, until: null }];
  assert.deepEqual(expandRecurring(rows, "2026-09-05", "2026-09-19"), rows);
});

test("an unread `until` defaults to a bounded trust window, never forever", () => {
  const row = eventFrom({ ...weekly(), until: null }, { lid: "111", source_kind: "page", status: "pending" }).row;
  assert.equal(row.until, "2026-10-15"); // date + 35 days
  assert.ok(row.until > row.date);
});

test("recurs is validated, and a one-off never carries an until", () => {
  assert.match(eventFrom({ ...weekly(), recurs: "daily" }, { lid: "111", source_kind: "page", status: "pending" }).error, /weekly/);
  assert.match(eventFrom({ ...weekly(), until: "next year" }, { lid: "111", source_kind: "page", status: "pending" }).error, /until/);
  assert.match(eventFrom({ ...weekly(), until: "2026-09-01" }, { lid: "111", source_kind: "page", status: "pending" }).error, /before/);
  assert.equal(eventFrom({ ...weekly(), recurs: null }, { lid: "111", source_kind: "page", status: "pending" }).row.until, null);
});

test("the page needs no new code: an expanded row is what nextEvent already eats", () => {
  const v = venue("111", []);
  applyEvents([v], { venues: { 111: expandRecurring([weekly()], "2026-09-05", "2026-09-19") } });
  assert.equal(v.events.length, 2);
  assert.equal(nextEvent(v, "2026-09-05").date, "2026-09-10");
  assert.equal(nextEvent(v, "2026-09-11").date, "2026-09-17");
});
