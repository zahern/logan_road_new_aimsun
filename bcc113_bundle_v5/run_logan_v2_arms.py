"""
run_logan_v2_arms.py -- v2 mechanism tests (Aimsun, build 16:00-v2arms).

  NO_TSP                 baseline
  MARL_CONT              champion MARL (generic pool, continuous, POG stack)
  MARL_CONT_TURNC        MARL_CONT + MEASURED_TURN_COST (movement-level side
                         cost -- the flag is exercised HERE, where car-only
                         ticks actually reach candidate ranking, unlike CELLQ)
  CELLQ_CONT_DE_HEADROOM champion CELLQ + HEADROOM_RESERVE_S=4 (carve
                         repayable cross slack so recovery trims can fire)

4 arms x 3 seeds = 12 runs ~2.7 h. Grep [HEADROOM] (reserve carved, bus
duration reduced) and [RECOVER_PLAN]/TSP_Retiming (debt actually repaid) vs
the champion's ret=0 baseline.
"""
import os as _os, sys as _sys, time as _time, glob as _glob
import csv as _csv
import importlib.util as _ilu
from collections import defaultdict

SEEDS = [300, 400, 500]
RESULTS_CSV_NAME = "logan_v2_arms.csv"

try:
    _ROOT = _os.path.dirname(_os.path.abspath(__file__))
except (NameError, TypeError):
    _ROOT = None
if not _ROOT or not _os.path.isdir(_ROOT):
    try:
        from PyANGKernel import GKSystem
        _d = _os.path.abspath(str(GKSystem.getSystem().getActiveModel(
            ).getDocumentDirectory().absolutePath()))
        for _ in range(6):
            if _os.path.isfile(_os.path.join(
                    _d, "run_logan_v2_arms.py")):
                _ROOT = _d
                break
            _d = _os.path.dirname(_d)
    except Exception:
        _ROOT = None
if not _ROOT:
    _ROOT = _os.path.abspath(_os.getcwd())
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
_CORR = _os.path.join(_ROOT, "logan_road_new")
CONTROLLER_PATH = _os.path.join(_ROOT, "shared_tsp_engine",
                                "intersection_controller.py")
RUN_CONFIG_PATH = _os.path.join(_CORR, "run_config.py")
EXPECTED_BUILD = "2026-09-28T20:10-replreset"

_FEEDS = {"MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True,
          "MEASURED_SIDE_COST": True, "CASCADE_COST_MODE": True}
_MON = {"CONTINUOUS_MONITOR_MODE": True, "BXT_CONTINUOUS_MODE": True,
        "CONTINUOUS_MONITOR_MIN_GAIN_PAXS": 50}
_POG = {"MONITOR_STATE_GATE": True, "SIDLESS_MONITOR_HOLD": True,
        "SIDE_QUEUE_FLOOR": True, "MONITOR_PROG_WEIGHT": 1.0,
        "MONITOR_BUS_ZERO": True, "PROGRESSION_GATE": True,
        "RECOVERABILITY_GATE": True,
        "DIAG_FLOW_STAGE": True, "DIAG_DECISION": True}
_MARL = {"GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0, "REWARD_BETA": 1.0,
         "REWARD_GAMMA": 1.0, "DCTSP_GREEN_REALLOC_MODE": True,
         "GREEN_REALLOC_RECOVER_FRACTION": 1.0, "DCTSP_W_H": 0.50,
         "DCTSP_CAR_WEIGHT": 1.00, "BXT_MODE": False, "DCTSP_ZIG_MODE": False,
         "MP_ECTM_MODE": False, "BARGAIN_SPM_MODE": False,
         "CENTRALIZED_MODE": False, "DCTSP_CONGESTION_GATE": True,
         "DCTSP_CONGESTION_GATE_FRACTION": 0.70}
_CELLQ = {"GLOBAL_REWARD_MODE": True, "BXT_MODE": True,
          "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False,
          "BARGAIN_SPM_MODE": False, "CENTRALIZED_MODE": False,
          "CELLQLEARN_DP_MODE": False,
          "BXT_DT_S": 1.0, "BXT_EPSILON": 0.02, "BXT_ALPHA": 0.2,
          "BXT_GAMMA": 0.01, "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
          "BXT_WARMSTART_FROM_SHARED": True, "BUS_PAX_WEIGHT": 1.3,
          "GREEN_KEEP_CREDIT_S": 3.0, "MULTIBUS_MAX_FACTOR": 1.0,
          "CORRIDOR_REWARD_NEIGHBOR_W": 0.5,
          "TSP_CYCLE_LENGTH_OVERRIDE_S": 135.0,
          "PHASE_SEQ_MAX_PER_CYCLE": 1,
          "BXT_NET_BENEFIT_GATE": True, "SELFORG_MIN_BUS_DELAY_S": 15.0,
          "BXT_EVAL_DIAGNOSTICS": True,
          "BXT_SOLVER": "de", "CELLQLEARN_MIN_GAIN_S": 8.0,
          "DECIDER_COST_VETO_RATIO": 2.5, "REWARD_GE_SOLVER": "exact",
          "BXT_POG_REWARD": True}

EXPERIMENTS = [
    {"name": "NO_TSP", "strategy": "NORMAL", "coordinated": False,
     "coordination_algo": "KALMAN", "reward_overrides": {}},
    {"name": "MARL_CONT", "strategy": "GLOBAL_REWARD", "coordinated": True,
     "coordination_algo": "KALMAN",
     "reward_overrides": {**_MARL, **_MON, **_POG, **_FEEDS}},
    {"name": "MARL_CONT_TURNC", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "KALMAN",
     "reward_overrides": {**_MARL, **_MON, **_POG, **_FEEDS,
                          "MEASURED_TURN_COST": True}},
    {"name": "CELLQ_CONT_DE_HEADROOM", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": {**_CELLQ, **_MON, **_POG, **_FEEDS,
                          "HEADROOM_RESERVE_S": 4.0}},
]

_KPI_KEYS = ("Objective_PaxPerDelayHr", "AvgBusPassDelay_s",
             "AvgCarPassDelay_s", "Net_MeanQueue_All", "TSP_Extensions",
             "TSP_Insertions", "TSP_GreenRealloc", "TSP_EarlyRed",
             "TSP_PhaseSkip", "TSP_PhaseRot", "SimDuration_hrs",
             "TotalPassDelay_hrs", "PaxEquivPassages", "Net_VQVeh_All",
             "N_BusTrips")
_SESSION = []


def _read_latest_kpis(name, seed):
    ds = sorted(_glob.glob(_os.path.join(
        _CORR, "results", f"{name}_seed{seed}_*")), key=_os.path.getmtime)
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


def _print_summary():
    byarm = defaultdict(list)
    for name, seed, k in _SESSION:
        if k.get("SimDuration_hrs", 0) >= 1.4:
            byarm[name].append(k)
    print("\n" + "=" * 72)
    print("[V2ARMS] SUMMARY (mean; obj higher=better)")
    _base = {}
    for name, ks in byarm.items():
        def m(kk):
            return sum(k[kk] for k in ks) / len(ks)
        tot = sum(m(kk) for kk in ("TSP_Extensions", "TSP_Insertions",
                                   "TSP_GreenRealloc", "TSP_EarlyRed",
                                   "TSP_PhaseSkip", "TSP_PhaseRot"))
        print(f"  {name:24s} obj={m('Objective_PaxPerDelayHr'):7.1f} "
              f"bus={m('AvgBusPassDelay_s'):.2f}s car={m('AvgCarPassDelay_s'):.2f}s "
              f"vq={m('Net_VQVeh_All'):.0f} totAct={tot:.0f}")
        if name == "NO_TSP":
            _base = {s: k for (n, s, k) in _SESSION
                     if n == "NO_TSP" and k.get("SimDuration_hrs", 0) >= 1.4}
    print("-" * 72)
    for name, ks in byarm.items():
        if name == "NO_TSP":
            continue
        _td = _sv = _ok = 0
        for k in ks:
            _seed = None
            for (sn, ss, sk) in _SESSION:
                if sk is k:
                    _seed = ss
                    break
            bb = _base.get(_seed)
            if bb and bb.get("TotalPassDelay_hrs"):
                _td += (k["TotalPassDelay_hrs"]
                        - bb["TotalPassDelay_hrs"]) \
                       / bb["TotalPassDelay_hrs"] * 100
                _sv += k["PaxEquivPassages"] / bb["PaxEquivPassages"] * 100
                _ok += 1
        if _ok:
            print(f"  {name:24s} vs NO_TSP: totDelay%={_td/_ok:+.2f} "
                  f"served%={_sv/_ok:.1f}")
    print("=" * 72)


def main():
    try:
        import GKModel as _gk
    except Exception:
        pass
    else:
        try:
            if _gk.gk.getApplicationNet() is None:
                raise SystemExit("Logan model must be open in Aimsun first")
        except SystemExit:
            raise
        except Exception:
            pass
    _br_path = _os.path.join(_CORR, "batch_runner.py")
    _spec = _ilu.spec_from_file_location("logan_batch", _br_path)
    _br = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_br)
    print(f"[V2ARMS] expect build={EXPECTED_BUILD}")
    print(f"[V2ARMS] arms={[e['name'] for e in EXPERIMENTS]} "
          f"seeds={SEEDS} ({len(EXPERIMENTS) * len(SEEDS)} runs)")
    rep = _br.get_first_replication()
    run_num = 0
    for exp in EXPERIMENTS:
        for seed in SEEDS:
            run_num += 1
            name = exp["name"]
            cfg = dict(exp.get("reward_overrides") or {})
            print(f"\n[V2ARMS] === run {run_num}: {name} seed={seed} === "
                  f"{_time.strftime('%H:%M:%S')}")
            _br.set_seed(rep, seed)
            _br.write_run_config(
                name, exp["strategy"], seed, 1.0,
                exp["coordinated"], exp["coordination_algo"],
                RUN_CONFIG_PATH,
                global_reward_mode=(exp["strategy"] != "NORMAL"),
                reward_cfg=cfg, bus_predictor="ADAPTIVE_KALMAN",
                results_csv_name=RESULTS_CSV_NAME,
                active_intersections=exp.get("active_intersections", None))
            _br._purge_pyc(CONTROLLER_PATH)
            t0 = _time.time()
            try:
                _br.run_replication(rep)
                k = _read_latest_kpis(name, seed)
                if k:
                    _SESSION.append((name, seed, k))
                    print(f"[V2ARMS]   {name} seed {seed}: "
                          f"obj={k['Objective_PaxPerDelayHr']:.1f} "
                          f"bus={k['AvgBusPassDelay_s']:.2f}s "
                          f"car={k['AvgCarPassDelay_s']:.2f}s "
                          f"vq={k['Net_VQVeh_All']:.0f} "
                          f"ext={k['TSP_Extensions']:.0f} "
                          f"ins={k['TSP_Insertions']:.0f} "
                          f"[{_time.time()-t0:.0f}s]")
            except Exception as e:
                print(f"[V2ARMS] run {run_num} EXCEPTION: {e!r}")
    _print_summary()


if __name__ == "__main__":
    main()
else:
    main()