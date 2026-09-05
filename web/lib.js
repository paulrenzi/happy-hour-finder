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
  if (item.price_usd != null) {
    // A range is shown as a range. See price_max in ingest/validate_pa.py.
    const amount = item.price_max != null
      ? money(item.price_usd) + "\u2013" + money(item.price_max).replace("$", "")
      : money(item.price_usd);
    return { amount, label: item.label };
  }
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

/* Drinks first, food last, everything else (fine print items with no
   category, daily specials) in between -- a long list now reads as one
   section a reader can stop skimming once they hit food. A stable sort: two
   items of the same section keep the order the source read them in. */
export function sortForDisplay(items) {
  const rank = (i) => (DRINK_CATEGORIES.includes(i.category) ? 0
    : i.category === "food" ? 2
    : 1);
  return items.map((item, i) => ({ item, i }))
    .sort((a, b) => rank(a.item) - rank(b.item) || a.i - b.i)
    .map((x) => x.item);
}

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
    /* The CALENDAR DATE this occurrence falls on, carried on the hit itself.
       `dayAhead` is measured from the anchor, and the anchor moves when the
       reader picks a day -- so reading "tomorrow" off dayAhead labelled the day
       AFTER the one they picked. A date cannot drift; every label is derived
       from it against the real today. */
    const dateKey = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
    let best = null;
    for (const w of deal.windows) {
      if (w.dow !== dow) continue;
      const s = mins(w.start), e = mins(w.end);
      if (dayAhead === 0) {
        if (startMinutes >= e) continue; // already over today
        if (startMinutes >= s) return { w, live: true, until: e - startMinutes, startsIn: 0, dayAhead, dateKey };
      }
      const startsIn = dayAhead * 1440 + s - startMinutes;
      if (!best || startsIn < best.startsIn) best = { w, live: false, until: startsIn, startsIn, dayAhead, dateKey };
    }
    if (best) return best;
  }
  return null;
}

/* Today's date key, for comparing against a hit's. */
export function dateKeyOf(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/* How many calendar days ahead of the REAL today a hit falls.

   The feed prints a section header whenever the label changes, and the label is
   this number -- so the ORDER has to be built from the same number, or the two
   disagree and a day's header repeats every time another day's row lands in the
   middle of it. One function, both readers: the header in app.js and the score
   below. They cannot drift apart. */
export function dayOffset(hit, today) {
  if (!hit || !hit.dateKey || !today) return 0;
  return Math.round(
    (new Date(hit.dateKey + "T00:00:00") - new Date(today + "T00:00:00")) / 86400000
  );
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
   the worst one. Without a location we cannot know, so we never claim it.

   `planning` is true whenever the reader is looking at anything other than the
   present. "Live now" and "Ends before you'd get there" are claims ABOUT THE
   PRESENT and are false of any other moment -- picking Tomorrow used to file
   210 cards as live and 71 as unreachable, both of a day that has not started.
   Nothing is live on a future day and nothing can be missed by driving to it,
   so planning collapses those three groups into "when is it on". */
export function groupFor(hit, driveMin, { planning = false, today = null } = {}) {
  if (planning) {
    return today && hit.dateKey && hit.dateKey !== today
      ? GROUP.UPCOMING
      : GROUP.LATER;
  }
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
/* Start times inside the same half-hour are the same decision -- see score(). */
const START_BUCKET = 30;
/* A group is worth 100,000, and a future row's day gets a slice of it.

   The furthest day a row can name is the last day the picker offers (6) plus
   the lookahead from there (7) -- fourteen slices counting today. They have to
   fit inside one group AND every distinct day needs its own slice: clamping the
   far ones into a shared band is what left Wednesday, Thursday and Friday
   interleaved when the reader picked three days out, because the ORDER merged
   days the HEADER still tells apart. */
export const MAX_DAY = 13;
export const DAY_BAND = Math.floor(100000 / (MAX_DAY + 1)); // 7142

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

  /* Another DAY is not an urgency. Inside "Tomorrow" or "Thursday", ordering by
     who opens earliest is answering a question nobody asked -- 11am and 4pm are
     both "not now", and it put a seventeen-mile brewery above one down the road
     for the sole reason that it opens at eleven. Once we know where the reader
     is, distance is the fact that actually separates these, so it leads and the
     clock breaks the tie. With no location we have nothing better than the
     clock, and we keep it. */
  /* ---- another day: the DATE leads, in every sort ----------------------
     The board prints one header per day, so a row's day has to outrank
     everything else about it. This used to be true in exactly ONE of the four
     paths through this function -- "soonest" with a location -- and the other
     three ranked future rows globally. That is what printed "Tomorrow" twenty
     times: a single Thursday row scoring between two Wednesday ones splits
     Wednesday's block, and the renderer, which starts a section whenever the
     label changes, prints the header again on the far side of it. Sorting
     across days was never a preference the reader expressed; picking a sort
     asks how to order the bars, not how to shuffle the calendar.

     One day gets one band of DAY_BAND, so nothing inside a day can score into
     the next one and nothing can leak past the group. Inside the day, the sort
     the reader chose decides -- each term below is sized to fit its band. */
  if (row.group === GROUP.UPCOMING) {
    const day = Math.max(0, Math.min(MAX_DAY, row.dayIndex ?? row.hit.dayAhead ?? 0));

    /* Every term is a FRACTION of its own range, and the weights fall away by a
       factor of ten, so the leading term decides, the next one breaks its ties,
       and the whole sum is provably under 1 -- which is what keeps a row inside
       its day whatever the numbers do. Ranking on raw minutes and miles is what
       needed a clamp, and a clamp is what merged the far days. */
    const part = (x, of) => Math.min(1, Math.max(0, x) / of);
    /* A venue we have no coordinates for sorts last inside its day. We cannot
       say it is near, and 2,100 of 2,900 venues have no coordinates yet --
       floating all of them above the ones we CAN place would undo the whole
       point of asking for a location. */
    const near = part(Math.min(row.miles ?? 199, 199), 200);
    const dear = part(100 - Math.min(value, 100), 100);
    /* The clock WITHIN the day. `startsIn` carries the day inside it, so
       ranking on it would re-rank the calendar we just fixed. */
    const clock = part(Math.floor((row.hit.w ? mins(row.hit.w.start) : 0) / START_BUCKET), 48);
    const unsure = part(conf, 10);

    let within;
    if (sort === "nearest") {
      within = near * 0.9 + unsure * 0.09;
    } else if (sort === "value") {
      within = dear * 0.9 + part(drive, 120) * 0.09;
    } else if (row.hasOrigin) {
      /* Another DAY is not an urgency. Inside "Tomorrow" or "Thursday",
         ordering by who opens earliest answers a question nobody asked -- 11am
         and 4pm are both "not now", and it put a seventeen-mile brewery above
         one down the road for the sole reason that it opens at eleven. Once we
         know where the reader is, distance separates these and the clock breaks
         the tie. */
      within = near * 0.9 + clock * 0.09;
    } else {
      // With no location we have nothing better than the clock, and we keep it.
      within = clock * 0.9 + dear * 0.09;
    }
    return row.group * 100000 + day * DAY_BAND + (within + unsure * 0.009) * DAY_BAND;
  }

  if (sort === "nearest") {
    return row.group * 100000 + (row.miles ?? 999) * 100 + conf;
  }
  if (sort === "value") {
    return row.group * 100000 + (100 - Math.min(value, 100)) * 100 + drive + conf;
  }
  // "soonest" -- the default, and the one that answers "where can I go now".

  /* Bucketed, not raw. Nobody chooses between "starts at 4:00" and "starts at
     4:20" -- they are the same plan -- but raw minutes made that 200 points of
     ranking, which no realistic distance could overcome, so an identical deal
     seventeen miles away outranked one down the street. Rounding start times
     into half-hours says the true thing: within the same part of the evening,
     the nearer bar is the better answer. */
  const shortfall = row.hit.live
    ? ENOUGH_MINUTES - Math.min(usableMinutes(row.hit, row.driveMin), ENOUGH_MINUTES)
    : Math.floor(row.hit.startsIn / START_BUCKET) * START_BUCKET;
  /* Clamped so a row can never score its way into the NEXT group's band. A
     window seven days out is 10,080 minutes of shortfall, which at TIME_WEIGHT
     is 100,800 -- past the 100,000 a group is worth -- so a far-off row could
     sort below an unreachable one and split its own section header in two. */
  const within = Math.min(
    99999,
    shortfall * TIME_WEIGHT + drive * DRIVE_WEIGHT + (100 - Math.min(value, 100)) + conf
  );
  return row.group * 100000 + within;
}

/* ---- the one call the app makes --------------------------------------- */

/* Build the ordered feed. `at` is the arrival moment; `origin` is the user's
   position or null. Rows are grouped and sorted, and the caller renders them
   in order, starting a new section whenever `group` changes. */
/* A name reduced to what a person actually typed at it: case, accents and the
   punctuation nobody reproduces. "P.J. Whelihan's" is searched for as
   "pj whelihans", and "Cafe" has to find "Café". */
export function normalizeName(s) {
  return (s || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/* Every word of the query has to appear in the name, in any order. Substring
   rather than whole-word, so "powd" finds Black Powder Tavern before the name
   is finished -- the board is 169 venues and the answer should arrive while you
   are still typing. Order-free because "tavern black" is the same request. */
const tight = (s) => normalizeName(s).replace(/ /g, "");

export function matchesQuery(venue, query) {
  const q = normalizeName(query);
  if (!q) return true;
  /* Matched against the name with its separators removed, not with them turned
     into spaces. "P.J. Whelihan's" normalizes to "p j whelihan s", so a person
     typing the name as they say it -- "pj whelihans" -- matches nothing at all
     against the spaced form. Comparing token-by-token against "pjwhelihans"
     costs a rare match across a word boundary and finds the bar. */
  const name = tight(venue.name);
  return q.split(" ").every((word) => name.includes(tight(word)));
}

export function buildFeed(venues, at, { zone = null, filter = "all", sort = "soonest", origin = null, horizonDays = 7, query = "", planning = false, now = null } = {}) {
  const today = dateKeyOf(now || new Date());
  const test = (FILTERS[filter] || FILTERS.all).test;
  const q = normalizeName(query);
  const rows = [];

  for (const v of venues) {
    /* A search is a question about the whole board, not about the town you last
       picked. Honouring the town filter here is what would make searching for a
       bar you can see on the map return nothing, because you happened to be
       looking at a different town when you typed it. */
    if (zone && !q && v.zone_id !== zone) continue;
    if (q && !matchesQuery(v, q)) continue;
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
          v, deal: null, hit: null, miles, driveMin, hasOrigin: origin != null,
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
        v, deal, hit, miles, driveMin, hasOrigin: origin != null,
        confidence,
        ageDays: ageDays(deal, at),
        group: groupFor(hit, driveMin, { planning, today }),
        /* Measured against the real today, exactly as the header is. `dayAhead`
           is measured from the anchor, and the anchor moves when the reader
           picks a day -- so ordering on it would band rows under a heading they
           are not filed under. */
        dayIndex: dayOffset(hit, today),
      });
    }
  }

  rows.sort((a, b) => score(a, { sort }) - score(b, { sort }) || a.v.name.localeCompare(b.v.name));

  /* ONE ROW PER BAR. A venue used to hold exactly one deal, so a row per deal
     and a row per bar were the same thing. They stopped being the same on
     2026-09-02, when ingest/read_menus_llm.py began publishing a venue's happy
     hour AND its daily specials AND its food combos as separate deals: Sly Fox
     painted seven cards in a row, Sedona Taphouse two, and the board read as a
     bug to anyone scrolling it. The rows are already sorted, so the first one a
     bar has is the deal that answers "can I go now?" best -- that is the one the
     board shows, and the venue sheet still lists every deal it has. `others` is
     how many it is standing in for, so a card can say so.

     Two deals of the SAME type (both "happy_hour", say) are not two different
     answers -- they are two photos of the one thing a reader means by "the
     happy hour", so they are merged into a single row instead of one hiding
     the other: Kooma's drinks photo and food photo both read as `happy_hour`
     and a person asking "what's the deal" wants both lists, not whichever
     photo sorted first. A deal of a DIFFERENT type (a food_combo next to a
     happy_hour) is a genuinely different offer, so it still collapses into
     `others` rather than merging. */
  const seen = new Map();
  const one = [];
  for (const row of rows) {
    const key = row.v.id;
    const held = seen.get(key);
    if (held) {
      if (held.deal && row.deal && (held.deal.type || "happy_hour") === (row.deal.type || "happy_hour")) {
        if (!held.mergedFrom) {
          held.deal = { ...held.deal, items: [...held.deal.items] };
          held.mergedFrom = [held.deal];
        }
        held.deal.items.push(...row.deal.items);
        held.mergedFrom.push(row.deal);
        continue;
      }
      held.others += 1;
      continue;
    }
    row.others = 0;
    seen.set(key, row);
    one.push(row);
  }
  return one;
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

/* ---- the live overlay --------------------------------------------------

   Approved photo deals that are not in the built bundles yet. The app loads its
   static bundles first and patches these over the top, so an approval reaches a
   reader in seconds instead of waiting for a rebuild and a Pages deploy.

   The merge rule is the same one ingest/review_photos.py applies at approval
   time, and for the same reason: a menu is often several pages, and those arrive
   as separate submissions minutes apart, while a menu CHANGING arrives weeks
   later. Six hours tells those two cases apart with room to spare. */
export const PAGE_SET_HOURS = 6;

const submittedAt = (deal) => (deal.source || {}).submitted || "";
const isPhoto = (deal) => (deal.source || {}).kind === "photo";

/* Six hours tells the two COMMON cases apart, but it cannot tell them apart
   when they look the same: a second page of the same menu photographed the
   next day is, by the clock, indistinguishable from a menu that changed. So
   the reviewer is asked at the moment of approval, and the answer rides on the
   deal itself. Absent an answer this stays "replace", which is the safe end --
   a menu that changed and did not supersede leaves contradictory hours on a
   card, while pages that replaced each other lose items the next photo
   restores. */
const addsToBoard = (deals) =>
  deals.some((d) => (d.source || {}).merge === "add");

/* Every licence ID a venue answers to. A venue can hold more than one. */
function lidsOf(venue) {
  return [venue.lid, ...(venue.also_lids || [])].filter(Boolean).map(String);
}

/* Merge the overlay into the venues in hand.

   Returns the venues (mutated in place -- they are this session's own copies)
   and the zones that could not be applied because the venue is not loaded yet.
   That is not an error: a venue auto-published from a photo had no hours, so it
   is in no deals bundle, and the app has to fetch that zone's base first. */
export function applyOverlay(venues, overlay) {
  const byLid = new Map();
  for (const v of venues) for (const lid of lidsOf(v)) byLid.set(lid, v);

  let added = 0;
  const missingZones = new Set();

  for (const entry of (overlay && overlay.venues) || []) {
    const venue = byLid.get(String(entry.lid));
    if (!venue) {
      if (entry.zone_id) missingZones.add(entry.zone_id);
      continue;
    }
    // A deal already baked into the bundle we just loaded. This is why every
    // overlay deal carries its photo_id: it means the overlay never has to know
    // when the bundles were last built.
    const have = new Set(
      (venue.deals || []).map((d) => (d.source || {}).photo_id).filter(Boolean)
    );
    const fresh = (entry.deals || []).filter(
      (d) => !have.has((d.source || {}).photo_id)
    );
    if (!fresh.length) continue;

    if (!addsToBoard(fresh)) {
      let newest = "";
      for (const d of fresh) if (submittedAt(d) > newest) newest = submittedAt(d);
      const cutoff = new Date(
        new Date(newest).getTime() - PAGE_SET_HOURS * 3600 * 1000
      ).toISOString();

      venue.deals = (venue.deals || []).filter(
        (d) => !isPhoto(d) || submittedAt(d) >= cutoff
      );
    }
    venue.deals.push(...fresh);
    added += fresh.length;
  }

  return { venues, added, missingZones: [...missingZones] };
}

/* ---- "yes, this is still on" ------------------------------------------

   The strongest evidence a happy hour is real is not that a model read it off a
   photo, and it is not that Paul approved the read. It is that somebody stood
   in the bar this week and said so. This is that signal.

   A confirmation is keyed to the WINDOWS, not to the venue. If the hours
   change, the key changes and every old confirmation stops applying to them --
   which is the point. Confirming 4-6pm must never make 5-7pm look confirmed.

   The key is only ever produced here, sent to the Worker, and stored verbatim,
   so there is one implementation of it and nothing to keep in step. */
export function dealKey(deal) {
  const w = (deal.windows || [])
    .map((x) => `${x.dow}:${x.start}-${x.end}`)
    .sort()
    .join(",");
  return `${deal.type || "happy_hour"}|${w}`;
}

/* How many people it takes before we stop hedging. One stranger agreeing with
   a menu photo is already better evidence than the photo alone, so the bar is
   one -- but the count is always shown, because "3 people" and "1 person" are
   different things to the reader and we should not flatten them. */
export const CONFIRMS_TO_VERIFY = 1;

/* Fold confirmation counts onto the deals in place.

   It rewrites last_verified_at, which is deliberate: the decay ladder and the
   "checked N days ago" line both read that field, and a deal somebody stood in
   front of yesterday IS a deal checked yesterday. Anything else would age out a
   window we have better evidence for than anything else on the board. */
export function applyConfirmations(venues, confirms) {
  if (!confirms) return 0;
  let touched = 0;
  for (const v of venues) {
    for (const lid of lidsOf(v)) {
      for (const deal of v.deals || []) {
        const hit = confirms[`${lid}:${dealKey(deal)}`];
        if (!hit || !hit.n) continue;
        deal.confirmations = hit.n;
        if (hit.last && hit.last > (deal.last_verified_at || "")) {
          deal.last_verified_at = hit.last;
        }
        if (hit.n >= CONFIRMS_TO_VERIFY && deal.confidence !== "disputed") {
          deal.confidence = "verified";
          deal.verified_by = "patron_confirmation";
        }
        touched += 1;
      }
    }
  }
  return touched;
}

/* ---- the night-out layer: events -----------------------------------------

   What is on at a venue tonight, and for the next two weeks: a band, trivia,
   a seating. Served live by the Worker (/live/events.json) and patched onto
   venues the same way approved deals are. Additive, idempotent, and a failed
   fetch changes nothing on screen. See PLAYBOOK-NIGHT-OUT.md section 2 for
   why start, set length, cover and kitchen are the fields that matter. */

export const EVENT_KIND_LABEL = {
  live_music: "Live music",
  trivia: "Trivia",
  dj: "DJ",
  comedy: "Comedy",
  other: "Event",
};

/* Fold the overlay's events onto the venues in place. Keyed by event id, so
   applying twice is applying once. Returns how many landed. */
export function applyEvents(venues, overlay) {
  const byLid = new Map();
  for (const v of venues) for (const lid of lidsOf(v)) byLid.set(lid, v);
  let added = 0;
  const entries = (overlay && overlay.venues) || {};
  for (const [lid, list] of Object.entries(entries)) {
    const venue = byLid.get(String(lid));
    if (!venue) continue;
    const have = new Set((venue.events || []).map((e) => e.id));
    for (const ev of list || []) {
      if (!ev || have.has(ev.id)) continue;
      (venue.events ||= []).push(ev);
      have.add(ev.id);
      added += 1;
    }
    if (venue.events) venue.events.sort((a, b) => (a.date + (a.start || "")).localeCompare(b.date + (b.start || "")));
  }
  return added;
}

/* The venue's next event on or after `today` (YYYY-MM-DD), or null. */
export function nextEvent(venue, today) {
  for (const ev of venue.events || []) if (ev.date >= today) return ev;
  return null;
}

/* One line for a card: "Tonight · Rhythm & Blondes 7pm–10pm · $5 cover · kitchen open".
   Says only what the row says; an unpublished start is left out, not guessed. */
export function eventLine(ev, today) {
  if (!ev) return "";
  const parts = [];
  const days = Math.round((Date.parse(ev.date) - Date.parse(today)) / 86400000);
  let when;
  if (days === 0) when = "Tonight";
  else if (days === 1) when = "Tomorrow";
  else {
    const d = new Date(ev.date + "T12:00:00");
    when = DOW_SHORT[dowOf(d) - 1];
    if (days > 6) when += ` ${d.getMonth() + 1}/${d.getDate()}`;
  }
  parts.push(when);
  let what = ev.act || EVENT_KIND_LABEL[ev.kind] || "Event";
  if (ev.start) what += ` ${fmtClock(ev.start)}`;
  if (ev.start && ev.end) what += `–${fmtClock(ev.end)}`;
  parts.push(what);
  if (ev.cover_usd != null) parts.push(ev.cover_usd === 0 ? "no cover" : `${money(ev.cover_usd)} cover`);
  if (ev.kitchen_open === 1) parts.push("kitchen open");
  else if (ev.kitchen_open === 0) parts.push("kitchen closed");
  return parts.join(" · ");
}

/* The signup form's only client-side rule. The Worker re-checks it. */
export function validEmail(s) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(String(s || "").trim());
}
