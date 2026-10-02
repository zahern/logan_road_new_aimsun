"""
run_logan_turncost_ab.py -- quick MEASURED_TURN_COST A/B (Aimsun).

NO_TSP vs CELLQ_CONT_DE (champion) vs CELLQ_CONT_DE_TURNC (champion +
movement-decomposed side cost). 3 seeds each (9 runs, ~2 h). Same-seed
guarded verdict prints in-session. Uses the current engine build.
"""
import os as _os, sys as _sys, time as _time, glob as _glob
import csv as _csv
import importlib.util as _ilu
from collections import defaultdict

SEEDS = [300, 400, 500]
RESULTS_CSV_NAME = "logan_turncost_ab.csv"
EXPECTED_BUILD = "2026-09-28T15:00-passgate-diag"

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
                    _d, "run_logan_turncost_ab.py")):
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

_FEEDS = {"MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True,
          "MEASURED_SIDE_COST": True, "CASCADE_COST_MODE": True}
_MON = {"CONTINUOUS_MONITOR_MODE": True, "BXT_CONTINUOUS_MODE": True,
        "CONTINUOUS_MONITOR_MIN_GAIN_PAXS": 50}
_POG = {"MONITOR_STATE_GATE": True, "SIDLESS_MONITOR_HOLD": True,
        "SIDE_QUEUE_FLOOR": True, "MONITOR_PROG_WEIGHT": 1.0,
        "MONITOR_BUS_ZERO": True, "PROGRESSION_GATE": True,
        "RECOVERABILITY_GATE": True,
        "DIAG_FLOW_STAGE": True, "DIAG_DECISION": True}
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
          "BXT_EVAL_DIAGNOSTICS": True}

_CLQ_CHAMP = {**_CELLQ, **_MON, **_POG, **_FEEDS,
              "BXT_SOLVER": "de",
              "CELLQLEARN_MIN_GAIN_S": 8.0,
              "DECIDER_COST_VETO_RATIO": 2.5,
              "REWARD_GE_SOLVER": "exact",
              "BXT_POG_REWARD": True}

EXPERIMENTS = [
    {"name": "NO_TSP", "strategy": "NORMAL", "coordinated": False,
     "coordination_algo": "KALMAN", "reward_overrides": {}},
    {"name": "CELLQ_CONT_DE", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": dict(_CLQ_CHAMP)},
    {"name": "CELLQ_CONT_DE_TURNC", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": {**_CLQ_CHAMP, "MEASURED_TURN_COST": True}},
]

_KPI_KEYS = ("Objective_PaxPerDelayHr", "AvgBusPassDelay_s",
             "AvgCarPassDelay_s", "Net_MeanQueue_All", "TSP_Extensions",
             "TSP_Insertions", "SimDuration_hrs", "TotalPassDelay_hrs",
             "PaxEquivPassages", "Net_VQVeh_All", "N_BusTrips")
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
    print("\n" + "=" * 70)
    print("[TURNCOST] SUMMARY (mean; obj higher=better)")
    _base = {}
    for name, ks in byarm.items():
        def m(kk):
            return sum(k[kk] for k in ks) / len(ks)
        print(f"  {name:22s} obj={m('Objective_PaxPerDelayHr'):7.1f} "
              f"bus={m('AvgBusPassDelay_s'):.2f}s car={m('AvgCarPassDelay_s'):.2f}s "
              f"vq={m('Net_VQVeh_All'):.0f} ext={m('TSP_Extensions'):.0f} "
              f"ins={m('TSP_Insertions'):.0f}")
        if name == "NO_TSP":
            _base = {s: k for (n, s, k) in _SESSION
                     if n == "NO_TSP" and k.get("SimDuration_hrs", 0) >= 1.4}
    print("-" * 70)
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
            print(f"  {name:22s} vs NO_TSP: totDelay%={_td/_ok:+.2f} "
                  f"served%={_sv/_ok:.1f}")
    print("=" * 70)


def main():
    try:
        import GKModel as _gk
    except Exception:
        pass
    else:
        try:
            _net = _gk.gk.getApplicationNet()
            if _net is None:
                raise SystemExit("Logan model must be open in Aimsun first")
        except SystemExit:
            raise
        except Exception:
            pass
    _br_path = _os.path.join(_CORR, "batch_runner.py")
    _spec = _ilu.spec_from_file_location("logan_batch", _br_path)
    _br = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_br)
    print(f"[TURNCOST] arms={[e['name'] for e in EXPERIMENTS]} "
          f"seeds={SEEDS} ({len(EXPERIMENTS) * len(SEEDS)} runs)")
    rep = _br.get_first_replication()
    run_num = 0
    for exp in EXPERIMENTS:
        for seed in SEEDS:
            run_num += 1
            name = exp["name"]
            cfg = dict(exp.get("reward_overrides") or {})
            print(f"\n[TURNCOST] === run {run_num}: {name} seed={seed} === "
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
                    print(f"[TURNCOST]   {name} seed {seed}: "
                          f"obj={k['Objective_PaxPerDelayHr']:.1f} "
                          f"bus={k['AvgBusPassDelay_s']:.2f}s "
                          f"car={k['AvgCarPassDelay_s']:.2f}s "
                          f"vq={k['Net_VQVeh_All']:.0f} "
                          f"ext={k['TSP_Extensions']:.0f} "
                          f"ins={k['TSP_Insertions']:.0f} "
                          f"[{_time.time()-t0:.0f}s]")
            except Exception as e:
                print(f"[TURNCOST] run {run_num} EXCEPTION: {e!r}")
    _print_summary()


if __name__ == "__main__":
    main()
else:
    main()