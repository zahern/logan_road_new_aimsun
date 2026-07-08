# =============================================================================
# batch_runner_bus_demand.py — Bus-demand (frequency) sweep
# =============================================================================
#
# PURPOSE (TODO.txt "Separate TEST saved in different folder"):
#   Instead of increasing TOTAL demand, sweep ONLY bus demand so we can see
#   what happens when multiple buses arrive per signal cycle.
#   Car/truck OD demand stays at 1.0x throughout.
#
#   Buses on this model come from PUBLIC TRANSPORT timetables, not OD
#   matrices, so the sweep scales PT line departures: a bus-demand scalar of
#   2.0 halves every timetable headway (twice as many buses).
#
#   Strategy under test: the most reliable configuration (WaveGate winner,
#   WG_HP_MG1: DCTSP_ZIG, ZIG_MIN_GAIN_S=1.0, Adaptive-Kalman, full action
#   set) — each bus-demand level is also run with NO_TSP for reference.
#
#   Results -> bus_demand_results\batch_results_bus_demand.csv
#
# USAGE: open in Aimsun "Run Script" menu (model must be open).
# =============================================================================

import os as _os
import sys as _sys
import time as _time
from PyANGKernel import GKSystem

_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
RESULTS_DIR = _os.path.join(_SCRIPT_DIR, "bus_demand_results")
BATCH_RESULTS_CSV = _os.path.join(RESULTS_DIR, "batch_results_bus_demand.csv")
CORE_OUTPUT_PATH  = _os.path.join(RESULTS_DIR, "core_output_bus_demand.csv")

try:
    from intersection_configs import INTERSECTIONS_CONFIG as _IC_CFG
    _ACTIVE_JCTS_LIST = [jid for jid, cfg in _IC_CFG.items()
                         if cfg.get('SignalGroupIDList')]
except ImportError:
    _ACTIVE_JCTS_LIST = None

# Bus-demand multipliers: 1x = timetable as modelled; 2x = double buses; etc.
BUS_DEMAND_SCALARS = [1.0, 1.5, 2.0, 3.0]
SEEDS              = [300, 42, 12345]

# Best (most reliable) WaveGate configuration — full action set
_WG_BEST = {
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
    "WOBJ_ALPHA":                    round(1/3, 6),
    "WOBJ_BETA":                     round(1/3, 6),
    "WOBJ_GAMMA":                    round(1/3, 6),
    "DETECTION_WINDOW_M_OVERRIDE":   50.0,
    "ZIG_ENABLE_GE":                 True,
    "ZIG_ENABLE_INS":                True,
    "ZIG_ENABLE_GR":                 True,
    "ZIG_ENABLE_SEQ":                True,
}

EXPERIMENTS = [
    {"name": "NO_TSP",  "strategy": "NORMAL",        "coordinated": False,
     "coordination_algo": "KALMAN",    "reward_overrides": {}},
    {"name": "WG_BEST", "strategy": "GLOBAL_REWARD", "coordinated": True,
     "coordination_algo": "SHOCKWAVE", "reward_overrides": _WG_BEST},
]

# =============================================================================
# ── PT timetable scaling ──────────────────────────────────────────────────────
# =============================================================================

def set_bus_headway_scalar(scalar, base_state):
    """Scale bus frequency by dividing every PT timetable headway by `scalar`.

    base_state caches original values (keyed by object id) so repeated calls
    never compound. Aimsun scripting APIs differ between versions, so every
    known accessor is attempted; anything actually changed is logged, and a
    total count is returned so the caller can verify the sweep really applied.
    """
    model = GKSystem.getSystem().getActiveModel()
    line_type = model.getType("GKPublicLine")
    objs = model.getCatalog().getObjectsByType(line_type)
    if not objs:
        print("[BD] WARNING: no GKPublicLine objects found — bus demand NOT scaled.")
        return 0

    lines = list(objs.values()) if isinstance(objs, dict) else list(objs)
    n_changed = 0
    for line in lines:
        try:
            timetables = line.getTimeTables()
        except Exception:
            continue
        for tt in timetables or []:
            try:
                schedules = tt.getTimeTableSchedules()
            except Exception:
                try:
                    schedules = tt.getSchedules()
                except Exception:
                    continue
            for sch in schedules or []:
                # Departure type 1 = interval/frequency-based in Aimsun Next.
                # Try the frequency (mean headway) accessors first.
                for getter, setter in (
                        ("getInterval",     "setInterval"),
                        ("getMeanHeadway",  "setMeanHeadway"),
                        ("getFrequency",    "setFrequency")):
                    try:
                        g = getattr(sch, getter, None)
                        s = getattr(sch, setter, None)
                        if g is None or s is None:
                            continue
                        key = (id(sch), getter)
                        if key not in base_state:
                            base_state[key] = g()
                        base = base_state[key]
                        # headway/interval shrink -> more buses
                        try:
                            new = base / float(scalar)
                        except TypeError:
                            # GKTimeDuration-like object: scale via seconds
                            secs = base.toSeconds() if hasattr(base, "toSeconds") else None
                            if secs is None:
                                continue
                            new = type(base)()
                            new.fromSeconds(int(max(1, round(secs / float(scalar)))))
                        s(new)
                        n_changed += 1
                        break
                    except Exception:
                        continue

    print(f"[BD] Bus demand x{scalar}: scaled {n_changed} timetable schedules "
          f"across {len(lines)} PT lines.")
    if n_changed == 0:
        print("[BD] WARNING: nothing scaled — check timetable schedule type "
              "(fixed departure lists need per-departure duplication; verify "
              "in Aimsun: Public Transport > line > timetable).")
    return n_changed


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
        print(f"[BD] WARNING: could not resolve project dir: {_e}")

    n_total = len(BUS_DEMAND_SCALARS) * len(EXPERIMENTS) * len(SEEDS)
    log("=" * 68)
    log("BATCH_RUNNER_BUS_DEMAND — bus-frequency sweep (car demand fixed 1.0x)")
    log(f"  bus scalars {BUS_DEMAND_SCALARS} x {len(EXPERIMENTS)} strategies "
        f"x {len(SEEDS)} seeds = {n_total} runs")
    log(f"  Results -> {BATCH_RESULTS_CSV}")
    log("=" * 68)

    rep       = _br.get_first_replication()
    run_num   = 0
    failures  = []
    _pt_base  = {}   # original timetable values — prevents compounding

    for bus_scalar in BUS_DEMAND_SCALARS:
        n = set_bus_headway_scalar(bus_scalar, _pt_base)

        for exp in EXPERIMENTS:
            exp_name    = f"{exp['name']}_BUSx{bus_scalar:g}"
            strategy    = exp["strategy"]
            coordinated = exp["coordinated"]
            coord_algo  = exp["coordination_algo"]
            overrides   = exp["reward_overrides"]
            is_baseline = (strategy == "NORMAL")
            bus_pred    = str(overrides.get("BUS_PREDICTOR_TYPE",
                                            "ADAPTIVE_KALMAN")).upper()

            try:
                _br.set_control_mode(strategy, CONTROLLER_PATH, _ACTIVE_JCTS_LIST
                                     if not is_baseline else None)
                _br.set_coordinated(CONTROLLER_PATH, coordinated)
                _br.set_coordination_algo(CONTROLLER_PATH, coord_algo)
            except Exception as e:
                print(f"[BD] FATAL: patch failed for {exp_name}: {e}")
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
                print(f"[BD] Run {run_num}/{n_total} | {exp_name} | seed={seed} "
                      f"| pt_schedules_scaled={n}")
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
                    print(f"[BD]   EXCEPTION: {e}")
                elapsed = _time.time() - t0
                print(f"[BD] Job {run_num}/{n_total} done, {n_total - run_num} to go")
                try:
                    metrics = _br.collect_run_metrics(
                        PROJECT_DIR, strategy, seed, 1.0, exp_name,
                        coordinated, elapsed, success, bus_predictor=bus_pred)
                    metrics["sweep_bus_demand_scalar"]  = bus_scalar
                    metrics["sweep_pt_schedules_scaled"] = n
                    _br.append_master_csv(BATCH_RESULTS_CSV, metrics)
                    _br.write_core_output(CORE_OUTPUT_PATH, metrics, overrides)
                    print(f"[BD]   delay={metrics.get('stats_TotalPassDelay_hrs','?')}h")
                except Exception as e:
                    print(f"[BD]   ERROR collecting metrics: {e}")
                    failures.append({"experiment": exp_name, "seed": seed,
                                     "error": str(e)})

    # Restore original timetables (scalar 1.0 = base values)
    set_bus_headway_scalar(1.0, _pt_base)

    print("=" * 68)
    print(f"[BD] Bus-demand sweep complete: {run_num} runs, {len(failures)} failures")
    for f in failures:
        print(f"[BD]   FAILED: {f}")
    print(f"[BD] Results -> {BATCH_RESULTS_CSV}")
    print("=" * 68)
