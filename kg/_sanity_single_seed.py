# =============================================================================
# _sanity_single_seed.py â€” quick sanity check for the car-cost fix in
# shared_tsp_engine/engine.py (_measured_network_cost_factor).
#
# Runs ONE seed over a tiny experiment set: the no-TSP baseline plus a couple
# of TSP methods, so you can confirm the TSP firing rate dropped after the
# patch and that actions now show a real network passenger cost.
#
# Run from Aimsun's "Run Script" menu (same as batch_runner_gui.py).
# Writes to a SEPARATE csv (batch_results_gui_sanity.csv) so it never
# overwrites your real `batch_results_gui.csv`.
# =============================================================================
import os as _os
import sys as _sys
import time as _time
import importlib.util as _ilu
from PyANGKernel import GKSystem

try:
    _SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
except NameError:
    _model = GKSystem.getSystem().getActiveModel()
    _SCRIPT_DIR = _model.getDocumentDirectory().absolutePath()

if _SCRIPT_DIR not in _sys.path:
    _sys.path.insert(0, _SCRIPT_DIR)

# Import the same helpers batch_runner_gui.py uses.
_br_path = _os.path.join(_SCRIPT_DIR, "batch_runner.py")
_spec = _ilu.spec_from_file_location("_br_gui", _br_path)
_br = _ilu.module_from_spec(_spec)
_sys.modules["_br_gui"] = _br
try:
    _spec.loader.exec_module(_br)
except SystemExit:
    pass

log = _br.log
set_control_mode = _br.set_control_mode
set_coordinated = _br.set_coordinated
set_coordination_algo = _br.set_coordination_algo
set_seed = _br.set_seed
set_reward_weights = _br.set_reward_weights
set_demand_scalar = _br.set_demand_scalar
write_run_config = _br.write_run_config
collect_run_metrics = _br.collect_run_metrics
append_master_csv = _br.append_master_csv
get_first_replication = _br.get_first_replication
run_replication = _br.run_replication
_purge_pyc = _br._purge_pyc
_set_logging = _br._set_logging

CONTROLLER_PATH = _br.CONTROLLER_PATH
RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
PROJECT_DIR = _br.PROJECT_DIR

SANITY_CSV = _os.path.join(_SCRIPT_DIR, "batch_results_gui_sanity.csv")

SEED = 800
DEMAND_SCALAR = 1.0

# ── Signal-Sequencing family base (mirrors batch_runner_signal_sequencing.py
# _SS_BASE + X3) — verifies the SWAPS/TIMES/BOTH mode-axis fix (#2):
# the three families must produce DIFFERENT KPIs (they used to be byte-identical
# because ZIG_ENABLE_SEQ/GR and PHASE_ROTATION_MODE were never read).
_SS_BASE_X3 = {
    "GLOBAL_REWARD_MODE":            True,
    "BARGAIN_SPM_MODE":              False,
    "DCTSP_ZIG_MODE":                True,
    "META_TSP_MODE":                 False,
    "MDN_DELAY_MODE":                False,
    "HS_EXT_MODE":                   False,
    "DCTSP_GREEN_REALLOC_MODE":      True,
    "GREEN_REALLOC_RECOVER_FRACTION":1.0,
    "BUS_PREDICTOR_TYPE":            "ADAPTIVE_KALMAN",
    "ZIG_BALANCE_FACTOR":            1.0,
    "NETWORK_FACTOR":                1.0,
    "NETWORK_FACTOR_DENSITY_RAMP":   False,
    "ZIG_PHASE_OVERLAP_S":           0.5,
    "ZIG_MIN_GAIN_S":                1.0,
    "WOBJ_ALPHA":                    1.0,
    "WOBJ_BETA":                     0.0,
    "WOBJ_GAMMA":                    0.0,
    "WOBJ_Z1_SCALE":                 3000000.0,
    "WOBJ_Z2_SCALE":                 7500.0,
    "WOBJ_Z3_SCALE":                 12000.0,
    "DETECTION_WINDOW_M_OVERRIDE":   50.0,
    "ZIG_ENABLE_GE":                 False,
    "ZIG_ENABLE_INS":                False,
    "ZIG_ENABLE_GR":                 False,
    "ZIG_ENABLE_SEQ":                False,
    "PHASE_ROTATION_MODE":           False,
    "PHASE_ROTATION_N_SEQS":         3.0,
    "PHASE_ROTATION_THRESHOLD_S":    5.0,
    "TSP_CYCLE_LENGTH_OVERRIDE_S":   45.0,
    "PHASE_SEQ_MAX_PER_CYCLE":       3,
}

_SS_FAMILY = {
    "SWAPS": {"ZIG_ENABLE_SEQ": True,  "ZIG_ENABLE_GR": False,
              "PHASE_ROTATION_MODE": True},
    "TIMES": {"ZIG_ENABLE_SEQ": False, "ZIG_ENABLE_GR": True,
              "PHASE_ROTATION_MODE": False},
    "BOTH":  {"ZIG_ENABLE_SEQ": True,  "ZIG_ENABLE_GR": True,
              "PHASE_ROTATION_MODE": True},
}


def _ss_exp(name, family):
    ov = dict(_SS_BASE_X3)
    ov.update(_SS_FAMILY[family])
    return {
        "name": name,
        "strategy": "GLOBAL_REWARD",
        "method": f"SS_{family}",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": ov,
        "method_overrides": {},
    }


EXPERIMENTS = [
    {
        "name": "NO_TSP_BUSX2",
        "strategy": "NORMAL",
        "method": "NO_TSP",
        "coordinated": False,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {},
        "method_overrides": {},
    },
    {
        "name": "GR_BASE_X3_BUSX2",
        "strategy": "GLOBAL_REWARD",
        "method": "NO_BASE_RL",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True,
            "PARETO_SELECTION_MODE": True,
            "Z4_CONSTRAINT_MODE": True,
            "Z4_TOLERANCE_VEH_S": 90.0,
            "REWARD_FUTURE_HORIZON_CYCLES": 1.0,
            "REWARD_FUTURE_DEBT_GAIN": 0.35,
            "REWARD_FUTURE_OFFSET_GAIN": 0.2,
            "CROSS_TRAFFIC_COST_MULTIPLIER": 2.0,
            "TSP_CYCLE_LENGTH_OVERRIDE_S": 45.0,
            "PHASE_SEQ_MAX_PER_CYCLE": 3,
        },
        "method_overrides": {},
    },
    {
        "name": "GR_PASSIVE_X3_BUSX2",
        "strategy": "GLOBAL_REWARD",
        "method": "NO_BASE_RL",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True,
            "PARETO_SELECTION_MODE": True,
            "Z4_CONSTRAINT_MODE": True,
            "Z4_TOLERANCE_VEH_S": 90.0,
            "REWARD_FUTURE_HORIZON_CYCLES": 1.0,
            "REWARD_FUTURE_DEBT_GAIN": 0.35,
            "REWARD_FUTURE_OFFSET_GAIN": 0.2,
            "CROSS_TRAFFIC_COST_MULTIPLIER": 2.0,
            "TSP_CYCLE_LENGTH_OVERRIDE_S": 45.0,
            "PHASE_SEQ_MAX_PER_CYCLE": 3,
            "REWARD_TSP_ENABLE_GE": False,
            "REWARD_TSP_ENABLE_INS": False,
        },
        "method_overrides": {},
    },
    {
        "name": "CTMGS_X3_BUSX2",
        "strategy": "GLOBAL_REWARD",
        "method": "CTMGS",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True,
            "PARETO_SELECTION_MODE": True,
            "Z4_CONSTRAINT_MODE": True,
            "Z4_TOLERANCE_VEH_S": 90.0,
            "REWARD_FUTURE_HORIZON_CYCLES": 1.0,
            "REWARD_FUTURE_DEBT_GAIN": 0.35,
            "REWARD_FUTURE_OFFSET_GAIN": 0.2,
            "CROSS_TRAFFIC_COST_MULTIPLIER": 2.0,
        },
        "method_overrides": {
            "MP_ECTM_MODE": True,
            "MP_ECTM_DT_S": 1.0,
            "MP_ECTM_MIN_EXT_S": 3.0,
            "MP_ECTM_MAX_EXT_S": 12.0,
            "MP_ECTM_CAR_OCC": 1.2,
            "MP_ECTM_BALANCE_FACTOR": 0.75,
            "TSP_CYCLE_LENGTH_OVERRIDE_S": 45.0,
            "PHASE_SEQ_MAX_PER_CYCLE": 3,
        },
    },
    {
        "name": "CTMGS_DP_X3_BUSX2",
        "strategy": "GLOBAL_REWARD",
        "method": "CTMGS_DP",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True,
            "PARETO_SELECTION_MODE": True,
            "Z4_CONSTRAINT_MODE": True,
            "Z4_TOLERANCE_VEH_S": 90.0,
            "REWARD_FUTURE_HORIZON_CYCLES": 1.0,
            "REWARD_FUTURE_DEBT_GAIN": 0.35,
            "REWARD_FUTURE_OFFSET_GAIN": 0.2,
            "CROSS_TRAFFIC_COST_MULTIPLIER": 2.0,
        },
        "method_overrides": {
            "MP_ECTM_DP_MODE": True,
            "MP_ECTM_DT_S": 1.0,
            "MP_ECTM_MIN_EXT_S": 3.0,
            "MP_ECTM_MAX_EXT_S": 12.0,
            "MP_ECTM_CAR_OCC": 1.2,
            "MP_ECTM_BALANCE_FACTOR": 0.75,
            "MP_ECTM_DP_HORIZON_S": 90.0,
            "MP_ECTM_DP_STAGE_S": 15.0,
            "MP_ECTM_DP_COORD_WEIGHT": 0.40,
            "TSP_CYCLE_LENGTH_OVERRIDE_S": 45.0,
            "PHASE_SEQ_MAX_PER_CYCLE": 3,
        },
    },
    {
        "name": "CELLQLEARN_X3_BUSX2",
        "strategy": "GLOBAL_REWARD",
        "method": "CELLQLEARN_DP",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True,
            "PARETO_SELECTION_MODE": True,
            "Z4_CONSTRAINT_MODE": True,
            "Z4_TOLERANCE_VEH_S": 90.0,
            "REWARD_FUTURE_HORIZON_CYCLES": 1.0,
            "REWARD_FUTURE_DEBT_GAIN": 0.35,
            "REWARD_FUTURE_OFFSET_GAIN": 0.2,
            "CROSS_TRAFFIC_COST_MULTIPLIER": 2.0,
        },
        "method_overrides": {
            "CELLQLEARN_DP_MODE": True,
            "CELLQLEARN_DP_DT_S": 1.0,
            "CELLQLEARN_DP_HORIZON_S": 90.0,
            "CELLQLEARN_DP_STAGE_S": 15.0,
            "CELLQLEARN_DP_COORD_WEIGHT": 0.22,
            "CELLQLEARN_DP_CAR_OCC": 1.2,
            "CELLQLEARN_DP_BALANCE_FACTOR": 0.75,
            "TSP_CYCLE_LENGTH_OVERRIDE_S": 45.0,
            "PHASE_SEQ_MAX_PER_CYCLE": 3,
        },
    },
    {
        "name": "BXT_X3_BUSX2",
        "strategy": "GLOBAL_REWARD",
        "method": "BXT",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True,
            "PARETO_SELECTION_MODE": True,
            "Z4_CONSTRAINT_MODE": True,
            "Z4_TOLERANCE_VEH_S": 90.0,
            "REWARD_FUTURE_HORIZON_CYCLES": 1.0,
            "REWARD_FUTURE_DEBT_GAIN": 0.35,
            "REWARD_FUTURE_OFFSET_GAIN": 0.2,
            "CROSS_TRAFFIC_COST_MULTIPLIER": 2.0,
        },
        "method_overrides": {
            "BXT_MODE": True,
            "BXT_DT_S": 1.0,
            "BXT_EPSILON": 0.1,
            "BXT_ALPHA": 0.01,
            "BXT_GAMMA": 0.005,
            "BXT_CAR_OCC": 1.2,
            "BXT_BALANCE_FACTOR": 0.75,
            "TSP_CYCLE_LENGTH_OVERRIDE_S": 45.0,
            "PHASE_SEQ_MAX_PER_CYCLE": 3,
        },
    },
    # ── Mode-axis fix (#2): SWAPS/TIMES/BOTH must differ ────────────────
    _ss_exp("SS_SWAPS_X3", "SWAPS"),
    _ss_exp("SS_TIMES_X3", "TIMES"),
    _ss_exp("SS_BOTH_X3",  "BOTH"),
    # ── WOBJ_ALPHA=0 falsy fix (#5a) + WOBJ_Z*_SCALE wiring (#5c): with
    # WOBJ_ALPHA=0.0 the Z1 term must be ignored (pre-fix it read as 1.0).
    {
        "name": "WS_Z1_0p00",
        "strategy": "GLOBAL_REWARD",
        "method": "WG_NO_Z1",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True,
            "DCTSP_ZIG_MODE": True,
            "WOBJ_ALPHA": 0.0,
            "WOBJ_BETA": 0.5,
            "WOBJ_GAMMA": 0.5,
            "WOBJ_Z1_SCALE": 3000000.0,
            "WOBJ_Z2_SCALE": 7500.0,
            "WOBJ_Z3_SCALE": 12000.0,
            "ZIG_ENABLE_GE": True,
            "ZIG_ENABLE_INS": True,
            "ZIG_ENABLE_GR": True,
            "ZIG_ENABLE_SEQ": True,
            "PHASE_ROTATION_MODE": True,
            "PARETO_SELECTION_MODE": True,
            "Z4_CONSTRAINT_MODE": True,
            "Z4_TOLERANCE_VEH_S": 90.0,
            "CROSS_TRAFFIC_COST_MULTIPLIER": 2.0,
            "TSP_CYCLE_LENGTH_OVERRIDE_S": 45.0,
            "PHASE_SEQ_MAX_PER_CYCLE": 3,
        },
        "method_overrides": {},
    },
    # ── CPD-QL keys (#5d): DCTSP_W_H / DCTSP_CAR_WEIGHT now feed the reward
    # blend in _dctsp_eval_action (previously dead keys).
    {
        "name": "CPDQL_WH50",
        "strategy": "GLOBAL_REWARD",
        "method": "CPD_QL",
        "coordinated": True,
        "coordination_algo": "KALMAN",
        "active_intersections": None,
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True,
            "REWARD_ALPHA": 1.0,
            "REWARD_BETA": 1.0,
            "REWARD_GAMMA": 1.0,
            "DCTSP_W_H": 0.50,
            "DCTSP_CAR_WEIGHT": 1.00,
            "DCTSP_GREEN_REALLOC_MODE": True,
            "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "ZIG_ENABLE_GE": True,
            "ZIG_ENABLE_INS": True,
            "ZIG_ENABLE_GR": True,
            "ZIG_ENABLE_SEQ": True,
            "PHASE_ROTATION_MODE": True,
            "PARETO_SELECTION_MODE": True,
            "Z4_CONSTRAINT_MODE": True,
            "Z4_TOLERANCE_VEH_S": 90.0,
            "CROSS_TRAFFIC_COST_MULTIPLIER": 2.0,
            "TSP_CYCLE_LENGTH_OVERRIDE_S": 45.0,
            "PHASE_SEQ_MAX_PER_CYCLE": 3,
        },
        "method_overrides": {},
    },
]


def _main():
    rep = get_first_replication()
    failures = []
    base_demands = {}
    rows = []

    # Start from a clean slate: the sanity CSV is append-only across every
    # code state ever run, so comparisons against old rows are meaningless.
    try:
        if _os.path.isfile(SANITY_CSV):
            _os.remove(SANITY_CSV)
            print(f"[SANITY] Deleted stale results: {_os.path.basename(SANITY_CSV)}")
    except Exception as _e:
        print(f"[SANITY] WARNING could not remove stale CSV: {_e}")

    try:
        set_demand_scalar(DEMAND_SCALAR, base_demands)
    except Exception as _e:
        print(f"[SANITY] WARNING demand scalar: {_e}")

    try:
        _set_logging(CONTROLLER_PATH, enabled=False)
    except Exception as _e:
        print(f"[SANITY] WARNING could not disable logging: {_e}")

    try:
        for exp in EXPERIMENTS:
            exp_name = exp["name"]
            strategy = exp["strategy"]
            coordinated = exp.get("coordinated", False)
            coord_algo = exp.get("coordination_algo", "KALMAN")
            reward_overrides = dict(exp.get("reward_overrides", {}) or {})
            reward_overrides.update(exp.get("method_overrides", {}) or {})
            is_baseline = (strategy == "NORMAL")
            bus_predictor = str(
                reward_overrides.get("BUS_PREDICTOR_TYPE", "ADAPTIVE_KALMAN")
            ).upper()

            print("-" * 68)
            print(f"[SANITY] {exp_name} seed={SEED} scalar={DEMAND_SCALAR}")

            try:
                set_control_mode(strategy, CONTROLLER_PATH, exp.get("active_intersections"))
            except Exception as _e:
                print(f"[SANITY] FATAL set_control_mode {exp_name}: {_e}")
                failures.append((exp_name, str(_e)))
                continue

            try:
                set_coordinated(CONTROLLER_PATH, coordinated)
                set_coordination_algo(CONTROLLER_PATH, coord_algo)
            except Exception as _e:
                print(f"[SANITY] coord {exp_name}: {_e}")

            _global_reward = bool(reward_overrides.get("GLOBAL_REWARD_MODE", False))
            _numeric_ov = {
                k: v for k, v in reward_overrides.items()
                if k != "GLOBAL_REWARD_MODE"
            }
            _run_cfg = (
                None
                if (is_baseline and not _numeric_ov)
                else (_numeric_ov or None)
            )
            if not is_baseline:
                try:
                    set_reward_weights(CONTROLLER_PATH, _numeric_ov or None)
                except Exception as _e:
                    print(f"[SANITY] reward patch {exp_name}: {_e}")

            set_seed(rep, SEED)
            write_run_config(
                exp_name, strategy, SEED, DEMAND_SCALAR,
                coordinated, coord_algo, RUN_CONFIG_PATH,
                global_reward_mode=_global_reward,
                reward_cfg=_run_cfg,
                bus_predictor=bus_predictor,
                results_csv_name=_os.path.basename(SANITY_CSV),
            )
            _purge_pyc(CONTROLLER_PATH)

            t0 = _time.time()
            success = True
            try:
                run_replication(rep)
            except Exception as _e:
                success = False
                failures.append((exp_name, str(_e)))
                print(f"[SANITY]   EXCEPTION during sim: {_e}")

            elapsed = _time.time() - t0
            print(f"[SANITY]   elapsed={elapsed:.0f}s  success={success}")

            try:
                metrics = collect_run_metrics(
                    PROJECT_DIR, strategy, SEED, DEMAND_SCALAR,
                    exp_name, coordinated, elapsed, success,
                    bus_predictor=bus_predictor)
                append_master_csv(SANITY_CSV, metrics)
                rows.append(metrics)
                _sum = lambda k: float(metrics.get(k, 0) or 0)  # noqa: E731
                print(f"[SANITY]   det={_sum('stats_TSP_Detections'):.0f} "
                      f"ext={_sum('stats_TSP_Extensions'):.0f} "
                      f"ins={_sum('stats_TSP_Insertions'):.0f} "
                      f"ext_s={_sum('stats_TSP_TotalExtension_s'):.0f}")
                print(f"[SANITY]   AvgBusTT_s={_sum('stats_AvgBusTT_s'):.1f} "
                      f"Obj={_sum('stats_Objective_PaxPerDelayHr'):.1f} "
                      f"AvgPaxDelay_s={_sum('stats_AvgPassDelay_s'):.1f}")
            except Exception as _e:
                print(f"[SANITY]   ERROR collecting metrics: {_e}")
                failures.append((exp_name, str(_e)))
    finally:
        try:
            _set_logging(CONTROLLER_PATH, enabled=True)
        except Exception:
            pass

    print("=" * 68)
    print(f"[SANITY] seed={SEED}  {len(rows)}/{len(EXPERIMENTS)} ok, "
          f"{len(failures)} failures -> {SANITY_CSV}")
    for f in failures:
        print(f"[SANITY]   FAILED: {f}")

    # ── Fingerprint check: the whole point of this run ────────────────────
    # Two experiments that collapse onto each other (identical SimTotalDelay
    # to 4 dp AND identical TSP_Detections) mean a mode/flag is still dead.
    def _fp(row):
        return (round(float(row.get('stats_SimTotalDelay_pax_s', 0) or 0), 4),
                float(row.get('stats_TSP_Detections', 0) or 0))

    by_name = {r.get('run_experiment', r.get('stats_ExperimentID', '')): r for r in rows}
    pairs = [
        ("SS_SWAPS_X3", "SS_TIMES_X3", "mode axis: SWAPS vs TIMES must differ (#2)"),
        ("SS_TIMES_X3", "SS_BOTH_X3",  "mode axis: TIMES vs BOTH must differ (#2)"),
        ("SS_SWAPS_X3", "SS_BOTH_X3",  "mode axis: SWAPS vs BOTH must differ (#2)"),
        ("WS_Z1_0p00",  "GR_BASE_X3_BUSX2", "WOBJ_ALPHA=0 must differ from GR_BASE (#5a/#5c)"),
        ("CPDQL_WH50",  "GR_BASE_X3_BUSX2", "CPD-QL keys must differ from GR_BASE (#5d)"),
    ]
    print("─" * 68)
    print("[SANITY] Fingerprint check (identical = fix NOT working):")
    n_bad = 0
    for a, b, why in pairs:
        ra, rb = by_name.get(a), by_name.get(b)
        if ra is None or rb is None:
            print(f"  SKIP  {a} vs {b}: missing rows ({why})")
            continue
        fa, fb = _fp(ra), _fp(rb)
        ok = fa != fb
        n_bad += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {a}={fa}  {b}={fb}  ({why})")
    if n_bad == 0:
        print("[SANITY] ALL FINGERPRINT CHECKS PASSED")
    else:
        print(f"[SANITY] {n_bad} FINGERPRINT CHECK(S) FAILED — a flag is still dead")


if __name__ == "__main__":
    _main()