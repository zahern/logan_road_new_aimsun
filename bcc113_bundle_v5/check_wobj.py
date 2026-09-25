#!/usr/bin/env python3
"""check_wobj.py -- weighted-objective component means per arm (live CSV)."""
import csv

rows = list(csv.DictReader(
    open("champion_kg.csv", newline="", encoding="utf-8-sig")))
EVAL = {"300", "400", "500", "600", "700"}


def F(r, k):
    try:
        v = float(r.get(k) or "nan")
        return v if v == v else None
    except Exception:
        return None


arms = {}
for r in rows:
    if str(r.get("run_seed", "")).split(".")[0] not in EVAL:
        continue
    arms.setdefault(r.get("run_experiment", "?"), []).append(r)

cols = ["stats_Objective_Weighted", "wobj_Z1_total", "wobj_Z2_total",
        "wobj_Z3_total", "wobj_Z4_total", "stats_Obj_Z1_delay_paxs",
        "stats_Obj_Z3_schedule_paxs", "stats_Obj_Z4_throughput_pax",
        "stats_AvgCarPassDelay_s", "stats_AvgBusPassDelay_s"]
print(f"{'arm':20s} " + " ".join(f"{c[6:16]:>10s}" for c in cols))
for name in sorted(arms):
    rs = arms[name]
    out = []
    for c in cols:
        vs = [v for v in (F(r, c) for r in rs) if v is not None]
        out.append(sum(vs) / len(vs) if vs else float("nan"))
    print(f"{name:20s} " + " ".join(f"{v:10.1f}" for v in out))
