"""
SA-Only Baseline Experiment
============================
SA applied to original census microdata (no GAN) to isolate the GAN contribution.
Reviewer 2 (P31): required to complete Table 2.

All paths come from config.py.  Run from synth_pop/:
    python sa_only_baseline.py [--zones 301011001 ...] [--max-iter 1000]
"""

import argparse, os, random, math, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config

# Add sa_run_again_n to path so we can import SA_2_level helpers
sys.path.insert(0, config.SA_DIR)

import pandas as pd
from SA_2_level import (
    build_control_dicts,
    calculate_total_rssz,
    calculate_total_rssz_table,
    calculate_total_marginals,
    adjust_with_tolerance,
    setup_logger,
)
from CensusRecordImporter import CensusControlTable
from helper_functions import Helper

OUTPUT_DIR = config.SA_ONLY_RESULTS_DIR
LOG_DIR    = os.path.join(OUTPUT_DIR, "logs")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)


def load_control_tables():
    ind, hh = {}, {}
    for fname in os.listdir(config.SA_CONTROL_IND):
        if fname.endswith(".csv"):
            key = fname.replace(".csv", "").lower()
            ct = CensusControlTable(os.path.join(config.SA_CONTROL_IND, fname))
            ct.validate_and_clean()
            ind[key] = ct
    for fname in os.listdir(config.SA_CONTROL_HH):
        if fname.endswith(".csv"):
            key = fname.replace(".csv", "").lower()
            ct = CensusControlTable(os.path.join(config.SA_CONTROL_HH, fname))
            ct.validate_and_clean()
            hh[key] = ct
    return ind, hh


def run_sa_zone(pop, ind_tables, hh_tables, zone, max_iter, initial_temp, cooling_rate):
    log_file = os.path.join(LOG_DIR, f"sa_only_{zone}.log")
    setup_logger(log_file)
    ind_dicts = build_control_dicts(ind_tables, zone)
    hh_dicts  = build_control_dicts(hh_tables,  zone)
    if sum(1 for d in ind_dicts.values() if not d) >= 2:
        print(f"  Zone {zone}: skipped — insufficient control data")
        return None, None

    households  = pop.groupby("abshid")
    remaining   = set(pop["abshid"].unique())
    total_ind, _ = calculate_total_marginals(ind_dicts, hh_dicts)

    solution, n = [], 0
    while n < total_ind and remaining:
        hh = random.choice(list(remaining)); remaining.remove(hh)
        data = households.get_group(hh).to_dict("records")
        solution.extend(data); n += len(data)

    current_cost = calculate_total_rssz(solution, ind_dicts, hh_dicts)
    best_sol, best_cost = list(solution), current_cost
    temp = initial_temp

    for it in range(max_iter):
        new_sol = list(solution); new_n = n
        move = random.choice(["add", "remove", "swap"])

        if move == "add" and remaining:
            hh = random.choice(list(remaining)); remaining.remove(hh)
            data = households.get_group(hh).to_dict("records")
            new_sol.extend(data); new_n += len(data)
        elif move == "remove" and new_sol:
            hh = random.choice(list({r["abshid"] for r in new_sol}))
            new_sol = [r for r in new_sol if r["abshid"] != hh]
            remaining.add(hh); new_n = len(new_sol)
        elif move == "swap" and new_sol and remaining:
            hh_out = random.choice(list({r["abshid"] for r in new_sol}))
            new_sol = [r for r in new_sol if r["abshid"] != hh_out]
            remaining.add(hh_out)
            hh_in = random.choice(list(remaining)); remaining.remove(hh_in)
            new_sol.extend(households.get_group(hh_in).to_dict("records"))
            new_n = len(new_sol)

        new_sol, new_n = adjust_with_tolerance(
            new_sol, new_n, total_ind, config.SA_TOLERANCE, households, remaining)

        new_cost = calculate_total_rssz(new_sol, ind_dicts, hh_dicts)
        diff = new_cost - current_cost
        if diff < 0 or random.random() < math.exp(-diff / max(temp, 1e-10)):
            solution, current_cost, n = new_sol, new_cost, new_n
            if current_cost < best_cost:
                best_sol, best_cost = list(solution), current_cost

        temp *= cooling_rate
        if (it + 1) % 200 == 0:
            print(f"  Zone {zone}: iter {it+1}/{max_iter}  RSSZ={current_cost:.4f}  best={best_cost:.4f}")

    _, per_table = calculate_total_rssz_table(best_sol, ind_dicts, hh_dicts)
    return pd.DataFrame(best_sol), {"zone": zone, "rssz_total": best_cost, **per_table}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--zones",        nargs="*", type=str)
    p.add_argument("--max-iter",     type=int,   default=config.SA_MAX_ITER)
    p.add_argument("--initial-temp", type=float, default=config.SA_INITIAL_TEMP)
    p.add_argument("--cooling-rate", type=float, default=config.SA_COOLING_RATE)
    args = p.parse_args()

    print(f"Loading census microdata from: {config.CENSUS_MICRODATA}")
    helper = Helper()
    microdata = helper.clean_my_datagan(config.CENSUS_MICRODATA)
    print(f"  Records: {len(microdata):,}")

    ind_tables, hh_tables = load_control_tables()
    print(f"  Individual control tables: {list(ind_tables.keys())}")
    print(f"  Household  control tables: {list(hh_tables.keys())}")

    if args.zones:
        zones = args.zones
    else:
        zones = next(iter(ind_tables.values())).data["sa2"].dropna().unique().tolist()
    print(f"\nProcessing {len(zones)} zones")

    all_rssz = []
    for zone in zones:
        print(f"\nZone {zone}")
        zone_pop = microdata[microdata.get("sa2", pd.Series(dtype=str)) == str(zone)]
        if zone_pop.empty:
            zone_pop = microdata[microdata.get("regucp", pd.Series(dtype=str)) == str(zone)]
        if zone_pop.empty:
            print(f"  No microdata for zone {zone} — skipping")
            continue

        result_df, rssz_info = run_sa_zone(
            zone_pop, ind_tables, hh_tables, zone,
            args.max_iter, args.initial_temp, args.cooling_rate)
        if result_df is not None:
            result_df.to_csv(os.path.join(OUTPUT_DIR, f"zone_{zone}.csv"), index=False)
            all_rssz.append(rssz_info)

    if all_rssz:
        summary = pd.DataFrame(all_rssz)
        out_path = os.path.join(OUTPUT_DIR, "sa_only_rssz_summary.csv")
        summary.to_csv(out_path, index=False)
        vals = summary["rssz_total"]
        print(f"\n{'='*60}\nSA-Only RSSZ Summary\n{'='*60}")
        print(f"  Zones : {len(vals)}")
        print(f"  Mean  : {vals.mean():.4f}")
        print(f"  Median: {vals.median():.4f}")
        print(f"  Min   : {vals.min():.4f}")
        print(f"  Max   : {vals.max():.4f}")
        print(f"  Std   : {vals.std():.4f}")
        print(f"\nSaved: {out_path}")
        print(
            "\n[CHECK] Add the SA-Only row to Table 2 of the paper.\n"
            "If SA-Only RSSZ ≈ SA-GAN RSSZ, most improvement comes from SA, not the GAN.\n"
            "If SA-Only RSSZ >> SA-GAN RSSZ, the GAN's richer microdata pool is the key driver."
        )


if __name__ == "__main__":
    main()
