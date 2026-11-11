"""Pair the SUMO Logan seed-check against the Aimsun Logan ladder on pax-hours.

Deliberately reports pax-delay hours per simulation hour, not the objective:
the two platforms count the passenger numerator differently, whereas pax-delay
hours carry no passenger denominator and are comparable (see PORT_NOTES and
compare_game_solution.py).

Pax-hours is also immune to the seed-300 passage correction -- that row's
delay-hours were never touched -- so this pairing needs no imputation.

    python pair_hpc_logan.py          # write + print whatever has landed
"""
import csv
import glob
import os
import statistics as st

SUMO_PARTS = r"Z:\tsp\sumo_hpc\parts"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# The 25-row ladder (5 arms x 5 seeds); the _corrected.csv beside this script is
# a 12-row stub left over from the first pass, so it is only a fallback.
AIMSUN = os.path.join(ROOT, "game_ladder_logan_lightsim_20261109_124707.csv")
AIMSUN_FALLBACK = os.path.join(HERE, "game_ladder_logan_lightsim_20261109_124707_corrected.csv")
ARMS = [("NO_TSP", "CHAMP_NO_TSP"),
        ("NASH_CTM2_SPILL2", "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2"),
        ("NASH_CTM2_SPILL2_LIGHTSIM",
         "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM"),
        ("UTIL_CTM2_SPILL2", "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2"),
        ("UTIL_CTM2_SPILL2_LIGHTSIM",
         "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_LIGHTSIM")]
SEEDS = [300, 400, 500, 600, 700]
SIM_H = 1.25


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _aimsun_path():
    return AIMSUN if os.path.exists(AIMSUN) else AIMSUN_FALLBACK


def load_aimsun():
    out = {}
    with open(_aimsun_path(), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            seed = int(_f(r.get("run_seed")))
            arm = r.get("run_experiment", "")
            out[(arm, seed)] = dict(
                paxh_col=_f(r.get("stats_AvgTotalPassDelay_pax_h_per_sim_h")),
                delay_hrs=_f(r.get("stats_TotalPassDelay_hrs")))
    return out


def load_sumo():
    out = {}
    rows = sorted(glob.glob(os.path.join(SUMO_PARTS, "ladder_*_eval*.csv")))
    for p in rows:
        try:
            with open(p, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if str(r.get("phase", "eval")).lower() != "eval":
                        continue
                    if str(r.get("ok", "")).lower() not in ("true", "1"):
                        continue
                    out[(r.get("arm", ""), int(_f(r.get("seed"))))] = {
                        k: r[k] for k in r}
        except (OSError, ValueError):
            continue
    return out, rows


def main():
    A, (S, files) = load_aimsun(), load_sumo()
    print("Aimsun ladder: %s" % _aimsun_path())
    print("SUMO ladder files: %d" % len(files))
    if not files:
        print("no SUMO rows yet -- nothing to pair")
        return 1
    if S:
        print("SUMO row columns: %s" % ", ".join(sorted(next(iter(S.values())))))

    print("\nper-seed pax-hours (pax-delay h per sim hour; lower is better)")
    hdr = ("  %-18s %5s %10s %8s %10s %8s %8s"
           % ("arm", "seed", "A_paxh", "A_d%", "S_paxh", "S_d%", "S/A"))
    print(hdr)
    recs = []
    for label, arm in ARMS:
        for s in SEEDS:
            a = A.get((arm, s))
            sv = S.get((arm, s))
            if a is None or sv is None:
                continue
            a_paxh = a["paxh_col"]
            a_derived = a["delay_hrs"] / SIM_H
            s_paxh = _f(sv.get("avg_total_pass_delay_per_hr"))
            base_a = A[("NO_TSP", s)]["paxh_col"]
            base_s = _f(S.get(("CHAMP_NO_TSP", s), {}).get("avg_total_pass_delay_per_hr"))
            recs.append(dict(label=label, seed=s, a_paxh=a_paxh, a_derived=a_derived,
                             s_paxh=s_paxh, base_a=base_a, base_s=base_s,
                             a_d=(a_paxh - base_a) / base_a * 100 if base_a else float("nan"),
                             s_d=(s_paxh - base_s) / base_s * 100 if base_s else float("nan"),
                             ratio=s_paxh / base_a if base_a else float("nan")))
    for r in recs:
        print("  %-18s %5d %10.1f %+7.1f%% %10.1f %+7.1f%% %8.3f"
              % (r["label"], r["seed"], r["a_paxh"], r["a_d"], r["s_paxh"],
                 r["s_d"], r["ratio"]))

    print("\n  NOTE A_paxh is the pipeline column; A_derived = delay_hrs/%.2f here:"
          % SIM_H)
    for r in recs[:3]:
        print("    seed %d: column %.1f | delay_hrs/1.25 %.1f"
              % (r["seed"], r["a_paxh"], r["a_derived"]))

    print("\nper-arm means over paired seeds")
    print("  %-18s %3s %10s %10s %8s %10s" % ("arm", "n", "A d%", "S d%", "S/A", "sign"))
    for label, arm in ARMS:
        rs = [r for r in recs if r["label"] == label]
        if not rs:
            continue
        pairs = [r for r in rs if r["a_d"] == r["a_d"] and r["s_d"] == r["s_d"]]
        if not pairs:
            continue
        agree = sum(1 for r in pairs
                    if (r["a_d"] == 0) == (r["s_d"] == 0) and
                    (r["a_d"] >= 0) == (r["s_d"] >= 0))
        print("  %-18s %3d %+9.1f%% %+9.1f%% %8.3f %d/%d"
              % (label, len(pairs), st.mean([r["a_d"] for r in pairs]),
                 st.mean([r["s_d"] for r in pairs]),
                 st.mean([r["ratio"] for r in pairs]), agree, len(pairs)))
    print("\nsign = seeds where both platforms move the same way vs their own NO_TSP")

    out = os.path.join(HERE, "hpc_vs_aimsun_logan_paxh.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["label", "seed", "a_paxh", "a_d",
                                           "s_paxh", "s_d", "ratio"])
        w.writeheader()
        w.writerows([{k: r[k] for k in w.fieldnames} for r in recs])
    print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
