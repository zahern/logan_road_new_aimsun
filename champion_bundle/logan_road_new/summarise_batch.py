"""
summarise_batch.py
------------------
Read batch_results.csv and print seed-averaged KPIs per strategy/experiment.
Run standalone:  python summarise_batch.py
"""
import os
import pandas as pd
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
CSV   = os.path.join(_HERE, "batch_results.csv")

# Key metrics to summarise (column name → display label)
METRICS = {
    "stats_AvgBusPassDelay_s":    "Avg Bus Delay (s/pax)",
    "stats_AvgCarPassDelay_s":    "Avg Car Delay (s/pax)",
    "stats_AvgPassDelay_s":       "Avg All Delay (s/pax)",
    "stats_Objective_PaxPerDelayHr": "Objective (pax/delay-hr)",
    "stats_TSP_Detections":       "TSP Detections",
    "stats_TSP_Extensions":       "TSP Extensions",
    "stats_TSP_Insertions":       "TSP Insertions",
    "stats_TSP_Detected_NoAction":"TSP No-Action",
    "stats_TotalPassDelay_hrs":   "Total Pax Delay (hrs)",
    "stats_BusTotalTT_hrs":       "Bus Total TT (hrs)",
    "stats_Net_AvgSpeed_kmh":     "Network Avg Speed (km/h)",
}

def main():
    if not os.path.exists(CSV):
        print(f"[summarise] {CSV} not found — run batch_runner first.")
        return

    df = pd.read_csv(CSV)

    # Filter successful runs only
    if "run_success" in df.columns:
        n_total = len(df)
        df = df[df["run_success"] == True]
        n_ok = len(df)
        if n_ok < n_total:
            print(f"[summarise] {n_total - n_ok} failed run(s) excluded.\n")

    exp_col  = "run_experiment"
    seed_col = "run_seed"

    exps   = df[exp_col].unique().tolist()
    seeds  = sorted(df[seed_col].unique().tolist())
    n_seed = len(seeds)

    print(f"{'='*72}")
    print(f"  Batch results summary")
    print(f"  CSV        : {CSV}")
    print(f"  Experiments: {exps}")
    print(f"  Seeds ({n_seed}): {seeds}")
    print(f"{'='*72}\n")

    # ── Per-metric table: mean ± std across seeds ─────────────────────────────
    rows = []
    for metric, label in METRICS.items():
        if metric not in df.columns:
            continue
        row = {"Metric": label}
        for exp in exps:
            vals = df[df[exp_col] == exp][metric].dropna()
            if len(vals) == 0:
                row[exp] = "–"
            elif len(vals) == 1:
                row[exp] = f"{vals.iloc[0]:.2f}"
            else:
                row[exp] = f"{vals.mean():.2f} ± {vals.std():.2f}"
        rows.append(row)

    summary = pd.DataFrame(rows).set_index("Metric")
    print(summary.to_string())
    print()

    # ── Improvement vs NO_TSP baseline ────────────────────────────────────────
    if "NO_TSP" in exps:
        print(f"{'─'*72}")
        print("  Improvement vs NO_TSP baseline (mean, lower delay = positive %)")
        print(f"{'─'*72}")
        delay_metrics = {
            "stats_AvgBusPassDelay_s": "Avg Bus Delay",
            "stats_AvgPassDelay_s":    "Avg All Delay",
            "stats_TotalPassDelay_hrs":"Total Pax Delay (hrs)",
        }
        base_means = {}
        for metric in delay_metrics:
            if metric not in df.columns:
                continue
            base_vals = df[df[exp_col] == "NO_TSP"][metric].dropna()
            base_means[metric] = base_vals.mean() if len(base_vals) else None

        imp_rows = []
        for exp in exps:
            if exp == "NO_TSP":
                continue
            imp_row = {"Strategy": exp}
            for metric, label in delay_metrics.items():
                if metric not in df.columns or base_means.get(metric) is None:
                    continue
                vals = df[df[exp_col] == exp][metric].dropna()
                if len(vals) == 0:
                    imp_row[label] = "–"
                else:
                    pct = (base_means[metric] - vals.mean()) / base_means[metric] * 100
                    imp_row[label] = f"{pct:+.1f}%"
            imp_rows.append(imp_row)

        if imp_rows:
            imp_df = pd.DataFrame(imp_rows).set_index("Strategy")
            print(imp_df.to_string())
            print()

    # ── Per-seed detail for key metric ───────────────────────────────────────
    print(f"{'─'*72}")
    print("  Per-seed detail: Avg Bus Passenger Delay (s/pax)")
    print(f"{'─'*72}")
    pivot_metric = "stats_AvgBusPassDelay_s"
    if pivot_metric in df.columns:
        pivot = df.pivot_table(
            index=seed_col, columns=exp_col, values=pivot_metric, aggfunc="mean"
        )
        # Add mean row
        mean_row = pivot.mean().rename("MEAN")
        pivot = pd.concat([pivot, mean_row.to_frame().T])
        print(pivot.round(2).to_string())
        print()

    # ── Save CSV summary ──────────────────────────────────────────────────────
    out = os.path.join(_HERE, "batch_summary.csv")
    df.groupby(exp_col)[list(METRICS.keys() & set(df.columns))].agg(["mean", "std"]).to_csv(out)
    print(f"[summarise] Full summary saved → {out}")


if __name__ == "__main__":
    main()
