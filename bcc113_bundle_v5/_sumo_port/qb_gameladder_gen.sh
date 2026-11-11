#!/bin/bash
# qb_gameladder_gen.sh -- SUMO HPC half of the Aimsun KG GAME LADDER that is
# running now.
#
# PORTED FROM this Aimsun-console snippet (the Aimsun half, unchanged):
#
#   os.environ["FIXED_ARMS"] = (
#     "CHAMP_ADAPTIVE_AIMSUN_DSW,CHAMP_ADAPTIVE_DSW_MARL_BUS,"
#     "CHAMP_ADAPTIVE_DSW_CELLQ_GATED,CHAMP_ADAPTIVE_DSW_GAME_BUS,"
#     "CHAMP_ADAPTIVE_DSW_GAME_COOP,"
#     "CHAMP_ADAPTIVE_DSW_GAME_SOL_NULL_CTM2,"
#     "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2,"
#     "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL,"
#     "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL,"
#     "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2,"
#     "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2")
#   os.environ["FIXED_SEEDS"] = "300,400,500,600,700"
#   os.environ["FIXED_TRAIN_SEEDS"] = "800,900,1000,1100"
#   exec(open(r"...\run_game_ladder_kg.py").read())
#
# SEEDS AND TRAIN SEEDS ARE ALREADY IDENTICAL on this tree: sweep_arms.EVAL_SEEDS
# = [300,400,500,600,700] and TRAIN_SEEDS = [800,900,1000,1100]. So the port is
# the ARM SET plus the job plumbing, which is what this file does.
#
# WHAT MATCHES -- ALL 11 of the 11 arms, same name, same flags as Aimsun:
#   CHAMP_ADAPTIVE_AIMSUN_DSW      paper base, Aimsun parity overlay applied
#   CHAMP_ADAPTIVE_DSW_MARL_BUS    learner  -> train 800/900/1000/1100 first
#   CHAMP_ADAPTIVE_DSW_CELLQ_GATED learner  -> train 800/900/1000/1100 first
#   CHAMP_ADAPTIVE_DSW_GAME_BUS    M4 Nash bargain + corridor best response
#   CHAMP_ADAPTIVE_DSW_GAME_COOP   M5 cooperative game
#   CHAMP_ADAPTIVE_DSW_GAME_SOL_*_CTM2[_SPILL[_2]]  the six CTM2 payoff arms
# plus CHAMP_NO_TSP, because AGENTS RULE 3 forbids scoring an arm against a
# baseline from a different build or seed.
#
# THE CTM2 GAP IS CLOSED (2026-11-06): _game_ctm2_payoffs / _cbql_ctm_geom /
# _vlt_advance_vph plus _section_jam_frac + _phase_origin_dests and the
# congestion / bus-in-horizon gates are ported into shared_tsp_engine, and
# ctm_twoclass.py is the Aimsun copy (with out_cap_frac + cross_mult). The six
# _CTM2 arms therefore score the CTM2 model here too. Two documented deviations
# remain, and neither changes the payoff formula:
#   * _vlt_advance_vph: this tree has no vloop_layout module, so the ADVANCE-loop
#     arrival rate is the section's rolling-window crossing count; when that is
#     unmeasurable the function returns None and the payoff uses
#     _measured_section_flow_vph -- the SAME fallback Aimsun uses before its
#     loops are built.
#   * _phase_turn_targets is absent, so GAME_CTM2_SPILLBACK prices the DIRECT
#     turning TO-sections of each phase (via _phase_origin_dests), not the
#     multi-hop targets the Aimsun topology walk adds.
# The capability probe below still refuses the CTM2 arms on any tree that lacks
# those symbols, so this script can never quietly run legacy payoffs under a
# CTM2 name.
#
# USAGE (generation is pure file I/O -> safe locally on Windows, AGENTS RULE 1;
# only qsub is ever issued on the cluster):
#   bash qb_gameladder_gen.sh                     # write the full 11-arm + NO_TSP matrix
#   SUBMIT=1 bash qb_gameladder_gen.sh            # same, and qsub it (real login node only)
#   SKIP_UNPORTED=1 ...                           # still supported: drop unportable arms
#   DRY=1 ...                                     # write + verify, never qsub
#   ARMS=... SEEDS=300 bash ...                   # explicit subset / single seed
#   DEP=12345 SKIP_TRAIN=1 ...                    # chain learner evals on a train job
#
# Results: $BASE/parts/ladder_<SHORT>_eval<SEED>.csv, one file per run, so two
# jobs can never clobber each other's rows (the shared --out form is a
# lost-update race -- run_sweep_hpc._flush rewrites the whole file).
#
# WHY BAKED PBS AND NOT `qsub -v`: this PBS keeps only the LAST -v and silently
# discards the rest (verified: `-v A=1 -v B=2 -v C=3 -v D=4` arrives as D=4
# only, which killed jobs 27677851/52/54/55 in 17 s). Parameters are written as
# literal assignments into a per-job PBS and read straight back after writing.
set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="${BASE:-$SELF_DIR}"
GEN="${GEN:-$BASE/jobs}"
RPID="${RPID:-FPAXJW8067}"
CORR="${CORR:-kg}"
END="${END:-4500}"
SUBMIT="${SUBMIT:-0}"
DRY="${DRY:-0}"
DEP="${DEP:-}"
SKIP_TRAIN="${SKIP_TRAIN:-0}"
SKIP_UNPORTED="${SKIP_UNPORTED:-0}"
QT_WAIT_S="${QT_WAIT_S:-600}"

# The exact arm list of the Aimsun snippet, in its order.
AIMSUN_ARMS=(
  CHAMP_ADAPTIVE_AIMSUN_DSW
  CHAMP_ADAPTIVE_DSW_MARL_BUS
  CHAMP_ADAPTIVE_DSW_CELLQ_GATED
  CHAMP_ADAPTIVE_DSW_GAME_BUS
  CHAMP_ADAPTIVE_DSW_GAME_COOP
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NULL_CTM2
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL
  CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2
  CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2
)

# Present on this fork, same name, same flags as the Aimsun arm.
PORTABLE=(
  CHAMP_NO_TSP
  CHAMP_ADAPTIVE_AIMSUN_DSW
  CHAMP_ADAPTIVE_DSW_MARL_BUS
  CHAMP_ADAPTIVE_DSW_CELLQ_GATED
  CHAMP_ADAPTIVE_DSW_GAME_BUS
  CHAMP_ADAPTIVE_DSW_GAME_COOP
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NULL_CTM2
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL
  CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL
  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2
  CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2
)

# Snippet arms that cannot run here. Empty since the CTM2 port (2026-11-06);
# kept so the gate keeps explaining itself if an arm is ever unported again.
UNPORTED=()

# Members of sweep_arms.CHAMPION_LEARNING_ARMS within the portable set. Kept in
# sync by hand because NOTHING may run python on the login node (AGENTS RULE 1);
# the generated job re-derives this from sweep_arms at runtime and aborts on a
# mismatch, so drift fails loudly instead of cold-starting a learner.
LEARNER_ARMS=(
  CHAMP_ADAPTIVE_DSW_MARL_BUS
  CHAMP_ADAPTIVE_DSW_CELLQ_GATED
)

contains () { local n="$1"; shift; local x; for x in "$@"; do [ "$x" = "$n" ] && return 0; done; return 1; }

if [ -n "${ARMS:-}" ]; then
  read -ra LIST <<< "${ARMS//,/ }"
else
  LIST=("${AIMSUN_ARMS[@]}")
fi
SEEDS_CSV="${SEEDS:-300,400,500,600,700}"
TRAIN_CSV="${TRAIN_SEEDS:-800,900,1000,1100}"
read -ra SEEDL <<< "${SEEDS_CSV//,/ }"

# ---- CTM2 capability probe --------------------------------------------------
# (grep only -- nothing may run an interpreter on the login node, AGENTS RULE 1)
# A _CTM2[_SPILL[_2]] arm only means what its name says when the engine carries
# the two-class CTM payoffs; without them it logs [GAME_CTM2_NA] and decides on
# LEGACY payoffs, i.e. a different strategy under the CTM2 name.
WANT_CTM2=0
for a in "${LIST[@]}"; do
  case "$a" in *_CTM2|*_CTM2_SPILL|*_CTM2_SPILL2) WANT_CTM2=1 ;; esac
done
if [ "$WANT_CTM2" = "1" ]; then
  ENG="$BASE/shared_tsp_engine/engine.py"
  SPM="$BASE/shared_tsp_engine/specialized_modes.py"
  MISSING=""
  for sym in _game_ctm2_payoffs _cbql_ctm_geom _vlt_advance_vph \
             _section_jam_frac _phase_origin_dests; do
    grep -q "def ${sym}(" "$ENG" 2>/dev/null || MISSING="$MISSING $sym"
  done
  grep -q 'GAME_CTM2_SPILLBACK' "$ENG" 2>/dev/null || MISSING="$MISSING GAME_CTM2_SPILLBACK"
  grep -q 'GAME_BUS_IN_HORIZON' "$SPM" 2>/dev/null || MISSING="$MISSING GAME_BUS_IN_HORIZON"
  grep -q 'GAME_CONGESTION_GATE' "$SPM" 2>/dev/null || MISSING="$MISSING GAME_CONGESTION_GATE"
  if [ -n "$MISSING" ]; then
    echo "== CTM2 arms requested but $BASE lacks:$MISSING"
    echo "   -> the engine would log [GAME_CTM2_NA] and decide on LEGACY payoffs."
    echo "   Nothing written. Port the stack first (on Windows, not the login node):"
    echo "     python _sumo_port/port_ctm2.py && python _sumo_port/port_ctm2_arms.py"
    exit 1
  fi
  echo "CTM2 capability probe: ok (payoffs + spillback + congestion/bus gates present)"
fi

# ---- portability gate -------------------------------------------------------
BAD=()
for a in "${LIST[@]}"; do
  contains "$a" "${PORTABLE[@]}" || BAD+=("$a")
done
if [ "${#BAD[@]}" -gt 0 ]; then
  echo "== NOT PORTABLE on this fork (${#BAD[@]} of ${#LIST[@]} requested arms) =="
  for a in "${BAD[@]}"; do
    if contains "$a" "${UNPORTED[@]}"; then
      echo "   $a"
      echo "      needs GAME_PAYOFF_MODEL='ctm2' (_game_ctm2_payoffs <- _cbql_ctm_geom/_vlt_advance_vph)"
      case "$a" in
        *_SPILL2) echo "      + GAME_CTM2_SPILLBACK, GAME_CONGESTION_GATE/MAX_JAM, GAME_CROSS_STARVE_MULT" ;;
        *_SPILL)  echo "      + GAME_CTM2_SPILLBACK, GAME_BUS_IN_HORIZON, GAME_CONGESTION_GATE" ;;
      esac
      echo "      -> running it here would log [GAME_CTM2_NA] and decide on LEGACY payoffs,"
      echo "         i.e. a different strategy under the CTM2 name. Refused."
    else
      echo "   $a  -- not in this build's arm table at all"
    fi
  done
  if [ "$SKIP_UNPORTED" != "1" ]; then
    echo
    echo "Nothing written. Choose one:"
    echo "  * run the portable subset:   SKIP_UNPORTED=1 bash $0"
    echo "  * compare the payoff model on both platforms with the LEGACY twins, which"
    echo "    do exist on both sides:    ARMS=CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH,... bash $0"
    echo "  * or port _game_ctm2_payoffs first (needs _cbql_ctm_geom/_vlt_advance_vph)."
    exit 1
  fi
  KEEP=()
  for a in "${LIST[@]}"; do contains "$a" "${PORTABLE[@]}" && KEEP+=("$a"); done
  LIST=("${KEEP[@]}")
  echo "   SKIP_UNPORTED=1 -> running ${#LIST[@]} arm(s): ${LIST[*]}"
  echo
fi

if [ "$CORR" = "kg" ]; then
  SCEN=kg_scenario
else
  CORR=logan_road_new
  SCEN=logan_scenario_realtls
fi

mkdir -p "$GEN" "$BASE/parts" || exit 1

# THE JOB BODY. Everything above BODY is per-job and baked; the body comes from a
# quoted heredoc so none of its ${...} is expanded at generation time.
#   emit_job <mode> <arm> <seed> <dep> <dest>
emit_job () {
  local mode="$1" arm="$2" seed="$3" dep="$4" dest="$5"
  local short="${arm#CHAMP_ADAPTIVE_DSW_}"
  short="${short#CHAMP_}"
  local jname="gl_${short}"
  [ "$mode" = "train" ] && jname="${jname}_tr" || jname="${jname}_${seed}"
  local wall="02:30:00"
  [ "$mode" = "train" ] && wall="03:00:00"
  {
    cat <<HDR
#!/bin/bash
#PBS -N ${jname}
#PBS -l select=1:ncpus=4:mem=16gb
#PBS -l walltime=${wall}
#PBS -j oe
#PBS -m be
HDR
    if [ -n "$dep" ]; then
      echo "#PBS -W depend=afterok:${dep}"
    fi
    cat <<HDR
#
# GENERATED by qb_gameladder_gen.sh -- do not edit; regenerate instead.
# Parameters are baked literals: no -v, nothing to drop.
MODE=${mode}
CORR=${CORR}
SCEN=${SCEN}
ARM=${arm}
SHORT=${short}
SEED=${seed}
END=${END}
TRAIN_SEEDS=${TRAIN_CSV}
QT_WAIT_S=${QT_WAIT_S}
HDR
    cat <<'BODY'

if [ -z "${BASE:-}" ]; then
  if [ -d /home/ahernz/tsp/sumo_hpc/sumo_bridge ]; then
    BASE=/home/ahernz/tsp/sumo_hpc
  else
    BASE=/scratch/ki13/za6261/tsp/sumo_hpc
  fi
fi
export BASE
cd "$BASE/sumo_bridge" || exit 1

if [ -z "${VENV:-}" ]; then
  if [ -f "$BASE/venv-gadi/bin/activate" ]; then
    VENV="$BASE/venv-gadi"
  else
    VENV="$BASE/venv"
  fi
fi
export VENV
source "$VENV/bin/activate"
_GADI_SUMO=/scratch/ki13/za6261/sumo-gadi
if [ -x "$_GADI_SUMO/bin/sumo" ]; then
    export SUMO_HOME="$_GADI_SUMO/share/sumo"
    export PATH="$_GADI_SUMO/bin:$PATH"
else
    export SUMO_HOME=${VENV:-$BASE/venv-gadi}/lib/python3.12/site-packages/sumo
    export PATH=$SUMO_HOME/bin:$PATH
fi
unset _GADI_SUMO
export PYTHONUTF8=1
export MPLBACKEND=Agg

# Baked values. Anything empty here means the generator wrote a bad file, so the
# job fails immediately and loudly instead of simulating a default search.
: "${MODE:?empty MODE in generated script - regenerate with qb_gameladder_gen.sh}"
: "${ARM:?empty ARM in generated script - regenerate with qb_gameladder_gen.sh}"
: "${CORR:?empty CORR in generated script - regenerate with qb_gameladder_gen.sh}"
: "${SCEN:?empty SCEN in generated script - regenerate with qb_gameladder_gen.sh}"
END="${END:-4500}"

case "$ARM" in
  CHAMP_*) : ;;
  *) echo "!! ARM does not look like a champion arm: [$ARM]"; exit 1 ;;
esac
case "$MODE" in
  train|eval) : ;;
  *) echo "!! MODE must be train|eval, got [$MODE]"; exit 1 ;;
esac
if [ "$MODE" = "eval" ]; then
  case "$SEED" in
    ''|*[!0-9]*) echo "!! SEED is not an integer: [$SEED]"; exit 1 ;;
  esac
fi

export CORRIDOR="$CORR"
if [ "$CORR" = "kg" ]; then
  QDIR="$BASE/kg/qtables/$SCEN"
else
  QDIR="$BASE/logan_road_new/qtables/$SCEN"
fi

# OUT embeds the seed: run_sweep_hpc._flush opens --out with mode "w" and
# rewrites every row it holds, so two runs sharing one --out are a lost-update
# race and a finished seed can silently vanish.
if [ "$MODE" = "train" ]; then
  OUT="$BASE/parts/ladder_${SHORT}_train.csv"
else
  OUT="$BASE/parts/ladder_${SHORT}_eval${SEED}.csv"
fi
mkdir -p "$BASE/parts"

echo "== $(hostname) $(date) mode=$MODE arm=$ARM seed=$SEED corr=$CORR scen=$SCEN end=$END =="
echo "   (baked: no -v was used to get these values)"
grep -m1 '^ENGINE_BUILD' "$BASE/shared_tsp_engine/engine.py"
grep -m1 '^GAME_SOLUTION' "$BASE/shared_tsp_engine/specialized_modes.py"
grep -m1 '^GAME_PAYOFF_MODEL' "$BASE/shared_tsp_engine/specialized_modes.py"
echo "   -> $OUT"

# Learner status comes from sweep_arms.LEARNING_ARMS, the single source of
# truth -- never a name heuristic, which silently classified CHAMP_CTM_MULTI &
# friends wrong and cold-started them.
IS_LEARNER=$(python - "$ARM" <<'PY'
import sys
from sweep_arms import CHAMPION_LEARNING_ARMS as L, LEARNING_ARMS
print("1" if sys.argv[1] in L or sys.argv[1] in LEARNING_ARMS else "0")
PY
)
if [ -z "$IS_LEARNER" ]; then
  echo "!! ABORT: could not classify $ARM as learner/non-learner (sweep_arms query failed)."
  echo "!! A missed learner would cold-start and invalidate the arm."
  exit 4
fi

if [ "$MODE" = "train" ]; then
  if [ "$IS_LEARNER" != "1" ]; then
    echo "== $ARM is not a learner on this build; no training needed (nothing to do) =="
    exit 0
  fi
  # Owns the qtable wipe. --eval-seeds "" is load-bearing: without it the arm
  # runs TRAIN_SEEDS + every EVAL_SEED in one job and is always killed.
  echo "== train seeds $TRAIN_SEEDS (warming $QDIR) =="
  python run_sweep_hpc.py --corridor "$CORR" --scenario "$SCEN" \
      --arms "$ARM" --seeds 300 --train-seeds "$TRAIN_SEEDS" --eval-seeds "" \
      --end "$END" --jobs 1 --resume --out "$OUT" \
      || { echo "!! train FAILED arm=$ARM"; exit 1; }
  ls -la "$QDIR" 2>/dev/null | head -5
  echo "== train done $(date) =="
  exit 0
fi

# ---- eval: one seed per job, never wiping the trained table ----
if [ "$IS_LEARNER" = "1" ]; then
  QT="$QDIR/$ARM.pkl"
  echo "== eval seed $SEED; Q-table guard: $QT (wait <=${QT_WAIT_S}s) =="
  t0=$(date +%s)
  while [ ! -s "$QT" ]; do
    now=$(date +%s)
    if [ $((now - t0)) -ge "${QT_WAIT_S}" ]; then
      echo "!! ABORT: no trained Q-table at $QT after ${QT_WAIT_S}s."
      echo "!! A cold-start eval would silently invalidate this learner arm."
      echo "!! Submit jobs/ladder_train_${SHORT}.pbs first (or chain this job with"
      echo "!! afterok:<train jobid>)."
      exit 3
    fi
    sleep 10
  done
  echo "   Q-table present: $(ls -la "$QT" | awk '{print $5" bytes, mtime "$6" "$7}')"
else
  echo "== eval seed $SEED; non-learner arm ($ARM): no Q-table needed =="
fi

python run_sweep_hpc.py --corridor "$CORR" --scenario "$SCEN" \
    --arms "$ARM" --seeds "$SEED" --skip-train --eval-seeds "$SEED" \
    --end "$END" --jobs 1 --keep-qtables --resume --out "$OUT" \
    || { echo "!! eval FAILED arm=$ARM seed=$SEED"; exit 1; }

echo "== rows =="
python - "$OUT" <<'PY'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
for r in rows:
    print("  %-34s seed=%s phase=%s ok=%s obj=%s paxh=%s"
          % (r.get("arm"), r.get("seed"), r.get("phase"), r.get("ok"),
             r.get("obj_pax_per_delay_hr"), r.get("avg_total_pass_delay_hr")))
print("  %d row(s)" % len(rows))
PY
echo "== done $(date) =="
BODY
  } > "$dest"
}

# qsub if we have it, otherwise print the allowlisted ssh form (AGENTS RULE 1:
# only qsub/qstat may run on the login node -- never python, never a script).
submit_job () {
  local pbs="$1" dep="$2" out
  # Printed commands must name the CLUSTER path, not the Z: mount we generate on.
  local cpbs="${pbs/#$BASE//home/ahernz/tsp/sumo_hpc}"
  if [ "$SUBMIT" != "1" ] || [ "$DRY" = "1" ]; then
    if [ -n "$dep" ]; then
      echo "   [not submitted] ssh aqua-auto \"qsub -P $RPID -W depend=afterok:$dep $cpbs\""
    else
      echo "   [not submitted] ssh aqua-auto \"qsub -P $RPID $cpbs\""
    fi
    return 0
  fi
  if ! command -v qsub >/dev/null 2>&1; then
    echo "!! SUBMIT=1 but no qsub on this host. Generate here and submit from a"
    echo "!! cluster shell, or run:  ssh aqua-auto \"qsub -P $RPID $pbs\""
    return 1
  fi
  if [ -n "$dep" ]; then
    out=$(qsub -P "$RPID" -W depend=afterok:"$dep" "$pbs" 2>&1)
  else
    out=$(qsub -P "$RPID" "$pbs" 2>&1)
  fi
  echo "   $out"
  case "$out" in
    *[0-9].aqua*) LAST_JOB="${out%%.*}"; return 0 ;;
    *) echo "!! qsub rejected $pbs: $out"; return 1 ;;
  esac
}

verify_baked () {
  local pbs="$1" arm="$2" seed="$3" mode="$4" corr="$5"
  local g_arm g_seed g_mode g_corr
  g_arm=$(sed -n 's/^ARM=//p' "$pbs" | head -1)
  g_seed=$(sed -n 's/^SEED=//p' "$pbs" | head -1)
  g_mode=$(sed -n 's/^MODE=//p' "$pbs" | head -1)
  g_corr=$(sed -n 's/^CORR=//p' "$pbs" | head -1)
  if [ "$g_arm" != "$arm" ] || [ "$g_seed" != "$seed" ] \
     || [ "$g_mode" != "$mode" ] || [ "$g_corr" != "$corr" ]; then
    echo "!! baked-value mismatch in $pbs (arm=[$g_arm] seed=[$g_seed] mode=[$g_mode] corr=[$g_corr])"
    return 1
  fi
  grep -Eq 'qsub[[:space:]]+-v' "$pbs" && { echo "!! $pbs still passes -v; the baked form must not"; return 1; }
  bash -n "$pbs" || { echo "!! syntax error in $pbs"; return 1; }
  return 0
}

echo "corridor=$CORR scen=$SCEN end=$END arms=${#LIST[@]} seeds=${SEEDL[*]} train=${TRAIN_CSV} gen=$GEN"
echo

# ---- phase 1: training jobs for learners (they own the qtable wipe) ----------
LAST_JOB=""
TRAIN_DEP=""
N_TRAIN=0
if [ "$SKIP_TRAIN" = "1" ] && [ -n "$DEP" ]; then
  TRAIN_DEP="$DEP"
  echo "phase 1: SKIP_TRAIN=1 DEP=$DEP -> learner evals chain on $DEP"
elif [ "$SKIP_TRAIN" != "1" ]; then
  echo "phase 1: learner training (seeds $TRAIN_CSV)"
  for a in "${LIST[@]}"; do
    # Sweep every arm so a non-learner train file is a no-op; only learners warm.
    short="${a#CHAMP_ADAPTIVE_DSW_}"; short="${short#CHAMP_}"
    pbs="$GEN/ladder_train_${short}.pbs"
    emit_job train "$a" 0 "" "$pbs" || { echo "!! could not write $pbs"; exit 1; }
    verify_baked "$pbs" "$a" 0 train "$CORR" || exit 1
    if contains "$a" "${LEARNER_ARMS[@]}"; then
      submit_job "$pbs" "" || exit 1
      # PBS takes a COLON-separated depend list (afterok:a:b), not commas.
      [ -n "${LAST_JOB:-}" ] && TRAIN_DEP="${TRAIN_DEP:+$TRAIN_DEP:}${LAST_JOB}"
      N_TRAIN=$((N_TRAIN + 1))
    else
      echo "   (non-learner: $pbs written, no work to do)"
    fi
  done
fi
echo

# ---- phase 2: one eval job per (arm, seed) ---------------------------------
echo "phase 2: evals (${#LIST[@]} arms x ${#SEEDL[@]} seeds)"
# One dep for every learner eval: with more than one train job the ids are a
# comma list, which PBS reads as "wait for all of these".
DEP_FOR_LEARNER="${TRAIN_DEP:-$DEP}"
N=0
for a in "${LIST[@]}"; do
  short="${a#CHAMP_ADAPTIVE_DSW_}"; short="${short#CHAMP_}"
  for s in "${SEEDL[@]}"; do
    pbs="$GEN/ladder_${short}_eval${s}.pbs"
    dep=""
    if contains "$a" "${LEARNER_ARMS[@]}"; then dep="$DEP_FOR_LEARNER"; fi
    emit_job eval "$a" "$s" "$dep" "$pbs" || { echo "!! could not write $pbs"; exit 1; }
    verify_baked "$pbs" "$a" "$s" eval "$CORR" || exit 1
    submit_job "$pbs" "$dep" || exit 1
    N=$((N + 1))
  done
done

echo
echo "$N eval job(s) + ${N_TRAIN} train job(s) written to $GEN"
if [ "$N_TRAIN" -gt 0 ] && [ -z "$DEP_FOR_LEARNER" ]; then
  echo "!! learner evals were generated WITHOUT a dependency: submit the two"
  echo "!! ladder_train_*.pbs jobs first, or regenerate the evals with"
  echo "!!   DEP=<trainjobid> SKIP_TRAIN=1 bash $0"
  echo "!! (the eval jobs do poll for the Q-table, but only for ${QT_WAIT_S}s)."
fi
[ "$SUBMIT" = "1" ] || echo "not submitted (SUBMIT=1 to qsub)"
echo "watch:  qstat -u ahernz | grep gl_"
echo "score:  python _sumo_port/compare_game_solution.py --seeds ${SEEDS_CSV}   (locally, on Windows)"
