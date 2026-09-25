"""
kg_probe_pt_scaling.py -- diagnostic probe for the bus-frequency scaler.

WHY (2026-08-25): champion_bus_demand achieved only ~0.54 of the intended
frequency multiplier at every level (x1.5 even ran FEWER buses than x1.0).
This probe applies the production scaler level-by-level and diffs every PT
schedule after each step, classifying exactly which schedules moved, which
were discarded, and which inverted -- so the fix targets the real failure.

RUN inside Aimsun, KG model open:
      kg_probe_pt_scaling.py

IMPORTANT: the probe MUTATES timetables in memory (like the real sweep does).
Do NOT save the model afterwards -- close without saving, or re-open.
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

_bd_path = _os.path.join(_HERE, "kg", "batch_runner_bus_demand.py")
if not _os.path.isfile(_bd_path):
    _bd_path = _os.path.join(_HERE, "batch_runner_bus_demand.py")
_spec = _ilu.spec_from_file_location("_bd_probe", _bd_path)
_bd = _ilu.module_from_spec(_spec)
_sys.modules["_bd_probe"] = _bd
try:
    _spec.loader.exec_module(_bd)
except SystemExit:
    pass


def _secs(t):
    try:
        return int(t.toSeconds())
    except Exception:
        try:
            return int(_bd._pt_time_to_secs(t))
        except Exception:
            return None


def snapshot():
    """{(line,tbl,sch): {...}} for every PT timetable schedule in the model."""
    from PyANGKernel import GKSystem
    model = GKSystem.getSystem().getActiveModel()
    ltype = model.getType("GKPublicLine")
    objs = model.getCatalog().getObjectsByType(ltype)
    out = {}
    if not objs:
        return out
    lines = list(objs.values()) if isinstance(objs, dict) else list(objs)
    for line in lines:
        try:
            lid = line.getId()
        except Exception:
            lid = id(line)
        for ti, tt in enumerate(line.getTimeTables() or []):
            try:
                scheds = tt.getSchedules()
            except Exception:
                continue
            for si, sch in enumerate(scheds or []):
                key = (lid, ti, si)
                try:
                    deps = list(sch.getDepartureTimes())
                except Exception:
                    deps = []
                entry = {
                    "ndeps": len(deps),
                    "interval": bool(_bd._is_interval_schedule(sch, deps)) if deps else False,
                    "mean": None,
                    "first": None,
                    "last": None,
                    "dep_type": "",
                }
                try:
                    entry["dep_type"] = str(sch.getDepartureType())
                except Exception:
                    pass
                if deps:
                    entry["first"] = _secs(deps[0].getDepartureTime())
                    entry["last"] = _secs(deps[-1].getDepartureTime())
                    mt = None
                    try:
                        mt = deps[0].getMeanTime()
                    except Exception:
                        mt = None
                    entry["mean"] = _secs(mt) if mt is not None else None
                out[key] = entry
    return out


def classify(before, after, scalar):
    """Classify one schedule's response to a scaling application."""
    if before == after:
        return "DISCARDED (no write persisted)"
    if before["interval"]:
        b, a = before["mean"], after["mean"]
        if b and a:
            if abs(a - round(b / scalar)) <= 1:
                return "OK (mean %ss -> %ss)" % (b, a)
            if abs(a - round(b * scalar)) <= 1:
                return "INVERTED (mean %ss -> %ss)" % (b, a)
        return "OTHER (mean %s -> %s)" % (b, a)
    # fixed-departure list
    bn, an = before["ndeps"], after["ndeps"]
    target = max(1, int(round(bn * scalar)))
    if an == target:
        return "OK (deps %d -> %d)" % (bn, an)
    if abs(an - bn) <= 1:
        return "DISCARDED-COUNT (deps %d -> %d, wanted %d)" % (bn, an, target)
    return "OTHER-COUNT (deps %d -> %d, wanted %d)" % (bn, an, target)


def report(prev, cur, scalar, label):
    print("[PROBE] ---- %s : applied x%s ----" % (label, scalar))
    tally = {}
    examples = {}
    for k, b in prev.items():
        a = cur.get(k)
        if a is None:
            cls = "VANISHED"
        else:
            cls = classify(b, a, scalar).split(" ")[0]
        tally[cls] = tally.get(cls, 0) + 1
        if cls not in examples:
            det = classify(b, a, scalar) if a else "schedule disappeared"
            examples[cls] = "key=%s :: %s" % (k, det)
    for cls, cnt in sorted(tally.items(), key=lambda kv: -kv[1]):
        print("[PROBE]   %-16s %3d   e.g. %s" % (cls, cnt, examples.get(cls, "")))


# ── main ──────────────────────────────────────────────────────────────────────
print("=" * 74)
print("[PROBE] KG PT-scaling probe -- do NOT save the model afterwards")
print("=" * 74)

base = snapshot()
_n_int = sum(1 for v in base.values() if v["interval"])
print("[PROBE] baseline: %d schedules (%d interval-type / %d fixed-type)"
      % (len(base), _n_int, len(base) - _n_int))
for k, v in list(base.items())[:6]:
    print("[PROBE]   e.g. key=%s type=%r interval=%s ndeps=%d mean=%s span=%s..%s"
          % (k, v["dep_type"], v["interval"], v["ndeps"], v["mean"], v["first"], v["last"]))

prev = base
_shared_cache = {}   # EXACTLY like champion_bus_demand: one dict across all
                     # levels -- this reproduces the production conditions,
                     # including any cross-level cache contamination.
for scalar in (1.5, 2.0, 3.0):
    n = _bd.set_bus_headway_scalar(scalar, _shared_cache)
    cur = snapshot()
    report(prev, cur, scalar, "vs previous state")
    report(base, cur, scalar, "vs ORIGINAL baseline")
    print("[PROBE]   scaler reported: scaled %d schedules (shared cache size=%d)"
          % (n, len(_shared_cache)))
    prev = cur

print("=" * 74)
print("[PROBE] DONE. Close the model WITHOUT saving (or File > Revert).")
print("[PROBE] Send Zeke the [PROBE] block above.")
