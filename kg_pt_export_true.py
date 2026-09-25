"""
kg_pt_export_true.py -- capture TRUE PT timetables from the pristine KG model.

OPEN THE MAY MODEL IN AIMSUN BEFORE RUNNING:
    TEG_KGER_T2_2025Base_QUT_AITAN1.ang     <-- the ORIGINAL, pre-experiments

Writes kg/pt_true_baseline.json containing every public line's exact schedule
(departure times / interval means). Read-only; close WITHOUT saving afterwards.
"""

import json
import os

from PyANGKernel import GKSystem

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)) if True else "",
                   "pt_true_baseline.json")
try:
    HERE = os.path.dirname(os.path.abspath(__file__))
    OUT = os.path.join(HERE, "pt_true_baseline.json")
except NameError:
    from PyANGKernel import GKSystem as _g
    HERE = os.path.dirname(
        _g.getSystem().getActiveModel().getDocumentFileName())
    OUT = os.path.join(HERE, "pt_true_baseline.json")

model = GKSystem.getSystem().getActiveModel()
cat = model.getCatalog()
lines = cat.getObjectsByType(model.getType("GKPublicLine"))
lines = list(lines.values()) if isinstance(lines, dict) else list(lines or [])


def secs(t):
    try:
        return int(t.toSeconds())
    except Exception:
        try:
            h, m, s = t.getHours(), t.getMinutes(), t.getSeconds()
            return h * 3600 + m * 60 + s
        except Exception:
            return None


data = {}
for line in lines:
    try:
        lid = int(line.getId())
        lname = line.getName()
    except Exception:
        continue
    entry = {"name": lname, "timetables": []}
    for ti, tt in enumerate(line.getTimeTables() or []):
        tt_entry = []
        try:
            scheds = list(tt.getSchedules() or [])
        except Exception:
            scheds = []
        for si, sch in enumerate(scheds):
            rec = {"interval": False, "mean": None, "anchor": None, "times": []}
            try:
                deps = list(sch.getDepartureTimes())
            except Exception:
                deps = []
            if deps:
                rec["times"] = [s for s in (secs(d.getDepartureTime())
                                            for d in deps) if s is not None]
                if len(deps) == 1:
                    mt = None
                    try:
                        mt = deps[0].getMeanTime()
                    except Exception:
                        pass
                    if mt is not None:
                        rec["interval"] = True
                        rec["mean"] = secs(mt)
                        rec["anchor"] = rec["times"][0] if rec["times"] else None
            tt_entry.append(rec)
        entry["timetables"].append(tt_entry)
    data[str(lid)] = entry

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(data, f)

n_sched = sum(len(tt) for v in data.values() for tt in v["timetables"])
n_deps = sum(len(s["times"]) for v in data.values()
             for tt in v["timetables"] for s in tt)
print("[PT-EXPORT] lines=%d schedules=%d total departures=%d" %
      (len(data), n_sched, n_deps))
print("[PT-EXPORT] wrote %s" % OUT)
print("[PT-EXPORT] CLOSE THIS MODEL WITHOUT SAVING. Now open the normal")
print("[PT-EXIT]   RECOVER model and run kg_pt_apply_true.py.")
