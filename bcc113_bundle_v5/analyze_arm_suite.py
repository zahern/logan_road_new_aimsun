"""analyze_arm_suite.py -- post-run analysis for the arm suite (run LOCALLY).

Reads the suite output CSV plus the per-run engine logs in <corridor>/logs/ and
produces, for every arm:

  1. arm_suite_bars.png              objective / THROUGHPUT / density / delay bars,
                                     each bar value SPELLED OUT (+ %% vs NO_TSP).
  2. arm_suite_cycle_time.csv/.png   per-arm, per-junction cycle length
                                     (init vs final) from plan_evolution_*.csv.
  3. arm_suite_density_per_intersection.csv / _heatmap.png
                                     per-arm, per-junction mean density + queue +
                                     delay from queue_snapshot_*.csv.

It does NOT touch the simulator, so it is safe to run on Windows at any time
(RULE 1: local python only). Usage:

    python analyze_arm_suite.py
    python analyze_arm_suite.py --out paxwin_arm_suite_5seeds.csv --corridor kg
    python analyze_arm_suite.py --arms CHAMP_ADAPTIVE_AIMSUN_DSW,CHAMP_ADAPTIVE_DSW_THRU_OPEN

By default it discovers arms from the summary CSV. For the per-junction logs it
uses, per arm, the most recent N files (N = number of seeds in the summary),
since the engine writes one plan_evolution / queue_snapshot file per run.
"""
import argparse
import csv
import glob
import os
import statistics as st
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


def _f(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        return list(csv.DictReader(fh))


# ── 1. summary bars (objective / throughput / density / delay) ───────────────
def summary_bars(out_csv, seeds):
    rows = _read_csv(out_csv)
    by = defaultdict(list)
    for r in rows:
        by[str(r.get("run_experiment", ""))].append(r)
    seedset = set(seeds)

    def vals(arm, key):
        out = []
        for r in by.get(arm, []):
            try:
                if int(float(r.get("run_seed"))) in seedset:
                    out.append(_f(r.get(key)))
            except Exception:
                continue
        return out

    arms = ["NO_TSP"] + [a for a in by if a != "NO_TSP"]
    arms = [a for a in arms if vals(a, "stats_Objective_PaxPerDelayHr")]
    if not arms:
        print("  no arms in", out_csv)
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print("  matplotlib missing, bars skipped:", e)
        return

    short = [a.replace("CHAMP_ADAPTIVE_", "") for a in arms]
    panels = [
        ("stats_Objective_PaxPerDelayHr", "Objective", "pax / delay-hr", True, "%.1f"),
        ("stats_PaxEquivPassages", "Throughput (pax pushed through)",
         "passenger passages", True, "%.0f"),
        ("stats_Net_AvgDensity_vkm", "Network density", "veh/km", False, "%.1f"),
        ("stats_TotalPassDelay_hrs", "Total passenger delay", "delay-hr", False, "%.0f"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(max(10, len(arms) * 1.6), 9))
    for ax, (col, title, ylab, hib, fmt) in zip(axes.ravel(), panels):
        means = [st.mean(vals(a, col)) if vals(a, col) else 0.0 for a in arms]
        base = means[0] if means else 0.0
        cols = []
        for a, m in zip(arms, means):
            if a == "NO_TSP":
                cols.append("#90a4ae")
            elif base and ((m > base) == hib):
                cols.append("#2e7d32")
            else:
                cols.append("#c62828")
        bars = ax.bar(range(len(arms)), means, color=cols)
        if base:
            ax.axhline(base, color="#607d8b", ls="--", lw=1)
        for i, (b, m) in enumerate(zip(bars, means)):
            lbl = fmt % m
            if base and arms[i] != "NO_TSP":
                lbl += "\n(%+.1f%%)" % (100.0 * (m - base) / base)
            ax.annotate(lbl, (b.get_x() + b.get_width() / 2, m), ha="center",
                        va="bottom", fontsize=7, xytext=(0, 2),
                        textcoords="offset points")
        ax.set_xticks(range(len(arms)))
        ax.set_xticklabels(short, rotation=30, ha="right", fontsize=7)
        ax.set_ylabel(ylab, fontsize=8)
        ax.set_title("%s  (%s)" % (title, "higher=better" if hib else "lower=better"),
                     fontsize=9)
        ax.grid(axis="y", alpha=0.3)
        ax.margins(y=0.15)
    fig.suptitle("Arm suite vs NO_TSP -- %d seeds (dashed = NO_TSP)" % len(seeds),
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    png = os.path.join(HERE, "arm_suite_bars.png")
    fig.savefig(png, dpi=150)
    print("  wrote", png)
    return arms


def _latest_files(logdir, prefix, arm, n):
    """Most-recent n files matching <logdir>/<prefix>_<arm>_*.csv."""
    pat = os.path.join(logdir, "%s_%s_*.csv" % (prefix, arm))
    fs = sorted(glob.glob(pat), key=os.path.getmtime, reverse=True)
    return fs[:max(1, n)]


# ── 2. cycle-time comparison (plan_evolution_*.csv) ──────────────────────────
def cycle_time(logdir, arms, n_seeds):
    out = []          # (arm, junction, route_pos, init_cycle, final_cycle)
    per_arm_final = defaultdict(list)
    for arm in arms:
        if arm == "NO_TSP":
            continue
        files = _latest_files(logdir, "plan_evolution", arm, n_seeds)
        # junction -> (init, final) averaged over the runs; cycle is per-junction
        jc = defaultdict(lambda: {"init": [], "final": [], "pos": None, "grp": None})
        for fp in files:
            for r in _read_csv(fp):
                j = str(r.get("junction_id", ""))
                if not j:
                    continue
                jc[j]["init"].append(_f(r.get("init_cycle_s")))
                jc[j]["final"].append(_f(r.get("final_cycle_s")))
                jc[j]["pos"] = _f(r.get("route_pos"))
                jc[j]["grp"] = r.get("corridor_group", "")
        for j, d in jc.items():
            ic = st.mean(d["init"]) if d["init"] else 0.0
            fc = st.mean(d["final"]) if d["final"] else 0.0
            out.append({"arm": arm, "junction": j, "corridor_group": d["grp"],
                        "route_pos": d["pos"], "init_cycle_s": round(ic, 1),
                        "final_cycle_s": round(fc, 1),
                        "delta_cycle_s": round(fc - ic, 1)})
            per_arm_final[arm].append(fc)
    if not out:
        print("  no plan_evolution logs found -- cycle-time skipped")
        return
    out.sort(key=lambda r: (r["arm"], r["route_pos"] or 0.0))
    cpath = os.path.join(HERE, "arm_suite_cycle_time.csv")
    with open(cpath, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print("  wrote", cpath, "(%d rows)" % len(out))

    # per-arm mean final cycle bar with value labels
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        arms2 = [a for a in per_arm_final]
        means = [st.mean(per_arm_final[a]) for a in arms2]
        fig, ax = plt.subplots(figsize=(max(7, len(arms2) * 1.4), 4.6))
        bars = ax.bar(range(len(arms2)), means, color="#5e35b1")
        for b, m in zip(bars, means):
            ax.annotate("%.0fs" % m, (b.get_x() + b.get_width() / 2, m),
                        ha="center", va="bottom", fontsize=8, xytext=(0, 2),
                        textcoords="offset points")
        ax.set_xticks(range(len(arms2)))
        ax.set_xticklabels([a.replace("CHAMP_ADAPTIVE_", "") for a in arms2],
                           rotation=30, ha="right", fontsize=7)
        ax.set_ylabel("mean final cycle length (s)")
        ax.set_title("Mean adapted cycle length per arm")
        ax.grid(axis="y", alpha=0.3)
        ax.margins(y=0.15)
        fig.tight_layout()
        png = os.path.join(HERE, "arm_suite_cycle_time.png")
        fig.savefig(png, dpi=150)
        print("  wrote", png)
    except Exception as e:
        print("  cycle-time plot skipped:", repr(e))


# ── 3. per-intersection density (queue_snapshot_*.csv) ───────────────────────
def density_per_intersection(logdir, arms, n_seeds):
    # arm -> junction -> lists
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    all_j = set()
    for arm in arms:
        files = _latest_files(logdir, "queue_snapshot", arm, n_seeds)
        for fp in files:
            for r in _read_csv(fp):
                j = str(r.get("junction_id", ""))
                if not j:
                    continue
                all_j.add(j)
                data[arm][j]["density"].append(_f(r.get("sw_density_main")))
                data[arm][j]["q_main"].append(_f(r.get("queue_main")))
                data[arm][j]["q_side"].append(_f(r.get("queue_side")))
                data[arm][j]["delay"].append(_f(r.get("delay_total_s")))
    if not data:
        print("  no queue_snapshot logs found -- density skipped")
        return
    rows = []
    for arm in data:
        for j in data[arm]:
            d = data[arm][j]
            rows.append({
                "arm": arm, "junction": j,
                "mean_density_vkm": round(st.mean(d["density"]) if d["density"] else 0.0, 2),
                "mean_queue_main_veh": round(st.mean(d["q_main"]) if d["q_main"] else 0.0, 1),
                "mean_queue_side_veh": round(st.mean(d["q_side"]) if d["q_side"] else 0.0, 1),
                "mean_delay_total_s": round(st.mean(d["delay"]) if d["delay"] else 0.0, 1),
            })
    rows.sort(key=lambda r: (r["arm"], r["junction"]))
    dpath = os.path.join(HERE, "arm_suite_density_per_intersection.csv")
    with open(dpath, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("  wrote", dpath, "(%d rows)" % len(rows))

    # heatmap arm x junction of mean density
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        arms2 = sorted(data.keys())
        js = sorted(all_j, key=lambda x: int(x) if x.isdigit() else 0)
        M = np.full((len(arms2), len(js)), np.nan)
        for ai, arm in enumerate(arms2):
            for ji, j in enumerate(js):
                d = data[arm].get(j, {}).get("density", [])
                if d:
                    M[ai, ji] = st.mean(d)
        fig, ax = plt.subplots(figsize=(max(8, len(js) * 0.7),
                                        max(3.5, len(arms2) * 0.6)))
        im = ax.imshow(M, aspect="auto", cmap="YlOrRd")
        ax.set_xticks(range(len(js)))
        ax.set_xticklabels(js, rotation=90, fontsize=7)
        ax.set_yticks(range(len(arms2)))
        ax.set_yticklabels([a.replace("CHAMP_ADAPTIVE_", "") for a in arms2], fontsize=7)
        for ai in range(len(arms2)):
            for ji in range(len(js)):
                if not np.isnan(M[ai, ji]):
                    ax.text(ji, ai, "%.0f" % M[ai, ji], ha="center", va="center",
                            fontsize=6, color="#222")
        ax.set_title("Mean main density (veh/km) per intersection")
        fig.colorbar(im, ax=ax, label="veh/km")
        fig.tight_layout()
        png = os.path.join(HERE, "arm_suite_density_heatmap.png")
        fig.savefig(png, dpi=150)
        print("  wrote", png)
    except Exception as e:
        print("  density heatmap skipped:", repr(e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="paxwin_arm_suite_5seeds.csv")
    ap.add_argument("--corridor", default="kg")
    ap.add_argument("--arms", default="")
    args = ap.parse_args()

    out_csv = args.out if os.path.isabs(args.out) else os.path.join(HERE, args.out)
    logdir = os.path.join(HERE, args.corridor, "logs")
    if not os.path.isfile(out_csv):
        raise SystemExit("summary CSV not found: %s" % out_csv)

    rows = _read_csv(out_csv)
    seeds = sorted({int(float(r["run_seed"])) for r in rows
                    if str(r.get("run_seed", "")).strip()})
    print("seeds:", seeds, "| logdir:", logdir)

    print("[1] summary bars")
    arms = summary_bars(out_csv, seeds) or []
    if args.arms:
        arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    print("[2] cycle-time comparison")
    cycle_time(logdir, arms, len(seeds) or 1)
    print("[3] per-intersection density")
    density_per_intersection(logdir, arms, len(seeds) or 1)
    print("DONE")


if __name__ == "__main__":
    main()
