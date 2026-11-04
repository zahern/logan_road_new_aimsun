"""analyze_paper_ladder.py -- one clean table for the paper's 5-method ladder.

Reads the suite CSV written by run_paper_ladder_5seeds.py (Aimsun) or
sweep_paper_ladder_*.csv (SUMO) and prints, per arm:
  n, total pax-delay hrs, % vs NO_TSP (paired same-seed), bus s/pax, car s/pax,
  and the TSP action mix (GE / INS / GR / ER / OC / ROT).

Usage:
    python analyze_paper_ladder.py paper_ladder_5seeds.csv
"""
import csv
import os
import sys
from collections import defaultdict


def _f(row, *names):
    for n in names:
        v = row.get(n)
        if v not in (None, "", "nan"):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def main(path):
    rows = [r for r in csv.DictReader(open(path, newline="", encoding="utf-8-sig"))
            if str(r.get("run_success", r.get("ok", "True"))).lower() != "false"]
    # Aimsun suite and SUMO sweep use different column names; accept both.
    tot = ("stats_TotalPassDelay_hrs", "truth_delay_hrs")
    bus = ("stats_AvgBusPassDelay_s", "avg_bus_pass_delay_s",
           "truth_mean_timeloss_s_bus")
    car = ("stats_AvgCarPassDelay_s", "truth_mean_timeloss_s_car")
    acts = [("GE", ("stats_TSP_Extensions", "n_tsp_extensions")),
            ("INS", ("stats_TSP_Insertions", "n_tsp_insertions")),
            ("GR", ("stats_TSP_GreenRealloc", "n_tsp_green_realloc")),
            ("ER", ("stats_TSP_EarlyRed", "n_tsp_early_red")),
            ("OC", ("stats_TSP_OffsetCorr", "n_tsp_offset_corr")),
            ("ROT", ("stats_TSP_PhaseRot", "n_tsp_phase_rot"))]

    g = defaultdict(dict)          # arm -> seed -> row
    for r in rows:
        seed = r.get("run_seed") or r.get("seed")
        arm = r.get("run_experiment") or r.get("arm")
        if seed and arm:
            g[arm][int(float(seed))] = r
    base = "NO_TSP" if "NO_TSP" in g else next(
        (a for a in g if a.endswith("NO_TSP")), None)
    if base is None:
        print("no NO_TSP baseline in", path)
        return
    print("%-34s %2s %9s %8s %7s %7s %s" %
          ("arm", "n", "totdel_h", "d%", "bus_s", "car_s", "acts GE/INS/GR/ER/OC/ROT"))
    base_tot = sum(_f(r, *tot) or 0 for r in g[base].values()) / max(1, len(g[base]))
    order = sorted(g, key=lambda a: sum(_f(r, *tot) or 0 for r in g[a].values())
                   / max(1, len(g[a])))
    for arm in order:
        rs = g[arm]
        t = sum(_f(r, *tot) or 0 for r in rs.values()) / max(1, len(rs))
        d = 100.0 * (t - base_tot) / base_tot if base_tot else 0.0
        b = sum(_f(r, *bus) or 0 for r in rs.values()) / max(1, len(rs))
        c = sum(_f(r, *car) or 0 for r in rs.values()) / max(1, len(rs))
        ac = []
        for _, cols in acts:
            v = [x for x in (_f(r, *cols) for r in rs.values()) if x is not None]
            ac.append("%.0f" % (sum(v) / len(v)) if v else "-")
        print("%-34s %2d %9.1f %+8.1f %7.2f %7.2f %s" %
              (arm, len(rs), t, d, b, c, "/".join(ac)))
    print("\npaired per-seed deltas vs %s:" % base)
    for arm in order:
        if arm == base:
            continue
        ds = []
        for seed, r in g[arm].items():
            if seed in g[base]:
                tb, ta = _f(g[base][seed], *tot), _f(r, *tot)
                if tb and ta is not None:
                    ds.append(100.0 * (ta - tb) / tb)
        if ds:
            ds.sort()
            print("  %-34s %+6.2f%%  (seeds: %s)" %
                  (arm, sum(ds) / len(ds),
                   ", ".join("%+.1f" % x for x in ds)))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python analyze_paper_ladder.py <suite.csv>")
    main(sys.argv[1])
