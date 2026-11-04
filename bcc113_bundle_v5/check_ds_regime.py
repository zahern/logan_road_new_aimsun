"""check_ds_regime.py -- did the DS recalibration and the regime state take effect?

    cd C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5
    python check_ds_regime.py

Reports, per arm in the newest logs:
  * [DS_TERMS] DS mean / max / spillback / starve floors
  * [DS_DECOMP] which term pins each phase (flow vs qr vs green_ref vs spill)
  * [REGIME] distribution of the SCATS-style operating state

PASS = DS no longer sits on the 5.0 clamp AND more than one regime is observed.
Exit code 0 on PASS.
"""
import collections
import glob
import io
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(BASE, "kg", "logs")


def newest_logs(limit=6):
    out = []
    files = sorted(glob.glob(os.path.join(LOGS, "Aimsun_TSP_Log_*.txt")),
                   key=os.path.getmtime)
    for f in files:
        txt = io.open(f, encoding="utf-8", errors="replace").read(8000)
        m = re.search(r"\[ARM\] exp=(\S+)", txt)
        if m:
            out.append((os.path.getmtime(f), f, m.group(1)))
    return out[-limit:]


def report(path, arm):
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    print("=" * 74)
    print("%s  (%s)" % (arm, time.strftime("%H:%M:%S",
                                           time.localtime(os.path.getmtime(path)))))
    fails = []

    m = re.search(r"\[DS_TERMS\][^\n]*DS mean=([0-9.]+) max=([0-9.]+)", txt)
    if m:
        mean, mx = float(m.group(1)), float(m.group(2))
        print("  [DS_TERMS] mean=%.2f max=%.2f" % (mean, mx))
        sp = re.search(r"spillback_floors=(\d+)", txt)
        sg = re.search(r"starve_guard_floors=(\d+)", txt)
        snap = re.search(r"snapshots=(\d+)", txt)
        print("             snapshots=%s spillback_floors=%s starve_floors=%s" % (
            snap.group(1) if snap else "?", sp.group(1) if sp else "?",
            sg.group(1) if sg else "?"))
        if mean >= 3.0:
            fails.append("DS mean still %.2f (queue term still pinning)" % mean)
        if mx >= 4.99:
            fails.append("DS max still at the 5.0 clamp")
    else:
        print("  [DS_TERMS] not present (run incomplete?)")

    rows = re.findall(
        r"\[DS_DECOMP\][^\n]*flow=([0-9.]+) qr=([0-9.]+) green_ref=([0-9.]+) "
        r"spill=([0-9.]+) raw=([0-9.]+) final=([0-9.]+)", txt)
    print("  [DS_DECOMP] lines: %d" % len(rows))
    if rows:
        n = float(len(rows))
        means = [sum(float(r[i]) for r in rows) / n for i in range(6)]
        print("             mean flow=%.2f qr=%.2f green_ref=%.2f spill=%.2f "
              "raw=%.2f final=%.2f" % tuple(means))
        worst = max(range(6), key=lambda i: means[i])
        names = ["flow", "qr", "green_ref", "spill", "raw", "final"]
        print("             dominant term: %s" % names[worst])
        if means[1] >= 2.9:
            fails.append("qr term still at its 3.0 cap on average")
    else:
        fails.append("no [DS_DECOMP] lines -> DS recalibration not loaded")

    regs = collections.Counter(
        re.findall(r"\[REGIME\][^\n]*regime=([A-Z_]+)\(", txt))
    print("  [REGIME] seen: %s" % (regs.most_common() or "none"))
    if not regs:
        fails.append("no [REGIME] lines -> regime classifier not loaded")
    elif len(regs) < 2:
        fails.append("only one regime observed (%s)" % list(regs))
    print()
    return fails


def main():
    logs = newest_logs()
    if not logs:
        sys.exit("no logs with [ARM] found")
    fails = []
    for _t, p, arm in logs:
        for f in report(p, arm):
            fails.append("%s: %s" % (arm.split("DSW_")[-1], f))
    print("=" * 74)
    if fails:
        print("FAIL")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS -- DS is discriminating again and the regime state is live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
