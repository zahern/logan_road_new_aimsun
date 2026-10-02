"""
run_logan_twoway_search.py -- EXPANDED SEARCH: two-way through-band veto on Logan.

WHY THIS FILE
 -------------
The Logan ladder (run_logan_cellq_cont_marl_test.py) showed every acting arm
losing to NO_TSP, with the blame reports pointing at green-shifting actions
(GE/INS/OC/GR) whose predicted benefit ignored the OPPOSITE corridor direction
and downstream progression. The engine now prices the opposite main direction
from measured queues (_measured_opposite_main_delay, always on), and this file
tests the HARD structural gate on top: the two-way through-band floors
(paper Eqs prog_in/band_*), which veto any action whose induced clock shift
would newly push either directional band below its floor.

  band b = TWOWAY_GREEN_S - |worst-neighbour relative shift|
  veto when b < B_PLUS_MIN or b < B_MINUS_MIN and the shift DEEPENS it.

With G=35 s: B+=B-=10 vetoes shifts beyond 25 s; B+=B-=20 vetoes beyond 15 s
(GE grids run 5-15 s, INS 10-20 s, so 20 is the meaningfully strict setting).

ARMS (all GLOBAL_REWARD; seed 300)
----------------------------------
  NO_TSP                              -- baseline.
  CELLQLEARN_CONT_PURPOSE             -- band OFF (reference; the best CELLQ arm
                                         of the previous ladder, ~-0.1%).
  CELLQLEARN_CONT_PURPOSE_TW10        -- band ON, floors 10 s.
  CELLQLEARN_CONT_PURPOSE_TW20        -- band ON, floors 20 s.
  DCTSP_MARL_CONT_PURPOSE             -- band OFF (reference; worst family).
  DCTSP_MARL_CONT_PURPOSE_TW10        -- band ON, floors 10 s.
  DCTSP_MARL_CONT_PURPOSE_TW20        -- band ON, floors 20 s.
  CELLQLEARN_CONT_PURPOSE_TW20_DE     -- TW20 + DE integer-lattice magnitudes
                                         instead of deficit closed-form (the
                                         full "everything on" job: band veto
                                         + measured costs + solved timing).

HYPOTHESIS: the band veto removes the progression-breaking actions that the
measured opposite-main cost alone cannot fully block (it prices delay, not
offset drift). If TW20 > PURPOSE > NO_TSP on obj, the structural gate is the
missing piece; if TW arms sit below PURPOSE, the veto is over-suppressing
(loosen floors or drop to TW10).

HOW TO RUN (inside Aimsun, Logan model open)
--------------------------------------------
  1. FULLY restart Aimsun (engine AND specialized_modes are session-cached;
     this build registers the TWOWAY flags in MODE_FLAGS so they propagate
     per-arm and reset between arms) and open
     logan_road_new/Logan_RD_for_QUT_with_detectors.ang.
  2. Run this file from the Aimsun Python console.
  3. Check the [LOAD] line shows ENGINE_BUILD matching EXPECTED_ENGINE_BUILD.

WHAT TO GREP AFTERWARDS
-----------------------
  '[TWOWAY]'          -- one line per VETOED action (band breach + shift).
                         Zero lines on a TW arm = the band never binds (floors
                         too loose / shifts too small) -> not a real test.
  '[ARM]'             -- per-run effective flags; TW arms must show
                         TWOWAY_BAND_MODE=True with the right floors.
  '[DECISION]'        -- committed actions (post-veto) for diagnose_vs_notsp.
  '[MONITOR_GATE]'    -- continuous-monitor holds (see main ladder docstring).
"""
import os as _os, sys as _sys, time as _time, importlib.util as _ilu

# ── Editable test design ──────────────────────────────────────────────────────
SEEDS = [300]
DEMAND_SCALAR = 1.0
RESULTS_CSV_NAME = "logan_twoway_search.csv"
EXPECTED_ENGINE_BUILD = "2026-09-26T16:30-family-canonical"

# ── Base configs (identical to run_logan_cellq_cont_marl_test.py) ─────────────
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
    "BXT_EVAL_DIAGNOSTICS": True, "DIAG_FLOW_STAGE": True, "DIAG_DECISION": True,
}
_CONT = {
    "CONTINUOUS_MONITOR_MODE": True,
    "BXT_CONTINUOUS_MODE": True,
    "CONTINUOUS_MONITOR_MIN_GAIN_PAXS": 50.0,
}
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
_MARL_CONT = {
    "CONTINUOUS_MONITOR_MODE": True,
    "CONTINUOUS_MONITOR_MIN_GAIN_PAXS": 50.0,
}
_MARL_PURPOSE = {
    "MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True,
    "MEASURED_SIDE_COST": True, "CASCADE_COST_MODE": True,
    "SELFORG_MIN_BUS_DELAY_S": 15.0,
    "DECIDER_COST_VETO_RATIO": 2.0,
}
# Two-way band floors: with TWOWAY_GREEN_S=35, floors of 10 veto shifts beyond
# 25 s; floors of 20 veto beyond 15 s (GE grids 5-15 s, INS 10-20 s).
_TW10 = {"TWOWAY_BAND_MODE": True, "B_PLUS_MIN": 10.0, "B_MINUS_MIN": 10.0}
_TW20 = {"TWOWAY_BAND_MODE": True, "B_PLUS_MIN": 20.0, "B_MINUS_MIN": 20.0}

_CELLQ_PURPOSE_ALL = {**_CELLQ_BASE, **_CONT, **_PURPOSE}
_MARL_PURPOSE_ALL = {**_MARL, **_MARL_CONT, **_MARL_PURPOSE}

EXPERIMENTS_TEST = [
    {"name": "NO_TSP", "strategy": "NORMAL", "coordinated": False,
     "coordination_algo": "KALMAN", "reward_overrides": {}},
    {"name": "CELLQLEARN_CONT_PURPOSE", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": dict(_CELLQ_PURPOSE_ALL)},
    {"name": "CELLQLEARN_CONT_PURPOSE_TW10", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": {**_CELLQ_PURPOSE_ALL, **_TW10}},
    {"name": "CELLQLEARN_CONT_PURPOSE_TW20", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": {**_CELLQ_PURPOSE_ALL, **_TW20}},
    {"name": "CELLQLEARN_CONT_PURPOSE_TW20_DE", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": {**_CELLQ_PURPOSE_ALL, **_TW20,
                          "BXT_SOLVER": "de"}},
    {"name": "DCTSP_MARL_CONT_PURPOSE", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "KALMAN",
     "reward_overrides": dict(_MARL_PURPOSE_ALL)},
    {"name": "DCTSP_MARL_CONT_PURPOSE_TW10", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "KALMAN",
     "reward_overrides": {**_MARL_PURPOSE_ALL, **_TW10}},
    {"name": "DCTSP_MARL_CONT_PURPOSE_TW20", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "KALMAN",
     "reward_overrides": {**_MARL_PURPOSE_ALL, **_TW20}},
]

GLOBAL_MEASURED_FEED = True
GLOBAL_MEASURED_SIDE_COST = True
GLOBAL_CASCADE_COST = True


# ── Runner plumbing (same as run_logan_cellq_cont_marl_test.py) ───────────────
def _module_root(_marker="run_logan_twoway_search.py"):
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
_TAG = "[TWOWAY_SEARCH]"


def _assert_logan_open():
    try:
        from PyANGKernel import GKSystem
        _m = GKSystem.getSystem().getActiveModel()
    except Exception:
        print(f"{_TAG} WARN: no Aimsun model handle; assuming Logan is open.")
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
    print(f"{_TAG} corridor guard OK: Logan model is open ({_nm!r}).")


def _load_logan_runner():
    _br_path = _os.path.join(_CORR_DIR, "batch_runner.py")
    if not _os.path.isfile(_br_path):
        raise RuntimeError(f"{_TAG} not found: {_br_path}")
    _spec = _ilu.spec_from_file_location("_br_tw", _br_path)
    _br = _ilu.module_from_spec(_spec)
    _sys.modules["_br_tw"] = _br
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


def _count_twoway_vetoes(logdir_hint=None):
    """Newest Aimsun log: count [TWOWAY] veto lines (band actually binding?)."""
    try:
        _ld = logdir_hint or _os.path.join(_CORR_DIR, "logs")
        _logs = _glob.glob(_os.path.join(_ld, "Aimsun_TSP_Log_*.txt"))
        if not _logs:
            return None, 0
        _f = max(_logs, key=_os.path.getmtime)
        _n = 0
        with open(_f, encoding="utf-8", errors="replace") as _fh:
            for _ln in _fh:
                if "[TWOWAY]" in _ln:
                    _n += 1
        return _os.path.basename(_f), _n
    except Exception:
        return None, 0


def _print_run_kpis(name, seed):
    k = _read_latest_kpis(name, seed)
    if not k:
        print(f"{_TAG}   (no KPIs found for {name} seed {seed} yet)")
        return
    _SESSION.append((name, seed, k))
    _lf, _nv = _count_twoway_vetoes()
    _tw = f" tw_veto={_nv}" if "TW" in name else ""
    print(f"{_TAG}   {name} seed {seed}: obj={k['Objective_PaxPerDelayHr']:.1f} "
          f"bus={k['AvgBusPassDelay_s']:.1f}s car={k['AvgCarPassDelay_s']:.1f}s "
          f"queue={k['Net_MeanQueue_All']:.0f} ext={k['TSP_Extensions']:.0f} "
          f"ins={k['TSP_Insertions']:.0f} dur={k['SimDuration_hrs']:.2f}h{_tw}")


def _print_summary():
    if not _SESSION:
        return
    from collections import defaultdict
    byarm = defaultdict(list)
    for name, seed, k in _SESSION:
        if k.get("SimDuration_hrs", 0) >= 1.4:
            byarm[name].append(k)
    print("\n" + "=" * 64)
    print(f"{_TAG} SESSION SUMMARY (mean over full runs; obj higher=better)")
    print(f"  {'arm':36s} {'obj':>7s} {'bus_s':>6s} {'car_s':>6s} {'queue':>6s} {'ext':>5s}")
    base = None
    for name, ks in byarm.items():
        def m(kk): return sum(k[kk] for k in ks) / len(ks)
        row = (m("Objective_PaxPerDelayHr"), m("AvgBusPassDelay_s"),
               m("AvgCarPassDelay_s"), m("Net_MeanQueue_All"), m("TSP_Extensions"))
        print(f"  {name:36s} {row[0]:7.1f} {row[1]:6.1f} {row[2]:6.1f} "
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
    print(f"{_TAG} runner = {_os.path.join(_CORR_DIR, 'batch_runner.py')}")
    print(f"{_TAG} expect ENGINE_BUILD={EXPECTED_ENGINE_BUILD} on the [LOAD] line")
    print(f"{_TAG} arms={[e['name'] for e in EXPERIMENTS_TEST]} seeds={SEEDS}")

    rep_obj = _br.get_first_replication()

    base_demands = {}
    if abs(float(DEMAND_SCALAR) - 1.0) > 1e-9:
        try:
            _br.set_demand_scalar(DEMAND_SCALAR, base_demands)
        except Exception as e:
            print(f"{_TAG} WARN demand scalar {DEMAND_SCALAR}: {e!r}")

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
            print(f"\n{_TAG} === run {run_num}: {name} seed={seed} "
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
                print(f"{_TAG} run {run_num} done in {_time.time()-t0:.0f}s")
                _print_run_kpis(name, seed)
            except Exception as e:
                print(f"{_TAG} run {run_num} EXCEPTION: {e!r}")

    _print_summary()

    print(f"\n{_TAG} COMPLETE. Results CSV: {RESULTS_CSV_NAME} (under "
          f"{_CORR}/results/). Grep '[TWOWAY]' (band vetoes), '[ARM]' (flags), "
          f"'[DECISION]', '[MONITOR_GATE]' and '] error' (want 0).")


if __name__ == "__main__":
    main()
else:
    main()
