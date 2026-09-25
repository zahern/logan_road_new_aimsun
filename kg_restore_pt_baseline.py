"""
kg_restore_pt_baseline.py -- undo a baked-in bus-demand scaling (KG model).

WHY THIS EXISTS (2026-08-25)
----------------------------
The bus-demand sweep scales PT departures in-memory; its old finally-restore
called scalar=1.0, which is a deliberate NO-OP in set_bus_headway_scalar, so
the x3 scaling was never undone and got saved into the .ang. Proof: all five
per-seed objectives of phase3 BOTH/X1 matched champion_bus_demand BUSx3
exactly (155.42 / 147.945 / 151.26 / 150.368 / 138.234).

This script applies the INVERSE (headways x3 == scalar 1/3) with a fresh
cache, so timetables return to the true 1x baseline.

RUN inside Aimsun, KG model open:
      kg_restore_pt_baseline.py

THEN (in this order):
      1. Save the model (File > Save)  <-- without saving, nothing persists
      2. Run one NO_TSP replication as verification:
           objective ~133.5  = restored to true 1x   (good)
           objective ~148.7  = still at 3x           (call Zeke)
"""
import os as _os
import sys as _sys
import importlib.util as _ilu

try:
    _HERE = _os.path.dirname(_os.path.abspath(__file__))
except NameError:
    from PyANGKernel import GKSystem
    _HERE = _os.path.dirname(
        GKSystem.getSystem().getActiveModel().getDocumentFileName())

_bd_path = _os.path.join(_HERE, "batch_runner_bus_demand.py")
_spec = _ilu.spec_from_file_location("_bd_restore", _bd_path)
_bd = _ilu.module_from_spec(_spec)
_sys.modules["_bd_restore"] = _bd
try:
    _spec.loader.exec_module(_bd)
except SystemExit:
    pass

# Timetables are currently at demand x3 => headways were divided by 3.
# set_bus_headway_scalar divides headway by the scalar, so applying 1/3
# multiplies headways back by 3 == original.
INVERSE = 1.0 / 3.0

print("[RESTORE] KG PT timetable restore: applying inverse of BUSx3 "
      "(scalar=%s) ..." % repr(INVERSE))
_n = _bd.set_bus_headway_scalar(INVERSE, {})
print("[RESTORE] schedules rewritten: %s" % _n)
print("[RESTORE] NOW: 1) File > Save the model   2) run one NO_TSP check")
print("[RESTORE] expected objective ~133.5 at true 1x (148.65 = still 3x).")
