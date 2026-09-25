#!/usr/bin/env python3
"""show_delay.py -- objective + delay columns from the smoke CSV."""
import csv

rows = list(csv.DictReader(
    open("champion_smoke_marls_kg.csv", newline="", encoding="utf-8-sig")))


def F(r, k):
    try:
        return float(r.get(k) or "nan")
    except Exception:
        return float("nan")


print(f"{'arm':20s} {'obj':>9s} {'vehDelay_h':>11s} {'schedPen_h':>11s} "
      f"{'inclSched_h':>11s}")
for r in rows:
    print(f"{r.get('run_experiment'):20s} "
          f"{F(r, 'stats_Objective_PaxPerDelayHr'):9.1f} "
          f"{F(r, 'stats_TotalPassDelay_hrs'):11.1f} "
          f"{F(r, 'stats_SchedulePenalty_hrs'):11.1f} "
          f"{F(r, 'stats_TotalPassDelayInclSched_hrs'):11.1f}")
