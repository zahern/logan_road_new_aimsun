"""_trap_seed300.py -- where does NO_TSP seed300 lose its progression?

Integrates section_timeseries.csv (q_veh_h over dt) into per-section vehicle
passages, and queue_veh over dt into queue-seconds, then compares seed 300
against seed 400 on the same build. No Aimsun needed; read-only.

    python _trap_seed300.py
"""
import csv
import os
import sys

R = os.path.join("logan_road_new", "results")
A = os.path.join(R, "NO_TSP_seed300_75206_75207_75210_20261109_125103")
B = os.path.join(R, "NO_TSP_seed400_75206_75207_75210_20261109_130126")


def load(folder):
    per = {}
    path = os.path.join(folder, "section_timeseries.csv")
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sid = int(row["SectionID"])
            d = per.get(sid)
            if d is None:
                d = per[sid] = {
                    "lanes": float(row["Lanes"]),
                    "len_km": float(row["Length_km"]),
                    "inter": row["IntersectionID"],
                    "main": row["IsMain"],
                    "veh": 0.0,        # vehicle passages
                    "qsec": 0.0,       # queue veh-seconds
                    "qpeak": 0.0,
                    "qmax": 0.0,
                    "kmax": 0.0,
                    "vmin": 1e9,
                    "t": 0.0,
                }
            t0 = float(row["t_start_s"])
            t1 = float(row["t_end_s"])
            dt = t1 - t0
            if dt <= 0:
                continue
            q = float(row["q_veh_h"])
            k = float(row["k_vkm_lane"])
            v = float(row["v_kmh"])
            qq = float(row["queue_veh"])
            d["t"] += dt
            d["veh"] += q * dt / 3600.0
            d["qsec"] += qq * dt
            d["qpeak"] = max(d["qpeak"], qq)
            d["qmax"] = max(d["qmax"], q)
            d["kmax"] = max(d["kmax"], k)
            if k > 0 and v > 0:
                d["vmin"] = min(d["vmin"], v)
    return per


def main():
    a = load(A)
    b = load(B)
    ta = sum(d["veh"] for d in a.values())
    tb = sum(d["veh"] for d in b.values())
    print("run span (s)      : %6.0f / %6.0f" % (max(d["t"] for d in a.values()),
                                                 max(d["t"] for d in b.values())))
    print("sections          : %d / %d" % (len(a), len(b)))
    print("total passages    : %9.0f / %9.0f  (300 is %+.1f%%)"
          % (ta, tb, 100.0 * (ta - tb) / tb))
    print()

    common = sorted(set(a) & set(b))
    rows = []
    for sid in common:
        da, db = a[sid], b[sid]
        # expected 300 passages if it merely shared 400's per-section share
        exp = tb and (db["veh"] / tb) * ta or 0.0
        rows.append((da["veh"] - exp, sid, da, db, exp))

    rows.sort()
    print("=== biggest shortfalls vs seed400's spatial share (veh passages) ===")
    print("%-7s %-7s %-5s %8s %8s %8s %7s %7s %6s"
          % ("Section", "Junc", "Main", "veh300", "veh400", "expctd", "defcit", "qsec%", "v300"))
    for gap, sid, da, db, exp in rows[:18]:
        qs = 100.0 * (da["qsec"] - db["qsec"]) / db["qsec"] if db["qsec"] > 0 else float("nan")
        print("%-7d %-7s %-5s %8.0f %8.0f %8.0f %7.0f %7.0f %6.1f"
              % (sid, da["inter"], da["main"], da["veh"], db["veh"], exp, gap, qs,
                 da["vmin"] if da["vmin"] < 1e8 else 0.0))

    print()
    print("=== biggest queue-seconds increases (300 vs 400) ===")
    byq = sorted(common, key=lambda s: a[s]["qsec"] - b[s]["qsec"], reverse=True)
    print("%-7s %-7s %10s %10s %9s %8s %8s"
          % ("Section", "Junc", "qsec300", "qsec400", "delta", "qpeak300", "kmax300"))
    for sid in byq[:15]:
        da, db = a[sid], b[sid]
        print("%-7d %-7s %10.0f %10.0f %9.0f %8.1f %8.1f"
              % (sid, da["inter"], da["qsec"], db["qsec"], da["qsec"] - db["qsec"],
                 da["qpeak"], da["kmax"]))

    print()
    print("=== per-junction passages (top 12 by absolute gap) ===")
    ja, jb = {}, {}
    for per, tgt in ((a, ja), (b, jb)):
        for d in per.values():
            tgt[d["inter"]] = tgt.get(d["inter"], 0.0) + d["veh"]
    jr = sorted(ja, key=lambda j: ja[j] - jb.get(j, 0.0))
    print("%-9s %9s %9s %9s" % ("Junction", "veh300", "veh400", "delta"))
    for j in jr[:12]:
        print("%-9s %9.0f %9.0f %9.0f" % (j, ja[j], jb.get(j, 0.0), ja[j] - jb.get(j, 0.0)))

    print()
    print("=== storage check: queue_veh peak vs lanes*length*k_jam (k=90,150) ===")
    top = [s for s in byq[:8]]
    print("%-7s %5s %6s %7s %7s %7s"
          % ("Section", "lanes", "len_km", "qpeak", "cap90", "cap150"))
    for sid in top:
        d = a[sid]
        cap90 = d["lanes"] * d["len_km"] * 90.0
        cap150 = d["lanes"] * d["len_km"] * 150.0
        print("%-7d %5.0f %6.3f %7.1f %7.1f %7.1f"
              % (sid, d["lanes"], d["len_km"], d["qpeak"], cap90, cap150))
    return 0


if __name__ == "__main__":
    sys.exit(main())
