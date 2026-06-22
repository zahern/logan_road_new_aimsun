"""
test_z2_live.py — After running one DRL_DENSITY experiment, check if Z2 is non-zero.
Run this AFTER a single simulation completes.

The controller must have:
  CONTROL_MODE = "DRL_DENSITY"
  COORDINATED_TSP = True
  BARGAIN_SPM_MODE = True (or any GLOBAL_REWARD variant)

Usage: Run from Aimsun's Run Script menu after a simulation.
"""
import os, glob, csv, sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR    = os.path.join(PROJECT_DIR, 'logs')

print("=" * 60)
print("Z2 Live Check")
print("=" * 60)

# ── Find the most recent weighted_objective CSV ───────────────────────────────
wobj_files = sorted(glob.glob(os.path.join(LOGS_DIR, 'weighted_objective_*.csv')),
                    key=os.path.getmtime, reverse=True)

if not wobj_files:
    print("\nERROR: No weighted_objective_*.csv found in logs/")
    print("The simulation may not have completed, or the controller")
    print("did not write weighted_objective output.")
    print("\nCheck:")
    print("  1. CONTROL_MODE is DRL_DENSITY?")
    print("  2. COORDINATED_TSP is True?")
    print("  3. Did the simulation run to completion?")
    sys.exit(1)

latest = wobj_files[0]
print(f"\nLatest: {os.path.basename(latest)}")

# ── Scan for Z2 values ────────────────────────────────────────────────────────
z2_col = None
total_rows = 0
z2_nonzero = 0
z2_values = []

with open(latest, 'r', encoding='utf-8', errors='ignore') as f:
    reader = csv.DictReader(f)
    if reader.fieldnames:
        for col in reader.fieldnames:
            if 'Z2' in col:
                z2_col = col
                break
    for row in reader:
        total_rows += 1
        if z2_col:
            try:
                v = float(row.get(z2_col, 0) or 0)
                if abs(v) > 0.001:
                    z2_nonzero += 1
                    z2_values.append(v)
            except: pass

print(f"  Total rows: {total_rows}")
print(f"  Z2 column: {z2_col or 'NOT FOUND'}")
print(f"  Non-zero Z2 rows: {z2_nonzero}")
if z2_values:
    print(f"  Z2 range: {min(z2_values):.3f}s to {max(z2_values):.3f}s")
    # Show first few non-zero samples
    print(f"  Sample values: {[f'{v:.2f}' for v in z2_values[:5]]}")

print(f"\n{'=' * 60}")
if z2_nonzero > 0:
    print("RESULT: Z2 IS WORKING")
    print(f"  {z2_nonzero} rows have non-zero offset-correction values.")
    print("  The DRL_DENSITY guard fix is confirmed.")
else:
    print("RESULT: Z2 IS ZERO")
    print("  All rows have Z2 = 0.0.")
    print("  The coordinator may not be running.")
    print("\n  Check in the Aimsun log for:")
    print("    '[INIT] Building corridor coordinators' — confirms guard is working")
    print("    '[CORRIDOR]' or '[OFFSET]' messages — confirms offset corrections")
    print("\n  If these are missing, verify:")
    print("    CONTROL_MODE = 'DRL_DENSITY'")
    print("    COORDINATED_TSP = True")
    print("    'DRL_DENSITY' is in the guard at line ~18155")

print("=" * 60)
