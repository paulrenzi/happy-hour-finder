/* The live overlay: approved deals patched over the static bundles.

   This is the one part of the app that can change what a reader sees without a
   rebuild, so its merge rule has to be exactly the one review_photos.py applies
   at approval time. Run with:

       node --test tests/
*/

import test from "node:test";
import assert from "node:assert/strict";
import { applyOverlay } from "../web/lib.js";

const photoDeal = (photoId, submitted, dow) => ({
  type: "happy_hour",
  windows: [{ dow, start: "17:00", end: "19:00" }],
  items: [],
  confidence: "unconfirmed",
  source: { kind: "photo", photo_id: photoId, submitted },
});

const siteDeal = (dow) => ({
  type: "happy_hour",
  windows: [{ dow, start: "16:00", end: "18:00" }],
  items: [],
  confidence: "likely",
  source: { kind: "venue_site", url: "https://example.com" },
});

const venue = (deals) => ({ id: "v1", name: "A Bar", lid: "111", deals });

test("an approved deal lands on a venue that had none", () => {
  const v = venue([]);
  const out = applyOverlay([v], {
    venues: [{ lid: "111", deals: [photoDeal("p1", "2026-08-31T22:00:00Z", 1)] }],
  });
  assert.equal(out.added, 1);
  assert.equal(v.deals.length, 1);
  assert.equal(v.deals[0].source.photo_id, "p1");
});

test("a deal already in the bundle is not added twice", () => {
  // The rebuild has happened: the bundle now contains p1, and the overlay is
  // still serving it because the Worker has no idea when Paul last built.
  const v = venue([photoDeal("p1", "2026-08-31T22:00:00Z", 1)]);
  const out = applyOverlay([v], {
    venues: [{ lid: "111", deals: [photoDeal("p1", "2026-08-31T22:00:00Z", 1)] }],
  });
  assert.equal(out.added, 0);
  assert.equal(v.deals.length, 1);
});

test("applying twice is the same as applying once", () => {
  // boot() applies, fetches a missing zone base, then applies again.
  const v = venue([]);
  const overlay = {
    venues: [{ lid: "111", deals: [photoDeal("p1", "2026-08-31T22:00:00Z", 1)] }],
  };
  applyOverlay([v], overlay);
  applyOverlay([v], overlay);
  assert.equal(v.deals.length, 1);
});

test("a newer photo supersedes an older one, as it does at approval time", () => {
  const v = venue([photoDeal("old", "2026-08-01T22:00:00Z", 1)]);
  applyOverlay([v], {
    venues: [{ lid: "111", deals: [photoDeal("new", "2026-08-31T22:00:00Z", 2)] }],
  });
  assert.deepEqual(v.deals.map((d) => d.source.photo_id), ["new"]);
});

test("pages of one menu add up rather than replacing each other", () => {
  // Two submissions 50 minutes apart are two pages of the same menu.
  const v = venue([photoDeal("page1", "2026-08-31T21:58:00Z", 1)]);
  applyOverlay([v], {
    venues: [{ lid: "111", deals: [photoDeal("page2", "2026-08-31T22:48:00Z", 2)] }],
  });
  assert.deepEqual(v.deals.map((d) => d.source.photo_id).sort(), ["page1", "page2"]);
});

test("a page added the next day keeps what is on the board, when told to", () => {
  // The case the clock gets wrong: more items from the same menu, photographed
  // a day later. Without the reviewer's answer this reads as a changed menu.
  const v = venue([photoDeal("page1", "2026-08-30T21:58:00Z", 1)]);
  const page2 = photoDeal("page2", "2026-08-31T22:48:00Z", 2);
  page2.source.merge = "add";
  applyOverlay([v], { venues: [{ lid: "111", deals: [page2] }] });
  assert.deepEqual(v.deals.map((d) => d.source.photo_id).sort(), ["page1", "page2"]);
});

test("without that answer a photo a day later still supersedes", () => {
  const v = venue([photoDeal("page1", "2026-08-30T21:58:00Z", 1)]);
  const later = photoDeal("later", "2026-08-31T22:48:00Z", 2);
  later.source.merge = "replace";
  applyOverlay([v], { venues: [{ lid: "111", deals: [later] }] });
  assert.deepEqual(v.deals.map((d) => d.source.photo_id), ["later"]);
});

test("adding a page cannot resurrect hours the overlay already dropped twice", () => {
  // Applying the same overlay twice is normal -- it happens on every poll.
  const v = venue([photoDeal("page1", "2026-08-30T21:58:00Z", 1)]);
  const page2 = photoDeal("page2", "2026-08-31T22:48:00Z", 2);
  page2.source.merge = "add";
  const overlay = { venues: [{ lid: "111", deals: [page2] }] };
  applyOverlay([v], overlay);
  applyOverlay([v], overlay);
  assert.equal(v.deals.length, 2);
});

test("a deal that did not come from a photo is never eaten", () => {
  const v = venue([siteDeal(3), photoDeal("old", "2026-08-01T22:00:00Z", 1)]);
  applyOverlay([v], {
    venues: [{ lid: "111", deals: [photoDeal("new", "2026-08-31T22:00:00Z", 2)] }],
  });
  assert.deepEqual(v.deals.map((d) => d.source.kind).sort(), ["photo", "venue_site"]);
});

test("a venue this session has not loaded reports its zone instead of vanishing", () => {
  // The auto-approve case: a venue with no hours is in no deals bundle at all.
  const out = applyOverlay([venue([])], {
    venues: [
      { lid: "999", zone_id: "king_of_prussia", deals: [photoDeal("p1", "2026-08-31T22:00:00Z", 1)] },
    ],
  });
  assert.equal(out.added, 0);
  assert.deepEqual(out.missingZones, ["king_of_prussia"]);
});

test("a venue is found by any licence it answers to", () => {
  const v = { id: "v2", name: "Two Licences", lid: "111", also_lids: ["222"], deals: [] };
  const out = applyOverlay([v], {
    venues: [{ lid: "222", deals: [photoDeal("p1", "2026-08-31T22:00:00Z", 1)] }],
  });
  assert.equal(out.added, 1);
});

test("an empty or missing overlay changes nothing", () => {
  const v = venue([siteDeal(1)]);
  assert.equal(applyOverlay([v], null).added, 0);
  assert.equal(applyOverlay([v], { venues: [] }).added, 0);
  assert.equal(v.deals.length, 1);
});
