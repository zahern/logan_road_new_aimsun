#!/usr/bin/env bash
# gamesol_watch.sh -- progress snapshotter for the Aimsun game-ladder batch.
#
# Appends one line a minute to _sumo_port/gamesol_watch.log while the batch runs,
# so progress is recoverable even though nothing wakes the agent when a run lands.
# Read-only: it inspects kg/results, kg/run_config.py and the session log names;
# it never touches the model, the simulator or any result.
#
#   bash _sumo_port/gamesol_watch.sh          # 6 h, 60 s cadence
#   HOURS=12 STEP=30 bash _sumo_port/gamesol_watch.sh
#
# Counting uses ONE directory listing + grep rather than per-arm globs: kg/results
# holds ~9k entries, and 24 globs a minute thrashes the network mount.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
LOG="$HERE/gamesol_watch.log"
HOURS="${HOURS:-6}"
STEP="${STEP:-60}"
ARMS_RE='NASH|UTIL|NWELF|EGAL|KS|STACKBUS|STACKCAR|NONCOOP'

END=$(( $(date +%s) + HOURS * 3600 ))
echo "=== watch start $(date '+%F %T') -- ${HOURS}h @ ${STEP}s -> $LOG" >> "$LOG"

while [ "$(date +%s)" -lt "$END" ]; do
    listing=$(ls -1 "$ROOT"/kg/results 2>/dev/null)

    # Concept rows: <arm>_seed{300,400,500}_*  (the _seed suffix also excludes _CTM2).
    rows=$(printf '%s\n' "$listing" \
           | grep -cE "^CHAMP_ADAPTIVE_DSW_GAME_SOL_(${ARMS_RE})_seed(300|400|500)_")
    per_arm=$(printf '%s\n' "$listing" \
              | grep -oE "^CHAMP_ADAPTIVE_DSW_GAME_SOL_(${ARMS_RE})_seed(300|400|500)_" \
              | sed -E 's/^CHAMP_ADAPTIVE_DSW_GAME_SOL_//; s/_seed.*//' \
              | sort | uniq -c | awk '{printf " %s:%s", $2, $1}')

    cfg=$(grep -hE '^CURRENT_EXPERIMENT|^CURRENT_SEED|^GAME_SOLUTION|^NASH_CORRIDOR_MODE' \
          "$ROOT"/kg/run_config.py 2>/dev/null \
          | sed -E "s/^CURRENT_EXPERIMENT = /exp=/; s/^CURRENT_SEED = /seed=/; \
                    s/^GAME_SOLUTION = /gsol=/; s/^NASH_CORRIDOR_MODE = /corr=/; s/'//g" \
          | tr '\n' ' ')
    newest=$(basename "$(ls -1t "$ROOT"/kg/logs/Aimsun_TSP_Log_*.txt 2>/dev/null | head -1)" .txt)

    # NOTE: NO_TSP is not counted -- 162 historical dirs exist, so a count says
    # nothing about progress. The paired baseline is visible as exp=NO_TSP in the
    # run_config field instead.
    printf '%s | %2d/24 rows | %s| log=%s%s\n' \
        "$(date '+%F %T')" "$rows" "$cfg" "${newest:-none}" "$per_arm" >> "$LOG"
    sleep "$STEP"
done

echo "=== watch end $(date '+%F %T')" >> "$LOG"
