"""
champion_resume.py -- Resume an interrupted Phase-1 champion search and carry on
through Phase 2 (champion pick) and Phase 3 (sensitivity), for whichever corridor
model is open.

WHY THIS EXISTS (and why plain `run_champion_pipeline.py --resume` is NOT enough
for a crash mid-search):
  champion_search's built-in resume skips per (arm, seed) that is already banked
  as run_success. That is CORRECT for the analytic arms, but WRONG for a LEARNER
  arm (CELLQLEARN*, DCTSP_MARL_RL) that was only PARTIALLY finished when the crash
  hit. The BXT/CPDQL Q-table (`_dctsp_bxt_q_table`) is an IN-MEMORY module global
  -- it is NOT persisted to disk. After a machine restart the Q-table is empty, so
  the learner must re-TRAIN on its TRAIN_SEEDS (in this fresh session) BEFORE its
  EVAL_SEEDS are scored. A seed-level resume that skipped the banked train seeds
  would evaluate the learner against an EMPTY Q -> degenerate all-NO_ACTION rows
  (cold start), inconsistent with its already-banked warm eval-300 row, poisoning
  the champion comparison.

WHAT THIS DOES INSTEAD (ARM-LEVEL resume):
  * An arm is "complete" only if EVERY seed it needs is banked as run_success
      - learners  : TRAIN_SEEDS + EVAL_SEEDS
      - all others : EVAL_SEEDS
  * Complete arms are kept as-is and skipped.
  * Any INCOMPLETE arm (the learner that died mid-run, plus every arm that never
    started) is re-run IN FULL. A partially-done learner therefore re-trains then
    re-evals warm, in one session -- consistent and valid.
  * The incomplete arms' stale partial rows are PRUNED from the CSV first (a .bak
    backup is written) so the re-run yields exactly one clean row-set per arm and
    the ranker cannot double-count a seed.

Then it mirrors run_champion_pipeline exactly: Phase 2 picks the champion off the
now-complete champion_<corridor>.csv, and Phase 3 runs the sensitivity sweep with
that champion as BASE.

PREREQUISITES (same as any batch run):
  * The intended corridor model is OPEN in Aimsun (Logan or KG). The corridor is
    auto-detected + guarded by champion_search; a stale lock cannot mis-route it.
  * Aimsun was FULLY restarted since the crash (engine/controller are cached once
    per session) -- confirm ENGINE_BUILD on the [LOAD] line as usual.

HOW TO RUN (from the Aimsun Python console, corridor model open):
    champion_resume.py                 # finish Phase 1, then Phase 2 + Phase 3
    champion_resume.py --phase1-only   # only finish the champion search
    champion_resume.py --phase3-quick  # Phase 3 runs its quick smoke matrix
    champion_resume.py --dry-run       # print the resume plan and exit (no runs)
    champion_resume.py --no-prune      # keep partial rows (NOT recommended)
"""

import csv as _csv
import importlib.util as _ilu
import os as _os
import shutil as _shutil
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
            model_dir = GKSystem.getSystem().getActiveModel() \
                .getDocumentDirectory().absolutePath()
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
        "champion_resume.py: cannot find champion_search.py. Open the corridor "
        f"model in Aimsun and run from the canonical bundle. Searched {candidates!r}.")


_HERE = _find_bundle_dir()
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

# ── Cache-buster (mirror run_champion_pipeline EXACTLY) ───────────────────────
# Drop the phase modules + champion_search's private batch-runner handle so the
# edited runner/config are re-read from disk. CRITICAL: do NOT pop 'batch_runner'
# -- popping the literal module splits the runner into two instances and breaks
# per-sim completion detection (every run then times out at 30 min with blank
# rows). champion_search loads the runner under the name '_br_champ'; popping
# that (as run_champion_pipeline does) is the safe cache-bust. The ENGINE and
# CONTROLLER are imported once per Aimsun SESSION -- they still need a full
# Aimsun restart to pick up edits (assumed already done after the crash).
for _mn in ("champion_search", "_br_champ", "champion_bus_demand",
            "phase3_sensitivity", "_pipeline_phase1", "_pipeline_phase2",
            "_pipeline_phase3", "_resume_phase1", "_resume_phase2",
            "_resume_phase3"):
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


def _required_seeds(cs, arm_name):
    """The seed set an arm must have banked to count as complete."""
    seeds = set(int(s) for s in cs.EVAL_SEEDS)
    if arm_name in cs.LEARNING_ARMS:
        seeds |= set(int(s) for s in cs.TRAIN_SEEDS)
    return seeds


def _banked_success_seeds(results_csv):
    """{arm_name: set(int seed)} of run_success rows already in the CSV."""
    done = {}
    if not _os.path.isfile(results_csv):
        return done
    with open(results_csv, newline='', encoding='utf-8-sig') as fh:
        for r in _csv.DictReader(fh):
            if str(r.get("run_success", "")).strip().lower() not in (
                    "true", "1", "yes"):
                continue
            name = str(r.get("run_experiment", "")).strip()
            seed_raw = str(r.get("run_seed", "")).split(".")[0].strip()
            if not name or not seed_raw:
                continue
            try:
                done.setdefault(name, set()).add(int(seed_raw))
            except ValueError:
                pass
    return done


def _prune_csv(results_csv, drop_names, log):
    """Rewrite the CSV keeping every row whose arm is NOT in drop_names. A .bak
    backup is written first. Preserves the existing header/column order."""
    if not drop_names or not _os.path.isfile(results_csv):
        return 0
    with open(results_csv, newline='', encoding='utf-8-sig') as fh:
        reader = _csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    keep = [r for r in rows if str(r.get("run_experiment", "")).strip()
            not in drop_names]
    dropped = len(rows) - len(keep)
    if dropped == 0:
        return 0
    bak = results_csv + ".bak"
    try:
        _shutil.copyfile(results_csv, bak)
        log(f"RESUME: backed up {_os.path.basename(results_csv)} -> "
            f"{_os.path.basename(bak)} before pruning")
    except Exception as e:
        log(f"RESUME: WARNING could not write backup ({e}); proceeding")
    with open(results_csv, "w", newline='', encoding='utf-8') as fh:
        w = _csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore",
                            restval="")
        w.writeheader()
        w.writerows(keep)
    log(f"RESUME: pruned {dropped} stale partial row(s) for arms "
        f"{sorted(drop_names)}; kept {len(keep)} complete-arm row(s)")
    return dropped


def _phase1_arm(phase2_module, champion_name):
    for arm in phase2_module._cs.ARMS:
        if arm.get("name") == champion_name:
            return {**arm,
                    "reward_overrides": dict(arm.get("reward_overrides", {}) or {})}
    raise RuntimeError(
        f"Champion {champion_name!r} is not present in champion_search.ARMS; "
        "Phase 3 cannot reproduce its controller configuration.")


def main(phase1_only=False, phase3_quick=False, do_prune=True, dry_run=False):
    phase1 = _load_script("_resume_phase1", "champion_search.py")
    log = phase1._br.log
    corridor = phase1.CORRIDOR
    results_csv = phase1.RESULTS_CSV
    parked = set(getattr(phase1, "PARKED_ARMS", set()))

    log("=" * 70)
    log(f"CHAMPION RESUME -- corridor={corridor}")
    log(f"  CSV: {results_csv}")
    log("=" * 70)

    banked = _banked_success_seeds(results_csv)

    complete, incomplete, remaining_arms = [], [], []
    for arm in phase1.ARMS:
        name = arm["name"]
        if name in parked:
            continue                              # never runs; not required
        need = _required_seeds(phase1, name)
        have = banked.get(name, set())
        missing = sorted(need - have)
        if missing:
            incomplete.append((name, missing))
            remaining_arms.append(arm)
        else:
            complete.append(name)

    log(f"COMPLETE arms ({len(complete)}) -- kept, skipped:")
    for n in complete:
        log(f"    OK   {n}")
    log(f"INCOMPLETE arms ({len(incomplete)}) -- will RE-RUN IN FULL:")
    for n, missing in incomplete:
        tag = " (LEARNER: retrains then evals warm)" \
            if n in phase1.LEARNING_ARMS else ""
        log(f"    RUN  {n:20s} missing seeds {missing}{tag}")
    if parked:
        log(f"PARKED arms (not required): {sorted(parked)}")

    if not remaining_arms:
        log("RESUME: Phase 1 is already COMPLETE -- nothing to re-run.")
    else:
        drop = {n for n, _ in incomplete}
        if dry_run:
            log(f"DRY-RUN: would prune partial rows for {sorted(drop)} and "
                f"re-run {len(remaining_arms)} arm(s). No runs executed.")
            return
        if do_prune:
            _prune_csv(results_csv, drop, log)
        else:
            log("RESUME: --no-prune set; partial rows kept (ranker may "
                "double-count a re-run seed).")
        log(f"[RESUME] Re-running {len(remaining_arms)} arm(s) to finish Phase 1")
        # resume=True => keep the (pruned) CSV and APPEND. The remaining arms
        # are no longer in the CSV, so nothing spurious is skipped and each
        # re-runs in full (learners train->eval in this session).
        phase1.main(arms=remaining_arms, results_csv=results_csv, resume=True)

    if dry_run:
        return
    if phase1_only:
        log("RESUME: --phase1-only set; stopping after champion search. Run "
            "run_champion_pipeline.py (or this without --phase1-only) for "
            "Phase 2 + Phase 3.")
        return

    # ── Phase 2: pick the champion off the now-complete CSV ───────────────────
    phase2 = _load_script("_resume_phase2", "champion_bus_demand.py")
    champion_name, selection_note = phase2._pick_champion()
    if not champion_name:
        raise RuntimeError(
            "Phase 1 finished but no champion is selectable: "
            f"{selection_note}. Phase 2/3 not started -- inspect the champion "
            "CSV / [SANITY] warnings.")
    champion_arm = _phase1_arm(phase2, champion_name)
    log(f"[RESUME] Champion selected: {champion_name} ({selection_note})")

    log("[RESUME] Starting Phase 2 bus-demand sensitivity")
    phase2.main()

    # ── Phase 3: sensitivity sweep with the champion as BASE ──────────────────
    phase3 = _load_script("_resume_phase3", "phase3_sensitivity.py")
    phase3.BASE = champion_arm
    log(f"[RESUME] Starting Phase 3 sensitivity with BASE={champion_name} "
        f"({'quick' if phase3_quick else 'full'})")
    phase3.main(quick=phase3_quick)

    try:
        _brp = getattr(phase3, "_br", None) or phase1._br
        if _brp is not None:
            _brp._set_logging(_brp.CONTROLLER_PATH, enabled=False)
            log("[RESUME] Console logging left DISABLED (pipeline complete).")
    except Exception as e:
        log(f"[RESUME] WARNING: could not disable console logging: {e}")

    log("=" * 70)
    log(f"[RESUME] Complete for corridor={corridor}")
    log(f"  Phase 1: {_os.path.join(_HERE, f'champion_{corridor}.csv')}")
    log(f"  Phase 2: {_os.path.join(_HERE, f'champion_bus_demand_{corridor}.csv')}")
    log(f"  Phase 3: {_os.path.join(_HERE, f'phase3_sensitivity_{corridor}.csv')}")
    log("=" * 70)


# ── Entry point ───────────────────────────────────────────────────────────────
# NO ARGUMENTS NEEDED. Executing this file bare (e.g. from the Aimsun Python
# console) runs the FULL continue: finish Phase 1's missing/incomplete arms ->
# pick the champion (Phase 2) -> Phase 3 sensitivity. Flags are optional and read
# by simple membership on sys.argv (not argparse), so a no-arg console execution
# can never trip an argument parser:
#   add "--dry-run"     to just PRINT the resume plan and stop (no sims)
#   add "--phase1-only" to stop after the champion search (skip Phase 2/3)
#   add "--phase3-quick" for Phase 3's quick smoke matrix instead of the full one
#   add "--no-prune"    to keep partial rows (NOT recommended)
if __name__ == "__main__":
    _argv = _sys.argv[1:] if len(_sys.argv) > 1 else []
    main(phase1_only=("--phase1-only" in _argv),
         phase3_quick=("--phase3-quick" in _argv),
         do_prune=("--no-prune" not in _argv),
         dry_run=("--dry-run" in _argv))
