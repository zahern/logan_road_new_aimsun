"""Classify existing runs: can main/side be corrected offline, or must they re-run?

The patch makes MainPlusSide == headline inside the engine. For a run that has
already finished, the same correction is computable from its own artifacts:

    delta   = SimBusDelay_pax_s - sum(AvgBusPassDelay_s * BusPaxEquivPassages)
    main_new = MainPassDelay_hrs - delta/3600
    M+S_new  = main_new + SidePassDelay_hrs        (must equal TotalPassDelay_hrs)

So a folder is "offline-fixable" when simulation_results.csv AND
simulation_results_per_intersection.csv both exist and the residual closes.
Anything else must be re-simulated (or is not a stats run at all).
"""
import csv
import glob
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = "kg/results"
NEED = ("simulation_results.csv", "simulation_results_per_intersection.csv")


def num(row, name, default=0.0):
    for k, v in row.items():
        if k and k.strip().lstrip("\ufeff") == name:
            try:
                return float(v)
            except (TypeError, ValueError):
                return default
    return default


def classify(d):
    have = [n for n in NEED if os.path.exists(os.path.join(d, n))]
    if len(have) != len(NEED):
        return ("missing", "lacks %s" % ", ".join(n for n in NEED if n not in have),
                None, None)
    try:
        run = next(csv.DictReader(io.open(os.path.join(d, NEED[0]),
                                          encoding="utf-8-sig")))
        rows = list(csv.DictReader(io.open(os.path.join(d, NEED[1]),
                                           encoding="utf-8-sig")))
    except Exception as exc:
        return ("broken", repr(exc), None, None)
    if not rows:
        return ("missing", "per-intersection file empty", None, None)

    head = num(run, "TotalPassDelay_hrs")
    main = num(run, "MainPassDelay_hrs")
    side = num(run, "SidePassDelay_hrs")
    ms = num(run, "MainPlusSidePassDelay_hrs")
    bus = num(run, "SimBusDelay_pax_s")
    s_bus = sum(num(r, "AvgBusPassDelay_s") * num(r, "BusPaxEquivPassages")
                for r in rows)

    delta = bus - s_bus
    main_new = main + delta / 3600.0
    ms_new = main_new + side
    resid = ms_new - head
    return ("fixable" if abs(resid) <= 0.05 else "rerun",
            "delta=%+.1f pax-s resid=%+.4f h" % (delta, resid),
            (head, ms, ms_new), None)


def main():
    dirs = sorted(d for d in glob.glob(os.path.join(ROOT, "*"))
                  if os.path.isdir(d))
    stats = {"fixable": [], "rerun": [], "missing": [], "broken": []}
    for d in dirs:
        kind, note, nums, _ = classify(d)
        stats[kind].append((os.path.basename(d), note, nums))

    print("run folders scanned: %d" % len(dirs))
    for kind in ("fixable", "rerun", "missing", "broken"):
        print("  %-8s %d" % (kind, len(stats[kind])))

    if stats["rerun"]:
        print("\nMUST RE-SIMULATE (correction does not close):")
        for name, note, nums in stats["rerun"][:15]:
            print("  %-72s %s" % (name[:72], note))

    if stats["missing"] or stats["broken"]:
        print("\nNO USABLE ARTIFACTS (cannot correct offline):")
        for kind in ("missing", "broken"):
            for name, note, _ in stats[kind][:10]:
                print("  %-72s %s" % (name[:72], note))

    print("\nsample of offline-correctable runs (headline / M+S old -> new):")
    for name, note, nums in stats["fixable"][:6]:
        if nums:
            print("  %-58s %8.3f | %8.3f -> %8.3f  %s"
                  % (name[:58], nums[0], nums[1], nums[2], note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
