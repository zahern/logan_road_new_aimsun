"""
run_champion_pipeline.py -- Run Phase 1, Phase 2, and Phase 3 in sequence.

Run this from the Aimsun Python console with one corridor model open:
    run_champion_pipeline.py

The runner:
  1. Runs champion_search.py and creates champion_<corridor>.csv.
    2. Selects the best arm using Phase 2's NO_TSP-aware objective and schedule rule.
  3. Runs champion_bus_demand.py for that selected champion.
  4. Runs phase3_sensitivity.py using the selected Phase-1 arm as BASE.

Use --phase3-quick to run only the Phase-3 smoke matrix after the full
Phase-1 and Phase-2 stages have completed.
"""

import argparse
import importlib.util as _ilu
import os as _os
import sys as _sys


def _find_bundle_dir():
    candidates = []
    try:
        candidates.append(_os.path.dirname(_os.path.abspath(__file__)))
    except (NameError, TypeError):
        pass

    if not candidates or not _os.path.isfile(
            _os.path.join(candidates[0], "champion_search.py")):
        try:
            from PyANGKernel import GKSystem
            model_dir = GKSystem.getSystem().getActiveModel().getDocumentDirectory().absolutePath()
            candidates.extend((
                model_dir,
                _os.path.dirname(model_dir),
                _os.path.dirname(_os.path.dirname(model_dir)),
            ))
        except Exception:
            pass

    for candidate in candidates:
        candidate = _os.path.abspath(candidate)
        if _os.path.isfile(_os.path.join(candidate, "champion_search.py")):
            return candidate
    raise RuntimeError(
        "run_champion_pipeline.py: cannot find champion_search.py; "
        f"searched {candidates!r}. Open the corridor model in Aimsun and "
        "run this script from the canonical bundle."
    )


_HERE = _find_bundle_dir()
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

# ── Cache-buster (session-level) ──────────────────────────────────────────────
# The pipeline is ONE long-lived invocation, but a PRIOR invocation in the same
# Aimsun session leaves champion_search / _br_champ / batch_runner cached in
# sys.modules. _load_script re-execs the phase files, yet champion_bus_demand's
# `import champion_search` (and champion_search's own `_br_champ` registration)
# can still serve a STALE batch_runner -> no [TIMING], no engine-stamp guard.
# Dropping them forces every fresh pipeline run to re-read the edited runner from
# disk. NOTE: this does NOT reload the ENGINE or CONTROLLER (imported once per
# Aimsun SESSION) -- those still need a full Aimsun restart to pick up edits.
for _mn in ("champion_search", "_br_champ", "_pipeline_phase1",
            "_pipeline_phase2", "_pipeline_phase3"):
    _sys.modules.pop(_mn, None)


def _load_script(module_name, filename):
    path = _os.path.join(_HERE, filename)
    if not _os.path.isfile(path):
        raise RuntimeError(f"Required pipeline script is missing: {path}")
    spec = _ilu.spec_from_file_location(module_name, path)
    module = _ilu.module_from_spec(spec)
    _sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _phase1_arm(phase2_module, champion_name):
    for arm in phase2_module._cs.ARMS:
        if arm.get("name") == champion_name:
            return {
                **arm,
                "reward_overrides": dict(arm.get("reward_overrides", {}) or {}),
            }
    raise RuntimeError(
        f"Champion {champion_name!r} is not present in champion_search.ARMS; "
        "Phase 3 cannot reproduce its controller configuration."
    )


def _apply_smoke(phase1, phase2):
    """SMOKE: cut the RUN COUNT (not the sim length) so the pipeline exercises
    every changed behaviour -- algorithm dispatch, bus-demand scaling (<1, =1,
    >1 injection), car demand -- on the fewest replications. Phase 1 drops to a
    single eval seed and no pre-training; Phase 2 keeps one down/at/up bus-demand
    level; Phase 3 runs its quick matrix. Per-run plots are already off (see
    champion_search._disable_batch_plotting). NOTE: each replication is still the
    full 1.5 h sim -- to make each run SHORT you must lower the Aimsun experiment
    duration AND batch_runner.EXPECTED_SIM_DURATION_HRS (the truncation guard),
    which is a model-side change; this flag only reduces how MANY runs happen."""
    phase1.EVAL_SEEDS = [300]
    phase1.TRAIN_SEEDS = []
    # Learners are eval-only here (train=[]) so their Q-table is empty and a frozen
    # BXT learner does nothing (== NO_TSP). Give untrained BXT learners a
    # traditional-TSP prior so the smoke comparison is meaningful; the FULL pipeline
    # leaves this OFF so training is untouched.
    phase1.SMOKE_HEURISTIC_PRIOR = True
    print(f"[SMOKE] Phase 1: EVAL_SEEDS={phase1.EVAL_SEEDS}, TRAIN_SEEDS=[], "
          f"SMOKE_HEURISTIC_PRIOR=True (untrained BXT learners act like traditional TSP)")
    try:
        phase2.BUS_DEMAND_SCALARS = [0.5, 1.0, 2.0]
        print(f"[SMOKE] Phase 2: BUS_DEMAND_SCALARS={phase2.BUS_DEMAND_SCALARS}")
    except Exception:
        pass


def main(phase3_quick=False, smoke=False, resume=False):
    print("=" * 70)
    print("CHAMPION PIPELINE: Phase 1 -> Phase 2 -> Phase 3"
          + ("  [SMOKE]" if smoke else ""))
    print("=" * 70)

    phase1 = _load_script("_pipeline_phase1", "champion_search.py")
    phase2 = _load_script("_pipeline_phase2", "champion_bus_demand.py")
    if smoke:
        _apply_smoke(phase1, phase2)
        phase3_quick = True

    print("[PIPELINE] Starting Phase 1 champion search"
          + ("  [RESUME]" if resume else ""))
    phase1.main(resume=resume)

    champion_name, selection_note = phase2._pick_champion()
    if not champion_name:
        raise RuntimeError(
            "Phase 1 completed without a selectable champion: "
            f"{selection_note}. Phase 2 and Phase 3 were not started."
        )
    champion_arm = _phase1_arm(phase2, champion_name)
    print(f"[PIPELINE] Champion selected: {champion_name} ({selection_note})")

    print("[PIPELINE] Starting Phase 2 bus-demand sensitivity")
    phase2.main()

    phase3 = _load_script("_pipeline_phase3", "phase3_sensitivity.py")
    phase3.BASE = champion_arm
    print(
        f"[PIPELINE] Starting Phase 3 sensitivity with BASE={champion_name} "
        f"({'quick' if phase3_quick else 'full'})"
    )
    phase3.main(quick=phase3_quick)

    # Leave console logging OFF after the FINAL run. Every phase re-enables it
    # (VERBOSE=True) at its own end, so without this the Aimsun console goes
    # verbose again once the pipeline finishes. This is the authoritative last
    # word so the console stays quiet after the last run. (user-requested
    # 2026-09-07) Re-enable manually (set VERBOSE=True in the controller) or run
    # any single-arm script, which restores it.
    try:
        _brp = getattr(phase3, "_br", None) or getattr(phase1, "_br", None)
        if _brp is not None:
            _brp._set_logging(_brp.CONTROLLER_PATH, enabled=False)
            print("[PIPELINE] Console logging left DISABLED (pipeline complete).")
    except Exception as _le:
        print(f"[PIPELINE] WARNING: could not disable console logging: {_le}")

    corridor = phase1.CORRIDOR
    print("=" * 70)
    print(f"[PIPELINE] Complete for corridor={corridor}")
    print(f"  Phase 1: {_os.path.join(_HERE, f'champion_{corridor}.csv')}")
    print(f"  Phase 2: {_os.path.join(_HERE, f'champion_bus_demand_{corridor}.csv')}")
    print(f"  Phase 3: {_os.path.join(_HERE, f'phase3_sensitivity_{corridor}.csv')}")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase3-quick",
        action="store_true",
        help="run Phase 3's BOTH/X1/x1.0 two-seed smoke matrix",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="fast sweep: 1 eval seed, 3 bus-demand levels, quick Phase 3 "
             "(cuts run COUNT, not sim length). Verifies every arm's behaviour "
             "changes without the full matrix. Run pipeline_preflight.py first "
             "for the instant offline algorithm-dispatch check.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume Phase 1 from the existing champion CSV: skip (arm, seed, "
             "demand) combos already banked as successful instead of redoing "
             "completed runs. Failed rows re-run. (Phase 2/3 still rerun.)",
    )
    args = parser.parse_args()
    main(phase3_quick=args.phase3_quick, smoke=args.smoke, resume=args.resume)
