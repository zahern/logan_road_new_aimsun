"""run_champion_pipeline_quick.py -- QUICK smoke run of the champion pipeline.

Runs every arm on a SINGLE eval seed (300) with NO pre-training, so you get a
full 13-arm comparison fast instead of 5 eval seeds + 4 train seeds per arm.
Phase 2 keeps 3 bus-demand levels and Phase 3 runs its quick matrix.

Run it in the Aimsun Python console with one corridor model open:
    run_champion_pipeline_quick.py

Equivalent to `run_champion_pipeline.py --smoke`, but takes no CLI args (Aimsun's
console can't pass them). To go back to the full 5-seed run, use
run_champion_pipeline.py instead.

NOTE: each replication is still the full ~1.5 h SIM. This only cuts how MANY
runs happen (13 instead of ~90+). Learning arms run UNTRAINED in smoke, so only
the heuristic arms (DCTSP_MARL, NASH_BARGAIN, ...) are representative here.
"""
import os as _os
import sys as _sys
import importlib.util as _ilu


def _find_bundle_dir():
    """Locate the bundle (dir with run_champion_pipeline.py) WITHOUT relying on
    __file__ -- Aimsun's "Python Script" object runs code with __file__ undefined
    (NameError), so fall back to the open model's directory and its parents."""
    cands = []
    try:
        cands.append(_os.path.dirname(_os.path.abspath(__file__)))
    except (NameError, TypeError):
        pass
    try:
        from PyANGKernel import GKSystem
        _md = GKSystem.getSystem().getActiveModel().getDocumentDirectory().absolutePath()
        cands += [_md, _os.path.dirname(_md), _os.path.dirname(_os.path.dirname(_md))]
    except Exception:
        pass
    cands.append(_os.getcwd())
    for c in cands:
        try:
            c = _os.path.abspath(c)
        except Exception:
            continue
        if _os.path.isfile(_os.path.join(c, "run_champion_pipeline.py")):
            return c
    raise RuntimeError(
        "run_champion_pipeline_quick.py: cannot find run_champion_pipeline.py; "
        f"searched {cands!r}. Open the corridor model in Aimsun and run from the bundle.")


_HERE = _find_bundle_dir()
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

# Fresh reload of the pipeline + every phase module it caches, so edits to
# champion_search / batch_runner load without an Aimsun restart (same reason the
# pipeline itself busts these; see run_champion_pipeline.py).
for _mn in ("run_champion_pipeline", "champion_search", "_br_champ",
            "_pipeline_phase1", "_pipeline_phase2", "_pipeline_phase3"):
    _sys.modules.pop(_mn, None)

_spec = _ilu.spec_from_file_location(
    "run_champion_pipeline", _os.path.join(_HERE, "run_champion_pipeline.py"))
_pipe = _ilu.module_from_spec(_spec)
_sys.modules["run_champion_pipeline"] = _pipe
_spec.loader.exec_module(_pipe)   # defines main(); __main__/argparse block is skipped

print("[QUICK] smoke pipeline: 1 eval seed (300), no pre-training, quick Phase 3")
_pipe.main(smoke=True)
