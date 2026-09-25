#!/usr/bin/env python3
"""run_probe.py -- one-line vehicle/API probe for the active corridor.

Run from the Aimsun Python console with the corridor model open (single line,
no multi-line paste):
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_probe.py").read())

Detects the active corridor from model lock files (same convention as the
pipeline), imports that corridor's batch_runner, and runs probe_vehicle_types().
"""
import os as _os
import sys as _sys
import glob as _glob

_HERE = _os.path.dirname(_os.path.abspath(__file__)) \
    if "__file__" in dir() else _os.getcwd()

# exec(open(...).read()) never sets __file__, so the bundle path is fixed
# explicitly (same convention as test_demand_direct_multiply.py).
_BUNDLE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"


def _detect_corr_dir():
    # 1. Authoritative: the open model's own directory (no lock files needed).
    try:
        from PyANGKernel import GKSystem
        _m = GKSystem.getSystem().getActiveModel()
        _dd = ""
        if _m is not None:
            try:
                _dd = str(_m.getDocumentDirectory().absolutePath())
            except Exception:
                try:
                    _dd = _os.path.dirname(str(_m.getDocumentFileName()))
                except Exception:
                    _dd = ""
        _base = _os.path.basename(_dd.rstrip("/\\")).lower()
        if _base in ("kg", "logan_road_new"):
            _cand = _os.path.join(_BUNDLE, _base)
            if _os.path.isfile(_os.path.join(_cand, "batch_runner.py")):
                return _cand
            if _os.path.isfile(_os.path.join(_dd, "batch_runner.py")):
                return _dd
    except Exception:
        pass
    # 2. Fallback: lock files under the bundle root, then the cwd.
    for _root in (_BUNDLE, _os.getcwd()):
        _cands = []
        for _c in ("kg", "logan_road_new"):
            _d = _os.path.join(_root, _c)
            _locks = _glob.glob(_os.path.join(_d, "*.ang.lck")) + \
                _glob.glob(_os.path.join(_d, "*.sang.lck"))
            if _locks:
                _cands.append((_d, max(_os.path.getmtime(_p) for _p in _locks)))
        if _cands:
            _cands.sort(key=lambda _t: -_t[1])
            return _cands[0][0]
    raise RuntimeError("Open the corridor model in Aimsun first (no open "
                       "model found and no *.ang.lck under kg/ or logan_road_new/).")


_CORR = _detect_corr_dir()
if _CORR not in _sys.path:
    _sys.path.insert(0, _CORR)
# Fresh import (console may hold a stale module from an earlier paste).
if "batch_runner" in _sys.modules:
    del _sys.modules["batch_runner"]
import batch_runner as _br

print("[RUNPROBE] corridor dir: " + _CORR)
print("[RUNNER] Using batch_runner from: " + _br.__file__)
_br.probe_vehicle_types()
