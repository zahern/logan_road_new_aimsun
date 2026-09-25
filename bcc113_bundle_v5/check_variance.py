#!/usr/bin/env python3
"""check_variance.py -- per-arm per-seed spread + what separates good/bad runs."""
import csv

rows = list(csv.DictReader(
    open("champion_kg.csv", newline="", encoding="utf-8-sig")))
print(f"rows: {len(rows)}")


def F(r, k):
    try:
        v = float(r.get(k) or "nan")
        return v if v == v else None
    except Exception:
        return None


KEYS = ["stats_Objective_PaxPerDelayHr", "stats_TotalPassDelay_hrs",
        "stats_AvgBusPassDelay_s", "stats_AvgCarPassDelay_s",
        "stats_TSP_Detections", "stats_TSP_Extensions",
        "stats_TSP_Insertions", "stats_TSP_GreenRealloc",
        "stats_TSP_EarlyRed", "stats_TSP_Detected_NoAction",
        "stats_TSP_NaturalGreen", "stats_N_DistinctBuses",
        "stats_N_DistinctCars", "stats_BusTotalTT_hrs"]
arms = {}
for r in rows:
    arms.setdefault(r.get("run_experiment", "?"), []).append(r)

for name in sorted(arms):
    rs = sorted(arms[name], key=lambda r: str(r.get("run_seed")))
    print(f"\n=== {name} (n={len(rs)}) ===")
    print(f"{'seed':>6s} " + " ".join(f"{k[6:18]:>12s}" for k in KEYS))
    for r in rs:
        vals = []
        for k in KEYS:
            v = F(r, k)
            vals.append(f"{v:12.1f}" if v is not None else f"{'NA':>12s}")
        print(f"{str(r.get('run_seed', '?')):>6s} " + " ".join(vals))
