#!/bin/sh
# One load level end to end, inside the loadtest container:
#   docker compose -f docker-compose.yml -f docker-compose.loadtest.yml --profile loadtest \
#     run --rm loadtest sh run_level.sh <name> <users> <spawn_rate> <duration>
#   e.g.  sh run_level.sh medium 100 10 3m
# Writes /reports/<name>/ (= docs/reports/<name>/): report.html, stats_*.csv, outcomes.json, invariants.json
set -e
NAME=${1:?name}; USERS=${2:?users}; RATE=${3:?spawn rate}; DURATION=${4:?duration}
OUT=/reports/$NAME
mkdir -p "$OUT"
python lt_data.py seed
python lt_data.py reset
OUTCOMES_FILE=$OUT/outcomes.json locust -f locustfile.py --headless -u "$USERS" -r "$RATE" -t "$DURATION" \
  --stop-timeout 30 --csv "$OUT/stats" --html "$OUT/report.html" --only-summary || true
python verify_invariants.py --out "$OUT/invariants.json"
