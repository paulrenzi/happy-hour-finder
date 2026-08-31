/* PA legal validators -- a port of ingest/validate_pa.py, kept message-for-message
   identical to it.

   Acts 57 & 86 of 2024 constrain happy hour by statute, so anything failing here
   is a parsing bug or a stale record, not a venue breaking the law.

   There are now two implementations of this, which is a liability: the Worker
   auto-approves without Python anywhere in the loop, and Python still gates the
   bundle build. tests/test_validators_agree.py runs BOTH over the same corpus of
   deals -- every shipped deal plus the edge cases -- and fails if the two ever
   disagree, on the verdict or on the wording. Change one, change the other. */

export const MAX_HOURS_PER_DAY = 4.0;
export const MAX_HOURS_PER_WEEK = 24.0;

const BANNED = [
  /all[- ]you[- ]can[- ]drink/,
  /bottomless/,
  /free drink/,
  /two for one|2 for 1|2-for-1/,
  /unlimited/,
];
// Source order, for messages that name the pattern.
const BANNED_SRC = [
  "all[- ]you[- ]can[- ]drink",
  "bottomless",
  "free drink",
  "two for one|2 for 1|2-for-1",
  "unlimited",
];

const TYPES = new Set(["happy_hour", "daily_special", "food_combo"]);
const CATEGORIES = new Set([
  "draft", "bottle_can", "wine", "well", "call", "cocktail", "shot", "food",
]);
const CONFIDENCE = new Set(["verified", "likely", "unconfirmed", "disputed"]);
const KINDS = new Set(["venue_site", "roundup", "aggregator", "instagram", "photo"]);

/* Python's repr() for the values that reach these messages. Keeping the wording
   identical is what lets the agreement test compare the two implementations
   character for character -- and the first thing that test caught was this
   function: Python prefers single quotes but switches to double when the string
   contains an apostrophe and no double quote, which "Henny's Nirvana" does. */
function repr(v) {
  if (v === undefined || v === null) return "None";
  if (typeof v !== "string") return String(v);
  const body = v.replace(/\\/g, "\\\\");
  if (body.includes("'") && !body.includes('"')) return `"${body}"`;
  return `'${body.replace(/'/g, "\\'")}'`;
}

/* Python's %g: trims trailing zeros, so 4.5 stays 4.5 and 5.0 prints as 5. */
function g(n) {
  return String(parseFloat(n.toPrecision(6)));
}

function minutes(hhmm) {
  const [h, m] = hhmm.split(":");
  return parseInt(h, 10) * 60 + parseInt(m, 10);
}

function windowHours(w) {
  return (minutes(w.end) - minutes(w.start)) / 60.0;
}

/* Python's repr() of a dict, for the "malformed window" message. */
function reprWindow(w) {
  const parts = Object.keys(w).map((k) => `${repr(k)}: ${repr(w[k])}`);
  return `{${parts.join(", ")}}`;
}

export function validateDeal(deal) {
  const errs = [];

  if (!TYPES.has(deal.type)) errs.push(`unknown deal type ${repr(deal.type)}`);
  if (!CONFIDENCE.has(deal.confidence)) {
    errs.push(`unknown confidence ${repr(deal.confidence)}`);
  }

  const windows = deal.windows || [];
  if (!windows.length) {
    errs.push("no windows -- a deal with no time is not an answer to 'can I go now?'");
  }

  const perDay = new Map();
  for (const w of windows) {
    const hhmm = /^\d{2}:\d{2}$/;
    if (!hhmm.test(w.start || "") || !hhmm.test(w.end || "")) {
      errs.push(`malformed window ${reprWindow(w)}`);
      continue;
    }
    if (!(Number.isInteger(w.dow) && w.dow >= 1 && w.dow <= 7)) {
      errs.push(`dow out of range: ${w.dow}`);
    }
    // "24:00" is midnight, the latest a PA discount may legally run. An end at
    // or before the start means the window wraps into the next morning.
    if (minutes(w.end) > 24 * 60) {
      errs.push(`window extends past midnight: ${w.start}-${w.end}`);
      continue;
    }
    const hrs = windowHours(w);
    if (hrs <= 0) {
      errs.push(`window extends past midnight: ${w.start}-${w.end}`);
      continue;
    }
    perDay.set(w.dow, (perDay.get(w.dow) || 0) + hrs);
  }

  // daily_special may run open-to-close on one beverage type; the 4h/24h caps
  // are a happy_hour constraint only.
  if (deal.type === "happy_hour") {
    for (const [dow, hrs] of perDay) {
      if (hrs > MAX_HOURS_PER_DAY) {
        errs.push(`day ${dow}: ${g(hrs)}h exceeds the 4h/day cap`);
      }
    }
    let total = 0;
    for (const hrs of perDay.values()) total += hrs;
    if (total > MAX_HOURS_PER_WEEK) {
      errs.push(`${g(total)}h/week exceeds the 24h/week cap`);
    }
  }

  const text = [deal.fine_print || ""]
    .concat((deal.items || []).map((i) => i.label || ""))
    .join(" ")
    .toLowerCase();
  BANNED.forEach((pat, i) => {
    if (pat.test(text)) errs.push(`unlawful claim matched /${BANNED_SRC[i]}/`);
  });

  for (const item of deal.items || []) {
    if (!CATEGORIES.has(item.category)) {
      errs.push(`unknown item category ${repr(item.category)}`);
    }
    if (
      (item.price_usd === undefined || item.price_usd === null) &&
      (item.discount_pct === undefined || item.discount_pct === null) &&
      (item.amount_off_usd === undefined || item.amount_off_usd === null)
    ) {
      errs.push(`item ${repr(item.label)} has neither a price nor a discount`);
    }
  }

  const source = deal.source || {};
  if (!source.url && !source.photo_id) {
    errs.push("no source -- every deal must be auditable");
  }
  if (!KINDS.has(source.kind)) errs.push(`unknown source kind ${repr(source.kind)}`);

  if (source.kind === "roundup") {
    if (!source.outlet) {
      errs.push("roundup with no outlet -- the card must name who said it");
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(source.published || "")) {
      errs.push("roundup with no publish date -- recency cannot be gated");
    }
    if (deal.confidence !== "unconfirmed") {
      errs.push(`roundup at ${repr(deal.confidence)}: the tier caps at unconfirmed`);
    }
  }

  return errs;
}

/* PA allows at most 2 food+drink combo specials per day. */
export function validateFoodComboCount(dealsForVenue) {
  const errs = [];
  const perDay = new Map();
  for (const d of dealsForVenue) {
    if (d.type !== "food_combo") continue;
    for (const w of d.windows || []) perDay.set(w.dow, (perDay.get(w.dow) || 0) + 1);
  }
  for (const [dow, n] of perDay) {
    if (n > 2) errs.push(`day ${dow}: ${n} food combos exceeds the 2/day cap`);
  }
  return errs;
}
