"""Flow-style result visualisations for the Aimsun corridor experiments.

Flow's own visualizer is SUMO/RLlib-bound; these plots reproduce the useful
diagnostic views from the experiment data we already collect:

    flow_style_objective.png       per-seed objective vs NO_TSP
    flow_style_delays.png          main/side passenger-delay decomposition
    flow_style_natural_green.png   natural-green fraction
    flow_style_bus_tt.png          bus travel time
    flow_style_time_space.png      Purdue time-space green band
    flow_style_link_pressure.png   master link pressure (if logged)
    flow_style_arrivals.png        composite arrival estimates (if logged)

Run outside Aimsun:
    python kg/flow_style_plots.py --csv paxwin_comprehensive_3seeds.csv
"""
import argparse
import csv
import glob
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _f(row, key):
    try:
        return float(row.get(key, "") or 0.0)
    except Exception:
        return 0.0


def _seed(row):
    for key in ("run_seed", "seed"):
        try:
            return int(float(row.get(key, 0) or 0))
        except Exception:
            pass
    return 0


def _load(csv_path):
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _group(rows, key):
    out = {}
    for r in rows:
        out.setdefault(str(r.get("run_experiment", "")), []).append((_seed(r), r))
    return out


def _bar_panel(ax, grouped, key, title, higher_better=False):
    arms = sorted(grouped)
    seeds = sorted({s for vals in grouped.values() for s, _ in vals})
    if not seeds:
        return
    w = 0.8 / max(len(arms), 1)
    for i, arm in enumerate(arms):
        vals = {s: _f(r, key) for s, r in grouped[arm]}
        xs = np.arange(len(seeds)) + (i - (len(arms) - 1) / 2.0) * w
        ys = [vals.get(s, np.nan) for s in seeds]
        ax.bar(xs, ys, width=w, label=arm[:28])
    base = grouped.get("NO_TSP")
    if base:
        bm = np.nanmean([_f(r, key) for _, r in base])
        ax.axhline(bm, color="#607d8b", ls="--", lw=1.2,
                   label="NO_TSP mean")
    ax.set_xticks(np.arange(len(seeds)))
    ax.set_xticklabels([str(s) for s in seeds])
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.25)


def _objective(rows, outdir):
    grouped = _group(rows, "obj")
    fig, ax = plt.subplots(figsize=(max(10, len(grouped) * 0.65), 5.2))
    _bar_panel(ax, grouped, "stats_Objective_PaxPerDelayHr",
               "Objective (lower is better)")
    ax.legend(fontsize=6, ncol=2, loc="upper right")
    fig.tight_layout()
    p = os.path.join(outdir, "flow_style_objective.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def _delays(rows, outdir):
    grouped = _group(rows, "delay")
    arms = sorted(grouped)
    fig, ax = plt.subplots(figsize=(max(10, len(arms) * 0.75), 5.0))
    xs = np.arange(len(arms))
    main = [np.mean([_f(r, "stats_MainPassDelay_hrs") for _, r in grouped[a]])
            for a in arms]
    side = [np.mean([_f(r, "stats_SidePassDelay_hrs") for _, r in grouped[a]])
            for a in arms]
    ax.bar(xs, main, color="#42a5f5", label="main")
    ax.bar(xs, side, bottom=main, color="#ef5350", label="side")
    ax.set_xticks(xs)
    ax.set_xticklabels([a[:26] for a in arms], rotation=55, ha="right")
    ax.set_ylabel("passenger-delay hours")
    ax.set_title("Main vs side passenger-delay decomposition")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    p = os.path.join(outdir, "flow_style_delays.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def _simple(rows, outdir, key, title, fname, ylabel):
    grouped = _group(rows, "x")
    fig, ax = plt.subplots(figsize=(max(10, len(grouped) * 0.65), 5.0))
    _bar_panel(ax, grouped, key, title)
    ax.set_ylabel(ylabel)
    ax.legend(fontsize=6, ncol=2, loc="upper right")
    fig.tight_layout()
    p = os.path.join(outdir, fname)
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def _time_space(csv_path, outdir):
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
        import plot_plan_evolution as ppe
    except Exception:
        return None
    logs = os.path.join(os.path.dirname(os.path.abspath(csv_path)), "kg", "logs")
    def newest(arm):
        fs = glob.glob(os.path.join(logs, "plan_evolution_%s_*.csv" % arm))
        return max(fs, key=os.path.getmtime) if fs else None
    before = newest("NO_TSP")
    if not before:
        return None
    rows = _load(csv_path)
    arms = sorted(_group(rows, "x"))
    arm = min(arms, key=lambda a: np.mean(
        [_f(r, "stats_Objective_PaxPerDelayHr") for _, r in _group(rows, "x")[a]]))
    after = newest(arm) or before
    out = os.path.join(outdir, "flow_style_time_space.png")
    try:
        return ppe.run_compare([before, after],
                               labels=["NO_TSP", arm[:28]],
                               out_path=out,
                               title="Time-space green band: NO_TSP vs %s" % arm[:36])
    except Exception:
        return None


def _log_rows(log_path):
    out = []
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            out.append(line.rstrip("\n"))
    return out


def _link_pressure(csv_path, outdir):
    logs = glob.glob(os.path.join(os.path.dirname(os.path.abspath(csv_path)),
                                  "kg", "logs", "Aimsun_TSP_Log_*.txt"))
    if not logs:
        return None
    lines = _log_rows(max(logs, key=os.path.getmtime))
    rows = []
    pat = re.compile(
        r"\[LINK PRESSURE\].*?from=(\d+)\s+to=(\d+).*?"
        r"q_up=([0-9.]+)\s+q_down=([0-9.]+).*?"
        r"p=([0-9.]+).*?delay=([0-9.]+)s")
    for line in lines:
        m = pat.search(line)
        if m:
            rows.append((int(m.group(1)), int(m.group(2)),
                         float(m.group(3)), float(m.group(4)),
                         float(m.group(5)), float(m.group(6))))
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(10, 4.8))
    labels = sorted({(a, b) for a, b, *_ in rows})
    for a, b in labels:
        sub = [r for r in rows if r[0] == a and r[1] == b]
        ax.plot(np.arange(len(sub)), [r[5] for r in sub],
                label="%s->%s" % (a, b), lw=1.4)
    ax.set_xlabel("master pressure sample")
    ax.set_ylabel("coordination delay (s)")
    ax.set_title("Master link pressure used in offsets")
    ax.legend(fontsize=6, ncol=2)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = os.path.join(outdir, "flow_style_link_pressure.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def _arrivals(csv_path, outdir):
    logs = glob.glob(os.path.join(os.path.dirname(os.path.abspath(csv_path)),
                                  "kg", "logs", "Aimsun_TSP_Log_*.txt"))
    if not logs:
        return None
    lines = _log_rows(max(logs, key=os.path.getmtime))
    rows = []
    pat = re.compile(r"\[ARRIVAL EST\] inter=(\d+) t=([0-9.]+) .*?arr=\{([^}]*)\}")
    for line in lines:
        m = pat.search(line)
        if not m:
            continue
        jid, t, arr = int(m.group(1)), float(m.group(2)), m.group(3)
        vals = {}
        for part in arr.split(","):
            if ":" not in part:
                continue
            k, v = part.split(":", 1)
            try:
                vals[int(k.strip())] = float(v.strip())
            except Exception:
                pass
        rows.append((jid, t, vals))
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(10, 4.8))
    for jid in sorted({r[0] for r in rows}):
        sub = [r for r in rows if r[0] == jid]
        tot = [sum(r[2].values()) for r in sub]
        ax.plot([r[1] for r in sub], tot, marker=".", lw=1.1, label=str(jid))
    ax.set_xlabel("simulation time (s)")
    ax.set_ylabel("estimated arrivals (veh/h)")
    ax.set_title("Composite arrival-rate estimates by junction")
    ax.legend(fontsize=6, ncol=2)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = os.path.join(outdir, "flow_style_arrivals.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="paxwin_comprehensive_3seeds.csv")
    ap.add_argument("--outdir", default="kg/flow_style")
    args = ap.parse_args()
    if not os.path.isfile(args.csv):
        raise SystemExit("CSV not found: %s" % args.csv)
    os.makedirs(args.outdir, exist_ok=True)
    rows = _load(args.csv)
    made = [
        _objective(rows, args.outdir),
        _delays(rows, args.outdir),
        _simple(rows, args.outdir, "stats_TSP_NaturalGreen",
                "Natural-green fraction", "flow_style_natural_green.png", "%"),
        _simple(rows, args.outdir, "stats_AvgBusTT_s",
                "Bus travel time", "flow_style_bus_tt.png", "s"),
        _time_space(args.csv, args.outdir),
        _link_pressure(args.csv, args.outdir),
        _arrivals(args.csv, args.outdir),
    ]
    for p in made:
        if p:
            print("wrote", p)


if __name__ == "__main__":
    main()
