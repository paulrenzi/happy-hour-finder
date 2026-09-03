/* Read a submitted menu photo, in the Worker, the moment it arrives.

   This is the same job ingest/extract_photo_deals.py does on Paul's PC through
   the `claude` CLI, moved to where it can run without him: same prompt, same
   grounding rule, same PA validators, same record shape. The CLI path stays --
   it costs nothing on the Max subscription, and it is what runs when no API key
   is configured here. A Max subscription is licensed for a person's own
   interactive use, not as a public site's backend, which is why THIS path is an
   API key and not a copied credentials file.

   Nothing here publishes. It writes a proposal onto the row; whether that
   proposal reaches the site is decided by the auto-approve gate in index.js,
   which is deliberately narrow, or by a person on the admin page. */

import { validateDeal, validateFoodComboCount } from "./validate_pa.js";

const CATEGORIES = [
  "bottle_can", "call", "cocktail", "draft", "food", "shot", "well", "wine",
];

/* Kept in step with PROMPT in ingest/extract_photo_deals.py. The only
   difference is the first line: the CLI is pointed at a file on disk, and the
   API is handed the bytes. */
const PROMPT = `You are transcribing a happy hour menu for a listings site that publishes only
what the venue itself put in writing.

You are a reader, not an author. Every price, discount, time and item you report must be
printed on the menu in the photo. If the menu says "select drafts", say select
drafts, not "all drafts". If a price is smudged or cut off, leave it out. If the
days are not printed, return no windows rather than guessing the usual ones. An
omission costs us one deal; an invention costs us the reader's trust, and the
reader is standing in a bar holding their phone.

Transcribe the whole menu into \`transcript\` first, verbatim. Then read the deals
back out of that transcript, and set each item's \`quote\` to the exact substring
you took it from. A quote that is not character-for-character inside the
transcript is discarded automatically, so do not paraphrase it.

Times are 24-hour "HH:MM". Days are 1=Monday through 7=Sunday. Midnight at the
end of a window is "24:00".

Pennsylvania caps happy hour at 4 hours a day and 24 a week, and forbids
all-you-can-drink, two-for-one, bottomless and free-drink offers. If the menu
advertises one of those, transcribe it as printed and let the validators handle
it -- do not clean it up.

Reply with ONE JSON object and nothing else. No prose, no code fence.

{
  "is_menu": true or false -- true only if this shows a printed or written menu,
             board or sign listing food or drink specials,
  "rejection_reason": "if is_menu is false, one sentence on what it actually
             shows; otherwise an empty string",
  "concerns": ["anything a human reviewer must see before this is published:
             identifiable people, a receipt or card number, anything unrelated
             to a menu. Empty list if none."],
  "legible": true or false -- false if the menu is blurred, cropped or angled
             badly enough that you are reading any price or time from context
             rather than from the pixels,
  "venue_name_on_menu": "the venue name printed on the menu, verbatim, or \\"\\"",
  "transcript": "every word visible on the menu, verbatim, in reading order",
  "deals": [
    {
      "type": "happy_hour" | "daily_special" | "food_combo",
      "windows": [{"dow": 1-7, "start": "16:00", "end": "18:00"}],
      "items": [
        {
          "category": one of: CATEGORIES,
          "label": "short description as printed",
          "price_usd": number or null,
          "discount_pct": number or null,
          "amount_off_usd": number or null -- use this only for a fixed-dollar
             discount explicitly printed as "$2 off"; exactly one of the three
             amount fields may be non-null,
          "quote": "the exact substring of transcript this came from"
        }
      ],
      "fine_print": "any conditions printed on the menu, or \\"\\""
    }
  ]
}`.replace("CATEGORIES", CATEGORIES.join(", "));

function base64(buf) {
  const bytes = new Uint8Array(buf);
  let s = "";
  // Chunked: String.fromCharCode(...bytes) blows the argument limit on a photo.
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

/* Whitespace and case only. A quote check that also ignored punctuation would
   pass "$5 drafts" against "no $5 drafts", which is the point of checking. */
function norm(text) {
  return (text || "").replace(/\s+/g, " ").trim().toLowerCase();
}

/* Drop every item whose quote is not in the transcript. The model is a reader,
   not an author: a price nobody printed is the failure that matters most. */
export function ground(read) {
  const transcript = norm(read.transcript);
  const kept = [];
  const dropped = [];
  for (const deal of read.deals || []) {
    const items = [];
    for (const item of deal.items || []) {
      const quote = norm(item.quote);
      const values = [item.price_usd, item.discount_pct, item.amount_off_usd]
        .filter((value) => value !== undefined && value !== null);
      const off = Number(item.amount_off_usd);
      const amount = Number.isFinite(off) && off > 0 && off <= 99
        ? String(off).replace(".", "\\\\.") : "";
      const offWritten = amount && new RegExp(
        `(?:\\$\\s*${amount}(?:\\.0{1,2})?\\s*off\\b|off\\s*\\$\\s*${amount}(?:\\.0{1,2})?\\b)`, "i"
      ).test(quote);
      if (quote && transcript.includes(quote) && values.length === 1 &&
          (item.amount_off_usd === undefined || item.amount_off_usd === null || offWritten)) {
        const clean = {};
        for (const [k, v] of Object.entries(item)) if (v !== null) clean[k] = v;
        items.push(clean);
      } else {
        const why = !quote || !transcript.includes(quote) ? "quote not in the transcript"
          : values.length !== 1 ? "needs exactly one price or discount"
          : "amount off not written as an OFF discount in the quote";
        dropped.push(`${JSON.stringify(item.label)}: ${why}`);
      }
    }
    const next = { ...deal, items };
    // A window with no priced items is still an answer to "can I go now?".
    if (next.items.length || (next.windows || []).length) kept.push(next);
  }
  return { kept, dropped };
}

/* Shape the model's deals like every other deal in the corpus. Mirrors
   to_records() in ingest/extract_photo_deals.py. */
export function toRecords(deals, sub, today) {
  return deals.map((deal) => {
    const rec = {
      type: deal.type || "happy_hour",
      windows: deal.windows || [],
      items: deal.items.map((i) => {
        const { quote, ...rest } = i;
        return rest;
      }),
      confidence: "unconfirmed", // a photo is never self-verifying
      last_verified_at: today,
      verified_by: "photo_submission",
      source: { kind: "photo", photo_id: sub.id, submitted: sub.submitted_at },
    };
    if (deal.fine_print) rec.fine_print = deal.fine_print;
    return rec;
  });
}

/* Everything after the model has spoken: grounding, then the PA validators,
   then the proposal the admin page and the auto-approve gate both read. Shared
   with the CLI path so the two produce the same object. */
export function proposalFrom(read, sub, today) {
  if (!read.is_menu) {
    return {
      is_menu: false,
      reason: read.rejection_reason || "",
      concerns: read.concerns || [],
      deals: [],
    };
  }
  const { kept, dropped } = ground(read);
  const publishable = [];
  const rejected = [...dropped];
  for (const rec of toRecords(kept, sub, today)) {
    const errs = validateDeal(rec);
    if (errs.length) rejected.push(`${rec.type}: ${errs[0]}`);
    else publishable.push(rec);
  }
  let finalDeals = publishable;
  for (const err of validateFoodComboCount(publishable)) {
    rejected.push(err);
    finalDeals = [];
  }
  return {
    is_menu: true,
    venue_name_on_menu: read.venue_name_on_menu || "",
    concerns: read.concerns || [],
    legible: read.legible !== false,
    transcript: read.transcript || "",
    deals: finalDeals,
    rejected,
  };
}

/* One API call over one photo. Returns the parsed JSON object the prompt asks
   for, or throws with something a human can act on. */
export async function readPhoto(env, bytes, contentType) {
  const model = env.VISION_MODEL || "claude-sonnet-5";
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model,
      max_tokens: 4096,
      messages: [
        {
          role: "user",
          content: [
            {
              type: "image",
              source: { type: "base64", media_type: contentType, data: base64(bytes) },
            },
            { type: "text", text: PROMPT },
          ],
        },
      ],
    }),
  });
  if (!res.ok) {
    throw new Error(`anthropic ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  const body = await res.json();
  const text = (body.content || []).map((c) => c.text || "").join("");
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) throw new Error(`no JSON object in reply: ${text.slice(0, 200)}`);
  return JSON.parse(m[0]);
}
