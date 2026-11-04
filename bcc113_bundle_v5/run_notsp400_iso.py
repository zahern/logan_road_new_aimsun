"""run_notsp400_iso.py -- is the OBJECTIVE reproducible for identical traffic?

DIAGNOSTIC for the baseline wobble. NO_TSP seed 400 gave objective 160.956 in
one run and 137.555 in another with BYTE-IDENTICAL microsim (Net_AvgSpeed
18.051 km/h and exit_count 162785 identical in both, SimDuration 1.25 h -- not
truncated). The traffic did not change; the objective's delay denominator
(corridor pax-s, OBJECTIVE_DELAY_SCOPE='corridor') did, because it is
accumulated from Aimsun's interval statistics and the sampling is not
bit-reproducible across runs (the same cause as the network stats'
akiest-system+incr-fill fallback).

This runs NO_TSP (+ CHAMP_GATED_CHAMP as a second reproducibility probe) on
seed 400 THREE times, each to its own timestamped CSV, so the spread of
Objective_PaxPerDelayHr can be measured directly. If NO_TSP 400 lands on three
different objectives, the metric is non-deterministic and must be moved onto a
full-run cumulative delay source before any % claim is trusted.

RUN (Aimsun console, KG model open, AFTER A FULL RESTART -- champion_search.py
changed, so CHAMP_GATED_CHAMP is a new arm):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_notsp400_iso.py").read())

6 sims (~1 h). Read the three CSVs' stats_Objective_PaxPerDelayHr for NO_TSP 400.
"""
import os as _os
import time as _time

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
_runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
_src = open(_runner, encoding="utf-8").read()

_os.environ["CHAMPION_POSTRUN_BUILD_CHECK"] = "1"
_os.environ.setdefault("STATS_SECTION_INTERVAL_S", "5")

_reps = int(_os.environ.get("ISO_REPS", "3"))
_outs = []
for _i in range(1, _reps + 1):
    _out = "notsp400_iso_rep%d_%s.csv" % (_i, _time.strftime("%Y%m%d_%H%M%S"))
    _outs.append(_out)
    _os.environ["ARM_SUITE_SEEDS"] = "400"
    _os.environ["ARM_SUITE_ARMS"] = "CHAMP_GATED_CHAMP"
    _os.environ["ARM_SUITE_CORRIDOR"] = "kg"
    _os.environ["ARM_SUITE_OUT"] = _out
    print("\n" + "#" * 72)
    print("# NO_TSP-400 ISOLATION  rep %d/%d  ->  %s" % (_i, _reps, _out))
    print("#" * 72)
    # Fresh namespace each rep; the suite reloads run_paxwin_game_vs_notsp itself.
    exec(compile(_src, _runner, "exec"), {"__name__": "__main__"})
    _time.sleep(1.0)

print("\n" + "=" * 72)
print("NO_TSP-400 ISOLATION DONE. Compare Objective_PaxPerDelayHr (NO_TSP 400):")
for _o in _outs:
    print("   ", _os.path.join(_HERE, _o))
print("=" * 72)
