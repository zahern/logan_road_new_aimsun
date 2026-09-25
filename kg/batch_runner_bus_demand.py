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
# Frequency multipliers applied PER LINE to its own timetable (0.5 = half as
# many trips / doubled headway; 1.5 = 50% more trips / headway÷1.5).
# Realistic service-adjustment band — not a demand-scaler on car demand.
BUS_FREQ_MULTIPLIERS = [0.5, 0.75, 1.0, 1.25, 1.5]
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
    {"name": "NO_TSP",     "strategy": "NORMAL",        "coordinated": False,
     "coordination_algo": "KALMAN",    "reward_overrides": {}},
    # DCTSP_MARL — the validated KG champion (+7.4% obj). Testing whether the
    # champion's advantage holds across bus-service levels (0.5x–1.5x).
    {"name": "DCTSP_MARL", "strategy": "GLOBAL_REWARD", "coordinated": True,
     "coordination_algo": "KALMAN",
     "reward_overrides": {
         "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0, "REWARD_BETA": 1.0,
         "REWARD_GAMMA": 1.0, "DCTSP_GREEN_REALLOC_MODE": True,
         "GREEN_REALLOC_RECOVER_FRACTION": 1.0, "DCTSP_W_H": 0.50,
         "DCTSP_CAR_WEIGHT": 1.00, "DECIDER_COST_VETO_RATIO": 3.0}},
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


def make_bus_schedules_frequent(multiplier, base_state, min_headway_s=60):
    """Make every PT timetable MORE FREQUENT by packing `multiplier`× trips
    into each line's existing service window (per-line — no global scalar).

    For each schedule:
      • base departures cached once (stable key = (line, tt, sched) indices)
      • interval schedules: expand the mean headway into explicit departures
        across the timetable's [first, last] span at headway/multiplier
      • fixed schedules: interpolate to round(count × multiplier) runs
      • multiplier 1.0 restores the original departure list exactly

    Writes use removeDepartureTimes + addDepartureTime(QTime) — the same
    mechanism the fixed path already proved persists in real Aimsun (the
    setMeanTime in-place write was shown to be discarded on copies).
    """
    model = GKSystem.getSystem().getActiveModel()
    line_type = model.getType("GKPublicLine")
    objs = model.getCatalog().getObjectsByType(line_type)
    if not objs:
        print("[BF] WARNING: no GKPublicLine objects found.")
        return 0
    lines = list(objs.values()) if isinstance(objs, dict) else list(objs)
    mult = max(0.25, float(multiplier))
    n_changed = 0
    _touched = set()
    for line in lines:
        try:
            timetables = line.getTimeTables()
        except Exception:
            continue
        try:
            lid = line.getId()
        except Exception:
            lid = None
        for ti, tt in enumerate(timetables or []):
            try:
                schedules = tt.getSchedules()
            except Exception:
                continue
            for si, sch in enumerate(schedules or []):
                key = (lid, ti, si)
                try:
                    deps = list(sch.getDepartureTimes())
                except Exception:
                    continue
                if not deps:
                    continue
                # ── cache base state ONCE per schedule ──
                if key not in base_state:
                    if len(deps) == 1 and _is_interval_schedule(sch, deps):
                        # interval: anchor = its departure time; span = one
                        # base headway (mean) — replicate across it.
                        try:
                            mean = int(deps[0].getMeanTime().toSeconds())
                            t0 = _pt_time_to_secs(deps[0].getDepartureTime())
                        except Exception:
                            continue
                        if t0 is None or mean <= 0:
                            continue
                        base_state[key] = {"mode": "interval",
                                           "anchor": t0, "mean": mean}
                    else:
                        times = []
                        for d in deps:
                            s0 = _pt_time_to_secs(d.getDepartureTime())
                            if s0 is None:
                                break
                            times.append(s0)
                        if not times:
                            continue
                        base_state[key] = {"mode": "fixed", "times": sorted(times)}
                info = base_state.get(key)
                if not info:
                    continue

                def _write(times_list):
                    qt = [_pt_secs_to_time(s0) for s0 in times_list]
                    if any(q is None for q in qt):
                        return False
                    sch.removeDepartureTimes()
                    for q in qt:
                        nd = type(deps[0])()
                        nd.setDepartureTime(q)
                        sch.addDepartureTime(nd)
                    try:
                        sch.sortDepartureTimes()
                    except Exception:
                        pass
                    return True

                if abs(mult - 1.0) < 1e-9:
                    # restore original exactly
                    if info["mode"] == "fixed":
                        if _write(info["times"]):
                            n_changed += 1; _touched.add(key)
                    else:
                        if _write([info["anchor"]]):
                            n_changed += 1; _touched.add(key)
                    continue
                if info["mode"] == "interval":
                    head = max(min_headway_s,
                               int(round(info["mean"] / mult)))
                    t0 = info["anchor"]
                    span_end = t0 + max(info["mean"], head) * max(1.0, mult)
                    times_list, cur = [], t0
                    while cur <= span_end:
                        times_list.append(cur); cur += head
                    if len(times_list) < 2:
                        times_list = [t0, t0 + head]
                else:
                    orig = info["times"]
                    target = max(len(orig), int(round(len(orig) * mult)))
                    times_list = sorted(set(int(round(
                        orig[0] + (orig[-1] - orig[0]) * i / max(target - 1, 1)))
                        for i in range(target)))
                if _write(times_list):
                    n_changed += 1; _touched.add(key)
    print(f"[BF] frequency x{mult:g}: rewrote {n_changed} schedules "
          f"across {len(lines)} lines (window-preserving, explicit departures).")
    return n_changed


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
        except Exception:
            return 0
        # PERSIST (real-Aimsun fix): getDepartureTimes() can return value COPIES,
        # so the in-place setMeanTime above is silently discarded and the schedule
        # keeps its base headway (readback shows stored==base). Re-read from the
        # schedule; if the change did NOT stick, re-attach the SAME modified
        # departure object (properties preserved, unlike a fresh type(deps[0])()).
        # Only rebuilds when needed, and is fully guarded, so it cannot make a
        # working in-place write worse.
        try:
            _reread = int(list(sch.getDepartureTimes())[0].getMeanTime().toSeconds())
        except Exception:
            _reread = None
        if _reread is not None and abs(_reread - new_secs) > 1:
            try:
                sch.removeDepartureTimes()
                sch.addDepartureTime(deps[0])
            except Exception:
                pass
        return 1

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


def set_bus_freq_inject_scalar(scalar, controller_path):
    """Plan-B frequency scaler: write BUS_FREQ_INJECT_SCALAR into the
    controller as a proper literal. The ENGINE then synthesizes extra buses at
    runtime via AKIPTEnterVeh (catalog-timetable edits provably never reach
    the simulation). scalar 1.0 = calibration run (records natural entries);
    0 = feature off. Never touches the model catalog -> nothing can leak."""
    import re as _re
    val = float(scalar)
    with open(controller_path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    pat = _re.compile(r"(?m)^(BUS_FREQ_INJECT_SCALAR)(\s*:\s*[a-zA-Z_.\[\]]+)?\s*=.*$")
    lit = repr(val)
    if pat.search(txt):
        txt = pat.sub(lambda m: "%s%s = %s" % (m.group(1), m.group(2) or "", lit),
                      txt, count=1)
    else:
        txt = txt.replace("\nCONTROL_MODE",
                          "\nBUS_FREQ_INJECT_SCALAR = %s\nCONTROL_MODE" % lit, 1)
    with open(controller_path, "w", encoding="utf-8", newline="") as f:
        f.write(txt)
    print("[BD] injection scalar x%s written to controller." % val)


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
    # FIX: at scalar 1.0 the champion run must not touch timetables at all.
    # Previously a stale id(sch) key collision (CPython reuses addresses of
    # garbage-collected wrappers) made one schedule look unscaled and triggered
    # a spurious write + READBACK MISMATCH (base=208 stored=100 depType=0).
    if abs(float(scalar) - 1.0) < 1e-9:
        print("[BD] Bus demand x1.0: scalar is neutral — timetables left "
              "untouched (no writes, no readback risk).")
        return 0
    n_changed = 0
    _modified_keys = set()
    for line in lines:
        try:
            timetables = line.getTimeTables()
        except Exception:
            continue
        lid = None
        try:
            lid = line.getId()
        except Exception:
            pass
        for ti, tt in enumerate(timetables or []):
            try:
                schedules = tt.getSchedules()
            except Exception:
                continue
            # FIX: stable identity key (line, timetable, schedule index).
            # The old id(sch) key collided when CPython reused addresses of
            # garbage-collected schedule wrappers, cross-contaminating
            # base_state between DIFFERENT schedules.
            for si, sch in enumerate(schedules or []):
                key = (lid, ti, si)
                try:
                    if _scale_one_schedule(sch, scalar, key, base_state):
                        n_changed += 1
                        _modified_keys.add(key)
                except Exception:
                    continue

    # ── Verification pass: re-read what the model actually stored ─────────────
    # Guards against a silently-inverted sign (e.g. a deployed copy writing
    # base*scalar) or an Aimsun mean-time semantic that differs from the mock.
    # If the stored mean is NOT base/scalar, log it loudly here instead of
    # discovering it later from corrupted bus flow.
    _ok = _bad = 0
    _diag = []
    for _li, _line in enumerate(lines):
        try:
            lid = _line.getId()
        except Exception:
            lid = None
        for _ti, _tt in enumerate(_line.getTimeTables() or []):
            for _si, _sch in enumerate(_tt.getSchedules() or []):
                _k = (lid, _ti, _si)
                # FIX: only verify schedules this call actually modified.
                if _k not in base_state or _k not in _modified_keys:
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
                _base = int(base_state[_k])
                _expect = max(1, int(round(_base / float(scalar))))
                # Allow +/-1 s: the headway is reconstructed from h/m/s and the
                # target is int-rounded, so a legitimate scale can differ by 1 s.
                if abs(_stored - _expect) <= 1:
                    _ok += 1
                else:
                    _bad += 1
                    # Classify the failure so the fix is targeted, not guessed:
                    if abs(_stored - _base) <= 1:
                        _why = "WRITE-NOT-PERSISTED (stored==base: getDepartureTimes() returns COPIES; setMeanTime on the copy is discarded)"
                    elif abs(_stored - int(round(_base * float(scalar)))) <= 1:
                        _why = "INVERTED (stored==base*scalar)"
                    else:
                        _why = "UNIT/SEMANTIC (stored is neither base/scalar, base, nor base*scalar)"
                    if len(_diag) < 6:
                        _dt = ""
                        try:
                            _dt = f" depType={_sch.getDepartureType()}"
                        except Exception:
                            pass
                        _diag.append(f"base={_base}s scalar={scalar} "
                                     f"expected={_expect}s stored={_stored}s{_dt} -> {_why}")
    if _bad:
        print(f"[BD] READBACK MISMATCH: {_bad} interval schedules off base/scalar "
              f"(bus demand for those lines is WRONG). Details:")
        for _d in _diag:
            print(f"[BD]   {_d}")
    elif _ok:
        print(f"[BD] Readback OK: {_ok} interval schedules store base/scalar.")

    print(f"[BD] Bus demand x{scalar}: scaled {n_changed} timetable schedules "
          f"across {len(lines)} PT lines.")
    if n_changed == 0:
        print("[BD] WARNING: nothing scaled — verify PT timetable schedule type "
              "in Aimsun (interval mean-headway vs fixed departure list).")
    else:
        global _LAST_APPLIED_SCALAR
        _LAST_APPLIED_SCALAR = float(scalar)
    return n_changed


# Last non-neutral scalar applied THIS SESSION (None = timetables believed
# pristine). set_bus_headway_scalar(1.0) is deliberately a no-op, so a sweep's
# finally-restore used to do NOTHING and the scaled timetable leaked into the
# saved .ang (measured 2026-08-25: phase3 inherited BUSx3 from the saved KG
# model -- 5/5 per-seed objective fingerprints matched). restore_pt_base()
# applies the explicit inverse instead.
_LAST_APPLIED_SCALAR = None


def restore_pt_base():
    """Undo the most recent scaling applied this session (explicit inverse).

    Returns the number of schedules touched, or 0 if nothing to undo."""
    global _LAST_APPLIED_SCALAR
    s = _LAST_APPLIED_SCALAR
    if s is None or abs(float(s) - 1.0) < 1e-9:
        print("[BD] restore_pt_base: nothing to restore (no scaling applied "
              "this session, or last scalar was neutral 1.0).")
        return 0
    print(f"[BD] restore_pt_base: applying inverse of x{s:g} -> x{1.0/float(s):g}")
    _n = set_bus_headway_scalar(1.0 / float(s), {})
    _LAST_APPLIED_SCALAR = None
    return _n


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

    for bus_scalar in BUS_FREQ_MULTIPLIERS:
        n = make_bus_schedules_frequent(bus_scalar, _pt_base)

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
    make_bus_schedules_frequent(1.0, _pt_base)   # restore original timetables

    print("=" * 68)
    print(f"[BD] Bus-demand sweep complete: {run_num} runs, {len(failures)} failures")
    for f in failures:
        print(f"[BD]   FAILED: {f}")
    print(f"[BD] Results -> {BATCH_RESULTS_CSV}")
    print("=" * 68)
