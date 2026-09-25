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
def _module_root(_marker="champion_search.py"):
    # __file__ is undefined when loaded in the Aimsun console (import/paste);
    # fall back to the open model's document directory, then CWD. (2026-09-22)
    try:
        return _os.path.dirname(_os.path.abspath(__file__))
    except (NameError, TypeError):
        pass
    try:
        from PyANGKernel import GKSystem
        _d = _os.path.abspath(str(GKSystem.getSystem().getActiveModel(
            ).getDocumentDirectory().absolutePath()))
        for _i in range(4):
            if _os.path.isfile(_os.path.join(_d, _marker)):
                return _d
            _d = _os.path.dirname(_d)
    except Exception:
        pass
    return _os.path.abspath(_os.getcwd())

_ROOT = _module_root()
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
# BASE = the Phase-1 champion (DCTSP_MARL). Standalone runs auto-pull the
# canonical arm from champion_search.ARMS below (Logan-aware branches
# included); the pipeline injects its picked champion instead.
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
else:  # logan_road_new — DCTSP_MARL champion mirror (static fallback).
    BASE = {
        "name": "DCTSP_MARL", "strategy": "GLOBAL_REWARD",
        "coordinated": True, "coordination_algo": "KALMAN",
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0,
            "REWARD_BETA": 1.0, "REWARD_GAMMA": 1.0,
            "DCTSP_GREEN_REALLOC_MODE": True,
            "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "DCTSP_W_H": 0.50, "DCTSP_CAR_WEIGHT": 1.00,
            "DECIDER_COST_VETO_RATIO": 3.5,
            "DCTSP_CONGESTION_GATE": True,
            "DCTSP_CONGESTION_GATE_FRACTION": 0.70,
            "BXT_MODE": False, "DCTSP_ZIG_MODE": False,
            "MP_ECTM_MODE": False, "BARGAIN_SPM_MODE": False,
            "CENTRALIZED_MODE": False},
    }

# Standalone runs (no pipeline override): pick the corridor's CHAMPION from its
# ranked champion_<corridor>.csv (best TSP arm by mean
# stats_Objective_PaxPerDelayHr, higher=better; NO_TSP excluded since BASE needs
# a strategy that HAS tactics), then pull that arm's full config from
# champion_search.ARMS. Falls back to the DCTSP_MARL arm (then the static BASE
# above) if the CSV is missing/incomplete or the arm is not in ARMS. So once
# Logan's champion search COMPLETES, Phase 3 automatically sweeps Logan's real
# champion instead of DCTSP_MARL -- KG keeps DCTSP_MARL because that IS its
# champion. The pipeline still sets phase3.BASE itself after loading, so this
# only affects direct `phase3_sensitivity.py` execution. (2026-09-07)
_OBJ_COL = "stats_Objective_PaxPerDelayHr"


def _champion_arm_name_from_csv(_corr):
    """Best TSP arm (excl. NO_TSP) by mean objective in champion_<corr>.csv."""
    import csv as _csv
    from collections import defaultdict as _dd
    _p = _os.path.join(_ROOT, f"champion_{_corr}.csv")
    if not _os.path.isfile(_p):
        return None
    _by = _dd(list)
    try:
        for _r in _csv.DictReader(open(_p, encoding="utf-8")):
            _name = (_r.get("run_experiment") or "").strip()
            if not _name or _name == "NO_TSP":
                continue
            if str(_r.get("run_success", "true")).lower() == "false":
                continue
            try:
                _by[_name].append(float(_r.get(_OBJ_COL, "")))
            except (TypeError, ValueError):
                continue
    except Exception:
        return None
    _by = {k: v for k, v in _by.items() if v}
    if not _by:
        return None
    return max(_by.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))[0]


try:
    _cs_path = _os.path.join(_ROOT, "champion_search.py")
    _cs_spec = _ilu.spec_from_file_location("_cs_p3base", _cs_path)
    _cs_mod = _ilu.module_from_spec(_cs_spec)
    _sys.modules["_cs_p3base"] = _cs_mod
    _cs_spec.loader.exec_module(_cs_mod)
    _champ_name = _champion_arm_name_from_csv(CORRIDOR)
    _champ_arm = None
    if _champ_name is not None:
        _champ_arm = next((a for a in _cs_mod.ARMS
                           if a.get("name") == _champ_name), None)
    if _champ_arm is None:              # no CSV champion, or arm not in ARMS
        _champ_arm = next(a for a in _cs_mod.ARMS if a.get("name") == "DCTSP_MARL")
        _src = "DCTSP_MARL fallback (no complete champion CSV)"
    else:
        _src = f"corridor champion from champion_{CORRIDOR}.csv"
    BASE = {"name": _champ_arm["name"], "strategy": _champ_arm["strategy"],
            "coordinated": _champ_arm.get("coordinated", False),
            "coordination_algo": _champ_arm.get("coordination_algo", "KALMAN"),
            "reward_overrides": dict(_champ_arm.get("reward_overrides", {}) or {})}
    print(f"[PHASE3] BASE = '{BASE['name']}' ({_src})")
except Exception as _base_e:
    print(f"[PHASE3] WARNING: keeping static BASE ({_base_e})")

# ── Load-from-file BASE override (HIGHEST precedence) ─────────────────────────
# Drop a phase3_base_<corridor>.json in the bundle root (or point env
# PHASE3_BASE_FILE at any JSON) to run Phase 3 on an EXPLICIT base instead of the
# auto-pulled champion -- e.g. phase3_base_kg.json = the CELLQLEARN champion with
# the net-benefit gate OFF, so the learner acts on many more buses and the tactic
# axis (TIMES/SWAPS/BOTH) yields visibly different action mixes. The JSON schema
# is {name, strategy, coordinated, coordination_algo, reward_overrides}. Requires
# a fresh Aimsun engine (the BXT family gate BXT_ENABLE_* lands in >=2026-09-15).
_base_file = (_os.environ.get("PHASE3_BASE_FILE")
              or _os.path.join(_ROOT, f"phase3_base_{CORRIDOR}.json"))
if _os.path.isfile(_base_file):
    try:
        import json as _json
        with open(_base_file, encoding="utf-8") as _bf:
            _bj = _json.load(_bf)
        BASE = {"name": _bj["name"],
                "strategy": _bj.get("strategy", "GLOBAL_REWARD"),
                "coordinated": bool(_bj.get("coordinated", True)),
                "coordination_algo": _bj.get("coordination_algo", "SHOCKWAVE"),
                "reward_overrides": dict(_bj.get("reward_overrides", {}) or {})}
        print(f"[PHASE3] BASE loaded from file {_os.path.basename(_base_file)} "
              f"-> '{BASE['name']}' (net_benefit_gate="
              f"{BASE['reward_overrides'].get('BXT_NET_BENEFIT_GATE', '?')})")
    except Exception as _bfe:
        print(f"[PHASE3] WARNING: could not load base file {_base_file} ({_bfe})")

TACTICS = {
    # Action-family switches. TWO flag families so the tactic axis bites BOTH
    # controller types: ZIG_ENABLE_* for a ZIG champion, and BXT_ENABLE_* for a
    # BXT/CELLQLEARN champion (the latter added 2026-09-16 -- before it, the BXT
    # decider ignored ZIG_ENABLE_* so SWAPS/TIMES/BOTH were byte-identical -> 218
    # duplicate SANITY flags). Mapping: TIMES = timing (GE + green-realloc),
    # SWAPS = order (INS + early-red), BOTH = everything.
    "TIMES": {"ZIG_ENABLE_GE": True,  "ZIG_ENABLE_INS": True,
              "ZIG_ENABLE_GR": True,  "ZIG_ENABLE_SEQ": False,
              "BXT_ENABLE_GE": True,  "BXT_ENABLE_GR": True,
              "BXT_ENABLE_INS": False, "BXT_ENABLE_ER": False},
    "SWAPS": {"ZIG_ENABLE_GE": False, "ZIG_ENABLE_INS": False,
              "ZIG_ENABLE_GR": False, "ZIG_ENABLE_SEQ": True,
              "BXT_ENABLE_GE": False, "BXT_ENABLE_GR": False,
              "BXT_ENABLE_INS": True,  "BXT_ENABLE_ER": True},
    "BOTH":  {"ZIG_ENABLE_GE": True,  "ZIG_ENABLE_INS": True,
              "ZIG_ENABLE_GR": True,  "ZIG_ENABLE_SEQ": True,
              "BXT_ENABLE_GE": True,  "BXT_ENABLE_GR": True,
              "BXT_ENABLE_INS": True,  "BXT_ENABLE_ER": True},
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

# Add a NO_TSP (no-priority) baseline across the SAME demand x seed grid so the
# sensitivity can quantify the priority benefit (champion vs no-priority) at each
# demand level. Adds len(DEMAND_SCALARS) x len(SEEDS) = 30 runs (~7 h). NO_TSP
# has no tactics/freqs, so it runs once per (demand, seed) -- not per tactic/freq
# cell. (2026-09-07, user-approved)
ADD_NO_TSP_BASELINE = True
NO_TSP_ARM = {"name": "NO_TSP", "strategy": "NORMAL",
              "coordinated": False, "coordination_algo": "KALMAN",
              "reward_overrides": {}}

# Phase-3 sweeps CAR demand only.  The bus-frequency scalar is a controller-file
# literal written by champion_bus_demand.py; if it is left behind from that
# sweep (x0.5 measured on Logan 2026-09-02), every phase-3 run without an
# explicit override inherits it -- the engine's AAPIInit only re-reads run_config
# keys that are PRESENT, so an absent key keeps the stale controller value
# (Logan X1_BASELINE runs ran with x0.5 suppression active: removed=7627).
# Force the bus scalar to x1.0 (off / calibrate) for every phase-3 run so the
# demand axis is unambiguously CAR-only.
BUS_FREQ_INJECT_SCALAR_PHASE3 = 0.0

# Demand mechanism (2026-09-05 audit): the ONLY live path is console-side
# GKODMatrix.multiply() via _br.scale_od_matrices_multiply() -- schedule
# factors never verify (read-back stuck at 100) and the engine OD path scales
# 0 pairs in every run. Do NOT add a set_demand_scalar() call here: that would
# double-scale (scalar^2). The single persistent od_state dict below is the
# anti-compounding mechanism (ratio-based); never reset it mid-sweep.

RESULTS_CSV = _os.path.join(_ROOT, f"phase3_sensitivity_{CORRIDOR}.csv")

# ── Console-launch defaults (Aimsun has no CLI argv) ─────────────────────
# When exec'ing this file from the Aimsun Python console, argparse sees no
# flags, so set these instead of editing the call below:
#   RESUME_DEFAULT = True   -> skip completed successful rows on relaunch
#   CELLS_DEFAULT = ["BOTH/X1_BASELINE"] -> only those tactic/freq cells
#   QUICK_DEFAULT = True    -> 2-run smoke test
# Alternatively (no file edit): import phase3_sensitivity as p3, then
#   p3.main(resume=True)  /  p3.main(resume=True, cells=["BOTH/X1_BASELINE"])
# (needs the bundle root on sys.path: sys.path.insert(0, r"C:\...\bcc113_bundle_v5"))
RESUME_DEFAULT = False
CELLS_DEFAULT = None
QUICK_DEFAULT = False


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
    # CARRY-OVER sentinel (see champion_search): trips-per-distinct-bus ratio is
    # ~5-10 for a real run; a stats-not-reset run does 100s (N_BusTrips explodes,
    # N_DistinctBuses saturates). Prefixed "CARRY-OVER" so the gate can abort.
    nt = _fnum(m, 'stats_N_BusTrips')
    if nt is not None and nb is not None and nb > 0 and nt / nb > 30.0:
        p.append(
            f"CARRY-OVER: N_BusTrips/N_DistinctBuses={nt / nb:.0f} (>30; real ~5-10) "
            f"-- stats did NOT reset between runs (N_BusTrips={nt:.0f}, "
            f"N_DistinctBuses={nb:.0f}). FULLY restart Aimsun (confirm ENGINE_BUILD "
            f"on the [LOAD] line) before trusting any row.")
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
                     PROJECT_DIR, log, collect=True):
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
        if not collect:
            # Train prologue: Q accumulates in-session; nothing is scored.
            return None
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


def main(quick=False, resume=False, cells=None, only_missing=False):
    log = _br.log
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    PROJECT_DIR = _br.PROJECT_DIR

    tactics = ["BOTH"] if quick else list(TACTICS.keys())
    freqs   = ["X1_BASELINE"] if quick else list(FREQS.keys())
    demands = [1.0]           if quick else DEMAND_SCALARS
    seeds   = [300, 400]      if quick else SEEDS
    if cells:
        _want = set(cells)
        tactics = [t for t in tactics
                   if any(f"{t}/{f}" in _want for f in freqs)]
        freqs = [f for f in freqs
                 if any(f"{t}/{f}" in _want for t in tactics)]

    _add_no_tsp = ADD_NO_TSP_BASELINE and not quick
    # Resume: read completed successful (tactic, freq, demand, seed) combos
    # and skip them (the sweep DELETES the CSV on a fresh start, so without
    # this an interrupted 300-run factorial restarts from zero).
    _done_keys = set()
    if resume and _os.path.isfile(RESULTS_CSV):
        try:
            import csv as _csv
            with open(RESULTS_CSV, newline='', encoding='utf-8-sig') as _fh:
                for _r in _csv.DictReader(_fh):
                    if str(_r.get("run_success", "")).strip().lower() in (
                            "true", "1", "yes", ""):
                        # NB: blank (legacy rows pre-run_success) counts as done
                        # only with a present nonzero objective AND a full
                        # design horizon (1.0 h) -- truncated runs like the
                        # 1.113 h Logan case must re-run, not be skipped.
                        try:
                            _o = float(_r.get("stats_Objective_PaxPerDelayHr", ""))
                        except Exception:
                            continue
                        if _o == 0.0:
                            continue
                        try:
                            _d = float(_r.get("stats_SimDuration_hrs", ""))
                            if _d < 0.98:
                                continue
                        except Exception:
                            pass
                        _done_keys.add((
                            str(_r.get("sens_base", "")),
                            str(_r.get("sens_tactic", "")),
                            str(_r.get("sens_freq", "")),
                            str(_r.get("demand_scalar", "")),
                            str(_r.get("run_seed", "")).split(".")[0]))
            log(f"RESUME: {len(_done_keys)} successful rows already in "
                f"{RESULTS_CSV} -- skipping those")
        except Exception as _e:
            log(f"RESUME: could not read {RESULTS_CSV} ({_e}); starting fresh")
            _done_keys = set()
    else:
        try:
            if _os.path.exists(RESULTS_CSV):
                _os.remove(RESULTS_CSV)
        except Exception:
            pass
    _n_no_tsp = (len(demands) * len(seeds)) if _add_no_tsp else 0
    n_total = len(tactics) * len(freqs) * len(demands) * len(seeds) + _n_no_tsp
    if _done_keys:
        # Progress counts REMAINING runs (skipped done rows excluded).
        n_total = 0
        for _t in tactics:
            for _f in freqs:
                for _s in demands:
                    for _sd in seeds:
                        if (BASE["name"], _t, _f, str(_s), str(_sd)) not in _done_keys:
                            n_total += 1
        if _add_no_tsp:
            for _s in demands:
                for _sd in seeds:
                    if ("NO_TSP", "NONE", "NONE", str(_s), str(_sd)) not in _done_keys:
                        n_total += 1
    log("=" * 70)
    log(f"PHASE 3 SENSITIVITY FACTORIAL -- corridor={CORRIDOR} | base={BASE['name']}")
    log(f"  {len(tactics)} tactics x {len(freqs)} freq x {len(demands)} demand "
        f"x {len(seeds)} seeds"
        f"{f' + {_n_no_tsp} NO_TSP baseline' if _add_no_tsp else ''} "
        f"= {n_total} runs")
    log(f"  -> {RESULTS_CSV}")
    log("=" * 70)

    # Resume must NOT delete the CSV (done rows are skipped via _done_keys and
    # new rows append). Only a fresh start clears it. (Fixed 2026-09-23: this
    # block previously deleted unconditionally, wiping resumed progress.)
    if not _done_keys:
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

    od_state = {}  # persistent multiply state for the whole sweep (see note above)
    # ── LEARNER BASE train prologue (same-session train-then-freeze) ──
    # A BXT/CELLQLEARN BASE keeps its Q-table in controller memory only (no
    # file persistence), so a fresh Aimsun session starts EMPTY and a frozen
    # learner would argmax NO_ACTION for every bus (a NO_TSP clone). Mirror
    # champion_search's fair training: run TRAIN_SEEDS at x1.0 with
    # exploration ON first (Q accumulates in-session, nothing is scored),
    # then freeze for the demand cells below. Non-learner BASE skips this.
    try:
        _LEARN_ARMS = set(getattr(_cs_mod, "LEARNING_ARMS", set()) or set())
        _TRAIN_SEEDS = list(getattr(_cs_mod, "TRAIN_SEEDS", [800, 900, 1000, 1100]))
        _TRAIN_EPS = float(getattr(_cs_mod, "BXT_TRAIN_EPSILON", 0.30))
    except Exception:
        _LEARN_ARMS, _TRAIN_SEEDS, _TRAIN_EPS = set(), [], 0.30
    if BASE["name"] in _LEARN_ARMS and _TRAIN_SEEDS:
        _trov = dict(BASE["reward_overrides"])
        _trov["Z4_CONSTRAINT_MODE"] = True
        _trov.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
        _trov.setdefault("MEASURED_STATE_FEED", True)
        _trov.setdefault("MEASURED_QUEUE_FEED", True)
        _trov.setdefault("MEASURED_SIDE_COST", True)
        _trov.setdefault("MEASURED_SIDE_COST_DIAG", True)
        _trov["BUS_FREQ_INJECT_SCALAR"] = float(BUS_FREQ_INJECT_SCALAR_PHASE3)
        log(f"TRAIN PROLOGUE: learner BASE '{BASE['name']}' trains on "
            f"{_TRAIN_SEEDS} at x1.0 (eps={_TRAIN_EPS}) -- 4 runs, not scored")
        try:
            _cs_mod._set_controller_bxt_seeds(CONTROLLER_PATH, _TRAIN_SEEDS,
                                              list(seeds), _TRAIN_EPS)
            _br.set_control_mode(BASE["strategy"], CONTROLLER_PATH)
            _br.set_coordinated(CONTROLLER_PATH, BASE["coordinated"])
            _br.set_coordination_algo(CONTROLLER_PATH, BASE["coordination_algo"])
            _br.set_reward_weights(CONTROLLER_PATH, {k: v for k, v in _trov.items()})
            _rep0 = _br.get_first_replication()
            for _ts in _TRAIN_SEEDS:
                log(f"  TRAIN seed={_ts}")
                _run_and_collect(_rep0, f"{BASE['name']}_TRAIN", BASE["strategy"],
                                 _ts, 1.0, BASE["coordinated"],
                                 BASE["coordination_algo"],
                                 bool(_trov.get("GLOBAL_REWARD_MODE")), dict(_trov),
                                 CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, log,
                                 collect=False)
            _cs_mod._set_controller_bxt_seeds(CONTROLLER_PATH, [], [], _TRAIN_EPS)
            log("TRAIN PROLOGUE done -- learner frozen for demand cells")
        except Exception as _te:
            log(f"TRAIN PROLOGUE FAILED: {_te} -- demand cells would clone "
                f"NO_TSP; aborting instead")
            return
    run_num = 0
    _flagged = 0
    _seen_sigs = {}  # (demand, seed) -> [(tactic, freq, sig)] for dup checks
    try:
        for tactic in tactics:
            for freq in freqs:
                for scalar in demands:
                    # ── patch controller ONCE per (tactic, freq) cell ──
                    rov = dict(BASE["reward_overrides"])
                    rov.update(TACTICS[tactic])
                    rov["Z4_CONSTRAINT_MODE"] = True
                    rov.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
                    # Match champion_search's global cost stack so the champion's
                    # config is IDENTICAL to how it was picked (2026-09-16): the
                    # measured side cost + the cascade diagnostic were only set by
                    # champion_search's GLOBAL_* injectors, so phase3 previously
                    # ran the champion WITHOUT measured-side-cost and with the
                    # cascade diagnostics OFF ([CASCADE_ZERO] never logged).
                    rov.setdefault("MEASURED_STATE_FEED", True)
                    rov.setdefault("MEASURED_QUEUE_FEED", True)
                    rov.setdefault("MEASURED_SIDE_COST", True)
                    rov.setdefault("MEASURED_SIDE_COST_DIAG", True)
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

                    # ── THE demand lever, once per scalar (not per seed) ──
                    # Console-side multiply BEFORE any replication of this level
                    # runs. Raises on verification failure -> aborts the sweep
                    # via finally-restore below instead of producing flat rows.
                    try:
                        _br.scale_od_matrices_multiply(scalar, od_state)
                    except Exception as e:
                        log(f"FATAL demand x{scalar:g}: {e}")
                        raise

                    # Fetch the replication AFTER scaling (mirrors the proven
                    # demand test): the rep reads the currently-scaled matrices.
                    rep = _br.get_first_replication()

                    for seed in seeds:
                        if (BASE["name"], tactic, freq, str(scalar), str(seed)) in _done_keys:
                            log(f"  SKIP done: {name} | d={scalar} | seed={seed}")
                            continue
                        run_num += 1
                        log(f"[{run_num}/{n_total}] {CORRIDOR} | {name} | "
                            f"d={scalar} | seed={seed}")
                        # Never inherited: phase-3 is a CAR-demand sweep, so the
                        # bus-frequency injection scalar is forced OFF (see
                        # BUS_FREQ_INJECT_SCALAR_PHASE3 rationale above).
                        _rov_run = dict(rov)
                        _rov_run["BUS_FREQ_INJECT_SCALAR"] = \
                            float(BUS_FREQ_INJECT_SCALAR_PHASE3)
                        m = _run_and_collect(
                            rep, name, strategy, seed, scalar,
                            BASE["coordinated"], BASE["coordination_algo"],
                            bool(rov.get("GLOBAL_REWARD_MODE")), _rov_run,
                            CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, log)
                        if m is not None:
                            m["sens_base"] = BASE["name"]
                            m["sens_tactic"] = tactic
                            m["sens_freq"] = freq
                            m["sens_cooldown_s"] = FREQS[freq]
                            m["demand_scalar"] = scalar
                            # Effective tactic switches as WRITTEN for this run
                            # (post-hoc proof the config reached the runner;
                            # engine-side application is in the [FLAGS] log).
                            # NOTE: these gate the GENERIC candidate pool only.
                            # A base with its own committing decider (MP/BXT/
                            # ZIG/...) skips that pool, so tactics are inert
                            # for it -- identical cross-tactic rows then mean
                            # the base decided alone, not a patch failure.
                            m["sens_ge_on"] = bool(rov.get("ZIG_ENABLE_GE", True))
                            m["sens_ins_on"] = bool(rov.get("ZIG_ENABLE_INS", True))
                            m["sens_gr_on"] = bool(rov.get("ZIG_ENABLE_GR", True))
                            m["sens_seq_on"] = bool(rov.get("ZIG_ENABLE_SEQ", True))
                            _br.append_master_csv(RESULTS_CSV, m)
                            _problems = _sanity_problems(m)
                            for _p in _problems:
                                log(f"  [SANITY] WARNING: {_p}")
                            _carry = [x for x in _problems if x.startswith("CARRY-OVER")]
                            if _carry:
                                raise RuntimeError(
                                    f"ABORTING sweep at run {run_num}/{n_total} "
                                    f"-- stats CARRY-OVER: {_carry[0]}")
                            _sig = _run_signature(m)
                            if _sig is not None:
                                # Keyed duplicate check: same (demand, seed) with
                                # byte-identical KPIs under a DIFFERENT tactic or
                                # freq means the sweep knob did nothing -- either
                                # the base decides without the gated pool (then it
                                # is expected; see sens_*_on note above) or the
                                # patch failed (then it is a bug). Same-cell
                                # repeats (re-runs) legitimately match: only
                                # cross-cell matches are flagged.
                                _prev = _seen_sigs.setdefault((scalar, seed), [])
                                for (_pt, _pf, _psig) in _prev:
                                    if _psig == _sig and (_pt, _pf) != (tactic, freq):
                                        log("  [SANITY] WARNING: byte-identical KPIs to "
                                            f"{_pt}/{_pf} at d={scalar} seed={seed} -- "
                                            f"sweep knob inert for this pair?")
                                        _flagged += 1
                                        break
                                _prev.append((tactic, freq, _sig))

        # ── NO_TSP (no-priority) baseline across the demand x seed grid ──────
        # One run per (demand, seed) -- NO_TSP has no tactics/freqs -- so the
        # sweep can measure the priority benefit (champion vs no-priority) at
        # each demand level. Same persistent od_state multiply chain (ratio
        # based; never reset), so scaling from the last champion scalar back
        # down/up is handled correctly. (user-approved 2026-09-07)
        if _add_no_tsp:
            _nt = NO_TSP_ARM
            try:
                _br.set_control_mode(_nt["strategy"], CONTROLLER_PATH)
                _br.set_coordinated(CONTROLLER_PATH, _nt["coordinated"])
                _br.set_coordination_algo(CONTROLLER_PATH, _nt["coordination_algo"])
                _br.set_reward_weights(CONTROLLER_PATH, {})
                _set_controller_const(CONTROLLER_PATH,
                                      "TSP_COOLDOWN_OVERRIDE_S", None)
            except Exception as e:
                log(f"FATAL patch NO_TSP baseline: {e}")
            else:
                for scalar in demands:
                    try:
                        _br.scale_od_matrices_multiply(scalar, od_state)
                    except Exception as e:
                        log(f"FATAL demand x{scalar:g} (NO_TSP): {e}")
                        raise
                    rep = _br.get_first_replication()
                    for seed in seeds:
                        if ("NO_TSP", "NONE", "NONE", str(scalar), str(seed)) in _done_keys:
                            log(f"  SKIP done: NO_TSP | d={scalar} | seed={seed}")
                            continue
                        run_num += 1
                        log(f"[{run_num}/{n_total}] {CORRIDOR} | NO_TSP | "
                            f"d={scalar} | seed={seed}")
                        _rov_run = {"BUS_FREQ_INJECT_SCALAR":
                                    float(BUS_FREQ_INJECT_SCALAR_PHASE3)}
                        m = _run_and_collect(
                            rep, "NO_TSP", _nt["strategy"], seed, scalar,
                            _nt["coordinated"], _nt["coordination_algo"],
                            False, _rov_run,
                            CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, log)
                        if m is not None:
                            m["sens_base"] = "NO_TSP"
                            m["sens_tactic"] = "NONE"
                            m["sens_freq"] = "NONE"
                            m["sens_cooldown_s"] = None
                            m["demand_scalar"] = scalar
                            m["sens_ge_on"] = False
                            m["sens_ins_on"] = False
                            m["sens_gr_on"] = False
                            m["sens_seq_on"] = False
                            _br.append_master_csv(RESULTS_CSV, m)
                            _problems = _sanity_problems(m)
                            for _p in _problems:
                                log(f"  [SANITY] WARNING: {_p}")
                            if _problems:
                                _flagged += 1
                            _sig = _run_signature(m)
                            if _sig is not None:
                                # A TSP cell byte-identical to the NO_TSP
                                # baseline at the same demand+seed acted as a
                                # no-op clone -- flag it (reverse direction:
                                # champion cells ran first, so they are in
                                # _seen_sigs already).
                                _prev = _seen_sigs.setdefault((scalar, seed), [])
                                for (_pt, _pf, _psig) in _prev:
                                    if _psig == _sig and (_pt, _pf) != ("NONE", "NONE"):
                                        log("  [SANITY] WARNING: NO_TSP row identical to "
                                            f"{_pt}/{_pf} at d={scalar} seed={seed} -- "
                                            f"that cell ran as a baseline clone?")
                                        _flagged += 1
                                        break
                                _prev.append(("NONE", "NONE", _sig))
                            _carry = [x for x in _problems if x.startswith("CARRY-OVER")]
                            if _carry:
                                raise RuntimeError(
                                    f"ABORTING NO_TSP baseline at run {run_num}/{n_total} "
                                    f"-- stats CARRY-OVER: {_carry[0]}")
    finally:
        # restore baseline plan state: neutral cooldown + original demand
        try:
            _set_controller_const(CONTROLLER_PATH, "TSP_COOLDOWN_OVERRIDE_S", None)
        except Exception:
            pass
        try:
            _br.scale_od_matrices_multiply(1.0, od_state)
        except Exception as _re:
            # finally must not throw; the model may need a reload for pristine
            # demand if this restore failed (integer-cell rounding aside).
            try:
                log(f"WARNING: OD restore to 1.0x failed: {_re} -- reload the "
                    f"model before the next sweep for pristine demand.")
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
    _argv0 = (_sys.argv[0] if getattr(_sys, "argv", None) else "")
    if "phase3_sensitivity" not in _argv0:
        # Loaded in the Aimsun console (import/paste: no argv available) --
        # do NOT auto-run; call main() explicitly instead.
        print("phase3_sensitivity loaded in-console; run "
              "p3.main(resume=True) to resume (no flags available here).")
    else:
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("--quick", action="store_true",
                        help="smoke test: BOTH/X1/x1.0 x seeds 300,400 only")
        ap.add_argument("--resume", action="store_true",
                        help="keep existing RESULTS_CSV and skip successful "
                             "(tactic, freq, demand, seed) rows (truncated runs "
                             "re-execute)")
        ap.add_argument("--cell", action="append", default=None,
                        help="only run a tactic/freq cell, e.g. --cell BOTH/X1_BASELINE "
                             "(repeatable)")
        a = ap.parse_args()
        main(quick=(a.quick or QUICK_DEFAULT), resume=(a.resume or RESUME_DEFAULT),
             cells=(a.cell or CELLS_DEFAULT))
