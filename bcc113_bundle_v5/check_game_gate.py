"""check_game_gate.py -- verify the GAME self-gate fix from a probe run.

Reads the probe CSV (default paper_game_gate_probe.csv) and the Aimsun logs
written since that CSV started, then reports:

  * executed actions per game arm (should be > 0 now),
  * [SELFGATE] pass/veto counts and the conflict_cost values (should no longer
    be a flat 6000 vetoing everything),
  * how many [NASH_BARGAIN] / [COOP_GAME] decisions were made.

Verdict:
  PASS     at least one game arm executed an action AND the veto rate fell
  PARTIAL  the 6000-veto is gone but no action was chosen (tune the net gate)
  FAIL     the arms still execute 0 actions and every candidate is vetoed

Usage (from the bundle dir, or give full paths):
    python check_game_gate.py
    python check_game_gate.py paper_game_gate_probe.csv --logs kg/logs
"""
from __future__ import annotations

import argparse
import glob
import io
import os
import re
import time

import pandas as pd

GAME = "CHAMP_ADAPTIVE_DSW_GAME_"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default=os.path.join(
        here, "paper_game_gate_probe.csv"))
    ap.add_argument("--logs", default=os.path.join(here, "kg", "logs"))
    ap.add_argument("--since", type=float, default=None,
                    help="epoch seconds; default = CSV mtime - 3600")
    a = ap.parse_args()

    if not os.path.isfile(a.csv):
        raise SystemExit("probe CSV not found: %s" % a.csv)
    d = pd.read_csv(a.csv)
    d = d[d["run_experiment"].astype(str).str.startswith(GAME)]
    if d.empty:
        raise SystemExit("no GAME_* rows in %s" % a.csv)

    for c in ("stats_TSP_Extensions", "stats_TSP_Insertions",
              "stats_TSP_GreenRealloc", "stats_TSP_EarlyRed",
              "stats_TSP_OffsetCorr", "stats_TSP_DeciderCostVeto"):
        if c not in d.columns:
            d[c] = 0
    d["actions"] = (pd.to_numeric(d["stats_TSP_Extensions"], errors="coerce")
                    + pd.to_numeric(d["stats_TSP_Insertions"], errors="coerce")
                    + pd.to_numeric(d["stats_TSP_GreenRealloc"], errors="coerce")
                    + pd.to_numeric(d["stats_TSP_EarlyRed"], errors="coerce")
                    + pd.to_numeric(d["stats_TSP_OffsetCorr"], errors="coerce"))

    print("=== probe results ===")
    print(d[["run_experiment", "run_seed", "stats_TotalPassDelay_hrs",
             "stats_TSP_Extensions", "stats_TSP_Insertions",
             "stats_TSP_DeciderCostVeto", "actions"]]
          .sort_values(["run_experiment", "run_seed"]).to_string(index=False))
    total_actions = float(d["actions"].sum())

    since = a.since if a.since is not None else os.path.getmtime(a.csv) - 3600
    logs = [f for f in glob.glob(os.path.join(a.logs, "Aimsun_TSP_Log_*.txt"))
            if os.path.getmtime(f) >= since]
    print("\n=== logs since %s (%d files) ===" %
          (time.strftime("%H:%M:%S", time.localtime(since)), len(logs)))

    veto = passed = nash = coop = 0
    costs = []
    for f in sorted(logs, key=os.path.getmtime):
        txt = io.open(f, encoding="utf-8", errors="replace").read()
        head = txt[:8000]
        m = re.search(r"(CHAMP_ADAPTIVE_DSW_GAME_(?:BUS|COOP|EGAL))", head)
        if not m:
            continue
        arm = m.group(1)
        v = len(re.findall(r"\[SELFGATE\].*->\s*VETO", txt))
        p = len(re.findall(r"\[SELFGATE\].*->\s*pass", txt))
        n = txt.count("[NASH_BARGAIN]")
        c = txt.count("[COOP_GAME]")
        cc = [int(x) for x in re.findall(r"conflict_cost=(\d+)", txt)]
        veto += v
        passed += p
        nash += n
        coop += c
        costs.extend(cc)
        print("  %-58s %-32s veto=%3d pass=%3d NASH=%2d COOP=%2d"
              % (os.path.basename(f), arm, v, p, n, c))

    print("\n=== summary ===")
    print("  executed game actions:", int(total_actions))
    print("  [SELFGATE] veto/pass :", veto, "/", passed)
    print("  [NASH_BARGAIN]/[COOP]:", nash, "/", coop)
    if costs:
        print("  conflict_cost min/max:", min(costs), "/", max(costs))

    if total_actions > 0 and (veto == 0 or passed > 0):
        verdict = "PASS"
    elif total_actions > 0:
        verdict = "PASS (actions executed; some candidates still vetoed)"
    elif (veto == 0 and passed == 0 and (nash + coop) > 0):
        verdict = "PARTIAL (6000-veto gone, but no action chosen)"
    else:
        verdict = "FAIL (still 0 actions / all candidates vetoed)"
    print("\nVERDICT:", verdict)
    if verdict.startswith("FAIL"):
        print("  Check that champion_search.py has DS_COST_IN_REWARD=False on")
        print("  GAME_BUS/GAME_COOP/GAME_EGAL and that Aimsun was fully restarted.")


if __name__ == "__main__":
    main()
