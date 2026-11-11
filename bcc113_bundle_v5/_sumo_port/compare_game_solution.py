#!/usr/bin/env python3
"""compare_game_solution.py -- Aimsun vs SUMO, same game, same seed.

Pairs the Aimsun GAME_SOLUTION ladder (local `kg/results/<arm>_seed<seed>_*`)
with the SUMO ladder (`Z:/tsp/sumo_hpc/parts/gamesol_*_eval<seed>.csv`) and
prints, per arm and seed, each platform's result against its OWN NO_TSP run on
that seed.

Two metrics, deliberately:

  obj      the pipeline's own objective (passengers / delay-hour). Aimsun's
           numerator counts passenger-junction passages, SUMO's counts distinct
           passengers, so the two COLUMNS are not comparable to each other --
           only each platform's % against its own baseline is. That is why the
           table shows dA% and dS% rather than an obj ratio.

  paxh     passenger-delay hours per simulation hour (lower is better). No
           passenger denominator, so the Aimsun and SUMO values ARE comparable
           and a stable ratio is the signature of a matched arm; a ratio far
           outside the band is a definition mismatch, not a result
           (see reconcile_metrics.py).

    python compare_game_solution.py                    # kg, seeds 300..700
    python compare_game_solution.py --seeds 300
    python compare_game_solution.py --csv out.csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SUMO = r"Z:\tsp\sumo_hpc"

ARMS = [
    # The non-game half of the Aimsun game-ladder snippet (qb_gameladder_gen.sh
    # emits the SUMO side of these on seeds 300-700).
    ("AIMSUN_DSW", "CHAMP_ADAPTIVE_AIMSUN_DSW"),
    ("MARL_BUS", "CHAMP_ADAPTIVE_DSW_MARL_BUS"),
    ("CELLQ_GATED", "CHAMP_ADAPTIVE_DSW_CELLQ_GATED"),
    ("GAME_BUS", "CHAMP_ADAPTIVE_DSW_GAME_BUS"),
    ("GAME_COOP", "CHAMP_ADAPTIVE_DSW_GAME_COOP"),
    ("GAME_SOL_NASH", "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH"),
    ("GAME_SOL_UTIL", "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL"),
    ("GAME_SOL_NWELF", "CHAMP_ADAPTIVE_DSW_GAME_SOL_NWELF"),
    ("GAME_SOL_EGAL", "CHAMP_ADAPTIVE_DSW_GAME_SOL_EGAL"),
    ("GAME_SOL_KS", "CHAMP_ADAPTIVE_DSW_GAME_SOL_KS"),
    ("GAME_SOL_STACKBUS", "CHAMP_ADAPTIVE_DSW_GAME_SOL_STACKBUS"),
    ("GAME_SOL_STACKCAR", "CHAMP_ADAPTIVE_DSW_GAME_SOL_STACKCAR"),
    ("GAME_SOL_NONCOOP", "CHAMP_ADAPTIVE_DSW_GAME_SOL_NONCOOP"),
    # The CTM2 ladder (2026-11-06): these are the arms the Aimsun game ladder
    # actually ran on seeds 300-700, so they are the ones with a real pairing.
    ("GAME_SOL_NULL_CTM2", "CHAMP_ADAPTIVE_DSW_GAME_SOL_NULL_CTM2"),
    ("GAME_SOL_NASH_CTM2", "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2"),
    ("GAME_SOL_NASH_CTM2_SPILL", "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL"),
    ("GAME_SOL_UTIL_CTM2_SPILL", "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL"),
    ("GAME_SOL_NASH_CTM2_SPILL2", "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2"),
    ("GAME_SOL_UTIL_CTM2_SPILL2", "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2"),
]

# Aimsun's simulation_results.csv carries these WITHOUT the stats_ prefix used
# elsewhere in the pipeline; accept both so a rename cannot silently read nan.
AIM_OBJ = ("Objective_PaxPerDelayHr", "stats_Objective_PaxPerDelayHr")
AIM_PAXH = ("AvgTotalPassDelay_pax_h_per_sim_h",
            "stats_AvgTotalPassDelay_pax_h_per_sim_h")
AIM_LOOPS = ("N_LoopCompletions", "stats_N_LoopCompletions")
AIM_LTT = ("MeanLoopTT_s", "stats_MeanLoopTT_s")
SUMO_OBJ = ("obj_pax_per_delay_hr",)
SUMO_PAXH = ("avg_total_pass_delay_per_hr",)


def _f(row, keys):
    for k in keys:
        v = (row or {}).get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except ValueError:
                continue
    return float("nan")


def aimsun_row(arm, seed, corridor="kg"):
    ds = sorted(glob.glob(os.path.join(ROOT, corridor, "results",
                                       "%s_seed%s_*" % (arm, seed))),
                key=os.path.getmtime)
    for d in reversed(ds):
        p = os.path.join(d, "simulation_results.csv")
        if os.path.isfile(p):
            try:
                rows = [r for r in csv.DictReader(open(p, encoding="utf-8-sig"))
                        if any(v not in (None, "") for v in r.values())]
                if rows:
                    return rows[-1]
            except Exception:
                continue
    return None


def sumo_rows(corridor="kg"):
    # ladder_<SHORT>_eval<SEED>.csv comes from qb_gameladder_gen.sh (the port of
    # the 11-arm Aimsun game ladder); gamesol_* from qb_gamesol_gen.sh.
    pats = [os.path.join(SUMO, "parts", "ladder_*_eval*.csv"),
            os.path.join(SUMO, "parts", "gamesol_*_eval*.csv"),
            os.path.join(SUMO, "gamesol_*.csv")]
    out = {}
    for p in sorted(sum((glob.glob(x) for x in pats), [])):
        try:
            for r in csv.DictReader(open(p, encoding="utf-8")):
                if str(r.get("phase", "eval")).lower() != "eval":
                    continue
                if str(r.get("ok", "")).lower() not in ("true", "1"):
                    continue
                out[(r.get("arm", ""), str(r.get("seed", "")))] = r
        except Exception:
            continue
    return out


def pct(v, ref):
    if not (v == v and ref == ref) or ref == 0:
        return float("nan")
    return (v - ref) / ref * 100.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corridor", default="kg")
    ap.add_argument("--seeds", default="300,400,500,600,700")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--src", default="aimsun", choices=["aimsun", "sumo"],
                    help="which platform's obj to show in the obj columns")
    a = ap.parse_args()
    seeds = [s.strip() for s in a.seeds.split(",") if s.strip()]

    S = sumo_rows(a.corridor)

    def base_of(seed):
        ao = aimsun_row("NO_TSP", seed, a.corridor)
        so = S.get(("CHAMP_NO_TSP", seed)) or S.get(("NO_TSP", seed))
        return (_f(ao, AIM_OBJ), _f(ao, AIM_PAXH),
                _f(so, SUMO_OBJ), _f(so, SUMO_PAXH))

    b = {s: base_of(s) for s in seeds}
    print("NO_TSP baseline (own platform, own seed)")
    print("  %-5s %12s %12s %12s %12s" % ("seed", "A_obj", "A_paxh", "S_obj", "S_paxh"))
    for s in seeds:
        print("  %-5s %12.3f %12.2f %12.3f %12.2f" % (s, *b[s]))
    print()

    hdr = ("%-16s %-5s | %10s %8s | %10s %8s | %8s" %
           ("arm", "seed", "A_obj", "dA%", "S_obj", "dS%", "S/A paxh"))
    print(hdr)
    print("-" * len(hdr))
    out_rows = []
    for label, arm in ARMS:
        for s in seeds:
            ao = aimsun_row(arm, s, a.corridor)
            so = S.get((arm, s))
            av, ap = _f(ao, AIM_OBJ), _f(ao, AIM_PAXH)
            sv, sp = _f(so, SUMO_OBJ), _f(so, SUMO_PAXH)
            ba, bap, bsv, bsp = b[s]
            ratio = (sp / bsp) if (bsp == bsp and bsp) else float("nan")
            print("%-16s %-5s | %10.3f %+7.1f%% | %10.3f %+7.1f%% | %8.2f | %s %s"
                  % (label, s, av, pct(av, ba), sv, pct(sv, bsv), ratio,
                     _f(ao, AIM_LOOPS), _f(ao, AIM_LTT)))
            out_rows.append(dict(arm=label, seed=s, aimsun_obj=av,
                                 aimsun_delta_pct=pct(av, ba),
                                 sumo_obj=sv, sumo_delta_pct=pct(sv, bsv),
                                 aimsun_paxh=ap, sumo_paxh=sp,
                                 sumo_paxh_ratio=ratio))
    print()

    # per-arm means over the seeds that have both sides
    print("per-arm means (seeds with both platforms present)")
    print("  %-16s %3s %9s %9s %9s" % ("arm", "n", "A d%", "S d%", "S/A"))
    for label, arm in ARMS:
        rs = [r for r in out_rows if r["arm"] == label]
        both = [r for r in rs if r["aimsun_delta_pct"] == r["aimsun_delta_pct"]
                and r["sumo_delta_pct"] == r["sumo_delta_pct"]]
        if not both:
            print("  %-16s  -       (no paired seeds yet)" % label)
            continue
        rr = [r["sumo_paxh_ratio"] for r in both if r["sumo_paxh_ratio"] == r["sumo_paxh_ratio"]]
        print("  %-16s %3d %+8.1f%% %+8.1f%% %9.2f"
              % (label, len(both),
                 st.mean([r["aimsun_delta_pct"] for r in both]),
                 st.mean([r["sumo_delta_pct"] for r in both]),
                 st.mean(rr) if rr else float("nan")))
    print()
    print("dA%/dS% = arm vs that platform's own NO_TSP on the SAME seed")
    print("S/A paxh = SUMO pax-delay-hr/sim-hr over the Aimsun NO_TSP value:")
    print("           ~1.7-1.8 is the matched-arm band (reconcile_metrics.py).")

    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
            w.writeheader()
            w.writerows(out_rows)
        print("\nwrote %s" % a.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
