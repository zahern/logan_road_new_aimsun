"""reconcile_metrics.py -- put Aimsun and SUMO results on ONE comparable metric.

WHY
---
Both pipelines compute ``objective = passengers / (pax_delay_s / 3600)``, but the
NUMERATOR is not the same quantity:

  Aimsun  ``stats_PaxEquivPassages``      -- a passenger is counted once per
                                             junction traversed (KG: ~100,200 for
                                             a 1.25 h run)
  SUMO    ``total_passengers``            -- distinct passengers (KG: ~8,100)

so Aimsun reports ~145 "pax per delay-hour" and SUMO ~6.4 for the same kind of
traffic, and a 20 % change in one is not the same 20 % in the other.

THE COMMON METRIC
-----------------
Passenger-delay HOURS PER SIMULATION HOUR (lower is better). It has no passenger
denominator, so it is immune to the passages-vs-passengers difference:

  Aimsun  stats_AvgTotalPassDelay_pax_h_per_sim_h
  SUMO    avg_total_pass_delay_per_hr

Measured on the KG ladders the two agree to a stable ratio of 1.67-1.81 for every
arm whose definition matches, which is what makes the comparison legitimate. An
arm whose ratio breaks that band is a DEFINITION mismatch, not a result -- that is
exactly what GAME_BUS showed (ratio 1.02) while its SUMO arm was still missing the
corridor/CTM/self-gate keys.

USAGE
-----
    python reconcile_metrics.py --aimsun paper_ladder_8arm_kg.csv \\
                                --sumo Z:\\tsp\\sumo_hpc\\sumo_bridge\\sweep_paper_ladder_kg_fixed.csv
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    import pandas as pd
except Exception:                                    # pragma: no cover
    sys.exit("pandas is required for reconcile_metrics.py")

# canonical short name -> (Aimsun experiment name, SUMO arm name)
ARM_MAP = {
    "NO_TSP":      ("NO_TSP", "CHAMP_NO_TSP"),
    "AIMSUN_DSW":  ("CHAMP_ADAPTIVE_AIMSUN_DSW", "CHAMP_ADAPTIVE_AIMSUN_DSW"),
    "MARL_BUS":    ("CHAMP_ADAPTIVE_DSW_MARL_BUS", "CHAMP_ADAPTIVE_DSW_MARL_BUS"),
    "CELLQ_GATED": ("CHAMP_ADAPTIVE_DSW_CELLQ_GATED",
                    "CHAMP_ADAPTIVE_DSW_CELLQ_GATED"),
    "GAME_BUS":    ("CHAMP_ADAPTIVE_DSW_GAME_BUS", "CHAMP_ADAPTIVE_DSW_GAME_BUS"),
    "GAME_COOP":   ("CHAMP_ADAPTIVE_DSW_GAME_COOP", "CHAMP_ADAPTIVE_DSW_GAME_COOP"),
}

AIM_METRIC = "stats_AvgTotalPassDelay_pax_h_per_sim_h"
SUMO_METRIC = "avg_total_pass_delay_per_hr"
# how far an arm's Aimsun/SUMO ratio may sit from the modal ratio before we call
# it a definition mismatch rather than a result
RATIO_TOL = 0.15


def _load(path):
    if not os.path.isfile(path):
        sys.exit("missing file: %s" % path)
    return pd.read_csv(path)


def _aimsun_means(d):
    d = d.copy()
    ok = d.get("run_success")
    if ok is not None:
        d = d[ok.astype(str).str.lower().isin(("true", "1"))]
    if AIM_METRIC not in d.columns:
        # legacy files: derive from total delay over simulation duration
        d[AIM_METRIC] = (d["stats_TotalPassDelay_hrs"]
                         / d["stats_SimDuration_hrs"].replace(0, 1.25))
    return d.groupby("run_experiment")[AIM_METRIC].mean()


def _sumo_means(d):
    d = d.copy()
    if "phase" in d.columns:
        d = d[d["phase"] == "eval"]
    if "ok" in d.columns:
        d = d[d["ok"].astype(str).str.lower().isin(("true", "1"))]
    return d.groupby("arm")[SUMO_METRIC].mean()


def build_table(aimsun_csv, sumo_csv):
    a = _aimsun_means(_load(aimsun_csv))
    s = _sumo_means(_load(sumo_csv))
    rows = []
    for short, (an, sn) in ARM_MAP.items():
        if an not in a.index or sn not in s.index:
            continue
        rows.append({"arm": short, "aimsun": float(a[an]), "sumo": float(s[sn])})
    if not rows:
        sys.exit("no overlapping arms between the two files")
    base = next((r for r in rows if r["arm"] == "NO_TSP"), None)
    for r in rows:
        r["ratio"] = r["sumo"] / r["aimsun"] if r["aimsun"] else float("nan")
        r["aim_pct"] = ((r["aimsun"] / base["aimsun"] - 1) * 100
                        if base and base["aimsun"] else 0.0)
        r["sumo_pct"] = ((r["sumo"] / base["sumo"] - 1) * 100
                         if base and base["sumo"] else 0.0)
        r["sign_agree"] = (r["aim_pct"] < 0) == (r["sumo_pct"] < 0)
    # modal ratio = median over the NON-baseline arms
    others = sorted(r["ratio"] for r in rows if r["arm"] != "NO_TSP")
    modal = others[len(others) // 2] if others else float("nan")
    for r in rows:
        r["definition_ok"] = (abs(r["ratio"] - modal) / modal <= RATIO_TOL
                              if modal else True)
    return rows, modal


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--aimsun", required=True)
    ap.add_argument("--sumo", required=True)
    ap.add_argument("--tol", type=float, default=RATIO_TOL)
    args = ap.parse_args(argv)

    rows, modal = build_table(args.aimsun, args.sumo)
    print("common metric: passenger-delay hours per simulation hour (lower better)")
    print("Aimsun %-38s SUMO %s" % (AIM_METRIC, SUMO_METRIC))
    print()
    print("%-12s %12s %12s %8s %10s %10s  %s"
          % ("arm", "Aimsun", "SUMO", "ratio", "Aimsun%", "SUMO%", "verdict"))
    bad = []
    for r in rows:
        verdict = "ok"
        if not r["definition_ok"]:
            verdict = "DEFINITION MISMATCH (ratio %.2f vs modal %.2f)" % (
                r["ratio"], modal)
            bad.append(r["arm"])
        elif not r["sign_agree"]:
            verdict = "SIGN DISAGREEMENT"
            bad.append(r["arm"])
        print("%-12s %12.1f %12.1f %8.2f %+9.1f%% %+9.1f%%  %s"
              % (r["arm"], r["aimsun"], r["sumo"], r["ratio"],
                 r["aim_pct"], r["sumo_pct"], verdict))
    print()
    print("modal Aimsun/SUMO level ratio: %.2f  (band +/-%.0f%%)"
          % (modal, args.tol * 100))
    if bad:
        print("\nNOT COMPARABLE for: %s" % ", ".join(bad))
        print("Fix the arm definition (see sweep_arms.py _AIMSUN_PARITY) and "
              "re-run before quoting a cross-simulator result.")
        return 1
    print("\nAll overlapping arms are definition-consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
