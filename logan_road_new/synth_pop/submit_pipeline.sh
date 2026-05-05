#!/bin/bash
# =============================================================================
# submit_pipeline.sh
# Full synthetic population pipeline — PBS job chain
#
# Usage (from synth_pop/ on the HPC login node):
#   chmod +x submit_pipeline.sh
#   ./submit_pipeline.sh [--total-zones 134] [--chunk-size 10] [--dict-opts 5]
#                        [--skip-gan] [--skip-household] [--only-analysis]
#
# Stages submitted:
#   J1  stage1_gan.pbs          GPU job, 24 h — train DATGAN
#   J2  stage2_household.pbs    CPU job, 12 h — household match + repair
#                               (depends on J1 via afterok)
#   J3  stage3_sa_fitting.pbs   CPU jobs, 94 h each — SA-GAN zone fitting
#                               submitted as CHUNK_SIZE-zone blocks
#                               (each depends on J2 via afterok)
#   J4  stage4_analysis.pbs     CPU job,  4 h — GAN validation + SA-Only + outliers
#                               (depends on all J3 jobs via afterok)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PBS_DIR="${SCRIPT_DIR}/pbs"

# Defaults
TOTAL_ZONES=134
CHUNK_SIZE=10
DICT_OPTS=5
SKIP_GAN=false
SKIP_HOUSEHOLD=false
ONLY_ANALYSIS=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --total-zones)   TOTAL_ZONES="$2";   shift 2;;
    --chunk-size)    CHUNK_SIZE="$2";    shift 2;;
    --dict-opts)     DICT_OPTS="$2";     shift 2;;
    --skip-gan)      SKIP_GAN=true;      shift;;
    --skip-household) SKIP_HOUSEHOLD=true; shift;;
    --only-analysis) ONLY_ANALYSIS=true; shift;;
    *) echo "Unknown argument: $1"; exit 1;;
  esac
done

echo "========================================"
echo " Synthetic Population Pipeline Submitter"
echo "========================================"
echo " Script dir  : $SCRIPT_DIR"
echo " Total zones : $TOTAL_ZONES"
echo " Chunk size  : $CHUNK_SIZE"
echo " Dict opts   : $DICT_OPTS"
echo " Skip GAN    : $SKIP_GAN"
echo " Skip HH     : $SKIP_HOUSEHOLD"
echo " Only analysis: $ONLY_ANALYSIS"
echo "========================================"

# Convert Windows line endings if needed (safety measure)
find "$PBS_DIR" -name "*.pbs" -exec dos2unix {} + 2>/dev/null || true
dos2unix "$SCRIPT_DIR/submit_pipeline.sh" 2>/dev/null || true

# ---------------------------------------------------------------------------
# J1 — GAN training (GPU)
# ---------------------------------------------------------------------------
J1_ID=""
if ! $SKIP_GAN && ! $ONLY_ANALYSIS; then
  J1_ID=$(qsub "${PBS_DIR}/stage1_gan.pbs")
  echo "[J1] GAN training submitted: $J1_ID"
else
  echo "[J1] GAN training SKIPPED"
fi

# ---------------------------------------------------------------------------
# J2 — Household matching (CPU, depends on J1)
# ---------------------------------------------------------------------------
J2_ID=""
if ! $SKIP_HOUSEHOLD && ! $ONLY_ANALYSIS; then
  if [ -n "$J1_ID" ]; then
    J2_ID=$(qsub -W depend=afterok:"$J1_ID" "${PBS_DIR}/stage2_household.pbs")
  else
    J2_ID=$(qsub "${PBS_DIR}/stage2_household.pbs")
  fi
  echo "[J2] Household matching submitted: $J2_ID"
else
  echo "[J2] Household matching SKIPPED"
fi

# ---------------------------------------------------------------------------
# J3 — SA-GAN zone fitting (CPU, zone-chunked, each depends on J2)
# ---------------------------------------------------------------------------
J3_IDS=()
if ! $ONLY_ANALYSIS; then
  for ((START=0; START<TOTAL_ZONES; START+=CHUNK_SIZE)); do
    END=$((START + CHUNK_SIZE - 1))
    (( END >= TOTAL_ZONES )) && END=$((TOTAL_ZONES - 1))
    INDICES="${START}-${END}"

    if [ -n "$J2_ID" ]; then
      JID=$(qsub -v INDICES="$INDICES",DICT_OPTS=$DICT_OPTS \
                 -W depend=afterok:"$J2_ID" \
                 "${PBS_DIR}/stage3_sa_fitting.pbs")
    else
      JID=$(qsub -v INDICES="$INDICES",DICT_OPTS=$DICT_OPTS \
                 "${PBS_DIR}/stage3_sa_fitting.pbs")
    fi
    J3_IDS+=("$JID")
    echo "[J3] SA zones $INDICES submitted: $JID"
  done
fi

# ---------------------------------------------------------------------------
# J4 — Analysis (depends on all J3 jobs, or runs immediately if only-analysis)
# ---------------------------------------------------------------------------
if [ ${#J3_IDS[@]} -gt 0 ]; then
  DEPEND_STR=$(IFS=":"; echo "afterok:${J3_IDS[*]}")
  J4_ID=$(qsub -W depend="$DEPEND_STR" "${PBS_DIR}/stage4_analysis.pbs")
else
  J4_ID=$(qsub "${PBS_DIR}/stage4_analysis.pbs")
fi
echo "[J4] Analysis submitted: $J4_ID"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "========================================"
echo " All jobs submitted"
echo "========================================"
echo " J1 (GAN)       : ${J1_ID:-SKIPPED}"
echo " J2 (Household) : ${J2_ID:-SKIPPED}"
echo " J3 (SA zones)  : ${#J3_IDS[@]} jobs — $(IFS=','; echo "${J3_IDS[*]:-none}")"
echo " J4 (Analysis)  : $J4_ID"
echo ""
echo " Monitor with:  qstat -u $USER"
echo " View logs  :   ls ${PBS_DIR}/../*.o* ${PBS_DIR}/../*.e*"
echo " Results    :   ${SCRIPT_DIR}/outputs/"
echo "========================================"
