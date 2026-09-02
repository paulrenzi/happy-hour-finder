# Happy Hour Finder — the model reads menus now; the blind town says REACH is the wall (2026-09-02, late)

**Read this first, then `ARCHITECTURE-MENU-INGEST.md` §"THE MODEL READS MENUS —
built 2026-09-02", then §"Scoped runs" for the recipe as it now stands.**
Supersedes `HANDOFF-THE-MODEL-READS-MENUS-20260902.md`; both of its numbered
steps are done.

---

## In one sentence

**A model now reads whole pages and whole menu transcripts and returns the deals
on them — kind, days, clock, items, each grounded in a quote checked twice — so
the "regardless of format" hole in EXTRACTION is closed; and the first town run
blind says the wall has moved to REACH, because six of fifteen venues returned
no page at all and fourteen of the twenty-one places Google calls a happy hour
in that town have no website on file.**

## What is owed to Paul, first thing

🎯 **One minute on Ambler / Upper Dublin.** The town was picked because nobody
had opened it and none of its zips overlap a worked zone. The run is finished
and the baseline is recorded, and the number is only honest if it is measured
against what you find, not against what we patched for ourselves. The worksheet:

| lid | name | card? | pages we hold | website on file |
|---|---|---|---|---|
| 53260 | Bar 31 | no | **0** | bar31.net (SSLError) |
| 47025 | Bridgets Steakhouse | no | 4 | bridgetssteak.com |
| 55311 | Fireside Bar and Grill | **YES** | 2 | firesidebarandgrille.com |
| 65679 | Forest & Main Pub | no | 3 | (shopify) |
| 93677 | Geronimo's Peruvian Cuisine | no | 3 | geronimosambler.com |
| 23492 | Guiseppes Restauant | no | **0** | giuseppesofambler.com (ConnectTimeout) |
| 132986 | Gypsy Blu | no | 1 | gypsyblurestaurant.com |
| 36839 | Halligan's | no | 0 | **none on file** |
| 68578 | Harrys Blue Bell Tap Room | no | 0 | **none on file** |
| 106059 | Lascala's Fire | no | 0 | **none on file** |
| 111570 | Redstone American Grill | no | 0 | **none on file** |
| 103160 | Springhouse Hdk | no | 0 | **none on file** |
| 126532 | T/A the Fort Kitchen and Bar | no | 0 | **none on file** |
| 59244 | The Jarrettown | no | 0 | **none on file** |

Also on the board and not in Google's list: **Well Crafted Beer Company** (3
deals). Eight more names Google returned are not PLCB licensees we hold at all —
KC's Alley, Cantina Feliz, Spring House Tavern, Roberts Block, 152 Public House,
The Stotesbury, The Highland Pub, Rooster's Glenside.

The count of what you find that the run did not **is the baseline**, and it is
the first one in this repo that was not scored against its own patched misses.
Record it in `data/ground_truth/ambler_upper_dublin.json` (`confirmed: true` +
the URL that states it).

## What was built

`ingest/read_menus_llm.py` — `ask` puts every saved page and every menu-picture
transcript of a scoped venue in front of a model and takes back
`{kind, days, start, end, items:[{label,price,category,evidence}], heading,
quote}`; `build` re-checks every quote against the file on disk and writes
`data/deals_menus.json`, which `build_bundles` merges above the extractor and
below a person. The grammar in `extract_deals` is now imported **only to
refuse**.

- **Daily specials are on the card**, as `kind`. Sly Fox ships its Appy Hour
  plus Wednesday growlers, Wednesday cheesesteak+pint, Thursday burger+pint,
  Saturday mystery pitcher and Sunday $2-off Bloody Marys — seven deals, each
  with the venue's own heading.
- **A daily special usually states no clock**, so it may ground one in a second
  span of the same page (the venue's own hours line). A happy hour may not.
- 🛑 **The guard cost a $50 prime rib.** The first run returned William Penn
  Inn's dinner PDF as three fully-grounded daily specials at $35–$50. Correct on
  every check, and the heading says "WILLIAM PENN INN PRIX FIXE". The model now
  returns the venue's own heading and `NOT_A_DEAL_RE` refuses a meal service
  whatever `kind` it claims. It caught Bridget's "Pre-Fixe Dinner Menu" next run.

Three instruments were broken by a venue holding more than one deal and are
fixed in the same commit: `needy.py` (its "no items" clause had **never**
selected anything — 76 of 214 deal-bearing venues were unreachable),
`card_diff` (read `deals[:1]`), and `lib.js` (one board row per DEAL — Sly Fox
painted seven cards in a row; it is one row per bar now, the sheet still lists
them all).

## State of the repo and the site

- `origin/master` = `531ef54` + this docs commit. Full gate green: 372 unit,
  64 node, parse/render/search/picker/card.
- Live in WebKit, with each town's own names, no page errors:
  `phoenixville` — Sly Fox, Sedona, Revival, Rivertown, il Granaio, Valley Forge
  all painted; `ambler_upper_dublin` — Fireside and Well Crafted.
  🛑 `live_check.py` with no names defaults to KoP names and prints FAIL.
- Ambler has a photo for **27 of its 35 licensees**, deals or not
  (`fetch_venue_photos.py --from-board --zone Z --every-venue --spend`).

## Next, in this order

1. **Paul's minute on Ambler**, then the baseline number. Nothing else is worth
   sequencing before it exists.
2. **REACH, which is what the blind town measured.** Six of fifteen sites
   returned nothing to a plain `requests` fetch (403, SSL, two timeouts) while
   they open fine in a browser — the render tier exists and the links/crawl
   stages do not use it on a hard failure. And a venue with no website on file
   is invisible to every reader we have: 14 of 21 in this town. Google Places
   already handed us a `websiteUri` for several of them and it was only stored
   in the ground-truth row, never promoted to the licensee.
3. **A judgement call for Paul.** The board row for a multi-deal venue is the
   deal that starts earliest, so Sly Fox reads "Starts 11:30am, 1 item" rather
   than its 3–6pm Appy Hour. Honest, and possibly not what a person scanning
   wants. Say which and it is a one-line change in `lib.js`.
4. Then the next blind town, and only then a second pass over a worked one.

## Standing constraints — unchanged

No full-corpus runs; West Chester last, stand-alone; robots obeyed; this repo's
own `.env`; `.new` + `os.replace`; verify in WebKit at the live URL with the
town's own names; a wrong item is worse than a missing one; the model is
grounded in code, never a source.
