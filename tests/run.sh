#!/bin/sh
# Every test in the repo. Run from the repo root:  sh tests/run.sh
set -eu

echo "== PA validators, decay ladder, geocode parsing =="
python -m unittest discover -s tests

echo
echo "== time math, ranking, feed assembly =="
node --test tests/time_math.test.mjs

echo
echo "== the shipped corpus still validates =="
python ingest/validate_pa.py
