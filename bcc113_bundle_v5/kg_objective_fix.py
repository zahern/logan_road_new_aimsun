"""Corrected objective for KG / Aimsun result CSVs.

WHY THIS EXISTS
---------------
``stats_Objective_PaxPerDelayHr`` is

    PaxEquivPassages / TotalPassDelay_hrs                       (higher = better)

``PaxEquivPassages`` is assembled in ``kg/Simulation_Stats.py``
(``add_section_delay``: ``d['bus_passages'] += bus_vehicle_count * occ``) from
``AKIEstGetParcialStatisticsSection.count``, i.e. the number of vehicles that
LEFT a section during each 1 s step, summed over every step and every junction
section.  That counter is not throughput: a vehicle that spills back and
re-crosses a section boundary is counted again, so stop-and-go traffic inflates
it.  Measured on ``gamesol_pair_kg_lightsim_20261110_095910.csv``:

    arm      PaxEquivPassages   Net_ExitCount_All   objective
    NO_TSP          82 052             150 581        117.61
    NASH           105 875             156 111        144.10   (+29 % passages, +3.7 % exits)

Flow was flat (Net_TotalFlowVeh 6854 vs 6849) and every physical metric was
worse in the TSP arm (loops -7.6 %, loop TT +4.1 %, speed -2.4 %, delay +5.3 %),
yet the legacy objective rose 22.5 %.  The numerator was counting churn.

THE FIX
-------
Use *network exits* weighted by occupancy -- vehicles that actually completed a
trip in the network, sampled once -- as the numerator:

    Objective_PaxExitsPerDelayHr = sum(Net_ExitCount_<type> * occ_<type>)
                                   / TotalPassDelay_hrs            (higher = better)

On the run above this ranks NO_TSP 211.40 > NASH/UTIL 205.78, which agrees with
every corridor metric.  ``Objective_DistinctPaxPerDelayHr`` (distinct vehicles x
occupancy) is reported as a second, stricter view.

The legacy column is kept untouched so previously published CSVs stay
comparable; rank on the corrected column from now on.

USAGE
-----
    python kg_objective_fix.py results.csv
    python kg_objective_fix.py results_*.csv --write rescored.csv
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import sys

# Fallbacks only; occupancies are derived from each run when possible.
DEF_OCC = {"bus": 40.0, "car": 1.2, "truck": 1.2}

LABEL_COLS = ("strategy", "tsp_strategy", "arm", "strategy_name", "label", "run")
BASELINE = "NO_TSP"


def _f(row, *keys):
    for k in keys:
        if k in row and row[k] not in ("", None):
            try:
                return float(row[k])
            except (TypeError, ValueError):
                continue
    return 0.0


def occupancy(row):
    """Implied per-mode occupancy: pax-equivalent passages / vehicle passages."""
    occ = {}
    for mode, pax_col, veh_col in (
        ("bus", "stats_BusPaxEquivPassages", "inter_sum_BusVehPassages"),
        ("car", "stats_CarPaxEquivPassages", "inter_sum_CarVehPassages"),
        ("truck", "stats_TruckPaxEquivPassages", "inter_sum_TruckVehPassages"),
    ):
        pax, veh = _f(row, pax_col), _f(row, veh_col)
        occ[mode] = (pax / veh) if (pax > 0 and veh > 0) else DEF_OCC[mode]
    return occ


def rescore(row, label=None):
    """Return legacy + corrected objective values for one result row."""
    occ = occupancy(row)
    delay_hrs = _f(row, "stats_TotalPassDelay_hrs")

    exits_pax = sum(_f(row, "stats_Net_ExitCount_" + col) * occ[key]
                    for key, col in (("bus", "Bus"), ("car", "Car"), ("truck", "Truck")))
    exits_all = _f(row, "stats_Net_ExitCount_All")
    if exits_pax <= 0.0 and exits_all > 0.0:           # no per-type split
        exits_pax = exits_all * occ["car"]

    distinct_pax = (_f(row, "stats_N_DistinctBuses") * occ["bus"]
                    + _f(row, "stats_N_DistinctCars") * occ["car"]
                    + _f(row, "stats_N_DistinctTrucks") * occ["truck"])

    # churn = how many times the passage counter counted each physical exit.
    churn = (_f(row, "stats_PaxEquivPassages") / exits_all) if exits_all > 0 else 0.0

    if delay_hrs <= 1e-9:
        legacy = exits_obj = distinct_obj = 0.0
    else:
        legacy = _f(row, "stats_PaxEquivPassages") / delay_hrs
        exits_obj = exits_pax / delay_hrs
        distinct_obj = distinct_pax / delay_hrs

    out = {
        "label": label or _label(row),
        "legacy": legacy,
        "exits_obj": exits_obj,
        "distinct_obj": distinct_obj,
        "exits_pax": exits_pax,
        "exits_all": exits_all,
        "passages": _f(row, "stats_PaxEquivPassages"),
        "churn": churn,
        "delay_hrs": delay_hrs,
        "loops": _f(row, "stats_N_LoopCompletions"),
        "loop_tt": _f(row, "stats_MeanLoopTT_s"),
        "speed": _f(row, "stats_Net_AvgSpeed_kmh"),
    }
    return out


def _label(row):
    if row.get("_label"):
        return str(row["_label"])
    for c in LABEL_COLS:
        if row.get(c):
            return row[c]
    return os.path.basename(str(row.get("_source", "run")))


def _detect_label_col(rows):
    """Find the arm-name column: the non-stats column holding NO_TSP/NASH/UTIL."""
    if not rows:
        return None
    for c in rows[0]:
        if c.startswith(("stats_", "inter_")) or c in ("_source", "_label"):
            continue
        if any(tag in str(r.get(c, "")).upper()
               for r in rows for tag in ("NO_TSP", "NASH", "UTIL")):
            return c
    return None


def load(paths):
    rows = []
    for pat in paths:
        for path in sorted(glob.glob(pat)):
            with open(path, newline="", encoding="utf-8-sig") as fh:
                file_rows = []
                for row in csv.DictReader(fh):
                    row["_source"] = path
                    file_rows.append(row)
            col = _detect_label_col(file_rows)
            for row in file_rows:
                row["_label"] = row.get(col, "") if col else ""
            rows.extend(file_rows)
    return rows


def _pct(v, base):
    return ("%+.1f%%" % (100.0 * (v - base) / base)) if base else "     -"


def report(rows):
    scored = [rescore(r) for r in rows]
    if not scored:
        print("no rows", file=sys.stderr)
        return scored

    base = next((s for s in scored if s["label"].strip().upper() == BASELINE), None)
    b_exit = base["exits_obj"] if base else 0.0
    b_leg = base["legacy"] if base else 0.0

    print("%-24s %10s %10s %10s %10s %8s %8s %8s"
          % ("arm", "legacy", "vs_NO_TSP", "exits", "vs_NO_TSP", "churn", "loops", "speed"))
    for s in scored:
        print("%-24s %10.2f %10s %10.2f %10s %8.2f %8.0f %8.2f"
              % (s["label"], s["legacy"], _pct(s["legacy"], b_leg),
                 s["exits_obj"], _pct(s["exits_obj"], b_exit),
                 s["churn"], s["loops"], s["speed"]))

    if base:
        better = [s["label"] for s in scored
                  if s["label"] != base["label"] and s["exits_obj"] > base["exits_obj"]]
        print("\nNO_TSP corrected objective = %.2f pax/delay-hr" % base["exits_obj"])
        print("arms beating it on the corrected column: %s"
              % (", ".join(better) if better else "none"))
        print("legacy column says NO_TSP wins: %s"
              % ("yes" if all(s["legacy"] <= base["legacy"] for s in scored) else "no"))
    return scored


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+", help="result CSV(s); globs allowed")
    ap.add_argument("--write", metavar="OUT",
                    help="write an augmented copy with the corrected columns")
    args = ap.parse_args(argv)

    rows = load(args.csv)
    scored = report(rows)

    if args.write and scored:
        by_src = {}
        for r, s in zip(rows, scored):
            by_src.setdefault(r["_source"], []).append((r, s))
        for src, pairs in by_src.items():
            fields = [k for k in pairs[0][0] if k not in ("_source", "_label")] + [
                "Objective_PaxExitsPerDelayHr", "Objective_DistinctPaxPerDelayHr",
                "PassageChurnPerExit"]
            with open(args.write, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                for r, s in pairs:
                    w.writerow(dict(r,
                                    Objective_PaxExitsPerDelayHr=round(s["exits_obj"], 3),
                                    Objective_DistinctPaxPerDelayHr=round(s["distinct_obj"], 3),
                                    PassageChurnPerExit=round(s["churn"], 3)))
        print("\nwrote %s" % args.write)
    return 0


if __name__ == "__main__":
    sys.exit(main())
