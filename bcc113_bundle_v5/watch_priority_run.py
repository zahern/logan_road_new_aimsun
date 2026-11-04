"""watch_priority_run.py -- poll the running Aimsun priority ladder and print a
verdict when it finishes (or when it stops advancing).

    python watch_priority_run.py

Polls paper_ladder_priority_kg.csv every 60 s. Completion = 25 rows
(5 arms x 5 seeds, NO_TSP included) OR no change for 20 minutes.
Exit code 0 = complete and all gates green.
"""
import glob
import io
import os
import re
import sys
import time

try:
    import pandas as pd
except Exception:
    sys.exit("pandas required")

B = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(B, "paper_ladder_priority_kg.csv")
LOGS = os.path.join(B, "kg", "logs")
EXPECT_ROWS = 25
POLL_S = 60
STALL_S = 20 * 60


def rows():
    if not os.path.isfile(CSV):
        return 0
    try:
        return len(pd.read_csv(CSV))
    except Exception:
        return 0


def newest_gates():
    """Scan the newest logs for the three gate signals."""
    files = sorted(glob.glob(os.path.join(LOGS, "Aimsun_TSP_Log_*.txt")),
                   key=os.path.getmtime)[-8:]
    out = {}
    for f in files:
        txt = io.open(f, encoding="utf-8", errors="replace").read()
        m = re.search(r"\[ARM\] exp=(\S+)", txt)
        if not m:
            continue
        out[m.group(1)] = {
            "build": (re.search(r"ENGINE_BUILD=(\S+)", txt).group(1)
                      if re.search(r"ENGINE_BUILD=(\S+)", txt) else "?"),
            "bxt": txt.count("[BXT]"),
            "ctm": txt.count("[CTM]"),
            "recv_bind": txt.count("recv_bind=1"),
            "conn_ok": len(re.findall(r"\[CTM\].*conn=\[[0-9]", txt)),
            "commits": len(re.findall(
                r"\[(?:NASH_BARGAIN|COOP_GAME)\][^\n]*chosen=", txt)),
            "errors": len([l for l in txt.splitlines() if "] error" in l]),
            "regime": txt.count("[REGIME]"),
        }
    return out


def main():
    seen = -1
    last_change = time.time()
    while True:
        n = rows()
        if n != seen:
            seen = n
            last_change = time.time()
            print("[watch] %s rows=%d" % (time.strftime("%H:%M:%S"), n))
        if n >= EXPECT_ROWS:
            print("[watch] complete: %d rows" % n)
            break
        if time.time() - last_change > STALL_S:
            print("[watch] STALLED at %d rows for %d min" % (n, STALL_S // 60))
            break
        time.sleep(POLL_S)

    gates = newest_gates()
    print("\n%-38s %-30s %s" % ("arm", "build", "gate counts"))
    bad = []
    for arm, g in gates.items():
        print("%-38s %-30s BXT=%d CTM=%d conn_ok=%d recv_bind=%d commits=%d "
              "regime=%d errors=%d"
              % (arm[:38], g["build"][:30], g["bxt"], g["ctm"], g["conn_ok"],
                 g["recv_bind"], g["commits"], g["regime"], g["errors"]))
        if g["errors"]:
            bad.append("%s: %d errors" % (arm, g["errors"]))
        if "CELLQ" in arm and g["bxt"] == 0:
            bad.append("%s: no BXT decisions" % arm)
        if "GAME_BUS" in arm and g["commits"] == 0:
            bad.append("%s: no game commits" % arm)

    d = pd.read_csv(CSV) if os.path.isfile(CSV) else pd.DataFrame()
    if len(d):
        print("\nrows per arm:")
        print(d.groupby("run_experiment").agg(
            n=("run_seed", "count"), seeds=("run_seed", "nunique")).to_string())
        if "stats_Objective_PaxPerDelayHr" in d.columns:
            piv = d.pivot_table(index="run_seed", columns="run_experiment",
                                values="stats_Objective_PaxPerDelayHr")
            print("\nobjective by seed:")
            print(piv.round(1).to_string())

    print("\nVERDICT:", "PASS" if not bad else "ISSUES")
    for b in bad:
        print("  -", b)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
