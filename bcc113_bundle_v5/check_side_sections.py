"""
check_side_sections.py -- 1-run SIDE-SECTION sanity check (NOT the full search).

Runs ONE NO_TSP replication on the open corridor, then reads the per-junction
side-section report the stats layer writes during the run and prints:
  - per-junction: n_main, n_side, source (conflicting_sg | topology | config | none)
  - corridor totals + a source breakdown
  - PASS/FAIL

RUN inside Aimsun, model open:   check_side_sections.py

PASS when: the corridor side-section total is TRIMMED (not the old whole-corridor
dump, e.g. Logan's 84) AND most junctions resolved via 'conflicting_sg' with a
small per-junction side list (the immediate cross approaches).

Self-diagnosing: prints [SIDECHK] markers and a traceback on any error.
"""
import os as _os
import sys as _sys
import csv as _csv
import traceback as _tb
import importlib.util as _ilu


def _say(msg):
    try:
        print("[SIDECHK] " + str(msg))
    except Exception:
        pass


_say("starting check_side_sections.py")


def _load_champion_search():
    # exec(open(...).read()) in the Aimsun console never sets __file__, and
    # the console cwd is the Aimsun install dir -- so probe candidate homes
    # (same convention as run_probe.py) instead of trusting either one.
    _cands = []
    try:
        if "__file__" in dir():
            _cands.append(_os.path.dirname(_os.path.abspath(__file__)))
    except NameError:
        pass
    _cands.append(r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5")
    try:
        _cands.append(_os.path.abspath(_os.getcwd()))
    except Exception:
        pass
    here = None
    for _c in _cands:
        if _os.path.isfile(_os.path.join(_c, "champion_search.py")):
            here = _c
            break
    if here is None:
        raise RuntimeError("champion_search.py not found (tried: "
                           + ", ".join(_cands) + ")")
    if here not in _sys.path:
        _sys.path.insert(0, here)
    cs_path = _os.path.join(here, "champion_search.py")
    if not _os.path.isfile(cs_path):
        raise RuntimeError("champion_search.py must sit next to this file (" + here + ")")
    spec = _ilu.spec_from_file_location("champion_search", cs_path)
    mod = _ilu.module_from_spec(spec)
    _sys.modules["champion_search"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run():
    cs = _load_champion_search()
    br = cs._br
    log = br.log
    CORRIDOR = cs.CORRIDOR
    CORR_DIR = cs.CORR_DIR
    CONTROLLER_PATH = br.CONTROLLER_PATH
    RUN_CONFIG_PATH = br.RUN_CONFIG_PATH
    PROJECT_DIR = br.PROJECT_DIR
    RESULTS_CSV = _os.path.join(cs._ROOT, "side_sections_check_" + CORRIDOR + ".csv")
    REPORT = _os.path.join(CORR_DIR, "side_sections_report.csv")

    _say("corridor=" + CORRIDOR + " | running 1x NO_TSP seed 300 to resolve sections")
    try:
        if _os.path.exists(REPORT):
            _os.remove(REPORT)   # ensure we read THIS run's report
    except Exception:
        pass
    try:
        br._set_logging(CONTROLLER_PATH, enabled=False)
    except Exception:
        pass
    try:
        cs._disable_batch_plotting(CONTROLLER_PATH)
    except Exception:
        pass
    try:
        br.set_control_mode("NORMAL", CONTROLLER_PATH, None)
        br.set_coordinated(CONTROLLER_PATH, False)
        br.set_coordination_algo(CONTROLLER_PATH, "KALMAN")
        br.set_reward_weights(CONTROLLER_PATH, None)
    except Exception as e:
        _say("WARN patch: " + repr(e))
    try:
        cs._set_controller_bxt_seeds(CONTROLLER_PATH, [], [], cs.BXT_TRAIN_EPSILON)
    except Exception:
        pass
    try:
        br.set_demand_scalar(1.0, {})
    except Exception:
        pass

    _say("starting the replication (resolves main/side sections at sim-ready)")
    rep = br.get_first_replication()
    cs._run_and_collect(
        br, rep, "NO_TSP", "NORMAL", 300, 1.0, False, "KALMAN",
        False, None, "ADAPTIVE_KALMAN",
        CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, RESULTS_CSV, log)
    try:
        br._set_logging(CONTROLLER_PATH, enabled=True)
    except Exception:
        pass

    if not _os.path.isfile(REPORT):
        _say("RESULT: FAIL -- no side_sections_report.csv was written at " + REPORT)
        _say("   (the run may not have reached _resolve_side_sections; check the log)")
        return

    rows = []
    diags = []
    try:
        with open(REPORT, newline="", encoding="utf-8") as f:
            _lines = f.read().splitlines()
        diags = [ln[len("#diag "):] for ln in _lines if ln.startswith("#diag ")]
        _data = [ln for ln in _lines if not ln.startswith("#diag ")]
        rows = list(_csv.DictReader(_data))
    except Exception as e:
        _say("RESULT: FAIL -- could not read report: " + repr(e))
        return

    if diags:
        _say("conflicting-SG diagnostics (why it fell back, per junction):")
        for d0 in diags[:12]:
            _say("  DIAG: " + d0)
        if len(diags) > 12:
            _say("  ... (%d more)" % (len(diags) - 12))
    else:
        _say("NOTE: no #diag lines in report -- the conflicting-SG method was "
             "never entered (stale code?) or produced sections without fallback.")

    _say("-" * 66)
    _say("%-14s %6s %6s  %s" % ("junction", "nMain", "nSide", "source"))
    total_side = 0
    total_main = 0
    src_counts = {}
    big = []
    for r in rows:
        try:
            ns = int(r["n_side"]); nm = int(r["n_main"])
        except Exception:
            ns = nm = 0
        src = r.get("source", "?")
        total_side += ns
        total_main += nm
        src_counts[src] = src_counts.get(src, 0) + 1
        if ns > 8:
            big.append((r["intersection_id"], ns))
        _say("%-14s %6d %6d  %s" % (r.get("intersection_id", "?"), nm, ns, src))
    _say("-" * 66)
    njn = len(rows)
    _say("junctions            = %d" % njn)
    _say("total MAIN sections  = %d" % total_main)
    _say("total SIDE sections  = %d   (was ~84 corridor-wide before the fix)" % total_side)
    _say("avg side/junction    = %.1f" % (total_side / njn if njn else 0.0))
    _say("source breakdown     = " + ", ".join("%s:%d" % (k, v) for k, v in sorted(src_counts.items())))
    if big:
        _say("junctions with >8 side sections: " + str(big))
    _say("-" * 66)

    n_conf = src_counts.get("conflicting_sg", 0)
    avg_side = (total_side / njn) if njn else 0.0
    ok_trim = (njn > 0 and avg_side <= 8.0 and total_side < 84)
    ok_method = (n_conf >= max(1, njn // 2))   # at least half via conflicting_sg
    if ok_trim and ok_method:
        _say("RESULT: PASS -- side sections trimmed AND mostly conflicting-signal-group.")
    elif ok_trim:
        _say("RESULT: PARTIAL -- side count is trimmed, but many junctions fell back to")
        _say("        'topology' (conflicting_sg=%d/%d). The GKSignalGroup->section" % (n_conf, njn))
        _say("        API likely didn't resolve; send Zeke a 'conflicting-SG resolution")
        _say("        failed:' line from the log so the exact call can be fixed.")
    else:
        _say("RESULT: FAIL -- side sections still large (avg %.1f/junction, total %d)." % (avg_side, total_side))
        _say("        -> copy this whole [SIDECHK] block back to Zeke.")


try:
    _run()
    _say("finished.")
except Exception:
    _say("FAILED with an exception -- traceback below:")
    _tb.print_exc()
