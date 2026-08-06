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
};

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

  picker(
    $("#zone"),
    [[null, "All zones"], ...state.zones.map((z) => [z.id, `${z.name} (${z.venues})`])],
    state.zone,
    (v) => (state.zone = v)
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
  else src.remove(); // a photo-sourced deal has no link to point at yet
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
  $("#heroCount").innerHTML = live
    ? `<b>${live}</b> happy hour${live === 1 ? "" : "s"} live ${isNow() ? "now" : "then"}`
    : soon
      ? `Nothing live yet — <b>${soon}</b> starting soon`
      : rows.length
        ? `Nothing on ${isNow() ? "right now" : "then"} — here's what's next`
        : "Nothing matches that filter";

  const feed = $("#feed");
  feed.textContent = "";

  if (!rows.length) {
    const p = el("p", "empty");
    p.append(el("b", null, "Nothing matches that."));
    p.append(
      document.createTextNode(
        state.filter === "all"
          ? "Try another zone. The seed corpus is 8 hand-checked venues — most bars around " +
            "here never publish their happy hour, which is what the camera button is for."
          : `No ${FILTERS[state.filter].label.toLowerCase()} in this zone. Try “Everything”.`
      )
    );
    feed.append(p);
    $("#status").textContent = "No results.";
    $("#sectionKicker").textContent = "Nothing to show";
    return;
  }

  let section = null;
  for (const row of rows) {
    const want = sectionFor(row, at);
    if (want !== section) feed.append(el("p", "sec", (section = want)));
    feed.append(card(row, at));
  }
  $("#status").textContent = `${rows.length} result${rows.length === 1 ? "" : "s"}, ${live} live.`;
  $("#sectionKicker").textContent =
    `${rows.length} venue${rows.length === 1 ? "" : "s"} · ` +
    (live ? `${live} live ${isNow() ? "now" : "then"}` : "none live");
}

function refresh() {
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
  const v = state.venues.find((x) => x.id === id);
  if (!v) return;
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
  const index = await (await fetch("data/index.json")).json();
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
  $("#photo").addEventListener("change", () => {
    const body = $("#sheetBody");
    body.textContent = "";
    body.append(el("h3", null, "Photo lane"));
    body.append(
      el(
        "p",
        null,
        "Capture works — the upload, vision extraction and moderation pipeline are not " +
          "built yet. At a 19% scrape yield this lane is the only path to half the venues " +
          "in the area, so it is the next thing to build."
      )
    );
    $("#sheet").showModal();
  });
  $("#sheetClose").addEventListener("click", () => $("#sheet").close());
  $("#sheet").addEventListener("close", () => writeHash());

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
}

boot();
