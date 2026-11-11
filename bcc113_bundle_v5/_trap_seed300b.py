"""_trap_seed300b.py -- why paxEq falls 13% at NO_TSP seed300 when section flow does not.

Checks, in order:
  1. paxEq component breakdown (bus / car / truck) -- buses weigh 40x.
  2. section traversals per distinct vehicle on the COMMON section set.
  3. simulation window and rows beyond the nominal 1.5 h.
  4. vehicles still on the network at the last sample (stranded).
  5. time-resolved network queue and cumulative passages at the worst junction.
"""
import csv
import os
import sys
from collections import defaultdict

R = os.path.join("logan_road_new", "results")
A = os.path.join(R, "NO_TSP_seed300_75206_75207_75210_20261109_125103")
B = os.path.join(R, "NO_TSP_seed400_75206_75207_75210_20261109_130126")
WORST = "21847"


def per_int(folder):
    out = {}
    for r in csv.DictReader(open(os.path.join(folder, "simulation_results_per_intersection.csv"),
                                 newline="", encoding="utf-8-sig")):
        out[r["IntersectionID"]] = r
    return out


def main():
    a, b = per_int(A), per_int(B)
    print("=== 1. paxEq components (sum over junctions) ===")
    keys = ["BusVehPassages", "CarVehPassages", "TruckVehPassages",
            "BusPaxEquivPassages", "CarPaxEquivPassages", "TruckPaxEquivPassages",
            "PaxEquivPassages"]
    print("%-24s %12s %12s %8s" % ("component", "seed300", "seed400", "delta%"))
    for k in keys:
        va = sum(float(r[k]) for r in a.values())
        vb = sum(float(r[k]) for r in b.values())
        print("%-24s %12.0f %12.0f %+7.1f%%" % (k, va, vb, 100.0 * (va - vb) / vb))
    cars_a = sum(float(r["N_DistinctCars"]) for r in a.values())
    cars_b = sum(float(r["N_DistinctCars"]) for r in b.values())
    print("  (N_DistinctCars is per-junction, not a network total: %.0f / %.0f)" % (cars_a, cars_b))

    print()
    print("=== 2. section traversals on the COMMON section set ===")
    def sec_passages(folder):
        per = defaultdict(float)
        span = 0.0
        beyond = 0.0
        for row in csv.DictReader(open(os.path.join(folder, "section_timeseries.csv"),
                                        newline="", encoding="utf-8-sig")):
            t0, t1 = float(row["t_start_s"]), float(row["t_end_s"])
            dt = t1 - t0
            if dt <= 0:
                continue
            per[int(row["SectionID"])] += float(row["q_veh_h"]) * dt / 3600.0
            span = max(span, t1)
            if t0 > 5400.0:
                beyond += dt
        return per, span, beyond
    pa, spana, beyonda = sec_passages(A)
    pb, spanb, beyondb = sec_passages(B)
    common = set(pa) & set(pb)
    sa = sum(pa[s] for s in common)
    sb = sum(pb[s] for s in common)
    print("common sections         : %d  (300 only %d, 400 only %d)"
          % (len(common), len(set(pa) - set(pb)), len(set(pb) - set(pa))))
    print("passages on common set   : %.0f / %.0f  (%+.2f%%)" % (sa, sb, 100.0 * (sa - sb) / sb))
    print("run span (s)             : %.0f / %.0f" % (spana, spanb))
    print("sampled time beyond 5400s: %.0f / %.0f s" % (beyonda, beyondb))
    print("sections only in one run : 300:%s  400:%s"
          % (sorted(set(pa) - set(pb))[:8], sorted(set(pb) - set(pa))[:8]))

    print()
    print("=== 3. vehicles still present at the last sample (stranded) ===")
    def last_nveh(folder):
        last = {}
        for row in csv.DictReader(open(os.path.join(folder, "section_timeseries.csv"),
                                        newline="", encoding="utf-8-sig")):
            sid = int(row["SectionID"])
            t1 = float(row["t_end_s"])
            if sid not in last or t1 >= last[sid][0]:
                last[sid] = (t1, float(row["n_veh"]))
        return last
    la, lb = last_nveh(A), last_nveh(B)
    print("last-sample n_veh sum    : %.0f / %.0f" % (sum(v[1] for v in la.values()),
                                                      sum(v[1] for v in lb.values())))
    print("last t_end seen          : %.0f / %.0f" % (max(v[0] for v in la.values()),
                                                      max(v[0] for v in lb.values())))

    print()
    print("=== 4. network queue by 5-min bucket (veh-min of queue) ===")
    def qbuckets(folder):
        q = defaultdict(float)
        for row in csv.DictReader(open(os.path.join(folder, "section_timeseries.csv"),
                                        newline="", encoding="utf-8-sig")):
            t0 = float(row["t_start_s"])
            dt = float(row["t_end_s"]) - t0
            if dt <= 0:
                continue
            q[int(t0 // 300) * 5] += float(row["queue_veh"]) * dt / 60.0
        return q
    qa, qb = qbuckets(A), qbuckets(B)
    print("%-8s %10s %10s %8s" % ("t_min", "q300", "q400", "delta%"))
    for t in sorted(set(qa) | set(qb))[:20]:
        x, y = qa.get(t, 0.0), qb.get(t, 0.0)
        d = (100.0 * (x - y) / y) if y else float("nan")
        print("%-8d %10.0f %10.0f %+7.1f%%" % (t, x, y, d))

    print()
    print("=== 5. cumulative passages at junction %s by 10-min bucket ===" % WORST)
    def jcum(folder):
        rows = {}
        for r in csv.DictReader(open(os.path.join(folder, "bus_trips.csv"),
                                      newline="", encoding="utf-8-sig")):
            if r["IntersectionID"] == WORST:
                rows.setdefault("bus", []).append(float(r["EntryTime_s"]))
        return rows
    ja, jb = jcum(A), jcum(B)
    print("bus entries at %s     : %d / %d" % (WORST, len(ja.get("bus", [])), len(jb.get("bus", []))))
    if ja.get("bus") and jb.get("bus"):
        print("median bus entry (s)     : %.0f / %.0f"
              % (sorted(ja["bus"])[len(ja["bus"]) // 2], sorted(jb["bus"])[len(jb["bus"]) // 2]))
        print("max bus entry (s)        : %.0f / %.0f" % (max(ja["bus"]), max(jb["bus"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
