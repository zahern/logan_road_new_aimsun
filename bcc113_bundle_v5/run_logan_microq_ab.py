"""run_logan_microq_ab.py -- single-seed paired A/B: MICRO_QUEUE_MODE on vs off.

Answers one question: does counting only STOPPED/SLOW vehicles as the queue
(Aimsun's own <5 km/h definition) change the scored outcome, or is the detector
feed already doing that job?

WHY THIS PAIR (2026-11-02)
  _zone_queue_count counts every in-zone vehicle unless MICRO_QUEUE_MODE is on.
  After the CTM seed fix, _ctm_cross_cost_paxs seeds its cell chain directly from
  _zone_queue_count on the CONFLICTING approach -- there is no detector-feed
  preference on that path (unlike _measured_main_queue_veh, which prefers
  stats.latest_section). So the flag now moves the seed of every CTM chain
  evaluation, plus the _compute_side_delay_penalty turn/fallback paths and the
  _measured_main_queue_veh live fallback. Whether that moves the OBJECTIVE is an
  empirical question -- hence a paired run, not an argument.

ARMS (2 + the suite's automatic NO_TSP baseline, all on the same build/seed):
  CHAMP_ADAPTIVE_DSW_GAME_BUS_LOGAN         control  -- the published champion
  CHAMP_ADAPTIVE_DSW_GAME_BUS_LOGAN_MICROQ  treated  -- same arm, ONLY
                                                       MICRO_QUEUE_MODE=True
Nothing else differs, so any metric difference is attributable to the flag.

RUN -- inside the Aimsun console, LOGAN ROAD model open, AFTER A FULL RESTART
(this build carries the 2026-11-02 engine changes, so the hash changes):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_logan_microq_ab.py").read())

Override the seed (default 600 = run_config.CURRENT_SEED, and a seed that already
has a published control row for the cross-check):

    import os; os.environ["MICROQ_SEED"] = "500"
    exec(open(r"...\\run_logan_microq_ab.py").read())

Re-read the CSV later WITHOUT Aimsun (no simulation calls, plain csv):

    MICROQ_REPORT_ONLY=1 python run_logan_microq_ab.py

READ THE OUTPUT
  A single seed cannot give significance: treat this as a direction check, and
  re-run the other seeds before quoting a percentage. Per Rule 3 never compare
  across different demand/build, and per Rule 4 do NOT read stats_N_BusTrips as
  throughput -- it is a sum of per-junction detection-window clearances. The
  physical corridor metrics (N_LoopCompletions / MeanLoopTT_s / LoopsPerBus) are
  reported instead, alongside passenger throughput.
"""
import csv as _csv
import os as _os

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

_SEED = (_os.environ.get("MICROQ_SEED", "600") or "600").strip()
_OUT = (_os.environ.get("MICROQ_OUT", "")
        or "logan_microq_ab_seed%s.csv" % _SEED).strip()

_CTRL = "CHAMP_ADAPTIVE_DSW_GAME_BUS_LOGAN"
_TREAT = "CHAMP_ADAPTIVE_DSW_GAME_BUS_LOGAN_MICROQ"
_BASE = "NO_TSP"

# (csv column, label, higher_is_better or None for "neutral", format).
# None = an ACTIVITY indicator: a change is worth knowing about but is not
# better or worse on its own. Order = report order.
_METRICS = [
    ("stats_Objective_PaxPerDelayHr", "Objective (pax / delay-hr)", True, "%.2f"),
    ("stats_TotalPassDelay_hrs", "Total passenger delay (h)", False, "%.2f"),
    ("stats_MainPassDelay_hrs", "  main delay (h)", False, "%.1f"),
    ("stats_SidePassDelay_hrs", "  side delay (h)", False, "%.1f"),
    ("stats_AvgBusPassDelay_s", "Bus delay / pax (s)", False, "%.1f"),
    ("stats_PaxEquivPassages", "Throughput: pax passages", True, "%.0f"),
    ("stats_BusPaxEquivPassages", "  bus pax passages", True, "%.0f"),
    ("stats_CarPaxEquivPassages", "  car pax passages", True, "%.0f"),
    ("stats_N_LoopCompletions", "Loop completions (corridor)", True, "%.0f"),
    ("stats_MeanLoopTT_s", "Mean loop travel time (s)", False, "%.1f"),
    ("stats_LoopsPerBus", "Loops per bus", True, "%.3f"),
    ("stats_TSP_Extensions", "GE actions (activity)", None, "%.0f"),
    ("stats_TSP_Insertions", "INS actions (activity)", None, "%.0f"),
    ("stats_TSP_EarlyRed", "ER actions (activity)", None, "%.0f"),
]


def _num(row, col):
    try:
        v = row.get(col, "")
        if v is None or str(v).strip() == "":
            return None
        return float(v)
    except Exception:
        return None


def _rows():
    path = _OUT if _os.path.isabs(_OUT) else _os.path.join(_HERE, _OUT)
    if not _os.path.isfile(path):
        print("no results CSV at", path)
        return path, {}
    out = {}
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        for r in _csv.DictReader(fh):
            try:
                seed = int(float(r.get("run_seed")))
            except Exception:
                continue
            if str(seed) != _SEED:
                continue
            out[(str(r.get("run_experiment", "")), seed)] = r
    return path, out


def _report():
    path, by = _rows()
    if not by:
        return
    seed = int(_SEED)
    c = by.get((_CTRL, seed))
    t = by.get((_TREAT, seed))
    n = by.get((_BASE, seed))

    print("=" * 92)
    print("MICRO_QUEUE_MODE A/B -- seed %d" % seed)
    print("  CSV      : %s" % path)
    print("  control  : %s  (MICRO_QUEUE_MODE = False)" % _CTRL)
    print("  treated  : %s  (MICRO_QUEUE_MODE = True)" % _TREAT)
    if c is None or t is None:
        print("  MISSING ROW: control=%s treated=%s" %
              (c is not None, t is not None))
        print("=" * 92)
        return
    print("=" * 92)

    hdr = "%-36s %12s %12s %12s %9s %s" % (
        "metric", "control", "microQ", "delta", "%", "verdict")
    print(hdr)
    print("-" * len(hdr))

    differed = []      # directional metrics that moved
    changed = []       # ANY metric that moved, including activity counts
    for col, label, hib, fmt in _METRICS:
        cv, tv = _num(c, col), _num(t, col)
        if cv is None and tv is None:
            print("%-36s %12s %12s %12s %9s %s"
                  % (label, "n/a", "n/a", "-", "-", "not recorded"))
            continue
        if cv is None or tv is None:
            print("%-36s %12s %12s %12s %9s %s"
                  % (label,
                     fmt % cv if cv is not None else "n/a",
                     fmt % tv if tv is not None else "n/a",
                     "-", "-", "one arm missing"))
            continue
        d = tv - cv
        pc = ("%+.1f%%" % (100.0 * d / cv)) if cv else ""
        if abs(d) <= 1e-9:
            verdict = "same"
        elif hib is None:
            verdict = "changed"          # activity only: no direction
            changed.append(col)
        else:
            differed.append(col)
            changed.append(col)
            better = (d > 0) == hib
            verdict = "BETTER" if better else "worse"
        print("%-36s %12s %12s %12s %9s %s"
              % (label, fmt % cv, fmt % tv, ("%+g" % round(d, 4)), pc, verdict))

    print("-" * len(hdr))
    if n is not None:
        nv = _num(n, "stats_Objective_PaxPerDelayHr")
        cv = _num(c, "stats_Objective_PaxPerDelayHr")
        if nv:
            print("  context  NO_TSP objective %.2f  (control %+.1f%%, microQ %+.1f%%)"
                  % (nv, 100.0 * (cv - nv) / nv if cv else 0.0,
                     100.0 * (_num(t, "stats_Objective_PaxPerDelayHr") - nv) / nv))
    else:
        print("  context  NO_TSP row missing for this seed")

    print("")
    if not changed:
        print("  VERDICT: INERT on this seed -- every reported metric is identical")
        print("           to the control. MICRO_QUEUE_MODE did not change a single")
        print("           decision, so the detector feed (MEASURED_QUEUE_FEED) is")
        print("           already supplying these quantities and the zone-count")
        print("           fallback never ran. Check the run log for")
        print("           [noupdate]/stale lines before concluding the flag is safe")
        print("           to leave off: it only matters where the feed is missing.")
    elif not differed:
        print("  VERDICT: decisions changed but NO scored metric moved on seed %d."
              % seed)
        print("           The flag reached the controller (action counts differ) but")
        print("           the queue re-measure did not survive to the outcome. Treat as")
        print("           inert-in-outcome: not worth a multi-seed campaign on its own.")
    else:
        print("  VERDICT: the flag moved %d metric(s) on seed %d (%d directional)."
              % (len(changed), seed, len(differed)))
        print("           Delay down + throughput/loops up = keep it on; delay up")
        print("           = the standing-queue count is over-throttling. ONE seed")
        print("           is a direction check only -- repeat on another seed")
        print("           before quoting a percentage.")
    print("=" * 92)


if __name__ == "__main__":
    _report_only = _os.environ.get("MICROQ_REPORT_ONLY", "0").strip() == "1"
    if not _report_only:
        _os.environ["ARM_SUITE_SEEDS"] = _SEED
        _os.environ["ARM_SUITE_ARMS"] = _CTRL + "," + _TREAT
        _os.environ["ARM_SUITE_OUT"] = _OUT
        _os.environ["ARM_SUITE_CORRIDOR"] = "logan_road_new"

        print("=" * 92)
        print("LOGAN MICRO_QUEUE_MODE A/B -- seed %s" % _SEED)
        print("  arms: %s" % (_CTRL + "," + _TREAT))
        print("  -> NO_TSP + 2 arms x 1 seed = 3 runs")
        print("  out : %s" % _os.path.join(_HERE, _OUT))
        print("  NOTE: full Aimsun restart required (engine build changed)")
        print("=" * 92)

        _runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
        exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
             {"__name__": "__main__"})

    _report()
