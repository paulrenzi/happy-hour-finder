#!/bin/sh
# Photos for every licensed venue in a list of zones, one zone at a time.
#
#     sh ingest/photo_sweep.sh king_of_prussia media doylestown
#
# 🛑 BILLED. About $0.039 a venue (Places text search + photo download). Price
# a zone first with `python ingest/fetch_venue_photos.py --from-board
# --every-venue --zone Z` (no --spend) before running this over it.
#
# 🔑 THE REBUILD BETWEEN ZONES IS NOT TIDINESS. Coverage is read off the
# SHIPPED bundles, so a second run before a rebuild re-bills every venue the
# first one already fetched. That cost about $0.50 the first time it happened.
set -eu
cd "$(dirname "$0")/.."
for zone in "$@"; do
    echo "===== $zone"
    python ingest/fetch_venue_photos.py --from-board --every-venue --zone "$zone" --spend
    python ingest/build_venue_base.py >/dev/null
    python ingest/build_bundles.py >/dev/null
done
echo
echo "swept: $*"
