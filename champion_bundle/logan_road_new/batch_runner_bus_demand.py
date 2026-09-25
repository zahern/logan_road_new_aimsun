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

def _pt_duration_from_secs(secs):
    """Build a GKTimeDuration (h/m/s) from a total-seconds value."""
    dur_cls = globals().get("GKTimeDuration")
    if dur_cls is None:
        try:
            from PyANGKernel import GKTimeDuration as dur_cls
        except Exception:
            return None
    h, rem = divmod(int(max(0, round(secs))), 3600)
    m, s = divmod(rem, 60)
    try:
        return dur_cls(h, m, s)
    except Exception:
        return None


def _pt_time_to_secs(t):
    """QTime -> seconds since midnight (or None)."""
    if t is None:
        return None
    try:
        return int(t.hour()) * 3600 + int(t.minute()) * 60 + int(t.second())
    except Exception:
        return None


def _pt_secs_to_time(secs):
    """Seconds since midnight -> QTime (via GKTimeDuration.toQTime())."""
    dur = _pt_duration_from_secs(secs)
    if dur is None:
        return None
    try:
        return dur.toQTime()
    except Exception:
        return None


def _is_interval_schedule(sch, deps):
    """True for frequency-based schedules: one departure carrying a mean headway."""
    try:
        dt = sch.getDepartureType()
        s = str(dt)
        if "Fixed" in s or "fixed" in s:
            return False
        if "Interval" in s or "interval" in s:
            return True
        try:
            v = int(dt)
            if v == 1:
                return False
            if v == 0:
                return True
        except Exception:
            pass
    except Exception:
        pass
    # Fallback heuristic: a schedule is interval-based when it has exactly one
    # departure entry whose mean time (headway) is populated.
    if len(deps) == 1:
        try:
            return deps[0].getMeanTime() is not None
        except Exception:
            pass
    return len(deps) == 1


def _scale_one_schedule(sch, scalar, key, base_state):
    """Scale one timetable schedule; returns 1 if it changed anything."""
    try:
        deps = list(sch.getDepartureTimes())
    except Exception:
        return 0
    if not deps:
        return 0

    if _is_interval_schedule(sch, deps):
        # Interval schedule: single departure, mean time is the headway.
        try:
            mean = deps[0].getMeanTime()
            if mean is None:
                return 0
            current_secs = int(mean.toSeconds())
        except Exception:
            return 0
        if key not in base_state:
            try:
                base_state[key] = current_secs
            except Exception:
                return 0
        new_secs = max(1, int(round(base_state[key] / float(scalar))))
        if new_secs == current_secs:
            # Already at the target headway (incl. scalar 1.0 with nothing to
            # restore) -- do NOT rebuild the departure.  A default-constructed
            # type(deps[0])() dropped the other departure properties and cut
            # bus service ~25% even at x1.0.
            return 0
        new_dur = _pt_duration_from_secs(new_secs)
        if new_dur is None:
            return 0
        try:
            # Modify the existing departure in place -- preserves every other
            # departure property (bus flow stayed at ~33.8 veh/h when the
            # timetables were untouched).
            deps[0].setMeanTime(new_dur)
            return 1
        except Exception:
            return 0

    # Fixed schedule: one departure entry per scheduled run.  Scale the run
    # count to ~scalar x by interpolating departure times across the window.
    if len(deps) < 2:
        return 0
    if key not in base_state:
        times = []
        for d in deps:
            secs = _pt_time_to_secs(d.getDepartureTime())
            if secs is None:
                return 0
            times.append(secs)
        base_state[key] = sorted(times)
        base_state[str(key) + "_was_scaled"] = False
    orig = base_state[key]
    was_scaled = base_state.get(str(key) + "_was_scaled", False)
    target = max(len(orig), int(round(len(orig) * scalar)))
    if target <= len(orig) and not was_scaled:
        return 0
    try:
        if target <= len(orig) and was_scaled:
            # Scalar back at 1.0 after an upscale: restore the original run
            # list.  Without this branch the upscaled fixed list stayed in
            # memory and compounded on every re-run of the sweep.
            new_times = orig
            base_state[str(key) + "_was_scaled"] = False
        else:
            new_times = sorted(
                set(int(round(orig[0] + (orig[-1] - orig[0]) * i / (target - 1.0)))
                    for i in range(target)))
            base_state[str(key) + "_was_scaled"] = True
        sch.removeDepartureTimes()
        for secs in new_times:
            qt = _pt_secs_to_time(secs)
            if qt is None:
                continue
            nd = type(deps[0])()
            nd.setDepartureTime(qt)
            sch.addDepartureTime(nd)
        try:
            sch.sortDepartureTimes()
        except Exception:
            pass
        return 1
    except Exception:
        return 0


def set_bus_headway_scalar(scalar, base_state):
    """Scale bus frequency by dividing every PT timetable headway by `scalar`.

    base_state caches original values (keyed by object id) so repeated calls
    never compound.  Handles both Aimsun Next departure types:
      - interval schedules: single departure whose mean time is the headway;
      - fixed schedules:    one departure entry per scheduled run, duplicated
                            to ~scalar x the original run count.
    Only PT (bus) timetables are touched; car/truck demand is untouched.
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
                schedules = tt.getSchedules()
            except Exception:
                continue
            for sch in schedules or []:
                try:
                    n_changed += _scale_one_schedule(sch, scalar, id(sch), base_state)
                except Exception:
                    continue

    # ── Verification pass: re-read what the model actually stored ─────────────
    # Guards against a silently-inverted sign (e.g. a deployed copy writing
    # base*scalar) or an Aimsun mean-time semantic that differs from the mock.
    # If the stored mean is NOT base/scalar, log it loudly here instead of
    # discovering it later from corrupted bus flow.
    _ok = _bad = 0
    _sample = None
    for _line in lines:
        for _tt in (_line.getTimeTables() or []):
            for _sch in (_tt.getSchedules() or []):
                _k = id(_sch)
                if _k not in base_state:
                    continue
                try:
                    _deps = list(_sch.getDepartureTimes())
                except Exception:
                    continue
                if not _deps or not _is_interval_schedule(_sch, _deps):
                    continue
                try:
                    _stored = int(_deps[0].getMeanTime().toSeconds())
                except Exception:
                    continue
                _expect = max(1, int(round(base_state[_k] / float(scalar))))
                if _stored == _expect:
                    _ok += 1
                else:
                    _bad += 1
                    if _sample is None:
                        _sample = f"base={base_state[_k]}s scalar={scalar} "                                   f"expected={_expect}s stored={_stored}s"
    if _bad:
        print(f"[BD] READBACK MISMATCH: {_bad} interval schedules stored a mean "
              f"time != base/scalar ({_sample}) -- inverted sign or API semantic!")
    elif _ok:
        print(f"[BD] Readback OK: {_ok} interval schedules store base/scalar.")

    print(f"[BD] Bus demand x{scalar}: scaled {n_changed} timetable schedules "
          f"across {len(lines)} PT lines.")
    if n_changed == 0:
        print("[BD] WARNING: nothing scaled — verify PT timetable schedule type "
              "in Aimsun (interval mean-headway vs fixed departure list).")
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
