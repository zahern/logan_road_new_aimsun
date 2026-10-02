"""
run_nash_test.py -- A/B the Nash bargaining controller (dctsp_nash_bargain) on
WHICHEVER corridor is open in Aimsun (KG or Logan Road), using the shared engine
at the bundle root. Answers the reviewer's question: does Nash LOSE, or did it
never get to PLAY? -- by running the as-reported UTILITARIAN arm next to a proper
NASH arm (genuine bargaining power + Tier-2 corridor equilibrium + state-dependent
threat point), both against NO_TSP.

WHY ROOT / SINGLE INSTANCE: same as run_corridor_test.py -- root on sys.path so the
shared_tsp_engine is unambiguous; the corridor's batch_runner is imported once under
the alias "_br_champ" (the champion_search cache-bust; NOT 'batch_runner').

HOW TO RUN (inside Aimsun):
  1. FULLY restart Aimsun (engine is session-cached) and open EITHER the KG model
     OR the Logan Road model.
  2. Run this file from the Aimsun Python console. It auto-detects the corridor.
  3. Verify the [LOAD] line shows ENGINE_BUILD == EXPECTED_ENGINE_BUILD, then read
     the printed summary (obj vs NO_TSP per arm). Grep [NASH_BARGAIN] for picks.

LADDER (3 arms):
  NO_TSP            -- fixed-plan baseline.
  NASH_UTILITARIAN  -- p_T=0 (NASH_BUS_WEIGHT=0): pure net-surplus / minimise total
                       pax delay. This is the arm the paper currently reports under a
                       "Nash" label -- it is NOT a bargain, it is utilitarian.
  NASH_REAL         -- p_T=1 (symmetric Nash PRODUCT) + Tier-2 corridor equilibrium
                       (NASH_CORRIDOR_MODE) + STATE-DEPENDENT THREAT (NASH_STATE_THREAT:
                       the disagreement point worsens for the bus as the cross street
                       saturates). This is genuine Nash bargaining.
"""
import os as _os, sys as _sys, time as _time, importlib.util as _ilu

# ── Editable test design ──────────────────────────────────────────────────────
SEEDS = [300, 400]
DEMAND_SCALAR = 1.0
RESULTS_CSV_NAME = "nash_test.csv"
EXPECTED_ENGINE_BUILD = "2026-09-30T21:30-micro-queue"

_MEASURED = {                   # real measured feed (accurate cpc for the bargain)
    "MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True, "MEASURED_SIDE_COST": True,
}
# Common Nash config (mirrors the champion NASH_BARGAIN arm): Tier-2 corridor
# equilibrium on, integer-duration bargaining, CTM cascade priced into cpc,
# viability/congestion gate so it stands down on saturation instead of gridlocking.
_NASH_BASE = {
    "GLOBAL_REWARD_MODE": True, "NASH_BARGAIN_MODE": True,
    "NASH_CORRIDOR_MODE": True,
    "NASH_CROSS_WEIGHT": 1.0,
    "NASH_MIN_BUS_DELAY_S": 5.0, "NASH_MIN_GAIN_S": 5.0,
    "NASH_NEIGHBOR_WEIGHT": 0.5, "NASH_MAX_ITER": 10, "NASH_CONVERGENCE_TOL": 0.01,
    "NASH_INTEGER_DURATIONS": True,
    "CASCADE_COST_MODE": True,
    "DCTSP_CONGESTION_GATE": True, "DCTSP_CONGESTION_GATE_FRACTION": 0.70,
    **_MEASURED,
}
_LADDER = [
    ("NO_TSP", "NORMAL", False, "KALMAN", {}),
    # As-reported: p_T=0 => the Nash PRODUCT collapses to pure net-surplus
    # (utilitarian). Individual rationality (bps>cpc) still enforced.
    ("NASH_UTILITARIAN", "GLOBAL_REWARD", True, "NASH", {
        **_NASH_BASE, "NASH_BUS_WEIGHT": 0.0, "NASH_STATE_THREAT": False,
    }),
    # Proper Nash: symmetric bargaining power p_T=1, Tier-2 corridor equilibrium,
    # and the state-dependent threat point (bargain harder as the cross saturates).
    ("NASH_REAL", "GLOBAL_REWARD", True, "NASH", {
        **_NASH_BASE, "NASH_BUS_WEIGHT": 1.0,
        "NASH_STATE_THREAT": True, "NASH_THREAT_CROSS_GAIN": 20.0,
    }),
]


def _module_root(_marker="run_nash_test.py"):
    try:
        return _os.path.dirname(_os.path.abspath(__file__))
    except (NameError, TypeError):
        pass
    try:
        from PyANGKernel import GKSystem
        _d = _os.path.abspath(str(GKSystem.getSystem().getActiveModel(
            ).getDocumentDirectory().absolutePath()))
        for _ in range(4):
            if _os.path.isfile(_os.path.join(_d, _marker)):
                return _d
            _d = _os.path.dirname(_d)
    except Exception:
        pass
    return _os.path.abspath(_os.getcwd())


_ROOT = _module_root()
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)


def _detect_corridor():
    """Return ('kg'|'logan_road_new', dir) from the OPEN Aimsun model (authoritative
    -- dir/name), never a stale lock. Mirrors champion_search._detect_corridor."""
    try:
        from PyANGKernel import GKSystem
        _m = GKSystem.getSystem().getActiveModel()
        _dd = ""
        try:
            _dd = _os.path.normcase(_os.path.abspath(
                _m.getDocumentDirectory().absolutePath()))
        except Exception:
            _dd = ""
        for c in ("kg", "logan_road_new"):
            _cd = _os.path.normcase(_os.path.abspath(_os.path.join(_ROOT, c)))
            if _dd and (_dd == _cd or _dd.startswith(_cd + _os.sep)
                        or _os.path.basename(_dd) == c):
                return c, _os.path.join(_ROOT, c)
        _nm = ""
        try:
            _nm = (_m.getName() or "").lower()
        except Exception:
            _nm = ""
        if "logan" in _nm:
            return "logan_road_new", _os.path.join(_ROOT, "logan_road_new")
        if "kger" in _nm or "teg_kg" in _nm or _nm.startswith("kg"):
            return "kg", _os.path.join(_ROOT, "kg")
    except Exception:
        pass
    raise RuntimeError("[NASH_TEST] could not detect corridor from the open "
                       "model; open the KG or Logan Road .ang and re-run.")


_CORR, _CORR_DIR = _detect_corridor()


def _load_runner():
    _br_path = _os.path.join(_CORR_DIR, "batch_runner.py")
    if not _os.path.isfile(_br_path):
        raise RuntimeError("[NASH_TEST] not found: %s" % _br_path)
    _spec = _ilu.spec_from_file_location("_br_champ", _br_path)
    _br = _ilu.module_from_spec(_spec)
    _sys.modules["_br_champ"] = _br
    try:
        _spec.loader.exec_module(_br)
    except SystemExit:
        pass
    return _br


import csv as _csv, glob as _glob

_KPI = ("Objective_PaxPerDelayHr", "AvgBusPassDelay_s", "AvgCarPassDelay_s",
        "Net_MeanQueue_All", "TSP_Extensions", "TSP_EarlyRed", "SimDuration_hrs")
_SESSION = []


def _latest_kpis(name, seed):
    ds = sorted(_glob.glob(_os.path.join(_CORR_DIR, "results",
                "%s_seed%s_*" % (name, seed))), key=_os.path.getmtime)
    for d in reversed(ds):
        p = _os.path.join(d, "simulation_results.csv")
        if not _os.path.isfile(p):
            continue
        try:
            rows = list(_csv.DictReader(open(p, encoding="utf-8-sig")))
        except Exception:
            continue
        if not rows:
            continue
        r = rows[-1]
        try:
            # truncated-run guard: KG peak is 1.25h, Logan longer; 1.0h passes a
            # full KG sim while rejecting a crashed/short run.
            if float(r.get("SimDuration_hrs") or 0) < 1.0:
                continue
            return {k: float(r.get(k)) for k in _KPI}
        except Exception:
            continue
    return None


def _summary():
    from collections import defaultdict
    import statistics as _st
    byarm = defaultdict(list)
    for name, seed, k in _SESSION:
        byarm[name].append(k)
    print("\n" + "=" * 66)
    print("[NASH_TEST] SUMMARY corridor=%s (mean over seeds)" % _CORR)
    print("  %-16s %7s %7s %6s %6s %5s %5s" %
          ("arm", "obj", "car", "bus", "queue", "ext", "er"))
    base = None
    for name in [a[0] for a in _LADDER]:
        ks = byarm.get(name, [])
        if not ks:
            print("  %-16s (pending)" % name); continue
        def m(kk): return _st.mean([x[kk] for x in ks])
        o = m("Objective_PaxPerDelayHr")
        print("  %-16s %7.1f %7.1f %6.1f %6.0f %5.0f %5.0f" %
              (name, o, m("AvgCarPassDelay_s"), m("AvgBusPassDelay_s"),
               m("Net_MeanQueue_All"), m("TSP_Extensions"), m("TSP_EarlyRed")))
        if name == "NO_TSP":
            base = o
    if base:
        for name in [a[0] for a in _LADDER]:
            if name == "NO_TSP" or not byarm.get(name):
                continue
            o = _st.mean([x["Objective_PaxPerDelayHr"] for x in byarm[name]])
            print("  -> %s vs NO_TSP: %+.1f%%" % (name, (o - base) / base * 100))
    print("=" * 66)


def main():
    _br = _load_runner()
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    print("[NASH_TEST] corridor=%s runner=%s" %
          (_CORR, _os.path.join(_CORR_DIR, "batch_runner.py")))
    print("[NASH_TEST] expect ENGINE_BUILD=%s ; arms=%s seeds=%s" %
          (EXPECTED_ENGINE_BUILD, [a[0] for a in _LADDER], SEEDS))
    rep_obj = _br.get_first_replication()
    base_demands = {}
    if abs(float(DEMAND_SCALAR) - 1.0) > 1e-9:
        try:
            _br.set_demand_scalar(DEMAND_SCALAR, base_demands)
        except Exception as e:
            print("[NASH_TEST] WARN demand scalar: %r" % e)
    run_num = 0
    for (name, strat, coord, coord_algo, rov) in _LADDER:
        for seed in SEEDS:
            run_num += 1
            gr = bool(rov.get("GLOBAL_REWARD_MODE", strat != "NORMAL"))
            print("\n[NASH_TEST] === run %d: %s seed=%s %s ===" %
                  (run_num, name, seed, _time.strftime("%H:%M:%S")))
            _br.set_seed(rep_obj, seed)
            _br.write_run_config(name, strat, seed, DEMAND_SCALAR, coord, coord_algo,
                                 RUN_CONFIG_PATH, global_reward_mode=gr,
                                 reward_cfg=dict(rov), bus_predictor="KALMAN",
                                 results_csv_name=RESULTS_CSV_NAME,
                                 active_intersections=None)
            _br._purge_pyc(CONTROLLER_PATH)
            t0 = _time.time()
            try:
                _br.run_replication(rep_obj)
                print("[NASH_TEST] run %d done in %.0fs" % (run_num, _time.time() - t0))
            except Exception as e:
                print("[NASH_TEST] run %d EXCEPTION: %r" % (run_num, e))
            k = _latest_kpis(name, seed)
            if k:
                _SESSION.append((name, seed, k))
                print("[NASH_TEST]   %s seed %s: obj=%.1f car=%.1f bus=%.1f ext=%.0f er=%.0f" %
                      (name, seed, k["Objective_PaxPerDelayHr"], k["AvgCarPassDelay_s"],
                       k["AvgBusPassDelay_s"], k["TSP_Extensions"], k["TSP_EarlyRed"]))
    _summary()


main()
