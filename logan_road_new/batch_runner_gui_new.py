# =============================================================================
# batch_runner_gui_new.py — LOGAN pending-sweep completion (bus demand × mode split)
# =============================================================================
#
# Completes ONLY the items still pending from the Signal-Sequencing × Bus-Demand
# sweep (the frequency axis X1/X2/X3 already ran and is under analysis):
#
#   1. Bus-demand sensitivity  — ×1.0 / ×1.5 / ×2.0 / ×3.0
#        Real PT scaling: every timetable headway divided by the scalar
#        (set_bus_headway_scalar).  Car/truck OD stays at 1.0x.
#   2. Adjustment-mode split   — SWAPS vs TIMES vs BOTH
#        Now genuinely different after the ZIG_ENABLE_SEQ/GR gating fix:
#          SWAPS = phase-order changes only (EARLY_RED / PT / VP / OC)
#          TIMES = green-duration changes only (GREEN_REALLOC / GE)
#          BOTH  = both families together
#        Run at a single middle frequency (X2 = 2 decisions/cycle, 67.5 s
#        window) so the mode axis is isolated from the frequency axis.
#   3. Network-level KPIs      — VKT, total hours of travel, system delay
#        Captured every run via collect_run_metrics: stats_Net_TotalDist_*,
#        stats_Net_TotalTT_h_*, stats_Net_Delay_*, aimsun_* (meta-NameError
#        fixed in batch_runner.py) plus corridor_total_veh_km.
#
#   Runs: (NO_TSP + 3 families) × 4 bus levels × 3 seeds = 48 runs.
#
#   Results -> logan_road_new\batch_results_gui_new.csv  (separate file so the
#   existing batch_results_gui.csv analysis is untouched).  A fingerprint check
#   at the end flags any pair that collapsed onto each other (dead flag / dead
#   axis).
#
# USAGE: open in Aimsun "Run Script" menu (model must be open).
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

# ── Shared infrastructure — imported from this folder's batch_runner.py ──────
_br_path = _os.path.join(_SCRIPT_DIR, "batch_runner.py")
_spec = _ilu.spec_from_file_location("_br_gui_new", _br_path)
_br = _ilu.module_from_spec(_spec)
_sys.modules["_br_gui_new"] = _br
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
write_run_config = _br.write_run_config
collect_run_metrics = _br.collect_run_metrics
append_master_csv = _br.append_master_csv
write_core_output = _br.write_core_output
get_first_replication = _br.get_first_replication
run_replication = _br.run_replication
_purge_pyc = _br._purge_pyc
_set_logging = _br._set_logging

CONTROLLER_PATH = _br.CONTROLLER_PATH
RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
PROJECT_DIR = _br.PROJECT_DIR

BATCH_RESULTS_CSV = _os.path.join(_SCRIPT_DIR, "batch_results_gui_new.csv")
CORE_OUTPUT_PATH = _os.path.join(_SCRIPT_DIR, "core_output_gui_new.csv")

try:
    from intersection_configs import INTERSECTIONS_CONFIG as _IC_CFG
    _ACTIVE_JCTS_LIST = [jid for jid, cfg in _IC_CFG.items()
                         if cfg.get('SignalGroupIDList')]
    # Logan's intersection_configs.py has no SignalGroupIDList keys, so the
    # filter above yields an empty list.  A falsy [] disables TSP in the engine
    # (''if TSP_ACTIVE_INTERSECTIONS and ...''), so fall back to ALL junctions —
    # matching logan's own TSP_ACTIVE_INTERSECTIONS = None convention.
    if not _ACTIVE_JCTS_LIST:
        _ACTIVE_JCTS_LIST = None
except ImportError:
    _ACTIVE_JCTS_LIST = None

# =============================================================================
# ── Sweep axes ────────────────────────────────────────────────────────────────
# =============================================================================
# Bus demand scalars: 1.0 = timetable as modelled; 2.0 = twice as many buses.
BUS_DEMAND_SCALARS = [1.0, 1.5, 2.0, 3.0]

# Frequency: single middle level so the mode axis is isolated.  X2 = 2
# decisions per cycle (67.5 s window).  Change here to X1 or X3 if desired.
_FREQ = {"TSP_CYCLE_LENGTH_OVERRIDE_S": 67.5, "PHASE_SEQ_MAX_PER_CYCLE": 2}
_FREQ_LABEL = "X2"

SEEDS = [300, 42, 12345]

# =============================================================================
# ── Signal-sequencing base config (phase adjustment only) ─────────────────────
# =============================================================================
_SS_BASE = {
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
    "ZIG_DE_POP":                    12,
    "ZIG_DE_ITER":                   30,
    "ZIG_DE_F":                      0.8,
    "ZIG_DE_CR":                     0.9,
    "WOBJ_ALPHA":                    1.0,
    "WOBJ_BETA":                     0.0,
    "WOBJ_GAMMA":                    0.0,
    "WOBJ_Z1_SCALE":                 3000000.0,
    "WOBJ_Z2_SCALE":                 7500.0,
    "WOBJ_Z3_SCALE":                 12000.0,
    "DETECTION_WINDOW_M_OVERRIDE":   50.0,
    # ── Action family gates (now READ by the engine — SWAPS vs TIMES vs BOTH) ──
    "ZIG_ENABLE_GE":                 False,   # GE hard-disabled (phase-adjustment only)
    "ZIG_ENABLE_INS":                False,   # INS hard-disabled
    "ZIG_ENABLE_GR":                 False,   # family override below
    "ZIG_ENABLE_SEQ":                False,   # family override below
    "PHASE_ROTATION_MODE":           False,   # family override below
    "PHASE_ROTATION_N_SEQS":         3.0,
    "PHASE_ROTATION_THRESHOLD_S":    5.0,
}

_FAMILY = {
    "SWAPS": {"ZIG_ENABLE_SEQ": True,  "ZIG_ENABLE_GR": False,
              "PHASE_ROTATION_MODE": True,
              "DCTSP_GREEN_REALLOC_MODE": True},
    "TIMES": {"ZIG_ENABLE_SEQ": False, "ZIG_ENABLE_GR": True,
              "PHASE_ROTATION_MODE": False,
              "DCTSP_GREEN_REALLOC_MODE": True},
    "BOTH":  {"ZIG_ENABLE_SEQ": True,  "ZIG_ENABLE_GR": True,
              "PHASE_ROTATION_MODE": True,
              "DCTSP_GREEN_REALLOC_MODE": True},
}


def _ss(name, family):
    ov = dict(_SS_BASE)
    ov.update(_FAMILY[family])
    ov.update(_FREQ)
    return {
        "name":                 name,
        "enabled":              True,
        "strategy":             "GLOBAL_REWARD",
        "coordinated":          True,
        "coordination_algo":    "SHOCKWAVE",
        "active_intersections": _ACTIVE_JCTS_LIST,
        "reward_overrides":     ov,
        "family":               family,
        "freq":                 _FREQ_LABEL,
    }


EXPERIMENTS = [
    {
        "name":                 "NO_TSP",
        "enabled":              True,
        "strategy":             "NORMAL",
        "coordinated":          False,
        "coordination_algo":    "KALMAN",
        "active_intersections": None,
        "reward_overrides":     {},
        "family":               "NONE",
        "freq":                 "NONE",
    },
    _ss("SS_SWAPS", "SWAPS"),
    _ss("SS_TIMES", "TIMES"),
    _ss("SS_BOTH",  "BOTH"),
]

# =============================================================================
# ── PT timetable scaling (real bus-demand axis) ───────────────────────────────
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
        print("[NEW] WARNING: no GKPublicLine objects found — bus demand NOT scaled.")
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
        print(f"[NEW] READBACK MISMATCH: {_bad} interval schedules stored a mean "
              f"time != base/scalar ({_sample}) -- inverted sign or API semantic!")
    elif _ok:
        print(f"[NEW] Readback OK: {_ok} interval schedules store base/scalar.")

    print(f"[NEW] Bus demand x{scalar}: scaled {n_changed} timetable schedules "
          f"across {len(lines)} PT lines.")
    if n_changed == 0:
        print("[NEW] WARNING: nothing scaled — verify PT timetable schedule type "
              "in Aimsun (interval mean-headway vs fixed departure list).")
    return n_changed


def _main():
    enabled = [e for e in EXPERIMENTS if e.get("enabled", True)]
    n_total = len(enabled) * len(BUS_DEMAND_SCALARS) * len(SEEDS)

    # Fresh results file: archive anything stale first (never delete).
    _archive_ts = _time.strftime("%Y%m%d_%H%M%S")
    for _stale in (BATCH_RESULTS_CSV, CORE_OUTPUT_PATH):
        try:
            if _os.path.isfile(_stale):
                _base, _ext = _os.path.splitext(_stale)
                _archived = f"{_base}_archive_{_archive_ts}{_ext}"
                _os.rename(_stale, _archived)
                print(f"[NEW] Archived previous results -> {_os.path.basename(_archived)}")
        except Exception as _e:
            print(f"[NEW] WARNING: could not archive {_stale}: {_e}")

    log("=" * 68)
    log("BATCH_RUNNER_GUI_NEW — KG pending-sweep completion")
    log(f"  {len(enabled)} experiments x {len(BUS_DEMAND_SCALARS)} bus levels"
        f" x {len(SEEDS)} seeds = {n_total} runs")
    log(f"  Families: SWAPS / TIMES / BOTH at {_FREQ_LABEL} (frequency axis already done)")
    log(f"  Bus demand scalars: {BUS_DEMAND_SCALARS}  (PT headway scaling)")
    log(f"  Network KPIs captured: VKT / TT-hours / system delay per run")
    log(f"  Results -> {BATCH_RESULTS_CSV}")
    log("=" * 68)

    rep = get_first_replication()
    run_num = 0
    failures = []
    _pt_base = {}

    try:
        _set_logging(CONTROLLER_PATH, enabled=False)
    except Exception as e:
        log(f"WARNING: could not disable controller logging: {e}")

    try:
        for bus_scalar in BUS_DEMAND_SCALARS:
            n_scaled = set_bus_headway_scalar(bus_scalar, _pt_base)

            for exp in enabled:
                exp_name = f"{exp['name']}_{_FREQ_LABEL if exp['freq'] != 'NONE' else 'NO_FREQ'}_BUSx{bus_scalar:g}"
                strategy = exp["strategy"]
                coordinated = exp.get("coordinated", False)
                coord_algo = exp.get("coordination_algo", "KALMAN")
                reward_overrides = dict(exp.get("reward_overrides", {}) or {})
                is_baseline = (strategy == "NORMAL")
                bus_predictor = str(reward_overrides.get("BUS_PREDICTOR_TYPE",
                                                         "ADAPTIVE_KALMAN")).upper()

                try:
                    set_control_mode(strategy, CONTROLLER_PATH,
                                     exp.get("active_intersections"))
                except Exception as e:
                    print(f"[NEW] FATAL: cannot patch strategy for {exp_name}: {e}")
                    for seed in SEEDS:
                        failures.append({"experiment": exp_name, "seed": seed,
                                         "error": str(e)})
                    continue

                try:
                    set_coordinated(CONTROLLER_PATH, coordinated)
                    set_coordination_algo(CONTROLLER_PATH, coord_algo)
                except Exception as e:
                    print(f"[NEW] WARNING: coord patch for {exp_name}: {e}")

                _global_reward = bool(reward_overrides.get("GLOBAL_REWARD_MODE", False))
                _numeric_ov = {k: v for k, v in reward_overrides.items()
                               if k != "GLOBAL_REWARD_MODE"}
                _run_cfg = None if is_baseline else (_numeric_ov or None)

                if not is_baseline:
                    try:
                        set_reward_weights(CONTROLLER_PATH, _numeric_ov or None)
                    except Exception as e:
                        log(f"WARNING: reward patch: {e}")

                for seed in SEEDS:
                    run_num += 1
                    print("-" * 68)
                    print(f"[NEW] Run {run_num}/{n_total} | {exp_name} "
                          f"| family={exp['family']} freq={exp['freq']} "
                          f"| bus_x{bus_scalar} seed={seed} | pt_scaled={n_scaled}")

                    set_seed(rep, seed)
                    _run_cfg_write = ({"DETECTION_WINDOW_M_OVERRIDE": 50.0}
                                      if is_baseline else _run_cfg)
                    write_run_config(
                        exp_name, strategy, seed, 1.0,
                        coordinated, coord_algo, RUN_CONFIG_PATH,
                        global_reward_mode=_global_reward,
                        reward_cfg=_run_cfg_write,
                        bus_predictor=bus_predictor,
                        results_csv_name=_os.path.basename(BATCH_RESULTS_CSV))
                    _purge_pyc(CONTROLLER_PATH)

                    t0 = _time.time()
                    success = True
                    try:
                        run_replication(rep)
                    except Exception as e:
                        success = False
                        failures.append({"experiment": exp_name, "seed": seed,
                                         "error": str(e)})
                        print(f"[NEW]   EXCEPTION during simulation: {e}")

                    elapsed = _time.time() - t0
                    print(f"[NEW]   elapsed={elapsed:.0f}s  success={success}")

                    try:
                        metrics = collect_run_metrics(
                            PROJECT_DIR, strategy, seed, 1.0,
                            exp_name, coordinated, elapsed, success,
                            bus_predictor=bus_predictor)
                        _rc = _run_cfg or {}
                        metrics["sweep_bus_demand_scalar"] = bus_scalar
                        metrics["sweep_pt_schedules_scaled"] = n_scaled
                        metrics["sweep_family"] = exp["family"]
                        metrics["sweep_freq_per_cycle"] = exp["freq"]
                        metrics["sweep_decision_window_s"] = _rc.get(
                            "TSP_CYCLE_LENGTH_OVERRIDE_S", None)
                        metrics["sweep_seq_max_per_cycle"] = _rc.get(
                            "PHASE_SEQ_MAX_PER_CYCLE", None)
                        metrics["sweep_ge_enabled"] = bool(_rc.get("ZIG_ENABLE_GE", False))
                        metrics["sweep_ins_enabled"] = bool(_rc.get("ZIG_ENABLE_INS", False))
                        metrics["sweep_gr_enabled"] = bool(_rc.get("ZIG_ENABLE_GR", False))
                        metrics["sweep_seq_enabled"] = bool(_rc.get("ZIG_ENABLE_SEQ", False))
                        metrics["sweep_pr_enabled"] = bool(_rc.get("PHASE_ROTATION_MODE", False))
                        append_master_csv(BATCH_RESULTS_CSV, metrics)
                        write_core_output(CORE_OUTPUT_PATH, metrics, reward_overrides)

                        _vkt = float(metrics.get('stats_Net_TotalDist_All', 0) or 0) / 1000.0
                        _tt = float(metrics.get('stats_Net_TotalTT_h_All', 0) or 0)
                        _sysd = float(metrics.get('stats_Net_Delay_All', 0) or 0)
                        print(f"[NEW]   delay={metrics.get('stats_TotalPassDelay_hrs','?')}h "
                              f"VKT={_vkt:,.0f}km TT={_tt:,.1f}h sysDelay={_sysd:,.1f} "
                              f"veh_km={metrics.get('corridor_total_veh_km','?')} "
                              f"-> {_os.path.basename(BATCH_RESULTS_CSV)}")
                    except Exception as e:
                        print(f"[NEW]   ERROR collecting metrics: {e}")
                        failures.append({"experiment": exp_name, "seed": seed,
                                         "error": str(e)})
    finally:
        # Restore original timetables regardless of failures
        try:
            set_bus_headway_scalar(1.0, _pt_base)
        except Exception as e:
            print(f"[NEW] WARNING: could not restore timetables: {e}")
        try:
            _set_logging(CONTROLLER_PATH, enabled=True)
        except Exception:
            pass

    print("=" * 68)
    print(f"[NEW] Sweep complete: {run_num} runs, {len(failures)} failures")
    for f in failures:
        print(f"[NEW]   FAILED: {f}")
    print(f"[NEW] Results -> {BATCH_RESULTS_CSV}")

    # ── Fingerprint check (catches a dead flag / dead axis instantly) ─────────
    try:
        import csv as _csv
        _rows = list(_csv.DictReader(open(BATCH_RESULTS_CSV, encoding='utf-8')))
    except Exception as e:
        print(f"[NEW] Could not re-read results for fingerprint check: {e}")
        return

    def _fp(r):
        return (round(float(r.get('stats_SimTotalDelay_pax_s', 0) or 0), 4),
                float(r.get('stats_TSP_Detections', 0) or 0))

    by_name = {}
    for r in _rows:
        by_name.setdefault(r.get('run_experiment', ''), []).append(r)

    def _pair_mean(exp_prefix, bus_lvl, freq_label=None):
        # NO_TSP rows are named with NO_FREQ, not the sweep's _FREQ_LABEL;
        # without the correct label the bus-demand axis check found nothing.
        freq = freq_label if freq_label is not None else _FREQ_LABEL
        key = f"{exp_prefix}_{freq}_BUSx{bus_lvl:g}"
        rs = by_name.get(key, [])
        if not rs:
            return None
        vals = [_fp(r) for r in rs]
        mean_delay = sum(v[0] for v in vals) / len(vals)
        mean_det = sum(v[1] for v in vals) / len(vals)
        return round(mean_delay, 4), round(mean_det, 3)

    print("─" * 68)
    print("[NEW] Fingerprint check (means over seeds):")
    n_bad = 0
    for bus_lvl in BUS_DEMAND_SCALARS:
        sw = _pair_mean("SS_SWAPS", bus_lvl)
        ti = _pair_mean("SS_TIMES", bus_lvl)
        bo = _pair_mean("SS_BOTH", bus_lvl)
        nt = _pair_mean("NO_TSP", bus_lvl, "NO_FREQ")
        if sw is None or ti is None or bo is None:
            print(f"  SKIP  bus_x{bus_lvl}: missing rows")
            continue
        for a, b, why in ((sw, ti, "SWAPS vs TIMES must differ (mode axis)"),
                          (ti, bo, "TIMES vs BOTH must differ (mode axis)"),
                          (sw, bo, "SWAPS vs BOTH must differ (mode axis)")):
            ok = a != b
            n_bad += 0 if ok else 1
            print(f"  {'PASS' if ok else 'FAIL'}  bus_x{bus_lvl} {why}: {a} vs {b}")
        if nt is not None and nt[1] == 0:
            print(f"  INFO  bus_x{bus_lvl}: NO_TSP det=0 (baseline check OK)")
    # Bus-demand axis: NO_TSP delay should rise with bus level
    nts = [_pair_mean("NO_TSP", b, "NO_FREQ") for b in BUS_DEMAND_SCALARS]
    if all(n is not None for n in nts) and nts[0] is not None and nts[-1] is not None:
        axis_ok = abs(nts[-1][0] - nts[0][0]) > 1.0
        n_bad += 0 if axis_ok else 1
        print(f"  {'PASS' if axis_ok else 'FAIL'}  bus-demand axis: NO_TSP delay "
              f"moves with bus level ({nts[0][0]} -> {nts[-1][0]})")
    if n_bad == 0:
        print("[NEW] ALL FINGERPRINT CHECKS PASSED")
    else:
        print(f"[NEW] {n_bad} FINGERPRINT CHECK(S) FAILED — a flag/axis is still dead")


if __name__ == "__main__":
    _main()
