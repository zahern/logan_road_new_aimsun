"""plot_true_states.py -- Aimsun true-state density/speed matrices + heatmaps.

Reads a run's ``section_timeseries.csv`` (the true per-section q/k/v stream
written by ``kg/Simulation_Stats.py``) and writes the same kind of artefacts
as the AIMSUN_with_AVs ``Simulation/true_states`` folder:

    truestate_<run>_density.txt / .png
    truestate_<run>_speed.txt   / .png
    truestate_<run>_flow.txt
    truestate_<run>_queue.txt

The matrix is (time x section), with the section IDs in the header row; the
PNG is a section x time heatmap (sections ordered by junction, main first).

Notes
-----
* The Aimsun dump cadence is 30 s by default; set
  ``STATS_SECTION_INTERVAL_S=5`` before the run for a 5 s true-state matrix
  (the repo's grid is 5 s x 179 m). Aimsun exposes per-section states, not
  179 m cells, so the spatial unit here is the Aimsun section (lengths vary);
  each section is one column.
* ``src=AKIEST`` rows are independently measured; ``IMPOSED`` rows are the
  simulator snapshot fallback. The script defaults to ``any`` so the space-time
  grid is complete; use ``--src AKIEST`` for measured-only.

Usage
-----
    python plot_true_states.py
    python plot_true_states.py --csv kg/results/NO_TSP_seed700_.../section_timeseries.csv
    python plot_true_states.py --out-dir true_states_kg
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))


def _latest_csv():
    fs = glob.glob(os.path.join(HERE, "kg", "results", "*",
                                "section_timeseries.csv"))
    if not fs:
        return None
    return max(fs, key=os.path.getmtime)


def _matrix(d, time_col, secs, value):
    try:
        p = d.pivot_table(index=time_col, columns="SectionID",
                          values=value, aggfunc="mean")
        p = p.reindex(columns=secs).sort_index()
        return p
    except Exception:
        return pd.DataFrame(index=sorted(d[time_col].dropna().unique()),
                            columns=secs, dtype=float)


def _write_matrix(path, p, label):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("time_s," + ",".join(str(int(s)) for s in p.columns) + "\n")
        for t, row in p.iterrows():
            vals = []
            for v in row.values:
                vals.append("" if pd.isna(v) else ("%.4f" % float(v)))
            fh.write("%.1f," % float(t) + ",".join(vals) + "\n")


def _plot(p, title, cbar, cmap, path, clip=None):
    fig, ax = plt.subplots(figsize=(max(9, 0.28 * len(p.columns)), 5.6))
    arr = p.values.T
    if clip is not None:
        arr = np.clip(arr, clip[0], clip[1])
    _extent = None
    try:
        _tmin = float(p.index.min())
        _tmax = float(p.index.max())
        if _tmax > _tmin:
            _extent = [_tmin, _tmax, -0.5, len(p.columns) - 0.5]
    except Exception:
        _extent = None
    im = ax.imshow(arr, aspect="auto", origin="lower",
                   interpolation="nearest", cmap=cmap,
                   extent=_extent)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("Aimsun section (ordered by junction, main first)")
    ax.set_title(title)
    ax.set_yticks(range(len(p.columns)))
    ax.set_yticklabels([str(int(s)) for s in p.columns], fontsize=6)
    fig.colorbar(im, ax=ax, label=cbar)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None,
                    help="section_timeseries.csv (default: newest run)")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--src", default="any",
                    help="any (default), AKIEST (measured only), or IMPOSED")
    ap.add_argument("--min-samples", type=int, default=2)
    args = ap.parse_args()

    csv_path = args.csv or _latest_csv()
    if not csv_path or not os.path.isfile(csv_path):
        raise SystemExit("no section_timeseries.csv found; pass --csv")
    d = pd.read_csv(csv_path, encoding="utf-8-sig", engine="python")
    if "SectionID" not in d.columns:
        raise SystemExit("not a section_timeseries.csv: %s" % csv_path)
    if "src" in d.columns and args.src.lower() != "any":
        d = d[d["src"].astype(str).str.upper() == args.src.upper()].copy()
    if d.empty:
        raise SystemExit("no %s rows in %s" % (args.src, csv_path))
    time_col = "t_end_s" if "t_end_s" in d.columns else "t_start_s"

    meta = d.groupby("SectionID").agg(
        inter=("IntersectionID", "first"),
        main=("IsMain", "first"),
        lanes=("Lanes", "first"),
        length_km=("Length_km", "first"),
        n=("k_vkm_lane", "count"))
    meta = meta[meta["n"] >= args.min_samples]
    meta = meta.sort_values(["inter", "main", "SectionID"],
                            ascending=[True, False, True])
    secs = [int(s) for s in meta.index]

    dens = _matrix(d, time_col, secs, "k_vkm_lane")
    speed = _matrix(d, time_col, secs, "v_kmh")
    flow = _matrix(d, time_col, secs, "q_veh_h")
    queue = _matrix(d, time_col, secs, "queue_veh")
    try:
        speed = speed.replace(0.0, np.nan)
    except Exception:
        pass

    run = os.path.basename(os.path.dirname(os.path.abspath(csv_path)))
    out = args.out_dir or os.path.join(
        os.path.dirname(os.path.abspath(csv_path)), "true_states")
    os.makedirs(out, exist_ok=True)

    _write_matrix(os.path.join(out, "truestate_%s_density.txt" % run),
                  dens, "density")
    _write_matrix(os.path.join(out, "truestate_%s_speed.txt" % run),
                  speed, "speed")
    _write_matrix(os.path.join(out, "truestate_%s_flow.txt" % run),
                  flow, "flow")
    _write_matrix(os.path.join(out, "truestate_%s_queue.txt" % run),
                  queue, "queue")

    _plot(dens, "True density -- %s" % run,
          "veh/km/lane", "viridis",
          os.path.join(out, "truestate_%s_density.png" % run))
    _plot(speed, "True speed -- %s" % run,
          "km/h", "turbo",
          os.path.join(out, "truestate_%s_speed.png" % run))
    _plot(flow, "True flow -- %s" % run,
          "veh/h", "magma",
          os.path.join(out, "truestate_%s_flow.png" % run))
    _plot(queue, "True queue -- %s" % run,
          "veh", "cividis",
          os.path.join(out, "truestate_%s_queue.png" % run))

    print("run      :", run)
    print("source   :", csv_path, "(%s rows)" % len(d))
    print("sections :", len(secs), "time samples:", len(dens))
    print("out      :", out)
    for f in sorted(os.listdir(out)):
        print("  ", f)


if __name__ == "__main__":
    main()
