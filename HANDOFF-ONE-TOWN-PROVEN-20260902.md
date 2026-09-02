# HANDOFF — one town proven end to end; the wall is REACH, and the instrument is Paul's minute
**2026-09-02, late.** Read this, then `ARCHITECTURE-MENU-INGEST.md` §"WILLOW GROVE /
HORSHAM — one town, proven end to end". Everything below is committed, pushed, and
live on `https://paulrenzi.github.io/happy-hour-finder/`.

---

## 🛑 THE STANDING RULE, IN PAUL'S WORDS

> **"We aren't doing big scrapes. You've failed at all of them. Prove it on a single town."**

No corpus runs. Ever. One town, scoped, finished on the live site, then Paul picks the
next one. West Chester is stand-alone and last. Robots obeyed. A web page is verified by
**running it in WebKit** with the town's own venue names — never by an HTTP 200.

---

## What is now true

**The model reads menus.** `ingest/read_menus_llm.py` sends every saved page and every
image transcript per venue and gets back `{kind, days, start, end, items, quote, heading}`.
The regex grammar in `extract_deals` is imported **only to refuse**. Every span is a
literal substring of the document, checked at write time and **re-checked by `build`
against the file on disk**. Daily specials ship to the card via `kind`.

**Willow Grove / Horsham, one town, one day:**

| | before | after |
|---|---|---|
| websites | 9 | **32** |
| photos | 0 | **34** |
| cards with hours | 0 | **11** |
| items on those cards | 0 | **83** |
| board, corpus-wide | 214 | **225** |

$1.68 for the photo+website pass. Live-verified in WebKit, 35 cards painted, 0 page errors.

🔑 **The photo call already had the websites and was discarding them.** The Places Text
Search is Pro-tier billed either way; the field mask now asks for `websiteUri`. That one
field is why 9 became 32 for no extra money.

---

## 🎯 THE NEXT THING, AND IT IS NOT CODE

**Paul owes one minute on a town, and until he spends it there is no denominator.**
`report_coverage` still prints *"0 confirmed rows — no denominator, no percentage"*.
Every coverage number to date was scored against misses that had already been patched
for it, which reads 100% by construction.

Worksheet: `HANDOFF-THE-MINUTE-ON-AMBLER-20260902.md`, list in
`data/ground_truth/ambler_upper_dublin.json`. Willow Grove works equally well and is
fresher. **Run blind → Paul spends one minute → count what he found that the run did not.**

---

## 🛑 The wall is REACH, not extraction

Ambler, blind: **6 of 15 venues returned zero pages**, and 14 of the 21 places Google
calls a happy hour there have **no website on file at all**. Corpus-wide: 2,787 venues,
791 with a website. A reader that is perfect cannot read a page that does not exist.

So the next *build* — after the minute — is reach, and the cheapest lever is already
proven: the photo pass returns a website for venues we had none for.

---

## Open, named, not done

1. **The name guard refuses apostrophe/spacing variants** — Richies vs Richie's, Magerks
   vs MaGerk's, Na Brasa vs NaBrasa. **4 of 9 refusals in this town**, and the live board
   paints *"Richie's Too"* and *"Richies Bar & Grill"* as two venues. Normalise
   punctuation before matching.
2. **`scratch/live_check.py` reads only the first 24 hours-unknown cards** and never
   clicks *Show more*, so it can call a venue missing that is on the board. It falsely
   reported Palz.
3. **A multi-deal venue's board row is the deal that starts earliest** — so Sly Fox reads
   *"Starts 11:30am, 1 item"* rather than its 3–6pm Appy Hour. **This is Paul's call**,
   not a defect: is the row "what starts first" or "the best deal"?
4. Three Willow Grove cards ship a window with **0 items** — those venues publish hours
   and no prices. That is honest, not broken.

---

## 🛑 Debugging lessons paid for today — do not re-learn these

- **A literal backspace byte is what `\b` becomes when an edit loses a backslash.** Inside
  `r"..."` it matches nothing and raises nothing, so the guard **stops existing silently**.
  Two were found: one new, one **long-shipping in `extract_deals.items_in()`**.
  🔑 **Never patch with a `<<'PY'` heredoc** — it eats backslashes and mangles CRLF. Write
  a patch script with the Write tool, spell a backslash `chr(92)`, patch line-by-line to
  preserve `\r\n`, assert `chr(8) not in s`, write `.new` + `os.replace`.
  `tests/test_menu_reader.py::NoStrayControlBytes` now fails the build on any of them.
- **`rm -rf ingest/__pycache__` before re-testing a patched module.** Stale bytecode cost
  a debugging cycle.
- **`vet()` takes a row and a document**, so the whole grounding half tests offline —
  16 cases, zero model spend. Add a case for every refusal you fix.
- **An instrument that reads `deals[:1]` was right only while a card held one deal.**
  `card_diff`, `lib.js` and `render_check` were all wrong the moment that changed.
- **A rule can be unreachable by construction** — `needy.py`'s "no items" clause had never
  fired because it read only `venues-<zone>.json`, which by definition holds the venues
  with no deal. 76 venues were invisible to every scoped run.

---

## The scoped recipe, in order

```
python ingest/needy.py --zone <zone>                 # -> run.lids
python ingest/reach_llm.py links --lids run.lids
python ingest/crawl_sites.py --lids run.lids --recrawl --render
python ingest/extract_menu_images.py --lids run.lids
python ingest/reach_llm.py verdict --lids run.lids
python ingest/read_menus_llm.py ask --lids run.lids   # the model reads the menus
python ingest/read_menus_llm.py build                 # re-grounds against disk
python ingest/fetch_venue_photos.py --zone <zone> --every-venue
python ingest/extract_deals.py && python ingest/build_venue_base.py && python ingest/build_bundles.py
bash tests/run.sh
python scratch/live_check.py <zone> "<Venue>" "<Venue>"   # AFTER pushing
```
