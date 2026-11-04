"""plot_true_states_hook.py -- generate true-state plots for one run dir.

Called automatically by champion_search._run_and_collect after a successful
replication, and usable by hand:

    python plot_true_states_hook.py --run-dir <kg/results/RUN_DIR>

Writes <run>/true_states/ (all rows: AKIEST + IMPOSED) and
<run>/true_states_akiest/ (measured rows only), each with flow/density/speed/
queue PNG+TXT. Never raises: a missing CSV or plotting failure is reported and
the run continues.
"""
import argparse
import os
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--python", default=os.environ.get("TRUE_STATE_PYTHON", ""))
    a = ap.parse_args()

    run_dir = os.path.abspath(a.run_dir)
    csv = os.path.join(run_dir, "section_timeseries.csv")
    if not os.path.isfile(csv):
        print("no section_timeseries.csv in", run_dir)
        return 0

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "plot_true_states.py")
    if not os.path.isfile(script):
        print("plot_true_states.py not found next to hook")
        return 0

    pythons = [a.python] if a.python else []
    pythons += [sys.executable]
    for cand in ("python", "python3", "py"):
        import shutil
        p = shutil.which(cand)
        if p:
            pythons.append(p)
    seen = set()
    for py in pythons:
        if not py or py in seen:
            continue
        seen.add(py)
        ok_all = True
        for src, sub in (("any", "true_states"), ("AKIEST", "true_states_akiest")):
            out = os.path.join(run_dir, sub)
            cmd = [py, script, "--csv", csv, "--out-dir", out]
            if src != "any":
                cmd += ["--src", src]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=240)
            except Exception as e:
                print("plot failed with %s: %r" % (py, e))
                ok_all = False
                break
            if r.returncode != 0:
                print("plot failed with %s (%s): %s"
                      % (py, src, (r.stderr or r.stdout)[-300:]))
                ok_all = False
                break
        if ok_all:
            print("true-state plots written:", run_dir)
            return 0
    print("could not generate true-state plots for", run_dir)
    return 1


if __name__ == "__main__":
    sys.exit(main())
