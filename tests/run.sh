#!/bin/sh
# Every test in the repo. Run from the repo root:  sh tests/run.sh
set -eu

echo "== PA validators, decay ladder, geocode parsing =="
python -m unittest discover -s tests

echo
echo "== time math, ranking, feed assembly, the live overlay =="
node --test "tests/*.test.mjs"

echo
echo "== the shipped corpus still validates =="
python ingest/validate_pa.py

echo
echo "== every published window agrees with its own quote =="
python tests/window_quote_check.py

echo
echo "== the shipped modules parse in a real browser engine =="
python tests/parse_check.py

echo
echo "== the board actually paints =="
python tests/render_check.py

echo
echo "== the live-shows chip shows live shows, tonight first =="
python tests/events_filter_check.py

echo
echo "== a bar can be found by name =="
python tests/search_check.py

echo
echo "== a menu can be sent for a bar that was never on the board =="
python tests/picker_check.py

echo
echo "== a tab left open restamps itself on wake =="
python tests/stale_clock_check.py

echo
echo "== a link can sort the board around a place, and says which =="
python tests/near_check.py

echo
echo "== a card still reads at phone width =="
python tests/card_chrome_check.py

echo
echo "== thin-read backlog: live deals under 5 items (report, not a gate) =="
python tests/thin_read_report.py
