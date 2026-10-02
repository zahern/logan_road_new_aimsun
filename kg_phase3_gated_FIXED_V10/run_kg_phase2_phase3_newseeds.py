"""
run_kg_phase2_phase3_newseeds.py -- KG Phase 2 (champion re-validation) + Phase 3, sequential.

Phase 2: CELLQLEARN_GATED (the gated KG champion from phase3_base_kg.json)
         + NO_TSP baseline, at x1.0 demand, on 5 FRESH seeds.
         Learners train on the classic TRAIN_SEEDS first (Q accumulates
         in-session, nothing scored), then KEEP LEARNING through the 5 fresh
         scored seeds -- they are deliberately NOT frozen. Writes
         champion_kg_newseeds.csv.
Phase 3: full demand-sensitivity factorial (3 tactics x 3 freq x 6 demands
         x 5 seeds + 30 NO_TSP + 4-seed train prologue) on 5 FRESH seeds.
         Writes phase3_sensitivity_kg_newseeds.csv.

Fresh seeds are disjoint from every old seed:
  old eval  = 300, 400, 500, 600, 700
  old train = 800, 900, 1000, 1100
  Phase 2   = 1200, 1300, 1400, 1500, 1600
  Phase 3   = 2000, 2100, 2200, 2300, 2400

HOW TO RUN (Aimsun, KG model open):
  run_kg_phase2_phase3_newseeds.py
  -> runs Phase 2 (~14 runs), then Phase 3 (~304 runs), resume-safe.
  Re-execute after any restart: done rows are skipped, nothing is wiped.

Outputs:
  champion_kg_newseeds.csv
  phase3_sensitivity_kg_newseeds.csv
"""

import os as _os
import sys as _sys
import importlib.util as _ilu


# ── Fresh seed sets (disjoint from 300-700 eval and 800-1100 train) ──────────
PHASE2_SEEDS = [1200, 1300, 1400, 1500, 1600]
PHASE3_SEEDS = [2000, 2100, 2200, 2300, 2400]

PHASE2_ARMS = ("CELLQLEARN_GATED", "NO_TSP")


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


def _load(_name, _path):
    _spec = _ilu.spec_from_file_location(_name, _path)
    _mod = _ilu.module_from_spec(_spec)
    _sys.modules[_name] = _mod
    try:
        _spec.loader.exec_module(_mod)
    except SystemExit:
        pass
    return _mod


_cs = _load("_cs_ns", _os.path.join(_ROOT, "champion_search.py"))
_p3 = _load("_p3_ns", _os.path.join(_ROOT, "phase3_sensitivity.py"))

CORRIDOR = getattr(_cs, "CORRIDOR", getattr(_p3, "CORRIDOR", "kg"))


def run_phase2(quick=False):
    seeds = [1200, 1300] if quick else list(PHASE2_SEEDS)
    _cs.EVAL_SEEDS = list(seeds)  # main() reads this global at call time
    _arms = [a for a in _cs.ARMS if a.get("name") in PHASE2_ARMS]
    _names = {a.get("name") for a in _arms}
    _missing = set(PHASE2_ARMS) - _names
    if _missing:
        raise RuntimeError(f"Phase 2 arms missing from champion_search.ARMS: {_missing}")
    _out = _os.path.join(_ROOT, f"champion_{CORRIDOR}_newseeds.csv")
    print(f"[P2+P3] Phase 2: {sorted(_names)} x seeds={seeds} -> {_out}")
    _cs.main(arms=_arms, results_csv=_out, resume=True)
    return _out


def run_phase3(quick=False):
    _p3.SEEDS = list(_p3.SEEDS) if quick else list(PHASE3_SEEDS)
    _p3.RESULTS_CSV = _os.path.join(_ROOT, f"phase3_sensitivity_{CORRIDOR}_newseeds.csv")
    print(f"[P2+P3] Phase 3: base={_p3.BASE['name']} x seeds={list(_p3.SEEDS)} "
          f"-> {_p3.RESULTS_CSV}")
    _p3.main(quick=quick, resume=True)
    return _p3.RESULTS_CSV


def main(quick=False, phase2_only=False, phase3_only=False):
    print("=" * 70)
    print(f"[P2+P3] SEQUENTIAL -- corridor={CORRIDOR} | "
          f"Phase2 seeds={PHASE2_SEEDS} | Phase3 seeds={PHASE3_SEEDS}")
    print("=" * 70)
    if not phase3_only:
        run_phase2(quick=quick)
    if not phase2_only:
        run_phase3(quick=quick)
    print("=" * 70)
    print("[P2+P3] DONE")
    print("=" * 70)


if __name__ == "__main__":
    # Same Aimsun-safe launch as phase3_sensitivity (FIX 2026-09-25): never
    # gate on sys.argv[0] -- inside Aimsun it is the Aimsun exe, not this file.
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--quick", action="store_true",
                     help="smoke test: 2 seeds per phase only")
    _ap.add_argument("--phase2-only", action="store_true",
                     help="run Phase 2 only")
    _ap.add_argument("--phase3-only", action="store_true",
                     help="run Phase 3 only")
    try:
        _a, _ = _ap.parse_known_args()
    except SystemExit:
        _a = None
    if _a is None:
        main()
    else:
        main(quick=_a.quick, phase2_only=_a.phase2_only, phase3_only=_a.phase3_only)
else:
    print("run_kg_phase2_phase3_newseeds imported; run "
          "run_kg_phase2_phase3_newseeds.main() to start.")
