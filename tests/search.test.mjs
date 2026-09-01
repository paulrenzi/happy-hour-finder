/* Finding a bar by name. The board is 169 venues, so this is a filter over data
   already in hand -- but it is the filter, not the DOM, that can be wrong in a
   way nobody sees, so it lives in lib.js and is tested here. */
import test from "node:test";
import assert from "node:assert/strict";
import { normalizeName, matchesQuery, buildFeed } from "../web/lib.js";

const AT = new Date("2026-09-01T17:00:00");

const venue = (name, zone_id = "wayne_radnor") => ({
  id: name, lid: name, name, zone_id, deals: [],
});

test("a name is reduced to what a person would actually type at it", () => {
  assert.equal(normalizeName("P.J. Whelihan's"), "p j whelihan s");
  assert.equal(normalizeName("  Café   Lift  "), "cafe lift");
  assert.equal(normalizeName(""), "");
  assert.equal(normalizeName(undefined), "");
});

test("a partial word finds the venue before you finish typing it", () => {
  assert.equal(matchesQuery(venue("Black Powder Tavern"), "powd"), true);
});

test("word order is not part of the request", () => {
  assert.equal(matchesQuery(venue("Black Powder Tavern"), "tavern black"), true);
});

test("punctuation nobody reproduces does not block the match", () => {
  assert.equal(matchesQuery(venue("P.J. Whelihan's"), "pj whelihans"), true);
  assert.equal(matchesQuery(venue("Café Lift"), "cafe"), true);
});

test("a different bar is not a match", () => {
  assert.equal(matchesQuery(venue("Black Powder Tavern"), "iron hill"), false);
});

test("an empty query matches everything, so the board is unfiltered", () => {
  assert.equal(matchesQuery(venue("Anything"), ""), true);
  assert.equal(matchesQuery(venue("Anything"), "   "), true);
});

test("searching asks about the whole board, not the town you last picked", () => {
  // The failure this guards: you can see the bar on the map, you type its name,
  // and you get nothing because a town filter you set earlier is still on.
  const venues = [venue("Black Powder Tavern", "wayne_radnor"), venue("Iron Hill", "media")];
  const rows = buildFeed(venues, AT, { zone: "media", query: "black powder" });
  assert.deepEqual(rows.map((r) => r.v.name), ["Black Powder Tavern"]);
});

test("with no query the town filter still applies", () => {
  const venues = [venue("Black Powder Tavern", "wayne_radnor"), venue("Iron Hill", "media")];
  const rows = buildFeed(venues, AT, { zone: "media" });
  assert.deepEqual(rows.map((r) => r.v.name), ["Iron Hill"]);
});

test("a venue with no published hours is still findable by name", () => {
  // It is most of the board, and it is the only way a person can tell us the
  // hours are missing.
  const rows = buildFeed([venue("Black Powder Tavern")], AT, { query: "black" });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].deal, null);
});
