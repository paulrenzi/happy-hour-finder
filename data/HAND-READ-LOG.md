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
