"""Merge the Logan extra-seed run into the published ladder (five seeds).

Reads
    paper_ladder_priority_logan.csv           seeds 300,400,500  (published)
    paper_ladder_priority_logan_500_700.csv   seeds 500,600,700  (new build)

Seed 500 was re-run as the A/B probe for the CTM group-boundary connector fix.
The merge keeps the PUBLISHED seed-500 rows and adds only the seeds the
published file does not have (600, 700), for two reasons:

  * every controlled arm's new seed-500 row is bit-identical to the published
    one, so nothing is gained by replacing it; and
  * the new session's NO_TSP seed-500 row is the FIRST run of a fresh Aimsun
    process and carries the documented first-replication artefact (throughput
    ~11% low, like KG seed 300), so it must not enter the ladder.

Output
    paper_ladder_priority_logan.csv       (backed up first)
    paper_ladder_priority_logan_summary.csv  rebuilt in the suite's format
"""
import csv
import os
import shutil
import statistics as st
import sys
from datetime import datetime

B = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
OLD = os.path.join(B, "paper_ladder_priority_logan.csv")
NEW = os.path.join(B, "paper_ladder_priority_logan_500_700.csv")
OUT = OLD

OUTCOME = ("stats_Objective_PaxPerDelayHr", "stats_TotalPassDelay_hrs",
           "stats_PaxEquivPassages", "stats_AvgBusPassDelay_s",
           "stats_AvgCarPassDelay_s", "stats_Net_AvgSpeed_kmh",
           "stats_TSP_Extensions", "stats_TSP_Insertions", "stats_TSP_EarlyRed")
TOL = 1e-6


def load(path):
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        return list(csv.DictReader(fh))


def num(row, k):
    try:
        return float(row.get(k, "") or 0.0)
    except ValueError:
        return 0.0


def key(row):
    return (str(row.get("run_experiment", "")), int(float(row.get("run_seed"))))


def main():
    if not os.path.isfile(NEW):
        sys.exit("missing %s -- run run_ladder_priority_logan_seeds_500_700.py first" % NEW)
    old, new = load(OLD), load(NEW)
    old_by, new_by = {key(r): r for r in old}, {key(r): r for r in new}
    old_seeds = {k[1] for k in old_by}
    new_seeds = sorted({k[1] for k in new_by})
    print("published: %d rows, seeds %s" % (len(old), sorted(old_seeds)))
    print("new batch: %d rows, seeds %s" % (len(new), new_seeds))

    # ---- A/B report on the repeated seed 500 -----------------------------
    arms = sorted({k[0] for k in old_by} & {k[0] for k in new_by})
    changed = []
    print("\nseed-500 A/B (published vs new build, connector fix on):")
    print("  %-42s %10s %10s %8s" % ("arm", "d_obj", "d_delay_h", "changed"))
    for arm in arms:
        a, b = old_by.get((arm, 500)), new_by.get((arm, 500))
        if a is None or b is None:
            continue
        d_obj = num(b, "stats_Objective_PaxPerDelayHr") - num(a, "stats_Objective_PaxPerDelayHr")
        d_dly = num(b, "stats_TotalPassDelay_hrs") - num(a, "stats_TotalPassDelay_hrs")
        diff = [c for c in OUTCOME if abs(num(b, c) - num(a, c)) > TOL]
        print("  %-42s %+10.3f %+10.2f %8s" % (arm, d_obj, d_dly, "YES" if diff else "-"))
        if diff:
            changed.append((arm, diff))
    if not changed:
        print("  -> the connector fix is inert for every scored arm: the "
              "published rows stand.")
    else:
        print("  -> changed arms: %s" % ", ".join(a for a, _ in changed))
    if any(a == "NO_TSP" for a, _ in changed):
        print("  note: the new NO_TSP seed-500 row is the first run of a fresh "
              "Aimsun process and carries the documented first-replication "
              "artefact; the published row is kept.")

    # ---- merge: published rows + new seeds only --------------------------
    merged = dict(old_by)
    added = [k for k in sorted(new_by, key=lambda k: (k[0], k[1])) if k[1] not in old_seeds]
    for k in added:
        merged[k] = new_by[k]
    rows = [merged[k] for k in sorted(merged, key=lambda k: (k[0], k[1]))]
    print("\nadded %d new (arm,seed) rows: seeds %s"
          % (len(added), sorted({k[1] for k in added})))
    print("merged rows %d, seeds %s" % (len(rows), sorted({key(r)[1] for r in rows})))

    bak = OUT + ".bak_before_merge_" + datetime.now().strftime("%Y%m%d_%H%M")
    shutil.copy2(OUT, bak)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote %s (backup %s)" % (OUT, os.path.basename(bak)))

    # ---- summary in the suite's format -----------------------------------
    seeds = sorted({key(r)[1] for r in rows})
    by = {}
    for r in rows:
        by.setdefault(str(r.get("run_experiment", "")), []).append(r)

    def vals(arm, col):
        return {int(float(r["run_seed"])): num(r, col) for r in by.get(arm, [])}

    base = vals("NO_TSP", "stats_Objective_PaxPerDelayHr")
    med = st.median(base.values())
    bad = {s for s, v in base.items() if med and abs(v / med - 1) * 100 > 10.0}
    if bad:
        print("[BASELINE] outlier seeds %s excluded from objective_pct_stable" % sorted(bad))

    out_rows = []
    for arm in ["NO_TSP"] + [a for a in by if a != "NO_TSP"]:
        a = vals(arm, "stats_Objective_PaxPerDelayHr")
        if not a:
            continue
        for s in seeds:
            if s not in a:
                continue
            out_rows.append({
                "arm": arm, "seed": s,
                "objective": a[s],
                "objective_pct_vs_no_tsp":
                    (100.0 * (a[s] - base[s]) / base[s]) if base.get(s) else "",
                "total_delay_hrs": vals(arm, "stats_TotalPassDelay_hrs").get(s, ""),
                "main_delay_hrs": vals(arm, "stats_MainPassDelay_hrs").get(s, ""),
                "side_delay_hrs": vals(arm, "stats_SidePassDelay_hrs").get(s, ""),
                "bus_delay_per_pax_s": vals(arm, "stats_AvgBusPassDelay_s").get(s, ""),
                "tsp_extensions": vals(arm, "stats_TSP_Extensions").get(s, ""),
                "tsp_insertions": vals(arm, "stats_TSP_Insertions").get(s, ""),
                "tsp_early_red": vals(arm, "stats_TSP_EarlyRed").get(s, ""),
                "tsp_natural_green": vals(arm, "stats_TSP_NaturalGreen").get(s, ""),
                "baseline_outlier": int(s in bad),
                "objective_pct_stable":
                    (100.0 * (a[s] - base[s]) / base[s])
                    if (base.get(s) and s not in bad) else "",
            })
    out_csv = os.path.splitext(OUT)[0] + "_summary.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print("wrote %s (%d rows)" % (out_csv, len(out_rows)))

    # ---- five-seed ladder -------------------------------------------------
    print("\n%-42s %8s %8s %9s %8s %8s" % (
        "arm", "obj", "%NO_TSP", "delay_h", "bus/pax", "car/pax"))
    for arm in ["NO_TSP"] + [a for a in by if a != "NO_TSP"]:
        a = vals(arm, "stats_Objective_PaxPerDelayHr")
        if not a:
            continue
        dd = vals(arm, "stats_TotalPassDelay_hrs")
        bb = vals(arm, "stats_AvgBusPassDelay_s")
        cc = vals(arm, "stats_AvgCarPassDelay_s")
        print("%-42s %8.2f %+7.1f%% %9.1f %8.2f %8.2f" % (
            arm, st.mean(a.values()),
            100 * (st.mean(a.values()) / st.mean(base.values()) - 1),
            st.mean(dd.values()), st.mean(bb.values()), st.mean(cc.values())))


if __name__ == "__main__":
    main()
