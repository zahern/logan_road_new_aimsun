"""Inspect the Aimsun 5-seed suite and the SUMO smoke runs.

Explains (a) which arms actually ran, (b) why the TSP/DSW variants lost to
NO_TSP, and (c) that the Flow arm (CHAMP_FIXED_FLOW_RL) has never run.

    python inspect_runs.py
"""
import glob
import os
import re

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.dirname(HERE)
AIMSUN = os.path.join(BUNDLE, "paxwin_adaptive_dsw_5seeds.csv")
SUMO_VAR = r"Z:\tsp\sumo_hpc\sumo_bridge\smoke_variants.csv"
SUMO_DSW = r"Z:\tsp\sumo_hpc\sumo_bridge\smoke_dsw.csv"
PLAN_LOGS = os.path.join(BUNDLE, "kg", "logs")


def _pct(x, b):
    return (100.0 * (x - b) / b) if b else 0.0


def aimsun():
    print("=" * 84)
    print("AIMSUN 5-SEED SUITE:", AIMSUN)
    print("=" * 84)
    if not os.path.isfile(AIMSUN):
        print("missing"); return
    d = pd.read_csv(AIMSUN, encoding="utf-8-sig", engine="python")
    print("arms:", d["run_experiment"].unique().tolist())
    has_flow = any("FLOW" in str(x).upper() for x in d["run_experiment"].unique())
    print("Flow arm present:", has_flow)
    base = d[d.run_experiment == "NO_TSP"].set_index("run_seed")
    print("\n%-30s %8s %9s %10s %10s %10s" %
          ("arm", "obj", "vs NO_TSP", "main h", "side h", "GE/INS/ER"))
    for arm, g in d.groupby("run_experiment"):
        if arm == "NO_TSP":
            continue
        x = g.set_index("run_seed")
        seeds = sorted(set(base.index) & set(x.index))
        obj = x.loc[seeds, "stats_Objective_PaxPerDelayHr"].mean()
        rel = _pct(obj, base.loc[seeds, "stats_Objective_PaxPerDelayHr"].mean())
        main = x.loc[seeds, "stats_MainPassDelay_hrs"].mean()
        side = x.loc[seeds, "stats_SidePassDelay_hrs"].mean()
        ge = x.loc[seeds, "stats_TSP_Extensions"].mean()
        ins = x.loc[seeds, "stats_TSP_Insertions"].mean()
        er = x.loc[seeds, "stats_TSP_EarlyRed"].mean()
        print("%-30s %8.2f %+8.1f%% %10.1f %10.1f %6.1f/%4.1f/%4.1f" %
              (arm, obj, rel, main, side, ge, ins, er))
    print("\nReading: the plan-only DSW/H10/H20 beat NO_TSP; the _TSP overlay")
    print("(GLOBAL_REWARD/NASH/SCATS_BUS_PRIORITY + JIT/recall) adds 150-230 h")
    print("of MAIN-corridor delay while side delay stays flat.")


def cycle_evidence():
    print("\n" + "=" * 84)
    print("AIMSUN PLAN-EVOLUTION: cycle inflation under the TSP overlay")
    print("=" * 84)
    base = sorted(glob.glob(os.path.join(
        PLAN_LOGS, "plan_evolution_CHAMP_ADAPTIVE_AIMSUN_DSW_20261023_15*.csv")))
    tsp = sorted(glob.glob(os.path.join(
        PLAN_LOGS, "plan_evolution_CHAMP_ADAPTIVE_DSW_TSP_*.csv")))
    if not base or not tsp:
        print("plan_evolution CSVs not found"); return
    for b, t in zip(base[-5:], tsp[-5:]):
        bd = pd.read_csv(b, encoding="utf-8-sig", engine="python")
        td = pd.read_csv(t, encoding="utf-8-sig", engine="python")
        bc = bd.groupby("junction_id")["final_cycle_s"].first().mean()
        tc = td.groupby("junction_id")["final_cycle_s"].first().mean()
        print("%-42s cycle base=%6.1f  tsp=%6.1f  (%+5.1f s)" %
              (os.path.basename(t)[-14:-4], bc, tc, tc - bc))
    print("\nA wave commissioned for ~120 s is desynchronised by a 124-139 s")
    print("cycle: extra main green is not where the platoon is.")


def sumo():
    print("\n" + "=" * 84)
    print("SUMO SMOKE (seed 300, 900 s)")
    print("=" * 84)
    for label, path in (("variants", SUMO_VAR), ("dsw", SUMO_DSW)):
        if not os.path.isfile(path):
            print(label, "missing"); continue
        d = pd.read_csv(path, encoding="utf-8-sig", engine="python")
        cols = [c for c in ("arm", "obj_pax_per_delay_hr", "main_pass_delay_hrs",
                            "side_pass_delay_hrs", "truth_delay_hrs",
                            "n_tsp_extensions", "n_tsp_insertions",
                            "n_tsp_early_red") if c in d.columns]
        print("\n---", label, "---")
        print(d[cols].to_string(index=False))
    print("\nReading: SUMO DSW fires TSP insertions (the Aimsun plan-only DSW")
    print("fires none) and the port's plan-apply shim does not preserve offsets.")
    print("With a 300 s warm-up in a 900 s run it only adapts ~5 times; CTM/MARL")
    print("still beat NO_TSP, so the corridor is responsive and the DSW port is")
    print("the outlier.")


def flow_arm():
    print("\n" + "=" * 84)
    print("FLOW ARM")
    print("=" * 84)
    ev = os.path.join(HERE, "flow_arm_eval.csv")
    if os.path.isfile(ev):
        d = pd.read_csv(ev, encoding="utf-8-sig", engine="python")
        print(d.to_string(index=False))
        print("\nThe exported example rules only fire ER (no GE/INS); they create")
        print("many unfinished trips, so use the completed-trip objective above,")
        print("not the earlier completed-only ratio.")
    else:
        print("Flow arm not run in SUMO yet. Run:")
        print("  python flow_marl/run_flow_arm.py --horizon 4500 --seed 300")
    print("\nAimsun CHAMP_FIXED_FLOW_RL still has no rows in the 5-seed CSV.")
    print("To test it there: ARM_SUITE_ARMS=CHAMP_FIXED_FLOW_RL,... then run")
    print("run_aimsun_arm_suite_5seeds.py.")



def first_seed_artifact():
    """The first NO_TSP run under-resolves the main sections (2 vs 3)."""
    print("\n" + "=" * 84)
    print("FIRST-RUN ARTIFACT (seed 300)")
    print("=" * 84)
    d = pd.read_csv(AIMSUN, encoding="utf-8-sig", engine="python")
    base = d[d.run_experiment == "NO_TSP"].set_index("run_seed")
    dsw = d[d.run_experiment == "CHAMP_ADAPTIVE_AIMSUN_DSW"].set_index("run_seed")

    def per_int(arm_df, seed):
        f = os.path.join(str(arm_df.loc[seed, "stats_results_folder"]),
                         "simulation_results_per_intersection.csv")
        return pd.read_csv(f, encoding="utf-8-sig", engine="python").set_index(
            "IntersectionID") if os.path.isfile(f) else None

    a, c = per_int(base, 300), per_int(base, 400)
    if a is not None and c is not None:
        js = [1043762, 36385, 36393, 39569, 39593]
        n300 = [int(a.loc[j, "N_MainSections"]) for j in js]
        n400 = [int(c.loc[j, "N_MainSections"]) for j in js]
        print("NO_TSP seed 300 N_MainSections:", n300)
        print("NO_TSP seed 400 N_MainSections:", n400)
        print("=> the first run resolved one fewer main approach per junction,")
        print("   so its junction passenger passages are under-counted.")

    print("\nArm deltas, including vs excluding the first-run artifact:")
    for arm, g in d.groupby("run_experiment"):
        if arm == "NO_TSP":
            continue
        x = g.set_index("run_seed")["stats_Objective_PaxPerDelayHr"].astype(float)
        seeds = sorted(set(base.index) & set(x.index))
        clean = [s for s in seeds if s != 300]
        def rel(ss):
            bm = base.loc[ss, "stats_Objective_PaxPerDelayHr"].astype(float).mean()
            xm = x.loc[ss].mean()
            return 100.0 * (xm - bm) / bm if bm else 0.0
        print("  %-30s all=%+6.1f%%   excl300=%+6.1f%%" %
              (arm, rel(seeds), rel(clean)))
    print("\nUse the excl300 column. The DSW's true effect is ~+3.8%, not +8.5%.")


if __name__ == "__main__":
    aimsun()
    first_seed_artifact()
    cycle_evidence()
    sumo()
    flow_arm()
