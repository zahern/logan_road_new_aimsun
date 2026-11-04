"""inspect_aimsun_actions.py -- what did each TSP arm actually decide?

Reads the latest ``reward_cycle_<arm>_<ts>.csv`` files (one row per candidate
action, ``is_chosen`` marks the final action) and the latest suite CSV, and
reports:

  * per-arm actions (GE/INS/ER/GR), detections, and no-action counts
  * per-decision chosen actions
  * decisions where the best non-NO_ACTION candidate beat NO_ACTION by more
    than ``--gap`` pax-s but the controller still chose NO_ACTION (blocked)
  * the top blocked decisions (time, junction, bus, ETA, queue, gap)

It also writes ``actions_chosen.csv`` and ``actions_blocked.csv`` next to this
script so the exact action stream can be inspected in Excel/pandas.

Usage
-----
    python inspect_aimsun_actions.py
    python inspect_aimsun_actions.py --suite paxwin_arm_suite_5seeds.csv
    python inspect_aimsun_actions.py --gap 500 --top 20

The reward_cycle CSV logs the shared candidate pool; for specialised modes
(BXT/NASH/CPDQL/BELLMAN) the committed action may be represented by the
``is_chosen`` row or by the mode's own log tag. The stats_TSP_* columns in the
suite CSV are the authoritative executed-action counts.
"""
import argparse
import glob
import os
import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, "kg", "logs")
DEFAULT_SUITE = os.path.join(HERE, "paxwin_arm_suite_5seeds.csv")


def _latest(pattern, cutoff=0.0):
    fs = [f for f in glob.glob(pattern) if os.path.getmtime(f) >= cutoff]
    if not fs:
        return None
    return max(fs, key=os.path.getmtime)


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default=DEFAULT_SUITE)
    ap.add_argument("--log-dir", default=LOG_DIR)
    ap.add_argument("--gap", type=float, default=1.0,
                    help="pax-s margin above NO_ACTION counted as blocked")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--since-hours", type=float, default=24.0,
                    help="ignore reward_cycle files older than the suite CSV")
    args = ap.parse_args()

    if not os.path.isfile(args.suite):
        raise SystemExit("missing suite CSV: %s" % args.suite)
    suite = pd.read_csv(args.suite, encoding="utf-8-sig", engine="python")
    exp_col = "run_experiment"
    obj_col = "stats_Objective_PaxPerDelayHr"
    if exp_col not in suite.columns or obj_col not in suite.columns:
        raise SystemExit("suite CSV missing %s/%s" % (exp_col, obj_col))

    base = suite[suite[exp_col] == "NO_TSP"][obj_col].mean()
    cutoff = os.path.getmtime(args.suite) - args.since_hours * 3600.0
    chosen_rows, blocked_rows = [], []

    print("=" * 92)
    print("TSP ACTION AUDIT -- %s" % os.path.basename(args.suite))
    print("=" * 92)
    for arm in suite[exp_col].drop_duplicates():
        g = suite[suite[exp_col] == arm]
        obj = g[obj_col].mean()
        rel = 100.0 * (obj - base) / base if base else 0.0
        det = g.get("stats_TSP_Detections", pd.Series(dtype=float)).mean()
        ge = g.get("stats_TSP_Extensions", pd.Series(dtype=float)).mean()
        ins = g.get("stats_TSP_Insertions", pd.Series(dtype=float)).mean()
        er = g.get("stats_TSP_EarlyRed", pd.Series(dtype=float)).mean()
        gr = g.get("stats_TSP_GreenRealloc", pd.Series(dtype=float)).mean()
        noact = g.get("stats_TSP_Detected_NoAction",
                      pd.Series(dtype=float)).mean()
        print("\n%-34s obj=%7.2f (%+6.1f%%)  det=%6.1f  GE=%.1f INS=%.1f "
              "ER=%.1f GR=%.1f  noact=%.1f"
              % (arm, obj, rel, det, ge, ins, er, gr, noact))

        p = _latest(os.path.join(args.log_dir,
                                 "reward_cycle_%s_*.csv" % arm), cutoff)
        if p is None:
            print("  no reward_cycle CSV (base/FLOW use another path)")
            continue
        try:
            d = pd.read_csv(p, encoding="utf-8-sig", engine="python")
        except Exception as e:
            print("  read error:", e)
            continue
        d["action"] = d.get("action", "").astype(str)
        d["is_chosen"] = _num(d.get("is_chosen", 0)).fillna(0)
        d["reward"] = _num(d.get("reward", -1e18)).fillna(-1e18)
        keys = [c for c in ("sim_time_s", "junction_id", "veh_id")
                if c in d.columns]
        if not keys:
            print("  no decision keys:", p)
            continue

        ch = d[d["is_chosen"] > 0]
        non = ch[ch["action"] != "NO_ACTION"]
        decisions = ch.groupby(keys, dropna=False).size()
        print("  log=%s  rows=%d  decisions=%d  chosen_nonNO=%d  %s"
              % (os.path.basename(p), len(d), len(decisions), len(non),
                 non["action"].value_counts().head(6).to_dict()))

        n_blocked = 0
        n_acted = 0
        for key, gg in d.groupby(keys, dropna=False):
            no = gg[gg["action"] == "NO_ACTION"]["reward"]
            nz = gg[gg["action"] != "NO_ACTION"]["reward"]
            if no.empty or nz.empty:
                continue
            gap = float(nz.max()) - float(no.max())
            chosen = (gg[gg["is_chosen"] > 0]["action"].iloc[0]
                      if len(gg[gg["is_chosen"] > 0]) else "?")
            row = {"arm": arm, "time": key[0] if len(key) > 0 else "",
                   "junction": key[1] if len(key) > 1 else "",
                   "veh": key[2] if len(key) > 2 else "",
                   "chosen": chosen, "gap_paxs": round(gap, 1)}
            for c in ("bus_eta_s", "queue_veh", "current_phase", "param_s",
                      "bus_saved_pax_s", "other_inc_pax_s", "side_inc_pax_s",
                      "sigma_in", "bus_late_s", "headway_s", "gate",
                      "decider_warm", "decider_min_late"):
                if c in gg.columns:
                    row[c] = gg[c].iloc[0]
            if chosen != "NO_ACTION":
                n_acted += 1
                chosen_rows.append(row)
            elif gap > args.gap:
                n_blocked += 1
                blocked_rows.append(row)
        print("  decisions with best_nonNO > NO+%.0f: acted=%d blocked=%d"
              % (args.gap, n_acted, n_blocked))
        if blocked_rows:
            bb = pd.DataFrame([r for r in blocked_rows if r["arm"] == arm])
            if len(bb):
                bb = bb.sort_values("gap_paxs", ascending=False).head(args.top)
                print(bb.to_string(index=False))

    if chosen_rows:
        out = os.path.join(HERE, "actions_chosen.csv")
        pd.DataFrame(chosen_rows).to_csv(out, index=False)
        print("\nwrote", out)
    if blocked_rows:
        out = os.path.join(HERE, "actions_blocked.csv")
        pd.DataFrame(blocked_rows).sort_values(
            "gap_paxs", ascending=False).to_csv(out, index=False)
        print("wrote", out)


if __name__ == "__main__":
    main()
