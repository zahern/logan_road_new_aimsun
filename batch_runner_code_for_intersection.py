# =============================================================================
# batch_runner_code_for_intersection.py — Aimsun Next 26 batch runner (REV05)
# =============================================================================
#
# HOW TO CONFIGURE:
#   1. Edit EXPERIMENTS below — each dict defines one experiment to run.
#   2. Edit SEEDS and DEMAND_SCALARS for replication/demand sweeps.
#   3. Call main() at the bottom (already done).
#
# EXPERIMENT DICT KEYS:
#   name                — folder-name prefix and display label
#   strategy            — one of: NORMAL, URTSP, HARMONY,
#                         GROUP_BASED, GROUP_BASED_URTSP, GROUP_BASED_HARMONY
#   active_intersections— None (all) or list of junction IDs, e.g. [17383, 19196]
#
# LOGGING:
#   When running batch, VERBOSE and all LOG_* flags in the controller are
#   automatically set to False so the Aimsun console stays clean.
#   The controller still writes everything to its log file.
# =============================================================================

import os as _os
import re
import json
import time as _time
from PyANGKernel import GKSystem

# =============================================================================
# ── EXPERIMENT DEFINITIONS ────────────────────────────────────────────────────
# =============================================================================
EXPERIMENTS = [
    {
        "name":                 "NORMAL",
        "strategy":             "NORMAL",
        "active_intersections": None,
    },
    {
        "name":                 "URTSP",
        "strategy":             "URTSP",
        "active_intersections": None,
    },
    {
        "name":                 "HARMONY",
        "strategy":             "HARMONY",
        "active_intersections": None,
    },
    {
        "name":                 "GROUP_BASED",
        "strategy":             "GROUP_BASED",
        "active_intersections": None,
    },
    {
        "name":                 "GROUP_BASED_URTSP",
        "strategy":             "GROUP_BASED_URTSP",
        "active_intersections": None,
    },
    {
        "name":                 "GROUP_BASED_HARMONY",
        "strategy":             "GROUP_BASED_HARMONY",
        "active_intersections": None,
    },
]

SEEDS           = [300, 201, 102, 103, 104]
DEMAND_SCALARS  = [1.0]           # e.g. [0.8, 1.0, 1.2] for demand sweeps
SCALE_TRUCKS    = False

TARGET_DEMAND_NAMES = ["01d Logan Rd 2025 AM", "01d Logan Rd 2025 PM"]

# =============================================================================
# ── INTERNAL CONFIG ───────────────────────────────────────────────────────────
# =============================================================================
CAR_KEYWORDS   = ("car",)
TRUCK_KEYWORDS = ("truck",)

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
        doc_dir = model.getDocumentDirectory()
        project_dir = doc_dir.absolutePath()
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
    if is_car:
        return True
    if is_truck and SCALE_TRUCKS:
        return True
    return False


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
            if matrix is None:
                continue
            if not _is_scalable_matrix(matrix):
                continue
            item_key = id(sched_item)
            if item_key not in base_demands:
                original_factor = sched_item.getFactor()
                try:
                    original_factor = float(original_factor)
                except Exception:
                    raise RuntimeError(
                        f"Schedule factor for '{matrix.getName()}' "
                        f"is not numeric: {original_factor}"
                    )
                base_demands[item_key] = original_factor
            new_factor = base_demands[item_key] * scalar
            sched_item.setFactor(new_factor)
            n_scaled += 1

    log(f"Demand scalar {scalar}x applied to {n_scaled} matrices.")


# =============================================================================
# ── CONTROLLER PATCHING ───────────────────────────────────────────────────────
# =============================================================================
def _set_logging(controller_path, enabled):
    """
    Patch VERBOSE and all LOG_* flags in the controller to True or False.
    When batch-running set enabled=False to silence the Aimsun console.
    The controller still writes to its log file regardless of VERBOSE.
    """
    with open(controller_path, 'r', encoding='utf-8') as f:
        text = f.read()

    val = "True" if enabled else "False"

    # Patch VERBOSE = ...
    text, n0 = re.subn(
        r'^(VERBOSE\s*=\s*).*',
        'VERBOSE = ' + val,
        text, flags=re.MULTILINE)

    # Patch every LOG_xxx = True/False line
    text, n1 = re.subn(
        r'^(LOG_\w+\s*=\s*)(True|False)',
        r'\g<1>' + val,
        text, flags=re.MULTILINE)

    with open(controller_path, 'w', encoding='utf-8') as f:
        f.write(text)

    if n0 + n1 > 0:
        log(f"Logging {'enabled' if enabled else 'disabled'} in controller "
            f"(VERBOSE + {n1} LOG_* flags).")
    else:
        log("WARNING: no VERBOSE/LOG_* flags found in controller.")


def set_control_mode(strategy, controller_path, active_intersections=None):
    """
    Patch CONTROL_MODE, GROUP_BASED_BUS_PRIORITY, and TSP_ACTIVE_INTERSECTIONS
    in the controller file.

    Supported strategies:
        NORMAL, URTSP, HARMONY,
        GROUP_BASED, GROUP_BASED_URTSP, GROUP_BASED_HARMONY,
        GROUP_BASED_FIXED  (→ GROUP_BASED + bus priority disabled)
    """
    with open(controller_path, 'r', encoding='utf-8') as f:
        text = f.read()

    if strategy == "GROUP_BASED_FIXED":
        mode     = "GROUP_BASED"
        priority = "False"
    else:
        mode     = strategy
        priority = "True"

    text, n1 = re.subn(
        r'^(CONTROL_MODE\s*=\s*)["\'].*?["\']',
        'CONTROL_MODE = "' + mode + '"',
        text, flags=re.MULTILINE)

    text, n2 = re.subn(
        r'^(GROUP_BASED_BUS_PRIORITY\s*=\s*).*',
        'GROUP_BASED_BUS_PRIORITY = ' + priority,
        text, flags=re.MULTILINE)

    if n2 == 0:
        text = re.sub(
            r'^(CONTROL_MODE\s*=\s*["\'].*?["\'])',
            r'\1\nGROUP_BASED_BUS_PRIORITY = ' + priority,
            text, flags=re.MULTILINE)

    tsp_value = repr(active_intersections)
    text, n3 = re.subn(
        r'^(TSP_ACTIVE_INTERSECTIONS\s*=\s*).*',
        'TSP_ACTIVE_INTERSECTIONS = ' + tsp_value,
        text, flags=re.MULTILINE)

    if n3 == 0:
        log("WARNING: TSP_ACTIVE_INTERSECTIONS not found in controller.")
    if n1 == 0:
        raise RuntimeError("CONTROL_MODE line not found in " + controller_path)

    with open(controller_path, 'w', encoding='utf-8') as f:
        f.write(text)

    active_label = "all" if active_intersections is None else str(active_intersections)
    log(f"CONTROL_MODE -> {mode} | bus_priority={priority} | TSP_ACTIVE -> {active_label}")


def write_run_config(experiment_name, strategy, seed, scalar, run_config_path):
    content = (
        "CURRENT_STRATEGY = "        + repr(strategy)        + "\n"
        "CURRENT_EXPERIMENT = "      + repr(experiment_name) + "\n"
        "CURRENT_SEED = "            + repr(seed)            + "\n"
        "CURRENT_DEMAND_SCALAR = "   + repr(scalar)          + "\n"
    )
    with open(run_config_path, 'w', encoding='utf-8') as f:
        f.write(content)
    log(f"run_config written: experiment={experiment_name} seed={seed} scalar={scalar}")


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
            if not any(k in title for k in ('result', 'statistic', 'summary', 'finish', 'output')):
                continue
            clicked = False
            for btn in w.findChildren(QPushButton):
                if any(t in btn.text().lower().replace('&', '') for t in ('close', 'ok', 'cancel')):
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
# ── MAIN ──────────────────────────────────────────────────────────────────────
# =============================================================================
def main():
    print("=" * 64)
    log("Batch runner starting (REV05)")

    try:
        PROJECT_DIR = get_project_dir()
    except RuntimeError as e:
        log("FATAL: " + str(e))
        return

    CONTROLLER_PATH = _os.path.join(PROJECT_DIR, "intersection_controller.py")
    RUN_CONFIG_PATH = _os.path.join(PROJECT_DIR, "run_config.py")

    n_total = len(EXPERIMENTS) * len(SEEDS) * len(DEMAND_SCALARS)
    log(f"Experiments: {[e['name'] for e in EXPERIMENTS]}")
    log(f"Seeds: {SEEDS}")
    log(f"Demand scalars: {DEMAND_SCALARS}")
    log(f"Total runs: {n_total}")
    print("=" * 64)

    # Disable logging in controller for the entire batch
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
    manifest     = []  # collects metadata for every run

    for scalar in DEMAND_SCALARS:
        log(f"==== Demand scalar: {scalar}x ====")
        set_demand_scalar(scalar, base_demands)

        for exp in EXPERIMENTS:
            exp_name   = exp["name"]
            strategy   = exp["strategy"]
            active_int = exp.get("active_intersections", None)

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

            for seed in SEEDS:
                run_num += 1
                print("-" * 64)
                log(f"Run {run_num}/{n_total} | scalar={scalar} "
                    f"experiment={exp_name} seed={seed}")

                set_seed(rep, seed)
                write_run_config(exp_name, strategy, seed, scalar, RUN_CONFIG_PATH)

                t0 = _time.time()
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

                manifest.append({
                    "run":                  run_num,
                    "experiment":           exp_name,
                    "strategy":             strategy,
                    "active_intersections": active_int,
                    "seed":                 seed,
                    "demand_scalar":        scalar,
                    "elapsed_s":            elapsed,
                    "success":              success,
                })

    print("=" * 64)
    log(f"Complete. {n_total - len(failures)}/{n_total} succeeded.")
    if failures:
        for f in failures:
            log(f"  FAILED: {f}")

    # Re-enable logging in controller so interactive use works after batch
    try:
        _set_logging(CONTROLLER_PATH, enabled=True)
    except Exception as e:
        log(f"WARNING: could not re-enable controller logging: {e}")

    # Save run manifest
    try:
        manifest_path = _os.path.join(PROJECT_DIR, "batch_manifest.json")
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        log(f"Manifest written: {manifest_path}")
    except Exception as e:
        log(f"WARNING: could not write manifest: {e}")

    print("=" * 64)


main()
