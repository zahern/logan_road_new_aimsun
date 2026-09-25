"""
run_logan_nash_test.py -- root-level launcher to TEST the 2026-09-24 engine
changes on Logan Road, using the shared engine at the bundle root.

WHY IT LIVES AT THE ROOT (outside logan_road_new/)
--------------------------------------------------
The bundle has ONE engine: bcc113_bundle_v5/shared_tsp_engine/. Running from the
root guarantees that copy is the one on sys.path (a script inside a corridor dir
can shadow it). We import logan_road_new/batch_runner.py as a single module
instance under the alias "_br_champ" -- the SAME cache-bust champion_search.py
uses -- so completion detection / the engine-stamp guard behave (popping the
name 'batch_runner' would split it into two instances and hang; do not do that).

HOW TO RUN (inside Aimsun, Logan model open)
--------------------------------------------
  1. FULLY restart Aimsun (the engine is session-cached) and open the Logan Road
     model (logan_road_new/Logan_RD_for_QUT_with_detectors.ang).
  2. Run this file from the Aimsun Python console.
     It refuses to run if the open model is not Logan.
  3. Verify the [LOAD] line shows ENGINE_BUILD matching EXPECTED_ENGINE_BUILD
     below, then read the printed session summary (obj vs NO_TSP per arm).

WHAT IT EXERCISES -- ISOLATION LADDER
-------------------------------------
  The all-on run regressed to -49% on Aimsun. This ladder isolates the cause:
  NO_TSP, then NASH_BASE (minimal continuous-Nash, ~-5% reference), then one arm
  per new layer added ON TOP of NASH_BASE (timing rules, measured state, corridor
  coupling, empty-phase skip, actuated base, actuated base + offset-preserve
  retiming). Run once; the arm whose objective falls off a cliff vs NASH_BASE is
  the offending layer. Edit SEEDS / _LADDER below to taste.
"""
import os as _os, sys as _sys, time as _time, importlib.util as _ilu

# ── Editable test design ──────────────────────────────────────────────────────
SEEDS = [300]                      # 1-seed SANITY on the roll_ctr-fix build (does the
                                   # cross-cost fix change the Logan verdict?)
DEMAND_SCALAR = 1.0
RESULTS_CSV_NAME = "logan_nash_test.csv"
EXPECTED_ENGINE_BUILD = "2026-09-25T00:30-rollctr-fix"

# ── SELECTIVE-ACTING LADDER ──────────────────────────────────────────────────
# First ladder result: NASH_BASE = -3.3%, only MEASURED helped (-2.7%), corridor
# + empty-skip were inert, and EVERY arm fired ~200 extensions/run -> acting too
# much on saturated Logan (buses barely delayed 8s, cars saturated) costs car
# delay for tiny bus gain. This ladder tests ACTING LESS / only when it pays:
#   NOMON       -- continuous monitor OFF (pure bus-triggered; kills no-bus acting)
#   GATED       -- act only on a genuinely delayed bus (high min-delay/min-gain)
#   MEASURED    -- the one layer that helped (keep it)
#   SELECTIVE   -- combine the winners: monitor off + hard gates + measured
# Goal: find a config whose objective >= NO_TSP by serving only buses that need it.
_MEASURED = {"NASH_MEASURED_STATE": True, "MEASURED_STATE_FEED": True,
             "MEASURED_QUEUE_FEED": True, "MEASURED_SIDE_COST": True}
_GATES = {"NASH_MIN_BUS_DELAY_S": 15.0, "NASH_MIN_GAIN_S": 15.0}  # Logan warrants
_NASH_BASE = {
    "GLOBAL_REWARD_MODE":               True,
    "NASH_BARGAIN_MODE":                True,
    "CONTINUOUS_MONITOR_MODE":          True,
    "NASH_CONTINUOUS_MODE":             True,
    "NASH_BUS_WEIGHT":                  0.0,    # utilitarian: min total pax delay
    "NASH_CROSS_WEIGHT":                1.0,
    "CONTINUOUS_MONITOR_MIN_GAIN_PAXS": 50.0,
}
# (name, extra flags layered ON TOP of _NASH_BASE; later keys override base)
_LADDER = [
    # 1-seed sanity on the roll_ctr-fix build: the fix corrects cross-cost pricing,
    # so the ACTING arms (esp. MEASURED, which uses the measured cross cost) are the
    # ones that could move. Compare to the pre-fix 3-seed run (NASH_BASE -5.4%,
    # GATED -5.3%, MEASURED -7.8%). NOMON/SELECTIVE dropped for speed (known / ~0).
    ("NASH_BASE",  {}),                                         # main acting arm
    ("GATED",      dict(_GATES)),                               # act only on delayed bus
    ("MEASURED",   dict(_MEASURED)),                            # most fix-sensitive
]

EXPERIMENTS_TEST = [
    {"name": "NO_TSP", "strategy": "NORMAL", "coordinated": False,
     "coordination_algo": "KALMAN", "reward_overrides": {}},
]
for _nm, _extra in _LADDER:
    _rov = dict(_NASH_BASE)
    _rov.update(_extra)
    EXPERIMENTS_TEST.append({
        "name": _nm, "strategy": "GLOBAL_REWARD",
        "coordinated": True, "coordination_algo": "KALMAN",
        "reward_overrides": _rov,
    })

# Match champion_search's global feed so the test decides on the same measured
# state the real matrix uses (these are setdefaults -- an arm can still override).
GLOBAL_MEASURED_FEED      = True
GLOBAL_MEASURED_SIDE_COST = True
GLOBAL_CASCADE_COST       = True


# ── Resolve the bundle root (works when pasted into the Aimsun console too) ────
def _module_root(_marker="run_logan_nash_test.py"):
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
    _sys.path.insert(0, _ROOT)          # so shared_tsp_engine resolves from root
_CORR = "logan_road_new"
_CORR_DIR = _os.path.join(_ROOT, _CORR)


def _assert_logan_open():
    """Refuse to run unless the model open in Aimsun is Logan -- prevents running
    Logan's runner/config against the KG network (a stale KG lock could otherwise
    win). Mirrors champion_search's corridor guard."""
    try:
        from PyANGKernel import GKSystem
        _m = GKSystem.getSystem().getActiveModel()
    except Exception:
        print("[LOGAN_TEST] WARN: no Aimsun model handle; assuming Logan is open.")
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
    print(f"[LOGAN_TEST] corridor guard OK: Logan model is open ({_nm!r}).")


def _load_logan_runner():
    """Import logan_road_new/batch_runner.py as a single module instance under an
    alias (NOT 'batch_runner' -- that split would hang completion detection)."""
    _br_path = _os.path.join(_CORR_DIR, "batch_runner.py")
    if not _os.path.isfile(_br_path):
        raise RuntimeError(f"[LOGAN_TEST] not found: {_br_path}")
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
_SESSION = []   # (name, seed, {kpi: val})


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
        print(f"[LOGAN_TEST]   (no KPIs found for {name} seed {seed} yet)")
        return
    _SESSION.append((name, seed, k))
    print(f"[LOGAN_TEST]   {name} seed {seed}: obj={k['Objective_PaxPerDelayHr']:.1f} "
          f"bus={k['AvgBusPassDelay_s']:.1f}s car={k['AvgCarPassDelay_s']:.1f}s "
          f"queue={k['Net_MeanQueue_All']:.0f} ext={k['TSP_Extensions']:.0f} "
          f"ins={k['TSP_Insertions']:.0f} dur={k['SimDuration_hrs']:.2f}h")


def _print_summary():
    if not _SESSION:
        return
    # mean per arm over this session's seeds
    from collections import defaultdict
    byarm = defaultdict(list)
    for name, seed, k in _SESSION:
        if k.get("SimDuration_hrs", 0) >= 1.4:   # full runs only
            byarm[name].append(k)
    print("\n" + "=" * 64)
    print("[LOGAN_TEST] SESSION SUMMARY (mean over full runs; obj higher=better)")
    print(f"  {'arm':16s} {'obj':>7s} {'bus_s':>6s} {'car_s':>6s} {'queue':>6s} {'ext':>5s}")
    base = None
    for name, ks in byarm.items():
        def m(kk): return sum(k[kk] for k in ks) / len(ks)
        row = (m("Objective_PaxPerDelayHr"), m("AvgBusPassDelay_s"),
               m("AvgCarPassDelay_s"), m("Net_MeanQueue_All"), m("TSP_Extensions"))
        print(f"  {name:16s} {row[0]:7.1f} {row[1]:6.1f} {row[2]:6.1f} "
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
    print(f"[LOGAN_TEST] runner   = {_os.path.join(_CORR_DIR, 'batch_runner.py')}")
    print(f"[LOGAN_TEST] engine   = {_os.path.join(_ROOT, 'shared_tsp_engine', 'engine.py')}")
    print(f"[LOGAN_TEST] expect ENGINE_BUILD={EXPECTED_ENGINE_BUILD} on the [LOAD] line")
    print(f"[LOGAN_TEST] arms={[e['name'] for e in EXPERIMENTS_TEST]} seeds={SEEDS}")

    # ONE Aimsun replication object, reused for every run (seed/config are rewritten
    # each time) -- this is the object set_seed/run_replication operate on, NOT a
    # loop counter (passing an int gives "'int' object has no attribute get").
    rep_obj = _br.get_first_replication()

    # Apply the demand scalar once against the base demand (guarded: Logan's
    # set_demand_scalar takes (scalar, base_demands); skip cleanly at 1.0).
    base_demands = {}
    if abs(float(DEMAND_SCALAR) - 1.0) > 1e-9:
        try:
            _br.set_demand_scalar(DEMAND_SCALAR, base_demands)
        except Exception as e:
            print(f"[LOGAN_TEST] WARN demand scalar {DEMAND_SCALAR}: {e!r}")

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
            print(f"\n[LOGAN_TEST] === run {run_num}: {name} seed={seed} "
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
                print(f"[LOGAN_TEST] run {run_num} done in {_time.time()-t0:.0f}s")
                _print_run_kpis(name, seed)
            except Exception as e:
                print(f"[LOGAN_TEST] run {run_num} EXCEPTION: {e!r}")

    _print_summary()

    print(f"\n[LOGAN_TEST] COMPLETE. Results CSV: {RESULTS_CSV_NAME} "
          f"(under {_CORR}/results/). Now grep the run log for "
          f"'[NASH_BARGAIN] [monitor]', '[MONITOR]', '[RECOVER_GATE]', "
          f"'[PROG_GATE]', and '] error' (want 0).")


if __name__ == "__main__":
    main()
else:
    # Also run when pasted/exec'd in the Aimsun console (no __main__).
    main()
