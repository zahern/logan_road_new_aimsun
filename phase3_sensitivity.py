"""
phase3_sensitivity.py -- BCC113 Phase 3: full sensitivity factorial (docx tab 3).

Per corridor:  BASE CHAMPION (from Phase 1)
             x 3 TACTICS   (SWAPS / TIMES / BOTH)
             x 3 FREQ      (X1 baseline / X2 frequent / X3 rare)
             x 6 DEMAND    (x0.6 .. x1.6)
             x 5 SEEDS     (300-700)
             = 270 runs.

HOW TO RUN (inside Aimsun, corridor model open):
    python phase3_sensitivity.py                 -> full 270-run factorial
    python phase3_sensitivity.py --quick         -> 1 combo x 2 seeds smoke test

Results -> phase3_sensitivity_<corridor>.csv  (tagged sens_tactic / sens_freq /
demand_scalar columns; rank with pandas pivot on those).

Levers map onto existing engine switches:
    TACTICS  ZIG_ENABLE_GE / ZIG_ENABLE_INS / ZIG_ENABLE_GR / ZIG_ENABLE_SEQ
             TIMES = timing actions only (GE+INS+GR)
             SWAPS = sequence actions only (PT/VP/ER)
             BOTH  = everything (the champion's native setting)
    FREQ     TSP_COOLDOWN_OVERRIDE_S — the minimum gap between interventions:
             X1 baseline (engine default 60 s), X2 = 40 s (most frequent the
             executor's own cycle-gate allows), X3 = 120 s (rare interventions).
"""

import os as _os, sys as _sys, time as _time, glob as _glob, importlib.util as _ilu

# ── 1. Corridor auto-detection (same convention as champion_search) ───────────
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
def _detect_corridor():
    cands = []
    for c in ("kg", "logan_road_new"):
        d = _os.path.join(_ROOT, c)
        locks = _glob.glob(_os.path.join(d, "*.ang.lck")) + \
                _glob.glob(_os.path.join(d, "*.sang.lck"))
        if locks:
            cands.append((c, d, max(_os.path.getmtime(p) for p in locks)))
    if cands:
        cands.sort(key=lambda t: -t[2]); return cands[0][0], cands[0][1]
    raise RuntimeError("Open the corridor model in Aimsun first "
                       "(no *.ang.lck found under kg/ or logan_road_new/).")

CORRIDOR, CORR_DIR = _detect_corridor()

# ── 2. Batch-runner infrastructure ────────────────────────────────────────────
_br_path = _os.path.join(CORR_DIR, "batch_runner.py")
_spec = _ilu.spec_from_file_location("_br_p3", _br_path)
_br = _ilu.module_from_spec(_spec); _sys.modules["_br_p3"] = _br
try:
    _spec.loader.exec_module(_br)
except SystemExit:
    pass

# ── 3. Factorial design ────────────────────────────────────────────────────────
# BASE = the Phase-1 champion. KG measured winner: DCTSP_MARL (+7.4% obj,
# bus -13.6%, car -3.5%, all 5 seeds — see coordinator-is-real-tsp-culprit.md).
# For Logan, swap this dict for Logan's Phase-1 champion when known.
if CORRIDOR == "kg":
    BASE = {
        "name": "DCTSP_MARL", "strategy": "GLOBAL_REWARD",
        "coordinated": True, "coordination_algo": "KALMAN",
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0,
            "REWARD_BETA": 1.0, "REWARD_GAMMA": 1.0,
            "DCTSP_GREEN_REALLOC_MODE": True,
            "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "DCTSP_W_H": 0.50, "DCTSP_CAR_WEIGHT": 1.00,
            "DECIDER_COST_VETO_RATIO": 3.0},
    }
else:  # logan_road_new — placeholder until Logan Phase 1 lands; edit here.
    BASE = {
        "name": "DCTSP_MARL", "strategy": "GLOBAL_REWARD",
        "coordinated": True, "coordination_algo": "KALMAN",
        "reward_overrides": {"GLOBAL_REWARD_MODE": True,
                             "DECIDER_COST_VETO_RATIO": 3.0},
    }

TACTICS = {
    # action-family switches consumed by the shared candidate pool (MODE_FLAGS)
    "TIMES": {"ZIG_ENABLE_GE": True,  "ZIG_ENABLE_INS": True,
              "ZIG_ENABLE_GR": True,  "ZIG_ENABLE_SEQ": False},
    "SWAPS": {"ZIG_ENABLE_GE": False, "ZIG_ENABLE_INS": False,
              "ZIG_ENABLE_GR": False, "ZIG_ENABLE_SEQ": True},
    "BOTH":  {"ZIG_ENABLE_GE": True,  "ZIG_ENABLE_INS": True,
              "ZIG_ENABLE_GR": True,  "ZIG_ENABLE_SEQ": True},
}

FREQS = {
    # TSP_COOLDOWN_OVERRIDE_S — minimum seconds between interventions.
    # NOTE: the executor also enforces max(30, 0.3*cycle) ~= 40 s on KG, so
    # X2=40 is the practical 'most frequent' setting.
    "X1_BASELINE": None,
    "X2_FREQUENT":  40,
    "X3_RARE":     120,
}

DEMAND_SCALARS = [0.6, 0.8, 1.0, 1.2, 1.4, 1.6]
SEEDS          = [300, 400, 500, 600, 700]

RESULTS_CSV = _os.path.join(_ROOT, f"phase3_sensitivity_{CORRIDOR}.csv")


def _set_controller_const(controller_path, var, value):
    """Regex-patch a top-level module constant (TSP_COOLDOWN_OVERRIDE_S etc.).

    The written value is ALWAYS a proper Python literal. Passing "False" or
    "0.0" as strings used to produce repr()d quoted text in the controller
    ('False' / '0.0'), which are truthy strings at runtime -- one of them
    crashed AAPIPostManage on a str>int compare (2026-08-24, KG)."""
    import re
    with open(controller_path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    pat = re.compile(r"(?m)^(%s)(\s*:\s*[a-zA-Z_.\[\]]+)?\s*=.*$" % re.escape(var))
    if value is None:
        val = "None"
    elif isinstance(value, (bool, int, float)):
        val = repr(value)
    else:
        # String input: accept bool-like / numeric-looking spellings and write
        # real literals; anything else keeps repr (a genuine string constant).
        s = str(value).strip()
        if s.lower() in ("true", "false"):
            val = s.capitalize()
        else:
            try:
                val = repr(float(s)) if ("." in s or "e" in s.lower()) else repr(int(s))
            except ValueError:
                val = repr(value)
    if pat.search(txt):
        txt = pat.sub(lambda m: "%s%s = %s" % (m.group(1), m.group(2) or "", val),
                      txt, count=1)
    else:
        txt = txt.replace("\nCONTROL_MODE",
                          "\n%s = %s\nCONTROL_MODE" % (var, val), 1)
    with open(controller_path, "w", encoding="utf-8", newline="") as f:
        f.write(txt)


def _obj_ok(m):
    try:
        v = m.get("stats_Objective_PaxPerDelayHr", "")
        return v not in ("", None) and float(v) != 0.0
    except Exception:
        return False


# ── [SANITY] live health gate (same thresholds as champion_search) ────────────
# A 270-run factorial is ~10 h; these catch the known silent-failure modes
# (collapsed car counting / broken passenger denominator / dead PT scan /
# byte-identical no-op runs) AT RUN TIME instead of poisoning the matrix.
def _fnum(m, key):
    try:
        v = float(m.get(key))
        return v if v == v else None          # NaN -> None
    except Exception:
        return None


def _sanity_problems(m):
    p = []
    nc, nb = _fnum(m, 'stats_N_DistinctCars'), _fnum(m, 'stats_N_DistinctBuses')
    ac, ab = _fnum(m, 'stats_AvgCarPassDelay_s'), _fnum(m, 'stats_AvgBusPassDelay_s')
    dur = _fnum(m, 'stats_SimDuration_hrs')
    if nc is None or nc < 500:
        p.append(f"N_DistinctCars={nc} (<500 -- car counting collapsed)")
    if ac is None or not (0 < ac < 600):
        p.append(f"AvgCarPassDelay_s={ac} outside (0,600)")
    if nb is not None and nb < 5:
        p.append(f"N_DistinctBuses={nb} (<5)")
    if ab is not None and not (0 < ab < 600):
        p.append(f"AvgBusPassDelay_s={ab} outside (0,600)")
    if dur is not None and dur <= 0:
        p.append("SimDuration_hrs<=0")
    return p


_SIG_KEYS = ('stats_Objective_PaxPerDelayHr', 'stats_N_DistinctCars',
             'stats_N_DistinctBuses', 'stats_AvgCarPassDelay_s')


def _run_signature(m):
    try:
        s = tuple(round(_fnum(m, k) or 0.0, 3) for k in _SIG_KEYS)
        return s if any(s) else None
    except Exception:
        return None


def _run_and_collect(rep, name, strategy, seed, scalar, coordinated, coord_algo,
                     global_reward, reward_cfg, CONTROLLER_PATH, RUN_CONFIG_PATH,
                     PROJECT_DIR, log):
    while True:
        _br.set_seed(rep, seed)
        _br.write_run_config(name, strategy, seed, scalar, coordinated,
                             coord_algo, RUN_CONFIG_PATH,
                             global_reward_mode=global_reward,
                             reward_cfg=reward_cfg or None,
                             bus_predictor="ADAPTIVE_KALMAN",
                             results_csv_name=_os.path.basename(RESULTS_CSV))
        _br._purge_pyc(CONTROLLER_PATH)
        t0 = _time.time(); ok = True
        try:
            _br.run_replication(rep)
        except Exception as e:
            ok = False; log(f"  EXCEPTION: {e}")
        dt = _time.time() - t0
        for w in (0, 4, 8, 12):
            if w:
                _time.sleep(w)
            try:
                m = _br.collect_run_metrics(PROJECT_DIR, strategy, seed, scalar,
                                            name, coordinated, dt, ok,
                                            bus_predictor="ADAPTIVE_KALMAN")
            except Exception as e:
                log(f"  metrics FAIL: {e}"); m = None
            if m is not None and _obj_ok(m):
                return m
            if w:
                log(f"  blank stats — re-collecting after {w}s")


def main(quick=False):
    log = _br.log
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    PROJECT_DIR = _br.PROJECT_DIR

    tactics = ["BOTH"] if quick else list(TACTICS.keys())
    freqs   = ["X1_BASELINE"] if quick else list(FREQS.keys())
    demands = [1.0]           if quick else DEMAND_SCALARS
    seeds   = [300, 400]      if quick else SEEDS

    n_total = len(tactics) * len(freqs) * len(demands) * len(seeds)
    log("=" * 70)
    log(f"PHASE 3 SENSITIVITY FACTORIAL -- corridor={CORRIDOR} | base={BASE['name']}")
    log(f"  {len(tactics)} tactics x {len(freqs)} freq x {len(demands)} demand "
        f"x {len(seeds)} seeds = {n_total} runs")
    log(f"  -> {RESULTS_CSV}")
    log("=" * 70)

    try:
        if _os.path.exists(RESULTS_CSV):
            _os.remove(RESULTS_CSV)
    except Exception:
        pass
    try:
        _br._set_logging(CONTROLLER_PATH, enabled=False)
    except Exception:
        pass
    for flag, val in (("MARK_DETECTION_POINTS", False),
                      ("OVERLAY_DETECTIONS_ON_MAP", False),
                      ("TRACK_BUS_POSITIONS", False),
                      ("STATUS_DASHBOARD_INTERVAL_S", 0.0)):
        try:
            _set_controller_const(CONTROLLER_PATH, flag, val)
        except Exception:
            pass

    rep = _br.get_first_replication()
    base_demands = {}
    run_num = 0
    _flagged = 0
    _last_sig = None
    try:
        for tactic in tactics:
            for freq in freqs:
                for scalar in demands:
                    # ── patch controller ONCE per (tactic, freq) cell ──
                    rov = dict(BASE["reward_overrides"])
                    rov.update(TACTICS[tactic])
                    rov["Z4_CONSTRAINT_MODE"] = True
                    rov.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
                    name = f"{BASE['name']}_{tactic}_{freq}"
                    strategy = BASE["strategy"]
                    try:
                        _br.set_control_mode(strategy, CONTROLLER_PATH)
                        _br.set_coordinated(CONTROLLER_PATH, BASE["coordinated"])
                        _br.set_coordination_algo(CONTROLLER_PATH,
                                                  BASE["coordination_algo"])
                        numeric = {k: v for k, v in rov.items()}
                        _br.set_reward_weights(CONTROLLER_PATH, numeric)
                        _set_controller_const(CONTROLLER_PATH,
                                              "TSP_COOLDOWN_OVERRIDE_S",
                                              FREQS[freq])
                    except Exception as e:
                        log(f"FATAL patch {name}: {e}"); continue

                    for seed in seeds:
                        run_num += 1
                        log(f"[{run_num}/{n_total}] {CORRIDOR} | {name} | "
                            f"d={scalar} | seed={seed}")
                        _br.set_demand_scalar(scalar, base_demands)
                        m = _run_and_collect(
                            rep, name, strategy, seed, scalar,
                            BASE["coordinated"], BASE["coordination_algo"],
                            bool(rov.get("GLOBAL_REWARD_MODE")), rov,
                            CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, log)
                        if m is not None:
                            m["sens_base"] = BASE["name"]
                            m["sens_tactic"] = tactic
                            m["sens_freq"] = freq
                            m["sens_cooldown_s"] = FREQS[freq]
                            m["demand_scalar"] = scalar
                            _br.append_master_csv(RESULTS_CSV, m)
                            _problems = _sanity_problems(m)
                            for _p in _problems:
                                log(f"  [SANITY] WARNING: {_p}")
                            _sig = _run_signature(m)
                            if _sig is not None and _sig == _last_sig:
                                log("  [SANITY] WARNING: headline KPIs identical to "
                                    "previous run -- no-op patch or stale module?")
                            if _problems or (_sig is not None and _sig == _last_sig):
                                _flagged += 1
                            _last_sig = _sig
    finally:
        # restore baseline plan state: neutral cooldown + original demand
        try:
            _set_controller_const(CONTROLLER_PATH, "TSP_COOLDOWN_OVERRIDE_S", None)
        except Exception:
            pass
        try:
            _br.set_demand_scalar(1.0, base_demands)
        except Exception:
            pass
        try:
            _br._set_logging(CONTROLLER_PATH, enabled=True)
        except Exception:
            pass

    log("=" * 70)
    log(f"DONE ({CORRIDOR}) -> {RESULTS_CSV}")
    if _flagged:
        log(f"SANITY SUMMARY: {_flagged}/{run_num} run(s) FLAGGED -- review the "
            f"[SANITY] WARNING lines above before ranking")
    else:
        log(f"SANITY SUMMARY: all {run_num} runs healthy")
    log("=" * 70)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="smoke test: BOTH/X1/x1.0 x seeds 300,400 only")
    a = ap.parse_args()
    main(quick=a.quick)
