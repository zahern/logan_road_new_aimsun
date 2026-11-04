"""calibrate_ctm_from_timeseries.py -- fit per-section CTM triangles from Aimsun runs.

The Aimsun stats module already writes the ground-truth per-section time series
``section_timeseries.csv`` (q_veh_h, k_vkm_lane, v_kmh, n_veh, queue_veh, src).
This script fits a triangular fundamental diagram per section:

    v_free  85th percentile speed at low density          [km/h]
    q_max   95th percentile measured flow per lane         [veh/h/lane]
    k_jam   97th percentile measured density               [veh/km/lane]
    k_crit  q_max / v_free                                 [veh/km/lane]
    w_back  congested-branch slope -dq/dk                  [km/h]

and writes ``kg/ctm_calibration.json`` for the CTM. Only ``src == AKIEST`` rows
(the independently measured triplet) are used; ``IMPOSED`` rows are fallbacks
with q = k*v enforced by construction and would bias the fit.

Usage
-----
    python calibrate_ctm_from_timeseries.py
    python calibrate_ctm_from_timeseries.py --arm NO_TSP --out kg/ctm_calibration.json
    python calibrate_ctm_from_timeseries.py --pattern "kg/results/*/section_timeseries.csv"

The output is additive and OPT-IN: nothing changes in the controller until
CTM_CALIB_PATH points at the JSON. Missing/weak sections keep the defaults.
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULTS = {
    "v_free_kmh": 50.0,
    "w_back_kmh": 18.0,
    "k_jam_vkm_lane": 200.0,
    "q_max_vph_lane": 1800.0,
    "k_crit_vkm_lane": 36.0,
}
MIN_SAMPLES = 30


def _num(s, d=0.0):
    try:
        v = float(s)
        return v if np.isfinite(v) else d
    except Exception:
        return d


def _pct(a, q, d):
    try:
        a = np.asarray(a, dtype=float)
        a = a[np.isfinite(a)]
        return float(np.percentile(a, q)) if a.size else float(d)
    except Exception:
        return float(d)


def _fit_section(g):
    g = g.copy()
    for c in ("q_veh_h", "k_vkm_lane", "v_kmh"):
        g[c] = pd.to_numeric(g[c], errors="coerce")
    g = g[(g["q_veh_h"] >= 0) & (g["k_vkm_lane"] >= 0) & (g["v_kmh"] >= 0)]
    g = g[np.isfinite(g["q_veh_h"]) & np.isfinite(g["k_vkm_lane"])]
    n_all = int(len(g))
    if n_all < MIN_SAMPLES:
        return None

    lanes = 1
    try:
        lanes = max(int(round(float(g["Lanes"].mode().iloc[0]))), 1)
    except Exception:
        lanes = 1
    length_km = _num(g["Length_km"].mode().iloc[0] if len(g) else 0.0, 0.0)

    k = g["k_vkm_lane"].to_numpy(dtype=float)
    q_lane = g["q_veh_h"].to_numpy(dtype=float) / float(lanes)
    v = g["v_kmh"].to_numpy(dtype=float)

    k_jam = _pct(k, 97, DEFAULTS["k_jam_vkm_lane"])
    q_max = _pct(q_lane[q_lane > 0], 95, DEFAULTS["q_max_vph_lane"])
    # Physical caps: per-lane capacity ~1900 veh/h and jam density ~200 veh/km.
    q_max = float(np.clip(q_max, 200.0, 1900.0))
    k_jam = float(np.clip(k_jam, 20.0, 200.0))

    low = (k <= max(0.35 * k_jam, 12.0)) & (v > 5.0)
    if int(low.sum()) >= 10:
        v_free = _pct(v[low], 85, DEFAULTS["v_free_kmh"])
    else:
        v_free = _pct(v[v > 5.0], 90, DEFAULTS["v_free_kmh"])
    v_free = float(np.clip(v_free, 20.0, 110.0))

    k_crit = float(q_max / max(v_free, 1.0))
    cong = (k > k_crit * 1.05) & (q_lane > 0)
    w_back = DEFAULTS["w_back_kmh"]
    if int(cong.sum()) >= 8:
        try:
            b, _a = np.polyfit(k[cong], q_lane[cong], 1)
            w_back = float(np.clip(-b, 5.0, 40.0))
        except Exception:
            pass

    try:
        inter = int(round(float(g["IntersectionID"].mode().iloc[0])))
    except Exception:
        inter = 0
    try:
        is_main = int(round(float(g["IsMain"].mode().iloc[0])))
    except Exception:
        is_main = 0

    return {
        "v_free_kmh": round(v_free, 2),
        "q_max_vph_lane": round(q_max, 1),
        "k_jam_vkm_lane": round(k_jam, 1),
        "k_crit_vkm_lane": round(k_crit, 2),
        "w_back_kmh": round(w_back, 2),
        "lanes": int(lanes),
        "length_km": round(length_km, 4),
        "is_main": int(is_main),
        "inter_id": int(inter),
        "n_samples": n_all,
        "n_akiest": int((g["src"].astype(str).str.upper() == "AKIEST").sum()),
    }


def _agg(rows, defaults):
    if not rows:
        return dict(defaults)
    out = {}
    for k in ("v_free_kmh", "q_max_vph_lane", "k_jam_vkm_lane",
              "w_back_kmh"):
        w = np.array([max(1, r.get("n_samples", 1)) for r in rows], dtype=float)
        a = np.array([float(r.get(k, defaults[k])) for r in rows], dtype=float)
        out[k] = round(float(np.average(a, weights=w)), 2)
    out["k_crit_vkm_lane"] = round(
        out["q_max_vph_lane"] / max(out["v_free_kmh"], 1.0), 2)
    out["n_sections"] = len(rows)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default=os.path.join(
        HERE, "kg", "results", "*", "section_timeseries.csv"))
    ap.add_argument("--arm", default="NO_TSP",
                    help="Experiment substring filter (default NO_TSP); '*' = all")
    ap.add_argument("--out", default=os.path.join(HERE, "kg", "ctm_calibration.json"))
    ap.add_argument("--qc", default=os.path.join(HERE, "kg", "ctm_calibration_qc.csv"))
    args = ap.parse_args()

    files = sorted(glob.glob(args.pattern))
    if args.arm and args.arm != "*":
        files = [f for f in files if args.arm.lower() in os.path.basename(
            os.path.dirname(f)).lower()]
    if not files:
        raise SystemExit("no section_timeseries.csv matched %r" % args.pattern)

    frames = []
    for f in files:
        try:
            d = pd.read_csv(f)
            d["_file"] = os.path.basename(os.path.dirname(f))
            frames.append(d)
        except Exception as e:
            print("skip %s: %r" % (f, e))
    if not frames:
        raise SystemExit("no readable time series")
    d = pd.concat(frames, ignore_index=True)
    d["src"] = d["src"].astype(str).str.upper()
    n_all = len(d)
    d = d[d["src"] == "AKIEST"]
    print("loaded %d files, %d rows (%d AKIEST)" % (len(files), n_all, len(d)))
    if d.empty:
        raise SystemExit("no AKIEST rows -- run with per-section stats enabled")

    sections = {}
    for sec, g in d.groupby("SectionID"):
        fit = _fit_section(g)
        if fit:
            sections[int(sec)] = fit

    junctions = {}
    for inter, gi in d.groupby("IntersectionID"):
        try:
            iid = int(round(float(inter)))
        except Exception:
            continue
        main = [sections[int(s)] for s in gi["SectionID"].unique()
                if int(s) in sections and sections[int(s)]["is_main"]]
        side = [sections[int(s)] for s in gi["SectionID"].unique()
                if int(s) in sections and not sections[int(s)]["is_main"]]
        junctions[str(iid)] = {
            "main": _agg(main, DEFAULTS),
            "side": _agg(side, DEFAULTS),
        }

    out = {
        "build": "2026-10-24-ctm-calib",
        "source_glob": args.pattern,
        "arm_filter": args.arm,
        "files": len(files),
        "akiest_rows": int(len(d)),
        "defaults": dict(DEFAULTS),
        "sections": {str(k): v for k, v in sorted(sections.items())},
        "junctions": dict(sorted(junctions.items())),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
    print("wrote", args.out, "(%d sections, %d junctions)"
          % (len(sections), len(junctions)))

    rows = []
    for sec, r in sorted(sections.items()):
        rows.append({"section": sec, "inter_id": r["inter_id"],
                     "is_main": r["is_main"], "lanes": r["lanes"],
                     "length_km": r["length_km"],
                     "v_free_kmh": r["v_free_kmh"],
                     "q_max_vph_lane": r["q_max_vph_lane"],
                     "k_jam_vkm_lane": r["k_jam_vkm_lane"],
                     "k_crit_vkm_lane": r["k_crit_vkm_lane"],
                     "w_back_kmh": r["w_back_kmh"],
                     "n_samples": r["n_samples"]})
    if rows:
        pd.DataFrame(rows).to_csv(args.qc, index=False)
        print("wrote", args.qc)
        print("v_free %.1f-%.1f  q_max %.0f-%.0f  k_jam %.0f-%.0f  w %.1f-%.1f"
              % (min(r["v_free_kmh"] for r in rows),
                 max(r["v_free_kmh"] for r in rows),
                 min(r["q_max_vph_lane"] for r in rows),
                 max(r["q_max_vph_lane"] for r in rows),
                 min(r["k_jam_vkm_lane"] for r in rows),
                 max(r["k_jam_vkm_lane"] for r in rows),
                 min(r["w_back_kmh"] for r in rows),
                 max(r["w_back_kmh"] for r in rows)))


if __name__ == "__main__":
    main()
