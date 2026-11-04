"""check_quick_test.py -- verify the CellQ CTM + GAME veto fixes.

Reads paper_quick_test.csv (or a path) and the Aimsun logs written since that
CSV started, then reports:

  CellQ:   [CTM] lines, conn=[...] vs conn=n/a, solve_bus_phase_green errors,
           executed actions.
  GAME:    executed actions, DSBalanceVeto / DeciderCostVeto, [SELFGATE] count,
           [NASH_BARGAIN] / [COOP_GAME] decisions.

Verdict:
  PASS   CellQ has CTM lines with a resolved connector and no solver error,
         AND at least one game arm executes an action with no [SELFGATE].
  PARTIAL one side passes.
  FAIL   neither.

Usage (bundle dir, or full paths):
    python check_quick_test.py
    python check_quick_test.py paper_quick_test.csv --logs kg/logs
"""
from __future__ import annotations

import argparse
import glob
import io
import os
import re
import time

import pandas as pd


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default=os.path.join(
        here, "paper_quick_test.csv"))
    ap.add_argument("--logs", default=os.path.join(here, "kg", "logs"))
    a = ap.parse_args()

    if not os.path.isfile(a.csv):
        raise SystemExit("CSV not found: %s" % a.csv)
    d = pd.read_csv(a.csv)
    print("=== quick-test results ===")
    cols = [c for c in ("run_experiment", "run_seed",
                        "stats_TotalPassDelay_hrs",
                        "stats_TSP_Extensions", "stats_TSP_Insertions",
                        "stats_TSP_DSBalanceVeto",
                        "stats_TSP_DeciderCostVeto") if c in d.columns]
    print(d[cols].to_string(index=False))

    act = {}
    for _, r in d.iterrows():
        a_ = str(r.get("run_experiment", ""))
        act[a_] = (float(r.get("stats_TSP_Extensions", 0) or 0)
                   + float(r.get("stats_TSP_Insertions", 0) or 0))

    since = os.path.getmtime(a.csv) - 3600
    logs = [f for f in glob.glob(os.path.join(a.logs, "Aimsun_TSP_Log_*.txt"))
            if os.path.getmtime(f) >= since]
    print("\n=== logs since %s (%d files) ===" %
          (time.strftime("%H:%M:%S", time.localtime(since)), len(logs)))

    ctm = conn_ok = conn_na = solver_err = selfgate = 0
    nash = coop = 0
    for f in sorted(logs, key=os.path.getmtime):
        txt = io.open(f, encoding="utf-8", errors="replace").read()
        head = txt[:8000]
        m = re.search(r"(CHAMP_ADAPTIVE_[A-Z0-9_]+|NO_TSP)", head)
        arm = m.group(1) if m else "?"
        c = txt.count("[CTM]")
        ok = len(re.findall(r"\[CTM\].*conn=\[", txt))
        na = len(re.findall(r"\[CTM\].*conn=n/a", txt))
        se = txt.count("solve_bus_phase_green error")
        sg = txt.count("[SELFGATE]")
        n = txt.count("[NASH_BARGAIN]")
        cp = txt.count("[COOP_GAME]")
        ctm += c
        conn_ok += ok
        conn_na += na
        solver_err += se
        selfgate += sg
        nash += n
        coop += cp
        print("  %s %-34s CTM=%3d conn_ok=%3d conn_na=%3d solver_err=%d "
              "SELFGATE=%d NASH=%d COOP=%d"
              % (os.path.basename(f), arm, c, ok, na, se, sg, n, cp))

    print("\n=== summary ===")
    print("  CTM lines          :", ctm)
    print("  connector resolved :", conn_ok, " (n/a:", conn_na, ")")
    print("  solver errors      :", solver_err)
    print("  [SELFGATE] lines   :", selfgate)
    print("  NASH / COOP        :", nash, "/", coop)
    print("  actions            :", {k: int(v) for k, v in act.items()})

    cell_ok = (ctm > 0 and conn_ok > 0 and solver_err == 0)
    game_ok = (selfgate == 0 and any(
        v > 0 for k, v in act.items() if "GAME" in k))
    if cell_ok and game_ok:
        verdict = "PASS"
    elif cell_ok or game_ok:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    print("\nVERDICT:", verdict)
    if not cell_ok:
        print("  CellQ: look for [CTM] conn=[...] (not n/a) and no")
        print("         'solve_bus_phase_green error'.")
    if not game_ok:
        print("  GAME: look for DSBalanceVeto=0 and actions > 0; if still 0,")
        print("        inspect the remaining veto counters in the CSV.")


if __name__ == "__main__":
    main()
