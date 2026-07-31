/* All filtering and "what's live right now" math runs client-side over the
   cached zone bundles, so the app works on a bad signal in a parking lot. */

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const state = { venues: [], zones: [], zone: null, offset: -1 };

const $ = (s, r = document) => r.querySelector(s);
const mins = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};
// Bundles use dow 1=Mon..7=Sun; Date uses 0=Sun.
const dowOf = (d) => (d.getDay() === 0 ? 7 : d.getDay());

function money(n) {
  return "$" + (n % 1 ? n.toFixed(2) : n);
}

/* Split into {amount, label} so the number can carry its own weight. */
function itemParts(item) {
  if (item.price_usd != null) return { amount: money(item.price_usd), label: item.label };
  if (item.discount_pct != null) return { amount: item.discount_pct + "% off", label: item.label };
  if (item.amount_off_usd != null) return { amount: money(item.amount_off_usd) + " off", label: item.label };
  return { amount: "", label: item.label };
}

/* The window covering `at`, or the next one starting within `lookahead` minutes. */
function windowFor(deal, at, lookahead = 180) {
  const dow = dowOf(at);
  const now = at.getHours() * 60 + at.getMinutes();
  let best = null;
  for (const w of deal.windows) {
    if (w.dow !== dow) continue;
    const s = mins(w.start), e = mins(w.end);
    if (now >= s && now < e) return { w, live: true, until: e - now };
    if (s > now && s - now <= lookahead) {
      const inMin = s - now;
      if (!best || inMin < best.until) best = { w, live: false, until: inMin };
    }
  }
  return best;
}

function fmtMins(n) {
  if (n < 60) return `${n} min`;
  const h = Math.floor(n / 60), m = n % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function arrivalTime() {
  if (state.offset < 0) return new Date();
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setMinutes(state.offset * 15);
  // Dragging to a time already past means tomorrow.
  if (d < new Date()) d.setDate(d.getDate() + 1);
  return d;
}

function score(row) {
  // Live beats upcoming; among live, less time remaining is more urgent;
  // a confident deal outranks an unconfirmed one at the same urgency.
  const conf = { verified: 0, likely: 1, unconfirmed: 2, disputed: 3 }[row.deal.confidence] ?? 2;
  return (row.hit.live ? 0 : 10000) + row.hit.until + conf * 3;
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

function heading(text) {
  const h = document.createElement("p");
  h.className = "sec";
  h.textContent = text;
  return h;
}

function render() {
  const at = arrivalTime();
  const feed = $("#feed");
  feed.textContent = "";

  const rows = [];
  for (const v of state.venues) {
    if (state.zone && v.zone_id !== state.zone) continue;
    for (const deal of v.deals) {
      if (deal.confidence === "disputed") continue;
      const hit = windowFor(deal, at);
      if (hit) rows.push({ v, deal, hit });
    }
  }
  rows.sort((a, b) => score(a) - score(b));

  const clock = at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  $("#clock").textContent = state.offset < 0 ? clock : `${DOW[at.getDay()]} ${clock}`;
  $("#whenLabel").textContent = state.offset < 0 ? "Right now" : "Arriving " + clock;

  const liveCount = rows.filter((r) => r.hit.live).length;
  $("#heroCount").innerHTML = rows.length
    ? (liveCount
        ? `<b>${liveCount}</b> happy hour${liveCount === 1 ? "" : "s"} live ${state.offset < 0 ? "now" : "then"}`
        : `Nothing live — <b>${rows.length}</b> starting soon`)
    : "Nothing live at that time";

  if (!rows.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.innerHTML =
      "<b>Nothing live here at that time.</b>Drag the slider, or pick another zone. " +
      "The seed corpus is 8 hand-checked venues — most bars around here never publish their happy hour, " +
      "which is what the camera button is for.";
    feed.append(p);
    return;
  }

  let section = null;
  for (const { v, deal, hit } of rows) {
    const want = hit.live ? "Live now" : "Starting soon";
    if (want !== section) {
      feed.append(heading((section = want)));
    }

    const el = $("#cardTpl").content.cloneNode(true);
    const card = $(".card", el);
    if (!hit.live) card.classList.add("soon");
    if (deal.confidence === "unconfirmed") card.classList.add("dim");

    const shot = $(".shot", el);
    shot.style.setProperty("--h", hueOf(v.id));
    if (v.photo) {
      const img = $(".photo", el);
      img.src = v.photo.file;
      img.hidden = false;
      // A photo that 404s must not leave a blank band -- fall back to the tile.
      img.addEventListener("error", () => {
        img.remove();
        shot.classList.add("fallback");
      });
      $(".credit", el).textContent = v.photo.attribution || "";
    } else {
      shot.classList.add("fallback");
      $(".mono", el).textContent = monogramOf(v.name);
    }

    $(".name", el).textContent = v.name;
    $(".zone", el).textContent = state.zones.find((z) => z.id === v.zone_id)?.name ?? "";

    const items = $(".items", el);
    for (const item of deal.items) {
      const { amount, label } = itemParts(item);
      const li = document.createElement("li");
      if (amount) li.append(Object.assign(document.createElement("b"), { textContent: amount }));
      li.append(document.createTextNode(label));
      items.append(li);
    }
    $(".fine", el).textContent =
      deal.fine_print || (deal.items.length ? "" : "Window published without prices.");

    const ends = $(".ends", el);
    if (hit.live) {
      ends.classList.add("live");
      ends.textContent = `Ends in ${fmtMins(hit.until)}`;
    } else {
      ends.textContent = `In ${fmtMins(hit.until)} · ${hit.w.start}`;
    }

    const conf = $(".conf", el);
    conf.classList.add(deal.confidence);
    const age = deal.age_days === 0 ? "today" : `${deal.age_days}d ago`;
    conf.textContent =
      deal.confidence === "unconfirmed" ? `Unconfirmed — call ahead · ${age}` : `Checked ${age}`;

    $(".map", el).href =
      "https://www.google.com/maps/dir/?api=1&destination=" +
      encodeURIComponent(`${v.name}, ${v.address}`);
    $(".src", el).href = deal.source.url;
    $(".wrong", el).addEventListener("click", () =>
      sheet(
        `<h3>${v.name}</h3><p>Reports go to a human queue daily — that habit is the whole trust model. ` +
          `The write path (Worker + D1) isn't wired yet, so this is a stub.</p>` +
          `<p>Source: <a href="${deal.source.url}">${deal.source.kind}</a>` +
          (deal.source.note ? `<br>${deal.source.note}` : "") +
          `</p>`
      )
    );
    feed.append(el);
  }
}

function sheet(html) {
  $("#sheetBody").innerHTML = html;
  $("#sheet").showModal();
}

function buildZoneChips() {
  const box = $("#zones");
  const mk = (id, label) => {
    const b = document.createElement("button");
    b.className = "chip";
    b.type = "button";
    b.textContent = label;
    b.setAttribute("aria-pressed", state.zone === id);
    b.addEventListener("click", () => {
      state.zone = id;
      [...box.children].forEach((c) => c.setAttribute("aria-pressed", "false"));
      b.setAttribute("aria-pressed", "true");
      render();
    });
    box.append(b);
  };
  mk(null, "All zones");
  state.zones.forEach((z) => mk(z.id, z.name));
}

/* The hero owns the title until it scrolls away, then the glass bar takes over. */
function watchHero() {
  const hero = $("#hero"), bar = $("#bar");
  if (!("IntersectionObserver" in window)) return bar.classList.add("show");
  new IntersectionObserver(([e]) => bar.classList.toggle("show", !e.isIntersecting), {
    rootMargin: "-56px 0px 0px 0px",
  }).observe(hero);
}

async function boot() {
  const index = await (await fetch("data/index.json")).json();
  state.zones = index.zones;
  const bundles = await Promise.all(
    index.zones.map((z) => fetch(`data/zone-${z.id}.json`).then((r) => r.json()))
  );
  state.venues = bundles.flatMap((b) => b.venues);

  buildZoneChips();
  watchHero();
  render();
  setInterval(() => state.offset < 0 && render(), 30000);

  $("#credits").innerHTML =
    'Header photo: <a href="https://commons.wikimedia.org/wiki/File:South_Shore_Brewery_Taproom.jpg">' +
    "South Shore Brewery Taproom</a> by Billertl, cropped, " +
    '<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>. ' +
    "Deal windows are transcribed from the source linked on each card — always call ahead.";

  $("#when").addEventListener("input", (e) => {
    state.offset = Number(e.target.value);
    render();
  });
  $("#nowBtn").addEventListener("click", () => {
    state.offset = -1;
    $("#when").value = -1;
    render();
    scrollTo({ top: 0, behavior: "smooth" });
  });
  $("#photo").addEventListener("change", () =>
    sheet(
      "<h3>Photo lane</h3><p>Capture works — the upload, vision extraction and moderation " +
        "pipeline are not built yet. At a 19% scrape yield this lane is the only path to half " +
        "the venues in the area, so it is the next thing to build.</p>"
    )
  );
  $("#sheetClose").addEventListener("click", () => $("#sheet").close());

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
}

boot();
