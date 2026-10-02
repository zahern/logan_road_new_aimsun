"""
run_all_test.py -- ONE launcher that A/Bs BOTH controller families on whichever
corridor is open in Aimsun (KG or Logan Road): the CELLQLEARN-v2 corridor learner
(BXT_CORRIDOR_MODE) AND the Nash bargaining controller (dctsp_nash_bargain), all
against the fixed-plan NO_TSP baseline, in a single run with one summary.

WHY ROOT / SINGLE INSTANCE: root on sys.path so the shared_tsp_engine is
unambiguous; the corridor's batch_runner is imported once under the alias
"_br_champ" (the champion_search cache-bust; NOT 'batch_runner').

HOW TO RUN (inside Aimsun):
  1. FULLY restart Aimsun (engine is session-cached) and open EITHER the KG model
     OR the Logan Road model.
  2. Run this file from the Aimsun Python console. It auto-detects the corridor.
  3. Verify the [LOAD] line shows ENGINE_BUILD == EXPECTED_ENGINE_BUILD, then read
     the printed summary. Grep [CELLQ_CORRIDOR] / [NASH_BARGAIN] for picks,
     [REMGREEN] to confirm the bus ETA logic is live.

COORDINATION SCOPE: when an arm sets coordinated=True the corridor coordinator
pre-arms the IMMEDIATE NEXT managed junction ONLY (engine _iter_managed_targets
[:1] + a hard [PREARM GUARD ERROR] guard); it re-seeds one hop at a time as the
bus advances, never fanning out to multiple downstream junctions in one shot.
All CELLQ/corridor arms are coordinated=False (the KALMAN coordinator was the
regression); only NO_TSP_COORD, the Nash arms, and the proven champion arms
still coordinate, and those stay single-hop.

LADDER (9 arms = NO_TSP + 4 CTM-off/CTM-on pairs; 5 seeds => 45 runs. Each tuple =
name, strategy, coordinated, coordination_algo, cfg):
  NO_TSP             -- fixed-plan baseline, NOT coordinated.
  NO_TSP_COORD       -- MATCHED BASELINE: no TSP action, but WITH the KALMAN
                        corridor coordinator. Isolates the cost of coordination.
  CELLQ_LEARN_UNCOORD-- MATCHED BASELINE: CellQ learner, but NO coordinator.
                        Isolates the value of TSP on its own.
  CELLQ_HEURISTIC    -- BXT_CORRIDOR_MODE, CTM-greedy heuristic (stage 1).
  CELLQ_LEARN        -- + CELLQ_CORRIDOR_LEARN (stage-2 Q-learner, DE-solved mags).
  CELLQ_LEARN_COUPLED-- + corridor coupling + exact-tracker bus chain (measured queue).
  NASH_UTILITARIAN   -- p_T=0: Nash product collapses to net-surplus (min total delay).
  NASH_REAL          -- p_T=1 symmetric Nash + Tier-2 corridor eq + state threat.
  NASH_CAL           -- Nash + delay calibration + Aimsun microscopic queue.
  CELLQ_LEARN_CAL    -- CellQ learner + delay calibration + microscopic queue.

WHY THE TWO MATCHED BASELINES (2026-09-30): the earlier ladder scored every TSP
arm with coordinated=True against NO_TSP with coordinated=False, so each arm's
number carried the KALMAN coordinator as well as its own action logic. Read the
[ALL_TEST] ATTRIBUTION block, not the arm-vs-NO_TSP list: if
"coordination alone" is strongly negative, the coordinator is the regression and
no TSP arm can beat it until that is fixed.

TO RUN THE ISOLATION TEST FAST (fewer runs): comment out CELLQ_HEURISTIC and
CELLQ_LEARN_COUPLED. CELLQ_LEARN already supplies the TSP+coord figure, so
NO_TSP + NO_TSP_COORD + CELLQ_LEARN_UNCOORD + CELLQ_LEARN (4 arms x 2 seeds =
8 runs) answers the attribution question completely.
"""
import os as _os, sys as _sys, time as _time, importlib.util as _ilu

# ── Editable test design ──────────────────────────────────────────────────────
SEEDS = [300, 400, 500, 600, 800]
DEMAND_SCALAR = 1.0
RESULTS_CSV_NAME = "all_test.csv"
EXPECTED_ENGINE_BUILD = "2026-10-01T14:00-ctm-multicell"

_MEASURED = {                   # real measured feed (accurate benefit/cost)
    "MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True, "MEASURED_SIDE_COST": True,
}
_BXT_LEARN = {"BXT_ALPHA": 0.3, "BXT_GAMMA": 0.5, "BXT_EPSILON": 0.10}
# Common CellQLearn baseline for the one-factor ablation sweep. Every A* arm is
# THIS plus exactly one flag, so a delta is attributable to that flag alone.
_CELLQ_BASE = {
    "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
    "CELLQ_CORRIDOR_LEARN": True, **_BXT_LEARN, **_MEASURED,
}
# Common Nash config (mirrors the champion NASH_BARGAIN arm).
_NASH_BASE = {
    "GLOBAL_REWARD_MODE": True, "NASH_BARGAIN_MODE": True, "NASH_CORRIDOR_MODE": True,
    "NASH_CROSS_WEIGHT": 1.0, "NASH_MIN_BUS_DELAY_S": 5.0, "NASH_MIN_GAIN_S": 5.0,
    "NASH_NEIGHBOR_WEIGHT": 0.5, "NASH_MAX_ITER": 10, "NASH_CONVERGENCE_TOL": 0.01,
    "NASH_INTEGER_DURATIONS": True, "CASCADE_COST_MODE": True,
    "DCTSP_CONGESTION_GATE": True, "DCTSP_CONGESTION_GATE_FRACTION": 0.70,
    **_MEASURED,
}
_LADDER = [
    # ── CTM-ON / CTM-OFF PAIRED LADDER (2026-10-01) ────────────────────────────
    # Every CELLQLEARN config appears TWICE: once with the classic Webster/shockwave
    # cross cost (CTM off) and once with the genuine multi-cell Cell-Transmission-
    # Model cross cost (CELLQ_CTM_REWARD=True). Each pair differs ONLY by that flag,
    # so the *_CTM vs base delta is the pure effect of making the reward a real CTM.
    # All uncoordinated (coordination was a dead end). Objective = pax-per-delay-hour,
    # higher is better => POSITIVE %% beats NO_TSP. 9 arms x 5 seeds = 45 runs.
    # (MICRO_QUEUE left OFF so the CTM-off arms stay comparable to the +8%% champion;
    #  the CTM still seeds its cells from the live queue via _zone_queue_count.)
    ("NO_TSP", "NORMAL", False, "KALMAN", {}),

    # pair 1: plain learner, no bargain
    ("CELLQ_LEARN_UNCOORD", "GLOBAL_REWARD", False, "KALMAN", {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True, **_BXT_LEARN, **_MEASURED,
    }),
    ("CELLQ_LEARN_UNCOORD_CTM", "GLOBAL_REWARD", False, "KALMAN", {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True, "CELLQ_CTM_REWARD": True,
        **_BXT_LEARN, **_MEASURED,
    }),

    # pair 2: THE CHAMPION -- learner + bargain p_T=0 (utilitarian)
    ("CELLQ_BARGAIN_PT0", "GLOBAL_REWARD", False, "KALMAN", {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True,
        "BXT_BARGAIN_DECISION": True, "BXT_BARGAIN_PT": 0.0,
        **_BXT_LEARN, **_MEASURED,
    }),
    ("CELLQ_BARGAIN_PT0_CTM", "GLOBAL_REWARD", False, "KALMAN", {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True,
        "BXT_BARGAIN_DECISION": True, "BXT_BARGAIN_PT": 0.0,
        "CELLQ_CTM_REWARD": True,
        **_BXT_LEARN, **_MEASURED,
    }),

    # pair 3: symmetric bargain p_T=1
    ("CELLQ_BARGAIN_PT1", "GLOBAL_REWARD", False, "KALMAN", {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True,
        "BXT_BARGAIN_DECISION": True, "BXT_BARGAIN_PT": 1.0, "BXT_BARGAIN_PC": 1.0,
        **_BXT_LEARN, **_MEASURED,
    }),
    ("CELLQ_BARGAIN_PT1_CTM", "GLOBAL_REWARD", False, "KALMAN", {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True,
        "BXT_BARGAIN_DECISION": True, "BXT_BARGAIN_PT": 1.0, "BXT_BARGAIN_PC": 1.0,
        "CELLQ_CTM_REWARD": True,
        **_BXT_LEARN, **_MEASURED,
    }),

    # pair 4: champion + per-jct GE cap at the gridlock junctions
    # CAPS MUST SIT BELOW MAX_GE_EXTENSION_S (10.0 s). The 2026-10-01 run used
    # {39590: 10.0, 39593: 8.0}: 10.0 is exactly the global bound, so the 39590
    # cap was a NO-OP and only 39593 ever bit. 5.0/4.0 make both bite.
    ("CELLQ_BARGAIN_GECAP", "GLOBAL_REWARD", False, "KALMAN", {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True,
        "BXT_BARGAIN_DECISION": True, "BXT_BARGAIN_PT": 0.0,
        "GE_UB_CAP_BY_JCT": {39590: 5.0, 39593: 4.0},
        **_BXT_LEARN, **_MEASURED,
    }),
    ("CELLQ_BARGAIN_GECAP_CTM", "GLOBAL_REWARD", False, "KALMAN", {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True,
        "BXT_BARGAIN_DECISION": True, "BXT_BARGAIN_PT": 0.0,
        "GE_UB_CAP_BY_JCT": {39590: 5.0, 39593: 4.0},
        "CELLQ_CTM_REWARD": True,
        **_BXT_LEARN, **_MEASURED,
    }),
]


def _module_root(_marker="run_all_test.py"):
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
    raise RuntimeError("[ALL_TEST] could not detect corridor from the open "
                       "model; open the KG or Logan Road .ang and re-run.")


_CORR, _CORR_DIR = _detect_corridor()


def _load_runner():
    _br_path = _os.path.join(_CORR_DIR, "batch_runner.py")
    if not _os.path.isfile(_br_path):
        raise RuntimeError("[ALL_TEST] not found: %s" % _br_path)
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
    print("\n" + "=" * 72)
    print("[ALL_TEST] SUMMARY corridor=%s (mean over seeds)" % _CORR)
    print("  %-20s %7s %7s %6s %6s %5s %5s" %
          ("arm", "obj", "car", "bus", "queue", "ext", "er"))
    base = None
    for name in [a[0] for a in _LADDER]:
        ks = byarm.get(name, [])
        if not ks:
            print("  %-20s (pending)" % name); continue
        def m(kk): return _st.mean([x[kk] for x in ks])
        o = m("Objective_PaxPerDelayHr")
        print("  %-20s %7.1f %7.1f %6.1f %6.0f %5.0f %5.0f" %
              (name, o, m("AvgCarPassDelay_s"), m("AvgBusPassDelay_s"),
               m("Net_MeanQueue_All"), m("TSP_Extensions"), m("TSP_EarlyRed")))
        if name == "NO_TSP":
            base = o
    if base:
        print("  (objective = pax-per-delay-hour, higher is better => POSITIVE %% = BEATS NO_TSP)")
        for name in [a[0] for a in _LADDER]:
            if name == "NO_TSP" or not byarm.get(name):
                continue
            o = _st.mean([x["Objective_PaxPerDelayHr"] for x in byarm[name]])
            _d = (o - base) / base * 100
            print("  -> %-20s vs NO_TSP: %+.1f%%%s" %
                  (name, _d, "  <-- BEATS NO_TSP" if _d > 0.5 else ""))

    # ── Attribution: decompose % change into coordination vs TSP ──────────────
    def _obj(n):
        ks = byarm.get(n, [])
        return _st.mean([x["Objective_PaxPerDelayHr"] for x in ks]) if ks else None

    _c, _t, _b = _obj("NO_TSP_COORD"), _obj("CELLQ_LEARN_UNCOORD"), _obj("CELLQ_LEARN")
    if base and (_c is not None or _t is not None):
        print("-" * 72)
        print("[ALL_TEST] ATTRIBUTION (%% of Objective_PaxPerDelayHr vs NO_TSP; "
              "objective is pax-per-delay-hour so POSITIVE = BETTER)")
        if _c is not None:
            print("  coordination alone (NO_TSP_COORD)      : %+.1f%%" % ((_c - base) / base * 100))
        if _t is not None:
            print("  TSP alone (CELLQ_LEARN_UNCOORD)       : %+.1f%%" % ((_t - base) / base * 100))
        if _c is not None and _t is not None and _b is not None:
            print("  TSP + coordination (CELLQ_LEARN)      : %+.1f%%" % ((_b - base) / base * 100))
            print("  => if NO_TSP_COORD alone is already strongly negative, the")
            print("     coordinator is the regression and no TSP arm can win until")
            print("     it is fixed; compare other arms to NO_TSP_COORD, not NO_TSP.")
        for _a, _lbl in ((("CELLQ_LEARN_UNCOORD"), "TSP arms vs NO_TSP_COORD"),
                         (("DCTSP_MARL"), "DCTSP_MARL vs NO_TSP_COORD"),
                         (("CELLQLEARN_GATED"), "CELLQLEARN_GATED vs NO_TSP_COORD")):
            _x = _obj(_a)
            if _c is not None and _x is not None:
                print("  %-34s : %+.1f%%" % (_lbl, (_x - _c) / _c * 100))
    print("=" * 72)


def _set_controller_flag(controller_path, var, value):
    """Rewrite one top-level controller constant, preserving any `: type` annotation.

    The controller writes these as annotated assignments
    (MARK_DETECTION_POINTS: bool = True), so the pattern must allow the
    annotation between the name and the '='. Values are written as real Python
    literals -- passing the string "False" would produce a truthy str.
    """
    import re
    with open(controller_path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    pat = re.compile(r"(?m)^(%s)(\s*:\s*[A-Za-z_.\[\]]+)?\s*=.*$" % re.escape(var))
    if not pat.search(txt):
        return
    new_txt = pat.sub(lambda m: "%s%s = %r" % (m.group(1), m.group(2) or "", value),
                      txt, count=1)
    with open(controller_path, "w", encoding="utf-8", newline="") as f:
        f.write(new_txt)


def main():
    _br = _load_runner()
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    print("[ALL_TEST] corridor=%s runner=%s" %
          (_CORR, _os.path.join(_CORR_DIR, "batch_runner.py")))
    print("[ALL_TEST] expect ENGINE_BUILD=%s ; arms=%s seeds=%s" %
          (EXPECTED_ENGINE_BUILD, [a[0] for a in _LADDER], SEEDS))
    # BUGFIX 2026-09-30: this script never disabled the per-run detection-point
    # marking, so it inherited whatever the controller file shipped with. That
    # was True -> 365,119 AAPI mark calls in a single run (logged as
    # "[MARK DIAG] _mark_calls_total=365119"), i.e. minutes of pure plotting
    # overhead on every one the 14 runs. It was NOT specific to PLAN_OPT --
    # every arm paid it. Patched here with a local regex writer rather than by
    # importing champion_search (this script deliberately loads only the runner;
    # champion_search has import-time side effects).
    for _flag, _val in (("MARK_DETECTION_POINTS", False),
                        ("OVERLAY_DETECTIONS_ON_MAP", False),
                        ("TRACK_BUS_POSITIONS", False),
                        ("STATUS_DASHBOARD_INTERVAL_S", 0.0)):
        try:
            _set_controller_flag(CONTROLLER_PATH, _flag, _val)
        except Exception as e:
            print("[ALL_TEST] WARN flag %s: %r" % (_flag, e))
    print("[ALL_TEST] batch plotting disabled "
          "(MARK_DETECTION_POINTS/OVERLAY/TRACK/DASHBOARD off)")
    rep_obj = _br.get_first_replication()
    base_demands = {}
    if abs(float(DEMAND_SCALAR) - 1.0) > 1e-9:
        try:
            _br.set_demand_scalar(DEMAND_SCALAR, base_demands)
        except Exception as e:
            print("[ALL_TEST] WARN demand scalar: %r" % e)
    run_num = 0
    for (name, strat, coord, coord_algo, rov) in _LADDER:
        for seed in SEEDS:
            run_num += 1
            gr = bool(rov.get("GLOBAL_REWARD_MODE", strat != "NORMAL"))
            print("\n[ALL_TEST] === run %d: %s seed=%s %s ===" %
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
                print("[ALL_TEST] run %d done in %.0fs" % (run_num, _time.time() - t0))
            except Exception as e:
                print("[ALL_TEST] run %d EXCEPTION: %r" % (run_num, e))
            k = _latest_kpis(name, seed)
            if k:
                _SESSION.append((name, seed, k))
                print("[ALL_TEST]   %s seed %s: obj=%.1f car=%.1f bus=%.1f ext=%.0f er=%.0f" %
                      (name, seed, k["Objective_PaxPerDelayHr"], k["AvgCarPassDelay_s"],
                       k["AvgBusPassDelay_s"], k["TSP_Extensions"], k["TSP_EarlyRed"]))
    _summary()


main()
