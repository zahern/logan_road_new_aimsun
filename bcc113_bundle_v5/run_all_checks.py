#!/usr/bin/env python3
"""run_all_checks.py -- every offline verification in one command.

    python run_all_checks.py [--full]

Runs (stdlib + local Python only, no Aimsun needed):
  1. FLOW LOGIC      test_flow_methods.py (windowed-flow/cap/queue math)
  2. TIMESERIES      check_timeseries.py on the newest run folder
  3. INTERSECTIONS   audit_intersections.py (--latest 20, or ALL with --full)
  4. RANKING         rank_champions.py champion lines (both modes)
  5. RUN HEALTH      newest results folder artifacts + newest TSP log scan
                     (VEH SCAN resolution, FATALs, probe blocks)

Exit 0 only if every section passes. --full audits all ~1800 run folders
(slow); default audits the 20 newest.
"""
import glob
import os
import re
import subprocess
import sys

def _bundle_root():
    # __file__ is undefined under console exec(); Aimsun's cwd is its install
    # dir -- neither locates the bundle. The bundle is wherever
    # champion_search.py lives: check __file__ dir, cwd, then the known path.
    _cands = []
    try:
        if "__file__" in dir():
            _cands.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    _cands.append(os.getcwd())
    _cands.append(r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5")
    for _c in _cands:
        if os.path.isfile(os.path.join(_c, "champion_search.py")):
            return _c
    return _cands[-1]


ROOT = _bundle_root()
FULL = "--full" in sys.argv
VERDICTS = []

# Inside the Aimsun console, sys.executable is Aimsun Next.exe itself -- using
# it for subprocesses would relaunch Aimsun once per check. Detect that and
# run every check in-process instead (no popups, much faster).
_IN_AIMSUN = "aimsun" in (sys.executable or "").lower()


def _run_in_process(script, args):
    """Execute a check script in this interpreter. Returns True on pass."""
    import importlib.util
    import traceback
    path = os.path.join(ROOT, script)
    saved_argv = sys.argv[:]
    try:
        if script == "test_flow_methods.py":
            # No main() guard: exec with a non-main name still runs it fully
            # (all work is top-level); failure raises SystemExit(1).
            try:
                src = open(path, encoding="utf-8").read()
                exec(compile(src, script, "exec"), {"__name__": "__checks__"})
                return True
            except SystemExit as e:
                return not (e.code or 0)
        # Fresh module object per run (console may hold stale copies).
        mod_name = "_checks_" + os.path.splitext(os.path.basename(script))[0]
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        sys.argv = [script, *args]
        if script == "rank_champions.py":
            # Top-level execution on import; success = no exception.
            spec.loader.exec_module(mod)
            return True
        spec.loader.exec_module(mod)
        if script == "check_timeseries.py":
            folder = args[0] if args else mod._find_latest()
            if not folder:
                print("    no run folder found")
                return False
            return mod.main(folder) == 0
        if script == "audit_intersections.py":
            return mod.main() == 0
        return False
    except SystemExit as e:
        return not (e.code or 0)
    except Exception:
        traceback.print_exc()
        return False
    finally:
        sys.argv = saved_argv


def _run(title, script, args=()):
    print("=" * 70)
    if _IN_AIMSUN:
        print(f"[CHECK] {title}: {script} {' '.join(args)} (in-process)".rstrip())
    else:
        print(f"[CHECK] {title}: python {script} {' '.join(args)}".rstrip())
    print("=" * 70)
    if _IN_AIMSUN:
        ok = _run_in_process(script, args)
        VERDICTS.append((title, ok))
        print(f"  -> {'PASS' if ok else 'FAIL'}")
        return ok
    try:
        p = subprocess.run(
            [sys.executable, os.path.join(ROOT, script), *args],
            cwd=ROOT, capture_output=True, text=True, timeout=900)
        out = (p.stdout or "") + (p.stderr or "")
        lines = out.strip().splitlines()
        # Show the tail (verdicts live at the end) plus any FAIL/WARN lines.
        keep = [ln for ln in lines if re.search(r"FAIL|WARN|VERDICT|PASS|CHAMPION|champion", ln)]
        tail = lines[-6:] if len(lines) > 20 else lines
        shown = set()
        for ln in tail:
            if ln not in shown:
                print("   ", ln[:150])
                shown.add(ln)
        for ln in keep:
            if ln not in shown:
                print("   ", ln[:150])
                shown.add(ln)
        ok = (p.returncode == 0)
    except subprocess.TimeoutExpired:
        print("    TIMEOUT after 900 s")
        ok = False
    except Exception as e:
        print(f"    harness error: {e!r}")
        ok = False
    VERDICTS.append((title, ok))
    print(f"  -> {'PASS' if ok else 'FAIL'}")
    return ok


def _newest(pattern_dir, pattern_file):
    # Newest FINISHED run: section_timeseries.csv alone may belong to a
    # replication still simulating; require simulation_results.csv too.
    best = None
    for root in dict.fromkeys((ROOT, r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5")):
        base = os.path.join(root, pattern_dir)
        if not os.path.isdir(base):
            continue
        for path in glob.glob(os.path.join(base, "*", pattern_file)):
            folder = os.path.dirname(path)
            if not os.path.isfile(os.path.join(folder, "simulation_results.csv")):
                continue
            try:
                mt = os.path.getmtime(path)
            except OSError:
                continue
            if best is None or mt > best[0]:
                best = (mt, path)
    return best[1] if best else None


def _run_health():
    print("=" * 70)
    print("[CHECK] RUN HEALTH: newest artifacts + newest TSP log")
    print("=" * 70)
    ok = True
    ts = _newest(os.path.join("kg", "results"), "section_timeseries.csv")
    if ts is None:
        for corr in ("kg", "logan_road_new"):
            ts = _newest(os.path.join(corr, "results"), "section_timeseries.csv")
            if ts:
                break
    if ts is None:
        print("    FAIL: no section_timeseries.csv anywhere")
        VERDICTS.append(("RUN HEALTH (artifacts)", False))
        return False
    folder = os.path.dirname(ts)
    print(f"    newest run: {os.path.basename(folder)}")
    expected = ("api_probe.log", "bus_schedule_deviation.csv", "bus_trips.csv",
                "schedule_summary.json", "section_stats.csv",
                "section_timeseries.csv", "signal_wait_summary.json",
                "simulation_results.csv",
                "simulation_results_per_intersection.csv", "summary.json")
    missing = [f for f in expected if not os.path.isfile(os.path.join(folder, f))]
    if missing:
        print(f"    FAIL: missing artifacts: {missing}")
        ok = False
    else:
        print("    artifacts: all 10 present")

    # Shadow-package check: any shared_tsp_engine/engine.py OUTSIDE this bundle
    # can shadow the real engine inside Aimsun (proven 2026-09-06: pre-Sept
    # engine executed while the bundle had newer code). The controller guard
    # pins the bundle first, but a new stray copy still deserves a warning.
    # Bounded scan (depth <= 2 under the workspace root): shadowing only
    # matters for top-level packages, and results/ trees are huge.
    try:
        _parent = os.path.dirname(ROOT)
        _mine = os.path.abspath(
            os.path.join(ROOT, "shared_tsp_engine", "engine.py")).lower()
        _shadows = []
        for _entry in sorted(os.listdir(_parent)):
            _p1 = os.path.join(_parent, _entry)
            if not os.path.isdir(_p1) or _entry.startswith("."):
                continue
            if _entry == "shared_tsp_engine":
                _cand = os.path.join(_p1, "engine.py")
                if (os.path.isfile(_cand)
                        and os.path.abspath(_cand).lower() != _mine):
                    _shadows.append(_cand)
                continue
            if _entry in ("kg", "logan_road_new"):
                continue  # inside this bundle: corridor dirs, no engine copies
            _p2 = os.path.join(_p1, "shared_tsp_engine", "engine.py")
            if (os.path.isfile(_p2)
                    and os.path.abspath(_p2).lower() != _mine):
                _shadows.append(_p2)
        if _shadows:
            print("    WARN: foreign shared_tsp_engine copies (shadowing risk):")
            for _s in _shadows[:6]:
                print(f"      {_s}")
    except Exception as _e:
        print(f"    WARN: shadow scan failed: {_e}")
    _ap = os.path.join(folder, "api_probe.log")
    try:
        with open(_ap, encoding="utf-8", errors="replace") as fh:
            _apt = fh.read()
        for tag in ("[ESTAD-PROBE]", "[FLOW-AUDIT]"):
            print(f"    api_probe {tag}: {_apt.count(tag)} line(s)")
        if "[ESTAD-PROBE]" not in _apt and "[FLOW-AUDIT]" not in _apt:
            print("    WARN: api_probe.log has no probe blocks "
                  "(pre-gating controller or warmup-only run?)")
    except OSError:
        print("    WARN: api_probe.log unreadable")

    log = None
    for corr in ("kg", "logan_road_new"):
        for path in glob.glob(os.path.join(
                ROOT, corr, "logs", "Aimsun_TSP_Log_*.txt")):
            if log is None or os.path.getmtime(path) > os.path.getmtime(log):
                log = path
    if log is None:
        print("    WARN: no TSP log found")
    else:
        print(f"    newest log: {os.path.basename(log)}")
        try:
            with open(log, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = ""
        m = re.search(r"\[VEH TYPES\].*?using car=(-?\d+) bus=(-?\d+) truck=(-?\d+)",
                      text)
        if m:
            c, b, t = int(m.group(1)), int(m.group(2)), int(m.group(3))
            good = c > 0 and b > 0 and t > 0 and len({c, b, t}) == 3
            print(f"    VEH TYPES resolved car/bus/truck = {(c, b, t)} "
                  f"({'OK' if good else 'BROKEN'})")
            ok = ok and good
        else:
            print("    WARN: no [VEH TYPES] line in newest log")
        fatals = re.findall(r"FATAL[^\n]{0,100}", text)
        # Parked-arm FATALs are a known, deliberate condition (MILP_MPC's
        # solver backend cannot load in Aimsun's interpreter -- [WinError 127]
        # -- so the arm is parked in champion_search.PARKED_ARMS). Downgrade
        # those to a warning; any OTHER FATAL still fails.
        _parked_pat = re.compile(r"MILP_MPC.*could not be imported")
        _real = [f for f in fatals if not _parked_pat.search(f)]
        _parked_n = len(fatals) - len(_real)
        if _parked_n:
            print(f"    WARN: {_parked_n} parked-arm FATAL line(s) "
                  f"(MILP_MPC import -- arm is parked, expected)")
        if _real:
            print(f"    FAIL: {len(_real)} FATAL line(s), e.g.: {_real[0][:120]}")
            ok = False
        elif not _parked_n:
            print("    FATALs: none")
    VERDICTS.append(("RUN HEALTH", ok))
    print(f"  -> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    print("#" * 70)
    print("# FULL OFFLINE VERIFICATION" + (" (FULL intersection sweep)" if FULL else ""))
    print("#" * 70)
    _run("FLOW LOGIC", "test_flow_methods.py")
    _run("TIMESERIES (newest run)", "check_timeseries.py")
    if FULL:
        _run("INTERSECTIONS (all folders)", "audit_intersections.py")
    else:
        _run("INTERSECTIONS (20 newest)", "audit_intersections.py",
             ("--latest", "20"))
    _run("RANKING", "rank_champions.py", ("--rank-by", "obj",))
    _run_health()
    print("#" * 70)
    print("SUMMARY")
    print("#" * 70)
    all_ok = True
    for title, ok in VERDICTS:
        all_ok = all_ok and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {title}")
    print("#" * 70)
    print(f"OVERALL: {'PASS -- everything checks out' if all_ok else 'FAIL -- see sections above'}")
    print("#" * 70)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
