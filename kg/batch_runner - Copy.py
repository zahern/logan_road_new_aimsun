# =============================================================================
# batch_runner.py — Aimsun Next 26 batch runner (REV06)
# =============================================================================
#
# QUICK-START:
#   1. Edit EXPERIMENTS — add/remove runs; set coordinated=True/False per run.
#   2. Edit SEEDS and DEMAND_SCALARS for replication / demand sweeps.
#   3. Run from Aimsun's "Run Script" menu (or Python console inside Aimsun).
#
# EXPERIMENT DICT KEYS:
#   name                — output folder prefix and display label
#   strategy            — NORMAL | URTSP | HARMONY | REWARD_TSP |
#                         GROUP_BASED | GROUP_BASED_URTSP | GROUP_BASED_HARMONY
#   coordinated         — True  → COORDINATED_TSP = True  (corridor coordination ON)
#                         False → COORDINATED_TSP = False (independent intersections)
#   active_intersections— None (all) or list of junction IDs e.g. [17383, 19196]
#
# LOGGING:
#   When batch mode starts ALL console/log flags in the controller are disabled:
#     VERBOSE = False
#     every LOG_* flag = False
#     STATUS_DASHBOARD_INTERVAL_S = 0
#     MARK_DETECTION_POINTS = False
#     OVERLAY_DETECTIONS_ON_MAP = False
#   The controller still writes results CSVs and summary.json regardless.
#   After the batch finishes all flags are restored to True.
#
# METRICS:
#   After every run the batch runner reads the controller's output CSVs and
#   appends a row to batch_results.csv in the project directory.  This gives
#   a single file that can be opened in Excel to compare all experiments.
# =============================================================================

import os as _os
import re
import json
import csv
import glob
import shutil
import sys as _sys
import time as _time
from PyANGKernel import GKSystem

# Script directory — used for dashboard import
_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))

# =============================================================================
# ── EXPERIMENT DEFINITIONS ───────────────────────────────────────────────────
# =============================================================================

EXPERIMENTS = [
    {
        "name":                 "NORMAL",
        "strategy":             "NORMAL",
        "coordinated":          False,      # independent intersections, no TSP
        "coordination_algo":    "KALMAN",
        "active_intersections": None,
    },
    # ── Harmony: coordinated vs independent (shows value of corridor coordination)
    # In current controller logic, coordinated HARMONY runs use CorridorCoordinator
    # pre-arm propagation (wave scheduling + downstream ETA-based preparation).
    {
        "name":                 "HARMONY_COORD",
        "strategy":             "HARMONY",
        "coordinated":          True,       # COORDINATED_TSP=True (corridor flag set)
        "coordination_algo":    "KALMAN",
        "active_intersections": None,
    },
    {
        "name":                 "HARMONY_COORD_SHOCKWAVE",
        "strategy":             "HARMONY",
        "coordinated":          True,
        "coordination_algo":    "SHOCKWAVE",
        "active_intersections": None,
    },
    {
        "name":                 "HARMONY_COORD_ADAPTIVE",
        "strategy":             "HARMONY",
        "coordinated":          True,
        "coordination_algo":    "ADAPTIVE",
        "active_intersections": None,
    },
    {
        "name":                 "HARMONY_INDEP",
        "strategy":             "HARMONY",
        "coordinated":          False,      # COORDINATED_TSP=False (independent)
        "coordination_algo":    "KALMAN",
        "active_intersections": None,
    },
    # Group-based runs are disabled by default for this batch profile.
    # Uncomment if you want them in a separate sweep.
    # {
    #     "name":                 "GROUP_BASED_HARMONY",
    #     "strategy":             "GROUP_BASED_HARMONY",
    #     "coordinated":          True,
    #     "coordination_algo":    "KALMAN",
    #     "active_intersections": None,
    # },
    # {
    #     "name":                 "GROUP_BASED_HARMONY_INDEP",
    #     "strategy":             "GROUP_BASED_HARMONY",
    #     "coordinated":          False,
    #     "coordination_algo":    "KALMAN",
    #     "active_intersections": None,
    # },
    # Uncomment to add more experiments:
    # {
    #     "name":                 "URTSP",
    #     "strategy":             "URTSP",
    #     "coordinated":          True,
    #     "active_intersections": None,
    # },
    # {
    #     "name":                 "GROUP_BASED",
    #     "strategy":             "GROUP_BASED",
    #     "coordinated":          True,
    #     "active_intersections": None,
    # },
    # ── Reward-TSP: action-reward based TSP (delay cost-benefit analysis) ─────
    {
        "name":                 "REWARD_TSP_COORD",
        "strategy":             "REWARD_TSP",
        "coordinated":          True,
        "coordination_algo":    "KALMAN",
        "active_intersections": None,
    },
    {
        "name":                 "REWARD_TSP_INDEP",
        "strategy":             "REWARD_TSP",
        "coordinated":          False,
        "coordination_algo":    "KALMAN",
        "active_intersections": None,
    },
    # ── DynaROPAC experiments — disabled (uncomment to re-enable) ────────────
    # {
    #     "name":                 "DYNAOPAC_COORD",
    #     "strategy":             "DYNAOPAC",
    #     "coordinated":          True,
    #     "coordination_algo":    "ADAPTIVE",
    #     "active_intersections": None,
    # },
    # {
    #     "name":                 "DYNAOPAC_INDEP",
    #     "strategy":             "DYNAOPAC",
    #     "coordinated":          False,
    #     "coordination_algo":    "KALMAN",
    #     "active_intersections": None,
    # },
    # {
    #     "name":                 "DYNAOPAC_COORD_SHOCKWAVE",
    #     "strategy":             "DYNAOPAC",
    #     "coordinated":          True,
    #     "coordination_algo":    "SHOCKWAVE",
    #     "active_intersections": None,
    # },
]

SEEDS           = [300]
DEMAND_SCALARS  = [1.0]        # e.g. [0.8, 1.0, 1.2] for demand sweeps
SCALE_TRUCKS    = False

TARGET_DEMAND_NAMES = ["01d Logan Rd 2025 AM", "01d Logan Rd 2025 PM"]

# =============================================================================
# ── INTERNAL CONFIG ───────────────────────────────────────────────────────────
# =============================================================================
CAR_KEYWORDS   = ("car",)
TRUCK_KEYWORDS = ("truck",)

# How long to wait (seconds) after patching the controller before starting the
# simulation — gives the OS time to flush the file to disk.
PATCH_SETTLE_S = 0.5

# =============================================================================
# ── LOGGING ───────────────────────────────────────────────────────────────────
# =============================================================================
def log(msg):
    print("[RUNNER] " + str(msg))


# =============================================================================
# ── PROJECT DIR ───────────────────────────────────────────────────────────────
# =============================================================================
def get_project_dir():
    model = GKSystem.getSystem().getActiveModel()
    if model is None:
        raise RuntimeError("No active model found. Open your project first.")
    try:
        project_dir = model.getDocumentDirectory().absolutePath()
    except Exception:
        try:
            filename = model.getDocumentFileName()
            if filename:
                project_dir = _os.path.dirname(filename)
            else:
                raise RuntimeError("Model has no document file name.")
        except Exception as e:
            raise RuntimeError(f"Could not determine project path: {e}")
    log("Project directory: " + project_dir)
    return project_dir


# =============================================================================
# ── DEMAND SCALING ────────────────────────────────────────────────────────────
# =============================================================================
def _is_scalable_matrix(matrix):
    try:
        v = matrix.getVehicle()
        vname = v.getName().lower() if v else ""
    except Exception:
        vname = ""
    is_car   = any(k in vname for k in CAR_KEYWORDS)
    is_truck = any(k in vname for k in TRUCK_KEYWORDS)
    return is_car or (is_truck and SCALE_TRUCKS)


def _is_target_demand(demand):
    if TARGET_DEMAND_NAMES is None:
        return True
    name = demand.getName().lower()
    return any(t.lower() in name for t in TARGET_DEMAND_NAMES)


def set_demand_scalar(scalar, base_demands):
    """Scale car (and optionally truck) demand. base_demands prevents compounding."""
    model = GKSystem.getSystem().getActiveModel()
    demand_type = model.getType("GKTrafficDemand")
    objs = model.getCatalog().getObjectsByType(demand_type)
    if not objs:
        log("WARNING: No GKTrafficDemand objects found.")
        return

    demand_list = list(objs.values()) if isinstance(objs, dict) else list(objs)
    n_scaled = 0

    for demand in demand_list:
        if not _is_target_demand(demand):
            continue
        schedule = demand.getSchedule()
        if not schedule:
            continue
        for sched_item in schedule:
            matrix = sched_item.getTrafficDemandItem()
            if matrix is None or not _is_scalable_matrix(matrix):
                continue
            item_key = id(sched_item)
            if item_key not in base_demands:
                original_factor_str = sched_item.getFactor()
                try:
                    base_demands[item_key] = float(original_factor_str)
                except Exception:
                    raise RuntimeError(
                        f"Schedule factor for '{matrix.getName()}' "
                        f"is not numeric: {original_factor_str}"
                    )
            new_factor = base_demands[item_key] * float(scalar)
            sched_item.setFactor("{:.6f}".format(new_factor))
            n_scaled += 1

    log(f"Demand scalar {scalar}x applied to {n_scaled} matrices.")


# =============================================================================
# ── CONTROLLER PATCHING ───────────────────────────────────────────────────────
# =============================================================================

def _read_controller(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _write_controller(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    # Flush OS buffer so Aimsun reads the updated file
    _time.sleep(PATCH_SETTLE_S)


def _purge_pyc(controller_path):
    """Delete any cached .pyc so Aimsun re-reads the patched .py next run."""
    base = _os.path.splitext(controller_path)[0]
    py_dir  = _os.path.dirname(controller_path)
    py_name = _os.path.basename(base)
    # __pycache__ is the normal location (Python 3)
    pycache = _os.path.join(py_dir, '__pycache__')
    for pyc in glob.glob(_os.path.join(pycache, py_name + '*.pyc')):
        try:
            _os.remove(pyc)
            log(f"Purged pyc cache: {pyc}")
        except Exception:
            pass
    # Legacy same-dir .pyc
    for pyc in glob.glob(base + '*.pyc'):
        try:
            _os.remove(pyc)
        except Exception:
            pass


def _set_logging(controller_path, enabled):
    """
    Patch ALL console/logging flags in the controller to True or False.

    When enabled=False the following are silenced:
      • VERBOSE
      • every LOG_* flag
      • STATUS_DASHBOARD_INTERVAL_S  (set to 0 / restored to 60)
      • OVERLAY_DETECTIONS_ON_MAP    (set to False — stops canvas annotation)

    NOTE: MARK_DETECTION_POINTS is intentionally NOT disabled during batch runs.
    It writes per-bus detection CSVs that the green-wave plot depends on.
    The per-run overhead is small and the data is valuable for post-analysis.

    The controller still writes simulation_results.csv / summary.json because
    those are triggered by save_results(), not by the LOG_* flags.
    """
    text = _read_controller(controller_path)
    val  = "True" if enabled else "False"

    # VERBOSE = ...
    text, n0 = re.subn(
        r'^(VERBOSE\s*=\s*).*',
        'VERBOSE = ' + val,
        text, flags=re.MULTILINE)

    # Every LOG_xxx = True/False line
    text, n1 = re.subn(
        r'^(LOG_\w+\s*=\s*)(True|False)',
        r'\g<1>' + val,
        text, flags=re.MULTILINE)

    # MARK_DETECTION_POINTS — always restored to True so detection CSVs are
    # generated for every run (green-wave plot needs them).
    text, n2 = re.subn(
        r'^(MARK_DETECTION_POINTS\s*:\s*bool\s*=\s*)(True|False)',
        r'\g<1>True',
        text, flags=re.MULTILINE)

    # OVERLAY_DETECTIONS_ON_MAP = True/False
    text, n3 = re.subn(
        r'^(OVERLAY_DETECTIONS_ON_MAP\s*:\s*bool\s*=\s*)(True|False)',
        r'\g<1>' + val,
        text, flags=re.MULTILINE)

    # STATUS_DASHBOARD_INTERVAL_S: 0 when disabled, 60 when re-enabled
    dash_val = "60.0" if enabled else "0.0"
    text, n4 = re.subn(
        r'^(STATUS_DASHBOARD_INTERVAL_S\s*:\s*float\s*=\s*)[\d.]+',
        r'\g<1>' + dash_val,
        text, flags=re.MULTILINE)

    _write_controller(controller_path, text)

    total = n0 + n1 + n2 + n3 + n4
    if total > 0:
        log(f"Logging {'enabled' if enabled else 'disabled'} in controller "
            f"(VERBOSE + {n1} LOG_* + MARK_DETECT=True(always) "
            f"+ OVERLAY={val} + DASHBOARD={dash_val}).")
    else:
        log("WARNING: no logging flags found in controller — check file path.")


def set_control_mode(strategy, controller_path, active_intersections=None):
    """
    Patch CONTROL_MODE, GROUP_BASED_BUS_PRIORITY, and TSP_ACTIVE_INTERSECTIONS.
    Verifies the patch was applied by re-reading the file after writing.
    """
    if strategy == "GROUP_BASED_FIXED":
        mode     = "GROUP_BASED"
        priority = "False"
    else:
        mode     = strategy
        priority = "True"

    text = _read_controller(controller_path)

    text, n1 = re.subn(
        r'^(CONTROL_MODE\s*=\s*)["\'].*?["\']',
        'CONTROL_MODE = "' + mode + '"',
        text, flags=re.MULTILINE)

    text, n2 = re.subn(
        r'^(GROUP_BASED_BUS_PRIORITY\s*=\s*).*',
        'GROUP_BASED_BUS_PRIORITY = ' + priority,
        text, flags=re.MULTILINE)

    if n2 == 0:
        # Insert after CONTROL_MODE line
        text = re.sub(
            r'^(CONTROL_MODE\s*=\s*["\'].*?["\'])',
            r'\1\nGROUP_BASED_BUS_PRIORITY = ' + priority,
            text, flags=re.MULTILINE)

    tsp_value = repr(active_intersections)
    text, n3 = re.subn(
        r'^(TSP_ACTIVE_INTERSECTIONS\s*=\s*).*',
        'TSP_ACTIVE_INTERSECTIONS = ' + tsp_value,
        text, flags=re.MULTILINE)

    if n1 == 0:
        raise RuntimeError("CONTROL_MODE line not found in " + controller_path)
    if n3 == 0:
        log("WARNING: TSP_ACTIVE_INTERSECTIONS not found in controller.")

    _write_controller(controller_path, text)

    # ── Verify patch was applied ──────────────────────────────────────────────
    verify = _read_controller(controller_path)
    if f'CONTROL_MODE = "{mode}"' not in verify:
        raise RuntimeError(
            f"Patch verification FAILED: CONTROL_MODE is not '{mode}' in "
            f"{controller_path} after writing.  Check file permissions."
        )

    active_label = "all" if active_intersections is None else str(active_intersections)
    log(f"CONTROL_MODE -> {mode} | bus_priority={priority} | "
        f"TSP_ACTIVE -> {active_label}  [patch verified OK]")


def set_coordinated(controller_path, coordinated: bool):
    """
    Patch COORDINATED_TSP = True/False in the controller.
    True  → corridor-wide bus-priority coordination across intersections.
    False → each intersection runs independently.

    The regex normalises any existing whitespace around the '=' so the
    verification string ('COORDINATED_TSP = True/False') always matches.
    """
    val  = "True" if coordinated else "False"
    text = _read_controller(controller_path)

    # Normalise spacing: replace 'COORDINATED_TSP <spaces>=<spaces> True/False'
    # with the canonical single-space form so verification is reliable.
    text, n = re.subn(
        r'^COORDINATED_TSP\s*=\s*(True|False)',
        f'COORDINATED_TSP = {val}',
        text, flags=re.MULTILINE)

    if n == 0:
        log("WARNING: COORDINATED_TSP not found in controller — cannot set.")
        return

    _write_controller(controller_path, text)

    # Verify (normalised form is now always present)
    verify = _read_controller(controller_path)
    if f'COORDINATED_TSP = {val}' not in verify:
        log(f"WARNING: COORDINATED_TSP patch verification failed. "
            f"Expected 'COORDINATED_TSP = {val}' in file.")
    else:
        log(f"COORDINATED_TSP -> {val}  [patch verified OK]")


def set_coordination_algo(controller_path, algo: str):
    """
    Patch COORDINATION_ALGO = "..." in the controller.
    Supported values: KALMAN | SHOCKWAVE | OBJECTIVE | ADAPTIVE.
    """
    algo_u = str(algo or "KALMAN").strip().upper()
    if algo_u not in {"KALMAN", "SHOCKWAVE", "OBJECTIVE", "ADAPTIVE"}:
        log(f"WARNING: unsupported COORDINATION_ALGO '{algo_u}', defaulting to KALMAN")
        algo_u = "KALMAN"

    text = _read_controller(controller_path)
    text, n = re.subn(
        r'^(COORDINATION_ALGO\s*=\s*)["\'].*?["\']',
        r'\1"' + algo_u + '"',
        text, flags=re.MULTILINE)

    if n == 0:
        log("WARNING: COORDINATION_ALGO not found in controller — cannot set.")
        return

    _write_controller(controller_path, text)

    verify = _read_controller(controller_path)
    if f'COORDINATION_ALGO   = "{algo_u}"' in verify or f'COORDINATION_ALGO = "{algo_u}"' in verify:
        log(f"COORDINATION_ALGO -> {algo_u}  [patch verified OK]")
    else:
        log(f"WARNING: COORDINATION_ALGO patch verification failed for {algo_u}")


def write_run_config(experiment_name, strategy, seed, scalar,
                     coordinated, coordination_algo, run_config_path):
    content = (
        "CURRENT_STRATEGY = "        + repr(strategy)        + "\n"
        "CURRENT_EXPERIMENT = "      + repr(experiment_name) + "\n"
        "CURRENT_SEED = "            + repr(seed)            + "\n"
        "CURRENT_DEMAND_SCALAR = "   + repr(scalar)          + "\n"
        "CURRENT_COORDINATED = "     + repr(coordinated)     + "\n"
        "CURRENT_COORDINATION_ALGO = "+ repr(coordination_algo)+ "\n"
    )
    with open(run_config_path, 'w', encoding='utf-8') as f:
        f.write(content)
    log(f"run_config written: experiment={experiment_name} "
        f"seed={seed} scalar={scalar} coordinated={coordinated} "
        f"coord_algo={coordination_algo}")


# =============================================================================
# ── REPLICATION HELPERS ───────────────────────────────────────────────────────
# =============================================================================
def get_first_replication():
    model = GKSystem.getSystem().getActiveModel()
    if model is None:
        raise RuntimeError("No active model.")
    rep_type = model.getType("GKReplication")
    if rep_type is None:
        raise RuntimeError("No GKReplication type found.")
    reps = model.getCatalog().getObjectsByType(rep_type)
    if not reps:
        raise RuntimeError("No replications found.")
    return next(iter(reps.values())) if isinstance(reps, dict) else reps[0]


def set_seed(rep, seed):
    try:
        rep.setRandomSeed(seed)
    except Exception:
        try:
            rep.getExperiment().setRandomSeed(seed)
        except Exception as e:
            log("WARNING: could not set seed: " + str(e))
    log("Seed -> " + str(seed))


def _close_dialogs(app):
    if app is None:
        return
    app.processEvents()
    try:
        from PyQt5.QtWidgets import QDialog, QPushButton
        for w in app.topLevelWidgets():
            if not w.isVisible():
                continue
            title = w.windowTitle().lower()
            if not any(k in title for k in ('result', 'statistic', 'summary',
                                             'finish', 'output')):
                continue
            clicked = False
            for btn in w.findChildren(QPushButton):
                if any(t in btn.text().lower().replace('&', '')
                       for t in ('close', 'ok', 'cancel')):
                    btn.click()
                    clicked = True
                    break
            if not clicked and isinstance(w, QDialog):
                w.reject()
        app.processEvents()
    except Exception:
        pass


def run_replication(rep):
    try:
        rep.setStorePaths(False)
    except Exception:
        pass
    try:
        rep.setOutputPathAssignment(None)
    except Exception:
        pass
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
    except ImportError:
        app = None

    GKSystem.getSystem().executeAction("execute", rep, [], "")
    _time.sleep(2.0)
    if app:
        app.processEvents()

    waited  = 0.0
    started = False
    while waited < 7200.0:
        if app:
            app.processEvents()
        try:
            status = rep.getSimulationStatus()
        except Exception:
            status = -1
        if not started and status == 1:
            started = True
            log("Simulation running...")
        if started and status != 1:
            break
        if not started and waited > 30.0:
            log("Assuming synchronous completion.")
            break
        _time.sleep(0.5)
        waited += 0.5
        if started and int(waited) % 30 == 0:
            log(f"  still running... {int(waited)}s")

    _time.sleep(2.0)
    if app:
        app.processEvents()
        _close_dialogs(app)


# =============================================================================
# ── METRICS COLLECTION ────────────────────────────────────────────────────────
# =============================================================================

def _find_results_folder(project_dir, strategy, seed, scalar, exp_name=None):
    """
    Locate the most-recently-written per-run results folder.

    The SimulationStats class writes to:
        <project>/results/<strategy>_seed<N>_<scenario>_<experiment>_<rep>/

    Newer runs write to:
        <project>/results/<experiment>_seed<N>_<scenario>_<experimentId>_<rep>/

    Older runs used '<strategy>_seed<seed>_...'. Try experiment prefix first,
    then fall back to strategy prefix for backward compatibility.
    """
    results_base = _os.path.join(project_dir, 'results')
    if not _os.path.isdir(results_base):
        return None

    prefixes = []
    if exp_name:
        safe_exp = ''.join(ch if ch.isalnum() or ch in ('_', '-') else '_' for ch in str(exp_name)).strip('_')
        if safe_exp:
            prefixes.append(f"{safe_exp}_seed{seed}")
    prefixes.append(f"{strategy}_seed{seed}")

    candidates = []
    for prefix in prefixes:
        candidates = [
            d for d in _os.scandir(results_base)
            if d.is_dir() and d.name.startswith(prefix)
        ]
        if candidates:
            break

    if not candidates:
        return None

    return max(candidates, key=lambda d: d.stat().st_mtime).path


def _read_csv_first_row(csv_path):
    """Read the LAST data row of a CSV as a dict (most recent run appended)."""
    if not _os.path.isfile(csv_path):
        return {}
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        return rows[-1] if rows else {}
    except Exception:
        return {}


def _read_json(json_path):
    if not _os.path.isfile(json_path):
        return {}
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _latest_rows_by_intersection(rows):
    """
    Keep only the latest row per intersection ID.

    simulation_results_per_intersection.csv is append-only across repeated runs,
    so run-scoped filtering can still return historical duplicates. Taking the
    latest row per intersection recovers the current-run snapshot.
    """
    latest = {}
    for r in rows:
        iid = str(r.get("IntersectionID", "")).strip()
        if not iid:
            continue
        latest[iid] = r
    return list(latest.values())


def _clear_previous_outputs(project_dir):
    """
    Start batch from a clean state.

    Removes old logs and prior generated batch artifacts so dashboard and CSV
    metrics always reflect the current batch only.
    """
    removed = {"files": 0, "dirs": 0}

    def _safe_remove(path):
        try:
            if _os.path.isdir(path):
                shutil.rmtree(path)
                removed["dirs"] += 1
            elif _os.path.isfile(path):
                _os.remove(path)
                removed["files"] += 1
        except Exception as e:
            log(f"WARNING: could not remove {path}: {e}")

    # 1) logs/ folder contents
    logs_dir = _os.path.join(project_dir, "logs")
    if _os.path.isdir(logs_dir):
        for name in _os.listdir(logs_dir):
            _safe_remove(_os.path.join(logs_dir, name))

    # 2) Batch-level artifacts
    for p in (
        _os.path.join(project_dir, "batch_results.csv"),
        _os.path.join(project_dir, "batch_manifest.json"),
        _os.path.join(project_dir, "tsp_dashboard.html"),
    ):
        _safe_remove(p)

    # 3) Per-run result CSV/JSON files inside results/* folders
    results_dir = _os.path.join(project_dir, "results")
    if _os.path.isdir(results_dir):
        for d in _os.scandir(results_dir):
            if not d.is_dir():
                continue
            for fname in (
                "simulation_results.csv",
                "simulation_results_per_intersection.csv",
                "summary.json",
                "bus_trips.csv",
            ):
                _safe_remove(_os.path.join(d.path, fname))

    log(f"Startup cleanup done: removed {removed['files']} files, {removed['dirs']} folders")


def collect_run_metrics(project_dir, strategy, seed, scalar,
                        exp_name, coordinated, elapsed_s, success):
    """
    After a simulation run, read SimulationStats output files and return a
    flat dict of all key metrics for this run.

    Sources
    -------
    simulation_results.csv          — global KPIs (delay, pax, TSP events)
    simulation_results_per_intersection.csv — per-junction detail (first row only)
    summary.json                    — quick overview
    Aimsun model objects            — network-level flow/density/speed via PyANGKernel
    """
    meta = {
        "run_experiment":       exp_name,
        "run_strategy":         strategy,
        "run_coordinated":      coordinated,
        "run_seed":             seed,
        "run_demand_scalar":    scalar,
        "run_elapsed_s":        elapsed_s,
        "run_success":          success,
    }

    if not success:
        return meta

    folder = _find_results_folder(project_dir, strategy, seed, scalar, exp_name)
    if folder is None:
        log(f"  WARNING: results folder not found for {strategy} seed={seed}")
        return meta

    # Store the results folder path so generate_dashboard.py can load per-intersection CSVs
    meta["stats_results_folder"] = folder

    # ── 1. Global simulation_results.csv ──────────────────────────────────────
    global_row = _read_csv_first_row(_os.path.join(folder, "simulation_results.csv"))
    for k, v in global_row.items():
        if k is not None:
            meta["stats_" + k] = v

    # ── 2. summary.json ───────────────────────────────────────────────────────
    summary = _read_json(_os.path.join(folder, "summary.json"))
    for k, v in summary.items():
        if isinstance(v, (int, float, str, bool)):
            meta["json_" + k] = v

    # ── 3. Per-intersection aggregates from simulation_results_per_intersection.csv
    inter_csv = _os.path.join(folder, "simulation_results_per_intersection.csv")
    if _os.path.isfile(inter_csv):
        try:
            with open(inter_csv, 'r', newline='', encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
            # Aggregate numeric columns across all intersections for this run
            # (all rows belong to this run — filter by TSP_Strategy to be safe)
            # Filter to THIS run only using the IDs from the global CSV row.
            # Without this, accumulated CSV rows from prior runs of the same
            # strategy inflate inter_sum (e.g. 2 runs × 9 intersections = 18 rows).
            _scen = str(global_row.get("ScenarioID", "")).strip()
            _exp  = str(global_row.get("ExperimentID", "")).strip()
            _rep  = str(global_row.get("ReplicationID", "")).strip()
            if _scen and _exp and _rep:
                run_rows = [
                    r for r in rows
                    if str(r.get("ScenarioID","")).strip()  == _scen
                    and str(r.get("ExperimentID","")).strip() == _exp
                    and str(r.get("ReplicationID","")).strip() == _rep
                ]
            else:
                run_rows = [r for r in rows if r.get("TSP_Strategy", "") == strategy]
            if not run_rows:
                run_rows = [r for r in rows if r.get("TSP_Strategy", "") == strategy] or rows

            # Historical rows accumulate across repeated runs in the same folder.
            # Keep the latest row per intersection to isolate current-run values.
            run_rows = _latest_rows_by_intersection(run_rows)
            agg_cols = [
                "TotalPassDelay_hrs", "MainPassDelay_hrs", "SidePassDelay_hrs",
                "BusTotalTT_hrs", "N_BusTrips", "N_DistinctBuses",
                "N_DistinctCars", "N_DistinctTrucks",
                "BusVehPassages", "CarVehPassages", "TruckVehPassages",
                "PaxEquivPassages", "BusPaxEquivPassages", "CarPaxEquivPassages",
                "AvgBusTT_s", "AvgPassDelay_s",
                "AvgBusPassDelay_s", "AvgCarPassDelay_s", "AvgTruckPassDelay_s",
                "TSP_Detections", "TSP_Extensions", "TSP_Insertions",
                "TSP_Skipped_GE", "TSP_Skipped_Ins", "TSP_Detected_NoAction",
                "TSP_NaturalGreen",   # bus caught green without any TSP action
            ]
            for col in agg_cols:
                vals = []
                for r in run_rows:
                    try:
                        vals.append(float(r[col]))
                    except Exception:
                        pass
                if vals:
                    meta[f"inter_sum_{col}"] = round(sum(vals), 4)
                    meta[f"inter_avg_{col}"] = round(sum(vals) / len(vals), 4)
                    meta[f"inter_n"]          = len(run_rows)
        except Exception as e:
            log(f"  WARNING: could not parse per-intersection CSV: {e}")

    # ── 4. Aimsun model network-level statistics (PyANGKernel) ───────────────
    try:
        aimsun_stats = _collect_aimsun_network_stats()
        meta.update(aimsun_stats)
    except Exception as e:
        log(f"  INFO: Aimsun network stats not available: {e}")

    log(f"  Metrics collected from: {folder}")
    return meta


def _collect_aimsun_network_stats():
    """
    Read network-level statistics from the Aimsun model object after a run.

    Returns a dict with keys prefixed 'aimsun_'.
    Falls back gracefully if any API call fails.

    Aimsun Next 25/26 statistics API is version-dependent. We try multiple
    patterns in order:
      1. getDataValueString / getDataValue (Aimsun Next 25+)
      2. Direct attribute access (getFlow, getDensity, getMeanSpeed)
      3. No-arg getStatistic() for some column IDs
    """
    out = {}
    try:
        model = GKSystem.getSystem().getActiveModel()
        if model is None:
            return out

        sec_type = model.getType("GKSection")
        if sec_type is None:
            return out

        sections = model.getCatalog().getObjectsByType(sec_type)
        if not sections:
            return out

        sec_list = list(sections.values()) if isinstance(sections, dict) else list(sections)

        # Length-weighted accumulators (all vehicles and per-type)
        # Aimsun reports length-weighted averages: total(metric×length) / total(length)
        wt_flow     = 0.0;  wt_density  = 0.0;  wt_speed    = 0.0;  wt_delay    = 0.0
        wt_flow_car = 0.0;  wt_dens_car = 0.0;  wt_spd_car  = 0.0;  wt_dly_car  = 0.0
        wt_flow_bus = 0.0;  wt_dens_bus = 0.0;  wt_spd_bus  = 0.0;  wt_dly_bus  = 0.0
        wt_flow_trk = 0.0;  wt_dens_trk = 0.0;  wt_spd_trk  = 0.0;  wt_dly_trk  = 0.0
        total_len   = 0.0
        n_sec       = 0
        n_flow_ok   = 0

        for sec in sec_list:
            try:
                # Section length in metres → km
                sec_len_km = 0.0
                for attr in ("length2D", "length", "getLengthInMeters"):
                    try:
                        fn = getattr(sec, attr, None)
                        v = fn() if callable(fn) else fn
                        if v is not None and float(v) > 0:
                            sec_len_km = float(v) / 1000.0
                            break
                    except Exception:
                        pass
                if sec_len_km <= 0:
                    sec_len_km = 0.1  # 100 m default so unresolved sections still contribute

                flow    = _safe_stat_v2(sec, "flow")
                density = _safe_stat_v2(sec, "density")
                speed   = _safe_stat_v2(sec, "speed")
                delay   = _safe_stat_v2(sec, "delay")

                n_sec += 1
                if flow > 0:
                    n_flow_ok += 1
                wt_flow    += flow    * sec_len_km
                wt_density += density * sec_len_km
                wt_speed   += speed   * sec_len_km
                wt_delay   += delay   * sec_len_km
                total_len  += sec_len_km

                # Per-vehicle-type: try car, bus, truck via named-type stat methods
                for _prefix, _ttype in (("car", "Car"), ("bus", "Bus"), ("truck", "Truck")):
                    _flow  = _safe_stat_v2_typed(sec, "flow",    _ttype)
                    _dens  = _safe_stat_v2_typed(sec, "density", _ttype)
                    _spd   = _safe_stat_v2_typed(sec, "speed",   _ttype)
                    _dly   = _safe_stat_v2_typed(sec, "delay",   _ttype)
                    if _prefix == "car":
                        wt_flow_car += _flow * sec_len_km; wt_dens_car += _dens * sec_len_km
                        wt_spd_car  += _spd  * sec_len_km; wt_dly_car  += _dly  * sec_len_km
                    elif _prefix == "bus":
                        wt_flow_bus += _flow * sec_len_km; wt_dens_bus += _dens * sec_len_km
                        wt_spd_bus  += _spd  * sec_len_km; wt_dly_bus  += _dly  * sec_len_km
                    else:
                        wt_flow_trk += _flow * sec_len_km; wt_dens_trk += _dens * sec_len_km
                        wt_spd_trk  += _spd  * sec_len_km; wt_dly_trk  += _dly  * sec_len_km
            except Exception:
                pass

        if n_sec > 0 and total_len > 0:
            out["aimsun_n_sections"]        = n_sec
            out["aimsun_flow_sections_ok"]  = n_flow_ok
            # Length-weighted network averages — match Aimsun's Time Series output
            if wt_flow > 0:
                out["aimsun_total_flow_veh"]   = round(wt_flow    / total_len, 2)
                out["aimsun_avg_density_vkm"]  = round(wt_density / total_len, 4)
                out["aimsun_avg_speed_kmh"]    = round(wt_speed   / total_len, 4)
                out["aimsun_avg_delay_s_km"]   = round(wt_delay   / total_len, 2)
            # Per-type averages (car, bus, truck)
            for _pfx, _wf, _wd, _ws, _wdly in [
                ("car", wt_flow_car, wt_dens_car, wt_spd_car, wt_dly_car),
                ("bus", wt_flow_bus, wt_dens_bus, wt_spd_bus, wt_dly_bus),
                ("truck", wt_flow_trk, wt_dens_trk, wt_spd_trk, wt_dly_trk),
            ]:
                if _wf > 0:
                    out[f"aimsun_flow_{_pfx}"]    = round(_wf   / total_len, 2)
                    out[f"aimsun_density_{_pfx}"] = round(_wd   / total_len, 4)
                    out[f"aimsun_speed_{_pfx}"]   = round(_ws   / total_len, 4)
                    out[f"aimsun_delay_{_pfx}"]   = round(_wdly / total_len, 2)

    except Exception as e:
        out["aimsun_error"] = str(e)

    # Also try reading aggregate network stats from the active experiment
    try:
        model = GKSystem.getSystem().getActiveModel()
        if model is not None:
            for attr in ("getFlow", "getMeanTravelTime", "getMeanDelay"):
                fn = getattr(model, attr, None)
                if fn:
                    try:
                        v = fn()
                        if v is not None and float(v) > 0:
                            out[f"aimsun_model_{attr[3:].lower()}"] = round(float(v), 3)
                    except Exception:
                        pass
    except Exception:
        pass

    return out


def _safe_stat_v2(section, stat_name: str) -> float:
    """
    Try multiple Aimsun API patterns to read a per-section aggregate statistic.
    Returns 0.0 if nothing works — callers must guard against all-zero results.

    Known working patterns (version-dependent):
      • getFlow() / getDensity() / getMeanSpeed() — zero-arg property methods
      • getDataValueString(col_id, rep, interval, vehtype) — Aimsun 25+
      • Direct attribute access (rarely used but included as fallback)
    """
    # Map stat name → common zero-arg method names and attribute names
    _method_map = {
        "flow":    ("getFlow",     "flow"),
        "density": ("getDensity",  "density"),
        "speed":   ("getMeanSpeed","speed",   "getMeanTravelSpeed"),
        "delay":   ("getMeanDelay","delay",   "getDelay"),
    }
    candidates = _method_map.get(stat_name, (stat_name,))

    for name in candidates:
        # Try as zero-arg method
        fn = getattr(section, name, None)
        if callable(fn):
            try:
                v = fn()
                if v is not None:
                    fv = float(v)
                    if fv >= 0:
                        return fv
            except Exception:
                pass
        # Try as attribute
        v = getattr(section, name, None)
        if v is not None:
            try:
                fv = float(v)
                if fv >= 0:
                    return fv
            except Exception:
                pass

    # Aimsun Next 25+ API: getDataValueString(column_type, replication, interval, vehtype)
    # Column type IDs differ by version; we try common ones
    _col_ids = {
        "flow":    [0x0001, 1],
        "density": [0x0002, 2],
        "speed":   [0x0004, 4],
        "delay":   [0x0020, 32],
    }
    for col_id in _col_ids.get(stat_name, []):
        for method_name in ("getDataValue", "getStatistic"):
            fn = getattr(section, method_name, None)
            if not callable(fn):
                continue
            for args in ((col_id, None, None, None), (col_id,), (col_id, None)):
                try:
                    v = fn(*args)
                    if v is not None:
                        fv = float(v)
                        if fv >= 0:
                            return fv
                except Exception:
                    pass

    return 0.0


def _safe_stat_v2_typed(section, stat_name: str, veh_type_name: str) -> float:
    """
    Like _safe_stat_v2 but attempts to read a per-vehicle-type statistic.
    veh_type_name: 'Car', 'Bus', 'Truck' (or lowercase)
    Returns 0.0 if unavailable.
    """
    # Try method variants: getCarFlow, getBusFlow, etc.
    vtn = veh_type_name.capitalize()
    stat_cap = stat_name.capitalize()
    for name in (f"get{vtn}{stat_cap}", f"get{vtn}Mean{stat_cap}", f"get{stat_cap}For{vtn}"):
        fn = getattr(section, name, None)
        if callable(fn):
            try:
                v = fn()
                if v is not None:
                    fv = float(v)
                    if fv >= 0:
                        return fv
            except Exception:
                pass
    return 0.0


# =============================================================================
# ── MASTER RESULTS CSV ────────────────────────────────────────────────────────
# =============================================================================

def append_master_csv(master_path, row_dict):
    """
    Append one metrics row to the master batch_results.csv.
    Creates the file with headers on the first call.
    All keys in row_dict become columns; missing keys are blank.

    Column expansion: if a later run introduces keys not in the existing
    header, the entire file is rewritten with the union of all headers so
    no run's data is ever silently truncated by extrasaction='ignore'.
    """
    # Deterministic priority column order — appears left-to-right in the CSV
    priority_keys = [
        "run_experiment", "run_strategy", "run_coordinated",
        "run_seed", "run_demand_scalar", "run_elapsed_s", "run_success",
        # Global stats (from simulation_results.csv)
        "stats_TSP_Strategy",
        "stats_TotalPassDelay_hrs", "stats_MainPassDelay_hrs", "stats_SidePassDelay_hrs",
        "stats_SimTotalDelay_pax_s", "stats_SimBusDelay_pax_s",
        "stats_SimCarDelay_pax_s",   "stats_SimTruckDelay_pax_s",
        "stats_PaxEquivPassages",    "stats_BusPaxEquivPassages",
        "stats_CarPaxEquivPassages", "stats_TruckPaxEquivPassages",
        "stats_AvgPassDelay_s",      "stats_AvgBusPassDelay_s",
        "stats_AvgCarPassDelay_s",   "stats_AvgTruckPassDelay_s",
        "stats_BusTotalTT_hrs",      "stats_AvgBusTT_s",
        "stats_N_BusTrips",          "stats_N_DistinctBuses",
        "stats_N_DistinctCars",      "stats_N_DistinctTrucks",
        "stats_TSP_Detections",      "stats_TSP_Extensions", "stats_TSP_Insertions",
        "stats_TSP_Skipped_GE",      "stats_TSP_Skipped_Ins",
        "stats_TSP_Detected_NoAction", "stats_TSP_NaturalGreen",
        "stats_Prearm_Fired",        "stats_Prearm_Success",
        "stats_Prearm_Missed",       "stats_Prearm_Expired",     "stats_Prearm_Discarded",
        "stats_Prearm_LateSuccess",  "stats_Prearm_LateSuccessDelay_s",
        "stats_TSP_TotalExtension_s","stats_TSP_TotalInsertion_s",
        "stats_TSP_AvgExtension_s",  "stats_TSP_AvgInsertion_s", "stats_TSP_AvgInsertionWait_s",
        "stats_Net_TotalFlowVeh",    "stats_Net_AvgDensity_vkm", "stats_Net_AvgSpeed_kmh",
        "stats_Net_Delay_All",        "stats_Net_Delay_Car",       "stats_Net_Delay_Bus",      "stats_Net_Delay_Truck",
        "stats_Objective_PaxPerDelayHr",
        # Per-intersection aggregates
        "inter_n",
        "inter_sum_TotalPassDelay_hrs",
        "inter_sum_BusTotalTT_hrs",
        "inter_sum_N_BusTrips",
        "inter_sum_CarVehPassages",
        "inter_sum_BusVehPassages",
        "inter_sum_PaxEquivPassages",
        "inter_avg_AvgBusTT_s",
        "inter_avg_AvgPassDelay_s",
        "inter_avg_AvgBusPassDelay_s",
        "inter_avg_AvgCarPassDelay_s",
        "inter_sum_TSP_Detections",
        "inter_sum_TSP_Extensions",
        "inter_sum_TSP_Insertions",
        "inter_sum_TSP_Skipped_GE",
        "inter_sum_TSP_Skipped_Ins",
        "inter_sum_TSP_Detected_NoAction",
        "inter_sum_TSP_NaturalGreen",
        # Aimsun network-level stats (from PyANGKernel post-run)
        "aimsun_n_sections",
        "aimsun_total_flow_veh",
        "aimsun_avg_density_vkm",
        "aimsun_avg_speed_kmh",
        "aimsun_total_delay_s",
        # Results folder path (for per-intersection CSV loading in dashboard)
        "stats_results_folder",
    ]
    priority_set = set(priority_keys)

    try:
        file_exists = _os.path.isfile(master_path)

        # ── Read existing header (if any) ─────────────────────────────────────
        existing_header = []
        existing_rows   = []
        if file_exists:
            try:
                with open(master_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    existing_header = list(reader.fieldnames or [])
                    existing_rows   = list(reader)
            except Exception:
                existing_header = []
                existing_rows   = []

        # ── Compute the union of all columns in deterministic order ───────────
        # priority_keys first, then any extras already in the file,
        # then any brand-new extras from the current row.
        existing_extra = [k for k in existing_header if k not in priority_set]
        new_extra      = [k for k in sorted(row_dict)
                          if k not in priority_set and k not in existing_header]
        all_keys = priority_keys + existing_extra + new_extra

        # ── If header changed, rewrite the whole file ─────────────────────────
        if new_extra and existing_rows:
            log(f"  CSV: new columns found ({new_extra}) — rewriting batch_results.csv")
            with open(master_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(existing_rows)
            file_exists = True  # header already written

        # ── Append the new row ────────────────────────────────────────────────
        with open(master_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction='ignore')
            if not file_exists:
                writer.writeheader()
            writer.writerow(row_dict)

    except Exception as e:
        log(f"WARNING: could not write master CSV: {e}")


# =============================================================================
# ── MAIN ──────────────────────────────────────────────────────────────────────
# =============================================================================
def main():
    print("=" * 68)
    log("Batch runner starting (REV06)")

    try:
        PROJECT_DIR = get_project_dir()
    except RuntimeError as e:
        log("FATAL: " + str(e))
        return

    CONTROLLER_PATH = _os.path.join(PROJECT_DIR, "intersection_controller.py")
    RUN_CONFIG_PATH = _os.path.join(PROJECT_DIR, "run_config.py")
    MASTER_CSV_PATH = _os.path.join(PROJECT_DIR, "batch_results.csv")
    MANIFEST_PATH   = _os.path.join(PROJECT_DIR, "batch_manifest.json")

    if not _os.path.isfile(CONTROLLER_PATH):
        log(f"FATAL: controller not found at {CONTROLLER_PATH}")
        return

    # Clean old logs/results so this batch run starts from a deterministic state.
    _clear_previous_outputs(PROJECT_DIR)

    n_total = len(EXPERIMENTS) * len(SEEDS) * len(DEMAND_SCALARS)
    log(f"Experiments : {[e['name'] for e in EXPERIMENTS]}")
    log(f"Seeds       : {SEEDS}")
    log(f"Scalars     : {DEMAND_SCALARS}")
    log(f"Total runs  : {n_total}")
    log(f"Master CSV  : {MASTER_CSV_PATH}")
    print("=" * 68)

    # ── Disable ALL logging in controller for the entire batch ────────────────
    try:
        _set_logging(CONTROLLER_PATH, enabled=False)
    except Exception as e:
        log(f"WARNING: could not disable controller logging: {e}")

    try:
        rep = get_first_replication()
    except RuntimeError as e:
        log("FATAL: " + str(e))
        return

    run_num      = 0
    failures     = []
    base_demands = {}
    manifest     = []

    for scalar in DEMAND_SCALARS:
        log(f"==== Demand scalar: {scalar}x ====")
        set_demand_scalar(scalar, base_demands)

        for exp in EXPERIMENTS:
            exp_name    = exp["name"]
            strategy    = exp["strategy"]
            coordinated = exp.get("coordinated", True)
            coord_algo  = exp.get("coordination_algo", "KALMAN")
            active_int  = exp.get("active_intersections", None)

            # ── Patch CONTROL_MODE ─────────────────────────────────────────
            try:
                set_control_mode(strategy, CONTROLLER_PATH, active_int)
            except Exception as e:
                log(f"FATAL: cannot patch strategy {strategy}: {e}")
                for seed in SEEDS:
                    failures.append({
                        "scalar": scalar, "experiment": exp_name,
                        "seed": seed, "error": str(e),
                    })
                continue

            # ── Patch COORDINATED_TSP ─────────────────────────────────────
            try:
                set_coordinated(CONTROLLER_PATH, coordinated)
            except Exception as e:
                log(f"WARNING: could not patch COORDINATED_TSP: {e}")

            try:
                set_coordination_algo(CONTROLLER_PATH, coord_algo)
            except Exception as e:
                log(f"WARNING: could not patch COORDINATION_ALGO: {e}")

            for seed in SEEDS:
                run_num += 1
                print("-" * 68)
                log(f"Run {run_num}/{n_total} | scalar={scalar} "
                    f"| experiment={exp_name} | strategy={strategy} "
                    f"| coordinated={coordinated} | algo={coord_algo} | seed={seed}")

                set_seed(rep, seed)
                write_run_config(exp_name, strategy, seed, scalar,
                                 coordinated, coord_algo, RUN_CONFIG_PATH)

                # Purge .pyc so Aimsun re-reads the patched controller
                _purge_pyc(CONTROLLER_PATH)

                t0      = _time.time()
                success = True
                try:
                    run_replication(rep)
                    elapsed = int(_time.time() - t0)
                    log(f"Run {run_num}/{n_total} DONE in {elapsed}s")
                except Exception as e:
                    elapsed = int(_time.time() - t0)
                    log(f"Run {run_num}/{n_total} FAILED in {elapsed}s: {e}")
                    failures.append({
                        "scalar": scalar, "experiment": exp_name,
                        "seed": seed, "error": str(e),
                    })
                    success = False

                # ── Collect and save metrics ───────────────────────────────
                try:
                    metrics = collect_run_metrics(
                        PROJECT_DIR, strategy, seed, scalar,
                        exp_name, coordinated, elapsed, success
                    )
                    append_master_csv(MASTER_CSV_PATH, metrics)
                except Exception as e:
                    log(f"WARNING: metrics collection failed: {e}")

                manifest.append({
                    "run":                  run_num,
                    "experiment":           exp_name,
                    "strategy":             strategy,
                    "coordinated":          coordinated,
                    "active_intersections": active_int,
                    "seed":                 seed,
                    "demand_scalar":        scalar,
                    "elapsed_s":            elapsed,
                    "success":              success,
                })

    print("=" * 68)
    log(f"Batch complete. {n_total - len(failures)}/{n_total} succeeded.")
    if failures:
        for f in failures:
            log(f"  FAILED: {f}")

    # ── Re-enable logging so interactive use works normally after batch ────────
    try:
        _set_logging(CONTROLLER_PATH, enabled=True)
        log("Controller logging restored to True.")
    except Exception as e:
        log(f"WARNING: could not re-enable controller logging: {e}")

    # ── Save manifest ─────────────────────────────────────────────────────────
    try:
        with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        log(f"Manifest written: {MANIFEST_PATH}")
    except Exception as e:
        log(f"WARNING: could not write manifest: {e}")

    log(f"Master metrics CSV: {MASTER_CSV_PATH}")

    # ── Generate HTML comparison dashboard ────────────────────────────────────
    try:
        import importlib, sys as _sys
        if _SCRIPT_DIR not in _sys.path:
            _sys.path.insert(0, _SCRIPT_DIR)
        import generate_dashboard as _gd
        importlib.reload(_gd)
        _html = _gd.generate(
            batch_csv=MASTER_CSV_PATH,
            log_dir=_os.path.join(PROJECT_DIR, "logs"),
        )
        if _html:
            log(f"HTML dashboard: {_html}")
    except Exception as _dbe:
        log(f"WARNING: HTML dashboard generation failed: {_dbe}")

    print("=" * 68)


main()
