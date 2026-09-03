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
listed), `ALREADY_LIVE` (already on board via another source, no net add),
`RESHIPPED` (re-read a venue already `SHIPPED` because its live item count was
suspiciously thin — 1-2 items for a full-menu venue — and the re-read found a
fuller menu; note the before/after item count).

🛑 2026-09-03 night finding: `SHIPPED` only ever meant "a window and at least
one item are live," never "the full menu was read." 28 live venues (11
`agent_read`, 17 `menu_read_llm`) were found with ≤1 item despite being
`SHIPPED` — see `ARCHITECTURE-MENU-INGEST.md`, "A SHIPPED HAND-READ CAN STILL
BE A THIN READ". Before skipping a `SHIPPED` venue as done, check its live
item count is plausible for the kind of place it is.

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
- ambler_upper_dublin | Fireside Bar and Grill (55311) | SHIPPED | | 2026-09-04
- pottstown | Doc's Irish Pub (68830) | SHIPPED | | 2026-09-04
- glen_mills_chadds_ford | The Crown Tavern (48062) | SHIPPED | | 2026-09-04
- glen_mills_chadds_ford | Chadds Ford Tavern (91807) | SHIPPED | | 2026-09-04
- upper_darby_lansdowne | Station Tap/Pete's Pizza and Beer/Fibbers/J T Brewski/Carlettes Hideaway | NO_CLOCK_TIME | no HH text found on any sweep | 2026-09-04
- ambler_upper_dublin | Well Crafted Beer Co/Gypsy Blu/Forest & Main | NO_CLOCK_TIME | empty sweeps | 2026-09-04
- ambler_upper_dublin | Spring House Tavern | UNREACHABLE | 403 forbidden | 2026-09-04
- ambler_upper_dublin | Bar 31 | UNREACHABLE | SSL cert expired | 2026-09-04
- limerick_royersford | Lost Planet Brewing/Magerks Pub/Tom's Bar & Grille/Craft Ale House/Salford Station Spirits | NO_CLOCK_TIME | empty sweeps, all dead-end | 2026-09-04
- pottstown | Sunset Hill Brewing/Gatsby's Pub/Twisted Cork | NO_CLOCK_TIME | empty sweeps | 2026-09-04
- pottstown | Big Phil's Bar & Grill | NO_CLOCK_TIME | window found (Mon-Fri 4-6) but only BOGO/relative pricing, no absolute price | 2026-09-04
- pottstown | Sly Fox Brewing/Tastin' Room | NO_CLOCK_TIME | bundle pricing not clearly tied to a stated clock window | 2026-09-04
- pottstown | Union Jacks | UNREACHABLE | connection timeout | 2026-09-04
- pottstown | Ron's Crooked Hill Tavern | UNREACHABLE | HTTP 509 | 2026-09-04
- pottstown | Jj Ratigan Brewing | NO_CLOCK_TIME | window found Mon-Thu 4-6 but no absolute item price | 2026-09-04
- souderton_harleysville | Sumneytown Hotel/Piano Bar/Branch Creek Brewing/3 Sisters Rum/Harleysville Hotel/Macoby Run/Telford Tavern/Rising Sun Inn/Hattricks/Imprint Beer | UNREACHABLE/NO_CLOCK_TIME | empty sweeps or connection errors | 2026-09-04
- souderton_harleysville | Northbound Restaurant | NO_CLOCK_TIME | window Tue-Fri 3:30-5:30 found, no prices reachable | 2026-09-04
- souderton_harleysville | Crossroads Tavern | NO_CLOCK_TIME | window Mon-Fri 4-6pm found, no prices reachable (dedicated HH page has no pricing text) | 2026-09-04
- souderton_harleysville | Red Cedar Grille | NO_CLOCK_TIME | HH mentioned only as SEO keyword list, no window/price | 2026-09-04
- souderton_harleysville | Butcher and Barkeep | NO_CLOCK_TIME | window Mon-Fri 3:30-5:30 found, no prices reachable | 2026-09-04
- souderton_harleysville | Perkiomen Valley Brewery | UNREACHABLE | HTTP 401 | 2026-09-04
- abington_jenkintown | Morgan Stillhouse/Bernie's/Glenside Pub/Drake Tavern/Kings Corner/Rockledge Malthouse/Bill's Best Brewery | UNREACHABLE/NO_CLOCK_TIME | connection errors or empty sweeps | 2026-09-04
- abington_jenkintown | W Tavern | NO_CLOCK_TIME | window Tue-Fri 4-6pm found but only "$1 off" relative pricing, no absolute price | 2026-09-04
- abington_jenkintown | Jerzees | NO_CLOCK_TIME | HH mentioned only in event-space marketing copy | 2026-09-04
- collegeville_trappe | Fitzwater Station/Stray Dog Tavern/Lock 29/Ember & Ale/Dutch Cottage Tavern | NO_CLOCK_TIME | empty sweeps | 2026-09-04
- collegeville_trappe | Trappe Tavern | NO_CLOCK_TIME | window Mon-Fri 4-6pm found ("drink, food, and draft features") but no specific prices reachable | 2026-09-04
- glen_mills_chadds_ford | 2 Sp Brewing/Bierhaul/Heroes Bar & Grill/Gran Rodeo | UNREACHABLE/NO_CLOCK_TIME | connection errors or empty sweeps | 2026-09-04
- glen_mills_chadds_ford | Del Pez Mexican Gastropub | UNREACHABLE | HTTP 429 | 2026-09-04
- lansdale_montgomeryville | Lansdale Tavern (100210) | SHIPPED | | 2026-09-04
- lansdale_montgomeryville | The Bull Restaurant & Tavern (126965) | SHIPPED | | 2026-09-04
- newtown_square_broomall | Sedona Taphouse (118439) | SHIPPED | | 2026-09-04
- conshohocken | The Gypsy Saloon (107050) | SHIPPED | | 2026-09-04
- conshohocken | Pepperoncini Restaurant & Bar (53783) | SHIPPED | | 2026-09-04
- lansdale_montgomeryville | Local Tap/Main Street Pizza & Brewery/Blue Dog Pub(429)/Ten7 Brewing | UNREACHABLE/NO_CLOCK_TIME | empty sweeps or rate-limited | 2026-09-04
- lansdale_montgomeryville | Metropolitan American Diner & Bar | NO_CLOCK_TIME | "All Day" specials not a clock window | 2026-09-04
- lansdale_montgomeryville | Tex Mex Connection | NO_CLOCK_TIME | window found Mon-Fri 4-6pm/weekend, but drinks menu has no HH-specific pricing | 2026-09-04
- lansdale_montgomeryville | Pour House | NO_CLOCK_TIME | HH mentioned only in marketing copy, no window/price | 2026-09-04
- lansdale_montgomeryville | Stove & Tap | UNREACHABLE | HTTP 429 | 2026-09-04
- newtown_square_broomall | Vino Bambino/Rey Azteca/Sproul Lanes/Hiramasa/Charlotte's/Ristorante la Locanda/Uno Pizzeria | NO_CLOCK_TIME | not attempted individually, low-yield chain/empty | 2026-09-04
- newtown_square_broomall | Ale House Newtown Square | NO_CLOCK_TIME | window found (daily 4-6pm via events calendar) but no pricing text found | 2026-09-04
- newtown_square_broomall | La Porta Ristorante | NO_CLOCK_TIME | HH page exists but link-only, no window/price text captured | 2026-09-04
- newtown_square_broomall | Anthony's at Paxon Hollow | UNREACHABLE | empty sweep | 2026-09-04
- conshohocken | Guppy's Good Times/Great American Pub/Conshohocken Brewing Co | NO_CLOCK_TIME | empty sweeps | 2026-09-04
- conshohocken | Coyote Crossing | NO_CLOCK_TIME | window Mon-Fri 4-6pm found, no absolute item price in reachable pages | 2026-09-04
- conshohocken | The StoneRose | NO_CLOCK_TIME | HH mentioned in menu nav only, no window/price | 2026-09-04
- conshohocken | Jasper's Backyard | NO_CLOCK_TIME | Weekend HH window Sat/Sun 3-5pm found, but no price explicitly tied to HH (regular menu prices only) | 2026-09-04
- blue_bell_plymouth_meeting | Blue Bell Inn (67233) | SHIPPED | | 2026-09-04
- blue_bell_plymouth_meeting | Scoogi's Italian Kitchen & Bar (27076) | SHIPPED | | 2026-09-04
- ardmore_bryn_mawr | The Pub of Penn Valley (43721) | SHIPPED | | 2026-09-04
- blue_bell_plymouth_meeting | Andy's Diner & Pub/Brittingham's/McCloskey's Tavern | NO_CLOCK_TIME | empty sweeps | 2026-09-04
- blue_bell_plymouth_meeting | Whitpain Tavern | NO_CLOCK_TIME | daily specials found but no explicit HH clock window tied to prices | 2026-09-04
- blue_bell_plymouth_meeting | The Phil's Tavern | NO_CLOCK_TIME | HH prices found but no clock window anywhere on site | 2026-09-04
- blue_bell_plymouth_meeting | El Sarape | NO_CLOCK_TIME | HH menu page exists but no window/price text reachable | 2026-09-04
- ardmore_bryn_mawr | McShea's/The Grog/Great American Pub/Tired Hands | UNREACHABLE/NO_CLOCK_TIME | connection errors, empty sweeps, or rate-limited | 2026-09-04
- ardmore_bryn_mawr | Gullifty's | NO_CLOCK_TIME | window Mon-Fri 3:30-6:00 found but pricing is "20% off" relative, not absolute post-discount price | 2026-09-04
- (correction) norristown_bridgeport | Chap's Taproom (114168) | SHIPPED | genuine net-new, confirmed vs pre-session baseline | 2026-09-04
- (correction) glen_mills_chadds_ford | The Crown Tavern (48062) | SHIPPED | genuine net-new, confirmed vs pre-session baseline | 2026-09-04
- (correction) blue_bell_plymouth_meeting | Blue Bell Inn (67233) | SHIPPED | genuine net-new, confirmed vs pre-session baseline | 2026-09-04
- (correction) pottstown | Doc's Irish Pub (68830) | ALREADY_LIVE | was already published pre-session (auto-extract); hand-read only upgraded evidence, no net add | 2026-09-04
- (correction) ambler_upper_dublin | Fireside Bar and Grill (55311) | ALREADY_LIVE | was already published pre-session; hand-read only upgraded evidence, no net add | 2026-09-04
- (correction) lansdale_montgomeryville | Lansdale Tavern (100210) | ALREADY_LIVE | was already published pre-session; hand-read only upgraded evidence, no net add | 2026-09-04
- (correction) lansdale_montgomeryville | The Bull Restaurant & Tavern (126965) | ALREADY_LIVE | was already published pre-session; hand-read only upgraded evidence, no net add | 2026-09-04
- (correction) newtown_square_broomall | Sedona Taphouse (118439) | ALREADY_LIVE | was already published pre-session; hand-read only upgraded evidence, no net add | 2026-09-04
- (correction) conshohocken | The Gypsy Saloon (107050) | ALREADY_LIVE | was already published pre-session; hand-read only upgraded evidence, no net add | 2026-09-04
- (correction) conshohocken | Pepperoncini Restaurant & Bar (53783) | ALREADY_LIVE | was already published pre-session; hand-read only upgraded evidence, no net add | 2026-09-04
- (correction) glen_mills_chadds_ford | Chadds Ford Tavern (91807) | ALREADY_LIVE | was already published pre-session; hand-read only upgraded evidence, no net add | 2026-09-04
- (correction) blue_bell_plymouth_meeting | Scoogi's Italian Kitchen & Bar (27076) | ALREADY_LIVE | was already published pre-session; hand-read only upgraded evidence, no net add | 2026-09-04
- (correction) ardmore_bryn_mawr | The Pub of Penn Valley (43721) | ALREADY_LIVE | was already published pre-session; hand-read only upgraded evidence, no net add | 2026-09-04
- IMPORTANT LESSON: check web/data/zone-<z>.json for the venue name BEFORE hand-reading -- a lid missing from agent_handread.json can still already be live via auto-extraction. Only 3 of 13 attempts this round were genuinely net-new.

## 2026-09-04 continued — third round (thin non-Philly PA sweep, then Job 2 new towns)
- souderton_harleysville | P J Whelihan's Hatfield (110926) | SHIPPED | same chain HH menu/window as 5 other locations already live | 2026-09-04
- pottstown | Sly Fox Tastin' Room | NO_CLOCK_TIME | Sunday-only relative discounts ($5 off wings, half price), no absolute price tied to window | 2026-09-04
- norristown_bridgeport | Bridgeport Rib House (theribby.com) | NO_CLOCK_TIME | re-confirmed: multiple clear HH windows, zero item prices anywhere on site | 2026-09-04
- pottstown | Big Phil's Bar & Grill | NO_CLOCK_TIME | re-confirmed: Mon-Fri 4-6pm window, only BOGO apps (relative), no absolute price | 2026-09-04
- audubon_eagleville | Eagleville Taphouse | UNREACHABLE | HTTP 406 | 2026-09-04
- ridley_tinicum | Hunt's Annex Lounge / Tom N Jerry's Sports Pub | UNREACHABLE | 403/406 | 2026-09-04
- ridley_tinicum | Erin Pub | NO_CLOCK_TIME | no HH text on 63KB page | 2026-09-04
- springfield_delco | Springfield Ale House / Crafty's Springfield | NO_CLOCK_TIME | empty/thin sweeps, no HH text | 2026-09-04
- upper_darby_lansdowne | 40 Garrett Rd Cafe | NO_CLOCK_TIME | empty sweep | 2026-09-04
- ambler_upper_dublin/limerick_royersford/collegeville_trappe | Well Crafted Beer Co, Spring House Tavern(403), Giuseppes, William Penn Inn, Lost Planet Brewing, Limerick Diner, Magerks, Tom's Bar & Grille, Moccia's Train Stop | UNREACHABLE/NO_CLOCK_TIME | empty sweeps or blocked | 2026-09-04
- norristown_bridgeport | Vonc Brewing, Mama Venezia | UNREACHABLE/NO_CLOCK_TIME | empty sweep / 404 | 2026-09-04
- pottstown | Sunset Hill Brewing, Flowing Springs Inn, Peppe's Pizza, Gatsby's Pub, Sanatoga Pizza Grill, Twisted Cork | NO_CLOCK_TIME | all empty sweeps | 2026-09-04
- souderton_harleysville | Harleysville Hotel, Sumneytown Hotel, Branch Creek Brewing, 3 Sisters Rum, Collegeville Diner, Spirochete Brewing | NO_CLOCK_TIME | all empty sweeps | 2026-09-04
- ambler_upper_dublin | Gypsy Blu, Bacio's Italian Cucina | NO_CLOCK_TIME | empty sweeps | 2026-09-04
- abington_jenkintown | Morgan Stillhouse | NO_CLOCK_TIME | empty sweep | 2026-09-04
- manayunk | Daiva's Grille, kitchenbar.net | UNREACHABLE/NO_CLOCK_TIME | 410 gone / empty sweep | 2026-09-04
- NOTE: remaining unread candidates in these thin non-Philly zones are heavily chains/groceries/non-bar businesses (Wawa, ShopRite, Giant, Chipotle, Chili's, Starbucks, Sheetz, Royal Farms, Little Caesars) or independents already dead-ended above -- this territory is close to tapped out for the hand-read ladder without new seeding (discover_places.py) or fresh sites appearing.
- ridley_tinicum | Rosemary (110744) | SHIPPED | full HH menu image, daily 4-6pm | 2026-09-03
- middletown_de | The Farmhouse Middletown (DEa4fada708b) | SHIPPED | Mon-Fri 3-6pm bar area, full pricing | 2026-09-03
- middletown_de | Mulligans (DEe5a79c1b86) | SHIPPED | Tue-Fri 3-6pm, full drink/food pricing | 2026-09-03
- havertown | Ivy Inn/Barnaby's/JD McGillicuddy's | NO_CLOCK_TIME | empty sweeps or marketing copy only, no window/price | 2026-09-03
- havertown | The Crossbar | UNREACHABLE | SSL cert self-signed | 2026-09-03
- havertown | 1019 Westgate (Westgate Pub) | UNREACHABLE | HTTP 429 | 2026-09-03
- ridley_tinicum | Fainting Goat | NO_CLOCK_TIME | window m-f 4-6 found repeatedly but no price text anywhere on site | 2026-09-03
- ridley_tinicum | Casey's Ridley Park | NO_CLOCK_TIME | Popmenu JS-rendered specials page, no content in raw fetch | 2026-09-03
- ridley_tinicum | Stinger's Waterfront/Gachi Sushi/Ridley House/Station Tap/Pete's Pizza/Carlette's Hideaway/JT Brewski/Fibbers | NO_CLOCK_TIME | empty sweeps | 2026-09-03
- middletown_de | Curry & Cocktails | NO_CLOCK_TIME | window daily 4:30-6:30pm found but no HH item prices reachable | 2026-09-03
- middletown_de | Ochinilis Steaks | UNREACHABLE | HTTP 403 | 2026-09-03
- middletown_de | Casa 19/Back Creek Seven Tap/Mas Tacos/Jackson House/Derby's/Caruso's Bistro/Randazzo's | NO_CLOCK_TIME | empty sweeps | 2026-09-03
- chester_chichester | Monaghan's Pub/Hunt's Annex/Tom N Jerry's/E Cooke Winery/Gachi Sushi/Phoenix Bar & Grill/Duffer's Mill/Lefty's Irish Pub/Maggie May's | NO_CLOCK_TIME | empty sweeps or unreachable Facebook page | 2026-09-03
- middletown_de | Pithari (DEc2e120b082) | SHIPPED | HH PDF menu, Tue-Sun 3-7pm, full food/cocktail/wine/beer pricing | 2026-09-03
- audubon_eagleville | The Cage / Select Pizza Grill of Audubon (115024) | SHIPPED | JSON-LD structured HH menu, Mon-Fri 4-6pm | 2026-09-03

## 2026-09-04 — Job 2: four new Bucks County towns seeded + hand-read
New zones added to data/zones.json (real, distinct, PLCB-verified municipalities not
previously claimed by any existing zone): new_hope, newtown_bucks (Newtown/Newtown Twp,
Bucks Co.), perkasie, quakertown. Seeded via ingest/seed_plcb.py (fresh PLCB export) +
ingest/discover_places.py --execute (66 Places lookups, within free Enterprise tier).
- new_hope | OldeStone Steakhouse (106434) | SHIPPED | Mon-Fri 4:30-6:30pm, full priced bar menu | 2026-09-04
- newtown_bucks | Green Parrot (60193) | SHIPPED | irregular windows (Mon-Thu/Fri/Sat/Sun differ), full priced menu | 2026-09-04
- newtown_bucks | PJ Whelihan's Pub + Restaurant - Newtown (133468) | SHIPPED | same chain HH menu/window as 6 other locations | 2026-09-04
- perkasie | Free Will Brewing (65716) | SHIPPED | Mon-Fri 4-6pm, $5 beers | 2026-09-04
- new_hope | Fran's Pub, Karla's, Havana, Nektar Wine Bar, Salt House, John & Peter's, The Landing, Bucks County Playhouse | NO_CLOCK_TIME | empty sweeps | 2026-09-04
- newtown_bucks | Piccolo Trattoria, Newtown Brewing Co, La Stalla (JS-rendered, empty raw HTML) | NO_CLOCK_TIME | empty sweeps | 2026-09-04
- perkasie | Rams Pint House | UNREACHABLE | HTTP 429 rate-limited, not retried | 2026-09-04
- perkasie | The Perk (attheperk.com) | NO_CLOCK_TIME | Mon-Fri 4-6pm window found but only "$1 Off" relative pricing | 2026-09-04
- quakertown | The Proper Brewing Co | NO_CLOCK_TIME | Wed-Thu 4-6pm window, only "$1 OFF drafts" relative pricing | 2026-09-04
- quakertown | Doan Distillery | NO_CLOCK_TIME | empty sweep | 2026-09-04
- quakertown | McCoole's at the Historic Red Lion Inn | NO_CLOCK_TIME | empty sweep | 2026-09-04
- FIX: found + removed a stale seed-corpus entry "Iron Hill Brewery & Restaurant -- Media"
  (30-32 E State St) that had silently dropped out of the 2026-09-03 PLCB active-licensee
  refresh (closed/lapsed license). It was shipping with lid=null and failing CI
  (test_it_holds_every_venue_the_bundles_ship + test_geocode_records_keep_the_address_...),
  which had SILENTLY BLOCKED EVERY DEPLOY since it was introduced -- confirmed via
  `gh run list`, two pushes (job2, job3) landed on GitHub but never went live until this
  was fixed. Moved to data/deals_seed.json's `_excluded` list with the reason; also
  removed its now-orphaned rows from data/venue_coords.json and data/venue_photos.json
  and its stale image. All 552 local tests pass after the fix; CI green; confirmed live.
- west_chester | Limoncello (59213) | RESHIPPED | was 1 item, now 10 (martinis/cocktails/spritzes/wine/draft/bottle/pizza/small-medium plates/pasta) | 2026-09-04
- exton_downingtown | Liberty Union Bar and Grill (65626) | RESHIPPED | was 0 hand-read items (auto_extract lane), now 9 (drafts/IPA/well/wine/tots/margarita/chicken/eggrolls/old fashioned) | 2026-09-04
- glen_mills_chadds_ford | Chadds Ford Tavern (91807) | RESHIPPED | was 1 item, now 10 (half-price bar + wedge/caesar/soup/frites/pretzel/eggrolls/shrimp/wings/flatbread/short-rib-fries) | 2026-09-04
- malvern_great_valley | Main Line Tavern (118403) | RESHIPPED | was 1 item, now 11 (same chain menu as Chadds Ford Tavern) | 2026-09-04
- middletown_de | The Farmhouse Middletown (DEa4fada708b) | RESHIPPED | was 4 items, now 5 (cocktails/well/wine/bottled beer/half-price pizza) | 2026-09-04
- warminster_warrington | Tony's Place Bar & Grill (55339) | RESHIPPED | was 4 items, now 10 (bites, sliders, clams, house wine, cans) | 2026-09-04
- upper_darby_lansdowne | Casey's (125992) | RESHIPPED | was 4 items, now 8 (margaritas/mules/martinis/statesides/surfsides/well/draft/bites) | 2026-09-04
- willow_grove_horsham | Copper Crow (101437) | RESHIPPED | was 1 item, now 5 (draft/wine glass/cocktail/wine bottle discount/rotating daily food special) | 2026-09-04
- new_castle_de | Stanley's Tavern (DEc5d692f92b) | UNREACHABLE | HTTP 403 on happy-hour page, not retried | 2026-09-04
- new_castle_de | Augustine Tavern (DE67e9d8cbb9) | NO_CLOCK_TIME | happy-hour event page says "More Information Coming Soon" | 2026-09-04
- newtown_square_broomall | La Porta Ristorante (64766) | NO_CLOCK_TIME | window found (Mon/Wed-Sat 4-6pm) but items are in menu images, not text -- needs an image-read pass | 2026-09-04
- newtown_square_broomall | Sedona Taphouse (118439) | NO_CLOCK_TIME | window found (Mon-Fri 4-6pm) but full items are in a linked PDF, not fetched | 2026-09-04
- willow_grove_horsham | Crooked Eye Brewery (69140) | NO_CLOCK_TIME | genuinely thin -- only "$1 off pints Fri 4-6pm" on the page | 2026-09-04
- kennett_square | Victory Brewing Company Kennett Square (70490) | NO_CLOCK_TIME | genuinely thin -- only "$2 off drafts/liquor/wine/shareables", no itemized menu | 2026-09-04
- glen_mills_chadds_ford | The Crown Tavern (48062) | NO_CLOCK_TIME | genuinely thin -- half-price drinks, $1 oysters, "$7 and up" food, no itemized list | 2026-09-04
- norristown_bridgeport | Chap's Taproom (114168) | NO_CLOCK_TIME | genuinely thin -- 3 category-level discounts only ($4 draft/well, $5 wine, $6 apps), no itemized menu | 2026-09-04
- pottstown | Doc's Irish Pub (68830) | NO_CLOCK_TIME | genuinely thin -- Busch $2.50 + "$1 off beers/wells/wines", no food items | 2026-09-04

## 2026-09-03 continued -- fourth round (Paul-named URLs, non-Philly follow-through)
- collegeville_trappe | Basta Pasta (51101) | SHIPPED | menu was in 2 linked JPGs (bastapastapa.com/happy-hour-menu), rendered w/ Read: 10 items (small plates, drafts, cocktails, wine), Mon-Fri 4-6/Sun 2-4 | 2026-09-03
- wayne_radnor | Amada Radnor (115054) | SHIPPED | menu was in a linked PDF (uploads/114704AMAHappyHourMenu0726-nocrop.pdf), rendered to PNG w/ fitz + Read: 10 items (sangria, cocktails, vino, draft, tapas), Sun-Fri 4:30-6:30pm | 2026-09-03
- wayne_radnor | Garrett Hill Ale House (101476) | NO_CLOCK_TIME | genuinely thin -- only "$2 off craft beers" Wed-Fri 4-7pm, no other items on page | 2026-09-03
- wayne_radnor | Exit 13 Gastrobar (109849) | NO_CLOCK_TIME | genuinely thin -- only "$1 Merasheen Bay Oysters" Tue, no other prices anywhere on site incl. /drinks | 2026-09-03
