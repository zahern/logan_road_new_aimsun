# =============================================================================
# batch_runner_signal_sequencing.py — Phase-adjustment-only TSP sweep
# =============================================================================
#
# PURPOSE (TODO.txt items 1–3):
#   Objective  : total passenger delay (WOBJ_ALPHA=1, Z2=Z3=0), with a
#                CONSTRAINT that total distance travelled (corridor veh-km,
#                Z4) is not sacrificed: when the best outcome is selected, a
#                run only qualifies if its veh-km >= (1 - VKT_TOLERANCE) x
#                the NO_TSP baseline mean. Selection = min passenger delay
#                subject to that throughput floor.
#   Actions    : PHASE ADJUSTMENT ONLY, on the most reliable strategy
#                (WaveGate / DCTSP_ZIG with ZIG_MIN_GAIN_S = 1.0, the
#                WG_HP_MG1 winner). Classic GE and phase insertion are
#                DISABLED via ZIG_ENABLE_GE / ZIG_ENABLE_INS:
#                  SWAPS — phase-order changes only (PHASE_ROTATION +
#                          wrong-phase GR cut + VP phase skip)
#                  TIMES — phase-duration changes only (GREEN_REALLOC
#                          wp=False: net-zero green reallocation)
#                  BOTH  — swaps + times together
#   Frequency  : each family swept at 1, 2, and 3 interventions per cycle:
#                  x1: TSP_CYCLE_LENGTH_OVERRIDE_S = 135 s (≈ one signal
#                      cycle decision window), PHASE_SEQ_MAX_PER_CYCLE = 1
#                  x2: 67.5 s window, PHASE_SEQ_MAX_PER_CYCLE = 2
#                  x3: 45 s window,  PHASE_SEQ_MAX_PER_CYCLE = 3
#   Baseline   : NO_TSP (all actions off) — every comparison is against it.
#
#   Best outcomes (per family and overall) are written to
#     signal_setting_results\best_outcomes.csv     (winning runs)
#     signal_setting_results\selection_summary.json (constraint + ranking)
#
# RUNS: 1 (NO_TSP) + 3 families x 3 frequencies = 10 experiments x SEEDS.
#
# USAGE:
#   Open in Aimsun "Run Script" menu (model must be open).
#   After run: python3.12 generate_dashboard.py batch_results_signal_sequencing.csv signal_sequencing_dashboard.html
# =============================================================================

import os as _os
import json
import csv as _csv
import sys as _sys
import time as _time
from PyANGKernel import GKSystem

_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))

# ── Signalised (active) junctions — derived from INTERSECTIONS_CONFIG ────────
try:
    from intersection_configs import INTERSECTIONS_CONFIG as _IC_CFG
    _ACTIVE_JCTS_LIST = [jid for jid, cfg in _IC_CFG.items()
                         if cfg.get('SignalGroupIDList')]
except ImportError:
    _ACTIVE_JCTS_LIST = None

# =============================================================================
# ── Base config: WaveGate winner (WG_HP_MG1) + pure pax-delay objective ──────
# =============================================================================
_SS_BASE = {
    # Mode flags — most reliable strategy: WaveGate / DCTSP_ZIG
    "GLOBAL_REWARD_MODE":            True,
    "BARGAIN_SPM_MODE":              False,
    "DCTSP_ZIG_MODE":                True,
    "META_TSP_MODE":                 False,
    "MDN_DELAY_MODE":                False,
    "HS_EXT_MODE":                   False,
    "DCTSP_GREEN_REALLOC_MODE":      True,
    "GREEN_REALLOC_RECOVER_FRACTION":1.0,
    "BUS_PREDICTOR_TYPE":            "ADAPTIVE_KALMAN",
    "ZIG_BALANCE_FACTOR":            1.0,
    "NETWORK_FACTOR":                1.0,
    "NETWORK_FACTOR_DENSITY_RAMP":   False,
    "ZIG_PHASE_OVERLAP_S":           0.5,
    "ZIG_MIN_GAIN_S":                1.0,      # WG_HP_MG1 winner
    "ZIG_DE_POP":                    12,
    "ZIG_DE_ITER":                   30,
    "ZIG_DE_F":                      0.8,
    "ZIG_DE_CR":                     0.9,
    # Objective: TOTAL PASSENGER DELAY ONLY (Z2/Z3 weights zeroed).
    # The distance constraint (Z4, veh-km) is enforced at selection time —
    # see select_best_outcomes() below.
    "WOBJ_ALPHA":                    1.0,
    "WOBJ_BETA":                     0.0,
    "WOBJ_GAMMA":                    0.0,
    "WOBJ_Z1_SCALE":                 3000000.0,
    "WOBJ_Z2_SCALE":                 7500.0,
    "WOBJ_Z3_SCALE":                 12000.0,
    "DETECTION_WINDOW_M_OVERRIDE":   50.0,
    # ── Action set: PHASE ADJUSTMENT ONLY — GE and INS hard-disabled ────────
    "ZIG_ENABLE_GE":                 False,
    "ZIG_ENABLE_INS":                False,
    # families override the two below
    "ZIG_ENABLE_GR":                 False,
    "ZIG_ENABLE_SEQ":                False,
    "PHASE_ROTATION_MODE":           False,
    "PHASE_ROTATION_N_SEQS":         3.0,
    "PHASE_ROTATION_THRESHOLD_S":    5.0,
}

# Frequency variants: decision-window seconds + resequences allowed per cycle.
# 135 s ≈ dominant junction cycle on the corridor (once-per-cycle decisions).
_FREQ = {
    "X1": {"TSP_CYCLE_LENGTH_OVERRIDE_S": 135.0, "PHASE_SEQ_MAX_PER_CYCLE": 1},
    "X2": {"TSP_CYCLE_LENGTH_OVERRIDE_S":  67.5, "PHASE_SEQ_MAX_PER_CYCLE": 2},
    "X3": {"TSP_CYCLE_LENGTH_OVERRIDE_S":  45.0, "PHASE_SEQ_MAX_PER_CYCLE": 3},
}

# Action families (TODO: "only swaps, then only update times, then both")
_FAMILY = {
    "SWAPS": {"ZIG_ENABLE_SEQ": True,  "ZIG_ENABLE_GR": False,
              "PHASE_ROTATION_MODE": True,
              "DCTSP_GREEN_REALLOC_MODE": True},   # engine needed for wp=True cut
    "TIMES": {"ZIG_ENABLE_SEQ": False, "ZIG_ENABLE_GR": True,
              "PHASE_ROTATION_MODE": False,
              "DCTSP_GREEN_REALLOC_MODE": True},
    "BOTH":  {"ZIG_ENABLE_SEQ": True,  "ZIG_ENABLE_GR": True,
              "PHASE_ROTATION_MODE": True,
              "DCTSP_GREEN_REALLOC_MODE": True},
}


def _ss(name, family, freq):
    ov = dict(_SS_BASE)
    ov.update(_FAMILY[family])
    ov.update(_FREQ[freq])
    return {
        "name":                 name,
        "enabled":              True,
        "strategy":             "GLOBAL_REWARD",
        "coordinated":          True,
        "coordination_algo":    "SHOCKWAVE",
        "active_intersections": _ACTIVE_JCTS_LIST,
        "reward_overrides":     ov,
        "family":               family,
        "freq":                 freq,
    }


EXPERIMENTS = [
    # Baseline — no TSP at all
    {
        "name":                 "NO_TSP",
        "enabled":              True,
        "strategy":             "NORMAL",
        "coordinated":          False,
        "coordination_algo":    "KALMAN",
        "active_intersections": None,
        "reward_overrides":     {},
        "family":               "NONE",
        "freq":                 "NONE",
    },
    # Sweep 1 — once per cycle
    _ss("SS_SWAPS_X1", "SWAPS", "X1"),
    _ss("SS_TIMES_X1", "TIMES", "X1"),
    _ss("SS_BOTH_X1",  "BOTH",  "X1"),
    # Sweep 2 — twice per cycle
    _ss("SS_SWAPS_X2", "SWAPS", "X2"),
    _ss("SS_TIMES_X2", "TIMES", "X2"),
    _ss("SS_BOTH_X2",  "BOTH",  "X2"),
    # Sweep 3 — three times per cycle
    _ss("SS_SWAPS_X3", "SWAPS", "X3"),
    _ss("SS_TIMES_X3", "TIMES", "X3"),
    _ss("SS_BOTH_X3",  "BOTH",  "X3"),
]

SEEDS          = [300, 42, 12345]
DEMAND_SCALARS = [1.0]

BATCH_RESULTS_CSV = _os.path.join(_SCRIPT_DIR, "batch_results_signal_sequencing.csv")
RESULTS_DIR       = _os.path.join(_SCRIPT_DIR, "signal_setting_results")
CORE_OUTPUT_PATH  = _os.path.join(_SCRIPT_DIR, "core_output_signal_sequencing.csv")

# Throughput constraint: a run qualifies as a "best outcome" only if its
# corridor veh-km is at least (1 - VKT_TOLERANCE) x NO_TSP baseline mean.
VKT_TOLERANCE = 0.01   # allow 1% measurement noise

# =============================================================================
# ── Shared infrastructure — imported from batch_runner.py ────────────────────
# =============================================================================
import importlib.util as _ilu
_br_path = _os.path.join(_SCRIPT_DIR, "batch_runner.py")
_spec    = _ilu.spec_from_file_location("_br", _br_path)
_br      = _ilu.module_from_spec(_spec)
_sys.modules["_br"] = _br
try:
    _spec.loader.exec_module(_br)
except SystemExit:
    pass

log                   = _br.log
set_control_mode      = _br.set_control_mode
set_coordinated       = _br.set_coordinated
set_coordination_algo = _br.set_coordination_algo
set_seed              = _br.set_seed
set_reward_weights    = _br.set_reward_weights
write_run_config      = _br.write_run_config
collect_run_metrics   = _br.collect_run_metrics
append_master_csv     = _br.append_master_csv
write_core_output     = _br.write_core_output
get_first_replication = _br.get_first_replication
run_replication       = _br.run_replication
_purge_pyc            = _br._purge_pyc
set_demand_scalar     = _br.set_demand_scalar

CONTROLLER_PATH = _br.CONTROLLER_PATH
RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
PROJECT_DIR     = _br.PROJECT_DIR


# =============================================================================
# ── Best-outcome selection with throughput (distance) constraint ─────────────
# =============================================================================

def _metric(row, *keys, default=None):
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "None"):
            try:
                return float(v)
            except Exception:
                continue
    return default


def select_best_outcomes(csv_path, out_dir):
    """min total passenger delay s.t. veh-km >= (1-tol) x NO_TSP mean."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))
    if not rows:
        print("[SS] No result rows — selection skipped.")
        return

    base_rows = [r for r in rows if r.get("experiment") == "NO_TSP"
                 or r.get("exp_name") == "NO_TSP"]
    vkts = [v for v in (_metric(r, "corridor_total_veh_km", "wobj_Z4_total")
                        for r in base_rows) if v]
    base_vkt = (sum(vkts) / len(vkts)) if vkts else None
    vkt_floor = base_vkt * (1.0 - VKT_TOLERANCE) if base_vkt else None

    base_delays = [v for v in (_metric(r, "stats_TotalPassDelay_hrs",
                                       "total_pass_delay_hrs")
                               for r in base_rows) if v is not None]
    base_delay = (sum(base_delays) / len(base_delays)) if base_delays else None

    def _name(r):
        return r.get("experiment") or r.get("exp_name") or "?"

    candidates = []
    for r in rows:
        if _name(r) == "NO_TSP":
            continue
        delay = _metric(r, "stats_TotalPassDelay_hrs", "total_pass_delay_hrs")
        vkt   = _metric(r, "corridor_total_veh_km", "wobj_Z4_total")
        if delay is None:
            continue
        feasible = True
        if vkt_floor is not None and vkt is not None:
            feasible = (vkt >= vkt_floor)
        candidates.append({"row": r, "name": _name(r), "delay": delay,
                           "vkt": vkt, "feasible": feasible})

    feas = [c for c in candidates if c["feasible"]]
    pool = feas if feas else candidates   # if all violate, report best anyway

    best_overall = min(pool, key=lambda c: c["delay"]) if pool else None
    best_by_family = {}
    for fam in ("SWAPS", "TIMES", "BOTH"):
        fam_pool = [c for c in pool if f"_{fam}_" in c["name"]]
        if fam_pool:
            best_by_family[fam] = min(fam_pool, key=lambda c: c["delay"])

    _os.makedirs(out_dir, exist_ok=True)
    winners = ([best_overall] if best_overall else []) \
              + [c for c in best_by_family.values()
                 if best_overall is None or c is not best_overall]
    if winners:
        fieldnames = list(winners[0]["row"].keys())
        with open(_os.path.join(out_dir, "best_outcomes.csv"), "w",
                  newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for c in winners:
                w.writerow(c["row"])

    summary = {
        "constraint": {
            "description": "corridor veh-km must be >= (1 - tol) x NO_TSP mean "
                           "(total distance travelled not sacrificed)",
            "vkt_tolerance": VKT_TOLERANCE,
            "no_tsp_mean_veh_km": base_vkt,
            "veh_km_floor": vkt_floor,
        },
        "no_tsp_mean_delay_hrs": base_delay,
        "n_candidate_runs": len(candidates),
        "n_feasible_runs": len(feas),
        "all_runs_violated_constraint": (not feas and bool(candidates)),
        "best_overall": ({
            "experiment": best_overall["name"],
            "delay_hrs": best_overall["delay"],
            "veh_km": best_overall["vkt"],
            "delay_saving_vs_no_tsp_hrs":
                (base_delay - best_overall["delay"])
                if (base_delay is not None) else None,
        } if best_overall else None),
        "best_by_family": {
            fam: {"experiment": c["name"], "delay_hrs": c["delay"],
                  "veh_km": c["vkt"]}
            for fam, c in best_by_family.items()
        },
    }
    with open(_os.path.join(out_dir, "selection_summary.json"), "w",
              encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("[SS] " + "=" * 60)
    print(f"[SS] NO_TSP baseline: delay={base_delay} h, veh-km={base_vkt}")
    if best_overall:
        print(f"[SS] BEST (constrained): {best_overall['name']} "
              f"delay={best_overall['delay']:.2f} h veh-km={best_overall['vkt']}")
    for fam, c in best_by_family.items():
        print(f"[SS]   best {fam}: {c['name']} delay={c['delay']:.2f} h")
    print(f"[SS] Winners + summary -> {out_dir}")


# =============================================================================
# ── Main sweep loop ───────────────────────────────────────────────────────────
# =============================================================================
if __name__ == "__main__":
    if _os.path.isfile(BATCH_RESULTS_CSV):
        _os.remove(BATCH_RESULTS_CSV)
        print(f"[SS] Deleted previous results: {_os.path.basename(BATCH_RESULTS_CSV)}")

    _br._QUIET = False
    try:
        _rt_proj = _br.get_project_dir()
        CONTROLLER_PATH = _os.path.join(_rt_proj, "intersection_controller.py")
        RUN_CONFIG_PATH = _os.path.join(_rt_proj, "run_config.py")
        PROJECT_DIR     = _rt_proj
        _br.CONTROLLER_PATH = CONTROLLER_PATH
        _br.RUN_CONFIG_PATH = RUN_CONFIG_PATH
        _br.PROJECT_DIR     = PROJECT_DIR
    except Exception as _e:
        print(f"[SS] WARNING: could not resolve project dir: {_e}")

    enabled = [e for e in EXPERIMENTS if e.get("enabled", True)]
    n_total = len(enabled) * len(SEEDS) * len(DEMAND_SCALARS)

    log("=" * 68)
    log("BATCH_RUNNER_SIGNAL_SEQUENCING — phase-adjustment-only sweep")
    log(f"  {len(enabled)} experiments x {len(SEEDS)} seeds = {n_total} runs")
    log("  Objective: total passenger delay (Z1 only); constraint: veh-km >= "
        f"{100*(1-VKT_TOLERANCE):.0f}% of NO_TSP (applied at selection)")
    log("  Actions: GE=OFF INS=OFF | families: SWAPS / TIMES / BOTH "
        "at 1x, 2x, 3x per cycle")
    log(f"  Results -> {BATCH_RESULTS_CSV}")
    log(f"  Best outcomes -> {RESULTS_DIR}")
    log("=" * 68)

    rep          = get_first_replication()
    run_num      = 0
    failures     = []
    base_demands = {}

    for scalar in DEMAND_SCALARS:
        try:
            set_demand_scalar(scalar, base_demands)
        except Exception as e:
            log(f"WARNING: demand scalar {scalar}: {e}")

        for exp in enabled:
            exp_name         = exp["name"]
            strategy         = exp["strategy"]
            coordinated      = exp.get("coordinated", False)
            coord_algo       = exp.get("coordination_algo", "KALMAN")
            reward_overrides = exp.get("reward_overrides", {})
            is_baseline      = (strategy == "NORMAL")
            bus_predictor    = str(reward_overrides.get("BUS_PREDICTOR_TYPE",
                                                        "ADAPTIVE_KALMAN")).upper()

            try:
                set_control_mode(strategy, CONTROLLER_PATH,
                                 exp.get("active_intersections"))
            except Exception as e:
                print(f"[SS] FATAL: cannot patch strategy for {exp_name}: {e}")
                for seed in SEEDS:
                    failures.append({"experiment": exp_name, "seed": seed,
                                     "error": str(e)})
                continue

            try:
                set_coordinated(CONTROLLER_PATH, coordinated)
                set_coordination_algo(CONTROLLER_PATH, coord_algo)
            except Exception as e:
                print(f"[SS] WARNING: coord patch for {exp_name}: {e}")

            _global_reward = bool(reward_overrides.get("GLOBAL_REWARD_MODE", False))
            _numeric_ov    = {k: v for k, v in reward_overrides.items()
                              if k != "GLOBAL_REWARD_MODE"}

            _run_cfg = None if is_baseline else dict(_numeric_ov)

            if not is_baseline:
                try:
                    set_reward_weights(CONTROLLER_PATH, _numeric_ov or None)
                except Exception as e:
                    log(f"WARNING: reward patch: {e}")

            for seed in SEEDS:
                run_num += 1
                print("-" * 68)
                print(f"[SS] Run {run_num}/{n_total} | {exp_name} "
                      f"| family={exp['family']} freq={exp['freq']} | seed={seed}")

                set_seed(rep, seed)
                _run_cfg_write = ({"DETECTION_WINDOW_M_OVERRIDE": 50.0}
                                  if is_baseline else _run_cfg)
                write_run_config(exp_name, strategy, seed, scalar,
                                 coordinated, coord_algo, RUN_CONFIG_PATH,
                                 global_reward_mode=_global_reward,
                                 reward_cfg=_run_cfg_write,
                                 bus_predictor=bus_predictor)
                _purge_pyc(CONTROLLER_PATH)

                t0 = _time.time()
                success = True
                try:
                    run_replication(rep)
                except Exception as e:
                    success = False
                    failures.append({"experiment": exp_name, "seed": seed,
                                     "error": str(e)})
                    print(f"[SS]   EXCEPTION during simulation: {e}")

                elapsed = _time.time() - t0
                print(f"[SS]   elapsed={elapsed:.0f}s success={success}")
                print(f"[SS] Job {run_num}/{n_total} done, {n_total - run_num} to go")
                try:
                    metrics = collect_run_metrics(
                        PROJECT_DIR, strategy, seed, scalar,
                        exp_name, coordinated, elapsed, success,
                        bus_predictor=bus_predictor)
                    _rc = _run_cfg or {}
                    metrics["sweep_family"]          = exp["family"]
                    metrics["sweep_freq_per_cycle"]  = exp["freq"]
                    metrics["sweep_decision_window_s"] = _rc.get(
                        "TSP_CYCLE_LENGTH_OVERRIDE_S", None)
                    metrics["sweep_seq_max_per_cycle"] = _rc.get(
                        "PHASE_SEQ_MAX_PER_CYCLE", None)
                    metrics["sweep_ge_enabled"]  = bool(_rc.get("ZIG_ENABLE_GE",  False))
                    metrics["sweep_ins_enabled"] = bool(_rc.get("ZIG_ENABLE_INS", False))
                    metrics["sweep_gr_enabled"]  = bool(_rc.get("ZIG_ENABLE_GR",  False))
                    metrics["sweep_seq_enabled"] = bool(_rc.get("ZIG_ENABLE_SEQ", False))
                    append_master_csv(BATCH_RESULTS_CSV, metrics)
                    write_core_output(CORE_OUTPUT_PATH, metrics, reward_overrides)
                    print(f"[SS]   delay={metrics.get('stats_TotalPassDelay_hrs','?')}h "
                          f"veh_km={metrics.get('corridor_total_veh_km','?')} "
                          f"-> {_os.path.basename(BATCH_RESULTS_CSV)}")
                except Exception as e:
                    print(f"[SS]   ERROR collecting metrics: {e}")
                    failures.append({"experiment": exp_name, "seed": seed,
                                     "error": str(e)})

    print("=" * 68)
    print(f"[SS] Sweep complete: {run_num} runs, {len(failures)} failures")
    for f in failures:
        print(f"[SS]   FAILED: {f}")

    # ── Constrained best-outcome selection ──────────────────────────────────
    try:
        select_best_outcomes(BATCH_RESULTS_CSV, RESULTS_DIR)
    except Exception as e:
        print(f"[SS] Best-outcome selection failed: {e}")

    # ── Dashboard ────────────────────────────────────────────────────────────
    _ss_html = _os.path.join(_SCRIPT_DIR, "signal_sequencing_dashboard.html")
    _gen_py  = _os.path.join(_SCRIPT_DIR, "generate_dashboard.py")
    try:
        _gd_spec = _ilu.spec_from_file_location("generate_dashboard", _gen_py)
        _gd      = _ilu.module_from_spec(_gd_spec)
        _gd_spec.loader.exec_module(_gd)
        _gd.generate(BATCH_RESULTS_CSV, _ss_html)
        print(f"[SS] Dashboard written -> {_ss_html}")
    except Exception as _dash_err:
        print(f"[SS] Dashboard generation failed: {_dash_err}")
    print("=" * 68)
