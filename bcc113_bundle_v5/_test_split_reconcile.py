"""Verify the split-reconcile patch: source contract + arithmetic on real runs.

Part A  the patched line exists exactly once, inside the `if _swk...` block of
        _global_kpis, and the file still parses.
Part B  the delta the code applies equals (SimBusDelay - sum of per-junction bus
        term), within rounding, for both 2026-11-10 runs.
Part C  executes the REAL patched line with the real numbers and asserts that
        main+side then equals the headline.
"""
import ast
import csv
import glob
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC = "kg/Simulation_Stats.py"
MARK = "SPLIT_RECONCILE"
LINE = "total_main_delay += (_new_bus - _old_bus) / 3600.0"

# Same batch, same seed, same build: 14:15 NO_TSP vs 14:26 LIGHTSIM_MP is the
# pair the 183.59 / 707.62 h gaps came from. The 163445 folder is included as a
# THIRD arm because its name says NASH/LIGHTSIM_MP while its own stats record
# GLOBAL_REWARD -- label it by what the run says, not by the folder.
RUNS = [
    ("NO_TSP", "kg/results/NO_TSP_seed300_*_141527"),
    ("LIGHTSIM_MP", "kg/results/CHAMP_*LIGHTSIM_MP_seed300_*_142647"),
    ("GLOBAL_REWARD (folder named NASH)", "kg/results/CHAMP_*_163445"),
]

fails = []


def check(label, ok, detail=""):
    print("  %-58s %s %s" % (label, "PASS" if ok else "FAIL", detail))
    if not ok:
        fails.append(label)


# ------------------------------------------------------------------ Part A
src = io.open(SRC, encoding="utf-8").read()
print("== A. source contract ==")
check("marker present exactly once", src.count(MARK) == 1, "count=%d" % src.count(MARK))
check("adjustment line present once", src.count(LINE) == 1,
      "count=%d" % src.count(LINE))

i = src.find(LINE)
if i > 0:
    guard = 'if _swk.get("n_buses_measured", 0) > 0:'
    j = src.rfind(guard, 0, i)
    k = src.rfind("def _global_kpis", 0, i)
    check("inside the n_buses_measured guard", j > k and j > 0)
    # nothing that would move it out of the block: no 'def ' between guard and line
    check("no intervening def (still same block)",
          "def " not in src[j:i])
    after = src[i + len(LINE):]
    check("uses /3600.0 (hours, matching the accumulators)",
          "/ 3600.0" in src[i:i + len(LINE)])
try:
    ast.parse(src)
    check("file parses", True)
except SyntaxError as e:
    check("file parses", False, repr(e))


# ------------------------------------------------------------------ Part B/C
def num(row, name):
    for k2, v in row.items():
        if k2 and k2.strip().lstrip("\ufeff") == name:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def run_checks(label, pat):
    d = sorted(glob.glob(pat))[-1]
    rows = list(csv.DictReader(io.open(
        os.path.join(d, "simulation_results_per_intersection.csv"),
        encoding="utf-8-sig")))
    run = next(csv.DictReader(io.open(
        os.path.join(d, "simulation_results.csv"), encoding="utf-8-sig")))
    sw = json.load(io.open(os.path.join(d, "signal_wait_summary.json")))

    s_total = sum(num(r, "TotalPassDelay_hrs") for r in rows) * 3600.0
    s_main = sum(num(r, "MainPassDelay_hrs") for r in rows) * 3600.0
    s_side = sum(num(r, "SidePassDelay_hrs") for r in rows) * 3600.0
    s_bus = sum(num(r, "AvgBusPassDelay_s") * num(r, "BusPaxEquivPassages")
                for r in rows)
    head = num(run, "TotalPassDelay_hrs") * 3600.0
    old_ms = num(run, "MainPlusSidePassDelay_hrs") * 3600.0
    new_bus = num(run, "SimBusDelay_pax_s")

    print("\n== %s (%s) ==" % (label, os.path.basename(d)[-6:]))
    print("   split before      %10.1f pax-s (%.3f h)" % (old_ms, old_ms / 3600.0))
    print("   headline          %10.1f pax-s (%.3f h)" % (head, head / 3600.0))
    print("   gap before        %+10.1f pax-s (%.3f h)"
          % (old_ms - head, (old_ms - head) / 3600.0))

    # Part B: the code's delta versus what the artifacts say it must be
    delta_code = new_bus - s_bus
    delta_needed = head - s_total
    check("%s delta matches artifacts" % label,
          abs(delta_code - delta_needed) <= 100.0,
          "(code %+.0f vs needed %+.0f pax-s)" % (delta_code, delta_needed))

    # Part C: execute the real line for both junctions' aggregates
    ns = {"total_main_delay": s_main / 3600.0, "_new_bus": new_bus,
          "_old_bus": s_bus}
    exec(LINE, ns)
    main_after = ns["total_main_delay"] * 3600.0
    ms_after = main_after + s_side
    print("   main+side after   %10.1f pax-s (%.3f h)" % (ms_after, ms_after / 3600.0))
    print("   residual after    %+10.1f pax-s (%+.4f h)"
          % (ms_after - head, (ms_after - head) / 3600.0))
    check("%s main+side == headline after fix" % label,
          abs(ms_after - head) <= 3600 * 0.05)


for label, pat in RUNS:
    if not glob.glob(pat):
        print("\n[SKIP] no folder for %s (%s)" % (label, pat))
        fails.append("missing folder for %s" % label)
        continue
    run_checks(label, pat)

print("\n" + "=" * 74)
if fails:
    print("FAILED: %s" % ", ".join(fails))
    sys.exit(1)
print("PASS: patch present, delta matches artifacts, main+side == headline on every arm")
