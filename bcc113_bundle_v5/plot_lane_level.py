"""Plot lane-level diagnostics from an Aimsun vehicle_tracks CSV.

Reads the ``vehicle_tracks_*.csv`` produced by ``shared_tsp_engine.engine``
(1 Hz snapshot of every vehicle on a managed approach) and writes:

    lane_occupancy_<run>.png   vehicles per section/lane over time
    lane_speed_<run>.png       mean speed per section/lane
    lane_queue_<run>.png       stopped vehicles per section/lane
    junction_turns_<run>.png   top turning movements (or one junction heatmap)
    junction_turns_<run>.csv   turning-movement counts
    trajectories_<run>.png     x/y trajectories, buses highlighted

Usage
-----
    python plot_lane_level.py
    python plot_lane_level.py --csv kg/logs/vehicle_tracks_....csv
    python plot_lane_level.py --csv ... --junction 21847
    python plot_lane_level.py --csv ... --section 2890 --time-bin 5
"""
import argparse
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


def _latest_csv():
    pats = [
        os.path.join(HERE, "kg", "logs", "vehicle_tracks_*.csv"),
        os.path.join(HERE, "logan_road_new", "logs", "vehicle_tracks_*.csv"),
    ]
    files = []
    for p in pats:
        files.extend(glob.glob(p))
    return max(files, key=os.path.getmtime) if files else None


def _load(path):
    d = pd.read_csv(path)
    need = {"sim_time_s", "veh_id", "section", "lane", "speed_kmh"}
    missing = need - set(d.columns)
    if missing:
        raise SystemExit("missing columns: %s" % ", ".join(sorted(missing)))
    for c in d.columns:
        if c in ("sim_time_s", "veh_id", "section", "segment", "lane",
                 "section_jct", "junction", "type", "line",
                 "from_section", "from_lane", "to_section", "to_lane"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["sim_time_s", "section", "lane"])
    d["section"] = d["section"].astype(int)
    d["lane"] = d["lane"].astype(int)
    d["veh_id"] = d["veh_id"].astype(int)
    d["is_bus"] = d.get("line", pd.Series(-1, index=d.index)).fillna(-1) > 0
    d["stopped"] = d["speed_kmh"].fillna(0.0) < 5.0
    return d


def _heat(ax, piv, title, cbar, cmap="viridis"):
    vals = piv.values.astype(float)
    im = ax.imshow(vals, aspect="auto", origin="lower",
                   interpolation="nearest", cmap=cmap)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.set_yticks(range(len(piv.index)))
    ax.set_yticklabels(["%s/%s" % (s, l) for s, l in piv.index], fontsize=6)
    cols = list(piv.columns)
    if len(cols) > 7:
        idx = np.linspace(0, len(cols) - 1, 7).astype(int)
        ax.set_xticks(idx)
        ax.set_xticklabels([str(int(cols[i])) for i in idx], fontsize=7)
    else:
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels([str(int(c)) for c in cols], fontsize=7)
    ax.set_xlabel("simulation time (s)", fontsize=8)
    ax.set_ylabel("section / lane", fontsize=8)
    fig = ax.figure
    fig.colorbar(im, ax=ax, label=cbar, fraction=0.035)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--junction", type=int, default=None)
    ap.add_argument("--section", type=int, default=None)
    ap.add_argument("--time-bin", type=float, default=5.0)
    ap.add_argument("--top-n", type=int, default=30)
    ap.add_argument("--max-samples", type=int, default=200000)
    args = ap.parse_args()

    csv = args.csv or _latest_csv()
    if not csv or not os.path.isfile(csv):
        raise SystemExit("no vehicle_tracks CSV found; pass --csv")
    run = os.path.splitext(os.path.basename(csv))[0]
    out = args.out_dir or os.path.join(HERE, "lane_level", run)
    os.makedirs(out, exist_ok=True)
    d = _load(csv)
    if args.section:
        d = d[d["section"] == args.section]
    if args.junction and "section_jct" in d.columns:
        d = d[d["section_jct"] == args.junction]
    if d.empty:
        raise SystemExit("no vehicle rows after filtering")

    tb = max(1.0, float(args.time_bin))
    d["tbin"] = (d["sim_time_s"] // tb) * tb

    # ---- lane occupancy / speed / stopped queue -----------------------------
    counts = (d.groupby(["section", "lane", "tbin"])
              .size().reset_index(name="veh"))
    rank = counts.groupby(["section", "lane"])["veh"].sum().nlargest(
        max(args.top_n, 1)).index
    occ = (counts.set_index(["section", "lane", "tbin"])["veh"]
           .unstack("tbin").reindex(rank).fillna(0.0))
    fig, ax = plt.subplots(figsize=(max(9, 0.22 * len(occ.columns)), 6))
    _heat(ax, occ, "Lane occupancy — vehicles per section/lane",
          "vehicles in bin")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "lane_occupancy_%s.png" % run), dpi=180)
    plt.close(fig)

    spd = (d.groupby(["section", "lane", "tbin"])["speed_kmh"]
           .mean().reset_index())
    spd_p = (spd.set_index(["section", "lane", "tbin"])["speed_kmh"]
             .unstack("tbin").reindex(rank))
    fig, ax = plt.subplots(figsize=(max(9, 0.22 * len(spd_p.columns)), 6))
    _heat(ax, spd_p, "Mean lane speed — km/h", "km/h", cmap="magma")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "lane_speed_%s.png" % run), dpi=180)
    plt.close(fig)

    q = (d[d["stopped"]].groupby(["section", "lane", "tbin"])
         .size().reset_index(name="stopped"))
    q_p = (q.set_index(["section", "lane", "tbin"])["stopped"]
           .unstack("tbin").reindex(rank).fillna(0.0))
    fig, ax = plt.subplots(figsize=(max(9, 0.22 * len(q_p.columns)), 6))
    _heat(ax, q_p, "Stopped vehicles (<5 km/h) per lane",
          "stopped vehicles", cmap="inferno")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "lane_queue_%s.png" % run), dpi=180)
    plt.close(fig)

    # ---- turning movements from section-to-section transitions --------------
    if "section_jct" in d.columns:
        t = d.sort_values(["veh_id", "sim_time_s"]).copy()
        g = t.groupby("veh_id", sort=False)
        t["prev_section"] = g["section"].shift()
        t["prev_lane"] = g["lane"].shift()
        t["prev_jct"] = g["section_jct"].shift()
        moves = t[
            (t["prev_jct"] > 0)
            & (t["prev_jct"] == t["section_jct"])
            & (t["prev_section"] != t["section"])
            & (t["prev_lane"] > 0) & (t["lane"] > 0)
        ]
        if args.junction:
            moves = moves[moves["section_jct"] == args.junction]
        turn = (moves.groupby(["section_jct", "prev_lane", "lane"])
                .size().reset_index(name="count"))
        turn.to_csv(os.path.join(out, "junction_turns_%s.csv" % run),
                    index=False)
        if not turn.empty:
            if args.junction:
                p = (turn.pivot(index="prev_lane", columns="lane",
                                values="count").fillna(0.0))
                fig, ax = plt.subplots(figsize=(6.5, 5.5))
                _heat(ax, p, "Junction %d turning movements" % args.junction,
                      "vehicles", cmap="Blues")
                ax.set_xlabel("to lane", fontsize=8)
                ax.set_ylabel("from lane", fontsize=8)
                fig.tight_layout()
                fig.savefig(os.path.join(
                    out, "junction_turns_%s_%d.png" % (run, args.junction)),
                    dpi=180)
                plt.close(fig)
            else:
                top = turn.sort_values("count", ascending=False).head(30)
                labels = ["%s: %s->%s" % (int(r.section_jct),
                                          int(r.prev_lane), int(r.lane))
                          for r in top.itertuples()]
                fig, ax = plt.subplots(figsize=(10, max(4, 0.28 * len(top))))
                ax.barh(range(len(top)), top["count"].values, color="#2563eb")
                ax.set_yticks(range(len(top)))
                ax.set_yticklabels(labels, fontsize=7)
                ax.invert_yaxis()
                ax.set_xlabel("vehicles")
                ax.set_title("Top turning movements by from/to lane",
                             fontsize=10, fontweight="bold")
                ax.grid(axis="x", alpha=0.25)
                fig.tight_layout()
                fig.savefig(os.path.join(out, "junction_turns_%s.png" % run),
                            dpi=180)
                plt.close(fig)

    # ---- x/y trajectories ----------------------------------------------------
    tr = d[(d["x"].fillna(0) != 0) | (d["y"].fillna(0) != 0)]
    if len(tr) > args.max_samples:
        tr = tr.sample(args.max_samples, random_state=1)
    fig, ax = plt.subplots(figsize=(8, 7))
    car = tr[~tr["is_bus"]]
    bus = tr[tr["is_bus"]]
    if len(car):
        ax.scatter(car["x"], car["y"], s=1.0, c="#2563eb", alpha=0.18,
                   linewidths=0, label="car/other")
    if len(bus):
        ax.scatter(bus["x"], bus["y"], s=3.0, c="#c82020", alpha=0.75,
                   linewidths=0, label="bus / PT")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("Aimsun x")
    ax.set_ylabel("Aimsun y")
    ax.set_title("Vehicle trajectories", fontsize=10, fontweight="bold")
    ax.legend(markerscale=4, fontsize=8)
    ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "trajectories_%s.png" % run), dpi=180)
    plt.close(fig)

    print("run      : %s" % run)
    print("rows     : %d" % len(d))
    print("sections : %d  lanes: %d" % (d["section"].nunique(),
                                        d["lane"].nunique()))
    print("output   : %s" % out)


if __name__ == "__main__":
    main()
