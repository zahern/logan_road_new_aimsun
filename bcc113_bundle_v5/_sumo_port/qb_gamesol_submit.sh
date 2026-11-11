#!/bin/bash
# SUPERSEDED by qb_gamesol_gen.sh. That generator bakes the parameters into a
# per-job PBS, so it does not depend on -v semantics at all. This script is kept
# only because its arm/seed matrix is still the reference list.
#
# qb_gamesol_submit.sh -- submit the SUMO half of the GAME_SOLUTION comparison.
#
# Run this ON AQUARIUS (it only calls qsub; no python runs on the login node):
#   bash /home/ahernz/tsp/sumo_hpc/qb_gamesol_submit.sh            # QUICK: seed 300
#   FULL=1 bash /home/ahernz/tsp/sumo_hpc/qb_gamesol_submit.sh     # all 3 seeds
#   DRY=1  bash /home/ahernz/tsp/sumo_hpc/qb_gamesol_submit.sh     # print only
#   ARMS="CHAMP_ADAPTIVE_DSW_GAME_COOP" SEEDS="300" bash ...        # explicit
#
# NO_TSP is included: the ladder must be scored against a baseline measured on
# the SAME build and seed, never against an older CSV (AGENTS RULE 3).
#
# qsub on aquarius now REJECTS a submit with no project code ("Supply a valid
# project RPID"), so every job is submitted with -P. Override with RPID=... .
#
# The variables go in ONE -v as a comma-separated list. Repeating -v does not
# merge: PBS keeps only the last one, so "-v CORR=kg -v ARM=X -v SEED=300"
# arrives as just SEED=300 and qb_gamesol.pbs aborts with "need ARM=...".
# That is how jobs 27677851/52/54/55 died in 17 s without simulating anything.
set -u
BASE="${BASE:-/home/ahernz/tsp/sumo_hpc}"
RPID="${RPID:-FPAXJW8067}"
CORR="${CORR:-kg}"
cd "$BASE" || exit 1

ALL_ARMS=(
  CHAMP_ADAPTIVE_DSW_GAME_COOP
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH
  CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NWELF
  CHAMP_ADAPTIVE_DSW_GAME_SOL_EGAL
  CHAMP_ADAPTIVE_DSW_GAME_SOL_KS
  CHAMP_ADAPTIVE_DSW_GAME_SOL_STACKBUS
  CHAMP_ADAPTIVE_DSW_GAME_SOL_STACKCAR
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NONCOOP
)

if [ -n "${ARMS:-}" ]; then
  read -ra LIST <<< "${ARMS//,/ }"
elif [ "${FULL:-0}" = "1" ]; then
  LIST=("CHAMP_NO_TSP" "${ALL_ARMS[@]}")
else
  LIST=("CHAMP_NO_TSP" CHAMP_ADAPTIVE_DSW_GAME_COOP \
        CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL)
fi

if [ -n "${SEEDS:-}" ]; then
  read -ra SEEDL <<< "${SEEDS//,/ }"
elif [ "${FULL:-0}" = "1" ]; then
  SEEDL=(300 400 500)
else
  SEEDL=(300)
fi

echo "corridor=$CORR arms=${#LIST[@]} seeds=${SEEDL[*]}"
N=0
for a in "${LIST[@]}"; do
  for s in "${SEEDL[@]}"; do
    if [ "${DRY:-0}" = "1" ]; then
      echo "qsub -P $RPID -v CORR=$CORR,ARM=$a,SEED=$s qb_gamesol.pbs"
    else
      qsub -P "$RPID" -v CORR="$CORR",ARM="$a",SEED="$s" qb_gamesol.pbs
    fi
    N=$((N + 1))
  done
done
echo "$N job(s)$([ "${DRY:-0}" = "1" ] && echo ' (dry run)')"
echo
echo "watch:  qstat -u ahernz"
echo "score:  python compare_game_solution.py    (locally, on Windows)"
