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

function itemText(item) {
  if (item.price_usd != null) return `${money(item.price_usd)} ${item.label}`;
  if (item.discount_pct != null) return `${item.discount_pct}% off ${item.label}`;
  if (item.amount_off_usd != null) return `${money(item.amount_off_usd)} off ${item.label}`;
  return item.label;
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

  $("#clock").textContent =
    state.offset < 0
      ? at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      : `${DOW[at.getDay()]} ${at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  $("#whenLabel").textContent =
    state.offset < 0
      ? "Right now"
      : "Arriving " + at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  if (!rows.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.innerHTML =
      "<b>Nothing live here at that time.</b><br>Drag the slider, or pick another zone. " +
      "The seed corpus is 8 hand-checked venues — most bars around here never publish their happy hour, " +
      "which is what the camera button is for.";
    feed.append(p);
    return;
  }

  for (const { v, deal, hit } of rows) {
    const el = $("#cardTpl").content.cloneNode(true);
    const card = $(".card", el);
    if (!hit.live) card.classList.add("soon");
    if (deal.confidence === "unconfirmed") card.classList.add("dim");

    $(".name", el).textContent = v.name;
    $(".zone", el).textContent = state.zones.find((z) => z.id === v.zone_id)?.name ?? "";
    $(".items", el).textContent = deal.items.map(itemText).join(" · ");
    $(".fine", el).textContent =
      deal.fine_print || (deal.items.length ? "" : "Window published without prices.");

    const ends = $(".ends", el);
    if (hit.live) {
      ends.classList.add("live");
      ends.textContent = `Ends in ${fmtMins(hit.until)}`;
    } else {
      ends.textContent = `Starts in ${fmtMins(hit.until)} · ${hit.w.start}–${hit.w.end}`;
    }

    const conf = $(".conf", el);
    conf.classList.add(deal.confidence);
    const age = deal.age_days === 0 ? "today" : `${deal.age_days}d ago`;
    conf.textContent =
      deal.confidence === "unconfirmed"
        ? `Unconfirmed — call ahead · ${age}`
        : `Checked ${age}`;

    $(".map", el).href =
      "https://www.google.com/maps/dir/?api=1&destination=" +
      encodeURIComponent(`${v.name}, ${v.address}`);
    $(".src", el).href = deal.source.url;
    $(".wrong", el).addEventListener("click", () =>
      sheet(
        `<h3>${v.name}</h3><p>Reports go to a human queue daily — that habit is the whole trust model. ` +
          `The write path (Worker + D1) isn't wired yet, so this is a stub.</p>` +
          `<p style="color:var(--dim)">Source: <a href="${deal.source.url}">${deal.source.kind}</a>` +
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

async function boot() {
  const index = await (await fetch("data/index.json")).json();
  state.zones = index.zones;
  const bundles = await Promise.all(
    index.zones.map((z) => fetch(`data/zone-${z.id}.json`).then((r) => r.json()))
  );
  state.venues = bundles.flatMap((b) => b.venues);

  buildZoneChips();
  render();
  setInterval(() => state.offset < 0 && render(), 30000);

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
