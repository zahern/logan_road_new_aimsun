# rank_sweep.py
# Rank a sweep CSV (run_sweep_hpc.py output) against its NO_TSP baseline,
# champion-search style: mean objective over eval rows per arm, % vs baseline.
#
#   python rank_sweep.py sweep_kg.csv
#   python rank_sweep.py sweep_kg.csv --demand 1.0 --eval-only

import argparse
import csv
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--demand", type=float, default=None)
    ap.add_argument("--metric", default="obj_pax_per_delay_hr",
                    help="objective column; lower is better")
    args = ap.parse_args()

    arms = defaultdict(list)
    with open(args.csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ok") not in ("True", "true", "1"):
                continue
            if args.demand is not None and \
                    abs(float(row.get("demand_scalar") or 0) - args.demand) > 1e-9:
                continue
            v = row.get(args.metric, "")
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v == 0.0:
                continue
            phase = row.get("phase", "eval")
            if phase != "eval":
                continue
            arms[row["arm"]].append(v)

    if "NO_TSP" not in arms:
        print("no NO_TSP eval rows found - nothing to rank against")
        return
    base = sum(arms["NO_TSP"]) / len(arms["NO_TSP"])
    print("baseline NO_TSP: %.2f (%d runs)" % (base, len(arms["NO_TSP"])))
    print("")
    ranked = []
    for arm, vals in arms.items():
        m = sum(vals) / len(vals)
        delta = (m - base) / base * 100.0
        ranked.append((delta, m, arm, len(vals)))
    ranked.sort()
    print("%-22s %10s %8s %6s" % ("arm", "mean obj", "% vs base", "n"))
    for delta, m, arm, n in ranked:
        print("%-22s %10.2f %+7.1f%% %6d" % (arm, m, delta, n))


if __name__ == "__main__":
    main()
