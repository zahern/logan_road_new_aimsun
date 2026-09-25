#!/usr/bin/env python3
"""check_phase3_dup.py -- duplicate + tactic/freq effectiveness audit."""
import csv
from collections import defaultdict

rows = list(csv.DictReader(
    open("phase3_sensitivity_kg.csv", newline="", encoding="utf-8-sig")))
print(f"rows: {len(rows)}")

ACTS = ["stats_TSP_Extensions", "stats_TSP_Insertions",
        "stats_TSP_GreenRealloc", "stats_TSP_EarlyRed",
        "stats_TSP_OffsetCorr", "stats_TSP_PhaseSkip",
        "stats_TSP_PhaseRot"]


def F(r, k):
    try:
        v = float(r.get(k) or "nan")
        return v if v == v else None
    except Exception:
        return None


# 1. byte-identical headline KPIs across DIFFERENT cells, same (demand,seed)
SIG = ["stats_Objective_PaxPerDelayHr", "stats_TotalPassDelay_hrs",
       "stats_AvgCarPassDelay_s", "stats_N_DistinctCars"]
by_ds = defaultdict(list)
for r in rows:
    by_ds[(str(r.get("demand_scalar")), str(r.get("run_seed")).split(".")[0])].append(r)
print("\n--- cross-cell exact duplicates (same demand+seed, all KPIs equal) ---")
ndup = 0
for key, rs in sorted(by_ds.items()):
    sigs = {}
    for r in rs:
        s = tuple(round(F(r, k) or -1.0, 3) for k in SIG)
        sigs.setdefault(s, []).append(r)
    for s, grp in sigs.items():
        cells = [f"{r.get('sens_tactic')}/{r.get('sens_freq')}" for r in grp]
        if len(set(cells)) > 1:
            ndup += 1
            _cars = ",".join(str(int(F(r, "stats_N_DistinctCars") or -1)) for r in grp)
            _bus = ",".join(str(int(F(r, "stats_N_DistinctBuses") or -1)) for r in grp)
            print(f"  d={key[0]} seed={key[1]}: IDENTICAL in {sorted(set(cells))} "
                  f"[cars={_cars} buses={_bus}]")
print(f"  duplicate groups: {ndup}")

# 2. action mix per tactic (TIMES should be GE/INS/GR-heavy, SWAPS SEQ-heavy)
print("\n--- mean actions per tactic ---")
by_t = defaultdict(list)
for r in rows:
    by_t[r.get("sens_tactic")].append(r)
print(f"{'tactic':8s} " + " ".join(f"{a[10:18]:>8s}" for a in ACTS) + "   n")
for t, rs in sorted(by_t.items()):
    means = []
    for a in ACTS:
        vs = [F(r, a) or 0.0 for r in rs]
        means.append(sum(vs) / len(vs))
    print(f"{str(t):8s} " + " ".join(f"{m:8.1f}" for m in means) +
          f"   {len(rs)}")

# 3. freq effect: mean actions + obj per freq within each tactic
print("\n--- freq effect within tactic (mean ext+ins+gr+er+oc+ps+pr, mean obj) ---")
by_tf = defaultdict(list)
for r in rows:
    by_tf[(r.get("sens_tactic"), r.get("sens_freq"))].append(r)
for (t, f), rs in sorted(by_tf.items()):
    ta = sum(sum(F(r, a) or 0.0 for a in ACTS) for r in rs) / len(rs)
    ob = sum(F(r, "stats_Objective_PaxPerDelayHr") or 0.0 for r in rs) / len(rs)
    print(f"  {str(t):6s}/{str(f):12s} n={len(rs):3d} actions={ta:7.1f} obj={ob:7.1f}")
