r"""analyze_stability.py -- replicate the paper's network-stability comparison.

Reproduces Fig. 8/9 of Qin & Zhang (CBQL-TSP, arXiv:2404.19683): the number of
waiting vehicles in the network as a function of simulation time, TSP vs
NO_TSP. A corridor is "stable" (eq. 23) when that count converges to a bounded
constant instead of growing without limit; the paper's finding is that TSP adds
only a small, bounded number of waiting cars over NO_TSP.

DATA SOURCE (no re-run needed): each result folder already writes
`section_timeseries.csv` with per-interval rows (t_start_s, SectionID,
IsMain, queue_veh, n_veh, ...). Summing `queue_veh` over all sections at each
t_start_s gives the network waiting-vehicle series. Buses are a ~1-2% share of
flow, so this total is dominated by private cars (the paper's y-axis).

CORRIDOR-AGNOSTIC: pass --corridor kg (default) or logan_road_new; the tool
reads <corridor>/results and pairs NO_TSP with each TSP arm at the same seed.

USAGE (local Windows python -- analysis only, never on the cluster):
    python analyze_stability.py                      # kg, all arms/seeds found
    python analyze_stability.py --corridor logan_road_new
    python analyze_stability.py --arms CHAMP_GATED_CHAMP,CHAMP_GATED_DELAYONLY
    python analyze_stability.py --seeds 400,500 --tail 300

Outputs (written to <corridor>/results/stability/):
    stability_<corridor>_seed<seed>.png   per-seed TSP-vs-NO_TSP time series
    stability_<corridor>_mean.png         seed-averaged comparison
    stability_summary_<corridor>.csv      tail-mean / peak / slope / vs-NO_TSP
"""
import argparse
import csv
import glob
import math
import os
import re
import sys

csv.field_size_limit(10 ** 7)

_HERE = os.path.dirname(os.path.abspath(__file__))
_FOLDER_RE = re.compile(r"^(?P<arm>.+?)_seed(?P<seed>\d+)_")


def _discover(results_dir):
    """Map (arm, seed) -> newest folder holding a section_timeseries.csv."""
    found = {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*", "section_timeseries.csv"))):
        folder = os.path.basename(os.path.dirname(path))
        m = _FOLDER_RE.match(folder)
        if not m:
            continue
        key = (m.group("arm"), int(m.group("seed")))
        # newest wins (folders carry a trailing _YYYYMMDD_HHMMSS timestamp)
        if key not in found or path > found[key]:
            found[key] = path
    return found


def _series(ts_csv):
    """Return sorted [(t_mid_s, total_queue_veh, main_queue, side_queue)] ."""
    agg = {}  # t_start -> [tot, main, side, t_end]
    with open(ts_csv, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                t0 = float(row["t_start_s"])
                q = float(row.get("queue_veh") or 0.0)
            except (TypeError, ValueError):
                continue
            is_main = str(row.get("IsMain", "")).strip() in ("1", "1.0", "True", "true")
            slot = agg.setdefault(t0, [0.0, 0.0, 0.0, t0])
            slot[0] += q
            if is_main:
                slot[1] += q
            else:
                slot[2] += q
            try:
                slot[3] = max(slot[3], float(row["t_end_s"]))
            except (TypeError, ValueError, KeyError):
                pass
    out = []
    for t0 in sorted(agg):
        tot, mn, sd, t1 = agg[t0]
        out.append((0.5 * (t0 + t1), tot, mn, sd))
    return out


def _tail_stats(series, tail_s):
    """Tail-window mean, peak, final, and linear slope (veh per 1000 s)."""
    if not series:
        return dict(tail_mean=0.0, peak=0.0, final=0.0, slope_per_ks=0.0)
    t_last = series[-1][0]
    tail = [(t, v) for (t, v, _m, _s) in series if t >= t_last - tail_s] or \
           [(series[-1][0], series[-1][1])]
    ys = [v for _t, v in tail]
    tail_mean = sum(ys) / len(ys)
    peak = max(v for _t, v, _m, _s in series)
    final = series[-1][1]
    # least-squares slope over the tail (boundedness: ~0 => stable)
    n = len(tail)
    if n >= 2:
        mx = sum(t for t, _ in tail) / n
        my = sum(v for _, v in tail) / n
        num = sum((t - mx) * (v - my) for t, v in tail)
        den = sum((t - mx) ** 2 for t, _ in tail) or 1.0
        slope_per_ks = (num / den) * 1000.0
    else:
        slope_per_ks = 0.0
    return dict(tail_mean=tail_mean, peak=peak, final=final, slope_per_ks=slope_per_ks)


def main():
    ap = argparse.ArgumentParser(description="Network-stability comparison (Fig. 9).")
    ap.add_argument("--corridor", default="kg", help="kg (default) or logan_road_new")
    ap.add_argument("--arms", default="", help="comma list of TSP arms; default = all found")
    ap.add_argument("--seeds", default="", help="comma list of seeds; default = all found")
    ap.add_argument("--baseline", default="NO_TSP", help="baseline arm name (default NO_TSP)")
    ap.add_argument("--tail", type=float, default=300.0, help="tail window (s) for stability stats")
    ap.add_argument("--smooth", type=float, default=90.0,
                    help="plot smoothing window (s); 0 disables. Stats use raw data.")
    args = ap.parse_args()

    def _smooth(xs, ys):
        """Centered moving average over ~args.smooth seconds (plot only)."""
        if args.smooth <= 0 or len(xs) < 3:
            return xs, ys
        dt = (xs[-1] - xs[0]) / max(len(xs) - 1, 1) or 0.5
        win = max(1, int(round(args.smooth / dt)))
        if win <= 1:
            return xs, ys
        out = []
        half = win // 2
        for i in range(len(ys)):
            lo, hi = max(0, i - half), min(len(ys), i + half + 1)
            out.append(sum(ys[lo:hi]) / (hi - lo))
        return xs, out

    results_dir = os.path.join(_HERE, args.corridor, "results")
    if not os.path.isdir(results_dir):
        sys.exit("no results dir: %s" % results_dir)
    out_dir = os.path.join(results_dir, "stability")
    os.makedirs(out_dir, exist_ok=True)

    found = _discover(results_dir)
    if not found:
        sys.exit("no section_timeseries.csv found under %s" % results_dir)

    want_arms = [a for a in args.arms.split(",") if a] or \
        sorted({a for (a, _s) in found} - {args.baseline})
    want_seeds = [int(s) for s in args.seeds.split(",") if s] or \
        sorted({s for (_a, s) in found})

    print("corridor=%s  baseline=%s" % (args.corridor, args.baseline))
    print("arms:", want_arms)
    print("seeds:", want_seeds)

    # load every needed series once
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cache = {}

    def get(arm, seed):
        key = (arm, seed)
        if key not in cache:
            p = found.get(key)
            cache[key] = _series(p) if p else None
        return cache[key]

    summary_rows = []
    # per-seed plots
    for seed in want_seeds:
        base = get(args.baseline, seed)
        plt.figure(figsize=(8, 4.5))
        plotted = False
        if base:
            xs = [t for t, _v, _m, _s in base]
            ys = [v for _t, v, _m, _s in base]
            plt.plot(*_smooth(xs, ys), label=args.baseline, color="#2b2b2b", lw=1.6)
            st = _tail_stats(base, args.tail)
            summary_rows.append((args.corridor, args.baseline, seed, st, 0.0))
            plotted = True
        for arm in want_arms:
            s = get(arm, seed)
            if not s:
                continue
            xs = [t for t, _v, _m, _s in s]
            ys = [v for _t, v, _m, _s in s]
            plt.plot(*_smooth(xs, ys), label=arm, lw=1.3)
            st = _tail_stats(s, args.tail)
            delta = st["tail_mean"] - (_tail_stats(base, args.tail)["tail_mean"] if base else 0.0)
            summary_rows.append((args.corridor, arm, seed, st, delta))
            plotted = True
        if not plotted:
            plt.close()
            continue
        plt.xlabel("simulation time (s)")
        plt.ylabel("waiting vehicles in network (sum queue_veh)")
        plt.title("Network stability -- %s seed %d (Fig. 9 style)" % (args.corridor, seed))
        plt.legend(fontsize=8)
        plt.grid(True, alpha=0.3)
        png = os.path.join(out_dir, "stability_%s_seed%d.png" % (args.corridor, seed))
        plt.tight_layout()
        plt.savefig(png, dpi=130)
        plt.close()
        print("wrote", png)

    # seed-averaged plot (resample each series onto a common grid)
    def mean_series(arm):
        all_s = [get(arm, sd) for sd in want_seeds if get(arm, sd)]
        if not all_s:
            return None
        t_max = min(s[-1][0] for s in all_s)
        grid = [t for t in range(0, int(t_max) + 1, 30)]
        avg = []
        for t in grid:
            vals = []
            for s in all_s:
                # nearest-earlier sample
                v = None
                for (ts, q, _m, _sd) in s:
                    if ts <= t:
                        v = q
                    else:
                        break
                if v is not None:
                    vals.append(v)
            if vals:
                avg.append((t, sum(vals) / len(vals)))
        return avg

    plt.figure(figsize=(8, 4.5))
    base_avg = mean_series(args.baseline)
    if base_avg:
        plt.plot(*_smooth([t for t, _ in base_avg], [v for _, v in base_avg]),
                 label=args.baseline, color="#2b2b2b", lw=1.8)
    for arm in want_arms:
        a = mean_series(arm)
        if a:
            plt.plot(*_smooth([t for t, _ in a], [v for _, v in a]), label=arm, lw=1.4)
    plt.xlabel("simulation time (s)")
    plt.ylabel("waiting vehicles in network (sum queue_veh)")
    plt.title("Network stability -- %s, seed-averaged (Fig. 9 style)" % args.corridor)
    plt.legend(fontsize=8)
    plt.grid(True, alpha=0.3)
    mean_png = os.path.join(out_dir, "stability_%s_mean.png" % args.corridor)
    plt.tight_layout()
    plt.savefig(mean_png, dpi=130)
    plt.close()
    print("wrote", mean_png)

    # summary CSV
    sum_csv = os.path.join(out_dir, "stability_summary_%s.csv" % args.corridor)
    with open(sum_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["corridor", "arm", "seed", "tail_mean_waiting_veh",
                    "peak_waiting_veh", "final_waiting_veh",
                    "tail_slope_veh_per_1000s", "delta_tailmean_vs_baseline",
                    "bounded_stable"])
        for corr, arm, seed, st, delta in summary_rows:
            # unbounded == sustained GROWTH; a negative/flat tail slope (queues
            # subsiding as the peak passes) is stable, not unbounded.
            bounded = st["slope_per_ks"] < 15.0  # <15 veh growth / 1000s => stable
            w.writerow([corr, arm, seed, round(st["tail_mean"], 1),
                        round(st["peak"], 1), round(st["final"], 1),
                        round(st["slope_per_ks"], 2), round(delta, 1),
                        "yes" if bounded else "NO"])
    print("wrote", sum_csv)
    print("\nStability summary (tail mean waiting veh, delta vs %s, slope/1000s):"
          % args.baseline)
    for corr, arm, seed, st, delta in summary_rows:
        print("  %-26s seed=%d  tail=%7.1f  dvs_base=%+7.1f  slope=%+7.2f  %s"
              % (arm, seed, st["tail_mean"], delta, st["slope_per_ks"],
                 "stable" if st["slope_per_ks"] < 15.0 else "UNBOUNDED?"))


if __name__ == "__main__":
    main()
