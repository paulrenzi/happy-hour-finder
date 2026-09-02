# HANDOFF — start here next session (written 2026-09-02, end of day)

**This is the current entry point.** It supersedes
`HANDOFF-DELAWARE-AND-THE-QUOTE-GUARD-20260902-LATE.md`, whose §1 is finished
and whose §4a/§4b are done.

---

## 0. Where things stand, in one paragraph

Delaware landed. All four unfinished zones crawled, the pipeline ran end to end,
and every one of them is verified LIVE by `live_front_door.py`. The board is
**326 published deals across 44 zones, 3,412 listings, 309 with a published
window**, with 0 windows contradicting their own quote. Two UI defects were
fixed on real evidence rather than on taste: two genuinely different Red Robins
in Newark were painting one indistinguishable card, and the arrival-time slider
— spec'd since day one, green in every test — was confusing enough that Paul
asked for it gone. **Nothing is mid-flight. No crawl is running.**

---

## 1. What is live right now

```
python tests/live_front_door.py newark_de             ->  LIVE, 22 of 22
python tests/live_front_door.py hockessin_greenville  ->  LIVE,  5 of 5
python tests/live_front_door.py new_castle_de         ->  LIVE,  5 of 5
python tests/live_front_door.py middletown_de         ->  LIVE,  3 of 3
python tests/live_front_door.py west_chester          ->  LIVE, 19 of 19
bash tests/run.sh    ->  527 python + 64 node, 8/8 PA validators, 0 fail
                         board paints 310 cards and no bar twice
```

Delaware went 265 -> 294 venues-with-a-deal on the crawl; the board ships 326.

| zone | listings | with hours |
|---|---|---|
| newark_de | 194 | **22** (was 2) |
| hockessin_greenville | 92 | 5 |
| new_castle_de | 85 | **5** (was 0) |
| middletown_de | 58 | **3** (was 0) |

**Roundups:** `montco.today` and `outandaboutnow.com` were the two unproven
outlets in the last handoff's §4b. **Both crawl fine.** MONTCO returns 403 to a
plain fetch and that turned out to be a plain-fetch artifact, not a block. 30/30
articles dated, 96 venue mentions, 23 venues with a roundup deal. The 64
refusals spot-check as correct — address lines and prose with no clock in them.

---

## 2. 🛑 THE TWO ARCHITECTURE FACTS FROM TODAY

### a. A `web/` edit ships NOTHING until `build_bundles.py` restamps `sw.js`

`web/sw.js` carries `const CACHE = "hhf-<date>-<n>-<hash>"` and **that hash is
computed over the shell files.** The cache name is the *only* eviction trigger —
`activate` deletes caches whose name differs. So a commit that changes
`index.html`, `app.js` or `styles.css` **without re-running the build** pushes a
shell the installed PWA will never fetch: it keeps serving the old `app.js` from
its own precache, indefinitely.

`tests/run.sh` catches it (`ServiceWorkerCache.test_the_cache_name_matches_the_bundle_that_shipped`,
message: *"web/sw.js was not stamped by the last build_bundles run"*), which is
the only reason this is a footnote and not an outage. It fired today.
🔧 **Never hand-edit `sw.js` — re-run the build**, and confirm the deploy by
fetching the live `sw.js` and grepping for the new cache name.

### b. Two real branches must say which one they are

`collapse_name_collisions()` deliberately refuses to merge two genuine bars
("merging two real bars is far worse than listing one twice") — and that was
right, but it left the READER the harder half. Newark, DE ships a Red Robin on
Pulaski Hwy and another on W Main St, three miles apart, and the two cards were
identical down to the window.

New in `ingest/build_bundles.py`: **`name_the_surviving_branches()`** — whatever
name collision *survives* the merge is a branch by definition, and gets the one
thing that separates it, its street (`street_of()`). 106 rows now carry one.
Both card renderers in `web/app.js` print it on the zone line.

Two details worth not undoing:

- 🛑 **A label that would repeat is not applied.** Two Dandan rows at one door
  (`Ste 4, 100 Sugartown Rd` and `100 Sugartown Rd`) would have got two
  different labels for one building. A street printed twice tells a reader less
  than no street. Unit clauses are stripped leading AND inline; a test pins it.
- 🔑 **`tests/render_check.py` BUILDS the same label rather than agreeing with
  it by string literal.** The first fix broke the gate silently, because the DOM
  key carried the branch and the bundle key did not. Producer and consumer
  agreeing by string equality is how a gate goes blind.

---

## 3. The arrival-time slider is gone

Paul: *"remove this arriving by search filter bar. its confusing as hell."*

A board whose whole promise is WHAT'S ON RIGHT NOW was also asking the reader to
set a time, and the strip label it painted — `Arriving Fri 5:30pm` — read as a
filter they had switched on by accident rather than a question they had
answered. Removed the **control**, not the concept:

- the Day chips still work; a future day still means "the evening" (16:00)
- **`state.offset` is still read off the `#t=` hash**, so an old shared link
  opens exactly as its sender saw it. Nothing writes it any more.
- `arrivalTime()` / `isNow()` untouched — the header clock IS the arrival moment
- `SPEC.md` §7 now records that the feature was built, shipped and removed, and
  why, instead of still specifying it

🔑 The lesson is not "sliders are bad": **a control the reader did not ask for
reads as a filter they cannot see themselves having set.** The default view has
to be the whole answer, not a starting position. Nothing in 527 tests could have
told us this; only Paul looking at it did.

Earlier UI asks from the same message are already in: **no Directions button on
an unknown-hours card**, and the **"Copy the details" button is gone** from the
"Know the hours?" modal.

---

## 4. 🎯 THE NEXT BUILDS, in order

### a. 🔴 Review Codex's scraping ideas against ours — THE EXPLICIT ASK, NOT STARTED

Paul asked for this twice and it has not been done. See
`HANDOFF-CODEX-DAILY-SCRAPE-20260902.md`. The five ideas on the table:

| idea | what it would buy | first question to ask it |
|---|---|---|
| render-on-blocked-fetch retry | pages that 403 a plain fetch (MONTCO did) | how many crawl misses actually are this? |
| `extract_deals.py --lids` | scoped re-extraction instead of the whole corpus | fits the SCOPED-RUNS-ONLY rule; cheap |
| `audit_rendered_artifacts.py` | see what rendering actually produced | **start here** |
| responsive-image dedupe in `extract_menu_images.py` | stop paying to read one menu at four widths | measure the duplicate rate first |
| `needy_lids(only=)` in `read_windows_llm.py` | scope the paid LLM pass | fits the same rule |

🎯 **The concrete first move, already recommended and still not run:**
`python ingest/audit_rendered_artifacts.py` on **one town (Upper Darby)** and
count **images → transcripts → cards → dollars** before any of this goes near
the daily job. *Prove it on one town for a dollar first.*

### b. ⏳ Philadelphia photos — ~1,150 venues, ~$45. **Paul's call, still unmade.**

Do not start it. The suburbs and Delaware are done.

### c. ❓ Photo upload "appears broken again" — BLOCKED ON PAUL

Server and browser flow were both verified clean and **nothing he sent reached
the queue**. Still need: which device, which browser, which button, and what
message he saw. Do not go hunting again without that — the last hunt found a
healthy system.

### d. The unknown-day-word guard — shipped last session, still worth extending

as the next unknown word appears. `DAYISH_RE` in `extract_deals.py`; four tests
pin it in `tests/test_window_agrees_with_quote.py`.

---

## 5. Standing rules (unchanged, do not relearn)

- 🛑 **Never run two crawls at once**, and never `git merge`/`pull` while one
  runs — `crawl_sites.py` rewrites the whole `crawl_hits.json` at checkpoints.
- 🛑 **Pull before you push. Codex works in this repo too.**
- 🛑 **"it is live" = one command:** `python tests/live_front_door.py <zone>`.
  A local render or a JSON 200 is a smaller question. GH Pages lags ~1 min, so
  **one NOT LIVE is a deploy in flight — re-run it**, do not diagnose it.
- 🛑 **Scoped runs only, never the corpus.**
- 🛑 **No `ANTHROPIC_API_KEY` in HHF's `.env`** — never borrow another repo's.
- 🛑 **Never write a backslash escape through a bash heredoc.** Use Write/Edit.
- 🛑 **`open(p, "w")` truncates before it writes.** Write `.new`, `os.replace`.

---

## 6. Housekeeping

`MEMORY.md` is **18.5 KB, over its own ~17 KB "past this is invisible" limit** —
it was already over before today's line was added. It wants a pruning pass; that
is a judgment call across lanes that are not all HHF's, so it was left for Paul
rather than trimmed silently.
