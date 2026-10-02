"""
run_logan_champion_paper.py -- paper-method champion search on Logan (Aimsun).

SCOPE (2026-09-28): the paper's key methods, NOT a kitchen sink. Every arm is
GLOBAL_REWARD, continuous-monitor based, with the DE solver where the method
has one. Three seeds (300/400/500) so the champion is the one that is LEAST
SENSITIVE across seeds, not the best single run.

  NO_TSP               -- baseline.
  MARL_CONT            -- analytic MARL, generic pool, measured feeds,
                          champion restraint (veto 3.5, congestion gate).
  MARL_CONT_EASE       -- softer gate (veto 2.5, 15 s bus-delay warrant).
  MARL_CONT_EXACT      -- MARL_CONT + exact lattice GE sizing.
  CELLQ_CONT_DE        -- CellQLearn champion (EASE: min-gain 8, veto 2.5,
                          BXT_SOLVER=de, exact GE) + BXT_POG_REWARD teaching.
  CELLQ_CONT_DE_NOPOG  -- same minus the learner POG term (isolates it).
  CELLQ_CONT_DE_STIFF  -- min-gain 15, veto 2.0, de, DE generic-GE.
  NASH_CONT            -- Nash bargaining, continuous, min-gain 50.
  NASH_CONT_GATED      -- + 15 s bus-delay/min-gain warrants + veto 2.0.
  NASH_CONT_INTDUR     -- gated + integer-duration search (recoverable
                          bounds baked into the search).

POG / funnel wiring carried by EVERY non-NO_TSP arm (explicit, so the search
is self-documenting and immune to default drift):
  - MONITOR_STATE_GATE / SIDLESS_MONITOR_HOLD / SIDE_QUEUE_FLOOR  (state gates)
  - MONITOR_PROG_WEIGHT = 1.0   (POG priced inside the monitor reward)
  - MONITOR_BUS_ZERO    = True  (no phantom bus credit on car-only ticks)
  - PROGRESSION_GATE    = True  (300 pax-s veto on offset-shifting grants)
  - RECOVERABILITY_GATE = True  (no unrepayable cycle-lengthening actions)
  - MEASURED feeds + CASCADE    (flow/queue adaptivity)
  - BXT_POG_REWARD on CELLQ arms (learner also taught the POG loss)
  - engine: [PLAN]/[PHASEMAP]/[PLANDUMP], push-registry plan broadcast,
    per-junction cycle-scaled bounds (GE_MAX_FRAC_OF_CYCLE=0.15), adaptive DE.

HOW TO RUN: full Aimsun restart, Logan model open, then
  exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\"
            r"run_logan_champion_paper.py", encoding="utf-8").read())
Verify [LOAD] shows EXPECTED_ENGINE_BUILD. 10 arms x 3 seeds = 30 runs,
~6.5 h. The summary prints obj/bus/car/totAct per arm plus the guarded
verdict (totDelay% vs NO_TSP same-seed, served%, VQ, busTrips).
"""
import os as _os, sys as _sys, time as _time, glob as _glob
import csv as _csv
import importlib.util as _ilu
from collections import defaultdict

_EXPECTED = "2026-09-28T09:20-plandump"
SEEDS = [300, 400, 500]
RESULTS_CSV_NAME = "logan_champion_paper.csv"

try:
    _ROOT = _os.path.dirname(_os.path.abspath(__file__))
except (NameError, TypeError):
    _ROOT = None
if not _ROOT or not _os.path.isdir(_ROOT):
    # Pasted into the Aimsun console: __file__ is undefined; resolve the
    # bundle root by walking up from the active model document.
    try:
        from PyANGKernel import GKSystem
        _d = _os.path.abspath(str(GKSystem.getSystem().getActiveModel(
            ).getDocumentDirectory().absolutePath()))
        for _ in range(6):
            if _os.path.isfile(_os.path.join(
                    _d, "run_logan_champion_paper.py")):
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
_CORR_DIR = _CORR
CONTROLLER_PATH = _os.path.join(_ROOT, "shared_tsp_engine",
                                "intersection_controller.py")
RUN_CONFIG_PATH = _os.path.join(_CORR, "run_config.py")

# ── Shared building blocks -------------------------------------------------
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

_MARL = {"GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0, "REWARD_BETA": 1.0,
         "REWARD_GAMMA": 1.0, "DCTSP_GREEN_REALLOC_MODE": True,
         "GREEN_REALLOC_RECOVER_FRACTION": 1.0, "DCTSP_W_H": 0.50,
         "DCTSP_CAR_WEIGHT": 1.00, "BXT_MODE": False, "DCTSP_ZIG_MODE": False,
         "MP_ECTM_MODE": False, "BARGAIN_SPM_MODE": False,
         "CENTRALIZED_MODE": False, "DCTSP_CONGESTION_GATE": True,
         "DCTSP_CONGESTION_GATE_FRACTION": 0.70}

_NASH = {"GLOBAL_REWARD_MODE": True, "NASH_BARGAIN_MODE": True,
         "CONTINUOUS_MONITOR_MODE": True, "NASH_CONTINUOUS_MODE": True,
         "NASH_BUS_WEIGHT": 0.0, "NASH_CROSS_WEIGHT": 1.0,
         "CONTINUOUS_MONITOR_MIN_GAIN_PAXS": 50.0}

EXPERIMENTS = [
    {"name": "NO_TSP", "strategy": "NORMAL", "coordinated": False,
     "coordination_algo": "KALMAN", "reward_overrides": {}},
    {"name": "MARL_CONT", "strategy": "GLOBAL_REWARD", "coordinated": True,
     "coordination_algo": "KALMAN",
     "reward_overrides": {**_MARL, **_MON, **_POG, **_FEEDS}},
    {"name": "MARL_CONT_EASE", "strategy": "GLOBAL_REWARD", "coordinated": True,
     "coordination_algo": "KALMAN",
     "reward_overrides": {**_MARL, **_MON, **_POG, **_FEEDS,
                          "DECIDER_COST_VETO_RATIO": 2.5,
                          "SELFORG_MIN_BUS_DELAY_S": 15.0}},
    {"name": "MARL_CONT_EXACT", "strategy": "GLOBAL_REWARD", "coordinated": True,
     "coordination_algo": "KALMAN",
     "reward_overrides": {**_MARL, **_MON, **_POG, **_FEEDS,
                          "REWARD_GE_SOLVER": "exact"}},
    {"name": "CELLQ_CONT_DE", "strategy": "GLOBAL_REWARD", "coordinated": True,
     "coordination_algo": "SHOCKWAVE",
     "reward_overrides": {**_CELLQ, **_MON, **_POG, **_FEEDS,
                          "BXT_SOLVER": "de",
                          "CELLQLEARN_MIN_GAIN_S": 8.0,
                          "DECIDER_COST_VETO_RATIO": 2.5,
                          "REWARD_GE_SOLVER": "exact",
                          "BXT_POG_REWARD": True}},
    {"name": "CELLQ_CONT_DE_NOPOG", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": {**_CELLQ, **_MON, **_POG, **_FEEDS,
                          "BXT_SOLVER": "de",
                          "CELLQLEARN_MIN_GAIN_S": 8.0,
                          "DECIDER_COST_VETO_RATIO": 2.5,
                          "REWARD_GE_SOLVER": "exact"}},
    {"name": "CELLQ_CONT_DE_STIFF", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "SHOCKWAVE",
     "reward_overrides": {**_CELLQ, **_MON, **_POG, **_FEEDS,
                          "BXT_SOLVER": "de",
                          "CELLQLEARN_MIN_GAIN_S": 15.0,
                          "DECIDER_COST_VETO_RATIO": 2.0,
                          "REWARD_GE_SOLVER": "de",
                          "BXT_POG_REWARD": True}},
    # V2 (2026-09-28): CELLQ champion + movement-decomposed side cost.
    # Dedicated turn lanes are distinct movements; MEASURED_TURN_COST prices
    # each side phase's turnings under their own extra red instead of lumping
    # them at section level. Engine flag is additive/off-by-default, so the
    # running champion search is unaffected. ENABLE for the v2 pass (the
    # current arm-table is already deep; keep this one OFF now).
    {"name": "CELLQ_CONT_DE_TURNC", "enabled": False,
     "strategy": "GLOBAL_REWARD", "coordinated": True,
     "coordination_algo": "SHOCKWAVE",
     "reward_overrides": {**_CELLQ, **_MON, **_POG, **_FEEDS,
                          "BXT_SOLVER": "de",
                          "CELLQLEARN_MIN_GAIN_S": 8.0,
                          "DECIDER_COST_VETO_RATIO": 2.5,
                          "REWARD_GE_SOLVER": "exact",
                          "BXT_POG_REWARD": True,
                          "MEASURED_TURN_COST": True}},
    {"name": "NASH_CONT", "strategy": "GLOBAL_REWARD", "coordinated": True,
     "coordination_algo": "KALMAN",
     "reward_overrides": {**_NASH, **_POG, **_FEEDS}},
    {"name": "NASH_CONT_GATED", "strategy": "GLOBAL_REWARD", "coordinated": True,
     "coordination_algo": "KALMAN",
     "reward_overrides": {**_NASH, **_POG, **_FEEDS,
                          "NASH_MIN_BUS_DELAY_S": 15.0,
                          "NASH_MIN_GAIN_S": 15.0,
                          "DECIDER_COST_VETO_RATIO": 2.0}},
    {"name": "NASH_CONT_INTDUR", "strategy": "GLOBAL_REWARD",
     "coordinated": True, "coordination_algo": "KALMAN",
     "reward_overrides": {**_NASH, **_POG, **_FEEDS,
                          "NASH_MIN_BUS_DELAY_S": 15.0,
                          "NASH_MIN_GAIN_S": 15.0,
                          "DECIDER_COST_VETO_RATIO": 2.0,
                          "NASH_INTEGER_DURATIONS": True,
                          "MAX_GE_EXTENSION_S": 15,
                          "DCTSP_MIN_INS_DURATION_S": 5,
                          "DCTSP_MAX_INS_DURATION_S": 20}},
]

_KPI_KEYS = ("Objective_PaxPerDelayHr", "AvgBusPassDelay_s",
             "AvgCarPassDelay_s", "AvgBusTT_s", "Net_MeanQueue_All",
             "TSP_Extensions", "TSP_Insertions", "SimDuration_hrs",
             "TotalPassDelay_hrs", "PaxEquivPassages", "Net_ExitCount_All",
             "Net_VQVeh_All", "N_BusTrips",
             "TSP_GreenRealloc", "TSP_EarlyRed", "TSP_OffsetCorr",
             "TSP_PhaseSkip", "TSP_PhaseRot")
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


def _print_run_kpis(name, seed):
    k = _read_latest_kpis(name, seed)
    if not k:
        print(f"[CHAMP]   (no KPIs for {name} seed {seed})")
        return
    _SESSION.append((name, seed, k))
    tot = sum(k.get(kk, 0.0) or 0.0 for kk in (
        "TSP_Extensions", "TSP_Insertions", "TSP_GreenRealloc",
        "TSP_EarlyRed", "TSP_OffsetCorr", "TSP_PhaseSkip", "TSP_PhaseRot"))
    print(f"[CHAMP]   {name} seed {seed}: obj={k['Objective_PaxPerDelayHr']:.1f} "
          f"bus={k['AvgBusPassDelay_s']:.1f}s car={k['AvgCarPassDelay_s']:.1f}s "
          f"totD={k['TotalPassDelay_hrs']:.1f}h served={k['PaxEquivPassages']:.0f} "
          f"vq={k['Net_VQVeh_All']:.0f} busTrips={k['N_BusTrips']:.0f} "
          f"actions={tot:.0f}")


def _print_summary():
    if not _SESSION:
        return
    byarm = defaultdict(list)
    for name, seed, k in _SESSION:
        if k.get("SimDuration_hrs", 0) >= 1.4:
            byarm[name].append(k)
    print("\n" + "=" * 76)
    print("[CHAMP] SESSION SUMMARY (mean over full runs; obj higher=better)")
    print(f"  {'arm':22s} {'obj':>7s} {'bus':>5s} {'car':>6s} "
          f"{'totAct':>6s} {'totDelay%':>9s} {'served%':>8s} {'vq':>7s} verdict")
    base_obj = None
    for name, ks in byarm.items():
        def m(kk):
            return sum(k[kk] for k in ks) / len(ks)
        tot = sum(m(kk) for kk in ("TSP_Extensions", "TSP_Insertions",
                                   "TSP_GreenRealloc", "TSP_EarlyRed",
                                   "TSP_OffsetCorr", "TSP_PhaseSkip",
                                   "TSP_PhaseRot"))
        row = (m("Objective_PaxPerDelayHr"), m("AvgBusPassDelay_s"),
               m("AvgCarPassDelay_s"), tot)
        if name == "NO_TSP":
            base_obj = row[0]
        print(f"  {name:22s} {row[0]:7.1f} {row[1]:5.1f} {row[2]:6.1f} "
              f"{row[3]:6.0f}")
    # ── Guarded verdict vs NO_TSP, same seed ──────────────────────────────
    print("-" * 76)
    _base_by_seed = {}
    for bn, bs, bk in _SESSION:
        if bn == "NO_TSP" and bk.get("SimDuration_hrs", 0) >= 1.4:
            _base_by_seed[bs] = bk
    for name, ks in byarm.items():
        if name == "NO_TSP":
            continue
        _td = _sv = None
        _ok = 0
        for k in ks:
            _seed = None
            for (sn, ss, sk) in _SESSION:
                if sk is k:
                    _seed = ss
                    break
            _bb = _base_by_seed.get(_seed)
            if _bb and _bb.get("TotalPassDelay_hrs"):
                _td = ((_td or 0.0) + (k["TotalPassDelay_hrs"]
                       - _bb["TotalPassDelay_hrs"])
                       / _bb["TotalPassDelay_hrs"] * 100.0)
                _ok += 1
            if _bb and _bb.get("PaxEquivPassages"):
                _sv = ((_sv or 0.0) + k["PaxEquivPassages"]
                       / _bb["PaxEquivPassages"] * 100.0)
        _td = (_td / _ok) if (_td is not None and _ok) else float("nan")
        _sv = (_sv / len(ks)) if (_sv is not None and ks) else float("nan")
        _vq = sum(k["Net_VQVeh_All"] for k in ks) / len(ks)
        _bt = sum(k["N_BusTrips"] for k in ks) / len(ks)
        tot = sum(sum(k.get(kk, 0.0) or 0.0 for kk in (
            "TSP_Extensions", "TSP_Insertions", "TSP_GreenRealloc",
            "TSP_EarlyRed", "TSP_OffsetCorr", "TSP_PhaseSkip",
            "TSP_PhaseRot")) for k in ks) / len(ks)
        _tags = []
        if _sv == _sv and _sv < 99.0:
            _tags.append("STARVED")
        if _bt == _bt and _bt < 50.0:
            _tags.append("SMALLN")
        if not _tags:
            _tags.append("WIN" if _td < 0.0 else "LOSE")
        print(f"  {name:22s} {'':7s} {'':5s} {'':6s} {tot:6.0f} "
              f"{_td:+8.1f}% {_sv:7.1f}% {_vq:7.0f} {' '.join(_tags)}")
    print("=" * 76)


def main():
    def _assert_logan_open():
        try:
            import GKModel as _gk
        except Exception:
            return
        try:
            _s = _gk.gk.getApplicationNet()
            assert _s is not None
        except Exception:
            raise SystemExit("Logan model must be open in Aimsun first")
    _assert_logan_open()
    _br_path = _os.path.join(_CORR, "batch_runner.py")
    _spec = _ilu.spec_from_file_location("logan_batch", _br_path)
    _br = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_br)
    print(f"[CHAMP] engine = {_os.path.join(_ROOT, 'shared_tsp_engine', 'engine.py')}")
    print(f"[CHAMP] expect ENGINE_BUILD={_EXPECTED} on the [LOAD] line")
    print(f"[CHAMP] arms={[e['name'] for e in EXPERIMENTS]} seeds={SEEDS} "
          f"({len(EXPERIMENTS) * len(SEEDS)} runs)")
    rep = _br.get_first_replication()
    run_num = 0
    for exp in EXPERIMENTS:
        for seed in SEEDS:
            run_num += 1
            name = exp["name"]
            cfg = dict(exp.get("reward_overrides") or {})
            print(f"\n[CHAMP] === run {run_num}: {name} seed={seed} === "
                  f"{_time.strftime('%H:%M:%S')}")
            _br.set_seed(rep, seed)
            _br.write_run_config(
                name, exp["strategy"], seed, 1.0,
                exp["coordinated"], exp["coordination_algo"], RUN_CONFIG_PATH,
                global_reward_mode=(exp["strategy"] != "NORMAL"),
                reward_cfg=cfg, bus_predictor="ADAPTIVE_KALMAN",
                results_csv_name=RESULTS_CSV_NAME,
                active_intersections=exp.get("active_intersections", None))
            _br._purge_pyc(CONTROLLER_PATH)
            t0 = _time.time()
            try:
                _br.run_replication(rep)
                print(f"[CHAMP] run {run_num} done in {_time.time()-t0:.0f}s")
                _print_run_kpis(name, seed)
            except Exception as e:
                print(f"[CHAMP] run {run_num} EXCEPTION: {e!r}")
    _print_summary()
    print(f"\n[CHAMP] COMPLETE. Results CSV: {RESULTS_CSV_NAME} "
          f"(under {_CORR}/results/).")


if __name__ == "__main__":
    main()
else:
    main()