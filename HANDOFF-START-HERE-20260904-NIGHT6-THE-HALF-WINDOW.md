# "No window" was three situations wearing one sentence

**Supersedes** `HANDOFF-START-HERE-20260904-NIGHT5-STRATEGY-AND-DOCS.md`
for what to read first.

## 0. Correction to NIGHT5, and it changes what to do next

NIGHT5 §2 says MadMacs and Slow Hand are unpublished because "neither venue's
own website states a day or a clock anywhere," and sends the next session to
Instagram/Facebook. **Both halves of that are wrong.**

Read off the raw HTML and PDF this session already had on disk in
`data/agent_reads/<lid>/` — no new fetches, no agent spend:

| venue | items banked | its own site states | missing |
|---|---|---|---|
| MadMacs (`DE40aae10689`) | 16 | `3:30 to 6:30 Bar Side & Bar Side High Tops` | **the days** |
| Slow Hand (`101307`) | 10 | `Tuesday through Friday. Bar prices, short list, pull up a stool.` | **the clock** |

Each publishes exactly the half the other lacks. Neither is a research dead
end; they are two *different* one-fact questions, and the cheaper one
(MadMacs' days) is a phone call, not a social-media hunt.

Also: **there are 4 stranded venues, not 2.** The other two are TGI Fridays
(`DE23baa43531` 4 items, `DE4bfeada154` 1 item) — `windows: []`, genuinely
nothing, and chain-parked. NIGHT5 counted only the actionable ones without
saying so.

**Instagram and Facebook are not reachable from here** — both venues' pages
are login-walled to `WebFetch` (checked). Whatever answers these two, it is
not a fetch.

## 1. Why the wrong claim was easy to make — and the fix

`build_bundles.py` prints the strand warning, and it said, for all four:

```
! 31 verified item(s) across 4 venue(s) were READ AND NEVER PUBLISHED
  -- no window means no deal to carry them: Slow Hand (10), TGI Fridays (4), MadMacs (16)
```

One sentence over three different situations. The half we already hold sits in
the read's `deals[].fine_print`, which **nothing read**. So the warning is now:

```
! 31 verified item(s) across 4 venue(s) were READ AND NEVER PUBLISHED -- no window means no deal to carry them.
    MadMacs (16 items) -- window evidence held: clock, no days
    Slow Hand (10 items) -- window evidence held: days, no clock
    TGI Fridays (4 items) -- window evidence held: neither
    TGI Fridays (1 items) -- window evidence held: neither
    Route a venue through data/agent_handread.json once its window is known; 'neither' needs a source, not a re-read.
```

`window_half_held()` in `ingest/build_bundles.py`, five tests in
`tests/test_ingest.py`. Case-insensitive on purpose — the same shouted-corpus
trap that blinded `ADDRESS_RE` is pinned by a test here. **Diagnostic only: no
bundle byte changed** (verified before and after).

## 2. Still not published, deliberately

Neither venue ships. A day without a clock is an unbounded window; a clock
without a day is every day. Either guess invents a claim the source did not
make. **A wrong item is worse than a miss** — these stay off the board until
someone supplies the missing half, and the route in is
`data/agent_handread.json` (write the window, omit `items`, and it adopts the
banked ones).

⚠️ A **web-search summary is not that source.** Searching Slow Hand returns a
confident "4 to 6 weekdays, $1 off beer, $5 wine" — which contradicts the
venue's own menu ($7 house wine, $3 High Life). It is the summariser trap
already on the books. Do not let one of these become a published window.

## 3. The open work

- **MadMacs — needs days only. Phone (302) 737-4800.** Cheapest yield on the
  board and it is now a single question.
- **Slow Hand — needs a clock only. Phone (484) 999-8638.**
- Thin-item towns: center_city (18 thin), phoenixville, newark_de (9 thin),
  exton_downingtown (8), remaining west_chester thin venues.
- `data/RESCRAPE-QUEUE.json`: **125** live deals under 5 items, corpus-wide.
- Paul's call, still open: drop James Street Tavern and Timothy's Riverfront
  Grill (confirmed no current happy hour)?

## 4. NIGHT5's §3 strategy question, with one datum added

It asked depth-first vs breadth-first without per-town yield stats. Nothing
here settles that, but it does argue for a third thing first: **the corpus
already holds partial evidence nobody is reading.** The half-window class was
invisible because a summary line flattened it, and it cost a session. Before
buying more reads, it is worth asking what else `fine_print` and the other
free-text fields already know that no report prints.

## 5. Verification

- `bash tests/run.sh` → **563** Python tests OK (was 558), node `fail 0`.
- `python ingest/build_bundles.py` → board unchanged: **371** deals, 48 zones,
  355 venues with a window; `git status` showed no bundle modified.
- `python tests/window_quote_check.py` → 371 published, 0 contradictions.
- Classifier checked against the raw source, not its own output: MadMacs'
  `happyhour.pdf` rendered and read (items only, no days), `hh_image.jpg` is a
  stock burger photo, `mainmenu.html` carries the clock; Slow Hand's
  `menu.html` Next.js boot state carries `"Tuesday through Friday"` and its
  only clocks are operating hours.

## 6. Standing rules, unchanged

Scoped runs only, one town at a time, never the corpus. "It is live" is one
command: `python tests/live_front_door.py <zone>` — and for a *removal*,
re-fetch the live bundle too. A wrong item is worse than a miss. Check
`git branch --show-current` before committing (repo is shared with Codex).
Check the **built bundle**, not a lane's own summary.
