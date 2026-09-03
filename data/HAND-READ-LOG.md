# Hand-read attempt log — every venue/zone touched, so we never re-research the same dead end

Append-only. One line per venue attempted, whether it shipped or not. This is
separate from `agent_handread.json` (which only holds venues that PUBLISHED) —
this log also records the ones that were tried and failed, and WHY, so a later
session doesn't burn time on the same site again.

Format: `- <zone> | <venue/lid> | RESULT | reason/note | date`

RESULT is one of: `SHIPPED` (live), `NO_CLOCK_TIME` (menu found, no window in
venue's own words), `UNREACHABLE` (site down/403/timeout), `NOT_SEEDED` (real
venue, not in venue_base.json — seed gap, out of scope), `NO_SITE` (seeded,
no resolved website even after discover_places.py), `WRONG_MATCH` (site
resolved to wrong business), `CHAIN_NO_DEAL` (chain page, no times/prices
listed), `ALREADY_LIVE` (already on board via another source, no net add).

## 2026-09-03/04 — DE + West Chester push (wilmington, newark_de, new_castle_de, west_chester)
(Not itemized retroactively — see HANDOFF-START-HERE-20260903-NIGHT-PA-NON-PHILLY-UNDER-10.md
for the summary. West Chester dead ends worth remembering: Slow Hand, Stove &
Tap, Roots Cafe, Andiario, dolce Zola — full menu found, NO_CLOCK_TIME, do not
re-attempt these unless the venue's own site changes.)

## 2026-09-03/04 night — first PA round (manayunk, audubon_eagleville, springfield_delco, chester_chichester, havertown, malvern_great_valley, warminster_warrington, doylestown, ridley_tinicum)
- manayunk | Taqueria Amor | SHIPPED | | 2026-09-04
- manayunk | Blondie on Main | SHIPPED | | 2026-09-04
- audubon_eagleville | Chickie's & Pete's Audubon | SHIPPED | | 2026-09-04
- springfield_delco | Dom & Mia's | SHIPPED | | 2026-09-04
- chester_chichester | Barnaby's - Aston | SHIPPED | | 2026-09-04
- havertown | Barnaby's - Havertown | SHIPPED | | 2026-09-04
- malvern_great_valley | Chickie's & Pete's Malvern | SHIPPED | | 2026-09-04
- warminster_warrington | Chickie's & Pete's Warrington | SHIPPED | | 2026-09-04
- doylestown | P J Whelihan's | SHIPPED | | 2026-09-04
- ridley_tinicum | Rosemary (existing) | SHIPPED | upgraded to verified clock+price, no net zone-count add | 2026-09-04
- conshohocken | P J Whelihan's | ALREADY_LIVE | verified upgrade, already on board via auto-extract | 2026-09-04
- blue_bell_plymouth_meeting | P J Whelihan's | ALREADY_LIVE | verified upgrade, already on board via auto-extract | 2026-09-04
- (unspecified zone) | P J Whelihan's - Wynnewood | ALREADY_LIVE | verified upgrade, already on board | 2026-09-04
- (unspecified zone) | P J Whelihan's - Oaks | ALREADY_LIVE | verified upgrade, already on board | 2026-09-04

## 2026-09-04 — second round in progress (norristown_bridgeport, upper_darby_lansdowne, ambler_upper_dublin, limerick_royersford, pottstown, souderton_harleysville, abington_jenkintown, collegeville_trappe, glen_mills_chadds_ford, lansdale_montgomeryville, newtown_square_broomall, conshohocken, blue_bell_plymouth_meeting, ardmore_bryn_mawr, + revisit thinner zones)
(agent running — appends its own attempts below as it goes)
- norristown_bridgeport | Chap's Taproom (114168) | SHIPPED | | 2026-09-04
- norristown_bridgeport | Vonc Brewing | UNREACHABLE | connection timeout | 2026-09-04
- norristown_bridgeport | Nippers | UNREACHABLE | connection timeout | 2026-09-04
- norristown_bridgeport | Five Saints Distilling | NO_CLOCK_TIME | reviews only, no HH window on page | 2026-09-04
- norristown_bridgeport | Conshohocken Brewing Company | NO_CLOCK_TIME | empty sweep, no HH text | 2026-09-04
- norristown_bridgeport | Justenuff | UNREACHABLE | connection timeout | 2026-09-04
- norristown_bridgeport | Capone's | NO_CLOCK_TIME | empty sweep | 2026-09-04
- norristown_bridgeport | Bridgeport Rib House | NO_CLOCK_TIME | windows found but no item prices in venue's own words | 2026-09-04
- manayunk | Cresson Inn | NO_CLOCK_TIME | mentions "daily happy hour specials" generically, no clock time/prices | 2026-09-04
- manayunk | Henry Ave Associates | UNREACHABLE | empty sweep | 2026-09-04
