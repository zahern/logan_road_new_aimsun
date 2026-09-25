#!/usr/bin/env python3
"""check_tradeoff.py -- bus saved vs car/truck lost per arm vs NO_TSP (smoke)."""
import csv
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "champion_kg.csv"
rows = list(csv.DictReader(open(path, newline="", encoding="utf-8-sig")))
print(f"{path}: {len(rows)} rows")


def F(r, k):
    try:
        v = float(r.get(k) or "nan")
        return v if v == v else None
    except Exception:
        return None


by_arm_seed = {}
for r in rows:
    by_arm_seed[(r.get("run_experiment"),
                 str(r.get("run_seed", "")).split(".")[0])] = r
seeds = sorted({s for (_, s) in by_arm_seed})
print(f"{'arm':20s} " + " ".join(f"s{s}_net" for s in seeds) + "   mean_net")
for arm in sorted({a for (a, _) in by_arm_seed if a != "NO_TSP"}):
    nets = []
    line = f"{arm:20s} "
    for s in seeds:
        a = by_arm_seed.get((arm, s))
        b = by_arm_seed.get(("NO_TSP", s))
        if a is None or b is None:
            line += " " * 12
            continue
        db = F(b, "stats_SimBusDelay_pax_s") - F(a, "stats_SimBusDelay_pax_s")
        dc = F(b, "stats_SimCarDelay_pax_s") - F(a, "stats_SimCarDelay_pax_s")
        dt = F(b, "stats_SimTruckDelay_pax_s") - F(a, "stats_SimTruckDelay_pax_s")
        net = db + dc + dt
        nets.append(net)
        line += f"{net:+12.0f}"
    line += f"   {sum(nets) / len(nets):+10.0f}" if nets else ""
    print(line)
print("(per-seed net pax-s vs same-seed NO_TSP; + = saved)")
