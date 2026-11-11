#!/usr/bin/env bash
# lightsim_watch.sh -- progress snapshotter for the LOGAN LightSim-CTM vs SPILL2 A/B.
#
# The live batch is game_ladder_logan_lightsim_<ts>.csv (5 arms x 5 seeds = 25 runs);
# it is NOT the KG GAME_SOL_* sweep, so progress must be read from THIS CSV, not from
# a count of kg/results (which holds years of history and cannot distinguish builds).
#
#   bash _sumo_port/lightsim_watch.sh
#   HOURS=8 STEP=60 bash _sumo_port/lightsim_watch.sh
#
# Read-only. One snapshot a minute; rows are counted from the CSV the runner appends
# to after each run, plus the last "[n/25]" line and the live run_config.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
LOG="$HERE/lightsim_watch.log"
CONSOLE="$ROOT/logan_road_new/logs/runner_console.txt"
HOURS="${HOURS:-8}"
STEP="${STEP:-60}"

END=$(( $(date +%s) + HOURS * 3600 ))
echo "=== watch start $(date '+%F %T') -- ${HOURS}h @ ${STEP}s -> $LOG" >> "$LOG"

while [ "$(date +%s)" -lt "$END" ]; do
    csv=$(ls -1t "$ROOT"/game_ladder_logan_lightsim_*.csv 2>/dev/null | head -1)
    if [ -n "$csv" ]; then
        lines=$(wc -l < "$csv" 2>/dev/null | tr -d ' ')
        rows=$(( ${lines:-0} - 1 ))     # minus header; fields here contain no newlines
        csvname=$(basename "$csv")
    else
        rows=0; csvname=none
    fi

    lastrun=$(grep -aoE '\[[0-9]+/25\][^|]*\|[^|]*\| seed=[0-9]+' "$CONSOLE" 2>/dev/null \
              | tail -1 | sed -E 's/ logan_road_new//; s/CHAMP_ADAPTIVE_DSW_GAME_SOL_//')
    cfg=$(grep -hE '^CURRENT_EXPERIMENT|^CURRENT_SEED' "$ROOT"/logan_road_new/run_config.py 2>/dev/null \
          | sed -E "s/^CURRENT_EXPERIMENT = '?CHAMP_ADAPTIVE_DSW_GAME_SOL_?//; s/^CURRENT_SEED = /!/; s/'//g" \
          | tr -d '\r' | tr '\n' ' ')

    printf '%s | %2d/25 rows | cfg %s| last %s | %s\n' \
        "$(date '+%F %T')" "$rows" "$cfg" "${lastrun:-none}" "$csvname" >> "$LOG"
    sleep "$STEP"
done

echo "=== watch end $(date '+%F %T')" >> "$LOG"
