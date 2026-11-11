r"""Final Logan Road comparison table: five arms, five seeds, anomaly-aware.

Reads the live ladder CSV, applies the NO_TSP seed-300 passage correction in
memory (the row is flagged, not overwritten), and reports per-arm means with
paired per-seed deltas against NO_TSP on the same seed, plus a sensitivity
that drops the flagged baseline seed.

Also appends the SUMO HPC rows for the same five arms as their parts CSVs land
(Z:\tsp\sumo_hpc\parts). They get their own block and their own baseline (SUMO
NO_TSP, same seed) because the two platforms count the passenger numerator
differently: only pax-hours per sim-hour is comparable across them, so the HPC
rows are written to logan_hpc_table.csv rather than mixed into the Aimsun table.

Usage:
    python final_logan_table.py                  # requires all 25 Aimsun rows
    python final_logan_table.py --allow-partial   # report whatever exists
    python final_logan_table.py --no-hpc          # Aimsun only
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

LIVE = "game_ladder_logan_lightsim_20261109_124707.csv"
OUT_CSV = "_sumo_port/analysis_corrected/logan_final_table.csv"
HPC_PARTS = r"Z:\tsp\sumo_hpc\parts"
HPC_OUT_CSV = "_sumo_port/analysis_corrected/logan_hpc_table.csv"
SEEDS = [300, 400, 500, 600, 700]
RAW_PAX_300 = 217929.6
CORRECTION = 1.159

OBJ = "stats_Objective_PaxPerDelayHr"
DLAY = "stats_TotalPassDelay_hrs"
PAX = "stats_PaxEquivPassages"
LOOP = "stats_N_LoopCompletions"

LABELS = {
    "NO_TSP": "M0 NO_TSP",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2": "NASH (CTM2+SPILL2)",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM": "NASH + LIGHTSIM",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2": "UTIL (CTM2+SPILL2)",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_LIGHTSIM": "UTIL + LIGHTSIM",
}
ORDER = list(LABELS)
BASE = "NO_TSP"

HPC_ARMS = [
    ("CHAMP_NO_TSP", "HPC M0 NO_TSP"),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2", "HPC NASH (CTM2+SPILL2)"),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM", "HPC NASH + LIGHTSIM"),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2", "HPC UTIL (CTM2+SPILL2)"),
    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_LIGHTSIM", "HPC UTIL + LIGHTSIM"),
]
HPC_BASE = "CHAMP_NO_TSP"
HPC_OBJ = "obj_pax_per_delay_hr"
HPC_PAXH = "avg_total_pass_delay_per_hr"


def load(path):
    d = pd.read_csv(path).set_index(["run_experiment", "run_seed"])
    k = (BASE, 300)
    if k in d.index and abs(float(d.loc[k, PAX]) - RAW_PAX_300) < 0.5:
        for col in (PAX, "inter_sum_PaxEquivPassages", "inter_avg_PaxEquivPassages",
                    "stats_CarPaxEquivPassages", "inter_sum_CarPaxEquivPassages",
                    "stats_Obj_Z4_throughput_pax"):
            if col in d.columns:
                d.loc[k, col] = float(d.loc[k, col]) * CORRECTION
        d.loc[k, OBJ] = float(d.loc[k, PAX]) / float(d.loc[k, DLAY])
        d.loc[k, "run_demand_anomaly"] = 1
    return d


def paired(table, col, seeds):
    """Mean per-seed ratio against NO_TSP on the same seed, with a 95% t-CI."""
    out = {}
    for arm in ORDER:
        r = []
        for s in seeds:
            if (arm, s) in table and (BASE, s) in table:
                n, dn = table[(arm, s)][col], table[(BASE, s)][col]
                if not (pd.isna(n) or pd.isna(dn)):
                    r.append(n / dn - 1.0)
        r = np.array(r, float)
        if len(r) == 0:
            out[arm] = (np.nan, np.nan, np.nan, 0)
            continue
        half = (stats.t.ppf(0.975, len(r) - 1) * r.std(ddof=1) / np.sqrt(len(r))
                if len(r) > 1 else np.nan)
        out[arm] = (100 * r.mean(), 100 * (r.mean() - half), 100 * (r.mean() + half), len(r))
    return out


def load_hpc(parts):
    """{(arm, seed): row} from the SUMO ladder parts; eval rows that finished ok."""
    out = {}
    for p in sorted(glob.glob(os.path.join(parts, "ladder_*_eval*.csv"))):
        try:
            d = pd.read_csv(p)
        except Exception:
            continue
        for _, r in d.iterrows():
            if str(r.get("phase", "eval")).lower() != "eval":
                continue
            if str(r.get("ok", "")).strip().lower() not in ("true", "1"):
                continue
            try:
                out[(str(r["arm"]).strip(), int(float(r["seed"])))] = r
            except (KeyError, TypeError, ValueError):
                continue
    return out


def hpc_paired(hpc, col):
    """Mean per-seed ratio against the SUMO NO_TSP row on the same seed."""
    res = {}
    for arm, _label in HPC_ARMS:
        r = []
        for s in SEEDS:
            if (arm, s) in hpc and (HPC_BASE, s) in hpc:
                b = float(hpc[(HPC_BASE, s)][col])
                v = float(hpc[(arm, s)][col])
                if b and not (np.isnan(b) or np.isnan(v)):
                    r.append(v / b - 1.0)
        r = np.array(r, float)
        if len(r) == 0:
            res[arm] = (np.nan, np.nan, np.nan, 0)
            continue
        half = (stats.t.ppf(0.975, len(r) - 1) * r.std(ddof=1) / np.sqrt(len(r))
                if len(r) > 1 else np.nan)
        res[arm] = (100 * r.mean(), 100 * (r.mean() - half), 100 * (r.mean() + half), len(r))
    return res


def report_hpc(args):
    """The SUMO rows: printed as they land, written separately from the Aimsun table."""
    hpc = {} if args.no_hpc else load_hpc(args.hpc_parts)
    print("\nSUMO HPC rows (pax-hours per sim-hour; deltas vs SUMO NO_TSP, same seed)")
    if not hpc:
        print("  no HPC parts yet under %s" % args.hpc_parts)
        return
    hobj = hpc_paired(hpc, HPC_OBJ)
    hpax = hpc_paired(hpc, HPC_PAXH)
    print("  %-24s %2s %10s %16s %10s %10s" % (
        "arm", "n", "objective", "dobj% [95% CI]", "paxh", "dpaxh%"))
    recs = []
    for arm, label in HPC_ARMS:
        vals = [s for s in SEEDS if (arm, s) in hpc]
        if not vals:
            continue
        o, ol, oh, _n = hobj[arm]
        m_obj = float(np.mean([float(hpc[(arm, s)][HPC_OBJ]) for s in vals]))
        m_paxh = float(np.mean([float(hpc[(arm, s)][HPC_PAXH]) for s in vals]))
        print("  %-24s %2d %10.3f %7.2f [%5.1f,%5.1f] %10.1f %+9.2f" % (
            label, len(vals), m_obj, o, ol, oh, m_paxh, hpax[arm][0]))
        recs.append(dict(platform="sumo", arm=label, n=len(vals), objective=m_obj,
                         dobj_pct=o, dobj_lo=ol, dobj_hi=oh, paxh=m_paxh,
                         dpaxh_pct=hpax[arm][0]))
    pd.DataFrame(recs).to_csv(HPC_OUT_CSV, index=False)
    print("  wrote %s" % HPC_OUT_CSV)
    print("  note: the SUMO objective counts passengers differently from Aimsun; "
          "compare pax-hours only, never the objective")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-partial", action="store_true")
    ap.add_argument("--live", default=LIVE)
    ap.add_argument("--hpc-parts", default=HPC_PARTS)
    ap.add_argument("--no-hpc", action="store_true")
    args = ap.parse_args()

    d = load(args.live)
    rows = d.reset_index().set_index(["run_experiment", "run_seed"])
    present = {(a, s): rows.loc[(a, s)] for (a, s) in rows.index}
    complete = all((a, s) in present for a in ORDER for s in SEEDS)
    print("live file: %s | rows: %d/25" % (args.live, len(rows)))
    if not complete and not args.allow_partial:
        print("incomplete: refusing to emit the final table (use --allow-partial)")
        report_hpc(args)
        return 2

    tbl = {(a, s): present[(a, s)] for (a, s) in present}
    obj = paired(tbl, OBJ, SEEDS)
    dly = paired(tbl, DLAY, SEEDS)
    pax = paired(tbl, PAX, SEEDS)
    lop = paired(tbl, LOOP, SEEDS)
    excl = paired(tbl, OBJ, [s for s in SEEDS if s != 300])

    def mean_of(arm, col, seeds=SEEDS):
        v = [tbl[(arm, s)][col] for s in seeds if (arm, s) in tbl]
        return float(np.mean(v)) if v else np.nan

    recs = []
    print("\n%-22s %2s %9s %16s %9s %9s %11s %9s %7s %9s %16s" % (
        "arm", "n", "objective", "dobj% [95% CI]", "delay", "ddelay%",
        "passages", "dpass%", "loops", "dloops%", "GE/INS/ER"))
    for arm in ORDER:
        vals = [s for s in SEEDS if (arm, s) in tbl]
        if not vals:
            continue
        ge = np.mean([tbl[(arm, s)].get("stats_TSP_Extensions", 0) for s in vals])
        ins = np.mean([tbl[(arm, s)].get("stats_TSP_Insertions", 0) for s in vals])
        er = np.mean([tbl[(arm, s)].get("stats_TSP_EarlyRed", 0) for s in vals])
        o, ol, oh, n = obj[arm]
        marker = "*" if arm != BASE and not complete else ""
        print("%-22s %2d %9.1f %7.2f [%5.1f,%5.1f] %9.0f %+8.2f %11.0f %+8.2f %7.0f %+8.2f %5.1f/%4.1f/%4.1f%s" % (
            LABELS[arm], len(vals), mean_of(arm, OBJ), o, ol, oh,
            mean_of(arm, DLAY), dly[arm][0], mean_of(arm, PAX), pax[arm][0],
            mean_of(arm, LOOP), lop[arm][0], ge, ins, er, marker))
        recs.append(dict(arm=LABELS[arm], n=len(vals),
                         objective=mean_of(arm, OBJ), dobj_pct=o, dobj_lo=ol, dobj_hi=oh,
                         delay=mean_of(arm, DLAY), ddelay_pct=dly[arm][0],
                         pax=mean_of(arm, PAX), dpax_pct=pax[arm][0],
                         loops=mean_of(arm, LOOP), dloops_pct=lop[arm][0],
                         ge=ge, ins=ins, er=er,
                         dobj_pct_excl300=excl[arm][0], n_excl300=excl[arm][3]))

    print("\nsensitivity: objective change with the flagged baseline seed dropped (n=4)")
    for arm in ORDER:
        if arm == BASE:
            continue
        print("  %-22s %+6.2f%%" % (LABELS[arm], excl[arm][0]))

    pd.DataFrame(recs).to_csv(OUT_CSV, index=False)
    print("\nwrote %s" % OUT_CSV)
    print("flag: NO_TSP seed 300 is imputed (pax-equivalents x%0.3f), not simulated" % CORRECTION)
    report_hpc(args)
    return 0 if complete else 3


if __name__ == "__main__":
    sys.exit(main())
