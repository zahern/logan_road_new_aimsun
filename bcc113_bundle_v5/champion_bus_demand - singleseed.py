"""
champion_bus_demand.py -- Phase 2 of the BCC113 simulation matrix.

BUS-DEMAND SENSITIVITY of the Phase-1 selected champion.
Sweeps ONLY bus demand -- the PT timetable frequency -- while car/truck OD demand
stays fixed at 1.0x, so we can characterise how the champion's benefit holds up as
the number of buses per signal cycle rises. A bus scalar of 2.0 halves every
timetable headway (twice as many buses); 3.0 triples the departures.

Every bus-demand level is run for BOTH the selected champion and NO_TSP, so the
champion's benefit is always measured against the do-nothing baseline AT THAT SAME
bus-demand level (more buses raise bus delay even with no TSP).

Reuses champion_search.py for the arm configs + fair run/collect machinery, and the
corridor's batch_runner_bus_demand.py for the PT-timetable headway scaler -- so the
numbers are directly comparable to Phase 1 (same seeds, same collection retry).

HOW TO RUN (inside Aimsun, one corridor at a time)
--------------------------------------------------
  1. Open the KG model in Aimsun -> run this script from the Python console.
     It auto-detects "kg" and writes champion_bus_demand_kg.csv.
  2. Open the Logan Road model -> run again -> champion_bus_demand_logan_road_new.csv.
  3. From a normal terminal:  python rank_champions.py --bus-demand    (or read the CSV)

Runs: |BUS_DEMAND_SCALARS| x [NO_TSP, selected champion] x |SEEDS|.
Each output row carries `sweep_bus_demand_scalar` and `sweep_base_arm` columns so
the sensitivity curve (metric vs bus scalar, per arm) is a simple group-by.
"""
import os as _os
import sys as _sys
import time as _time
import math as _math
import statistics as _st
import importlib.util as _ilu

# ── Robustly load champion_search (Phase-1 machinery) by ABSOLUTE PATH ─────────
# A plain `import champion_search` fails when Aimsun runs THIS file from a working
# directory where the repo root is not on sys.path (the script then errors before
# any run happens -- "clicking it does nothing"). Resolve our own folder and load
# champion_search.py from it explicitly, the same importlib pattern the rest of
# the codebase uses. __file__ is set when Aimsun runs a script; fall back to CWD.
try:
    _HERE = _os.path.dirname(_os.path.abspath(__file__))
except NameError:
    _HERE = _os.path.abspath(_os.getcwd())
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)
_cs_path = _os.path.join(_HERE, "champion_search.py")
if not _os.path.isfile(_cs_path):
    raise RuntimeError(
        "champion_bus_demand.py: cannot find champion_search.py next to it "
        f"(looked in {_HERE!r}). Unzip the bundle so both files sit in the same "
        "folder, then run this from Aimsun with the model open.")
_spec_cs = _ilu.spec_from_file_location("champion_search", _cs_path)
_cs = _ilu.module_from_spec(_spec_cs)
_sys.modules["champion_search"] = _cs
_spec_cs.loader.exec_module(_cs)

CORRIDOR = _cs.CORRIDOR
CORR_DIR = _cs.CORR_DIR
_br = _cs._br
log = _br.log

# ── Import the corridor's bus-demand runner for the PT-headway scaler ─────────
# It has a proper __main__ guard, so importing only binds set_bus_headway_scalar
# and its helpers (no sweep runs on import).
_bd_path = _os.path.join(CORR_DIR, "batch_runner_bus_demand.py")
_spec = _ilu.spec_from_file_location("_bd_champ", _bd_path)
_bd = _ilu.module_from_spec(_spec)
_sys.modules["_bd_champ"] = _bd
try:
    _spec.loader.exec_module(_bd)
except SystemExit:
    pass

# ── Phase-2 design ────────────────────────────────────────────────────────────
# Frequency multipliers applied to every PT line via the Plan-B scaler:
#   <1.0 removes a deterministic fraction of natural departures (AKIRemoveVehicle)
#   1.0   baseline / calibration run (records natural entry pattern)
#   >1.0  injects extra buses to reach exactly that multiple
BUS_DEMAND_SCALARS = [0.5, 0.75, 1.0, 2.0, 3.0]
SEEDS = list([1])                 # the same 5 champion seeds (300..700)
NO_TSP_MAX_OBJECTIVE_GAP_PCT = 5.0


def _pt_calibration_path():
    """Corridor-level calibration CSV recorded by an x1.0 (calibrating) run."""
    return _os.path.join(CORR_DIR, "pt_entry_calibration.csv")


def _ensure_pt_calibration(_br, rep, CONTROLLER_PATH, RUN_CONFIG_PATH,
                           PROJECT_DIR, log):
    """Run ONE x1.0 calibration replication if the corridor has no
    pt_entry_calibration.csv AND the sweep will inject (>1.0 levels).

    pt_inject.py can only synthesise extra buses from a captured natural-entry
    pattern; without the file, x2/x3 levels inject NOTHING and silently rerun the
    x1.0 simulation (measured: KG BUSx2/BUSx3 ≡ BUSx1, defect report 2026-09-01,
    finding 4).  The engine records the calibration during ANY x1.0 run (scalar
    1.0 => calibrating mode => AAPIFinish persists session_entries), so the
    simplest reliable way is a single NO_TSP x1.0 replication on the first seed.
    """
    if not any(float(s) > 1.0 + 1e-9 for s in BUS_DEMAND_SCALARS):
        return                                       # no injection levels used
    if _os.path.isfile(_pt_calibration_path()):
        return                                       # already calibrated
    log("[BD] no pt_entry_calibration.csv -- running ONE x1.0 calibration "
        "replication (NO_TSP) so x2/x3 can inject")
    try:
        _br.set_control_mode("NORMAL", CONTROLLER_PATH)
        _br.set_coordinated(CONTROLLER_PATH, False)
        _br.set_coordination_algo(CONTROLLER_PATH, "KALMAN")
        _br.set_reward_weights(CONTROLLER_PATH, None)
    except Exception as e:
        log(f"FATAL calibration patch: {e}")
        return
    try:
        _bd.set_bus_freq_inject_scalar(1.0, CONTROLLER_PATH)
    except Exception as e:
        log(f"FATAL bus scalar 1.0 (calibration): {e}")
        return
    seed0 = SEEDS[0]
    _br.set_seed(rep, seed0)
    _br.write_run_config("PT_CALIBRATION", "NORMAL", seed0, 1.0, False,
                         "KALMAN", RUN_CONFIG_PATH,
                         global_reward_mode=False,
                         reward_cfg={"BUS_FREQ_INJECT_SCALAR": 1.0},
                         bus_predictor="ADAPTIVE_KALMAN",
                         results_csv_name="pt_calibration.csv")
    _br._purge_pyc(CONTROLLER_PATH)
    t0 = _time.time(); ok = True
    try:
        _br.run_replication(rep)
    except Exception as e:
        ok = False; log(f"  calibration EXCEPTION: {e}")
    log(f"[BD] calibration run done in {_time.time() - t0:.0f}s ok={ok}")
    if not _os.path.isfile(_pt_calibration_path()):
        log("[BD] WARNING: pt_entry_calibration.csv still missing after x1.0 "
            "run -- x2/x3 levels will inject NOTHING (results will collapse)")

_SCHEDULE_DEVIATION_KEYS = (
    "ttotal_bus_tt_deviation_sec",
    "schedule_total_abs_deviation_s",
    "stats_Schedule_TotalAbsDeviation_s",
    "Schedule_TotalAbsDeviation_s",
)
_SCHEDULE_COUNT_KEYS = (
    "schedule_n",
    "stats_Schedule_N",
    "Schedule_N",
)
_SCHEDULE_AVAILABLE_KEYS = (
    "schedule_available",
    "stats_Schedule_Available",
    "Schedule_Available",
)


def _row_number(row, keys):
    for key in keys:
        try:
            value = float(row.get(key, ""))
            if _math.isfinite(value):
                return value
        except (TypeError, ValueError):
            continue
    return None


def _schedule_deviation(row):
    count = _row_number(row, _SCHEDULE_COUNT_KEYS)
    if count is not None and count <= 0.0:
        return None
    availability_seen = False
    for key in _SCHEDULE_AVAILABLE_KEYS:
        raw = row.get(key, "")
        if str(raw).strip():
            availability_seen = True
        if str(raw).strip().lower() in ("0", "false", "no"):
            return None
    deviation = _row_number(row, _SCHEDULE_DEVIATION_KEYS)
    if count is None and not availability_seen and deviation == 0.0:
        return None
    return deviation


def _mean_rows(rows, metric):
    values = []
    for row in rows:
        value = (_schedule_deviation(row) if metric == "schedule"
                 else _row_number(row, metric))
        if value is not None:
            values.append(value)
    return _st.mean(values) if values else None


def _is_no_tsp(name):
    normalized = str(name or "").strip().upper()
    return normalized == "NO_TSP" or normalized.startswith("NO_TSP_")

# ── Champion auto-selection ───────────────────────────────────────────────────
# Reads the corridor's Phase-1 results (champion_<corr>.csv) and picks the TSP
# arm with the best mean objective on the eval seeds. If NO_TSP has the best
# objective, select the TSP arm that stays within the objective-gap tolerance
# and has the smallest absolute timetable deviation.
def _pick_champion():
    path = _os.path.join(_cs._ROOT, f"champion_{CORRIDOR}.csv")
    if not _os.path.isfile(path):
        return None, "no Phase-1 file"
    try:
        import csv as _csv, collections as _col
        with open(path, newline="", encoding="utf-8") as _fh:
            rows = list(_csv.DictReader(_fh))
        per = _col.defaultdict(list)
        for r in rows:
            name = r.get("run_experiment") or ""
            if not name:
                continue
            try:
                seed = int(r.get("run_seed", -1))
            except Exception:
                continue
            if seed not in _cs.EVAL_SEEDS:
                continue          # learners' train rows would skew the mean
            objective = _row_number(r, ("stats_Objective_PaxPerDelayHr",))
            if objective is None or objective == 0.0:
                continue
            per[name].append(r)
        complete = {
            name: arm_rows for name, arm_rows in per.items()
            if len({int(r.get("run_seed", -1)) for r in arm_rows})
            >= len(_cs.EVAL_SEEDS)
        }
        scored = {
            name: _mean_rows(arm_rows, ("stats_Objective_PaxPerDelayHr",))
            for name, arm_rows in complete.items()
        }
        scored = {name: value for name, value in scored.items()
                  if value is not None}
        if not scored:
            return None, "Phase-1 file has no arm with all eval seeds"

        baseline_names = [name for name in scored if _is_no_tsp(name)]
        tsp_scores = {name: value for name, value in scored.items()
                      if not _is_no_tsp(name)}
        if not tsp_scores:
            if baseline_names:
                return "NO_TSP", "only complete arm is NO_TSP"
            return None, "Phase-1 file has no complete non-NO_TSP arm"

        best_tsp = max(tsp_scores, key=tsp_scores.get)
        baseline_name = max(baseline_names, key=scored.get) if baseline_names else None
        if baseline_name is None or scored[best_tsp] > scored[baseline_name]:
            return best_tsp, \
                   "best of %d TSP arms: %s" % (len(tsp_scores),
                                                ", ".join("%s=%.1f" % kv
                                                          for kv in sorted(tsp_scores.items())))

        baseline_objective = scored[baseline_name]
        candidates = []
        for name in tsp_scores:
            objective_gap_pct = ((baseline_objective - tsp_scores[name])
                                 / abs(baseline_objective) * 100.0
                                 if baseline_objective else float("inf"))
            if objective_gap_pct > NO_TSP_MAX_OBJECTIVE_GAP_PCT:
                continue
            schedule_deviation = _mean_rows(complete[name], "schedule")
            candidates.append((schedule_deviation is None,
                               schedule_deviation if schedule_deviation is not None else 0.0,
                               -tsp_scores[name], name))

        if not candidates:
            return "NO_TSP", (
                "NO_TSP led objective and no complete TSP arm was within %.1f%% "
                "of its objective" % NO_TSP_MAX_OBJECTIVE_GAP_PCT)

        has_schedule = [candidate for candidate in candidates if not candidate[0]]
        selected_pool = has_schedule or candidates
        _, schedule_deviation, _, selected = min(selected_pool)
        schedule_note = (
            "%.1fs mean total abs timetable deviation" % schedule_deviation
            if has_schedule else "schedule deviation unavailable; best close objective")
        return selected, (
            "NO_TSP led objective; selected %s among TSP arms within %.1f%% "
            "objective gap by %s"
            % (selected, NO_TSP_MAX_OBJECTIVE_GAP_PCT, schedule_note))
    except Exception as e:
        return None, "parse error %r" % e

CHAMP_NAME, _pick_note = _pick_champion()
if CHAMP_NAME is None:
    CHAMP_NAME = "DCTSP_MARL"                 # historical KG winner fallback
    _pick_note += " -> fallback DCTSP_MARL"

SWEEP_ARMS = ["NO_TSP", CHAMP_NAME]           # reference + champion at every level
RESULTS_CSV = _os.path.join(_cs._ROOT, f"champion_bus_demand_{CORRIDOR}.csv")

_arms = [a for a in _cs.ARMS if a["name"] in SWEEP_ARMS]
# Order NO_TSP first so each bus level has its reference row before the champion.
_arms.sort(key=lambda a: SWEEP_ARMS.index(a["name"]))
print("[PHASE2] champion selected: %s (%s)" % (CHAMP_NAME, _pick_note))


def main():
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    PROJECT_DIR = _br.PROJECT_DIR

    n_total = len(BUS_DEMAND_SCALARS) * len(_arms) * len(SEEDS)
    log("=" * 70)
    log(f"CHAMPION BUS-DEMAND SENSITIVITY (Phase 2) -- corridor={CORRIDOR}")
    log(f"  bus scalars={BUS_DEMAND_SCALARS} | arms={[a['name'] for a in _arms]} "
        f"| seeds={SEEDS}")
    log(f"  total runs = {n_total}  (car/truck demand fixed at 1.0x)")
    log(f"  -> {RESULTS_CSV}")
    log("=" * 70)

    # fresh results file
    try:
        if _os.path.exists(RESULTS_CSV):
            _os.remove(RESULTS_CSV)
    except Exception:
        pass

    try:
        _br._set_logging(CONTROLLER_PATH, enabled=False)
    except Exception:
        pass
    # Same batch-speed setup as champion_search: no per-run dashboards/plots.
    _cs._disable_batch_plotting(CONTROLLER_PATH)

    rep = _br.get_first_replication()
    run_num = 0
    _pt_base = {}        # original PT timetable values -- prevents compounding
    base_demands = {}    # car/truck demand cache (kept at 1.0x)
    try:
        # Car/truck OD demand stays at 1.0x for the whole sweep.
        try:
            _br.set_demand_scalar(1.0, base_demands)
        except Exception as e:
            log(f"WARN car demand scalar 1.0: {e}")

        # One-time calibration (x1.0) so >1.0 levels can actually inject.
        _ensure_pt_calibration(_br, rep, CONTROLLER_PATH, RUN_CONFIG_PATH,
                               PROJECT_DIR, log)

        for bus_scalar in BUS_DEMAND_SCALARS:
            # ── Plan-B scaler: runtime injection, NOT timetable edits ──
            # Catalog-departure edits provably never reach the simulation
            # (2026-08-25 probes). The engine now synthesizes extra PT
            # vehicles via AKIPTEnterVeh from a calibrated entry pattern:
            #   x1.0 run  -> records natural entries (calibration)
            #   x>1.0 runs -> replay pattern + inject extras to reach N*x
            try:
                _bd.set_bus_freq_inject_scalar(bus_scalar, CONTROLLER_PATH)
                log(f"-- bus demand x{bus_scalar:g} (injection mode)")
            except Exception as e:
                log(f"FATAL bus scalar {bus_scalar}: {e}")
                continue

            for arm in _arms:
                name = arm["name"]
                strategy = arm["strategy"]
                coordinated = arm.get("coordinated", False)
                coord_algo = arm.get("coordination_algo", "KALMAN")
                rov = dict(arm.get("reward_overrides", {}) or {})
                is_baseline = (strategy == "NORMAL")
                if not is_baseline:
                    rov["Z4_CONSTRAINT_MODE"] = True
                    rov.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
                bus_pred = str(rov.get("BUS_PREDICTOR_TYPE", "ADAPTIVE_KALMAN")).upper()

                try:
                    _br.set_control_mode(strategy, CONTROLLER_PATH,
                                         arm.get("active_intersections"))
                    _br.set_coordinated(CONTROLLER_PATH, coordinated)
                    _br.set_coordination_algo(CONTROLLER_PATH, coord_algo)
                except Exception as e:
                    log(f"FATAL patch {name}: {e}")
                    continue

                _global_reward = bool(rov.get("GLOBAL_REWARD_MODE", False))
                _numeric = {k: v for k, v in rov.items() if k != "GLOBAL_REWARD_MODE"}
                # ALWAYS call set_reward_weights -- overrides for the champion, None
                # for the baseline. Passing None RESETS every mode flag to its
                # default False in the controller file, so DCTSP_MARL's flags cannot
                # LEAK into the NO_TSP run that follows it at the next bus level.
                # champion_search only ever ran NO_TSP FIRST so it never hit this;
                # the bus-demand sweep runs NO_TSP after DCTSP_MARL every level, so
                # the reset is mandatory (without it every arm looks identical --
                # exactly the "all results the same" symptom seen on Logan).
                try:
                    _br.set_reward_weights(
                        CONTROLLER_PATH,
                        (_numeric or None) if not is_baseline else None)
                except Exception as e:
                    log(f"WARN reward patch {name}: {e}")

                # None of the swept arms learn, so run per_seed (no train/eval split).
                try:
                    _cs._set_controller_bxt_seeds(
                        CONTROLLER_PATH, [], [], _cs.BXT_TRAIN_EPSILON)
                except Exception:
                    pass

                _run_reward_cfg = dict(_numeric)
                _run_reward_cfg["BUS_FREQ_INJECT_SCALAR"] = bus_scalar

                for seed in SEEDS:
                    run_num += 1
                    _label = f"{name}_BUSx{bus_scalar:g}"
                    log(f"[{run_num}/{n_total}] {CORRIDOR} | {_label} | seed={seed}")
                    m = _cs._run_and_collect(
                        _br, rep, _label, strategy, seed, 1.0,
                        coordinated, coord_algo, _global_reward,
                        _run_reward_cfg,
                        bus_pred, CONTROLLER_PATH, RUN_CONFIG_PATH,
                        PROJECT_DIR, RESULTS_CSV, log)
                    if m is not None:
                        # Sensitivity-analysis columns: clean base arm + bus level.
                        m["sweep_bus_demand_scalar"] = bus_scalar
                        m["sweep_base_arm"] = name
                        _br.append_master_csv(RESULTS_CSV, m)
    finally:
        # Injection scaler never mutates the model -- nothing to restore.
        # Just switch the feature off and re-enable logging.
        try:
            _bd.set_bus_freq_inject_scalar(0.0, CONTROLLER_PATH)
        except Exception:
            pass
        try:
            _br._set_logging(CONTROLLER_PATH, enabled=True)
        except Exception:
            pass

    log("=" * 70)
    log(f"DONE ({CORRIDOR}) -> {RESULTS_CSV}")
    log("=" * 70)


if __name__ == "__main__":
    main()
