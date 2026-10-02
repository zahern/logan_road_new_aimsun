"""
run_kg_champion_and_phase2.py -- KG, one file, three jobs, fresh seeds.

JOB 1  Champion validation: CELLQLEARN_GATED on 5 fresh seeds at x1.0
       (learner trains on the standard prologue, then freezes).
JOB 2  Phase 2 bus-demand sweep: DCTSP_MARL (the champion) at
       x0.5, x0.75, x1.0, x2.0, x3.0 bus frequency -> 5 x 5 = 25 runs.
JOB 3  NO_TSP baseline at the SAME five bus levels and seeds -> 25 runs
       (20 if the existing x1.0 rows are reused; 5 if not).

Car/truck OD demand stays pinned at 1.0x throughout, so the only thing the
sweep varies is the number of buses. Both jobs 2 and 3 measure the champion
against do-nothing AT THE SAME BUS LEVEL -- more buses raise bus delay even
with no priority, so a cross-level comparison would be meaningless.

HOW TO RUN (Aimsun, KG model open, execute this one file):
  run_kg_champion_and_phase2.py
Re-execute after any interruption: everything is resume-safe and nothing is
wiped. Seeds are disjoint from every earlier campaign (eval 300-700, train
800-1100).

OUTPUTS (written next to this file, appended, never truncated):
  champion_kg_newseeds.csv              job 1
  champion_bus_demand_newseeds.csv      jobs 2 + 3, columns
                                       sweep_bus_demand_scalar / sweep_base_arm
"""
import os as _os
import sys as _sys
import importlib.util as _ilu

# ── configuration ──────────────────────────────────────────────────────────
FRESH_SEEDS = [1200, 1300, 1400, 1500, 1600]     # 5 fresh seeds
BUS_DEMAND_SCALARS = [0.5, 0.75, 1.0, 2.0, 3.0]  # PT frequency multipliers
# 2026-10-01: was "CELLQLEARN_GATED", which is NOT one of champion_search.ARMS
# (only NO_TSP, CELLQLEARN, CELLQLEARN_FORCED, DCTSP_ZIG, DCTSP_MP_ECTM,
# DCTSP_BARGAIN_SPM are), so the default could not run and aborted with
#   RuntimeError: arm 'CELLQLEARN_GATED' is not in champion_search.ARMS
# CELLQ_BEST_CTM is the measured KG champion: learner + CTM-priced cross cost,
# uncoordinated. Seed 400, +6.1% vs NO_TSP (the same arm without CELLQ_CTM_REWARD
# scores -4.7%), objective = pax per delay-hour, higher is better.
# Declare any other arm in INLINE_ARMS below.
CHAMPION_ARM = "CELLQ_BEST_CTM"                     # job 1
PHASE2_CHAMPION = "DCTSP_MARL"                   # job 2
BASELINE_ARM = "NO_TSP"                          # job 3
CAR_DEMAND_SCALAR = 1.0                          # never swept

JOBS = ("champion", "phase2", "baseline")


# ── locate ourselves (works in Aimsun, where __file__ may be absent) ────────
def _module_root(_marker="champion_search.py"):
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
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)


def _load(_name, _filename):
    _p = _os.path.join(_ROOT, _filename)
    if not _os.path.isfile(_p):
        raise RuntimeError(f"{_filename} not found next to this script "
                           f"(looked in {_ROOT!r}). Unzip the bundle so "
                           f"champion_search.py sits beside this file.")
    _spec = _ilu.spec_from_file_location(_name, _p)
    _mod = _ilu.module_from_spec(_spec)
    _sys.modules[_name] = _mod
    try:
        _spec.loader.exec_module(_mod)
    except SystemExit:
        pass
    return _mod


_cs = _load("_cs_kgcp2", "champion_search.py")
CORRIDOR = _cs.CORRIDOR
CORR_DIR = _cs.CORR_DIR
_br = _cs._br
log = _br.log

# bus-frequency scaler (PT injection, not timetable edits)
_bd = _load("_bd_kgcp2", _os.path.join(CORR_DIR, "batch_runner_bus_demand.py"))

RESULTS_CHAMPION = _os.path.join(_ROOT, "champion_kg_newseeds.csv")
RESULTS_BUS = _os.path.join(_ROOT, "champion_bus_demand_newseeds.csv")


# ── resume helpers ─────────────────────────────────────────────────────────
def _load_done_keys(_path, _keyfields):
    """(arm, seed, bus_scalar) triples already banked, so a restart skips them."""
    _keys = set()
    if not _os.path.isfile(_path):
        return _keys
    try:
        import csv as _csv
        with open(_path, newline='', encoding='utf-8-sig') as _fh:
            for _r in _csv.DictReader(_fh):
                if str(_r.get("run_success", "")).strip().lower() in (
                        "false", "0", "no"):
                    continue
                try:
                    if float(_r.get("stats_SimDuration_hrs", "") or 0) < 0.98:
                        continue          # truncated run: re-do it
                except (TypeError, ValueError):
                    pass
                try:
                    if float(_r.get("stats_Objective_PaxPerDelayHr", "") or 0) == 0.0:
                        continue          # blank row: re-do it
                except (TypeError, ValueError):
                    continue
                _vals = tuple(str(_r.get(_k, "")).strip() for _k in _keyfields)
                _keys.add(_vals)
    except Exception as _e:
        log(f"WARN could not read {_os.path.basename(_path)} for resume: {_e}")
    return _keys


# champion_search.ARMS only carries the six ORIGINAL paper arms, so asking this
# script for anything else (CELLQLEARN_GATED, the CTM-reward champion, an
# ablation arm) used to abort the whole batch with
#     RuntimeError: arm 'CELLQLEARN_GATED' is not in champion_search.ARMS
# -- one unknown name killed every arm, including the ones that were fine.
# INLINE_ARMS lets an ad-hoc champion be declared here instead. It is merged
# AFTER champion_search.ARMS, so a name defined in both resolves to ARMS (the
# battle-tested definition wins).
#
# best_cell_q_learner (2026-10-01): the KG winner from the isolation sweep --
# learner + CTM-priced reward, NO corridor coordination, because coordination is
# what costs 27% (coord alone is inert in NORMAL mode, so the old
# NO_TSP_COORD control proved nothing). Measured +6.1% vs NO_TSP, seed 400.
INLINE_ARMS = {
    "CELLQ_BEST_CTM": {
        "strategy": "GLOBAL_REWARD",
        "coordinated": False,
        "coordination_algo": "KALMAN",
        "reward_overrides": {
            "GLOBAL_REWARD_MODE": True,
            "BXT_CORRIDOR_MODE": True,
            "CELLQ_CORRIDOR_LEARN": True,
            "CELLQ_CTM_REWARD": True,
            "BXT_ALPHA": 0.3, "BXT_GAMMA": 0.5, "BXT_EPSILON": 0.10,
            "MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True,
            "MEASURED_SIDE_COST": True,
        },
    },
}


def _arm_by_name(_name):
    for _a in _cs.ARMS:
        if _a.get("name") == _name:
            return _a
    if _name in INLINE_ARMS:
        _d = dict(INLINE_ARMS[_name])
        _d["name"] = _name
        log(f"arm {_name!r} resolved from INLINE_ARMS "
            f"(strategy={_d.get('strategy')!r}, coordinated={_d.get('coordinated')})")
        return _d
    _known = [a.get("name") for a in _cs.ARMS] + sorted(INLINE_ARMS)
    _hint = ""
    try:
        import difflib as _dl
        _c = _dl.get_close_matches(_name, _known, n=3, cutoff=0.4)
        if _c:
            _hint = ("  did you mean: " + ", ".join(_c) + "?")
    except Exception:
        pass
    raise RuntimeError(
        f"arm {_name!r} is not in champion_search.ARMS or INLINE_ARMS."
        f"{_hint}\n  known arms: {_known}\n"
        f"  to add one, declare it in INLINE_ARMS at the top of this file.")


def _patch_controller(_arm, CONTROLLER_PATH):
    """Apply one arm's control mode / coordination / rewards to the controller.

    ALWAYS calls set_reward_weights, including with None for the baseline:
    that resets every mode flag to False so the champion's flags cannot leak
    into the NO_TSP run that follows it. (The bus sweep runs NO_TSP after the
    champion at every level, so without the reset every arm looks identical.)
    """
    _strategy = _arm["strategy"]
    _coord = _arm.get("coordinated", False)
    _algo = _arm.get("coordination_algo", "KALMAN")
    _rov = dict(_arm.get("reward_overrides", {}) or {})
    _is_baseline = (_strategy == "NORMAL")
    if not _is_baseline:
        _rov["Z4_CONSTRAINT_MODE"] = True
        _rov.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
    _bus_pred = str(_rov.get("BUS_PREDICTOR_TYPE", "ADAPTIVE_KALMAN")).upper()
    _br.set_control_mode(_strategy, CONTROLLER_PATH,
                         _arm.get("active_intersections"))
    _br.set_coordinated(CONTROLLER_PATH, _coord)
    _br.set_coordination_algo(CONTROLLER_PATH, _algo)
    _numeric = {k: v for k, v in _rov.items() if k != "GLOBAL_REWARD_MODE"}
    _br.set_reward_weights(CONTROLLER_PATH,
                           (None if _is_baseline else (_numeric or None)))
    # The bus sweep arms never learn; empty seed lists -> per-seed runs.
    try:
        _cs._set_controller_bxt_seeds(CONTROLLER_PATH, [], [],
                                      _cs.BXT_TRAIN_EPSILON)
    except Exception:
        pass
    return _strategy, _coord, _algo, _is_baseline, _rov, _bus_pred


def _run_one(_arm, _label, _seed, _bus_scalar, CONTROLLER_PATH,
             RUN_CONFIG_PATH, PROJECT_DIR, _rep):
    """Run one replication and collect its metrics.

    The final RESULTS_CSV argument of _run_and_collect is passed as None: that
    argument is where champion_search logs its own per-run trace, and we write
    our own rows with append_master_csv instead, so we must not let it append to
    (or truncate) a file we are managing ourselves.
    """
    _strategy, _coord, _algo, _is_base, _rov, _bus_pred = _patch_controller(
        _arm, CONTROLLER_PATH)
    return _cs._run_and_collect(
        _br, _rep, _label, _strategy, _seed, CAR_DEMAND_SCALAR,
        _coord, _algo, bool(_rov.get("GLOBAL_REWARD_MODE", False)),
        (None if _is_base else (dict(_rov) or None)),
        _bus_pred, CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, None, log)


# ── JOB 1: champion validation on fresh seeds ───────────────────────────────
def run_champion_validation(quick=False):
    """CELLQLEARN_GATED, car demand x1.0, bus frequency x1.0, fresh seeds.

    The learner trains on the standard prologue (TRAIN_SEEDS, exploration on,
    nothing scored) inside this same session, then freezes for the scored
    seeds. Without the prologue a fresh session starts with an empty Q-table
    and the arm degenerates into a NO_TSP clone.
    """
    seeds = FRESH_SEEDS[:2] if quick else list(FRESH_SEEDS)
    arm = _arm_by_name(CHAMPION_ARM)
# An inline arm may declare is_learner explicitly. Deriving it from
    # champion_search.LEARNING_ARMS alone is a trap: a NEW learner name is not in
    # that set, so is_learner silently goes False, the TRAIN prologue is skipped,
    # and the Q-table is wiped every scored seed (per_seed) -- i.e. an arm that
    # looks trained is scored cold. Default here is False on purpose: CELLQ_BEST_CTM
    # reproduces the sweep arm, which was itself measured under per_seed learning,
    # and that is what the +6.1% refers to. Set True to add the prologue.
    if "is_learner" in arm:
        is_learner = bool(arm["is_learner"])
    else:
        is_learner = CHAMPION_ARM in getattr(_cs, "LEARNING_ARMS", set())
    train_seeds = list(getattr(_cs, "TRAIN_SEEDS", [800, 900, 1000, 1100]))
    train_eps = float(getattr(_cs, "BXT_TRAIN_EPSILON", 0.30))

    n = len(seeds) + (len(train_seeds) if is_learner else 0)
    log("=" * 70)
    log(f"JOB 1 CHAMPION VALIDATION -- corridor={CORRIDOR} arm={CHAMPION_ARM}")
    log(f"  fresh seeds={seeds}"
        + (f" + train prologue {train_seeds}" if is_learner else ""))
    log(f"  total runs = {n}  -> {RESULTS_CHAMPION}")
    log("=" * 70)

    done = _load_done_keys(RESULTS_CHAMPION, ("run_experiment", "run_seed"))
    if not done:
        try:
            if _os.path.exists(RESULTS_CHAMPION):
                _os.remove(RESULTS_CHAMPION)
        except Exception:
            pass
    try:
        _br._set_logging(CONTROLLER_PATH, enabled=False)
    except Exception:
        pass
    try:
        _cs._disable_batch_plotting(CONTROLLER_PATH)
    except Exception:
        pass

    run_num = 0
    flagged = 0
    try:
        # bus frequency OFF for a plain x1.0 champion run
        _bd.set_bus_freq_inject_scalar(0.0, CONTROLLER_PATH)
        try:
            _br.set_demand_scalar(CAR_DEMAND_SCALAR, {})
        except Exception as e:
            log(f"WARN car demand scalar: {e}")

        if is_learner and train_seeds:
            # NOTE (2026-09-30): the prologue can never be skipped on resume.
            # Its runs are labelled f"{CHAMPION_ARM}_TRAIN" and are collected with
            # RESULTS_CSV=None, so they never appear in RESULTS_CHAMPION and
            # `done` can never contain a ("TRAIN", seed) key -- this guard is
            # therefore always true. That is the DESIRED behaviour, not an
            # oversight: the trained Q-table lives in module memory only, so a
            # resumed process has an empty table and must retrain before it can
            # score any seed. Skipping the prologue would score a cold-started arm.
            train_keys = {("TRAIN", str(s)) for s in train_seeds}
            if not all(k in done for k in train_keys):
                _strategy, _coord, _algo, _is_base, _rov, _bus_pred = \
                    _patch_controller(arm, CONTROLLER_PATH)
                # Prologue trains the table (phase='train', exploration on). The
                # freeze flag is set here too so the whole job shares one value --
                # otherwise the prologue would honour the engine default while the
                # scored seeds honoured whatever was patched afterwards.
                _cs._set_controller_bxt_seeds(
                    CONTROLLER_PATH, train_seeds, seeds, train_eps,
                    freeze_on_eval=bool(getattr(
                        _cs, "LEARNERS_FREEZE_ON_EVAL", True)))
                for _s in train_seeds:
                    run_num += 1
                    log(f"[{run_num}/{n}] TRAIN prologue seed={_s} (not scored)")
                    _cs._run_and_collect(
                        _br, _rep, f"{CHAMPION_ARM}_TRAIN", _strategy, _s,
                        CAR_DEMAND_SCALAR, _coord, _algo,
                        bool(_rov.get("GLOBAL_REWARD_MODE", False)),
                        dict(_rov) or None, _bus_pred, CONTROLLER_PATH,
                        RUN_CONFIG_PATH, PROJECT_DIR, None, log)
            # ── FREEZE the learner for the scored seeds ────────────────────────
            # BUGFIX 2026-09-30: this used to pass ([], []), which puts the engine
            # in per_seed phase and calls reset_bxt_learning() on EVERY scored
            # run (engine.py AAPIInit). That is not a freeze -- it wipes the table
            # accumulated by the prologue and cold-starts each scored seed, so the
            # arm was scored untrained while the log claimed "learner frozen".
            # The scored seeds must stay in BXT_EVAL_SEEDS: the engine resets only
            # at the FIRST train seed, so the table survives the prologue and is
            # held across the scored seeds.
            #
            # freeze_on_eval: True reproduces the September champion numbers (and
            # is what makes repeat runs bit-identical); False lets the table keep
            # learning through the scored seeds, which is a different experiment
            # whose results must not be pooled with frozen-policy ones. Defaults
            # to champion_search.LEARNERS_FREEZE_ON_EVAL so both scripts agree.
            _freeze = bool(getattr(_cs, "LEARNERS_FREEZE_ON_EVAL", True))
            _cs._set_controller_bxt_seeds(CONTROLLER_PATH, train_seeds, seeds,
                                          train_eps, freeze_on_eval=_freeze)
            log(f"TRAIN PROLOGUE done -- learner FROZEN for scored seeds "
                f"(BXT_FREEZE_ON_EVAL={_freeze}, scored seeds held in "
                f"BXT_EVAL_SEEDS={seeds})")

        _rep = _br.get_first_replication()
        for _s in seeds:
            key = (CHAMPION_ARM, str(_s))
            if key in done:
                log(f"  SKIP done: {CHAMPION_ARM} seed={_s}")
                continue
            run_num += 1
            log(f"[{run_num}/{n}] {CORRIDOR} | {CHAMPION_ARM} | seed={_s}")
            m = _run_one(arm, CHAMPION_ARM, _s, 1.0, CONTROLLER_PATH,
                         RUN_CONFIG_PATH, PROJECT_DIR, _rep)
            if m is not None:
                m["sweep_bus_demand_scalar"] = 1.0
                m["sweep_base_arm"] = CHAMPION_ARM
                m["sweep_seed_set"] = "fresh_1200_1600"
                _br.append_master_csv(RESULTS_CHAMPION, m)
                for _p in _cs._kpi_sanity(m):
                    log(f"  [SANITY] WARNING: {_p}")
                    flagged += 1
    finally:
        try:
            _bd.set_bus_freq_inject_scalar(0.0, CONTROLLER_PATH)
        except Exception:
            pass
        try:
            _br._set_logging(CONTROLLER_PATH, enabled=True)
        except Exception:
            pass

    log("=" * 70)
    log(f"JOB 1 DONE -> {RESULTS_CHAMPION}")
    if flagged:
        log(f"SANITY SUMMARY: {flagged} run(s) FLAGGED -- review above")
    log("=" * 70)


# ── JOBS 2 + 3: bus-demand sweep, champion then NO_TSP at each level ───────
def run_bus_sweep(quick=False, champion_only=False, baseline_only=False):
    scalars = BUS_DEMAND_SCALARS[:1] if quick else list(BUS_DEMAND_SCALARS)
    seeds = FRESH_SEEDS[:2] if quick else list(FRESH_SEEDS)
    arms = []
    if not baseline_only:
        arms.append((PHASE2_CHAMPION, _arm_by_name(PHASE2_CHAMPION)))
    if not champion_only:
        arms.append((BASELINE_ARM, _arm_by_name(BASELINE_ARM)))
    n_total = len(scalars) * len(arms) * len(seeds)

    log("=" * 70)
    log(f"JOB 2+3 BUS-DEMAND SWEEP -- corridor={CORRIDOR}")
    log(f"  bus scalars={scalars} | arms={[a[0] for a in arms]} | seeds={seeds}")
    log(f"  total runs = {n_total}  (car/truck demand fixed at "
        f"{CAR_DEMAND_SCALAR:g}x)")
    log(f"  -> {RESULTS_BUS}")
    log("=" * 70)

    done = _load_done_keys(
        RESULTS_BUS, ("run_experiment", "run_seed", "sweep_bus_demand_scalar"))
    if not done:
        try:
            if _os.path.exists(RESULTS_BUS):
                _os.remove(RESULTS_BUS)
        except Exception:
            pass
    log(f"RESUME: {len(done)} completed rows already in "
        f"{_os.path.basename(RESULTS_BUS)} -- those cells are skipped")

    try:
        _br._set_logging(CONTROLLER_PATH, enabled=False)
    except Exception:
        pass
    try:
        _cs._disable_batch_plotting(CONTROLLER_PATH)
    except Exception:
        pass

    run_num = 0
    skipped = 0
    try:
        _br.set_demand_scalar(CAR_DEMAND_SCALAR, {})
        _rep = _br.get_first_replication()
        for _bus in scalars:
            try:
                _bd.set_bus_freq_inject_scalar(_bus, CONTROLLER_PATH)
                log(f"-- bus frequency x{_bus:g} (PT injection mode)")
            except Exception as e:
                log(f"FATAL bus scalar {_bus:g}: {e}")
                continue
            for _name, _arm in arms:
                _label = f"{_name}_BUSx{_bus:g}"
                for _s in seeds:
                    key = (_label, str(_s), str(_bus))
                    if key in done:
                        skipped += 1
                        log(f"  SKIP done: {_label} seed={_s}")
                        continue
                    run_num += 1
                    log(f"[{run_num}/{n_total}] {CORRIDOR} | {_label} | seed={_s}")
                    m = _run_one(_arm, _label, _s, _bus, CONTROLLER_PATH,
                                 RUN_CONFIG_PATH, PROJECT_DIR, _rep)
                    if m is not None:
                        m["sweep_bus_demand_scalar"] = _bus
                        m["sweep_base_arm"] = _name
                        m["sweep_seed_set"] = "fresh_1200_1600"
                        _br.append_master_csv(RESULTS_BUS, m)
                        for _p in _cs._kpi_sanity(m):
                            log(f"  [SANITY] WARNING: {_p}")
    finally:
        try:
            _bd.set_bus_freq_inject_scalar(0.0, CONTROLLER_PATH)
        except Exception:
            pass
        try:
            _br._set_logging(CONTROLLER_PATH, enabled=True)
        except Exception:
            pass

    log("=" * 70)
    log(f"JOB 2+3 DONE (ran {run_num}, skipped {skipped} done) -> {RESULTS_BUS}")
    log("=" * 70)


# ── driver ─────────────────────────────────────────────────────────────────
def main(jobs=JOBS, quick=False):
    global CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    PROJECT_DIR = _br.PROJECT_DIR

    print("=" * 70)
    print(f"[KG] corridor={CORRIDOR} runner={_os.path.join(CORR_DIR, 'batch_runner.py')}")
    print(f"[KG] fresh seeds        : {FRESH_SEEDS}")
    print(f"[KG] bus levels         : {BUS_DEMAND_SCALARS}")
    print(f"[KG] car demand         : fixed x{CAR_DEMAND_SCALAR:g}")
    print(f"[KG] job 1 arm          : {CHAMPION_ARM}")
    print(f"[KG] job 2/3 arms       : {PHASE2_CHAMPION} + {BASELINE_ARM}")
    print(f"[KG] jobs               : {tuple(jobs)}")
    print("=" * 70)

    if "champion" in jobs:
        run_champion_validation(quick=quick)
    if "phase2" in jobs or "baseline" in jobs:
        run_bus_sweep(quick=quick,
                      champion_only=("baseline" not in jobs),
                      baseline_only=("phase2" not in jobs))

    print("=" * 70)
    print("[KG] ALL REQUESTED JOBS DONE")
    print(f"  {RESULTS_CHAMPION}")
    print(f"  {RESULTS_BUS}")
    print("=" * 70)


# Aimsun-safe launch: never test sys.argv[0] (inside Aimsun it is the Aimsun
# executable, not this file). --quick is honoured for a 2-run smoke test.
if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--quick", action="store_true",
                     help="smoke test: 2 seeds, 1 bus level")
    _ap.add_argument("--jobs", default=",".join(JOBS),
                     help="subset of champion,phase2,baseline")
    try:
        _a, _ = _ap.parse_known_args()
    except SystemExit:
        _a = None
    if _a is None:
        main()
    else:
        main(jobs=tuple(j.strip() for j in _a.jobs.split(",") if j.strip()),
             quick=_a.quick)
else:
    print("run_kg_champion_and_phase2 loaded; run "
          "run_kg_champion_and_phase2.main() to start.")
