/* DOM only. Every decision about what to show and in what order lives in
   lib.js, which is pure and tested -- this file just paints the result.

   All of it runs client-side over cached zone bundles, so the app keeps working
   on a bad signal in a parking lot. */

import {
  DOW_SHORT, DOW_LONG, dowOf, fmtClock, fmtMins, fmtMiles, itemParts,
  FILTERS, GROUP, GROUP_LABEL, buildFeed, summarizeWindows, usableMinutes,
  matchesQuery,
  haversineMiles, driveMinutes, ageDays, effectiveConfidence, applyOverlay,
  dealKey, applyConfirmations,
} from "./lib.js";

const state = {
  venues: [],
  zones: [],
  day: 0,        // days ahead: 0 = today
  offset: -1,    // 15-minute slot of the day; -1 means "right now"
  zone: null,
  query: "",     // venue-name search, from the menu panel
  filter: "all",
  sort: "soonest",
  // Set once the reader chooses an order, so knowing where they are can pick a
  // better default without ever overriding what they asked for.
  sortPicked: false,
  origin: null,  // {lat,lng} once, in-session only -- never tracked in the background
  // Zones whose full venue base has been fetched. Boot loads every zone's
  // DEALS (small, and "what's on right now" is an area-wide question); the
  // 2,900-venue base is a megabyte, so it arrives one zone at a time.
  loadedZones: new Set(),
  loadingZone: null,
  // Set when the photo lane is opened from a specific venue's sheet, so the
  // submitter skips the picker. Consumed once, then cleared.
  photoVenue: null,
  // How many no-hours venues the feed is currently showing. Reset on every
  // control change -- a zone with 668 licensed bars must not paint 668 cards.
  shown: 0,
};

const UNKNOWN_PAGE = 24;

const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const SORTS = [
  ["soonest", "Best now"],
  ["nearest", "Nearest"],
  ["value", "Best value"],
];

/* ---- time ------------------------------------------------------------- */

function arrivalTime() {
  const d = new Date();
  if (state.day > 0) d.setDate(d.getDate() + state.day);
  if (state.offset >= 0) {
    d.setHours(0, 0, 0, 0);
    d.setMinutes(state.offset * 15);
  } else if (state.day > 0) {
    d.setHours(16, 0, 0, 0); // a future day with no time set means "the evening"
  }
  return d;
}

const isNow = () => state.day === 0 && state.offset < 0;

/* ---- url state -------------------------------------------------------- */

/* The link IS the session -- happy hour is a group decision and the share
   button has to reproduce exactly what the sender was looking at. */
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (p.has("d")) state.day = Math.min(6, Math.max(0, Number(p.get("d")) || 0));
  if (p.has("t")) state.offset = Math.min(96, Math.max(-1, Number(p.get("t"))));
  if (p.has("z")) state.zone = p.get("z") || null;
  if (p.has("q")) state.query = p.get("q") || "";
  if (p.has("f") && FILTERS[p.get("f")]) state.filter = p.get("f");
  if (p.has("s") && SORTS.some(([k]) => k === p.get("s"))) {
    state.sort = p.get("s");
    state.sortPicked = true;
  }
  return p.get("v");
}

function writeHash(venueId) {
  const p = new URLSearchParams();
  if (state.day) p.set("d", state.day);
  if (state.offset >= 0) p.set("t", state.offset);
  if (state.zone) p.set("z", state.zone);
  if (state.query) p.set("q", state.query);
  if (state.filter !== "all") p.set("f", state.filter);
  if (state.sort !== "soonest") p.set("s", state.sort);
  if (venueId) p.set("v", venueId);
  const hash = p.toString();
  history.replaceState(null, "", hash ? "#" + hash : location.pathname + location.search);
}

/* ---- chips ------------------------------------------------------------ */

function chipRow(box, options, isActive, onPick) {
  box.textContent = "";
  for (const [value, label, title] of options) {
    const b = el("button", "chip", label);
    b.type = "button";
    if (title) b.title = title;
    b.setAttribute("aria-pressed", String(isActive(value)));
    b.addEventListener("click", () => {
      onPick(value);
      [...box.children].forEach((c) => c.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");
      refresh();
    });
    box.append(b);
  }
}

function dayOptions() {
  const out = [[0, "Today"]];
  const d = new Date();
  for (let i = 1; i <= 6; i++) {
    d.setDate(d.getDate() + 1);
    out.push([i, i === 1 ? "Tomorrow" : DOW_SHORT[dowOf(d) - 1]]);
  }
  return out;
}

function picker(sel, options, current, onPick) {
  sel.textContent = "";
  for (const [value, label] of options) {
    const o = el("option", null, label);
    o.value = value ?? "";
    if ((value ?? "") === (current ?? "")) o.selected = true;
    sel.append(o);
  }
  sel.onchange = () => {
    onPick(sel.value || null);
    refresh();
  };
}

function buildControls() {
  chipRow($("#days"), dayOptions(), (v) => state.day === v, (v) => {
    state.day = v;
    if (v > 0 && state.offset < 0) state.offset = 68; // 5pm, a sane default for a future day
    if (v === 0) state.offset = -1;
  });

  chipRow(
    $("#filters"),
    Object.entries(FILTERS).map(([k, f]) => [k, f.label]),
    (v) => state.filter === v,
    (v) => (state.filter = v)
  );

  // "King of Prussia (6 of 59)" -- the second number is the coverage claim and
  // the first is what we can actually stand behind. Showing only one of them is
  // what made the board look either empty or complete, and it is neither.
  picker(
    $("#zone"),
    [
      [null, "All towns"],
      ...state.zones.map((z) => [
        z.id,
        `${z.name} (${z.with_deals ?? z.venues} of ${z.venues})`,
      ]),
    ],
    state.zone,
    (v) => {
      state.zone = v;
      loadZoneVenues(v);
    }
  );

  picker($("#sort"), SORTS, state.sort, (v) => {
    state.sort = v;
    state.sortPicked = true;
  });
}

/* ---- location --------------------------------------------------------- */

/* One shot, in session, on an explicit tap. Never a watch, never on load.
   Distance is the difference between "it's on" and "I can get there", so the
   app asks -- but it works fully without it, and says so. */
function askLocation() {
  const label = $("#nearMeLabel");
  if (!navigator.geolocation) {
    label.textContent = "Location unavailable";
    return;
  }
  label.textContent = "Locating…";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      state.origin = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      rememberOrigin(state.origin);
      if (!state.sortPicked) {
        state.sort = "nearest";
        // The control has to agree with the board: an order that changed under
        // the reader while the picker still reads "Best now" is the app lying
        // about what it just did.
        $("#sort").value = state.sort;
      }
      $("#nearMe").classList.add("on");
      label.textContent = "Located";
      refresh();
    },
    () => {
      label.textContent = "Declined";
      setTimeout(() => (label.textContent = "Near me"), 2500);
    },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 }
  );
}

/* Kept for half a day, not for the tab.

   sessionStorage forgot where you were the moment the tab closed, so the next
   visit re-sorted the whole board by the clock and buried the bar down the road
   under thirty that happen to open earlier. A location half a day old is still
   the right town; older than that and we ask again rather than guess. */
const ORIGIN_TTL_MS = 12 * 3600 * 1000;

function rememberOrigin(origin) {
  try {
    localStorage.setItem("origin", JSON.stringify({ ...origin, at: Date.now() }));
  } catch {
    /* private mode, a full quota -- the app still works, it just re-asks */
  }
}

function restoreLocation() {
  try {
    const saved = JSON.parse(localStorage.getItem("origin") || "null");
    if (!saved || !(Date.now() - saved.at < ORIGIN_TTL_MS)) return;
    state.origin = { lat: saved.lat, lng: saved.lng };
    /* Knowing where they are makes "nearest" the better answer to the question
       the board is for, so it becomes the default -- but never over a sort the
       reader picked, or one carried in on a shared link. */
    if (!state.sortPicked) {
      state.sort = "nearest";
      $("#sort").value = state.sort;
    }
    $("#nearMe").classList.add("on");
    $("#nearMeLabel").textContent = "Located";
  } catch {
    /* a corrupt stored value is not worth a crash */
  }
}

/* ---- the venue base --------------------------------------------------- */

/* Every licensed bar, restaurant and brewery in one zone -- including the four
   in five we have no published window for. Fetched only when that zone is
   picked: the whole base is a megabyte, and downloading it to answer "what's on
   near me right now" would cost every user the price of a question they didn't
   ask. */
async function loadZoneVenues(zoneId) {
  if (!zoneId || state.loadedZones.has(zoneId) || state.loadingZone === zoneId) return;
  state.loadingZone = zoneId;
  refresh();
  try {
    const res = await fetch(`data/venues-${zoneId}.json`);
    if (!res.ok) throw new Error(res.status);
    const bundle = await res.json();
    state.venues = state.venues.concat(bundle.venues);
    state.loadedZones.add(zoneId);
  } catch {
    // Offline, or a zone whose file hasn't shipped yet. The deals already in
    // hand still render -- the board degrades to what it used to be, which is
    // a worse answer but never a broken page.
  } finally {
    state.loadingZone = null;
    refresh();
  }
}

/* ---- rendering -------------------------------------------------------- */

function sectionFor(row, at) {
  if (row.group !== GROUP.UPCOMING) return GROUP_LABEL[row.group];
  if (row.hit.dayAhead === 1) return "Tomorrow";
  const d = new Date(at);
  d.setDate(d.getDate() + row.hit.dayAhead);
  return DOW_LONG[dowOf(d) - 1];
}

/* What is true about this window, in as few words as it takes.

   "Ends in 2h" is only true of a happy hour that is ON. Said of one that starts
   tomorrow it is nonsense, and "in 13h 54m" is a countdown to tomorrow lunchtime
   that nobody was running. A window that has not started STARTS; the clock time
   is the fact, and a countdown is only worth printing while it is short enough
   to be a plan. */
const COUNTDOWN_MINS = 180;

function whenText(row) {
  const { hit } = row;
  if (hit.live) return { text: `Live until ${fmtClock(hit.w.end)}`, live: true };
  if (hit.dayAhead === 0 && hit.startsIn <= COUNTDOWN_MINS) {
    return { text: `Starts in ${fmtMins(hit.startsIn)}` };
  }
  return { text: `Starts ${fmtClock(hit.w.start)}` };
}

function distanceText(venue, miles, driveMin) {
  if (miles == null) return "";
  // A road-level geocode is a street centroid, so don't imply a decimal of
  // accuracy the match cannot support.
  return `${fmtMiles(miles, venue.geo_precision !== "road")} · ~${driveMin} min`;
}

function distanceTo(venue) {
  if (!state.origin || venue.lat == null) return null;
  const miles = haversineMiles(state.origin, venue);
  return { miles, driveMin: driveMinutes(miles) };
}

/* The card for a venue whose hours nobody has published.

   It is deliberately a full card and not a grey stub. This is most of the board
   -- 2,732 of 2,901 venues -- and the product's only path to covering them is a
   person who has been there telling us. That ask has to look like an invitation,
   not like a hole where a card failed to load. */
function unknownCard(row) {
  const { v } = row;
  const node = $("#unknownTpl").content.cloneNode(true);

  const shot = $(".shot", node);
  shot.style.setProperty("--h", hueOf(v.id));
  if (v.photo) {
    const img = $(".photo", node);
    img.src = v.photo.file;
    img.hidden = false;
    img.addEventListener("error", () => {
      img.remove();
      shot.classList.add("fallback");
    });
  } else {
    shot.classList.add("fallback");
    $(".mono", node).textContent = monogramOf(v.name);
  }
  shot.addEventListener("click", () => openVenue(v.id));

  $(".name", node).textContent = v.name;
  const zoneName = state.zones.find((z) => z.id === v.zone_id)?.name ?? "";
  const dist = distanceText(v, row.miles, row.driveMin);
  $(".zone", node).textContent = dist ? `${zoneName} · ${dist}` : zoneName;
  $(".kind", node).textContent = licenseLabel(v.license_type);

  $(".map", node).href = directionsUrl(v);
  const site = $(".site", node);
  if (v.website) site.href = v.website;
  else site.remove();
  $(".know", node).addEventListener("click", () => submitHours(v));
  return node;
}

/* The PLCB licence class, said the way a person would. It is the only thing we
   know about an unlisted venue beyond its name and address, and "Brewery" vs
   "Hotel bar" genuinely changes whether you'd walk in. */
const LICENSE_LABEL = {
  "Restaurant (Liquor)": "Restaurant & bar",
  "Eating Place Retail Dispenser (Malt)": "Beer & food",
  "Hotel (Liquor)": "Hotel bar",
  "Brewery": "Brewery",
  "Brewery Pub": "Brewpub",
  "Limited Winery": "Winery tasting room",
  "Winery": "Winery",
  "Limited Distillery": "Distillery tasting room",
  "Distillery": "Distillery",
  "Airport Restaurant (Liquor)": "Airport restaurant",
  "Public Venue Restaurant": "Venue restaurant",
  "Performing Arts Facility": "Theatre bar",
  "Privately-Owned Public Golf Course Rest (Liquor)": "Golf club restaurant",
  "Municipal Golf Course (Liquor)": "Golf course restaurant",
  "Economic Development Restaurant (Liquor)": "Restaurant & bar",
};

function licenseLabel(type) {
  return LICENSE_LABEL[type] || "Licensed venue";
}

/* Submitting hours. There is no backend yet -- the Worker is a decision that has
   not been made -- so this opens a prefilled mail draft. That is a real delivery
   path today rather than another "not wired yet" dialog, and when a write
   endpoint lands it replaces this one function and nothing else.

   The LID rides in the subject because it is the stable key: a venue's name can
   change and its slug with it, but the licence number is what the board is
   keyed on. */
/* Assembled rather than written out, and never rendered as text anywhere on the
   page: the address is the destination of a mailto, not content. A plain literal
   in a public bundle is a mailbox address harvesters read for free. */
const SUBMIT_TO = ["paul", "umbrellaarcades.com"].join("@");

function submitHours(v) {
  const body = $("#sheetBody");
  body.textContent = "";
  body.append(el("h3", null, v.name));
  body.append(el("p", "sheetSub", v.address));
  body.append(
    el(
      "p",
      null,
      "Nobody has published this one's happy hour anywhere we can read, so it " +
        "isn't on the board yet. If you know it, send it — the days, the times, " +
        "and anything it applies to. Every window on this site says where it came " +
        "from and when it was last checked, and yours will too."
    )
  );

  const lines = [
    `Venue: ${v.name}`,
    `Address: ${v.address}`,
    v.plcb_name && v.plcb_name !== v.name ? `Licensee: ${v.plcb_name}` : null,
    "",
    "Happy hour (days and times):",
    "",
    "Prices, if you know them:",
    "",
    "How do you know? (saw the menu / staff told me / I work here):",
    "",
  ].filter((l) => l !== null);

  const href =
    `mailto:${SUBMIT_TO}` +
    `?subject=${encodeURIComponent(`Happy hour: ${v.name} (LID ${v.lid || v.id})`)}` +
    `&body=${encodeURIComponent(lines.join("\n"))}`;

  const acts = el("div", "actions");
  const send = el("a", "btn go", "Send the hours");
  send.href = href;
  acts.append(send);

  const copy = el("button", "btn", "Copy the details");
  copy.type = "button";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(`${lines.join("\n")}\nLID ${v.lid || v.id}`);
      toast("Copied");
    } catch {
      /* clipboard denied -- the mail button is still there */
    }
  });
  acts.append(copy);
  body.append(acts);

  acts.append(photoButton(v, "Or send a photo of the menu"));

  body.append(
    el("p", "note", `Reference: LID ${v.lid || v.id}. Quote it and we'll know exactly which venue you mean.`)
  );
  openSheet();
}

/* ---- the sheet ---------------------------------------------------------

   Every dialog on this site is the same <dialog>, so opening and closing it
   goes through here.

   The body scroll lock is not cosmetic. A <dialog> in the top layer does not
   stop iOS Safari from scrolling the page underneath it, and once the page
   under a bottom-anchored sheet starts moving, touches land on the page rather
   than on the sheet -- which is why the Close button "could not be pressed".
   Freezing the body at its current offset and restoring it on close keeps the
   taps where the user aimed them. */
let sheetScrollY = 0;

function openSheet() {
  const dlg = $("#sheet");
  if (!dlg.open) {
    sheetScrollY = window.scrollY;
    document.body.style.top = `-${sheetScrollY}px`;
    document.body.classList.add("sheetOpen");
    dlg.showModal();
  }
  dlg.scrollTop = 0;
}

function releaseSheet() {
  if (!document.body.classList.contains("sheetOpen")) return;
  document.body.classList.remove("sheetOpen");
  document.body.style.top = "";
  window.scrollTo(0, sheetScrollY);
}

/* The venue this sheet is about, so a button inside it can hand the photo lane
   a venue that is already known. */
function photoButton(v, label) {
  const b = el("button", "btn", label);
  b.type = "button";
  b.addEventListener("click", () => {
    // Remember which venue, then trigger the same file input the header button
    // uses. Coming from a card is the good case: the venue is already known, so
    // the submitter never has to find their own bar in a list of 2,900.
    state.photoVenue = v;
    $("#photo").click();
  });
  return b;
}

/* ---- photo lane -------------------------------------------------------- */

/* The Worker (worker/index.js). Everything else on this site is static files;
   this is the one endpoint that writes. */
const SUBMIT_API = "https://hhf-submit.paulmichaelrenzi.workers.dev";

/* Re-encode to a bounded JPEG before upload.

   Three things at once, and all three matter: it strips EXIF (a menu photo
   carries the GPS of the bar and we promised never to store that), it converts
   whatever the phone's library handed us into a format the server accepts, and
   it turns a 3 MB capture into ~300 KB so the upload finishes on bar wifi.

   Returns null if the browser cannot decode the file at all -- HEIC on a
   desktop browser, mostly. The caller sends the original and lets the server
   say no, which is a clearer error than one invented here. */
async function shrink(file, maxEdge = 1600, quality = 0.82) {
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return null;
  }
  const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close?.();
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
}

/* The venue this menu is for. A photo with no venue is unfilable, so this is
   the one required field -- but it is a search, not a dropdown: the board is
   2,900 licensed premises and no one scrolls that. */
/* Every licensed venue we hold, by name -- fetched the first time somebody
   opens the picker, and never at boot. 265 KB is nothing to a person filling in
   a menu and everything to a reader who just wants to know what is on tonight.

   One in-flight fetch, shared: two keystrokes must not become two downloads. */
let nameIndexPromise = null;

function loadNameIndex() {
  if (!nameIndexPromise) {
    nameIndexPromise = fetch("data/name-index.json")
      .then((r) => {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .catch(() => {
        // Offline, or the file has not shipped. Fall back to what is in memory
        // rather than breaking the one field a submission cannot do without.
        nameIndexPromise = null;
        return null;
      });
  }
  return nameIndexPromise;
}

function venuePicker(onPick) {
  const wrap = el("div", "picker");
  const input = el("input", "pickerInput");
  input.type = "search";
  input.placeholder = "Which bar? Start typing the name";
  input.setAttribute("aria-label", "Search for the venue this menu is from");
  const list = el("div", "pickerList");
  const chosen = el("p", "pickerChosen");

  let index = null;
  let indexReady = false;
  // Start the fetch as soon as the picker exists, not on the first keystroke --
  // by the time anyone has typed two characters it is usually already here.
  loadNameIndex().then((data) => {
    index = data;
    indexReady = true;
    if (input.value.trim().length >= 2) render();
  });

  /* Rank a match by WHERE the query lands, not merely whether it does. Typing
     "taku" must put Taku Japanese Steakhouse above Gyu-Kaku, and a bar whose
     name starts with what you typed is nearly always the one you meant. */
  function score(name, q) {
    const n = name.toLowerCase();
    const at = n.indexOf(q);
    if (at < 0) return -1;
    if (at === 0) return 0;
    return /[\s&'-]/.test(n[at - 1]) ? 1 : 2;
  }

  function render() {
    const q = input.value.trim().toLowerCase();
    list.textContent = "";
    chosen.textContent = "";
    if (q.length < 2) return;

    // In-memory venues first -- they carry hours, photos and coordinates the
    // index rows do not -- then everything else we are licensed to know about.
    // Keyed by LID so a venue already on the board is never offered twice.
    const seen = new Set();
    const hits = [];
    for (const v of state.venues) {
      const s = score(v.name, q);
      if (s < 0) continue;
      const lid = String(v.lid || v.id || "");
      if (lid && seen.has(lid)) continue;
      if (lid) seen.add(lid);
      hits.push({ s, venue: v, zone: v.zone_id, onBoard: !!(v.deals && v.deals.length) });
    }
    if (index) {
      for (const [lid, name, address, zone] of index.venues) {
        if (seen.has(lid)) continue;
        const s = score(name, q);
        if (s < 0) continue;
        seen.add(lid);
        hits.push({ s, venue: { lid, id: lid, name, address, zone_id: zone }, zone });
      }
    }

    if (!hits.length) {
      if (!indexReady) {
        list.append(el("p", "pickerMiss", "Still loading the venue list — one moment."));
        return;
      }
      // The index is here and holds every licensed premises in the area, so
      // this really is "we do not have it" -- not "we have not fetched it".
      // Saying so plainly is the honest answer; it was not available before.
      list.append(
        el("p", "pickerMiss",
          "No licensed venue by that name in the area we cover. Check the " +
            "spelling, or try a shorter piece of the name — some bars are " +
            "licensed under a different trading name.")
      );
      return;
    }

    hits.sort((a, b) => a.s - b.s || a.venue.name.localeCompare(b.venue.name));
    for (const hit of hits.slice(0, 8)) {
      const v = hit.venue;
      const b = el("button", "pickerHit");
      b.type = "button";
      b.append(el("b", null, v.name));
      // Two bars sharing a name is common and the address is what separates
      // them -- Taku in King of Prussia against Takumi in Devon, three Dave &
      // Buster's in three towns. Never resolve that for the submitter: a wrong
      // LID hangs a menu on the wrong bar and the card shows nothing amiss.
      const where = [v.address || "", zoneLabel(index, hit.zone)]
        .filter(Boolean).join(" · ");
      b.append(el("span", null, where));
      if (hit.onBoard) b.append(el("span", "pickerOn", "already has hours"));
      b.addEventListener("click", () => {
        onPick(v);
        chosen.textContent = `Menu for ${v.name}`;
        list.textContent = "";
        input.value = "";
      });
      list.append(b);
    }
  }

  input.addEventListener("input", render);
  wrap.append(input, list, chosen);
  return wrap;
}

function zoneLabel(index, zoneId) {
  if (!zoneId) return "";
  const names = (index && index.zone_names) || {};
  return names[zoneId] || zoneId.replace(/_/g, " ");
}

function photoLane(file) {
  const body = $("#sheetBody");
  body.textContent = "";
  body.append(el("h3", null, "Send a menu photo"));

  let venue = state.photoVenue || null;
  state.photoVenue = null;

  body.append(
    el("p", "sheetSub", venue
      ? `Menu for ${venue.name}.`
      : "Around four in five bars never publish their happy hour anywhere we can " +
        "read, so a photo of the menu on the wall is how most of this board gets " +
        "filled in.")
  );

  const kb = Math.round(file.size / 1024);
  body.append(el("p", "pick", `${file.name} — ${file.type || "unknown type"}, ${kb} KB`));

  const url = URL.createObjectURL(file);
  const img = el("img", "pick-preview");
  img.alt = "The menu photo you just picked";
  img.src = url;
  img.addEventListener("error", () => {
    img.replaceWith(
      el("p", "pick-warn",
        "The browser can't preview this format. You can still send it, but if it " +
          "comes back rejected, retake the photo with your camera app.")
    );
    URL.revokeObjectURL(url);
  });
  img.addEventListener("load", () => URL.revokeObjectURL(url));
  body.append(img);

  if (!venue) body.append(venuePicker((v) => { venue = v; }));

  const note = el("textarea", "noteBox");
  note.placeholder = "Anything worth knowing? (bar only, weekdays, seasonal…)";
  note.maxLength = 500;
  note.setAttribute("aria-label", "Optional note about this menu");
  body.append(note);

  const status = el("p", "sendStatus");
  const acts = el("div", "actions");
  const send = el("button", "btn go", "Send it");
  send.type = "button";
  acts.append(send);
  body.append(acts, status);

  body.append(
    el("p", "note",
      "A person reads every photo before anything goes on the board, so this " +
        "won't appear straight away. We strip the location data out of the image " +
        "before it's stored, and the photo itself is never published — only the " +
        "hours printed on it, with a note saying they came from a menu photo.")
  );

  send.addEventListener("click", async () => {
    if (!venue) {
      status.textContent = "Pick which bar this menu is from first.";
      return;
    }
    send.disabled = true;
    status.textContent = "Sending…";

    const shrunk = await shrink(file);
    const form = new FormData();
    form.append("photo", shrunk || file, shrunk ? "menu.jpg" : file.name);
    form.append("lid", venue.lid || venue.id);
    form.append("venue_name", venue.name);
    form.append("note", note.value.trim());

    try {
      const res = await fetch(`${SUBMIT_API}/submit`, { method: "POST", body: form });
      const out = await res.json().catch(() => ({}));
      if (!res.ok) {
        status.textContent = out.error || "That didn't go through. Try again in a minute.";
        send.disabled = false;
        return;
      }
      body.textContent = "";
      body.append(el("h3", null, "Got it — thank you"));
      body.append(
        el("p", null,
          `That's in the queue for ${venue.name}. Someone reads it, checks the ` +
            "hours against Pennsylvania's happy hour rules, and puts it on the " +
            "board — usually within a day or two. It'll say it came from a photo, " +
            "and it'll show the date, same as every other window on this site.")
      );
    } catch {
      // Offline in a basement bar is the normal case -- but it is not the only
      // way this throws, and blaming the signal when the endpoint itself is
      // down sends the submitter to go stand by a window for nothing. The
      // browser knows which one it is, so say which one it is.
      status.textContent = navigator.onLine
        ? "We can't reach the server right now — that's on us, not your signal. " +
          "The photo is still in your camera roll; please try again later."
        : "You're offline — the photo is still in your camera roll; try again " +
          "when you have a bar or two.";
      send.disabled = false;
    }
  });

  openSheet();
}

/* Fine print, folded.

   A card's job is to say what the deal is and when. One venue's menu carries
   592 characters of promotional small print -- legally part of the offer, so we
   do not drop it -- and printed in full it buried every card under it. Long
   text gets a "Details" toggle; short text (which is nearly all of it) is
   printed as it always was, because a toggle over one line is worse than the
   line. */
const FINE_FOLD_CHARS = 150;

/* A menu is not a list -- it is a wall.

   Taku's menu read cleanly and produced SIXTEEN priced items, which is the
   product working, and on a phone it was a card you had to scroll past to
   reach the next bar. So the card shows the first few and folds the rest
   behind a count. The fold is a <details> with two words in it for the same
   reason the small print's is: a decorative glyph has to survive every editor
   between here and the page, and one of them ate it.

   Nothing is dropped -- "+13 more" is itself the honest signal that this venue
   published a real menu, and every item is one tap away. */
const ITEMS_SHOWN = 3;

function itemChip(item) {
  const { amount, label } = itemParts(item);
  const li = el("li");
  if (amount) li.append(el("b", null, amount));
  li.append(document.createTextNode(label));
  return li;
}

/* ONE fold per card.

   A card that hid its extra prices behind "+13 more" and its small print behind
   "Show the small print" made the reader tap twice to finish reading one bar,
   and put two competing buttons in a feed meant to be thumbed past. There is
   one thing folded here -- the rest of this card -- so there is one button.

   Nothing is dropped, and the count stays in the label: "+13 more" is itself
   the honest signal that this venue published a real menu. */
function fillItems(list, items, fineNode, fine) {
  for (const item of items.slice(0, ITEMS_SHOWN)) list.append(itemChip(item));
  const rest = items.slice(ITEMS_SHOWN);
  const foldFine = fine.length > FINE_FOLD_CHARS;
  // Short small print (nearly all of it) still prints in the open, because a
  // toggle over one line is worse than the line.
  if (!foldFine) fineNode.textContent = fine;
  if (!rest.length && !foldFine) return;

  const details = el("details", "moreFold");
  const summary = el("summary");
  // Two labels rather than a caret: a decorative glyph has to survive every
  // editor and encoding between here and the page, and one of them ate it.
  summary.append(
    el("span", "foldShow", rest.length ? `+${rest.length} more` : "Show more"),
    el("span", "foldHide", "Show less")
  );
  const body = el("div", "foldBody");
  if (rest.length) {
    const more = el("ul", "items itemsMore");
    for (const item of rest) more.append(itemChip(item));
    body.append(more);
  }
  if (foldFine) body.append(el("p", "foldText", fine));
  details.append(summary, body);
  // Outside the <ul>: a <details> is not a valid child of a list, and Safari
  // is the engine that punishes that rather than the one that forgives it.
  list.after(details);
}

function card(row, at) {
  const { v, deal, hit } = row;
  const node = $("#cardTpl").content.cloneNode(true);
  const article = $(".card", node);
  if (!hit.live) article.classList.add("soon");
  if (row.group === GROUP.UNREACHABLE) article.classList.add("unreachable");

  const shot = $(".shot", node);
  shot.style.setProperty("--h", hueOf(v.id));
  if (v.photo) {
    const img = $(".photo", node);
    img.src = v.photo.file;
    img.hidden = false;
    // A photo that 404s must not leave a blank band -- fall back to the tile.
    img.addEventListener("error", () => {
      img.remove();
      shot.classList.add("fallback");
    });
  } else {
    shot.classList.add("fallback");
    $(".mono", node).textContent = monogramOf(v.name);
  }
  shot.addEventListener("click", () => openVenue(v.id));

  $(".name", node).textContent = v.name;
  const zoneName = state.zones.find((z) => z.id === v.zone_id)?.name ?? "";
  const dist = distanceText(v, row.miles, row.driveMin);
  $(".zone", node).textContent = dist ? `${zoneName} · ${dist}` : zoneName;

  const when = whenText(row);
  const ends = $(".ends", node);
  ends.textContent = when.text;
  if (when.live) ends.classList.add("live");

  let fine = deal.fine_print || (deal.items.length ? "" : "Window published without prices.");
  if (row.group === GROUP.UNREACHABLE) {
    fine =
      `It ends in ${fmtMins(hit.until)} and you're about ${row.driveMin} minutes away. ` + fine;
  } else if (hit.live && row.driveMin != null) {
    const usable = usableMinutes(hit, row.driveMin);
    if (usable < 30) fine = `About ${fmtMins(usable)} of it left by the time you arrive. ` + fine;
  }
  // How old a reading is belongs on the venue sheet with the rest of the
  // provenance, not on the face of the card. "Not checked since 26d ago" is
  // true, and printed under every second bar it reads as an apology for the
  // board rather than a fact about one deal -- it spent our credibility to say
  // nothing the reader could act on. The decay ladder still demotes and then
  // hides a deal that gets too old; that is the part of freshness doing work.
  fillItems($(".items", node), deal.items, $(".fine", node), fine.trim());

  $(".map", node).href = directionsUrl(v);
  const src = $(".src", node);
  if (deal.source?.url) src.href = deal.source.url;
  // A photo has no URL to link. Where the hours came from -- and who took the
  // venue photo -- is real and stays on the record, but it belongs on the venue
  // sheet with the rest of the provenance, not as a line of grey text between a
  // person and the Directions button.
  else src.remove();
  $(".wrong", node).addEventListener("click", () => reportWrong(v, deal));
  return node;
}

function render() {
  const at = arrivalTime();
  const rows = buildFeed(state.venues, at, {
    zone: state.zone,
    query: state.query,
    filter: state.filter,
    sort: state.sort,
    origin: state.origin,
  });

  const clock = at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  $("#clock").textContent = isNow() ? clock : `${DOW_SHORT[dowOf(at) - 1]} ${clock}`;
  $("#whenLabel").textContent = isNow()
    ? "Right now"
    : `Arriving ${state.day ? DOW_LONG[dowOf(at) - 1] + " " : ""}${clock}`;
  $("#when").value = state.offset;

  const live = rows.filter((r) => r.group === GROUP.LIVE).length;
  const soon = rows.filter((r) => r.group === GROUP.SOON).length;
  const withDeals = rows.filter((r) => r.group !== GROUP.UNKNOWN).length;
  $("#heroCount").innerHTML = live
    ? `<b>${live}</b> happy hour${live === 1 ? "" : "s"} live ${isNow() ? "now" : "then"}`
    : soon
      ? `Nothing live yet — <b>${soon}</b> starting soon`
      : withDeals
        ? `Nothing on ${isNow() ? "right now" : "then"} — here's what's next`
        : rows.length
          ? "No published hours here yet — every venue below is one you could fill in"
          : "Nothing matches that filter";

  const feed = $("#feed");
  feed.textContent = "";

  if (!rows.length) {
    const p = el("p", "empty");
    p.append(el("b", null, "Nothing matches that."));
    p.append(
      document.createTextNode(
        state.query
          ? `No venue loaded is called “${state.query}”. Venues with no published ` +
            "hours only load once you pick their town, so try clearing the search " +
            "and picking the town instead."
          : state.filter === "all"
          ? state.loadingZone
            ? "Loading this town's venues…"
            : "Try another town. Around four in five bars never publish a happy hour " +
              "anywhere, so most of the board is venues waiting for someone to fill them in."
          : `No ${FILTERS[state.filter].label.toLowerCase()} in this town. Try “Everything” ` +
            "to see every licensed venue here, published hours or not."
      )
    );
    feed.append(p);
    $("#status").textContent = "No results.";
    $("#sectionKicker").textContent = "Nothing to show";
    return;
  }

  // Split before painting: the no-hours rows are the bulk of the board and are
  // revealed a page at a time, so they cannot go through the same loop.
  const dealRows = rows.filter((r) => r.group !== GROUP.UNKNOWN);
  const unknownRows = rows.filter((r) => r.group === GROUP.UNKNOWN);

  let section = null;
  for (const row of dealRows) {
    const want = sectionFor(row, at);
    if (want !== section) feed.append(el("p", "sec", (section = want)));
    feed.append(card(row, at));
  }

  if (unknownRows.length) {
    const n = Math.min(state.shown || UNKNOWN_PAGE, unknownRows.length);
    const head = el("p", "sec sec-unknown");
    head.append(document.createTextNode(GROUP_LABEL[GROUP.UNKNOWN]));
    head.append(el("span", "secCount", `${unknownRows.length} venue${unknownRows.length === 1 ? "" : "s"}`));
    feed.append(head);
    feed.append(
      el(
        "p",
        "secNote",
        "Licensed bars, restaurants and breweries we have no published happy hour " +
          "for. Most never post one anywhere — if you know one, the card says how " +
          "to tell us."
      )
    );
    for (const row of unknownRows.slice(0, n)) feed.append(unknownCard(row));
    if (n < unknownRows.length) {
      const more = el("button", "moreBtn", `Show ${Math.min(UNKNOWN_PAGE, unknownRows.length - n)} more of ${unknownRows.length - n}`);
      more.type = "button";
      more.addEventListener("click", () => {
        state.shown = n + UNKNOWN_PAGE;
        render(); // not refresh(): the hash describes the query, not how far you scrolled
      });
      feed.append(more);
    }
  } else if (state.zone && !state.loadedZones.has(state.zone) && state.filter === "all") {
    feed.append(
      el("p", "secNote", state.loadingZone === state.zone
        ? "Loading every licensed venue in this town…"
        : "Couldn't load the full venue list for this town — showing published happy hours only.")
    );
  } else if (!state.zone && state.filter === "all" && !state.query) {
    feed.append(
      el(
        "p",
        "secNote",
        "Pick a town above to see every licensed bar, restaurant and brewery in it — " +
          "including the ones whose happy hour nobody has published."
      )
    );
  }

  $("#status").textContent =
    `${dealRows.length} result${dealRows.length === 1 ? "" : "s"}, ${live} live` +
    (unknownRows.length ? `, ${unknownRows.length} with no published hours.` : ".");
  const total = dealRows.length + unknownRows.length;
  $("#sectionKicker").textContent =
    `${total} venue${total === 1 ? "" : "s"} · ` +
    (live ? `${live} live ${isNow() ? "now" : "then"}` : "none live") +
    (unknownRows.length ? ` · ${unknownRows.length} need hours` : "");
}

function refresh() {
  // Any change to the query is a new list, so the "show more" reveal starts over.
  // Keeping it would leave you 200 cards deep in a zone you just switched away from.
  state.shown = UNKNOWN_PAGE;
  writeHash();
  render();
}

/* ---- venue sheet ------------------------------------------------------ */

const DEAL_TYPE = {
  happy_hour: "Happy hour",
  daily_special: "Daily special",
  food_combo: "Food & drink combo",
};

function openVenue(id) {
  // The board is keyed on the PLCB licence number now. Every link shared before
  // that was keyed on a name-derived slug, so those still resolve -- a slug is
  // carried on any venue that ever had one.
  const v = state.venues.find((x) => x.id === id) || state.venues.find((x) => x.slug === id);
  if (!v) return;
  if (!v.deals.length) return submitHours(v);
  const body = $("#sheetBody");
  body.textContent = "";

  body.append(el("h3", null, v.name));
  const sub = el("p", "sheetSub", v.address);
  body.append(sub);

  const away = distanceTo(v);
  if (away) {
    sub.append(el("span", "pill", `${distanceText(v, away.miles, away.driveMin)} away`));
    if (v.geo_precision === "road") {
      body.append(
        el("p", "note", "This address matched to the street rather than the building, so the distance is good to a block.")
      );
    }
  }

  for (const deal of v.deals) {
    const box = el("div", "dealBlock");
    box.append(el("h4", null, DEAL_TYPE[deal.type] || deal.type));
    box.append(el("p", "sched", summarizeWindows(deal.windows)));

    if (deal.items.length) {
      const ul = el("ul", "items");
      for (const item of deal.items) {
        const { amount, label } = itemParts(item);
        const li = el("li");
        if (amount) li.append(el("b", null, amount));
        li.append(document.createTextNode(label));
        ul.append(li);
      }
      box.append(ul);
    }
    if (deal.fine_print) box.append(el("p", "note", deal.fine_print));

    const days = ageDays(deal);
    const age = days === 0 ? "today" : `${days} day${days === 1 ? "" : "s"} ago`;
    const prov = el("p", "note");
    prov.append(
      document.createTextNode(
        effectiveConfidence(deal) === "unconfirmed"
          ? `Last checked ${age} — old enough to be worth a call. Source: `
          : `Last checked ${age}. Source: `
      )
    );
    if (deal.source?.url) {
      const a = el("a", null, deal.source.kind.replace("_", " "));
      a.href = deal.source.url;
      a.target = "_blank";
      a.rel = "noopener";
      prov.append(a);
    } else {
      prov.append(document.createTextNode(deal.source?.kind || "unknown"));
    }
    if (deal.source?.note) prov.append(document.createTextNode(` — ${deal.source.note}`));
    box.append(prov);
    body.append(box);
  }

  // The photo credit lives here now, once per venue, instead of on every card
  // it appears on. It is a licence condition, not decoration, so it does not
  // get dropped -- it gets put where someone reading about this venue will
  // find it and someone scanning the board will not trip over it.
  if (v.photo?.attribution) body.append(el("p", "note", `Photo: ${v.photo.attribution}`));

  const acts = el("div", "actions");
  const dir = el("a", "btn go", "Directions");
  dir.href = directionsUrl(v);
  dir.target = "_blank";
  dir.rel = "noopener";
  acts.append(dir);

  if (v.website) {
    const site = el("a", "btn", "Website");
    site.href = v.website;
    site.target = "_blank";
    site.rel = "noopener";
    acts.append(site);
  }

  const share = el("button", "btn", "Share");
  share.type = "button";
  share.addEventListener("click", () => shareVenue(v));
  acts.append(share);
  body.append(acts);

  // The photo lane used to live only in submitHours(), which runs for venues
  // with NO hours -- so the one case that actually happens, somebody standing
  // in a bar looking at hours we publish and a menu that disagrees, had no way
  // in. A newer photo supersedes what is here (ingest/review_photos.py), so
  // this is the update path, not a second opinion.
  const upd = el("div", "actions");
  upd.append(photoButton(v, "These hours changed — send a photo of the menu"));
  body.append(upd);
  body.append(
    el("p", "note",
      "A photo of the current menu replaces what's above once a person has read " +
        "it. Several pages? Send them one after another and they'll be read as " +
        "one menu.")
  );

  writeHash(v.id);
  openSheet();
}

async function shareVenue(v) {
  const url = location.href;
  const data = { title: v.name, text: `${v.name} — happy hour`, url };
  try {
    if (navigator.share) return await navigator.share(data);
    await navigator.clipboard.writeText(url);
    toast("Link copied");
  } catch {
    /* the user dismissed the share sheet -- not an error */
  }
}

function reportWrong(v, deal) {
  const body = $("#sheetBody");
  body.textContent = "";
  body.append(el("h3", null, v.name));
  body.append(el("p", "sheetSub", summarizeWindows(deal.windows)));
  body.append(
    el(
      "p",
      null,
      "Wrong window, new prices, a menu that changed last week — it is all the " +
        "same fix, and the fastest one by a distance is a photo of the menu: it " +
        "goes into the same queue a person reads every day, and an approved " +
        "photo replaces what's on the card above."
    )
  );

  const acts = el("div", "actions");
  acts.append(photoButton(v, "Send a photo of the menu"));

  // Not everyone reporting a wrong window is standing in front of the menu.
  // A mail draft is a real delivery path for those, and it carries the LID so
  // the report is filable against a licence number rather than a name.
  const lines = [
    `Venue: ${v.name}`,
    `Address: ${v.address}`,
    `LID: ${v.lid || v.id}`,
    `What we show: ${summarizeWindows(deal.windows)}`,
    "",
    "What's wrong, or what changed:",
    "",
    "How do you know? (saw the menu / staff told me / I work here):",
    "",
  ];
  const mail = el("a", "btn", "No photo — tell us instead");
  mail.href =
    `mailto:${SUBMIT_TO}` +
    `?subject=${encodeURIComponent(`Hours changed: ${v.name} (LID ${v.lid || v.id})`)}` +
    `&body=${encodeURIComponent(lines.join("\n"))}`;
  acts.append(mail);
  body.append(acts);

  const p = el("p", "note");
  p.append(document.createTextNode("What we have now came from: "));
  if (deal.source?.url) {
    const a = el("a", null, deal.source.kind.replace("_", " "));
    a.href = deal.source.url;
    a.target = "_blank";
    a.rel = "noopener";
    p.append(a);
  } else {
    p.append(document.createTextNode(deal.source?.kind || "unknown"));
  }
  if (deal.source?.note) p.append(document.createTextNode(` — ${deal.source.note}`));
  body.append(p);
  openSheet();
}

function toast(text) {
  const t = el("div", "toast", text);
  document.body.append(t);
  setTimeout(() => t.remove(), 1800);
}

function directionsUrl(v) {
  // Prefer the coordinate when we have one: two "Iron Hill Brewery" rows are
  // different bars, and a name search can route you to the wrong town.
  const dest = v.lat != null ? `${v.lat},${v.lng}` : `${v.name}, ${v.address}`;
  return "https://www.google.com/maps/dir/?api=1&destination=" + encodeURIComponent(dest);
}

/* A venue with no photo still gets a designed tile, not a grey hole. The hue is
   derived from the id so a given bar always looks like itself. */
function hueOf(id) {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return (h % 32) + 6; // rust..amber only -- a missing photo still reads warm, never sickly
}

function monogramOf(name) {
  return (name.replace(/^(The|A)\s+/i, "").match(/[A-Za-z]/) || ["·"])[0].toUpperCase();
}

/* ---- search ----------------------------------------------------------- */

/* Opening the panel is the whole navigation: there is one thing behind the
   button, so the button focuses the field rather than presenting a list of one.
   Closing it clears nothing -- a search you scrolled away from is still the
   list you are reading, and the hash carries it, so a shared link searches. */
function toggleMenu(open) {
  const btn = $("#menuBtn"), panel = $("#menuPanel");
  const want = open ?? panel.hidden;
  panel.hidden = !want;
  btn.setAttribute("aria-expanded", String(want));
  if (want) {
    const box = $("#search");
    box.value = state.query;
    box.focus();
    box.select();
  }
}

/* What the search actually looked at. The board holds every town's deal-bearing
   venues from boot, but the 2,900-venue base arrives one town at a time -- so a
   bar with no published hours in a town nobody has opened is genuinely not in
   memory to be found, and saying so is the honest answer rather than "no
   results". */
function searchNote() {
  const note = $("#searchNote");
  if (!note) return;
  if (!state.query) {
    note.textContent = "Searches every venue currently loaded — 169 with published hours, plus every licensed venue in any town you've opened.";
    return;
  }
  const n = state.venues.filter((v) => matchesQuery(v, state.query)).length;
  note.textContent = n
    ? `${n} venue${n === 1 ? "" : "s"} match “${state.query}”.`
    : `Nothing loaded matches “${state.query}”. Venues with no published hours only load once you pick their town.`;
}

/* The hero owns the title until it scrolls away, then the glass bar takes over. */
function watchHero() {
  const hero = $("#hero"), bar = $("#bar");
  if (!("IntersectionObserver" in window)) return bar.classList.add("show");
  new IntersectionObserver(([e]) => bar.classList.toggle("show", !e.isIntersecting), {
    rootMargin: "-56px 0px 0px 0px",
  }).observe(hero);
}

/* ---- boot ------------------------------------------------------------- */

// GitHub Pages sits behind Fastly, which refuses a burst: firing all 38 zone
// bundles at once had every one of them dropped on a clean connection, and the
// same URLs fetched singly a second later were fine. Six at a time is well under
// that, and on a phone it is six sockets competing for one radio instead of 38.
const FETCH_POOL = 6;

async function fetchJSON(url, tries = 3) {
  let last;
  for (let i = 0; i < tries; i++) {
    // Back off before a RETRY only; the first attempt goes immediately.
    if (i) await new Promise((r) => setTimeout(r, 250 * 2 ** (i - 1)));
    try {
      // no-cache revalidates rather than trusting the 10-minute HTTP freshness
      // window -- a stale bundle is wrong in a way the page cannot show.
      const res = await fetch(url, { cache: "no-cache" });
      if (!res.ok) throw new Error(`${res.status} ${url}`);
      return await res.json();
    } catch (e) {
      last = e;
    }
  }
  throw last;
}

async function pooled(items, limit, fn) {
  const out = new Array(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i], i);
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return out;
}

// Never all-or-nothing. Promise.all rejected the entire board when a single
// bundle dropped, and boot() then died BEFORE it had drawn even the controls --
// a fully styled page stuck on "Loading..." with empty filters, forever. A zone
// that will not load now costs that zone and nothing else.
async function loadZoneDeals(zones) {
  const failed = [];
  const got = await pooled(zones, FETCH_POOL, async (z) => {
    try {
      return await fetchJSON(`data/zone-${z.id}.json`);
    } catch {
      failed.push(z);
      return null;
    }
  });
  state.venues = state.venues.concat(got.filter(Boolean).flatMap((b) => b.venues));
  return failed;
}

/* Approved photo deals that are not in the built bundles yet.

   Everything on this page is normally static files, and that is the point --
   it works in a parking lot with no signal. This is the one live read, and it
   is additive: it patches deals over what the bundles already gave us. A
   failed fetch changes nothing on screen, so the offline story is unharmed.

   A venue that auto-published had NO hours, so it is in no deals bundle at
   all. applyOverlay hands back the zones those venues live in; we fetch each
   zone's base once and apply again, which is idempotent because every overlay
   deal carries the photo_id that says it has already been applied. */
async function loadOverlay() {
  let overlay;
  try {
    overlay = await fetchJSON(`${SUBMIT_API}/live/deals.json`, 1);
  } catch {
    return; // the board is already drawn from the bundles; this adds or it does not
  }
  let res = applyOverlay(state.venues, overlay);
  for (const zid of res.missingZones) await loadZoneVenues(zid);
  if (res.missingZones.length) res = applyOverlay(state.venues, overlay);
  const confirms = applyConfirmations(state.venues, overlay.confirms);
  if (res.added || confirms) refresh();
}

// A page that cannot say what went wrong is indistinguishable from a broken one.
function boardNote(text, retry) {
  let n = $("#boardNote");
  if (!n) {
    n = el("div", "boardNote");
    n.id = "boardNote";
    $("#feed").before(n);
  }
  n.textContent = "";
  n.append(el("p", null, text));
  if (retry) {
    const b = el("button", "btn", "Retry");
    b.type = "button";
    b.addEventListener("click", () => {
      n.remove();
      retry();
    });
    n.append(b);
  }
}

function noteMissingZones(failed) {
  const names = failed.map((z) => z.name).join(", ");
  boardNote(
    `${failed.length} of ${state.zones.length} areas didn't load, so some happy ` +
      `hours are missing: ${names}.`,
    async () => {
      const still = await loadZoneDeals(failed);
      if (still.length) noteMissingZones(still);
      refresh();
    }
  );
}

async function boot() {
  const index = await fetchJSON("data/index.json");
  state.zones = index.zones;

  // Paint the controls off the index, before a single bundle is asked for. They
  // need nothing else, and a page that shows its filters immediately reads as
  // loading rather than as broken while the network is slow.
  const openId = readHash();
  buildControls();
  restoreLocation();
  watchHero();

  state.venues = [];
  const failed = await loadZoneDeals(index.zones);
  render();
  if (failed.length) noteMissingZones(failed);
  loadOverlay();
  // A shared link to a venue with no published hours names a venue that only
  // arrives with its zone's base, so the fetch has to finish before the sheet is
  // opened -- otherwise the link silently does nothing, which is exactly the
  // failure a share is supposed to prevent.
  if (state.zone) await loadZoneVenues(state.zone);
  if (openId) openVenue(openId);

  // Keep "ends in" honest while the page sits open, but only in live mode.
  setInterval(() => isNow() && render(), 30000);
  /* A timer is not enough. A backgrounded tab is throttled, a laptop that
     sleeps stops it dead, and a tab Chrome discarded and restored comes back
     painted with whatever the board said hours ago -- a 3-6pm window still
     reading "Live now" at half past seven. Whenever the page becomes visible
     again, it is a page of unknown age: re-render before the reader believes
     any of it. */
  const restamp = () => isNow() && render();
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) restamp();
  });
  window.addEventListener("pageshow", restamp);
  window.addEventListener("focus", restamp);
  // And pick up anything approved since this page loaded. The endpoint is
  // cached for 30s, so this is cheap and a new approval lands within a minute
  // on a page nobody has touched.
  setInterval(loadOverlay, 60000);

  $("#credits").innerHTML =
    'Header photo: <a href="https://commons.wikimedia.org/wiki/File:South_Shore_Brewery_Taproom.jpg">' +
    "South Shore Brewery Taproom</a> by Billertl, cropped, " +
    '<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>. ' +
    'Venue locations and websites from <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, ' +
    "© OpenStreetMap contributors, ODbL. Drive times are estimates. " +
    "Deal windows are transcribed from the source linked on each card — always call ahead.";

  $("#when").addEventListener("input", (e) => {
    const v = Number(e.target.value);
    // The slider means "when I arrive", so on today it cannot point backwards.
    const nowSlot = Math.floor((new Date().getHours() * 60 + new Date().getMinutes()) / 15);
    state.offset = state.day === 0 && v >= 0 && v <= nowSlot ? -1 : v;
    refresh();
  });
  $("#nowBtn").addEventListener("click", () => {
    state.day = 0;
    state.offset = -1;
    buildControls();
    refresh();
    scrollTo({ top: 0, behavior: "smooth" });
  });
  $("#nearMe").addEventListener("click", askLocation);
  $("#menuBtn").addEventListener("click", () => toggleMenu());
  $("#search").addEventListener("input", (e) => {
    state.query = e.target.value;
    refresh();
    searchNote();
  });
  // Enter on a phone means "I am done typing", not "submit": the list is
  // already filtered, so it just gets the keyboard out of the way.
  $("#search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); e.target.blur(); }
    if (e.key === "Escape") { state.query = ""; e.target.value = ""; refresh(); searchNote(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#menuPanel").hidden && document.activeElement !== $("#search")) {
      toggleMenu(false);
      $("#menuBtn").focus();
    }
  });
  // A search restored from a shared link has to be visible, or the board looks
  // arbitrarily short with nothing on screen explaining why.
  if (state.query) { toggleMenu(true); $("#search").blur(); }
  searchNote();
  $("#photo").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    // Let the same file be picked twice in a row, and clear it before the sheet
    // opens so a cancelled pick doesn't leave the input holding the last one.
    e.target.value = "";
    if (file) photoLane(file);
  });
  $("#sheetClose").addEventListener("click", () => $("#sheet").close());
  $("#sheet").addEventListener("close", () => {
    releaseSheet();
    writeHash();
  });

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
}

boot().catch((err) => {
  // The only throw left is the zone index itself: without it there is no board
  // to draw and no list of zones to report as missing.
  console.error(err);
  $("#heroCount").textContent = "Couldn't reach the board.";
  $("#sectionKicker").textContent = "Not loaded";
  boardNote(
    "The board didn't load. That is nearly always a dropped connection rather " +
      "than anything wrong with the happy hours themselves.",
    () => location.reload()
  );
});
