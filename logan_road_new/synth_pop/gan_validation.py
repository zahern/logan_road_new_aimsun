"""
GAN Validation
==============
Compares the DATGAN-generated synthetic population against the original census microdata.

Addresses:
- Reviewer 1: distribution comparison + out-of-sample joint attribute validation
- Reviewer 2 (App A.2): rejection/repair rate reporting

All paths come from config.py.  Run from synth_pop/:
    python gan_validation.py
"""

import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import ks_2samp, chi2_contingency

OUTPUT_DIR = config.GAN_VALIDATION_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, "marginal_distributions"), exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, "joint_distributions"), exist_ok=True)

# Columns used as control tables — out-of-sample columns are the rest
FITTING_COLUMNS = [
    "SEXP", "AGEP", "MTWP", "HIED", "OCCP", "MSTP", "MRERD", "RNTRD",
    "VEHRD", "NPRD", "RLHP", "STRD",
]

JOINT_PAIRS_OUT_OF_SAMPLE = [
    ("AGEP", "INCP"),
    ("OCCP", "INCP"),
    ("SEXP", "OCCP"),
    ("HEAP", "EMPP"),
    ("HIND", "VEHRD"),
    ("CPRF", "CACF"),
]

# Hard-constraint checks for repair/rejection rate (Reviewer 2, App A.2)
CONSTRAINT_CHECKS = {
    "AGEP<15 but EMPP employed":
        lambda df: (df["AGEP"] < 15) & (~df["EMPP"].isin([4, 8]))
        if "AGEP" in df.columns and "EMPP" in df.columns
        else pd.Series(False, index=df.index),

    "CACF > CPRF (children exceed family size)":
        lambda df: df["CACF"] > df["CPRF"]
        if "CACF" in df.columns and "CPRF" in df.columns
        else pd.Series(False, index=df.index),

    "HIND==1 (negative) but MRERD>0":
        lambda df: (df["HIND"] == 1) & (df["MRERD"] > 0)
        if "HIND" in df.columns and "MRERD" in df.columns
        else pd.Series(False, index=df.index),
}


def load():
    orig  = pd.read_csv(config.LINKED_DATA)
    synth = pd.read_csv(config.DATGAN_OUTPUT)
    orig.columns  = [c.upper() for c in orig.columns]
    synth.columns = [c.upper() for c in synth.columns]
    print(f"Original : {len(orig):,} records")
    print(f"Synthetic: {len(synth):,} records  ({len(synth)/max(len(orig),1):.1f}×)")
    return orig, synth


def compare_marginal(col, orig, synth):
    orig_v  = orig[col].dropna()
    synth_v = synth[col].dropna()
    is_cont = pd.api.types.is_float_dtype(orig_v) and orig_v.nunique() > 30

    if is_cont:
        stat, pval = ks_2samp(orig_v, synth_v)
        stat_name = "KS"
    else:
        cats = sorted(set(orig_v.unique()) | set(synth_v.unique()))
        o = orig_v.value_counts().reindex(cats, fill_value=0)
        s = synth_v.value_counts().reindex(cats, fill_value=0)
        scale = len(orig_v) / max(len(synth_v), 1)
        s_scaled = (s * scale).round().astype(int)
        ct = np.array([o.values, s_scaled.values])
        ct = ct[:, ct.sum(axis=0) > 0]
        chi2, pval, _, _ = chi2_contingency(ct)
        stat, stat_name = chi2, "chi2"

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, (label, series) in zip(axes, [("Original", orig_v), ("Synthetic", synth_v)]):
        if is_cont:
            ax.hist(series, bins=30, edgecolor="black", alpha=0.7)
        else:
            vc = series.value_counts().sort_index()
            ax.bar(vc.index.astype(str), vc.values, edgecolor="black", alpha=0.7)
            ax.tick_params(axis="x", rotation=45)
        ax.set_title(f"{label} — {col}")
        ax.set_ylabel("Count")
    fig.suptitle(f"{col}  |  {stat_name}={stat:.4f}  p={pval:.4f}", fontsize=11)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "marginal_distributions", f"{col}.png"), dpi=100)
    plt.close()
    return {"column": col, "statistic": stat_name, "value": round(stat, 4), "p_value": round(pval, 4)}


def compare_joint(col_a, col_b, orig, synth):
    missing = [c for c in (col_a, col_b) if c not in orig.columns or c not in synth.columns]
    if missing:
        print(f"  skip joint ({col_a}×{col_b}) — missing: {missing}")
        return
    def ct(df, a, b):
        return pd.crosstab(df[a], df[b], normalize="all")
    o_ct = ct(orig,  col_a, col_b)
    s_ct = ct(synth, col_a, col_b)
    rows = sorted(set(o_ct.index) | set(s_ct.index))
    cols = sorted(set(o_ct.columns) | set(s_ct.columns))
    o_ct = o_ct.reindex(index=rows, columns=cols, fill_value=0)
    s_ct = s_ct.reindex(index=rows, columns=cols, fill_value=0)
    diff = s_ct - o_ct
    vmax = max(o_ct.values.max(), s_ct.values.max())

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    for ax, data, title, cmap in zip(
        axes,
        [o_ct, s_ct, diff],
        ["Original", "Synthetic", "Diff (Synth − Orig)"],
        ["Blues", "Oranges", "RdBu"],
    ):
        im = ax.imshow(data.values, cmap=cmap, aspect="auto",
                       vmin=(-vmax if "Diff" in title else 0), vmax=vmax)
        ax.set_title(f"{title}  {col_a}×{col_b}")
        ax.set_xlabel(col_b); ax.set_ylabel(col_a)
        plt.colorbar(im, ax=ax)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "joint_distributions", f"joint_{col_a}_{col_b}.png"), dpi=100)
    plt.close()


def repair_rate(synth):
    n = len(synth)
    lines = [f"Repair / Rejection Rate Report\n{'='*50}", f"Synthetic records: {n:,}\n"]
    total = pd.Series(False, index=synth.index)
    for desc, fn in CONSTRAINT_CHECKS.items():
        mask = fn(synth)
        cnt = int(mask.sum())
        lines.append(f"  {desc}\n    violations: {cnt:,}  ({100*cnt/n:.2f}%)\n")
        total |= mask
    tc = int(total.sum())
    lines.append(f"Total records requiring repair/rejection: {tc:,}  ({100*tc/n:.2f}%)")
    lines.append(
        "\nNote: a repair rate >5% suggests the GAN's joint distribution diverges\n"
        "from the hard constraint space, potentially biasing the synthetic population."
    )
    report = "\n".join(lines)
    with open(os.path.join(OUTPUT_DIR, "repair_report.txt"), "w") as f:
        f.write(report)
    print(report)
    return 100 * tc / n


def main():
    print("Loading data...")
    orig, synth = load()
    common = [c for c in orig.columns if c in synth.columns]

    print(f"\n--- Marginal distributions ({len(common)} columns) ---")
    results = []
    for col in common:
        r = compare_marginal(col, orig, synth)
        if r:
            oos = " [out-of-sample]" if col not in FITTING_COLUMNS else ""
            print(f"  {col}: {r['statistic']}={r['value']:.4f}  p={r['p_value']:.4f}{oos}")
            results.append(r)

    if results:
        df = pd.DataFrame(results)
        df["in_fitting"] = df["column"].isin(FITTING_COLUMNS)
        df.sort_values("value", ascending=False).to_csv(
            os.path.join(OUTPUT_DIR, "validation_summary.csv"), index=False)
        print(f"\nSaved validation_summary.csv")

    print("\n--- Joint attribute pairs (out-of-sample) ---")
    for a, b in JOINT_PAIRS_OUT_OF_SAMPLE:
        compare_joint(a, b, orig, synth)

    print("\n--- Repair / rejection rate ---")
    pct = repair_rate(synth)
    print(f"\nOverall estimated repair rate: {pct:.2f}%")
    print(f"\nOutputs written to: {OUTPUT_DIR}")
    print("\n[CHECK] marginal_distributions/ — do synthetic distributions match original?")
    print("[CHECK] joint_distributions/    — are multi-attribute relationships preserved?")
    print(f"[CHECK] repair_report.txt      — if >5%, discuss bias in paper (App A.2)")


if __name__ == "__main__":
    main()
