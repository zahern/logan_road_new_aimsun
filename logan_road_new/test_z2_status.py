"""
test_z2_status.py — Check Z2 guard status and historical data.
Run from Aimsun's Run Script menu or any Python console.
No pandas, no unicode — safe for embedded Python.
"""
import os, glob, csv, sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR    = os.path.join(PROJECT_DIR, 'logs')
CSV_PATH    = os.path.join(PROJECT_DIR, 'batch_results.csv')

print("=" * 60)
print("Z2 (offset-correction) Diagnostic")
print("=" * 60)

# ── STEP 1: Verify guards are correct (SOURCE CHECK) ─────────────────────────
CTRL_PATH = os.path.join(PROJECT_DIR, 'intersection_controller.py')
guards_ok = False
if os.path.isfile(CTRL_PATH):
    with open(CTRL_PATH, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    guard_blocks = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if ('if CONTROL_MODE in' in s or 'if COORDINATED_TSP or CONTROL_MODE in' in s) and '(' in s:
            block = s
            if ')' not in s:
                j = i + 1
                while j < len(lines) and ')' not in lines[j]:
                    block += ' ' + lines[j].strip()
                    j += 1
                if j < len(lines):
                    block += ' ' + lines[j].strip()
            guard_blocks.append((i+1, block))
        i += 1

    print("\n[STEP 1] Source guard check:")
    for ln, gtxt in guard_blocks:
        # Classify the guard
        is_coord = ('corridor_coordinators' in ''.join(lines[max(0,ln-5):ln]) or
                    'COORDINATED_TSP or' in gtxt or
                    'Building corridor coordinators' in ''.join(lines[ln:ln+5]))
        is_log   = 'PHASE GROUP SUMMARY' in ''.join(lines[max(0,ln-3):ln+3])
        is_group_reinit = 'GROUP_BASED' in gtxt and 'startswith' in ''.join(lines[ln-2:ln+2])

        if is_coord:
            has_drl = 'DRL_DENSITY' in gtxt
            tag = '[OK]' if has_drl else '[FIX NEEDED]'
            print(f"  Line {ln} coordinator: {tag}")
            if has_drl: guards_ok = True
        elif is_log or is_group_reinit:
            has_drl = 'DRL_DENSITY' in gtxt
            if not has_drl:
                print(f"  Line {ln} group-only: [OK - no DRL needed]")
            else:
                print(f"  Line {ln} group-only: [OK]")
        # else: skip non-coord guards silently

    if guards_ok:
        print("\n  --> Guards CORRECT. DRL_DENSITY is in coordinator build guards.")
        print("  --> Z2 WILL be computed on the next batch re-run.")
    else:
        print("\n  --> GUARDS STILL MISSING DRL_DENSITY. Z2 will stay 0.")
        print("  --> Check lines ~18155 and ~18579 in intersection_controller.py")
else:
    print("\n  intersection_controller.py not found - cannot verify guards")

# ── STEP 2: Check historical data (EXPECTED to be zero) ──────────────────────
print("\n[STEP 2] Historical data check (existing runs, pre-fix):")

# batch_results.csv
if os.path.isfile(CSV_PATH):
    with open(CSV_PATH, 'r', newline='', encoding='utf-8') as f:
        batch_rows = list(csv.DictReader(f))
    z2_nonzero = 0
    for r in batch_rows:
        try:
            v = float(r.get('wobj_Z2_total', '') or 0)
            if v != 0: z2_nonzero += 1
        except: pass
    print(f"  batch_results.csv: {len(batch_rows)} rows, {z2_nonzero} with non-zero Z2")
else:
    print(f"  batch_results.csv not found")

# weighted_objective CSVs
wobj_files = sorted(glob.glob(os.path.join(LOGS_DIR, 'weighted_objective_*.csv')))
if wobj_files:
    total_rows = 0
    total_z2_ok = 0
    for fp in wobj_files[:10]:  # sample first 10
        try:
            with open(fp, 'r') as f:
                rdr = csv.DictReader(f)
                for row in rdr:
                    total_rows += 1
                    for k in row:
                        if 'Z2' in k or 'offset' in k.lower():
                            try:
                                if float(row[k] or 0) != 0:
                                    total_z2_ok += 1
                            except: pass
                            break
        except: pass
    print(f"  {len(wobj_files)} weighted_objective CSVs, {total_rows} rows sampled")
    print(f"  Non-zero Z2 rows: {total_z2_ok}")
else:
    print(f"  No weighted_objective CSVs in logs/")

print("\n" + "=" * 60)
print("RESULT")
print("=" * 60)
if guards_ok:
    if z2_nonzero > 0:
        print("Guards: CORRECT. DRL_DENSITY in coordinator build guards.")
        print(f"Data: Z2 IS WORKING - {z2_nonzero} experiments with non-zero Z2.")
        print(f"      {total_z2_ok} rows with offset-correction values > 0.")
    else:
        print("Guards: CORRECT. DRL_DENSITY in coordinator build guards.")
        print("Data: Z2 still 0 (may be from pre-fix batch).")
        print("ACTION: Re-run the batch. Z2 will populate.")
else:
    print("ACTION: Add 'DRL_DENSITY' to the coordinator build guards")
    print("        at lines ~18155 and ~18579 in intersection_controller.py.")

print("\nNO_TSP Z3: Sigma IS tracked (_hw_update_sigma line 11587)")
print("but run_normal() never persists it. Needs code fix.")
