/* The product is this file. Everything here is pure: given a corpus, a moment,
   and where you are standing, it decides what to show and in what order.
   app.js only turns the result into DOM.

   Kept separate because it is the part that can be wrong in a way nobody sees
   -- a card on the wrong day still looks like a correct card -- so it is the
   part that has tests (tests/time_math.test.mjs). */

export const DOW_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const DOW_LONG = [
  "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
];

/* Bundles use dow 1=Mon..7=Sun (ISO). JS Date uses 0=Sun..6=Sat. Every bug in
   this file's history would have lived in that gap, so it is converted once,
   here, and nowhere else. */
export const dowOf = (d) => (d.getDay() === 0 ? 7 : d.getDay());

export const mins = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

export function minutesOfDay(d) {
  return d.getHours() * 60 + d.getMinutes();
}

/* 16:00 -> "4pm", 16:30 -> "4:30pm", 24:00 -> "midnight" (the latest a PA
   discount may legally run, so it shows up in real data). */
export function fmtClock(hhmm) {
  const t = typeof hhmm === "string" ? mins(hhmm) : hhmm;
  if (t >= 1440) return "midnight";
  const h = Math.floor(t / 60), m = t % 60;
  const suffix = h >= 12 ? "pm" : "am";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m ? `${h12}:${String(m).padStart(2, "0")}${suffix}` : `${h12}${suffix}`;
}

export function fmtMins(n) {
  if (n < 60) return `${n} min`;
  const h = Math.floor(n / 60), m = n % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export function money(n) {
  return "$" + (n % 1 ? n.toFixed(2) : n);
}

/* Split into {amount, label} so the number can carry its own weight. */
export function itemParts(item) {
  if (item.price_usd != null) return { amount: money(item.price_usd), label: item.label };
  if (item.discount_pct != null) return { amount: item.discount_pct + "% off", label: item.label };
  if (item.amount_off_usd != null) return { amount: money(item.amount_off_usd) + " off", label: item.label };
  return { amount: "", label: item.label };
}

/* ---- geography -------------------------------------------------------- */

const R_MILES = 3958.8;
const rad = (deg) => (deg * Math.PI) / 180;

export function haversineMiles(a, b) {
  const dLat = rad(b.lat - a.lat), dLng = rad(b.lng - a.lng);
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R_MILES * Math.asin(Math.sqrt(s));
}

/* Crow-flies miles -> a defensible drive estimate. Suburban Montgomery/Delaware
   County roads run about 1.35x straight-line and average ~26 mph door to door,
   plus a few minutes to park. This is an ESTIMATE and the UI always says "~".
   Replacing it with a routing API changes only this function. */
export function driveMinutes(miles) {
  return Math.max(1, Math.round((miles * 1.35 * 60) / 26 + 3));
}

export function fmtMiles(miles, precise = true) {
  if (miles < 0.1) return "here";
  // A road-level geocode is good to a block, so don't imply a decimal of accuracy.
  if (!precise) return `~${Math.round(miles)} mi`;
  return miles < 10 ? `${miles.toFixed(1)} mi` : `${Math.round(miles)} mi`;
}

/* ---- deal value ------------------------------------------------------- */

/* A single sortable "how good is this", which is the thing SPEC section 7 says
   nobody else can do -- "half off drafts", "$4 drafts" and "$2 off all beer"
   are three unsortable strings everywhere else.

   It is a HEURISTIC and is only ever used for ordering, never displayed as a
   number, because there is no honest unit for it. Higher is better. */
export function itemValue(item) {
  if (item.discount_pct != null) return item.discount_pct;
  if (item.amount_off_usd != null) return item.amount_off_usd * 12;
  if (item.price_usd != null) {
    return item.category === "food"
      ? Math.max(0, 60 - item.price_usd * 4)
      : Math.max(0, 70 - item.price_usd * 7);
  }
  return 0;
}

export function dealValue(deal) {
  // The best single item is what makes you choose a bar, not the average.
  return (deal.items || []).reduce((best, i) => Math.max(best, itemValue(i)), 0);
}

export function cheapestPrice(deal, categories = null) {
  let best = null;
  for (const i of deal.items || []) {
    if (i.price_usd == null) continue;
    if (categories && !categories.includes(i.category)) continue;
    if (best == null || i.price_usd < best) best = i.price_usd;
  }
  return best;
}

export const DRINK_CATEGORIES = ["draft", "bottle_can", "wine", "well", "call", "cocktail", "shot"];

/* ---- filters ---------------------------------------------------------- */

export const FILTERS = {
  all: { label: "Everything", test: () => true },
  food: {
    label: "Food deals",
    test: (deal) => (deal.items || []).some((i) => i.category === "food"),
  },
  cheap: {
    label: "Drinks under $5",
    test: (deal) => {
      const p = cheapestPrice(deal, DRINK_CATEGORIES);
      return p != null && p < 5;
    },
  },
  drinks: {
    label: "Drink deals",
    test: (deal) => (deal.items || []).some((i) => DRINK_CATEGORIES.includes(i.category)),
  },
};

/* ---- when is this deal on? -------------------------------------------- */

/* The window covering `at`, or the next one starting within `lookahead` minutes
   on the SAME day. Returns null when neither applies -- callers that must not
   dead-end use nextOccurrence() instead. */
export function windowFor(deal, at, lookahead = 180) {
  const dow = dowOf(at);
  const now = minutesOfDay(at);
  let best = null;
  for (const w of deal.windows) {
    if (w.dow !== dow) continue;
    const s = mins(w.start), e = mins(w.end);
    if (now >= s && now < e) return { w, live: true, until: e - now, startsIn: 0 };
    if (s > now && s - now <= lookahead) {
      const inMin = s - now;
      if (!best || inMin < best.startsIn) best = { w, live: false, until: inMin, startsIn: inMin };
    }
  }
  return best;
}

/* The next time this deal runs at all, searching forward up to `horizonDays`.

   This is what keeps the app from being blank for eighteen hours a day. At
   11am on a Sunday every window is either over or days away, and "nothing live"
   is a true statement that is useless to someone holding a phone. */
export function nextOccurrence(deal, from, horizonDays = 7) {
  const startMinutes = minutesOfDay(from);
  for (let dayAhead = 0; dayAhead <= horizonDays; dayAhead++) {
    const day = new Date(from);
    day.setDate(day.getDate() + dayAhead);
    const dow = dowOf(day);
    let best = null;
    for (const w of deal.windows) {
      if (w.dow !== dow) continue;
      const s = mins(w.start), e = mins(w.end);
      if (dayAhead === 0) {
        if (startMinutes >= e) continue; // already over today
        if (startMinutes >= s) return { w, live: true, until: e - startMinutes, startsIn: 0, dayAhead };
      }
      const startsIn = dayAhead * 1440 + s - startMinutes;
      if (!best || startsIn < best.startsIn) best = { w, live: false, until: startsIn, startsIn, dayAhead };
    }
    if (best) return best;
  }
  return null;
}

/* ---- freshness -------------------------------------------------------- */

/* Age is computed HERE, at read time, from the absolute date in the bundle --
   never baked in at build time. A bundle built once and served for two months
   would otherwise keep telling everyone a deal was "checked 1d ago" forever,
   which is precisely the failure this product exists to avoid. */
export function ageDays(deal, now = new Date()) {
  if (!deal.last_verified_at) return null;
  const seen = new Date(deal.last_verified_at + "T00:00:00");
  return Math.max(0, Math.floor((now - seen) / 86400000));
}

/* The decay ladder from SPEC section 6, mirrored from ingest/build_bundles.py.
   A deal never silently disappears, it demotes: deleting looks like a bug to
   the person who saw it yesterday, demoting with a visible date reads as
   honesty. Kept client-side for the same reason as ageDays. */
export function effectiveConfidence(deal, now = new Date()) {
  const stated = deal.confidence;
  if (stated === "verified" || stated === "disputed") return stated;
  const age = ageDays(deal, now);
  if (age == null) return stated;
  if (age > 120) return "hidden";
  if (age > 45 && stated === "likely") return "unconfirmed";
  return stated;
}

/* ---- ranking ---------------------------------------------------------- */

/* Groups, in the order a person actually wants them. Lower sorts first. */
export const GROUP = {
  LIVE: 0,        // on now, and you can get there
  SOON: 1,        // starts within the lookahead
  LATER: 2,       // later today
  UPCOMING: 3,    // another day
  UNREACHABLE: 4, // on now, but it ends before you could arrive
  UNKNOWN: 5,     // a licensed bar we have no published window for -- most of them
};

export const GROUP_LABEL = {
  [GROUP.LIVE]: "Live now",
  [GROUP.SOON]: "Starting soon",
  [GROUP.LATER]: "Later today",
  [GROUP.UPCOMING]: "Later this week",
  [GROUP.UNREACHABLE]: "Ends before you'd get there",
  [GROUP.UNKNOWN]: "Hours not published",
};

const CONFIDENCE_PENALTY = { verified: 0, likely: 3, unconfirmed: 9, disputed: 99 };

/* Assign a row to a group, given how far away it is.

   The important case is UNREACHABLE. Sorting live deals by least-time-remaining
   -- which is what "urgency" naively means -- puts the deal you have the least
   chance of reaching at the very top of the screen. A deal ending in 8 minutes
   25 minutes away is not the best answer to "where can I go right now", it is
   the worst one. Without a location we cannot know, so we never claim it. */
export function groupFor(hit, driveMin) {
  if (hit.live) {
    if (driveMin != null && hit.until <= driveMin) return GROUP.UNREACHABLE;
    return GROUP.LIVE;
  }
  if (hit.dayAhead > 0) return GROUP.UPCOMING;
  return hit.startsIn <= 180 ? GROUP.SOON : GROUP.LATER;
}

/* Minutes of happy hour you would actually get, having driven there. This, and
   not "minutes remaining", is what a live deal is worth. */
export function usableMinutes(hit, driveMin) {
  return Math.max(0, hit.until - (driveMin ?? 0));
}

/* Past this much deal left, more time stops being a reason to choose one bar
   over another -- three hours and two hours are the same evening. Capping it is
   what stops a distant all-night deal from outranking the good one nearby. */
const ENOUGH_MINUTES = 120;
const DRIVE_WEIGHT = 12; // a minute in the car costs more than a minute of deal
const TIME_WEIGHT = 10;

/* Lower is better. Deliberately readable rather than tuned: group dominates,
   then how much deal you actually get, then how far, then how good, then how
   sure we are. */
export function score(row, { sort = "soonest" } = {}) {
  const conf = CONFIDENCE_PENALTY[row.confidence] ?? 9;
  const drive = row.driveMin ?? 0;

  /* A venue with no published window has no deal to rank and no window to be
     early or late for. It sits in its own group below everything else, ordered
     by how far away it is -- the only fact about it we actually have. */
  if (row.group === GROUP.UNKNOWN) {
    return GROUP.UNKNOWN * 100000 + Math.min((row.miles ?? 999) * 100, 99999);
  }

  const value = dealValue(row.deal);

  if (sort === "nearest") {
    return row.group * 100000 + (row.miles ?? 999) * 100 + conf;
  }
  if (sort === "value") {
    return row.group * 100000 + (100 - Math.min(value, 100)) * 100 + drive + conf;
  }
  // "soonest" -- the default, and the one that answers "where can I go now".
  const shortfall = row.hit.live
    ? ENOUGH_MINUTES - Math.min(usableMinutes(row.hit, row.driveMin), ENOUGH_MINUTES)
    : row.hit.startsIn;
  return (
    row.group * 100000 +
    shortfall * TIME_WEIGHT +
    drive * DRIVE_WEIGHT +
    (100 - Math.min(value, 100)) +
    conf
  );
}

/* ---- the one call the app makes --------------------------------------- */

/* Build the ordered feed. `at` is the arrival moment; `origin` is the user's
   position or null. Rows are grouped and sorted, and the caller renders them
   in order, starting a new section whenever `group` changes. */
export function buildFeed(venues, at, { zone = null, filter = "all", sort = "soonest", origin = null, horizonDays = 7 } = {}) {
  const test = (FILTERS[filter] || FILTERS.all).test;
  const rows = [];

  for (const v of venues) {
    if (zone && v.zone_id !== zone) continue;
    const miles = origin && v.lat != null ? haversineMiles(origin, v) : null;
    const driveMin = miles == null ? null : driveMinutes(miles);

    /* The reframe: the board is a list of VENUES, and the happy hour is an
       attribute some of them have. A licensed bar with no window we could prove
       still gets a row, because it is the only way a person can see that it is
       missing and tell us what it is -- they cannot fill in a bar that never
       shows up. It is excluded only under a DEAL filter, where the question
       being asked ("food deals") is one an empty venue cannot answer. */
    if (!v.deals || !v.deals.length) {
      if (filter === "all") {
        rows.push({
          v, deal: null, hit: null, miles, driveMin,
          confidence: "unknown", ageDays: null, group: GROUP.UNKNOWN,
        });
      }
      continue;
    }

    for (const deal of v.deals) {
      const confidence = effectiveConfidence(deal, at);
      // Disputed is held out of default results; hidden has decayed past the
      // point where showing it is honest.
      if (confidence === "disputed" || confidence === "hidden") continue;
      if (!test(deal)) continue;
      const hit = nextOccurrence(deal, at, horizonDays);
      if (!hit) continue;
      rows.push({
        v, deal, hit, miles, driveMin,
        confidence,
        ageDays: ageDays(deal, at),
        group: groupFor(hit, driveMin),
      });
    }
  }

  rows.sort((a, b) => score(a, { sort }) - score(b, { sort }) || a.v.name.localeCompare(b.v.name));
  return rows;
}

/* "Mon–Fri 4–6pm, Sat–Sun 2–4pm" -- collapse a week of windows into the line a
   person would actually say. Consecutive days sharing a time become a range. */
export function summarizeWindows(windows) {
  const byTime = new Map();
  for (const w of windows) {
    const key = `${w.start}-${w.end}`;
    if (!byTime.has(key)) byTime.set(key, []);
    byTime.get(key).push(w.dow);
  }
  const parts = [];
  for (const [key, dows] of byTime) {
    const [start, end] = key.split("-");
    dows.sort((a, b) => a - b);
    const runs = [];
    for (const d of dows) {
      const last = runs[runs.length - 1];
      if (last && d === last[1] + 1) last[1] = d;
      else runs.push([d, d]);
    }
    const days = runs
      .map(([a, b]) =>
        a === b
          ? DOW_SHORT[a - 1]
          : b === a + 1
            ? `${DOW_SHORT[a - 1]}, ${DOW_SHORT[b - 1]}`
            : `${DOW_SHORT[a - 1]}–${DOW_SHORT[b - 1]}`
      )
      .join(", ");
    parts.push(`${days} ${fmtClock(start)}–${fmtClock(end)}`);
  }
  return parts.join(" · ");
}
