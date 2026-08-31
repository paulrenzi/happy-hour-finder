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
echo "== the shipped modules parse in a real browser engine =="
python tests/parse_check.py

echo
echo "== the board actually paints =="
python tests/render_check.py

echo
echo "== a tab left open restamps itself on wake =="
python tests/stale_clock_check.py
