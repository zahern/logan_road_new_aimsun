"""watch_true_states.py -- backfill true-state plots for new Aimsun runs.

Use this if the in-process hook is disabled or Aimsun's Python lacks matplotlib.
Run it in a normal shell; it polls kg/results and plots any run dir that has a
section_timeseries.csv but no true_states/ yet.

    python watch_true_states.py                 # poll forever (30 s)
    python watch_true_states.py --once          # backfill now and exit
    python watch_true_states.py --interval 60
"""
import argparse
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "plot_true_states_hook.py")
RESULTS = os.path.join(HERE, "kg", "results")


def pending():
    out = []
    for d in glob.glob(os.path.join(RESULTS, "*")):
        if not os.path.isdir(d):
            continue
        csv = os.path.join(d, "section_timeseries.csv")
        if not os.path.isfile(csv):
            continue
        if os.path.isdir(os.path.join(d, "true_states")) and \
                os.path.isdir(os.path.join(d, "true_states_akiest")):
            continue
        out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    print("watching", RESULTS, "every %.0fs" % a.interval)
    while True:
        todo = pending()
        for d in todo:
            print("plotting", os.path.basename(d))
            subprocess.run([sys.executable, HOOK, "--run-dir", d],
                           check=False)
        if todo:
            print("backfilled", len(todo), "run dir(s)")
        if a.once:
            return
        time.sleep(max(5.0, a.interval))


if __name__ == "__main__":
    main()
