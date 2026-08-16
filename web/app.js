/* DOM only. Every decision about what to show and in what order lives in
   lib.js, which is pure and tested -- this file just paints the result.

   All of it runs client-side over cached zone bundles, so the app keeps working
   on a bad signal in a parking lot. */

import {
  DOW_SHORT, DOW_LONG, dowOf, fmtClock, fmtMins, fmtMiles, itemParts,
  FILTERS, GROUP, GROUP_LABEL, buildFeed, summarizeWindows, usableMinutes,
  haversineMiles, driveMinutes, ageDays, effectiveConfidence,
} from "./lib.js";

const state = {
  venues: [],
  zones: [],
  day: 0,        // days ahead: 0 = today
  offset: -1,    // 15-minute slot of the day; -1 means "right now"
  zone: null,
  filter: "all",
  sort: "soonest",
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
  if (p.has("f") && FILTERS[p.get("f")]) state.filter = p.get("f");
  if (p.has("s") && SORTS.some(([k]) => k === p.get("s"))) state.sort = p.get("s");
  return p.get("v");
}

function writeHash(venueId) {
  const p = new URLSearchParams();
  if (state.day) p.set("d", state.day);
  if (state.offset >= 0) p.set("t", state.offset);
  if (state.zone) p.set("z", state.zone);
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
      [null, "All zones"],
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

  picker($("#sort"), SORTS, state.sort, (v) => (state.sort = v));
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
      sessionStorage.setItem("origin", JSON.stringify(state.origin));
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

function restoreLocation() {
  try {
    const saved = sessionStorage.getItem("origin");
    if (!saved) return;
    state.origin = JSON.parse(saved);
    $("#nearMe").classList.add("on");
    $("#nearMeLabel").textContent = "Located";
  } catch {
    /* a corrupt session value is not worth a crash */
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

function whenText(row) {
  const { hit } = row;
  if (hit.live) return { text: `Ends in ${fmtMins(hit.until)}`, live: true };
  if (hit.dayAhead === 0) return { text: `${fmtClock(hit.w.start)} · in ${fmtMins(hit.startsIn)}` };
  return { text: `${fmtClock(hit.w.start)}–${fmtClock(hit.w.end)}` };
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
    $(".credit", node).textContent = v.photo.attribution || "";
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

  const photo = el("button", "btn", "Or send a photo of the menu");
  photo.type = "button";
  photo.addEventListener("click", () => {
    // Remember which venue, then trigger the same file input the header button
    // uses. Coming from a card is the good case: the venue is already known, so
    // the submitter never has to find their own bar in a list of 2,900.
    state.photoVenue = v;
    $("#photo").click();
  });
  acts.append(photo);

  body.append(
    el("p", "note", `Reference: LID ${v.lid || v.id}. Quote it and we'll know exactly which venue you mean.`)
  );
  $("#sheet").showModal();
}

/* ---- photo lane -------------------------------------------------------- */

/* The Worker (worker/index.js). Everything else on this site is static files;
   this is the one endpoint that writes. */
const SUBMIT_API = "https://hhf-submit.paulrenzi.workers.dev";

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
function venuePicker(onPick) {
  const wrap = el("div", "picker");
  const input = el("input", "pickerInput");
  input.type = "search";
  input.placeholder = "Which bar? Start typing the name";
  input.setAttribute("aria-label", "Search for the venue this menu is from");
  const list = el("div", "pickerList");
  const chosen = el("p", "pickerChosen");

  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    list.textContent = "";
    if (q.length < 2) return;
    const hits = state.venues
      .filter((v) => v.name.toLowerCase().includes(q))
      .slice(0, 8);
    if (!hits.length) {
      // Boot loads every zone's deal-bearing venues, but the 2,900-venue base
      // arrives one zone at a time. So a miss here usually means "that zone
      // isn't loaded", not "that bar isn't licensed" -- and telling someone
      // their bar doesn't exist when we simply haven't fetched it is the wrong
      // answer to give the one person willing to fill the board in.
      list.append(
        el("p", "pickerMiss",
          "No match yet. If it's not a bar with hours already on the board, " +
            "pick its area at the top of the page first — that loads the rest.")
      );
      return;
    }
    for (const v of hits) {
      const b = el("button", "pickerHit");
      b.type = "button";
      b.append(el("b", null, v.name));
      b.append(el("span", null, v.address || ""));
      b.addEventListener("click", () => {
        onPick(v);
        chosen.textContent = `Menu for ${v.name}`;
        list.textContent = "";
        input.value = "";
      });
      list.append(b);
    }
  });

  wrap.append(input, list, chosen);
  return wrap;
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
      // Offline in a basement bar is the normal case, not the exception.
      status.textContent =
        "Couldn't reach us — you might be on bad signal. The photo is still in " +
        "your camera roll; try again when you have a bar or two.";
      send.disabled = false;
    }
  });

  $("#sheet").showModal();
}

function card(row, at) {
  const { v, deal, hit } = row;
  const node = $("#cardTpl").content.cloneNode(true);
  const article = $(".card", node);
  if (!hit.live) article.classList.add("soon");
  if (row.confidence === "unconfirmed") article.classList.add("dim");
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
    $(".credit", node).textContent = v.photo.attribution || "";
  } else {
    shot.classList.add("fallback");
    $(".mono", node).textContent = monogramOf(v.name);
  }
  shot.addEventListener("click", () => openVenue(v.id));

  $(".name", node).textContent = v.name;
  const zoneName = state.zones.find((z) => z.id === v.zone_id)?.name ?? "";
  const dist = distanceText(v, row.miles, row.driveMin);
  $(".zone", node).textContent = dist ? `${zoneName} · ${dist}` : zoneName;

  const items = $(".items", node);
  for (const item of deal.items) {
    const { amount, label } = itemParts(item);
    const li = el("li");
    if (amount) li.append(el("b", null, amount));
    li.append(document.createTextNode(label));
    items.append(li);
  }

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
  $(".fine", node).textContent = fine.trim();

  const conf = $(".conf", node);
  conf.classList.add(row.confidence);
  const age = row.ageDays === 0 ? "today" : `${row.ageDays}d ago`;
  conf.textContent =
    row.confidence === "unconfirmed" ? `Unconfirmed — call ahead · ${age}` : `Checked ${age}`;

  $(".map", node).href = directionsUrl(v);
  const src = $(".src", node);
  if (deal.source?.url) src.href = deal.source.url;
  else if (deal.source?.kind === "photo") {
    // A photo has no URL to link, but it still has a provenance, and every card
    // on this site says where its hours came from. Saying "from a photo of the
    // menu" is the honest version of that; removing the element would quietly
    // make this the one card that cites nothing.
    src.replaceWith(el("span", "srcNote", "From a photo of their menu"));
  } else src.remove();
  $(".wrong", node).addEventListener("click", () => reportWrong(v, deal));
  return node;
}

function render() {
  const at = arrivalTime();
  const rows = buildFeed(state.venues, at, {
    zone: state.zone,
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
        state.filter === "all"
          ? state.loadingZone
            ? "Loading this zone's venues…"
            : "Try another zone. Around four in five bars never publish a happy hour " +
              "anywhere, so most of the board is venues waiting for someone to fill them in."
          : `No ${FILTERS[state.filter].label.toLowerCase()} in this zone. Try “Everything” ` +
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
        ? "Loading every licensed venue in this zone…"
        : "Couldn't load the full venue list for this zone — showing published happy hours only.")
    );
  } else if (!state.zone && state.filter === "all") {
    feed.append(
      el(
        "p",
        "secNote",
        "Pick a zone above to see every licensed bar, restaurant and brewery in it — " +
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
          ? `Unconfirmed, last checked ${age}. Call ahead. Source: `
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

  writeHash(v.id);
  $("#sheet").showModal();
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
  body.append(
    el(
      "p",
      null,
      "Reports go to a human queue daily — that habit is the whole trust model. " +
        "The write path (Worker + D1) isn't wired yet, so nothing is sent."
    )
  );
  const p = el("p", "note");
  p.append(document.createTextNode("Source: "));
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
  $("#sheet").showModal();
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

/* The hero owns the title until it scrolls away, then the glass bar takes over. */
function watchHero() {
  const hero = $("#hero"), bar = $("#bar");
  if (!("IntersectionObserver" in window)) return bar.classList.add("show");
  new IntersectionObserver(([e]) => bar.classList.toggle("show", !e.isIntersecting), {
    rootMargin: "-56px 0px 0px 0px",
  }).observe(hero);
}

/* ---- boot ------------------------------------------------------------- */

async function boot() {
  // no-cache revalidates rather than trusting the 10-minute HTTP freshness window:
  // the zone list is what every count on the page is drawn from, so a stale copy is
  // wrong in a way the page cannot show.
  const index = await (await fetch("data/index.json", { cache: "no-cache" })).json();
  state.zones = index.zones;
  const bundles = await Promise.all(
    index.zones.map((z) => fetch(`data/zone-${z.id}.json`).then((r) => r.json()))
  );
  state.venues = bundles.flatMap((b) => b.venues);

  const openId = readHash();
  buildControls();
  restoreLocation();
  watchHero();
  render();
  // A shared link to a venue with no published hours names a venue that only
  // arrives with its zone's base, so the fetch has to finish before the sheet is
  // opened -- otherwise the link silently does nothing, which is exactly the
  // failure a share is supposed to prevent.
  if (state.zone) await loadZoneVenues(state.zone);
  if (openId) openVenue(openId);

  // Keep "ends in" honest while the page sits open, but only in live mode.
  setInterval(() => isNow() && render(), 30000);

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
  $("#photo").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    // Let the same file be picked twice in a row, and clear it before the sheet
    // opens so a cancelled pick doesn't leave the input holding the last one.
    e.target.value = "";
    if (file) photoLane(file);
  });
  $("#sheetClose").addEventListener("click", () => $("#sheet").close());
  $("#sheet").addEventListener("close", () => writeHash());

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
}

boot();
