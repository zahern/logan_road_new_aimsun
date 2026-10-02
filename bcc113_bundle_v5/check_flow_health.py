"""
check_flow_health.py -- pre-experiment FLOW-CAPTURE audit (read-only, offline).

WHY: the TSP arms only act as well as the flow they can see. Before spending
1.5-3 h on an arm ladder, run ONE short replication (e.g. check_side_sections.py
or a single NO_TSP) and audit how much of the network's flow was actually
GRABBED (measured) vs IMPOSED (fallback identity q=k*v).

READS:
  <run>/section_timeseries.csv  -- per-section 30 s rows; src=AKIEST is
                                   independently measured (delta-counts /
                                   inputCounts / space-mean speed),
                                   src=IMPOSED had q=k*v forced by a fallback
                                   and must not be trusted as measurement.
  newest Aimsun_TSP_Log_*.txt   -- [FLOW SRC] tier mix (demand_profile seed vs
                                   snapshot_alltypes vs partial windows) and
                                   [SIDE_SCAN] stale-counter faults.

USAGE (from the Aimsun console, bare exec works -- defaults to the newest run):
  exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\check_flow_health.py").read())
Or from a terminal:
  python check_flow_health.py [run_folder] [--log <file>]

Exit is never raised (console-safe). Prints a per-junction table + verdict.
"""
import collections
import csv
import glob
import os
import re
import sys

ROOT = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
CORR_DIR = os.path.join(ROOT, "logan_road_new")


def _newest_run():
    cands = [d for d in glob.glob(os.path.join(CORR_DIR, "results", "*"))
             if os.path.isdir(d)]
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


def _newest_log():
    logs = glob.glob(os.path.join(CORR_DIR, "logs", "Aimsun_TSP_Log_*.txt"))
    return max(logs, key=os.path.getmtime) if logs else None


def _load_ts(run_dir):
    p = os.path.join(run_dir, "section_timeseries.csv")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run_dir = args[0] if args else _newest_run()
    log_path = None
    if "--log" in sys.argv:
        i = sys.argv.index("--log")
        if i + 1 < len(sys.argv):
            log_path = sys.argv[i + 1]
    if not log_path:
        log_path = _newest_log()

    print("=" * 78)
    print("FLOW-CAPTURE HEALTH (pre-experiment audit)")
    print(f"  run: {run_dir}")
    print(f"  log: {log_path}")
    print("=" * 78)
    if not run_dir:
        print("no run folder found -- run one replication first.")
        return

    rows = _load_ts(run_dir)
    if rows is None:
        print("no section_timeseries.csv in that folder.")
        return

    # ── per-junction main/side capture ────────────────────────────────────────
    agg = collections.defaultdict(lambda: {"mn": 0, "mn_nz": 0, "mn_aki": 0,
                                           "sn": 0, "sn_nz": 0, "sn_aki": 0,
                                           "mn_secs": set(), "sn_secs": set(),
                                           "mn_q": 0.0, "sn_q": 0.0})
    for r in rows:
        jid = str(r.get("IntersectionID", "?")).strip()
        a = agg[jid]
        q = _f(r.get("q_veh_h"))
        nz = 1 if q > 1.0 else 0
        aki = 1 if str(r.get("src", "")).strip() == "AKIEST" else 0
        try:
            a["mn_secs"].add(r.get("SectionID"))
            a["sn_secs"].add(r.get("SectionID"))
        except Exception:
            pass
        if str(r.get("IsMain", "")).strip() == "1":
            a["mn"] += 1; a["mn_nz"] += nz; a["mn_aki"] += aki; a["mn_q"] += q
        else:
            a["sn"] += 1; a["sn_nz"] += nz; a["sn_aki"] += aki; a["sn_q"] += q

    print(f"{'jct':>7} {'mSec':>5} {'mRows':>6} {'m%flow':>7} {'m%AKI':>6} "
          f"{'mQ':>7} | {'sSec':>5} {'sRows':>6} {'s%flow':>7} {'s%AKI':>6} {'sQ':>7}  flag")
    n_bad = n_warn = 0
    for jid in sorted(agg, key=lambda x: (len(x), x)):
        a = agg[jid]
        mf = a["mn_nz"] / a["mn"] if a["mn"] else float("nan")
        ma = a["mn_aki"] / a["mn"] if a["mn"] else float("nan")
        mq = a["mn_q"] / a["mn"] if a["mn"] else 0.0
        sf = a["sn_nz"] / a["sn"] if a["sn"] else float("nan")
        sa = a["sn_aki"] / a["sn"] if a["sn"] else float("nan")
        sq = a["sn_q"] / a["sn"] if a["sn"] else 0.0
        flag = ""
        if a["mn"] and mf < 0.30:
            flag = "MAIN-FLOW-DEAD"; n_bad += 1
        elif a["mn"] and mf < 0.60:
            flag = "main-low"; n_warn += 1
        if a["sn"] and sf == sf and sf < 0.30:
            flag = (flag + "+side-low") if flag else "side-low"
        def pct(v):
            return "--" if v != v else f"{v*100:.0f}%"
        print(f"{jid:>7} {len(a['mn_secs']):>5} {a['mn']:>6} {pct(mf):>7} {pct(ma):>6} "
              f"{mq:>7.0f} | {len(a['sn_secs']):>5} {a['sn']:>6} {pct(sf):>7} {pct(sa):>6} {sq:>7.0f}  {flag}")

    # ── log-side tier mix + stale counters ───────────────────────────────────
    tiers = collections.Counter()
    stale = collections.Counter()
    noupd = 0
    if log_path and os.path.isfile(log_path):
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if "[FLOW SRC]" in ln:
                    m = re.search(r"tier=([a-z_]+)", ln)
                    if m:
                        tiers[m.group(1)] += 1
                if "[noupdate stale=" in ln:
                    noupd += 1
                    m = re.search(r"inter=(\d+)", ln)
                    if m:
                        stale[m.group(1)] += 1
        print("-" * 78)
        print(f"[FLOW SRC] tiers: {dict(tiers)}  "
              f"(demand_profile=seed prior; snapshot/partial=measured)")
        print(f"[noupdate] stale-counter lines: {noupd}"
              + (f"  worst: {stale.most_common(5)}" if stale else ""))

    print("-" * 78)
    n_j = len(agg)
    if n_bad:
        print(f"RESULT: {n_bad} junction(s) with DEAD main-flow capture "
              f"(<30% nonzero) -- fix sections/detectors before the ladder.")
    elif n_warn:
        print(f"RESULT: OK-ish -- {n_warn} junction(s) below 60% main capture "
              f"(check flagged rows); no dead junctions.")
    else:
        print(f"RESULT: PASS -- all {n_j} junctions capture main flow "
              f"(>=60% nonzero rows).")
    print("Note: side% can be legitimately low (empty approaches); trust it only "
          "together with [SIDE_OBJ] n_veh.")


if __name__ == "__main__":
    main()
