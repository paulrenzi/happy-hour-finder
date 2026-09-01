#!/usr/bin/env python3
"""Venues that must never appear on the board, and why.

Two different kinds of thing live here, and keeping them apart is the point.

  1. A BANNED venue. Paul's call, permanent, no appeal, and it does not need a
     reason a program could check. Bald Birds Brewing is banned as of
     2026-09-01. Keyed on the PLCB licensee name, because that is the one field
     nobody rewrites: the trade name comes from Google and changes under us.

  2. A venue that is a HOTEL -- not a place with a hotel LICENCE. Those are not
     the same thing and the difference nearly cost us seven working venues.
     'Hotel (Liquor)' is a PLCB licence class, and 178 venues hold one; only 87
     of them are hotels. The Black Horse Tavern, The Stray Dog Tavern, Joseph
     Ambler Inn, Panorama and CO-OP Restaurant & Bar all hold that licence, all
     publish a happy hour, and all were on the board. Excluding the LICENCE
     would have deleted them along with the Marriotts.

     So a hotel is recognised by its BRAND, plus the narrow case of a venue that
     has the word 'Hotel' or 'Motel' in its own name AND holds the hotel
     licence. 'Inn' is deliberately not a signal on its own -- Joseph Ambler
     Inn, Sanatoga Inn and Flowing Spring are restaurants.

Nothing here is a scraper decision. It is a list of places we do not list, and
it runs at the two doors onto the board: ingest/build_venue_base.py, where a
venue first exists, and ingest/build_bundles.py, so a stale base cannot put one
back on the site.
"""

import re

# Keyed on the PLCB licensee name, upper-cased, matched as a whole name.
BANNED_PLCB_NAMES = {
    "BALD BIRDS BREWING COMPANY": "banned by Paul, permanently (2026-09-01)",
}

HOTEL_BRAND_RE = re.compile(
    r"\b("
    r"marriott|hilton|hyatt|sheraton|westin|doubletree|sofitel|"
    r"residence inn|courtyard|springhill|fairfield inn|towneplace|home2 suites|"
    r"hampton inn|homewood suites|embassy suites|holiday inn|crowne plaza|"
    r"staybridge|candlewood|wyndham|radisson|la quinta|best western|"
    r"comfort (?:inn|suites)|quality inn|sleep inn|days inn|super 8|"
    r"extended stay|sonesta|aloft|element by|tru by|ac hotel|moxy|"
    r"hotel indigo|kimpton|loews hotel|four seasons|ritz.?carlton|"
    r"le meridien|conrad|canopy by|tribute portfolio|autograph collection|"
    r"red carpet inn"
    r")\b", re.I)

# Only trusted alongside the hotel licence, and only as a whole word: a bar
# called 'The Hotel Bar' on a restaurant licence is a bar.
#
# And a name that ALSO says what it is beats it. 'THE OLDE BLACK HORSE TAVERN
# AND MOTEL' is a tavern that rents rooms, holds the hotel licence, publishes a
# happy hour and was on the board -- this rule took it off, and that was wrong.
# A brand match is not softened this way: a Marriott with a grill in it is
# still a Marriott, which is the thing Paul asked to stop listing.
HOTEL_WORD_RE = re.compile(r"\b(hotel|motel)\b", re.I)
NOT_A_HOTEL_RE = re.compile(
    r"\b(tavern|taproom|tap room|brewing|brewery|brewpub|pub|saloon|"
    r"alehouse|ale house|bar\s*(?:&|and)\s*grill|grille?|restaurant|"
    r"kitchen|cantina|trattoria|osteria|steakhouse|diner)\b", re.I)
HOTEL_LICENCE = "Hotel (Liquor)"


def excluded(name, plcb_name="", license_type=""):
    """Why this venue is off the board, or None to keep it."""
    labels = [(plcb_name or "").strip().upper(), (name or "").strip().upper()]
    # Contained, not equal: the trade name arrives as 'Bald Birds Brewing
    # Company - King of Prussia' and the licensee as the bare brand.
    for banned, why in BANNED_PLCB_NAMES.items():
        if any(banned in lab for lab in labels if lab):
            return why
    for label in (name or "", plcb_name or ""):
        if HOTEL_BRAND_RE.search(label):
            return "hotel"
        if (license_type == HOTEL_LICENCE and HOTEL_WORD_RE.search(label)
                and not NOT_A_HOTEL_RE.search(label)):
            return "hotel"
    return None
