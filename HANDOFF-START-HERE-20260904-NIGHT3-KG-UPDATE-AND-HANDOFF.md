# Overnight session closeout — the simple number, and what's next — 2026-09-04

**Supersedes** `HANDOFF-START-HERE-20260904-NIGHT2-CAPS-DRINKFOOD-RESCRAPE.md` for
what to read first; that one's §1–§4 detail (the ALL CAPS fix, drinks-before-food,
the two amount_off_usd bugs, and the venue-by-venue re-read results) is still current
and not repeated here.

## 0. The number Paul asked for

**2 brand-new happy-hour menus went live this session** that had none before:

- **Argilla Brewing Co. @ Pietro's Pizza** (newark_de) — 3 items, Thursday 4–10pm
- **Kid Shelleen's - Trolley Square** (wilmington) — 5 items, crossed the "thin"
  line (was 1 roundup item)

Plus **2 existing published venues got real items back** that a bug was silently
dropping (not new menus, but real money-relevant recoveries):

- **Iron Hill Brewery & Restaurant** (wilmington) — 1 → 4 items
- **Sly Fox** (phoenixville) — +2 items on its existing block

**Site-wide, this session: 264 → 265 venues with items, 1,928 → 1,943 items
(+15), the exhausted-agent-read backlog 23 → 15, the thin/blank rescrape queue
219 → 125+94≈down by several** (see README's live table for the current count,
it's kept current rather than restated here).

Three more real menus were read and paid for but are **not yet live** — see §2.

## 1. Architecture/findings worth remembering (added to KG + README this session)

**A schema field has to be grepped to every reader, not just the one you're
looking at.** `amount_off_usd` was added to the agent lane's prompt schema
2026-09-04 morning (commit `1d22a26`) but a second, independent function —
`extract_prices_llm.verify()`, reused by `extract_menu_images.items_from()`
for menu-photo/PDF reads — had its own copy of the same three-field
(`price_usd`/`discount_pct`/`amount_off_usd`) check and never learned the
field. Two misses of the same field in one session is not a coincidence;
it's what happens when nobody greps for every place a check like this is
duplicated. Fixed both this session (commits `1d22a26`, `aa7d3f0`). **If a
schema field changes again, `grep -rn "price_usd.*discount_pct" ingest/` before
calling it done.**

**Most of the blank/thin backlog is not a scraper bug.** Worked wilmington's
full 14-venue thin list this session: 1 of 14 crossed the 5-item line. The
rest confirmed genuinely short real-world menus, or (2 venues — James Street
Tavern, Timothy's Riverfront Grill) a stale roundup claim with **no current
happy hour at all** — those are publishing something untrue and should
probably come off the board; that's Paul's call, not made yet. **Read this as
the finding, not a disappointing yield**: an `agent_read`-tagged thin venue
already had a real agent read the real page. Chasing this list town-by-town
mostly re-confirms it rather than finding bugs — same signal as the
exhausted-23 chain-site pattern below.

**Chain-style venues (Darden, franchise groups) keep exhausting the agent's
turn budget without a menu.** Crooked Hammock Brewery re-confirmed exhausted
tonight even at the raised `HHF_MAX_TURNS=28`, the same shape as Deer Park
Tavern last session. Two strikes on the same site pattern in a row is a real
signal: treat further chain-site spend as low-probability until something
changes (a different reading strategy, not just more turns).

**Full detail on all of the above, plus the item-gap history this supersedes
in spirit:** `project_hhf_the_item_gap_is_the_standing_failure.md` in the
Claude memory store now carries a 2026-09-04 update note; new memory
`feedback_hhf_a_schema_field_must_be_grepped_to_every_reader.md` records the
duplicate-verify()-function lesson as a standalone, reusable rule (it isn't
HHF-specific — any repo with a prompt-driven schema and more than one reader
of it has this exposure).

## 2. Real, paid-for menus banked but NOT yet live — free money for next session

No new agent spend needed — these just need the routing worked out:

| venue | zone | items | why it's not live |
|---|---|---|---|
| MadMacs | newark_de | 16 | Read explicitly says "No days of the week are printed" — no window, so nothing to publish. Needs someone to find the missing day off-site (Instagram/Facebook), not the main site. |
| Shellhammer's Bar and Grill | newark_de | 7 | Real menu, but its existing deal is `menu_read_llm`-typed (doesn't qualify for direct merge) and this read's clock/window wasn't captured cleanly enough to hand-write an `agent_handread.json` record without re-checking the site. |
| Slow Hand | west_chester | 10 | Blocked by the bug in §3, not a data-quality issue on the read itself. |

## 3. Found, not fixed: a stale venue name may be showing a closed business

`101307` (west_chester, 30 N Church St) ships on the live board as
**"Serum Kitchen & Taphouse"**, sourced from an older `menu_read_llm` deal (8
items). `venue_base.json` and the PLCB record both say **Slow Hand** at that
address. This means the board may currently be showing a closed business's
hours and menu under its old name to a customer standing outside — worse
than the thin-item problem this session was otherwise chasing. **Needs a
person to check the address before either merging Slow Hand's fresh 10-item
read in or touching this lid at all** — not fixed blindly, flagged both
sessions running now.

## 4. Verified live this session

`tests/live_front_door.py wilmington` and `newark_de` — both confirmed
`LIVE — the built bundle is on the site and paints`, 39/39 and 32/32 named
venues respectively, run just before this handoff was written (after the
last push). `bash tests/run.sh` green throughout (552 Python tests + node
suite). All commits pushed; `git status` clean on `master`.

## 5. What's worth the next session's money, unchanged from NIGHT2, still true

1. §2 above — free, no new spend, real menus sitting unused.
2. center_city (18 thin), phoenixville (remaining), newark_de (9 remaining
   thin), exton_downingtown (8), west_chester (8 remaining thin).
3. Only then, reconsider spend on the remaining chain sites — two
   confirmed-exhausted strikes in a row (Deer Park Tavern, Crooked Hammock)
   is a real pattern now, not noise.
4. Paul's call, not automated: should James Street Tavern and Timothy's
   Riverfront Grill come off the board (confirmed no current happy hour)?
   Should the §3 name-collision lid be resolved by a person visiting/calling?

## 6. Standing rules, unchanged

Scoped runs only, one town at a time, never the corpus. "It is live" is one
command: `python tests/live_front_door.py <zone>`. A wrong item is worse than
a miss. Check `git branch --show-current` before committing (repo is
shared). Check the **built bundle**, not a lane's own summary, before
believing a read reached the board.
