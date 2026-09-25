# run_sumo_hpc.py
# Drive shared_tsp_engine strategies on SUMO via the AAPI shim.
#
#   python run_sumo_hpc.py --corridor kg --strategy NO_TSP --seed 300
#   python run_sumo_hpc.py --corridor kg --scenario kg_scenario --smoke   # plumbing test
#
# One OS process per seed => embarrassingly parallel on HPC:
#   for s in 300 400 500; do python run_sumo_hpc.py --seed $s ... & done

import argparse
import importlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))


def find_sumo_home():
    sh = os.environ.get("SUMO_HOME")
    if sh and os.path.isdir(sh):
        return sh
    for cand in (r"C:\Program Files\Eclipse\Sumo", r"C:\Program Files (x86)\Eclipse\Sumo"):
        if os.path.isdir(cand):
            return cand
    # POSIX fallback: locate the binary on PATH and derive its install root
    import shutil as _sh
    w = _sh.which("sumo")
    if w:
        real = os.path.realpath(w)
        cand = os.path.dirname(os.path.dirname(real))     # <home>/bin/sumo
        return cand if os.path.isdir(cand) else os.path.dirname(real)
    return None


def force_utf8_text_open():
    """
    The engine/plot scripts open() files without encoding= and write unicode
    (arrows, >= signs) - on Windows that dies with cp1252 'charmap' errors.
    PYTHONUTF8 can't take effect after interpreter start, so redirect every
    text-mode open() without an explicit encoding to UTF-8.

    Bugfix (HPC sweep o25049273): the old wrapper forwarded leftover
    positionals alongside an injected encoding= keyword, so any call shaped
    open(f, mode, buf, enc, ...) raised
    "TypeError: argument for open() given by name ('encoding') and
     position (4)" and killed every sweep run at t=0.
    Now EVERY positional is normalized to its named parameter before the
    call, making a positional/keyword collision impossible; and on Linux
    (PYTHONUTF8 already active) the patch is skipped outright.
    """
    import builtins
    import io
    import sys as _sys
    if _sys.platform != "win32" or _sys.flags.utf8_mode:
        return                      # POSIX + PYTHONUTF8: nothing to fix

    _orig_open = builtins.open
    _ORDER = ("buffering", "encoding", "errors", "newline",
              "closefd", "opener")   # open()'s positional parameter order

    def _open(file, mode="r", *args, **kwargs):
        args = list(args)
        for name in _ORDER:         # fold positionals into named params,
            if not args:            # in open()'s own canonical order
                break
            if name in kwargs:
                raise TypeError("open() got multiple values for %r" % name)
            kwargs[name] = args.pop(0)
        if "b" not in mode and kwargs.get("encoding") is None:
            kwargs["encoding"] = "utf-8"
        return _orig_open(file, mode, **kwargs)

    builtins.open = _open
    io.open = _open

    # same story for console prints (engine logs contain >= / arrows)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corridor", required=True, choices=["kg", "logan_road_new"])
    ap.add_argument("--scenario", default=None, help="subdir under sumo_bridge/")
    ap.add_argument("--strategy", default="NO_TSP")
    ap.add_argument("--experiment", default=None)
    ap.add_argument("--seed", type=int, default=300)
    ap.add_argument("--end", type=float, default=3600.0)
    ap.add_argument("--step", type=float, default=1.0)
    ap.add_argument("--demand-scalar", type=float, default=1.0)
    ap.add_argument("--gui", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="skip strategy engine, exercise shim")
    ap.add_argument("--controller", default=None,
                    help="override intersection_controller.py path "
                         "(e.g. sandboxed copy for dry-runs)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="extra run_config.py line(s), e.g. "
                         "--set MP_ECTM_MODE=True --set Z4_TOLERANCE_VEH_S=300")
    args = ap.parse_args()
    force_utf8_text_open()

    scen = args.scenario or ("%s_scenario" % args.corridor)
    scen_dir = os.path.abspath(os.path.join(HERE, scen))
    cfg = os.path.join(scen_dir, "%s.sumocfg" % args.corridor)
    if not os.path.exists(cfg):
        sys.exit("scenario config missing: %s\nrun build_sumo_scenario.py first" % cfg)

    # ------------------------------------------------------------- paths/env
    shome = find_sumo_home()
    if not shome:
        sys.exit("SUMO_HOME not found")
    os.environ["SUMO_HOME"] = shome
    os.environ.setdefault("PYTHONUTF8", "1")   # engine writes unicode logs/CSVs
    os.environ.setdefault("MPLBACKEND", "Agg")  # headless plotting on HPC
    tools = os.path.join(shome, "tools")
    if os.path.isdir(tools) and tools not in sys.path:
        sys.path.insert(0, tools)

    corridor_dir = os.path.abspath(os.path.join(REPO_ROOT, args.corridor))
    for p in (HERE, REPO_ROOT):
        if p not in sys.path:
            sys.path.insert(0, p)

    # ------------------------------------------------------- install shim
    # MUST happen before any module does `from AAPI import *`
    import aapi_shim
    sys.modules["AAPI"] = aapi_shim

    # mirror the batch runners' run_config contract (back up the real one)
    results_csv = ("champion_kg.csv" if args.corridor == "kg"
                   else "batch_results_gui.csv")
    override_lines = []
    for kv in getattr(args, "set", []) or []:
        k, _, v = kv.partition("=")
        k = k.strip()
        if k:
            override_lines.append("%s = %s" % (k, v.strip()))

    if args.controller:
        # sandboxed controller: keep run_config + outputs next to it
        controller = os.path.abspath(args.controller)
        if os.path.isdir(controller):
            controller = os.path.join(controller, "intersection_controller.py")
        work_rc = os.path.join(os.path.dirname(controller), "run_config.py")
    else:
        rc_path = os.path.join(corridor_dir, "run_config.py")
        rc_bak = rc_path + ".bak"
        if os.path.exists(rc_path) and not os.path.exists(rc_bak):
            with open(rc_path, encoding="utf-8") as f:
                src = f.read()
            with open(rc_bak, "w", encoding="utf-8") as f:
                f.write(src)
        work_rc = rc_path
        controller = os.path.join(corridor_dir, "intersection_controller.py")

    with open(work_rc, "w", encoding="utf-8") as f:
        f.write(
            "CURRENT_STRATEGY = %r\n"
            "CURRENT_EXPERIMENT = %r\n"
            "CURRENT_SEED = %d\n"
            "CURRENT_DEMAND_SCALAR = %r\n"
            "CURRENT_COORDINATED = True\n"
            "RESULTS_CSV_NAME = %r\n"
            % (args.strategy,
               args.experiment or "%s_seed%d" % (args.strategy, args.seed),
               args.seed, args.demand_scalar, results_csv))
        for line in override_lines:
            f.write(line + "\n")

    # engine detects corridor via cwd / *.ang.lck; sandboxed controllers win
    # via explicit --controller (we exec it ourselves, Aimsun-style)
    workdir = os.path.dirname(controller)
    os.chdir(workdir)
    if workdir not in sys.path:
        sys.path.insert(0, workdir)

    # ------------------------------------------------------------ start sumo
    import traci
    if args.gui:
        binary = os.path.join(shome, "bin", "sumo-gui.exe")
        if not os.path.exists(binary):
            binary = os.path.join(shome, "bin", "sumo-gui")
        if not os.path.exists(binary):
            binary = _sh.which("sumo-gui") or "sumo-gui"
    else:
        binary = os.path.join(shome, "bin", "sumo.exe")
        if not os.path.exists(binary):
            # Linux wheels install the plain (no-.exe) binary under bin/
            binary = os.path.join(shome, "bin", "sumo")
        if not os.path.exists(binary):
            binary = _sh.which("sumo") or "sumo"
    cmd = [binary, "-c", cfg, "--seed", str(args.seed),
           "--step-length", str(args.step),
           "--no-step-log", "true"]
    print("[RUN] starting:", " ".join(cmd))
    traci.start(cmd, label="hpc_%d" % args.seed)
    conn = traci.getConnection("hpc_%d" % args.seed)

    aapi_shim.BRIDGE.init(conn, scen_dir,
                          replication_id=11129240, scenario_id=11129236,
                          experiment_id=11129237, step_length=args.step)

    try:
        if args.smoke:
            run_smoke(conn, aapi_shim.BRIDGE, args.end)
        else:
            run_engine(aapi_shim.BRIDGE, args,
                       os.path.abspath(args.controller) if args.controller else None)
    finally:
        conn.close()
    print("[RUN] done")


def run_engine(bridge, args, controller):
    import time as _t
    import aapi_shim
    import shared_tsp_engine.engine as eng
    if controller:
        if os.path.isdir(controller):
            controller = os.path.join(controller, "intersection_controller.py")
        if os.path.abspath(controller) != os.path.abspath(
                os.path.join(REPO_ROOT, args.corridor, "intersection_controller.py")):
            # sandboxed / alternate config shim: exec it so its bind_config()
            # footer populates engine globals exactly as Aimsun would
            ns = {"__file__": controller, "__name__": "intersection_controller"}
            with open(controller, "r", encoding="utf-8") as f:
                src = f.read()
            exec(compile(src, controller, "exec"), ns)
    w0 = _t.time()
    eng.AAPILoad()
    print("[RUN] AAPILoad %.1fs" % (_t.time() - w0))
    w0 = _t.time()
    eng.AAPIInit()
    print("[RUN] AAPIInit %.1fs" % (_t.time() - w0))
    try:
        eng.AAPISimulationReady()
    except Exception as e:
        print("[RUN] AAPISimulationReady failed (%r) - continuing" % e)

    step = args.step
    t = step
    hb = int(os.environ.get("RUN_HEARTBEAT_S", "30"))
    last_hb = 0.0
    n_steps = 0
    w_loop = _t.time()
    prof = os.environ.get("RUN_PROFILE")
    pr = None
    if prof:
        import cProfile
        pr = cProfile.Profile()
        pr.enable()
    while t <= args.end:
        try:
            bridge.conn.simulationStep()
            bridge.step_refresh()
        except aapi_shim.SimulationStopped:
            print("[RUN] AKISimulationStop honoured at t=%.0f" % t)
            break
        time_sta = float(int(t // 300) * 300)     # stats interval anchor
        acycle = int(step * 1000)
        eng.AAPIManage(t, time_sta, t, acycle)
        eng.AAPIPostManage(t, time_sta, t, acycle)
        n_steps += 1
        if _t.time() - last_hb >= hb:
            last_hb = _t.time()
            rate = n_steps / max(_t.time() - w_loop, 1e-6)
            print("[RUN] t=%6.0f wall=%.0fs (%.1f steps/s) vehicles=%d"
                  % (t, _t.time() - w_loop, rate,
                     len(bridge.conn.vehicle.getIDList())))
        t += step
    if pr is not None:
        import pstats
        pr.disable()
        pr.dump_stats(prof)
        print("[RUN] profile -> %s" % prof)
        pstats.Stats(pr).sort_stats("cumulative").print_stats(25)
    eng.AAPIFinish()
    try:
        eng.AAPIUnLoad()
    except Exception:
        pass


def run_smoke(conn, bridge, end_t):
    """Exercise the shim surface so plumbing is verified without the engine."""
    from aapi_shim import (AKIGetCurrentSimulationTime, AKIDetGetNumberDetectors,
                           AKIDetGetIdDetector, AKIDetGetPropertiesDetectorById,
                           AKIVehStateGetNbVehiclesSection, ECIGetCurrentPhase,
                           ECIGetStartingTimePhase, ECIChangeTimingPhase,
                           AKIEstGetCurrentStatisticsSection, doublep)
    t = bridge.step_length
    while t <= min(end_t, 600.0):
        conn.simulationStep()
        bridge.step_refresh()
        t += bridge.step_length
    print("---- smoke report @ t=%.0f ----" % AKIGetCurrentSimulationTime())
    print("sections:", len(bridge.section_ids), "| detectors:", AKIDetGetNumberDetectors())
    for did in bridge.det_order[:3]:
        p = AKIDetGetPropertiesDetectorById(did)
        print("  det %d -> sec=%s pos=%.1f..%.1f count60s=%d"
              % (did, p.IdSection, p.InitialPosition, p.FinalPosition,
                 __import__("aapi_shim").AKIDetGetCounterAggregatedbyId(did, 0)))
    for sid in bridge.section_ids[:5]:
        st = AKIEstGetCurrentStatisticsSection(sid)
        print("  sec %-9d count=%-4d flow=%7.1f speed=%5.1f density=%5.1f"
              % (sid, st.count, st.flow, st.speed, st.density))
    for tl in sorted(bridge.tls_phases)[:3]:
        node = bridge._node_int(tl)
        d = doublep(); mx = doublep(); mn = doublep()
        __import__("aapi_shim").ECIGetDurationsPhase(node, ECIGetCurrentPhase(node),
                                                     t, d, mx, mn)
        print("  tls %-8s phase=%d start=%.0f dur=%.1f nlinks=%d"
              % (tl, ECIGetCurrentPhase(node), ECIGetStartingTimePhase(node),
                 d.value(), len(bridge.node_turns.get(node, []))))
    # timing override round-trip
    for tl in sorted(bridge.tls_phases)[:1]:
        node = bridge._node_int(tl)
        ECIChangeTimingPhase(node, ECIGetCurrentPhase(node), 42.0, t)
        conn.simulationStep(); bridge.step_refresh()
        print("  ECIChangeTimingPhase applied, remaining ok")


if __name__ == "__main__":
    main()
