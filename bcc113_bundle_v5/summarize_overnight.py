"""summarize_overnight.py -- persist a per-ARM aggregate + paired t-test.

The suite runner (run_aimsun_arm_suite_5seeds.py) writes a per-(arm,seed) CSV and
its *_summary.csv, but the across-seed MEANS and the paired t-test vs NO_TSP are
only PRINTED to stdout -- after an overnight run they scroll away. This reads the
per-row CSV and writes:

    <stem>_aggregate.csv   one row per arm: mean objective / throughput / delay,
                           % vs NO_TSP, paired t vs NO_TSP (same seed), win count.

Run LOCALLY on Windows (RULE 1 -- never on the login node):

    python -I summarize_overnight.py bellman_harmony_overnight.csv
"""
import csv
import sys
import os
import statistics as st

PCT_DANGER = None  # set by caller; unused

# Passenger occupancies for the FAIR objective (match the engine defaults;
# override via env if the model uses different values).
CAR_OCC = float(os.environ.get("FAIR_CAR_OCC", "1.2"))
BUS_OCC = float(os.environ.get("FAIR_BUS_OCC", "40.0"))
# Trucks counted like cars (1 occupant -> same 1.2 pax-equiv weight), per operator.
TRUCK_OCC = float(os.environ.get("FAIR_TRUCK_OCC", "1.2"))


def _f(r, k):
    try:
        return float(r.get(k, "") or 0.0)
    except Exception:
        return float("nan")


def _fair_pax(r):
    """DISTINCT passengers served = distinct vehicles x occupancy. Unlike
    stats_PaxEquivPassages (summed per-junction crossings, inflated ~12x by how far
    a vehicle progresses) this is ~invariant to corridor progression, so the
    fair_obj = fair_pax / delay stops amplifying a small delay delta into a huge
    objective delta. Demand is fixed, so this is ~constant across arms and the fair
    comparison reduces to total passenger DELAY -- which is the honest differentiator."""
    return (_f(r, "stats_N_DistinctCars") * CAR_OCC
            + _f(r, "stats_N_DistinctBuses") * BUS_OCC
            + _f(r, "stats_N_DistinctTrucks") * TRUCK_OCC)


def _paired_t(xs, ys):
    """Paired t statistic + two-sided p for xs vs ys (same order). Pure-python;
    no scipy dependency. p via a Welch-free Student-t survival approximation."""
    d = [a - b for a, b in zip(xs, ys)]
    n = len(d)
    if n < 2:
        return float("nan"), float("nan")
    m = st.mean(d)
    sd = st.pstdev(d) * (n / (n - 1)) ** 0.5 if n > 1 else 0.0
    if sd == 0.0:
        return (float("inf") if m else 0.0), (0.0 if m else 1.0)
    t = m / (sd / n ** 0.5)
    # two-sided p from a t-dist with n-1 dof via the regularized incomplete beta
    df = n - 1
    x = df / (df + t * t)
    # continued-fraction betainc(x; df/2, 1/2) -> Student-t tail
    import math

    def _betacf(a, b, x):
        MAXIT, EPS, FPMIN = 200, 3e-12, 1e-300
        qab, qap, qam = a + b, a + 1.0, a - 1.0
        c = 1.0
        d0 = 1.0 - qab * x / qap
        if abs(d0) < FPMIN:
            d0 = FPMIN
        d0 = 1.0 / d0
        h = d0
        for mm in range(1, MAXIT + 1):
            m2 = 2 * mm
            aa = mm * (b - mm) * x / ((qam + m2) * (a + m2))
            d0 = 1.0 + aa * d0
            if abs(d0) < FPMIN:
                d0 = FPMIN
            c = 1.0 + aa / c
            if abs(c) < FPMIN:
                c = FPMIN
            d0 = 1.0 / d0
            h *= d0 * c
            aa = -(a + mm) * (qab + mm) * x / ((a + m2) * (qap + m2))
            d0 = 1.0 + aa * d0
            if abs(d0) < FPMIN:
                d0 = FPMIN
            c = 1.0 + aa / c
            if abs(c) < FPMIN:
                c = FPMIN
            d0 = 1.0 / d0
            de = d0 * c
            h *= de
            if abs(de - 1.0) < EPS:
                break
        return h

    def _betai(a, b, x):
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        lbeta = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                 + a * math.log(x) + b * math.log(1.0 - x))
        bt = math.exp(lbeta)
        if x < (a + 1.0) / (a + b + 2.0):
            return bt * _betacf(a, b, x) / a
        return 1.0 - bt * _betacf(b, a, 1.0 - x) / b

    p = _betai(df / 2.0, 0.5, x)
    return t, p


def main(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig", errors="replace")))
    by = {}
    for r in rows:
        by.setdefault(r.get("run_experiment", ""), {})[
            int(float(r.get("run_seed", 0)))] = r
    if "NO_TSP" not in by:
        print("NO_TSP rows missing from", path)
        return
    seeds = sorted(by["NO_TSP"].keys())
    base = by["NO_TSP"]

    OBJ = "stats_Objective_PaxPerDelayHr"
    THR = "stats_PaxEquivPassages"
    DEL = "stats_TotalPassDelay_hrs"
    MAIN = "stats_MainPassDelay_hrs"
    BUSD = "stats_AvgBusPassDelay_s"

    out = os.path.splitext(path)[0] + "_aggregate.csv"
    cols = ["arm", "n_seeds", "obj_mean", "obj_pct_vs_no_tsp", "obj_wins",
            "obj_t_vs_no_tsp", "obj_p_vs_no_tsp", "throughput_mean",
            "throughput_pct", "total_delay_mean", "main_delay_mean",
            "bus_delay_per_pax_mean",
            # FAIR objective (distinct-pax based; not junction-crossing inflated)
            "fair_obj_mean", "fair_obj_pct_vs_no_tsp", "fair_obj_wins",
            "fair_t_vs_no_tsp", "fair_p_vs_no_tsp", "delay_per_pax_s_mean",
            "distinct_pax_mean", "loop_completions_mean"]
    arms = ["NO_TSP"] + [a for a in by if a != "NO_TSP"]
    agg = []
    print("\n--- INFLATED headline objective (PaxEquivPassages = junction-crossings) ---")
    print("%-38s %8s %8s %5s %7s %7s  %10s %8s" %
          ("arm", "obj", "%vNOTSP", "wins", "t", "p", "thru%", "busdel"))
    for arm in arms:
        d = by[arm]
        ss = [s for s in seeds if s in d]
        if not ss:
            continue
        ov = [_f(d[s], OBJ) for s in ss]
        bv = [_f(base[s], OBJ) for s in ss]
        obj_m = st.mean(ov)
        rel = 100.0 * (obj_m - st.mean(bv)) / st.mean(bv) if st.mean(bv) else 0.0
        wins = sum(1 for s in ss if _f(d[s], OBJ) > _f(base[s], OBJ))
        t, p = _paired_t(ov, bv) if arm != "NO_TSP" else (0.0, 1.0)
        thr_m = st.mean([_f(d[s], THR) for s in ss])
        thr_b = st.mean([_f(base[s], THR) for s in ss])
        thr_pct = 100.0 * (thr_m - thr_b) / thr_b if thr_b else 0.0
        # FAIR objective: distinct-pax / total delay (both ~trip-based, not crossings)
        fo = [(_fair_pax(d[s]) / _f(d[s], DEL)) if _f(d[s], DEL) else float("nan")
              for s in ss]
        fb = [(_fair_pax(base[s]) / _f(base[s], DEL)) if _f(base[s], DEL)
              else float("nan") for s in ss]
        fair_m = st.mean(fo)
        fair_rel = 100.0 * (fair_m - st.mean(fb)) / st.mean(fb) if st.mean(fb) else 0.0
        fair_wins = sum(1 for a, b in zip(fo, fb) if a > b)
        ft, fp = _paired_t(fo, fb) if arm != "NO_TSP" else (0.0, 1.0)
        dpx = [(_f(d[s], DEL) * 3600.0 / _fair_pax(d[s])) if _fair_pax(d[s])
               else float("nan") for s in ss]
        row = {
            "arm": arm, "n_seeds": len(ss),
            "obj_mean": round(obj_m, 3),
            "obj_pct_vs_no_tsp": round(rel, 2),
            "obj_wins": "%d/%d" % (wins, len(ss)),
            "obj_t_vs_no_tsp": round(t, 3), "obj_p_vs_no_tsp": round(p, 4),
            "throughput_mean": round(thr_m, 1),
            "throughput_pct": round(thr_pct, 2),
            "total_delay_mean": round(st.mean([_f(d[s], DEL) for s in ss]), 1),
            "main_delay_mean": round(st.mean([_f(d[s], MAIN) for s in ss]), 1),
            "bus_delay_per_pax_mean":
                round(st.mean([_f(d[s], BUSD) for s in ss]), 2),
            "fair_obj_mean": round(fair_m, 3),
            "fair_obj_pct_vs_no_tsp": round(fair_rel, 2),
            "fair_obj_wins": "%d/%d" % (fair_wins, len(ss)),
            "fair_t_vs_no_tsp": round(ft, 3), "fair_p_vs_no_tsp": round(fp, 4),
            "delay_per_pax_s_mean": round(st.mean(dpx), 2),
            "distinct_pax_mean": round(st.mean([_fair_pax(d[s]) for s in ss]), 0),
            "loop_completions_mean":
                round(st.mean([_f(d[s], "stats_N_LoopCompletions") for s in ss]), 0),
        }
        agg.append(row)
        print("%-38s %8.2f %+7.1f %5s %7.2f %7.4f  %+9.2f %8.2f" %
              (arm, obj_m, rel, row["obj_wins"], t, p, thr_pct,
               row["bus_delay_per_pax_mean"]))
    print("\n--- FAIR objective (distinct pax / total delay; throughput ~invariant) ---")
    print("%-38s %9s %8s %5s %7s %7s  %9s %9s" %
          ("arm", "fair_obj", "%vNOTSP", "wins", "t", "p",
           "del/pax_s", "totdel_h"))
    for row in agg:
        print("%-38s %9.3f %+7.1f %5s %7.2f %7.4f  %9.2f %9.1f" %
              (row["arm"], row["fair_obj_mean"], row["fair_obj_pct_vs_no_tsp"],
               row["fair_obj_wins"], row["fair_t_vs_no_tsp"],
               row["fair_p_vs_no_tsp"], row["delay_per_pax_s_mean"],
               row["total_delay_mean"]))
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(agg)
    print("\nwrote", out)
    print("(paired t vs NO_TSP, same seed; p<0.05 = significant.)")
    print("FAIR obj uses DISTINCT pax (cars*%.1f + buses*%.0f + trucks*%.1f), not the"
          % (CAR_OCC, BUS_OCC, TRUCK_OCC))
    print("junction-crossing PaxEquivPassages -- so it is not amplified by corridor")
    print("progression. Since throughput is ~invariant, trust fair_obj / del-per-pax.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bellman_harmony_overnight.csv")
