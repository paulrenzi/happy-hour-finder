# The agent lane reads a town and cannot publish it — 2026-09-03, night

**Supersedes `HANDOFF-START-HERE-20260903-THE-AGENT-IS-THE-SCRAPER.md`.**
Everything in that document still stands; this one is what the first whole-town
run did to it.

## 0. Paul, verbatim

> "doing a blanket run without taking into account what's already there is
> wasteful"

> "it just sounds like you're telling me it doesn't work yet."

Both correct. The lane **reads** — proven on a second venue now, from a PDF the
crawl never found. It **cannot publish** what it reads for a venue that has no
window, and that is one decision away, not one bug away.

## 1. What happened, shortest version

A blanket `--zone newark_de` run was started over all 173 websites. Paul stopped
it at 4 venues. The tiers were measured, `--tier` was built, tier A was run,
two defects were found and fixed, and the one venue tier A found **did not reach
a card**.

| | |
|---|---|
| tier A read | 10 venues, ~$4 |
| returned items | **1** — Lefty's Alley & Eats, 10 items off a happy-hour PDF |
| published | **0** |
| genuinely no published price | 7 (five of them Applebee's — category names, no prices) |
| turns exhausted | 2 (LongHorn, Cheddar's — Darden chain sites) |

## 2. 🛑 THE BLOCKER — the one thing to settle first

`build_bundles.py` attaches the agent sidecar **inside** `for deal in
venue.get("deals", [])` (line ~609). A venue with **no deterministic window has
no deal**, so the loop never runs and verified items are stranded with no error
anywhere:

```
data/deals_agent.json          DE4798b4126a -> 10 items
web/data/venues-newark_de.json Lefty's Alley & Eats -> "deals": []
```

The Greene Turtle proof did not expose this because that venue already carried a
regex-lane window. **The lane is proven to read and unproven to publish.**

**Paul's call, three options:**

- **a.** a venue with no window may carry the agent's **items** on a
  window-less card (the board already ships 3,097 venues with no window)
- **b.** it may take the agent's **window** as well — Lefty's reads
  **Mon–Fri 15:00–19:00** off the PDF, and that reading is sitting in
  `data/agent_reads.json["DE4798b4126a"].deals[0].windows`, unpublished
- **c.** neither — items ship only where a deterministic window exists, and the
  agent lane's real yield is smaller than the read count suggests

Nothing was published from the agent's windows. That rule was not touched.

**The human minute, if he wants it before deciding:**
`https://iloveleftys.com/wp-content/uploads/2026/06/Happy-Hour-menu-REV08-1-1.pdf`
against — Potstickers $10, ½ lb Peel & Eat Shrimp $10, Signature Nachos $10,
Chicken & Waffles $11, Enchiladas $11, Bavarian Pretzel $12, Birria Tacos $12,
Meat Lover's Stromboli $14, Domestic Drafts $3, Crushes & Signature Cocktails $9.

## 3. What was built — selection by evidence already held

`population()` took **every website in the zone** at one price. The numbers to
order it by were already on disk in `crawl_hits.json`. newark_de, 173 websites,
**153 needy** (`ingest/needy.py`: a website and no items on the card):

| tier | what we already hold | count | blind cost |
|---|---|---|---|
| **A** | the crawl **captured a menu image**, never read | 10 | ~$3.50 |
| **B** | the crawl **quoted happy hour** on a page | 25 | ~$9 |
| **C** | a website and no hh-shaped evidence at all | 118 | ~$41 |

Tier C is **77% of the spend** aimed at exactly the population the reach
measurement already showed publishes no price anywhere.

`--tier A|B|AB|C` and `--needy` now order a run; `--tier` implies `--needy`, so
a blanket selection is not reachable by accident.

> 🔑 **Run the tier, measure its hit rate, let that decide whether the next tier
> is worth buying.** "Prove it on one town for a dollar" applies to the
> SELECTION as much as to the town.

## 4. Two defects fixed (both were invisible)

**1. A non-zero exit is not an empty result.** `claude -p` exits **1** when a
session runs out of turns — and still prints its **whole JSON envelope on
stdout, including what it spent**. LongHorn and Cheddar's read as
`RuntimeError: claude -p exited 1: ` with an **EMPTY stderr** (that is the tell).
$0.53 and $0.59 of real model time each, filed as `error`, counted in the run
total as **$0.00**, and re-read at full price on every later run *because the
lane retries errors*. The same ending was bought three times before it was
caught. Now stdout is parsed first; only a run that printed nothing parseable is
an error; a turn-exhausted read is `kind: "exhausted"`, carries its `cost_usd`,
and is **never retried** — a retry at the same `--max-turns` buys the same ending.

**2. The run summary counted the file, not the run** — "2 venue(s) with items"
on a run that found one. Now `N of M venue(s) read returned items (K on file)`.

## 5. Also open, smaller

- **A fixed-dollar discount has no home in the schema.** The gates refused
  "Craft & Select — **$2 off**" and "Wine by the Glass — $3 off": an item needs
  exactly one of `price_usd` / `discount_pct`, and "$2 off" is neither. Two of
  Lefty's twelve reads died on it. A real gap, not a bad read.
- **Chain sites burn turns.** LongHorn and Cheddar's spent 15 turns wandering
  Darden location pages and returned nothing. If they should be read, raise
  `MAX_TURNS` for them deliberately.
- **`MEMORY.md` is at 26KB against its own 17KB limit** and needs a prune.

## 6. NEXT SESSION — start here

1. **Settle §2 with Paul.** Nothing else in this lane is worth doing first: it
   decides whether a town's reads can ever become cards.
2. If **a** or **b**: change `build_bundles.py` so a venue with no deal can
   receive the agent sidecar, rebuild, and check **the built bundle** — the
   board diff, not the lane's summary. Then push and
   `python tests/live_front_door.py newark_de`.
3. Then tier **B** on newark_de (25 venues, ~$9) and compare its hit rate to
   tier A's 1-in-10 before anyone pays for tier C.
4. Decide, with the tier A + B numbers in hand, whether tier C is ever worth
   buying — or whether the reach finding already answered that.

## 7. Standing rules — unchanged

- Scoped runs only, one town at a time, never the corpus.
- "It is live" is one command: `python tests/live_front_door.py <zone>`.
- A wrong item is worse than a miss. The grounding gate and the reviewer stay.
- Never write a backslash escape through a bash heredoc — use Write/Edit.
- 🛑 A step done by hand to diagnose a pipeline is an **autopsy, not a test**.
- 🛑 **Check the built bundle, not the lane's own summary.** The lane said it
  succeeded; the board was byte-identical. That zero-byte diff was the finding.

## 8. Where it is written

- `ARCHITECTURE-MENU-INGEST.md` — *"THE AGENT IS THE SCRAPER"* section: the
  selection tiers, and a new *"Debugging the lane: three failures that all
  looked like nothing"*.
- `README.md` — the four commands, `--tier`, and the known gap, stated plainly.
- `umbrella-arcades/Knowledge-Graph.md` — the 2026-09-03 night entry, at top.
- Memory: `project_hhf_the_agent_is_the_scraper.md`,
  `feedback_a_non_zero_exit_is_not_an_empty_result.md`.
