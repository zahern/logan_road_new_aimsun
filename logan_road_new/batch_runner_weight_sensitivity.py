# =============================================================================
# batch_runner_weight_sensitivity.py — Objective-weight sensitivity
# =============================================================================
#
# PURPOSE (TODO.txt last item):
#   Weighted-objective sensitivity using the best method (WaveGate winner,
#   WG_HP_MG1 configuration), sweeping each objective weight while holding
#   EVERYTHING else identical.
#
#   The controller's live weighted objective has three weight knobs:
#     Z1 (WOBJ_ALPHA)  total passenger delay              — minimise
#     Z2 (WOBJ_BETA)   flow-weighted green-wave bandwidth — maximise
#     Z3 (WOBJ_GAMMA)  bus headway deviation (lateness)   — minimise
#   Z4 (corridor veh-km / travel distance) is REPORTED for every run
#   (corridor_total_veh_km in the results CSV) but has no weight in the
#   implemented objective — its sensitivity is captured by observing how
#   the Z1–Z3 weight changes move it.
#
#   Sweep design (one-at-a-time, levels 0 / 0.25 / 0.5 / 0.75 / 1.0):
#   the swept objective takes the level w; the other two share (1-w)/2,
#   so the weights always sum to 1 and only ONE dimension moves at a time.
#
#   Results -> weight_sensitivity_results\batch_results_weight_sensitivity.csv
#
# USAGE: open in Aimsun "Run Script" menu (model must be open).
#   After: python3.12 generate_dashboard.py weight_sensitivity_results\batch_results_weight_sensitivity.csv weight_sensitivity_dashboard.html
# =============================================================================

import os as _os
import sys as _sys
import time as _time
from PyANGKernel import GKSystem

_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
RESULTS_DIR = _os.path.join(_SCRIPT_DIR, "weight_sensitivity_results")
BATCH_RESULTS_CSV = _os.path.join(RESULTS_DIR, "batch_results_weight_sensitivity.csv")
CORE_OUTPUT_PATH  = _os.path.join(RESULTS_DIR, "core_output_weight_sensitivity.csv")

try:
    from intersection_configs import INTERSECTIONS_CONFIG as _IC_CFG
    _ACTIVE_JCTS_LIST = [jid for jid, cfg in _IC_CFG.items()
                         if cfg.get('SignalGroupIDList')]
except ImportError:
    _ACTIVE_JCTS_LIST = None

SEEDS  = [300, 42, 12345]
LEVELS = [0.0, 0.25, 0.5, 0.75, 1.0]

# Best method — WaveGate winner, everything held fixed except the Z weights
_WG_BEST_FIXED = {
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
    "ZIG_PHASE_OVERLAP_S":           0.5,
    "ZIG_MIN_GAIN_S":                1.0,
    "WOBJ_Z1_SCALE":                 3000000.0,
    "WOBJ_Z2_SCALE":                 7500.0,
    "WOBJ_Z3_SCALE":                 12000.0,
    "DETECTION_WINDOW_M_OVERRIDE":   50.0,
    "ZIG_ENABLE_GE":                 True,
    "ZIG_ENABLE_INS":                True,
    "ZIG_ENABLE_GR":                 True,
    "ZIG_ENABLE_SEQ":                True,
}


def _weights(swept, w):
    """Swept objective gets w; the other two share (1-w)/2. Sum = 1."""
    rest = (1.0 - w) / 2.0
    out = {"Z1": rest, "Z2": rest, "Z3": rest}
    out[swept] = w
    return {"WOBJ_ALPHA": round(out["Z1"], 6),
            "WOBJ_BETA":  round(out["Z2"], 6),
            "WOBJ_GAMMA": round(out["Z3"], 6)}


EXPERIMENTS = [{
    "name":             "NO_TSP",
    "strategy":         "NORMAL",
    "coordinated":      False,
    "coordination_algo":"KALMAN",
    "reward_overrides": {},
    "swept":            "NONE",
    "level":            None,
}]
for _z in ("Z1", "Z2", "Z3"):
    for _w in LEVELS:
        ov = dict(_WG_BEST_FIXED)
        ov.update(_weights(_z, _w))
        EXPERIMENTS.append({
            "name":             f"WS_{_z}_{_w:.2f}".replace(".", "p"),
            "strategy":         "GLOBAL_REWARD",
            "coordinated":      True,
            "coordination_algo":"SHOCKWAVE",
            "reward_overrides": ov,
            "swept":            _z,
            "level":            _w,
        })

# =============================================================================
# ── Shared infrastructure ─────────────────────────────────────────────────────
# =============================================================================
import importlib.util as _ilu
_br_path = _os.path.join(_SCRIPT_DIR, "batch_runner.py")
_spec    = _ilu.spec_from_file_location("_br", _br_path)
_br      = _ilu.module_from_spec(_spec)
_sys.modules["_br"] = _br
try:
    _spec.loader.exec_module(_br)
except SystemExit:
    pass

log = _br.log

if __name__ == "__main__":
    _os.makedirs(RESULTS_DIR, exist_ok=True)
    if _os.path.isfile(BATCH_RESULTS_CSV):
        _os.remove(BATCH_RESULTS_CSV)

    _br._QUIET = False
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    PROJECT_DIR     = _br.PROJECT_DIR
    try:
        _rt_proj = _br.get_project_dir()
        CONTROLLER_PATH = _os.path.join(_rt_proj, "intersection_controller.py")
        RUN_CONFIG_PATH = _os.path.join(_rt_proj, "run_config.py")
        PROJECT_DIR     = _rt_proj
        _br.CONTROLLER_PATH = CONTROLLER_PATH
        _br.RUN_CONFIG_PATH = RUN_CONFIG_PATH
        _br.PROJECT_DIR     = PROJECT_DIR
    except Exception as _e:
        print(f"[WS] WARNING: could not resolve project dir: {_e}")

    n_total = len(EXPERIMENTS) * len(SEEDS)
    log("=" * 68)
    log("BATCH_RUNNER_WEIGHT_SENSITIVITY — one-at-a-time Z-weight sweep")
    log(f"  3 objectives x {len(LEVELS)} levels + NO_TSP = {len(EXPERIMENTS)} "
        f"experiments x {len(SEEDS)} seeds = {n_total} runs")
    log("  Z4 (veh-km) reported per run; no weight knob in implemented objective")
    log(f"  Results -> {BATCH_RESULTS_CSV}")
    log("=" * 68)

    rep      = _br.get_first_replication()
    run_num  = 0
    failures = []
    base_demands = {}
    try:
        _br.set_demand_scalar(1.0, base_demands)
    except Exception as e:
        log(f"WARNING: demand scalar: {e}")

    for exp in EXPERIMENTS:
        exp_name    = exp["name"]
        strategy    = exp["strategy"]
        coordinated = exp["coordinated"]
        coord_algo  = exp["coordination_algo"]
        overrides   = exp["reward_overrides"]
        is_baseline = (strategy == "NORMAL")
        bus_pred    = str(overrides.get("BUS_PREDICTOR_TYPE",
                                        "ADAPTIVE_KALMAN")).upper()

        try:
            _br.set_control_mode(strategy, CONTROLLER_PATH,
                                 _ACTIVE_JCTS_LIST if not is_baseline else None)
            _br.set_coordinated(CONTROLLER_PATH, coordinated)
            _br.set_coordination_algo(CONTROLLER_PATH, coord_algo)
        except Exception as e:
            print(f"[WS] FATAL: patch failed for {exp_name}: {e}")
            continue

        _numeric_ov = {k: v for k, v in overrides.items()
                       if k != "GLOBAL_REWARD_MODE"}
        if not is_baseline:
            try:
                _br.set_reward_weights(CONTROLLER_PATH, _numeric_ov or None)
            except Exception as e:
                log(f"WARNING: reward patch: {e}")

        for seed in SEEDS:
            run_num += 1
            print("-" * 68)
            print(f"[WS] Run {run_num}/{n_total} | {exp_name} | seed={seed} | "
                  f"swept={exp['swept']} level={exp['level']}")
            _br.set_seed(rep, seed)
            _br.write_run_config(
                exp_name, strategy, seed, 1.0, coordinated, coord_algo,
                RUN_CONFIG_PATH,
                global_reward_mode=bool(overrides.get("GLOBAL_REWARD_MODE", False)),
                reward_cfg=(None if is_baseline else _numeric_ov),
                bus_predictor=bus_pred)
            _br._purge_pyc(CONTROLLER_PATH)

            t0 = _time.time()
            success = True
            try:
                _br.run_replication(rep)
            except Exception as e:
                success = False
                failures.append({"experiment": exp_name, "seed": seed,
                                 "error": str(e)})
                print(f"[WS]   EXCEPTION: {e}")
            elapsed = _time.time() - t0
            print(f"[WS] Job {run_num}/{n_total} done, {n_total - run_num} to go")
            try:
                metrics = _br.collect_run_metrics(
                    PROJECT_DIR, strategy, seed, 1.0, exp_name,
                    coordinated, elapsed, success, bus_predictor=bus_pred)
                metrics["sweep_swept_objective"] = exp["swept"]
                metrics["sweep_weight_level"]    = exp["level"]
                metrics["sweep_Z1_weight"] = _numeric_ov.get("WOBJ_ALPHA")
                metrics["sweep_Z2_weight"] = _numeric_ov.get("WOBJ_BETA")
                metrics["sweep_Z3_weight"] = _numeric_ov.get("WOBJ_GAMMA")
                _br.append_master_csv(BATCH_RESULTS_CSV, metrics)
                _br.write_core_output(CORE_OUTPUT_PATH, metrics, overrides)
                print(f"[WS]   delay={metrics.get('stats_TotalPassDelay_hrs','?')}h "
                      f"veh_km={metrics.get('corridor_total_veh_km','?')}")
            except Exception as e:
                print(f"[WS]   ERROR collecting metrics: {e}")
                failures.append({"experiment": exp_name, "seed": seed,
                                 "error": str(e)})

    print("=" * 68)
    print(f"[WS] Weight sensitivity complete: {run_num} runs, "
          f"{len(failures)} failures")
    for f in failures:
        print(f"[WS]   FAILED: {f}")
    print(f"[WS] Results -> {BATCH_RESULTS_CSV}")
    print("=" * 68)
