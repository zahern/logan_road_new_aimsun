#!/usr/bin/env python3
"""check_marl_vs_notsp.py -- per-seed MARL vs NO_TSP vs MILP_MPC comparison."""
import csv

with open("champion_kg.csv", "r", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

want = ("DCTSP_MARL", "NO_TSP", "MILP_MPC")
keys = ["stats_Objective_PaxPerDelayHr", "stats_TotalPassDelay_hrs",
        "stats_BusTotalTT_hrs", "stats_AvgBusTT_s", "stats_N_DistinctBuses",
        "stats_TSP_Detections", "stats_TSP_Extensions", "stats_TSP_Insertions"]
by_arm_seed = {}
for r in rows:
    if r.get("run_experiment") in want:
        by_arm_seed[(r["run_experiment"], r["run_seed"])] = r

seeds = sorted({s for (_, s) in by_arm_seed})
print(f"{'seed':>6s} {'arm':14s} " + " ".join(f"{k[6:22]:>16s}" for k in keys))
for s in seeds:
    for a in want:
        r = by_arm_seed.get((a, s))
        if r is None:
            print(f"{s:>6s} {a:14s} MISSING")
            continue
        print(f"{s:>6s} {a:14s} " + " ".join(
            f"{r.get(k, '?'):>16s}" for k in keys))
