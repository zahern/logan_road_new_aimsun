# =============================================================================
# batch_runner_wavegate.py — WaveGate sensitivity sweep
# =============================================================================
#
# PURPOSE:
#   Sensitivity study on WaveGate (DCTSP_ZIG_MODE, Adaptive-Kalman predictor).
#   All groups share the same fixed base config:
#     ZIG_BALANCE_FACTOR = 1.0  (principled break-even gate)
#     NETWORK_FACTOR     = 1.0  (no hand-tuned amplification)
#     detection window   = 50 m  (Group B swept this; 50 m set as default)
#     ZIG_MIN_GAIN_S     = 1.5 s (Group G showed 1.5 s optimal)
#     Z1 = Z2 = Z3      = 1/3  (all-equal objectives)
#   Passive junctions (10157950, 11118289, 1119660, 39568) excluded via
#   TSP_ACTIVE_INTERSECTIONS — they have no signal plan and cannot be controlled.
#
#   GROUP A — Baseline
#     NO_TSP  No priority at all; reference for all other groups.
#     NO_TSP also writes DETECTION_WINDOW_M_OVERRIDE=40m to run_config so
#     detection counts are directly comparable to WaveGate runs.
#
#   GROUP B — REMOVED (detection distance sweep showed no differentiation;
#     all configs ≈90–94 h, no clear trend with distance; fixed at 50 m)
#
#   GROUP C — Objective weight (fixed 50 m detection, vary Z-weights)
#     WaveGate uses three live objectives:
#       Z1 (WOBJ_ALPHA)  Σ passenger delay (pax·s)          — minimise
#       Z2 (WOBJ_BETA)   Flow-weighted green-wave bandwidth  — maximise
#       Z3 (WOBJ_GAMMA)  Bus headway deviation σ⁺ (pax·s)   — minimise
#     Four variants (one Z off, plus all-Z1 pure delay):
#       WG_NO_Z1   Z1=0, Z2=Z3=0.5
#       WG_NO_Z2   Z2=0, Z1=Z3=0.5
#       WG_NO_Z3   Z3=0, Z1=Z2=0.5
#       WG_Z1ONLY  Z1=1, Z2=Z3=0   (pure pax-delay minimisation)
#     (All-equal baseline = WG_DET40M from Group B)
#
#   GROUP D — ZIG min-gain sensitivity (40 m, all-equal)
#     ZIG_MIN_GAIN_S is the only ZIG hyperparameter that showed a clear effect
#     (1162 h vs 1375 h total delay) in the initial sweep.  BAL/POP/IT all
#     produced binary noise (1240 h / 1293 h) indistinguishable from seed variance.
#       WG_HP_MG1   ZIG_MIN_GAIN_S=1.0 s  (soft gate)
#       WG_HP_MG3   ZIG_MIN_GAIN_S=3.0 s  (hard gate)
#
#   GROUP E — REMOVED (old PR algorithm never fired; all configs identical at
#     94.53 h — indistinguishable from seed noise; PR redesigned as advanced PI
#     in current controller but not yet re-swept here)
#
#   GROUP F — Offset correction sensitivity (40 m, all-equal, OFFSET_CORRECTION_MODE=True)
#     OFFSET_CORRECTION_MODE adds a ZIG candidate that trims the current non-bus
#     phase (up to DCTSP_OC_MAX_ADJ_S) when this junction's last offset-error
#     sample (set by the upstream junction's pre-arm offset computation) shows
#     the bus phase needs to start sooner than scheduled (corridor drift).
#     Competes against NO_ACTION/GE/INS/PR through the normal reward gate —
#     contrast with the pre-existing GLOBAL_REWARD_MODE-only "Forward OC" that
#     fires unconditionally and isn't available in WaveGate/ZIG mode.
#       WG_OC_THR2   DCTSP_OC_THRESH_S=2.0 (low gate, fires on small drift)
#       WG_OC_THR5   DCTSP_OC_THRESH_S=5.0 (default-ish)
#       WG_OC_MAXADJ10  DCTSP_OC_MAX_ADJ_S=10.0 (smaller max trim)
#       WG_OC_MAXADJ20  DCTSP_OC_MAX_ADJ_S=20.0 (larger max trim)
#
#   GROUP G — Min-gain fine sweep + stacked best (40 m, all-equal)
#     Group D showed ZIG_MIN_GAIN_S=1.0 beating BOTH 0.0 (all of B/C/E/F) and
#     3.0 (WG_HP_MG3) on every metric at once: best objective (102.2 vs 82.5-
#     95.0 elsewhere), lowest bus pax delay (53.3s), AND the smallest bus-
#     count shortfall vs NO_TSP (55/57 vs 54/57 everywhere else) — so the
#     true optimum likely sits near 1.0, not at the swept endpoints.
#       WG_MG_0_5    ZIG_MIN_GAIN_S=0.5  (between 0.0 baseline and the 1.0 winner)
#       WG_MG_1_5    ZIG_MIN_GAIN_S=1.5  (just past the 1.0 winner)
#       WG_MG_2_0    ZIG_MIN_GAIN_S=2.0  (between 1.0 winner and the 3.0 hard gate)
#     Groups E and F were each tested in isolation against the weak
#     MIN_GAIN_S=0.0 baseline, not against the proven MIN_GAIN_S=1.0 winner —
#     so any gains they offer may be hidden under noise from low-value
#     marginal actions that MIN_GAIN_S=1.0 would have screened out. WG_BEST_STACK
#     combines the Group D winner with PR and OC enabled to test whether the
#     gains compound:
#       WG_BEST_STACK  ZIG_MIN_GAIN_S=1.0 + PHASE_ROTATION_MODE (N_SEQS=3,
#                      THR=5.0) + OFFSET_CORRECTION_MODE (THRESH=3.0, MAXADJ=15.0)
#
#   Single seed (300).  Results → batch_results_wavegate.csv
#   15 runs total (A=1, C=4, D=2, F=4, G=4).  B and E removed (no gain).
#
# USAGE:
#   Open in Aimsun "Run Script" menu.
#   After run: python3.12 generate_dashboard.py batch_results_wavegate.csv wavegate_dashboard.html
# =============================================================================

import os as _os
import re
import json
import csv
import glob
import shutil
import sys as _sys
import time as _time
from PyANGKernel import GKSystem

_SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))

# ── Signalized (active) junctions — derived from INTERSECTIONS_CONFIG ──────────
# All configured junctions are signalised; former passive stubs (10157950,
# 11118289, 1119660, 39568) were removed from intersection_configs.py.
try:
    from intersection_configs import INTERSECTIONS_CONFIG as _IC_CFG
    _ACTIVE_JCTS_LIST = [jid for jid, cfg in _IC_CFG.items()
                         if cfg.get('SignalGroupIDList')]
except ImportError:
    _ACTIVE_JCTS_LIST = None   # fallback: all junctions (import fails outside Aimsun)

# =============================================================================
# ── FIXED WaveGate base overrides ────────────────────────────────────────────
# =============================================================================
_WG_BASE = {
    # Mode flags
    "GLOBAL_REWARD_MODE":            True,
    "BARGAIN_SPM_MODE":              False,
    "DCTSP_ZIG_MODE":                True,
    "META_TSP_MODE":                 False,
    "MDN_DELAY_MODE":                False,
    "HS_EXT_MODE":                   False,
    "DCTSP_GREEN_REALLOC_MODE":      True,
    "GREEN_REALLOC_RECOVER_FRACTION":1.0,
    # Predictor
    "BUS_PREDICTOR_TYPE":            "ADAPTIVE_KALMAN",
    # Gate — principled break-even
    "ZIG_BALANCE_FACTOR":            1.0,
    "NETWORK_FACTOR":                1.0,
    "NETWORK_FACTOR_DENSITY_RAMP":   False,
    "ZIG_PHASE_OVERLAP_S":           0.5,
    "ZIG_MIN_GAIN_S":                1.5,
    # DE solver baseline
    "ZIG_DE_POP":                    12,
    "ZIG_DE_ITER":                   30,
    "ZIG_DE_F":                      0.8,
    "ZIG_DE_CR":                     0.9,
    # Objective scales
    "WOBJ_Z1_SCALE":                 3000000.0,
    "WOBJ_Z2_SCALE":                 7500.0,
    "WOBJ_Z3_SCALE":                 12000.0,
    # All-equal objective weights (baseline)
    "WOBJ_ALPHA":                    round(1/3, 6),
    "WOBJ_BETA":                     round(1/3, 6),
    "WOBJ_GAMMA":                    round(1/3, 6),
    # Detection window — 50 m default (Groups C/D/F/G inherit this)
    "DETECTION_WINDOW_M_OVERRIDE":   50.0,
}


def _wg(name, overrides):
    """Build one WaveGate experiment entry."""
    ov = dict(_WG_BASE)
    ov.update(overrides)
    return {
        "name":                 name,
        "enabled":              True,
        "strategy":             "GLOBAL_REWARD",
        "coordinated":          True,
        "coordination_algo":    "SHOCKWAVE",
        "active_intersections": _ACTIVE_JCTS_LIST,   # excludes passive junctions
        "reward_overrides":     ov,
    }


# =============================================================================
# ── EXPERIMENTS ───────────────────────────────────────────────────────────────
# =============================================================================
# Groups trimmed after initial run showed:
#   Groups E-H (Horizon/CoordDepth/GreenRecovery/SideWeight) — all clustered at
#   the same two delay values (1240 h vs 1293 h), indistinguishable from seed
#   noise.  Removed to focus runs on parameters with clear signal.
#   Group D trimmed: ZIG_BALANCE_FACTOR, ZIG_DE_POP, ZIG_DE_ITER showed no
#   differentiation; only ZIG_MIN_GAIN_S produced a meaningful effect (1162 h
#   vs 1375 h), so BAL/POP/IT variants are removed.
#
# EXPERIMENTS total: A(1) + C(4) + D(2) + F(4) + G(4) = 15 runs × 1 seed = 15 total
# Groups B (detection distance, no gain) and E (old PR never fired) removed.
# =============================================================================
EXPERIMENTS = [

    # ─── GROUP A: Baseline — no TSP ──────────────────────────────────────────
    {
        "name":                 "NO_TSP",
        "enabled":              True,
        "strategy":             "NORMAL",
        "coordinated":          False,
        "coordination_algo":    "KALMAN",
        "active_intersections": None,   # no TSP — active_intersections unused
        "reward_overrides":     {},
    },

    # ─── GROUP C: Objective weight sweep (50 m detection, one Z off each) ────
    # All-equal baseline = default _WG_BASE (det=50 m, min_gain=1.5 s).
    _wg("WG_NO_Z1",  {"WOBJ_ALPHA": 0.0, "WOBJ_BETA": 0.5,  "WOBJ_GAMMA": 0.5}),
    _wg("WG_NO_Z2",  {"WOBJ_ALPHA": 0.5, "WOBJ_BETA": 0.0,  "WOBJ_GAMMA": 0.5}),
    _wg("WG_NO_Z3",  {"WOBJ_ALPHA": 0.5, "WOBJ_BETA": 0.5,  "WOBJ_GAMMA": 0.0}),
    _wg("WG_Z1ONLY", {"WOBJ_ALPHA": 1.0, "WOBJ_BETA": 0.0,  "WOBJ_GAMMA": 0.0}),  # pure pax-delay

    # ─── GROUP D: ZIG min-gain sensitivity (only param with clear effect) ─────
    # ZIG_MIN_GAIN_S is a hard gate: ZIG fires only when predicted bus saving
    # exceeds this threshold.  0.0 = fire on any positive gain (default).
    # Previous sweep showed BAL/POP/IT produced binary stochastic noise only.
    _wg("WG_HP_MG1", {"ZIG_MIN_GAIN_S": 1.0}),   # soft gate: ≥1 s bus saving required
    _wg("WG_HP_MG3", {"ZIG_MIN_GAIN_S": 3.0}),   # hard gate: ≥3 s bus saving required

    # ─── GROUP F: Offset correction sensitivity (50 m, all-equal, OC enabled) ─
    # OFFSET_CORRECTION_MODE=True adds a ZIG candidate that trims the current
    # non-bus phase to advance the bus phase when the upstream junction's
    # offset-error sample shows corridor drift (green starting too late).
    # DCTSP_OC_THRESH_S = min |offset error| (s) to act on; DCTSP_OC_MAX_ADJ_S
    # = max seconds trimmed per correction.
    _wg("WG_OC_THR2",     {"OFFSET_CORRECTION_MODE": True, "DCTSP_OC_THRESH_S": 2.0,  "DCTSP_OC_MAX_ADJ_S": 15.0}),
    _wg("WG_OC_THR5",     {"OFFSET_CORRECTION_MODE": True, "DCTSP_OC_THRESH_S": 5.0,  "DCTSP_OC_MAX_ADJ_S": 15.0}),
    _wg("WG_OC_MAXADJ10", {"OFFSET_CORRECTION_MODE": True, "DCTSP_OC_THRESH_S": 3.0,  "DCTSP_OC_MAX_ADJ_S": 10.0}),
    _wg("WG_OC_MAXADJ20", {"OFFSET_CORRECTION_MODE": True, "DCTSP_OC_THRESH_S": 3.0,  "DCTSP_OC_MAX_ADJ_S": 20.0}),

    # ─── GROUP G: min-gain fine sweep + stacked best ──────────────────────────
    # WG_HP_MG1 (ZIG_MIN_GAIN_S=1.0, Group D) beat every other config in this
    # whole sweep simultaneously on objective, bus pax delay, AND bus-count
    # recovery — fine-sweep around it to find the true optimum, and test
    # stacking it with PR/OC (each only validated so far against the weaker
    # MIN_GAIN_S=0.0 baseline).
    _wg("WG_MG_0_5", {"ZIG_MIN_GAIN_S": 0.5}),
    _wg("WG_MG_1_5", {"ZIG_MIN_GAIN_S": 1.5}),
    _wg("WG_MG_2_0", {"ZIG_MIN_GAIN_S": 2.0}),
    _wg("WG_BEST_STACK", {
        "ZIG_MIN_GAIN_S":            1.0,
        "PHASE_ROTATION_MODE":       True,
        "PHASE_ROTATION_N_SEQS":     3.0,
        "PHASE_ROTATION_THRESHOLD_S": 5.0,
        "OFFSET_CORRECTION_MODE":    True,
        "DCTSP_OC_THRESH_S":         3.0,
        "DCTSP_OC_MAX_ADJ_S":        15.0,
    }),
]

# Multi-seed replication for statistical robustness
SEEDS          = [300, 42, 12345, 7, 99]
DEMAND_SCALARS = [1.0]
SCALE_TRUCKS   = True

# Separate output CSV so results don't pollute the main batch
BATCH_RESULTS_CSV = _os.path.join(_SCRIPT_DIR, "batch_results_wavegate.csv")
CORE_OUTPUT_PATH  = _os.path.join(_SCRIPT_DIR, "core_output_wavegate.csv")

TARGET_DEMAND_NAMES = ["01d Logan Rd 2025 AM", "01d Logan Rd 2025 PM"]

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

log                            = _br.log
set_control_mode               = _br.set_control_mode
set_coordinated                = _br.set_coordinated
set_coordination_algo          = _br.set_coordination_algo
set_seed                       = _br.set_seed
set_reward_weights             = _br.set_reward_weights
write_run_config               = _br.write_run_config
collect_run_metrics            = _br.collect_run_metrics
append_master_csv              = _br.append_master_csv
write_core_output               = _br.write_core_output
get_first_replication          = _br.get_first_replication
run_replication                = _br.run_replication
_purge_pyc                     = _br._purge_pyc
set_demand_scalar              = _br.set_demand_scalar
set_junctions_external_control = _br.set_junctions_external_control

CONTROLLER_PATH  = _br.CONTROLLER_PATH
RUN_CONFIG_PATH  = _br.RUN_CONFIG_PATH
PROJECT_DIR      = _br.PROJECT_DIR

# =============================================================================
# ── Main sweep loop ───────────────────────────────────────────────────────────
# =============================================================================
if __name__ == "__main__":
    # Auto-delete previous results so fresh runs aren't contaminated by old data
    if _os.path.isfile(BATCH_RESULTS_CSV):
        _os.remove(BATCH_RESULTS_CSV)
        print(f"[WG] Deleted previous results: {_os.path.basename(BATCH_RESULTS_CSV)}")

    # Enable runner logging — wavegate is a short diagnostic sweep, not a
    # 55-run production batch, so we want full visibility.
    _br._QUIET = False

    # Resolve runtime project dir (confirms Aimsun model is open) and update
    # the path constants imported from batch_runner so all helpers use the
    # correct location even if the model dir differs from the script dir.
    try:
        _rt_proj = _br.get_project_dir()
        CONTROLLER_PATH = _os.path.join(_rt_proj, "intersection_controller.py")
        RUN_CONFIG_PATH = _os.path.join(_rt_proj, "run_config.py")
        PROJECT_DIR     = _rt_proj
        # Reflect back into the imported module so shared helpers pick them up
        _br.CONTROLLER_PATH = CONTROLLER_PATH
        _br.RUN_CONFIG_PATH = RUN_CONFIG_PATH
        _br.PROJECT_DIR     = PROJECT_DIR
        print(f"[WG] Project dir: {PROJECT_DIR}")
        print(f"[WG] Controller : {CONTROLLER_PATH}")
        print(f"[WG] Run config : {RUN_CONFIG_PATH}")
    except Exception as _e:
        print(f"[WG] WARNING: could not resolve project dir from model: {_e} — using script dir")
        print(f"[WG] CONTROLLER_PATH={CONTROLLER_PATH}")
        print(f"[WG] RUN_CONFIG_PATH={RUN_CONFIG_PATH}")

    enabled = [e for e in EXPERIMENTS if e.get("enabled", True)]
    n_total = len(enabled) * len(SEEDS) * len(DEMAND_SCALARS)

    log("=" * 68)
    log("BATCH_RUNNER_WAVEGATE — WaveGate sensitivity sweep (Groups A–G)")
    log(f"  {len(enabled)} experiments  x  {len(SEEDS)} seed(s)  =  {n_total} runs total")
    log(f"  Base: ZIG_BALANCE_FACTOR=1.0 | NETWORK_FACTOR=1.0 | det=50m | min_gain=1.5s | Z1=Z2=Z3=1/3")
    log(f"  Groups: A=NO_TSP  C=ObjWeight  D=MinGain  F=OffsetCorrection  G=MinGainFine+Stack")
    log(f"  Active jcts: {_ACTIVE_JCTS_LIST}  (passive jcts excluded)")
    log(f"  Results -> {BATCH_RESULTS_CSV}")
    log("Experiments:")
    _grp_labels = {
        "NO_TSP":      "A",
        "WG_NO_Z1":    "C", "WG_NO_Z2":    "C", "WG_NO_Z3":   "C", "WG_Z1ONLY": "C",
        "WG_HP_MG1":   "D", "WG_HP_MG3":   "D",
        "WG_OC_THR2":  "F", "WG_OC_THR5":  "F",
        "WG_OC_MAXADJ10": "F", "WG_OC_MAXADJ20": "F",
        "WG_MG_0_5":   "G", "WG_MG_1_5":   "G", "WG_MG_2_0": "G",
        "WG_BEST_STACK": "G",
    }
    for i, e in enumerate(enabled, 1):
        grp = _grp_labels.get(e["name"], "?")
        log(f"  [{i:>2}/{len(enabled)}] Group {grp}  {e['name']}")
    log("=" * 68)

    rep          = get_first_replication()
    run_num      = 0
    failures     = []
    base_demands = {}  # persists across scalars to prevent factor compounding

    # Passive junctions were removed from intersection_configs.py — nothing
    # to promote to External control any more.

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
            is_baseline      = (strategy == "NORMAL")   # NO_TSP — no reward patching
            bus_predictor    = str(reward_overrides.get("BUS_PREDICTOR_TYPE",
                                                        "ADAPTIVE_KALMAN")).upper()

            try:
                set_control_mode(strategy, CONTROLLER_PATH,
                                 exp.get("active_intersections"))
            except Exception as e:
                print(f"[WG] FATAL: cannot patch strategy for {exp_name}: {e}")
                for seed in SEEDS:
                    failures.append({"experiment": exp_name, "seed": seed, "error": str(e)})
                continue

            try:
                set_coordinated(CONTROLLER_PATH, coordinated)
                set_coordination_algo(CONTROLLER_PATH, coord_algo)
            except Exception as e:
                print(f"[WG] WARNING: coord patch for {exp_name}: {e}")

            _global_reward = bool(reward_overrides.get("GLOBAL_REWARD_MODE", False))
            _numeric_ov    = {k: v for k, v in reward_overrides.items()
                              if k != "GLOBAL_REWARD_MODE"}

            # Build run_config defaults then overlay experiment-specific overrides.
            # For NO_TSP we still write run_config (records metadata) but leave
            # reward_cfg=None so no reward flags are emitted.
            _run_cfg = None if is_baseline else {
                "REWARD_INV_DELAY_MODE":              False,
                "REWARD_V2X_MODE":                    False,
                "REWARD_SELFORG_MODE":                False,
                "DCTSP_ZIG_MODE":                     True,
                "MP_ECTM_MODE":                       False,
                "BXT_MODE":                           False,
                "BARGAIN_SPM_MODE":                   False,
                "HS_EXT_MODE":                        False,
                "META_TSP_MODE":                      False,
                "MDN_DELAY_MODE":                     False,
                "REWARD_MAIN_SECTION_WEIGHT":         1.0,
                "REWARD_SIDE_SECTION_WEIGHT":         0.50,
                "WOBJ_ALPHA":                         round(1/3, 6),
                "WOBJ_BETA":                          round(1/3, 6),
                "WOBJ_GAMMA":                         round(1/3, 6),
                "DETECTION_PROB":                     1.0,
                "BUS_OCC_OVERRIDE":                   None,
                "CAR_OCC_OVERRIDE":                   None,
                "DETECTION_WINDOW_M_OVERRIDE":        40.0,
                "NETWORK_FACTOR":                     1.0,
                "NETWORK_FACTOR_DENSITY_RAMP":        False,
                "REWARD_FUTURE_HORIZON_CYCLES":       1.0,
                "TSP_CYCLE_LENGTH_OVERRIDE_S":        10.0,
                # Group G defaults (overridden per-experiment)
                "GREEN_REALLOC_RECOVER_FRACTION":     1.0,
                "DCTSP_CONGESTION_GATE":              False,
                "DCTSP_CONGESTION_GATE_FRACTION":     0.85,
            }
            if _run_cfg is not None:
                _run_cfg.update(_numeric_ov)

            if not is_baseline:
                try:
                    set_reward_weights(CONTROLLER_PATH, _numeric_ov or None)
                except Exception as e:
                    log(f"WARNING: reward patch: {e}")

            for seed in SEEDS:
                run_num += 1
                alpha = (_run_cfg or {}).get("WOBJ_ALPHA", 0.0)
                beta  = (_run_cfg or {}).get("WOBJ_BETA",  0.0)
                gamma = (_run_cfg or {}).get("WOBJ_GAMMA", 0.0)
                det_m = (_run_cfg or {}).get("DETECTION_WINDOW_M_OVERRIDE", None)

                print("-" * 68)
                print(f"[WG] Run {run_num}/{n_total} | {exp_name} | seed={seed} "
                      + (f"| Z1={alpha:.3f} Z2={beta:.3f} Z3={gamma:.3f} "
                         f"| det={det_m}m" if not is_baseline else "| NO_TSP baseline"))

                set_seed(rep, seed)
                # For NO_TSP, write a minimal run_config with just the detection
                # window so bus-approach counts are comparable to WG runs (40 m).
                # TSP is still disabled via strategy="NORMAL" — this only ensures
                # the controller uses the same detection radius for logging.
                _run_cfg_write = ({"DETECTION_WINDOW_M_OVERRIDE": 40.0}
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
                    failures.append({"experiment": exp_name, "seed": seed, "error": str(e)})
                    print(f"[WG]   EXCEPTION during simulation: {e}")

                elapsed = _time.time() - t0
                print(f"[WG]   elapsed={elapsed:.0f}s  success={success}")
                print(f"[WG] Job {run_num}/{n_total} done, {n_total - run_num} to go")
                try:
                    metrics = collect_run_metrics(
                        PROJECT_DIR, strategy, seed, scalar,
                        exp_name, coordinated, elapsed, success,
                        bus_predictor=bus_predictor)
                    # Annotate sweep dimensions for dashboard analysis
                    _rc = _run_cfg or {}
                    metrics["sweep_group"]             = _grp_labels.get(exp_name, "?")
                    metrics["sweep_Z1_weight"]         = alpha
                    metrics["sweep_Z2_weight"]         = beta
                    metrics["sweep_Z3_weight"]         = gamma
                    metrics["sweep_detection_m"]       = det_m if det_m is not None else 40.0
                    metrics["sweep_min_gain_s"]        = _rc.get("ZIG_MIN_GAIN_S", None)
                    metrics["sweep_active_jcts"]       = len(_ACTIVE_JCTS_LIST) if _ACTIVE_JCTS_LIST else None
                    metrics["sweep_phase_rot_enabled"] = bool(_rc.get("PHASE_ROTATION_MODE", False))
                    metrics["sweep_phase_rot_n_seqs"]  = _rc.get("PHASE_ROTATION_N_SEQS", None)
                    metrics["sweep_phase_rot_thr_s"]   = _rc.get("PHASE_ROTATION_THRESHOLD_S", None)
                    metrics["sweep_offset_corr_enabled"] = bool(_rc.get("OFFSET_CORRECTION_MODE", False))
                    metrics["sweep_offset_corr_thresh_s"] = _rc.get("DCTSP_OC_THRESH_S", None)
                    metrics["sweep_offset_corr_max_adj_s"] = _rc.get("DCTSP_OC_MAX_ADJ_S", None)
                    append_master_csv(BATCH_RESULTS_CSV, metrics)
                    write_core_output(CORE_OUTPUT_PATH, metrics, reward_overrides)
                    print(f"[WG]   delay={metrics.get('stats_TotalPassDelay_hrs','?')}h  "
                          f"written -> {_os.path.basename(BATCH_RESULTS_CSV)}")
                except Exception as e:
                    print(f"[WG]   ERROR collecting metrics: {e}")
                    failures.append({"experiment": exp_name, "seed": seed, "error": str(e)})

    _wg_html = _os.path.join(_SCRIPT_DIR, "wavegate_dashboard.html")
    _gen_py  = _os.path.join(_SCRIPT_DIR, "generate_dashboard.py")
    print("=" * 68)
    print(f"[WG] WaveGate sweep complete: {run_num} runs, {len(failures)} failures")
    if failures:
        for f in failures:
            print(f"[WG]   FAILED: {f}")
    print(f"[WG] Results CSV : {BATCH_RESULTS_CSV}")
    print(f"[WG] Generating dashboard -> {_wg_html} ...")
    try:
        import importlib.util as _ilu2
        _gd_spec = _ilu2.spec_from_file_location("generate_dashboard", _gen_py)
        _gd      = _ilu2.module_from_spec(_gd_spec)
        _gd_spec.loader.exec_module(_gd)
        _gd.generate(BATCH_RESULTS_CSV, _wg_html)
        print(f"[WG] Dashboard written -> {_wg_html}")
    except Exception as _dash_err:
        print(f"[WG] Dashboard generation failed: {_dash_err}")
        print(f"[WG] Run manually: python3.12 \"{_gen_py}\" \"{BATCH_RESULTS_CSV}\" \"{_wg_html}\"")
    print("=" * 68)
