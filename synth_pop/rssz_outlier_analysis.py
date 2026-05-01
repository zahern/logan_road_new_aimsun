"""
RSSZ Outlier Analysis
======================
Diagnoses zones with high RSSZ and which control tables drive the poor fit.
Reviewer 2 (Table 2): explain why max RSSZ spikes to 7.52 for SA-GAN.

All paths come from config.py.  Run from synth_pop/:
    python rssz_outlier_analysis.py [--results-dir zones_sa_5_main] [--threshold 2.0]
"""

import argparse, glob, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config
sys.path.insert(0, config.SA_DIR)

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from SA_2_level import build_control_dicts, calculate_total_rssz_table
from CensusRecordImporter import CensusControlTable

OUTPUT_DIR = config.RSSZ_OUTLIER_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_control_tables():
    ind, hh = {}, {}
    for fname in os.listdir(config.SA_CONTROL_IND):
        if fname.endswith(".csv"):
            key = fname.replace(".csv", "").lower()
            ct = CensusControlTable(os.path.join(config.SA_CONTROL_IND, fname))
            ct.validate_and_clean(); ind[key] = ct
    for fname in os.listdir(config.SA_CONTROL_HH):
        if fname.endswith(".csv"):
            key = fname.replace(".csv", "").lower()
            ct = CensusControlTable(os.path.join(config.SA_CONTROL_HH, fname))
            ct.validate_and_clean(); hh[key] = ct
    return ind, hh


def zone_rssz(fpath, zone_id, ind_tables, hh_tables):
    df = pd.read_csv(fpath)
    ind_d = build_control_dicts(ind_tables, zone_id)
    hh_d  = build_control_dicts(hh_tables,  zone_id)
    try:
        total, per_table = calculate_total_rssz_table(df.to_dict("records"), ind_d, hh_d)
        return total, per_table
    except Exception as e:
        print(f"  WARN zone {zone_id}: {e}")
        return None, None


def plot_zone(zone_id, per_table, threshold):
    labels = list(per_table.keys())
    values = [per_table[k] for k in labels]
    thresh_per = threshold / max(len(labels), 1)
    colors = ["crimson" if v > thresh_per else "steelblue" for v in values]
    fig, ax = plt.subplots(figsize=(max(10, len(labels)*0.7), 5))
    ax.bar(range(len(labels)), values, color=colors, edgecolor="black", alpha=0.8)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=8)
    ax.set_ylabel("RSSZ"); ax.set_title(f"Zone {zone_id} — per-table RSSZ (red = high)")
    ax.axhline(np.mean(values), color="orange", linestyle="--",
               label=f"Mean = {np.mean(values):.3f}")
    ax.legend(); plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, f"outlier_zone_{zone_id}.png"), dpi=100)
    plt.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir", default=config.SA_GAN_RESULTS_DIR)
    p.add_argument("--threshold",   type=float, default=2.0)
    args = p.parse_args()

    # Prefer SA-GAN results; fall back to SA-Only
    result_files = glob.glob(os.path.join(args.results_dir, "*.csv"))
    if not result_files:
        result_files = glob.glob(os.path.join(config.SA_ONLY_RESULTS_DIR, "zone_*.csv"))
    if not result_files:
        raise FileNotFoundError(f"No result CSVs found in {args.results_dir}")

    print(f"Analysing {len(result_files)} zone files from: {args.results_dir}")
    ind_tables, hh_tables = load_control_tables()

    records = []
    for fpath in sorted(result_files):
        zone_id = (os.path.basename(fpath)
                   .replace(".csv", "").replace("zone_", "").replace("_sa_only", ""))
        print(f"  zone {zone_id}...")
        total, per = zone_rssz(fpath, zone_id, ind_tables, hh_tables)
        if total is None: continue
        rec = {"zone": zone_id, "rssz_total": total}
        if per: rec.update(per)
        records.append(rec)

    rssz_df = pd.DataFrame(records).sort_values("rssz_total", ascending=False)
    rssz_df.to_csv(os.path.join(OUTPUT_DIR, "rssz_by_zone.csv"), index=False)

    vals = rssz_df["rssz_total"]
    print(f"\n{'='*60}\nRSSZ summary — {len(vals)} zones\n{'='*60}")
    print(f"  Mean  : {vals.mean():.4f}")
    print(f"  Median: {vals.median():.4f}")
    print(f"  Min   : {vals.min():.4f}")
    print(f"  Max   : {vals.max():.4f}")
    print(f"  Std   : {vals.std():.4f}")

    outliers = rssz_df[rssz_df["rssz_total"] > args.threshold]
    outliers.to_csv(os.path.join(OUTPUT_DIR, "outlier_zones.csv"), index=False)
    print(f"\n  Outlier zones (>{args.threshold}): {len(outliers)}")
    for _, row in outliers.iterrows():
        print(f"    Zone {row['zone']}: {row['rssz_total']:.4f}")

    table_cols = [c for c in rssz_df.columns if c not in ("zone", "rssz_total")]
    for _, row in outliers.iterrows():
        pt = {c: row[c] for c in table_cols if pd.notna(row.get(c))}
        plot_zone(row["zone"], pt, args.threshold)

    if table_cols:
        thresh_per = args.threshold / max(len(table_cols), 1)
        driver_counts = {c: int((rssz_df[c] > thresh_per).sum())
                         for c in table_cols if c in rssz_df.columns}
        driver_df = pd.DataFrame(
            sorted(driver_counts.items(), key=lambda x: -x[1]),
            columns=["control_table", "n_zones_high_rssz"]
        )
        driver_df.to_csv(os.path.join(OUTPUT_DIR, "driver_tables.csv"), index=False)
        print("\nTop control tables driving high RSSZ:")
        print(driver_df.head(10).to_string(index=False))

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(vals, bins=30, edgecolor="black", alpha=0.75, color="steelblue")
    ax.axvline(args.threshold, color="red",    linestyle="--", label=f"threshold={args.threshold}")
    ax.axvline(vals.mean(),    color="orange", linestyle="--", label=f"mean={vals.mean():.4f}")
    ax.set_xlabel("RSSZ"); ax.set_ylabel("Zones")
    ax.set_title("Distribution of Zone-Level RSSZ Values")
    ax.legend(); plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "rssz_distribution.png"), dpi=100)
    plt.close()

    print(f"\nOutputs written to: {OUTPUT_DIR}")
    print(
        "\n[CHECK] rssz_distribution.png — are outlier zones small (high sampling variance)?")
    print("[CHECK] outlier_zone_*.png   — which control tables fail in outlier zones?")
    print("[CHECK] driver_tables.csv    — flag the worst-fitting tables in the paper discussion.")


if __name__ == "__main__":
    main()
