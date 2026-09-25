"""
run_logan_cellq_cont_marl_test.py -- CELLQLEARN (+continuous/+purpose) vs MARL vs NO_TSP on Logan.

WHY THIS FILE
-------------
run_logan_nash_test.py showed every Nash arm losing ~-5% to NO_TSP on Logan:
saturated cars + barely-delayed buses (~8 s) mean acting costs car delay for
tiny bus gain. This ladder asks the follow-up questions:

  1. Does CELLQLEARN (BXT learner, per-seed) beat NO_TSP on Logan?
  2. Does CONTINUOUS monitoring help CELLQLEARN (car-state feedback between
     buses via CONTINUOUS_MONITOR_MODE + BXT_CONTINUOUS_MODE)?
  3. Does the PURPOSE-built selective layer on top of continuous (measured
     state + measured side cost + cascade + net-benefit gate + Logan 15 s
     gates + SAFE veto) turn it positive -- i.e. act rarely but only when it
     pays?
  4. Does analytic DCTSP_MARL beat NO_TSP (no training needed, so 1-seed
     comparison is fair)?
  5. NASH_BASE is kept as an anchor so this run is directly comparable to the
     "bad" run_logan_nash_test.py verdict.
  6. Does CONTINUOUS monitoring help MARL (same car-state feedback between
     buses via CONTINUOUS_MONITOR_MODE + 50 pax-s gain; NO BXT flag --
     BXT_CONTINUOUS_MODE only routes the learner's no-bus ticks)?
  7. Does the PURPOSE selective layer on MARL (measured feeds + cascade +
     Logan 15 s bus-delay gate + veto 2.0) fix its over-acting (-10.6%)?

ARMS (all GLOBAL_REWARD, KALMAN/SHOCKWAVE as in champion_search.py)
-------------------------------------------------------------------
  NO_TSP                  -- baseline, no TSP.
  CELLQLEARN              -- champion CELLQLEARN config, per-seed (eps 0.02).
  CELLQLEARN_CONT         -- CELLQLEARN + CONTINUOUS_MONITOR_MODE +
                             BXT_CONTINUOUS_MODE (car gain 50 pax-s).
  CELLQLEARN_CONT_PURPOSE -- CONT + measured feeds + MEASURED_SIDE_COST +
                             CASCADE + BXT_NET_BENEFIT_GATE + 15 s Logan gates
                             + veto 2.0 (the "purpose" selective acting layer).
  DCTSP_MARL              -- champion analytic MARL, Logan veto 3.5 +
                             congestion gate 0.70.
  DCTSP_MARL_CONT         -- MARL + CONTINUOUS_MONITOR_MODE (car gain 50 pax-s,
                             no BXT flag).
  DCTSP_MARL_CONT_PURPOSE -- MARL_CONT + measured feeds + CASCADE + 15 s
                             bus-delay gate + veto 2.0 (selective MARL).
  NASH_BASE               -- reference from run_logan_nash_test.py (utilitarian
                             continuous-Nash, min-gain 50 pax-s).

HOW TO RUN (inside Aimsun, Logan model open)
--------------------------------------------
  1. FULLY restart Aimsun (engine is session-cached) and open
     logan_road_new/Logan_RD_for_QUT_with_detectors.ang.
  2. Run this file from the Aimsun Python console.
  3. Check the [LOAD] line shows ENGINE_BUILD matching EXPECTED_ENGINE_BUILD
     below, then read the session summary (obj vs NO_TSP per arm).

WHAT TO GREP AFTERWARDS
-----------------------
  '[SIDE_SCAN]'   -- len_m tags: [dead]/[main]/[managed]/[zone]/+model are all
                     NORMAL (entry / correct guards / full cover / virtual
                     resolved). Only apifail-node/apifail-turns/empty are walk
                     faults. roll_ctr=0 before ~300 s is warm-up (flow carries
                     the OD seed prior); [noupdate stale=...] after 600 s with
                     n_veh>0 is the only real counter fault.
  '[FLOW SRC]'    -- tier=demand_profile (seed prior) vs tier=partial/snapshot
                     (real measurement). A side stuck on the seed all run
                     (constant ~1800) with n_veh=0 is an EMPTY approach reading
                     its prior -- now fixed to 0 after warm-up via the
                     allow_seed=False live overlay.
  '[NASH_BARGAIN] [monitor]', '[MONITOR]', '[MEAS_SIDE]', '] error' (want 0).
  '[MONITOR_GATE]' -- throttled holds of no-bus ticks (no fresh side feed,
                      side empty, main queue=0). Expect MANY on no-side
                      junctions (20270/20280/...) and early run; near-zero
                      late on measured sides. Zero everywhere = gate off.
"""""
import os as _os, sys as _sys, time as _time, importlib.util as _ilu

# ── Editable test design ──────────────────────────────────────────────────────
SEEDS = [300]                      # 1-seed sanity first; extend to [300,400,500] once green
DEMAND_SCALAR = 1.0
RESULTS_CSV_NAME = "logan_cellq_cont_marl_test.csv"
EXPECTED_ENGINE_BUILD = "2026-09-25T17:00-seeddecay-mongate"

# ── Base configs (mirrors champion_search.py Logan arms) ─────────────────────
_CELLQ_BASE = {
    "GLOBAL_REWARD_MODE": True, "BXT_MODE": True,
    "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BARGAIN_SPM_MODE": False,
    "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
    "BXT_DT_S": 1.0, "BXT_EPSILON": 0.02, "BXT_ALPHA": 0.2, "BXT_GAMMA": 0.01,
    "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
    "CELLQLEARN_MIN_GAIN_S": 15.0,
    "DECIDER_COST_VETO_RATIO": 1.5, "BXT_WARMSTART_FROM_SHARED": True,
    "BXT_SOLVER": "deficit",
    "BUS_PAX_WEIGHT": 1.3, "GREEN_KEEP_CREDIT_S": 3.0,
    "MULTIBUS_MAX_FACTOR": 1.0,
    "CORRIDOR_REWARD_NEIGHBOR_W": 0.5,
    "TSP_CYCLE_LENGTH_OVERRIDE_S": 135.0, "PHASE_SEQ_MAX_PER_CYCLE": 1,
    # Diagnosis: realized-vs-predicted pairing + decision/stage tracing for
    # diagnose_vs_notsp.py (logging only, does not change the policy).
    "BXT_EVAL_DIAGNOSTICS": True, "DIAG_FLOW_STAGE": True, "DIAG_DECISION": True,
}
_CONT = {
    "CONTINUOUS_MONITOR_MODE": True,
    "BXT_CONTINUOUS_MODE": True,
    "CONTINUOUS_MONITOR_MIN_GAIN_PAXS": 50.0,
}
# PURPOSE selective layer: measured + cascade + net-benefit + hard Logan gates.
_PURPOSE = {
    "MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True,
    "MEASURED_SIDE_COST": True, "CASCADE_COST_MODE": True,
    "BXT_NET_BENEFIT_GATE": True,
    "CELLQLEARN_MIN_GAIN_S": 15.0, "SELFORG_MIN_BUS_DELAY_S": 15.0,
    "DECIDER_COST_VETO_RATIO": 2.0,
}
_MARL = {
    "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0, "REWARD_BETA": 1.0,
    "REWARD_GAMMA": 1.0, "DCTSP_GREEN_REALLOC_MODE": True,
    "GREEN_REALLOC_RECOVER_FRACTION": 1.0, "DCTSP_W_H": 0.50,
    "DCTSP_CAR_WEIGHT": 1.00,
    "DECIDER_COST_VETO_RATIO": 3.5,
    "DCTSP_CONGESTION_GATE": True,
    "DCTSP_CONGESTION_GATE_FRACTION": 0.70,
    "BXT_MODE": False, "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False,
    "BARGAIN_SPM_MODE": False, "CENTRALIZED_MODE": False,
    "DIAG_FLOW_STAGE": True, "DIAG_DECISION": True,
    "MEASURED_SIDE_COST_DIAG": True,
}
_NASH_BASE = {
    "GLOBAL_REWARD_MODE": True, "NASH_BARGAIN_MODE": True,
    "CONTINUOUS_MONITOR_MODE": True, "NASH_CONTINUOUS_MODE": True,
    "NASH_BUS_WEIGHT": 0.0, "NASH_CROSS_WEIGHT": 1.0,
    "CONTINUOUS_MONITOR_MIN_GAIN_PAXS": 50.0,
    "DIAG_FLOW_STAGE": True, "DIAG_DECISION": True,
}
# MARL continuous: monitor-only. BXT_CONTINUOUS_MODE is intentionally absent --
# it only re-routes the BXT learner's no-bus ticks (specialized_modes.py) and
# DCTSP_MARL runs with BXT_MODE False, so the flag would be dead config.
_MARL_CONT = {
    "CONTINUOUS_MONITOR_MODE": True,
    "CONTINUOUS_MONITOR_MIN_GAIN_PAXS": 50.0,
}
# MARL purpose layer: generic selective gates only (measured/cascade feeds are
# already applied to every non-NO_TSP arm via GLOBAL_* setdefaults below).
# BXT_NET_BENEFIT_GATE / CELLQLEARN_MIN_GAIN_S are BXT-specific -- excluded.
_MARL_PURPOSE = {
    "MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True,
    "MEASURED_SIDE_COST": True, "CASCADE_COST_MODE": True,
    "SELFORG_MIN_BUS_DELAY_S": 15.0,
    "DECIDER_COST_VETO_RATIO": 2.0,
}

EXPERIMENTS_TEST = [
    {"name": "NO_TSP", "strategy": "NORMAL", "coordinated": False,
     "coordination_algo": "KALMAN", "reward_overrides": {}},
    {"name": "CELLQLEARN", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": dict(_CELLQ_BASE)},
    {"name": "CELLQLEARN_CONT", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": {**_CELLQ_BASE, **_CONT}},
    {"name": "CELLQLEARN_CONT_PURPOSE", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": {**_CELLQ_BASE, **_CONT, **_PURPOSE}},
    {"name": "DCTSP_MARL", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "KALMAN",
     "reward_overrides": dict(_MARL)},
    {"name": "DCTSP_MARL_CONT", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "KALMAN",
     "reward_overrides": {**_MARL, **_MARL_CONT}},
    {"name": "DCTSP_MARL_CONT_PURPOSE", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "KALMAN",
     "reward_overrides": {**_MARL, **_MARL_CONT, **_MARL_PURPOSE}},
    {"name": "NASH_BASE", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "KALMAN",
     "reward_overrides": dict(_NASH_BASE)},
]

# Same global feed the champion matrix uses (setdefaults -- an arm can override).
GLOBAL_MEASURED_FEED = True
GLOBAL_MEASURED_SIDE_COST = True
GLOBAL_CASCADE_COST = True


# ── Resolve the bundle root (works when pasted into the Aimsun console too) ────
def _module_root(_marker="run_logan_cellq_cont_marl_test.py"):
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
_CORR = "logan_road_new"
_CORR_DIR = _os.path.join(_ROOT, _CORR)


def _assert_logan_open():
    try:
        from PyANGKernel import GKSystem
        _m = GKSystem.getSystem().getActiveModel()
    except Exception:
        print("[CELLQ_CONT_MARL] WARN: no Aimsun model handle; assuming Logan is open.")
        return
    _dd = ""
    try:
        _dd = _os.path.normcase(_os.path.abspath(
            _m.getDocumentDirectory().absolutePath()))
    except Exception:
        _dd = ""
    _nm = ""
    try:
        _nm = (_m.getName() or "").lower()
    except Exception:
        _nm = ""
    _cd = _os.path.normcase(_os.path.abspath(_CORR_DIR))
    _is_logan = (_dd and (_dd == _cd or _dd.startswith(_cd + _os.sep)
                          or _os.path.basename(_dd) == _CORR)) or ("logan" in _nm)
    if not _is_logan:
        raise RuntimeError(
            f"CORRIDOR GUARD: the open Aimsun model is not Logan "
            f"(name={_nm!r}, dir={_dd!r}). Open "
            f"{_CORR}/Logan_RD_for_QUT_with_detectors.ang and re-run.")
    print(f"[CELLQ_CONT_MARL] corridor guard OK: Logan model is open ({_nm!r}).")


def _load_logan_runner():
    _br_path = _os.path.join(_CORR_DIR, "batch_runner.py")
    if not _os.path.isfile(_br_path):
        raise RuntimeError(f"[CELLQ_CONT_MARL] not found: {_br_path}")
    _spec = _ilu.spec_from_file_location("_br_champ", _br_path)
    _br = _ilu.module_from_spec(_spec)
    _sys.modules["_br_champ"] = _br
    try:
        _spec.loader.exec_module(_br)
    except SystemExit:
        pass
    return _br


import csv as _csv, glob as _glob

_KPI_KEYS = ("Objective_PaxPerDelayHr", "AvgBusPassDelay_s", "AvgCarPassDelay_s",
             "AvgBusTT_s", "Net_MeanQueue_All", "TSP_Extensions", "TSP_Insertions",
             "SimDuration_hrs")
_SESSION = []


def _read_latest_kpis(name, seed):
    ds = sorted(_glob.glob(_os.path.join(
        _CORR_DIR, "results", f"{name}_seed{seed}_*")), key=_os.path.getmtime)
    if not ds:
        return None
    p = _os.path.join(ds[-1], "simulation_results.csv")
    if not _os.path.isfile(p):
        return None
    try:
        rows = list(_csv.DictReader(open(p, encoding="utf-8-sig")))
    except Exception:
        return None
    if not rows:
        return None
    r = rows[-1]
    out = {}
    for k in _KPI_KEYS:
        try:
            out[k] = float(r.get(k))
        except Exception:
            out[k] = float("nan")
    return out


def _print_run_kpis(name, seed):
    k = _read_latest_kpis(name, seed)
    if not k:
        print(f"[CELLQ_CONT_MARL]   (no KPIs found for {name} seed {seed} yet)")
        return
    _SESSION.append((name, seed, k))
    print(f"[CELLQ_CONT_MARL]   {name} seed {seed}: obj={k['Objective_PaxPerDelayHr']:.1f} "
          f"bus={k['AvgBusPassDelay_s']:.1f}s car={k['AvgCarPassDelay_s']:.1f}s "
          f"queue={k['Net_MeanQueue_All']:.0f} ext={k['TSP_Extensions']:.0f} "
          f"ins={k['TSP_Insertions']:.0f} dur={k['SimDuration_hrs']:.2f}h")


def _print_summary():
    if not _SESSION:
        return
    from collections import defaultdict
    byarm = defaultdict(list)
    for name, seed, k in _SESSION:
        if k.get("SimDuration_hrs", 0) >= 1.4:
            byarm[name].append(k)
    print("\n" + "=" * 64)
    print("[CELLQ_CONT_MARL] SESSION SUMMARY (mean over full runs; obj higher=better)")
    print(f"  {'arm':22s} {'obj':>7s} {'bus_s':>6s} {'car_s':>6s} {'queue':>6s} {'ext':>5s}")
    base = None
    for name, ks in byarm.items():
        def m(kk): return sum(k[kk] for k in ks) / len(ks)
        row = (m("Objective_PaxPerDelayHr"), m("AvgBusPassDelay_s"),
               m("AvgCarPassDelay_s"), m("Net_MeanQueue_All"), m("TSP_Extensions"))
        print(f"  {name:22s} {row[0]:7.1f} {row[1]:6.1f} {row[2]:6.1f} "
              f"{row[3]:6.0f} {row[4]:5.0f}")
        if name == "NO_TSP":
            base = row[0]
    if base:
        for name, ks in byarm.items():
            if name == "NO_TSP":
                continue
            o = sum(k["Objective_PaxPerDelayHr"] for k in ks) / len(ks)
            print(f"  -> {name} objective vs NO_TSP: {(o-base)/base*100:+.1f}%")
    print("=" * 64)


def main():
    _assert_logan_open()
    _br = _load_logan_runner()
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    print(f"[CELLQ_CONT_MARL] runner   = {_os.path.join(_CORR_DIR, 'batch_runner.py')}")
    print(f"[CELLQ_CONT_MARL] engine   = {_os.path.join(_ROOT, 'shared_tsp_engine', 'engine.py')}")
    print(f"[CELLQ_CONT_MARL] expect ENGINE_BUILD={EXPECTED_ENGINE_BUILD} on the [LOAD] line")
    print(f"[CELLQ_CONT_MARL] arms={[e['name'] for e in EXPERIMENTS_TEST]} seeds={SEEDS}")

    rep_obj = _br.get_first_replication()

    base_demands = {}
    if abs(float(DEMAND_SCALAR) - 1.0) > 1e-9:
        try:
            _br.set_demand_scalar(DEMAND_SCALAR, base_demands)
        except Exception as e:
            print(f"[CELLQ_CONT_MARL] WARN demand scalar {DEMAND_SCALAR}: {e!r}")

    run_num = 0
    for exp in EXPERIMENTS_TEST:
        if not exp.get("enabled", True):
            continue
        for seed in SEEDS:
            run_num += 1
            name = exp["name"]
            cfg = dict(exp.get("reward_overrides") or {})
            gr = bool(cfg.get("GLOBAL_REWARD_MODE", exp["strategy"] != "NORMAL"))
            if name != "NO_TSP":
                if GLOBAL_MEASURED_FEED:
                    cfg.setdefault("MEASURED_STATE_FEED", True)
                    cfg.setdefault("MEASURED_QUEUE_FEED", True)
                if GLOBAL_MEASURED_SIDE_COST:
                    cfg.setdefault("MEASURED_SIDE_COST", True)
                if GLOBAL_CASCADE_COST:
                    cfg.setdefault("CASCADE_COST_MODE", True)
            print(f"\n[CELLQ_CONT_MARL] === run {run_num}: {name} seed={seed} "
                  f"scalar={DEMAND_SCALAR} === {_time.strftime('%H:%M:%S')}")
            _br.set_seed(rep_obj, seed)
            _br.write_run_config(
                name, exp["strategy"], seed, DEMAND_SCALAR,
                exp["coordinated"], exp["coordination_algo"], RUN_CONFIG_PATH,
                global_reward_mode=gr, reward_cfg=cfg, bus_predictor="KALMAN",
                results_csv_name=RESULTS_CSV_NAME, active_intersections=None)
            _br._purge_pyc(CONTROLLER_PATH)
            t0 = _time.time()
            try:
                _br.run_replication(rep_obj)
                print(f"[CELLQ_CONT_MARL] run {run_num} done in {_time.time()-t0:.0f}s")
                _print_run_kpis(name, seed)
            except Exception as e:
                print(f"[CELLQ_CONT_MARL] run {run_num} EXCEPTION: {e!r}")

    _print_summary()

    print(f"\n[CELLQ_CONT_MARL] COMPLETE. Results CSV: {RESULTS_CSV_NAME} "
          f"(under {_CORR}/results/). Grep for '[SIDE_SCAN]', '[FLOW SRC]', "
          f"'[NASH_BARGAIN] [monitor]', '[MONITOR]', '[MEAS_SIDE]' and '] error'.")


if __name__ == "__main__":
    main()
else:
    main()
