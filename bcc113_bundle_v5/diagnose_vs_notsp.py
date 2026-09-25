#!/usr/bin/env python3
"""
diagnose_vs_notsp.py -- blame WHY a TSP run lost to its NO_TSP baseline.

Compares two per-run result folders (same seed, same demand) and points at the
exact junctions/actions that made the TSP run worse, plus the cascade evidence.

WHAT IT ANSWERS
---------------
  1. Global verdict: obj / bus / car deltas (is the loss car-driven?).
  2. WHERE: per-junction blame ranking by added pax-hours (total/main/side
     split, bus vs car, queue, actions fired). A side-heavy loss = cross-street
     cascade; a main-heavy loss = corridor progression break.
  3. WHAT ACTION: from the per-run reward_cycle_*.csv ledger (new columns
     chain/stage/monitor, engine >= 2026-09-25T14:00-diag-ledger) and/or
     [DECISION] log lines: commits per losing junction with predicted
     bus_saved/other/side/net + flow stage at commit. Predicted-net-negative
     actions = gate failure; predicted-positive but realized loss =
     model miscalibration (see [BXT_EVAL] realized_adv).
  4. CASCADE: section_timeseries.csv queue early-vs-late per losing junction
     (TSP vs baseline), plus [FLOW_STAGE]/[VIABILITY]/[CASCADE]/[MEAS_SIDE]/
     [noupdate] evidence from the run log when given.

USAGE (normal terminal, no Aimsun needed)
-----------------------------------------
  python diagnose_vs_notsp.py --tsp <tsp_run_folder> --base <notsp_run_folder>
      [--reward-csv <reward_cycle_*.csv>] [--log <Aimsun_TSP_Log_*.txt>]
      [--top 8] [--out blame.md]

  Run folders look like:
    logan_road_new/results/CELLQLEARN_seed300_.../
    logan_road_new/results/NO_TSP_seed300_.../
  Each must contain simulation_results.csv + simulation_results_per_intersection.csv
  (section_timeseries.csv optional, used for the cascade window).

  --reward-csv/--log: if omitted, the script auto-looks in <corridor>/logs/
  (sibling of results/) for the newest matching files and says what it used.
  Pass them explicitly for precision -- log timestamps rotate every run.
"""
import argparse
import csv
import glob
import os
import re
import sys
from collections import defaultdict


def _f(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _read_first_row(path):
    try:
        with open(path, "r", newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                return row
    except Exception:
        pass
    return {}


def _read_rows(path):
    try:
        with open(path, "r", newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def _filter_run_rows(all_rows, global_row):
    """Mirror batch_runner._per_intersection_rows: keep this run's slice."""
    scen = str(global_row.get("ScenarioID", "") or "").strip()
    exp = str(global_row.get("ExperimentID", "") or "").strip()
    rep = str(global_row.get("ReplicationID", "") or "").strip()
    if scen and exp and rep:
        sub = [r for r in all_rows
               if str(r.get("ScenarioID", "")).strip() == scen
               and str(r.get("ExperimentID", "")).strip() == exp
               and str(r.get("ReplicationID", "")).strip() == rep]
        if sub:
            return sub
    return all_rows


def _autofind_logs(tsp_folder):
    """Best-effort: <corridor>/logs/ newest reward_cycle + Aimsun log."""
    try:
        corr = os.path.dirname(os.path.dirname(os.path.abspath(tsp_folder)))
        logdir = os.path.join(corr, "logs")
        rcs = sorted(glob.glob(os.path.join(logdir, "reward_cycle_*.csv")),
                     key=os.path.getmtime)
        logs = sorted(glob.glob(os.path.join(logdir, "Aimsun_TSP_Log_*.txt")),
                      key=os.path.getmtime)
    except Exception:
        return None, None, None
    return (rcs[-1] if rcs else None), (logs[-1] if logs else None), logdir


def _parse_reward_ledger(path):
    """Aggregate chosen actions per junction from reward_cycle CSV."""
    per_j = defaultdict(lambda: {"n": 0, "bus": 0.0, "other": 0.0,
                                 "side": 0.0, "net": 0.0, "chain": 0.0,
                                 "stages": defaultdict(int),
                                 "actions": defaultdict(int), "first_t": None,
                                 "last_t": None})
    n_rows = 0
    try:
        for r in _read_rows(path):
            if str(r.get("is_chosen", "0")).strip() not in ("1", "1.0", "True"):
                continue
            act = str(r.get("action", "")).strip()
            if not act or act == "NO_ACTION":
                continue
            j = str(r.get("junction_id", "?")).strip()
            d = per_j[j]
            bs, oi, si = _f(r.get("bus_saved_pax_s")), _f(r.get("other_inc_pax_s")), _f(r.get("side_inc_pax_s"))
            d["n"] += 1
            d["bus"] += bs
            d["other"] += oi
            d["side"] += si
            d["net"] += bs - oi - si
            d["chain"] += _f(r.get("chain_pax_s"))
            st = str(r.get("stage", "") or "").strip() or "UNK"
            d["stages"][st] += 1
            d["actions"][act.split("_")[0]] += 1
            try:
                t = float(r.get("sim_time_s", 0) or 0)
                d["first_t"] = t if d["first_t"] is None else min(d["first_t"], t)
                d["last_t"] = t if d["last_t"] is None else max(d["last_t"], t)
            except Exception:
                pass
            n_rows += 1
    except Exception as e:
        print(f"  [warn] reward ledger parse failed: {e!r}")
    return per_j, n_rows


_DECISION_RE = re.compile(
    r"\[DECISION\]\s+inter=(\S+)\s+t=([\d.]+)\s+bus=(\S+)\s+action=(\S+)\s+dur=([\d.]+)s\s+"
    r"pred_bus=([-\d.]+)\s+pred_other=([-\d.]+)\s+pred_side=([-\d.]+)\s+pred_net=([-\d.]+)\s+"
    r"chain=([-\d.]+)\s+R=([-\d.]+)\s+(.*)")
_STAGE_RE = re.compile(
    r"\[FLOW_STAGE\]\s+inter=(\S+)\s+t=([\d.]+)\s+stage=(\S+)\s+main_x=([\d.]+)\s+"
    r"side_max=([\d.]+)vph\s+queue=([\d.]+)\s+armed=(\d)")
_BXT_EVAL_RE = re.compile(
    r"\[BXT_EVAL\]\s+inter=(\S+)\s+bus=(\S+)\s+t=([\d.]+)\s+action=(\S+)\s+.*?"
    r"realized_adv=([-\d.infna]+)", re.IGNORECASE)


def _parse_run_log(path):
    decisions = defaultdict(list)
    stages = {}
    evals = defaultdict(list)
    counts = defaultdict(int)
    stale = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _DECISION_RE.search(line)
                if m:
                    decisions[m.group(1)].append(line.strip())
                    counts["DECISION"] += 1
                    continue
                m = _STAGE_RE.search(line)
                if m:
                    stages[m.group(1)] = line.strip()
                    counts["FLOW_STAGE"] += 1
                    continue
                m = _BXT_EVAL_RE.search(line)
                if m:
                    try:
                        evals[m.group(1)].append(float(m.group(5)))
                    except Exception:
                        evals[m.group(1)].append(0.0)
                    counts["BXT_EVAL"] += 1
                    continue
                for tag in ("[VIABILITY]", "[CASCADE]", "[MEAS_SIDE]",
                            "[CASCADE_ZERO]", "[MONITOR]", "[RECOVER_GATE]",
                            "[PROG_GATE]", "[Z4 GATE]"):
                    if tag in line:
                        counts[tag] += 1
                        break
                if "[noupdate stale=" in line:
                    stale.append(line.strip())
                    counts["[noupdate]"] += 1
    except Exception as e:
        print(f"  [warn] log parse failed: {e!r}")
    return decisions, stages, evals, counts, stale


def _timeseries_queue(folder):
    """Per-intersection mean queue_veh early (t<1800) vs late (t>3600)."""
    path = os.path.join(folder, "section_timeseries.csv")
    if not os.path.isfile(path):
        return {}, False
    early = defaultdict(lambda: [0.0, 0])
    late = defaultdict(lambda: [0.0, 0])
    try:
        with open(path, "r", newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                try:
                    t = float(r.get("t_start_s", 0) or 0)
                    q = float(r.get("queue_veh", 0) or 0)
                    j = str(r.get("IntersectionID", "?")).strip()
                except Exception:
                    continue
                if t < 1800:
                    early[j][0] += q
                    early[j][1] += 1
                elif t > 3600:
                    late[j][0] += q
                    late[j][1] += 1
    except Exception:
        return {}, False
    out = {}
    for j in set(list(early) + list(late)):
        e = early[j][0] / early[j][1] if early[j][1] else 0.0
        l = late[j][0] / late[j][1] if late[j][1] else 0.0
        out[j] = (e, l)
    return out, True


def main():
    ap = argparse.ArgumentParser(description="Blame why a TSP run lost to NO_TSP.")
    ap.add_argument("--tsp", required=True, help="TSP run folder (results/<exp>_seedN_*/)")
    ap.add_argument("--base", required=True, help="NO_TSP baseline run folder (same seed)")
    ap.add_argument("--reward-csv", default=None, help="reward_cycle_*.csv for the TSP run")
    ap.add_argument("--log", default=None, help="Aimsun_TSP_Log_*.txt for the TSP run")
    ap.add_argument("--top", type=int, default=8, help="junctions to blame (default 8)")
    ap.add_argument("--out", default=None, help="also write report to this file")
    a = ap.parse_args()

    out_lines = []

    def emit(s=""):
        print(s)
        out_lines.append(s)

    for label, p in (("TSP", a.tsp), ("BASE", a.base)):
        if not os.path.isdir(p):
            emit(f"ERROR: {label} folder not found: {p}")
            return 2

    g_t = _read_first_row(os.path.join(a.tsp, "simulation_results.csv"))
    g_b = _read_first_row(os.path.join(a.base, "simulation_results.csv"))
    if not g_t or not g_b:
        emit("ERROR: missing simulation_results.csv in one folder.")
        return 2

    def gk(g, *keys):
        for k in keys:
            if g.get(k) not in (None, ""):
                return _f(g.get(k))
        return 0.0

    obj_t = gk(g_t, "Objective_PaxPerDelayHr")
    obj_b = gk(g_b, "Objective_PaxPerDelayHr")
    bus_t = gk(g_t, "AvgBusPassDelay_s")
    bus_b = gk(g_b, "AvgBusPassDelay_s")
    car_t = gk(g_t, "AvgCarPassDelay_s")
    car_b = gk(g_b, "AvgCarPassDelay_s")
    tot_t = gk(g_t, "TotalPassDelay_hrs")
    tot_b = gk(g_b, "TotalPassDelay_hrs")
    main_t = gk(g_t, "MainPassDelay_hrs")
    main_b = gk(g_b, "MainPassDelay_hrs")
    side_t = gk(g_t, "SidePassDelay_hrs")
    side_b = gk(g_b, "SidePassDelay_hrs")
    ext_t = gk(g_t, "TSP_Extensions")
    ins_t = gk(g_t, "TSP_Insertions")
    exp_t = str(g_t.get("ExperimentID", g_t.get("TSP_Strategy", "?")))
    exp_b = str(g_b.get("ExperimentID", g_b.get("TSP_Strategy", "?")))

    emit("=" * 72)
    emit(f"BLAME REPORT: {exp_t}  vs  {exp_b} (baseline)")
    emit(f"  tsp : {os.path.abspath(a.tsp)}")
    emit(f"  base: {os.path.abspath(a.base)}")
    emit("=" * 72)
    dobj = (obj_t - obj_b) / obj_b * 100.0 if obj_b else 0.0
    emit(f"Global: obj {obj_b:.1f} -> {obj_t:.1f} ({dobj:+.1f}%)  "
         f"| bus {bus_b:.1f}s -> {bus_t:.1f}s ({bus_t-bus_b:+.1f}s)  "
         f"| car {car_b:.1f}s -> {car_t:.1f}s ({car_t-car_b:+.1f}s)")
    emit(f"        total delay {tot_b:.1f}h -> {tot_t:.1f}h ({tot_t-tot_b:+.1f}h)  "
         f"[main {main_t-main_b:+.1f}h / side {side_t-side_b:+.1f}h]  "
         f"actions ext={ext_t:.0f} ins={ins_t:.0f}")
    if dobj >= 0:
        emit("Verdict: TSP did NOT lose on objective -- blame ranking below is "
             "informational (where the gains/costs landed).")
    else:
        drv = "car-driven" if (car_t - car_b) > max(0.5, abs(bus_t - bus_b)) else \
              "bus+car" if bus_t > bus_b else "car-driven (buses helped, cars paid more)"
        emit(f"Verdict: TSP LOST ({dobj:.1f}%). Loss is {drv}.")
    emit("")

    # ── Per-junction blame ──
    it = _filter_run_rows(_read_rows(os.path.join(a.tsp, "simulation_results_per_intersection.csv")), g_t)
    ib = _filter_run_rows(_read_rows(os.path.join(a.base, "simulation_results_per_intersection.csv")), g_b)
    mb = {str(r.get("IntersectionID", "")).strip(): r for r in ib}
    blame = []
    for r in it:
        j = str(r.get("IntersectionID", "")).strip()
        b = mb.get(j)
        if b is None:
            continue
        dt = _f(r.get("TotalPassDelay_hrs")) - _f(b.get("TotalPassDelay_hrs"))
        dm = _f(r.get("MainPassDelay_hrs")) - _f(b.get("MainPassDelay_hrs"))
        ds = _f(r.get("SidePassDelay_hrs")) - _f(b.get("SidePassDelay_hrs"))
        db = _f(r.get("AvgBusPassDelay_s")) - _f(b.get("AvgBusPassDelay_s"))
        dc = _f(r.get("AvgCarPassDelay_s")) - _f(b.get("AvgCarPassDelay_s"))
        blame.append({"j": j, "dt": dt, "dm": dm, "ds": ds, "db": db, "dc": dc,
                      "ext": _f(r.get("TSP_Extensions")), "ins": _f(r.get("TSP_Insertions")),
                      "det": _f(r.get("TSP_Detections")),
                      "q": _f(r.get("AvgQueue_veh")), "qb": _f(b.get("AvgQueue_veh"))})
    blame.sort(key=lambda d: -d["dt"])
    emit(f"--- WHERE: per-junction blame (top {a.top} by added pax-hours) ---")
    emit(f"  {'jct':>8s} {'+tot_h':>7s} {'+main':>7s} {'+side':>7s} "
         f"{'+bus_s':>7s} {'+car_s':>7s} {'ext':>4s} {'ins':>4s} {'q':>5s}")
    for d in blame[:a.top]:
        emit(f"  {d['j']:>8s} {d['dt']:7.2f} {d['dm']:7.2f} {d['ds']:7.2f} "
             f"{d['db']:7.1f} {d['dc']:7.1f} {d['ext']:4.0f} {d['ins']:4.0f} "
             f"{d['q']:5.1f}")
    if not blame:
        emit("  (no matched IntersectionIDs -- check the two folders are same-seed runs)")
    emit("  Read: +side-heavy loss = cross-street cascade (side cost under-priced); "
         "+main-heavy = progression/offset break on the corridor.")
    emit("")

    # ── Action attribution ──
    rcsv = a.reward_csv
    auto_note = ""
    if rcsv is None:
        rcsv, _log_auto, logdir = _autofind_logs(a.tsp)
        auto_note = f" (auto: newest in {logdir})" if rcsv else ""
    ledger, n_chosen = ({}, 0)
    if rcsv and os.path.isfile(rcsv):
        ledger, n_chosen = _parse_reward_ledger(rcsv)
        emit(f"--- WHAT ACTION: ledger {os.path.basename(rcsv)}{auto_note} "
             f"({n_chosen} chosen commits) ---")
        for d in blame[:a.top]:
            L = ledger.get(d["j"])
            if not L:
                emit(f"  jct {d['j']}: no ledger commits (loss without acting here "
                     f"-- cascade victim, look upstream).")
                continue
            st = ",".join(f"{k}:{v}" for k, v in sorted(L["stages"].items()))
            ak = ",".join(f"{k}:{v}" for k, v in sorted(L["actions"].items()))
            emit(f"  jct {d['j']}: n={L['n']} pred_net={L['net']:.0f}paxs "
                 f"(bus {L['bus']:.0f}/other {L['other']:.0f}/side {L['side']:.0f}, "
                 f"chain {L['chain']:.0f}) [{ak}] stages[{st}]")
            if L["net"] < 0:
                emit(f"      -> predicted NEGATIVE: gate failure (veto/net-benefit "
                     f"should have blocked these). Tighten veto/gates.")
            elif d["dt"] > 0:
                emit(f"      -> predicted positive yet realized +{d['dt']:.2f}h: model "
                     f"miscalibration (cross/cascade under-priced). Check [BXT_EVAL] "
                     f"realized_adv below + [MEAS_SIDE]/[CASCADE] engagement.")
    else:
        emit("--- WHAT ACTION: (no reward ledger; pass --reward-csv "
             "reward_cycle_<exp>_*.csv from <corridor>/logs/ for per-action "
             "predicted bus/other/side/net + stage) ---")
        for d in blame[:a.top]:
            if d["ext"] + d["ins"] > 0:
                emit(f"  jct {d['j']}: ext={d['ext']:.0f} ins={d['ins']:.0f} "
                     f"det={d['det']:.0f} added {d['dt']:+.2f}h "
                     f"(bus {d['db']:+.1f}s / car {d['dc']:+.1f}s)")
    emit("")

    # ── Log evidence ──
    logp = a.log
    if logp is None:
        _, logp, _ = _autofind_logs(a.tsp)
    if logp and os.path.isfile(logp):
        decisions, stages, evals, counts, stale = _parse_run_log(logp)
        emit(f"--- LOG EVIDENCE: {os.path.basename(logp)} ---")
        emit(f"  counts: " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        for d in blame[:a.top]:
            j = d["j"]
            bits = []
            if j in stages:
                bits.append(stages[j])
            if j in decisions:
                bits.append(f"{len(decisions[j])} [DECISION] commits; e.g. {decisions[j][0][:160]}")
            if j in evals and evals[j]:
                ev = evals[j]
                bits.append(f"[BXT_EVAL] n={len(ev)} mean_realized_adv={sum(ev)/len(ev):.0f}paxs "
                            f"{'(negative = model over-promised)' if sum(ev)/len(ev) < 0 else ''}")
            if bits:
                emit(f"  jct {j}:")
                for b in bits:
                    emit(f"    {b}")
        if stale:
            emit(f"  [noupdate] stale counters ({len(stale)}): e.g. {stale[0][:200]}")
            emit("    -> vehicles present but never counted: check detector/section mapping, "
                 "not the TSP logic.")
        else:
            emit("  [noupdate]: none -- counters healthy (roll_ctr=0 lines before ~300 s "
                 "are warm-up, not faults).")
    else:
        emit("--- LOG EVIDENCE: (no run log; pass --log Aimsun_TSP_Log_*.txt for "
             "[DECISION]/[FLOW_STAGE]/[BXT_EVAL]/[VIABILITY]/[noupdate]) ---")
    emit("")

    # ── Cascade window ──
    qt, has_t = _timeseries_queue(a.tsp)
    qb, has_b = _timeseries_queue(a.base)
    if has_t and has_b:
        emit("--- CASCADE: mean queue_veh early(<30min) -> late(>60min), TSP vs BASE ---")
        for d in blame[:a.top]:
            j = d["j"]
            te = qt.get(j, (0, 0))
            be = qb.get(j, (0, 0))
            emit(f"  jct {j}: tsp {te[0]:.1f}->{te[1]:.1f}  base {be[0]:.1f}->{be[1]:.1f}  "
                 f"{'(grew late under TSP = cascade/blackspot)' if te[1] > be[1] + 1.0 else ''}")
    else:
        emit("--- CASCADE: (section_timeseries.csv missing in a folder -- "
             "per-junction main/side split above is the cascade proxy) ---")
    emit("")
    emit("Next step: re-run the TSP arm with BXT_EVAL_DIAGNOSTICS=1 (CELLQLEARN) or "
         "MEASURED_SIDE_COST_DIAG=1 and diff again -- predicted-positive/realized-negative "
         "junctions name the miscalibrated cost term.")
    emit("=" * 72)

    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.write("\n".join(out_lines) + "\n")
            print(f"Wrote {a.out}")
        except Exception as e:
            print(f"[warn] could not write {a.out}: {e!r}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
