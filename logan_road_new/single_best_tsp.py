# =============================================================================
# single_best_intersection.py
# Finds the SINGLE best intersection to apply TSP for each strategy.
# Much faster than full greedy forward selection.
# =============================================================================

import os
import re
import csv
import time as _time
from PyANGKernel import GKSystem

# ========================== CONFIGURATION ==========================
STRATEGIES = [
    "HARMONY",
    "NORMAL",
    "URTSP",
    "GROUP_BASED",
    "GROUP_BASED_FIXED",   # uncomment if you want it
]

SEEDS = [100]                    # Add more seeds later: [100, 200, 300]
KPI_COLUMN = "TotalPassDelay_hrs"   # KPI to MINIMIZE

CONTROLLER_PATH = r"D:\Zeke_DEBUG_ERIC\kg\intersection_controller.py"
RUN_CONFIG_PATH = r"D:\Zeke_DEBUG_ERIC\kg\run_config.py"
RESULTS_ROOT    = r"D:\Aimsun_Results"
SENSITIVITY_ROOT = r"D:\Aimsun_Results\single_best"

ALL_INTERSECTIONS = [
    39606, 39590, 36393, 36385, 39593, 39587,
    39576, 39578, 1043762, 39569, 39572, 38339,
]
# ===================================================================

os.makedirs(SENSITIVITY_ROOT, exist_ok=True)

def log(msg):
    print("[SINGLE_BEST] " + str(msg))

# ---------------------------------------------------------------------------
# File patching
# ---------------------------------------------------------------------------
def patch_controller(strategy, active_subset):
    """Set CONTROL_MODE and TSP_ACTIVE_INTERSECTIONS"""
    with open(CONTROLLER_PATH, 'r', encoding='utf-8') as f:
        text = f.read()

    mode = "GROUP_BASED" if strategy == "GROUP_BASED_FIXED" else strategy
    priority = "False" if strategy == "GROUP_BASED_FIXED" else "True"

    text = re.sub(r'^(CONTROL_MODE\s*=\s*)["\'].*?["\']',
                  f'CONTROL_MODE = "{mode}"', text, flags=re.MULTILINE)
    
    text = re.sub(r'^(GROUP_BASED_BUS_PRIORITY\s*=\s*).*',
                  f'GROUP_BASED_BUS_PRIORITY = {priority}', text, flags=re.MULTILINE)

    new_val = "None" if active_subset is None else str(active_subset)
    text = re.sub(r'^(TSP_ACTIVE_INTERSECTIONS\s*=\s*).*',
                  f'TSP_ACTIVE_INTERSECTIONS = {new_val}', text, flags=re.MULTILINE)

    with open(CONTROLLER_PATH, 'w', encoding='utf-8') as f:
        f.write(text)

def write_run_config(strategy, seed, subset_label):
    content = f"""CURRENT_STRATEGY = "{strategy}"
CURRENT_SEED = {seed}
CURRENT_SUBSET = "{subset_label}"
"""
    with open(RUN_CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(content)

# ---------------------------------------------------------------------------
# Run replication
# ---------------------------------------------------------------------------
def get_replication():
    model = GKSystem.getSystem().getActiveModel()
    if model is None:
        raise RuntimeError("No active model.")
    rep_type = model.getType("GKReplication")
    reps = model.getCatalog().getObjectsByType(rep_type)
    return next(iter(reps.values())) if isinstance(reps, dict) else reps[0]

def run_once(rep, seed):
    try:
        rep.setRandomSeed(seed)
        rep.setStorePaths(False)
    except:
        pass

    GKSystem.getSystem().executeAction("execute", rep, [], "")
    
    import time as t
    t.sleep(3.0)
    waited = 0.0
    while waited < 7200:
        try:
            status = rep.getSimulationStatus()
            if status != 1:   # not running
                break
        except:
            pass
        t.sleep(0.5)
        waited += 0.5
    t.sleep(2.0)

# ---------------------------------------------------------------------------
# Read KPI from latest results
# ---------------------------------------------------------------------------
def read_latest_kpi(strategy, seed, kpi_col):
    best_time = 0
    best_val = None
    prefix = strategy + "_seed" + str(seed) + "_"
    
    for folder in os.listdir(RESULTS_ROOT):
        if not folder.startswith(prefix):
            continue
        csv_path = os.path.join(RESULTS_ROOT, folder, "simulation_results.csv")
        if not os.path.exists(csv_path):
            continue
        mtime = os.path.getmtime(csv_path)
        if mtime <= best_time:
            continue
        try:
            df = pd.read_csv(csv_path)
            if not df.empty and kpi_col in df.columns:
                val = float(df[kpi_col].iloc[-1])
                if mtime > best_time:
                    best_val = val
                    best_time = mtime
        except:
            pass
    return best_val

def average_kpi(strategy, subset, subset_label, seeds, kpi_col):
    values = []
    for seed in seeds:
        write_run_config(strategy, seed, subset_label)
        run_once(get_replication(), seed)
        val = read_latest_kpi(strategy, seed, kpi_col)
        if val is not None:
            values.append(val)
            log(f"  seed {seed}: {val:.4f}")
    return sum(values) / len(values) if values else float('inf')

# ---------------------------------------------------------------------------
# Main: Find single best intersection per strategy
# ---------------------------------------------------------------------------
import pandas as pd

def find_single_best_for_strategy(strategy):
    sens_dir = os.path.join(SENSITIVITY_ROOT, strategy)
    os.makedirs(sens_dir, exist_ok=True)
    
    log(f"\n=== Starting Single-Best Search for {strategy} ===")
    
    # Baseline (no TSP)
    patch_controller(strategy, [])
    baseline_kpi = average_kpi(strategy, [], "baseline", SEEDS, KPI_COLUMN)
    log(f"Baseline (no TSP): {baseline_kpi:.4f}")
    
    best_kpi = baseline_kpi
    best_intersection = None
    best_subset = []
    
    # Test each intersection individually
    for inter in ALL_INTERSECTIONS:
        trial_subset = [inter]
        label = f"single_{inter}"
        
        log(f"Testing intersection {inter} alone...")
        patch_controller(strategy, trial_subset)
        
        mean_kpi = average_kpi(strategy, trial_subset, label, SEEDS, KPI_COLUMN)
        improvement = ((baseline_kpi - mean_kpi) / baseline_kpi * 100) if baseline_kpi > 0 else 0
        
        log(f"→ KPI = {mean_kpi:.4f} ({improvement:.2f}% better)")
        
        if mean_kpi < best_kpi:
            best_kpi = mean_kpi
            best_intersection = inter
            best_subset = trial_subset
            log(f"   *** New best: {inter} ***")
    
    # Final result
    improvement_pct = ((baseline_kpi - best_kpi) / baseline_kpi * 100) if baseline_kpi > 0 else 0
    
    log(f"\n=== RESULT for {strategy} ===")
    log(f"Best single intersection : {best_intersection}")
    log(f"Baseline KPI             : {baseline_kpi:.4f}")
    log(f"Best KPI                 : {best_kpi:.4f}")
    log(f"Improvement              : {improvement_pct:.2f}%")
    
    # Save result
    with open(os.path.join(sens_dir, "single_best_result.txt"), "w") as f:
        f.write(f"Strategy: {strategy}\n")
        f.write(f"Best Intersection: {best_intersection}\n")
        f.write(f"Baseline KPI: {baseline_kpi:.4f}\n")
        f.write(f"Best KPI: {best_kpi:.4f}\n")
        f.write(f"Improvement: {improvement_pct:.2f}%\n")
    
    # Restore full TSP
    patch_controller(strategy, None)
    return best_intersection, best_kpi, baseline_kpi


# =============================================================================
# Main
# =============================================================================
def main():
    log("Single Best Intersection Search Started")
    log("Strategies: " + str(STRATEGIES))
    log("KPI to minimize: " + KPI_COLUMN)
    
    summary = []
    
    for strategy in STRATEGIES:
        try:
            best_inter, best_kpi, baseline = find_single_best_for_strategy(strategy)
            summary.append([strategy, best_inter, round(best_kpi, 4), 
                           round(baseline, 4), round(((baseline - best_kpi)/baseline*100), 2)])
        except Exception as e:
            log(f"ERROR with {strategy}: {e}")
    
    # Final summary
    print("\n" + "="*80)
    print("SINGLE BEST INTERSECTION SUMMARY")
    print("="*80)
    for row in summary:
        print(f"{row[0]:<15} → Best Inter: {row[1]:<6} | Improvement: {row[4]:5.1f}%")
    print("="*80)
    
    # Save summary CSV
    pd.DataFrame(summary, columns=["Strategy", "Best_Intersection", "Best_KPI", 
                                   "Baseline_KPI", "Improvement_Pct"]).to_csv(
        os.path.join(SENSITIVITY_ROOT, "single_best_summary.csv"), index=False)

if __name__ == "__main__":
    main()