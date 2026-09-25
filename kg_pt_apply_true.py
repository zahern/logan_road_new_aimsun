"""
kg_pt_apply_true.py -- write the TRUE timetables (from the May model export)
into the current working KG model.

PREREQUISITE: kg/pt_true_baseline.json must exist (created by
kg_pt_export_true.py with the May model open).

Applies every schedule exactly (fixed lists rebuilt departure-for-departure;
interval means + anchors restored). Then:
    1. File > Save
    2. Close and reopen the model
    3. Run check_car_count.py  ->  expect ~56 buses / objective ~133.5
"""

import json
import os

from PyANGKernel import GKSystem

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    HERE = os.path.dirname(
        GKSystem.getSystem().getActiveModel().getDocumentFileName())
SRC = os.path.join(HERE, "pt_true_baseline.json")

if not os.path.isfile(SRC):
    raise SystemExit("[PT-APPLY] MISSING %s -- run kg_pt_export_true.py on the "
                     "May model first." % SRC)

with open(SRC, encoding="utf-8") as f:
    truth = json.load(f)

model = GKSystem.getSystem().getActiveModel()
cat = model.getCatalog()
lines = cat.getObjectsByType(model.getType("GKPublicLine"))
lines = list(lines.values()) if isinstance(lines, dict) else list(lines or [])


def secs(t):
    try:
        return int(t.toSeconds())
    except Exception:
        return None


def dur(s):
    from PyANGKernel import GKTimeDuration
    h, rem = divmod(int(max(0, round(s))), 3600)
    m, sec = divmod(rem, 60)
    return GKTimeDuration(h, m, sec)


applied = 0
missing_lines = []
partial = []
touched_lines = set()

for line in lines:
    try:
        lid = int(line.getId())
    except Exception:
        continue
    if str(lid) not in truth:
        missing_lines.append(lid)
        continue
    entry = truth[str(lid)]
    tts = line.getTimeTables() or []
    if len(tts) < len(entry["timetables"]):
        partial.append(lid)
    for ti, tt in enumerate(tts):
        if ti >= len(entry["timetables"]):
            continue
        scheds = list(tt.getSchedules() or [])
        want = entry["timetables"][ti]
        for si, sch in enumerate(scheds):
            if si >= len(want):
                partial.append((lid, ti, si, "extra schedule in model"))
                continue
            w = want[si]
            try:
                deps = list(sch.getDepartureTimes())
            except Exception:
                deps = []
            proto = deps[0] if deps else None
            if w["interval"]:
                if not w["times"] or w["mean"] is None:
                    continue
                sch.removeDepartureTimes()
                nd = type(proto)() if proto is not None else None
                if nd is None:
                    continue
                nd.setDepartureTime(dur(w["anchor"]))
                try:
                    nd.setMeanTime(dur(w["mean"]))
                except Exception:
                    pass
                sch.addDepartureTime(nd)
                applied += 1
                touched_lines.add(lid)
            else:
                times = w["times"]
                if len(times) < 2:
                    continue
                sch.removeDepartureTimes()
                for s0 in times:
                    nd = type(proto)() if proto is not None else None
                    if nd is None:
                        break
                    nd.setDepartureTime(dur(s0))
                    sch.addDepartureTime(nd)
                try:
                    sch.sortDepartureTimes()
                except Exception:
                    pass
                applied += 1
                touched_lines.add(lid)

print("=" * 74)
print("[PT-APPLY] schedules rewritten : %d" % applied)
print("[PT-APPLY] lines touched       : %d / %d in model, %d in baseline"
      % (len(touched_lines), len(lines), len(truth)))
if missing_lines:
    print("[PT-APPLY] lines in model but NOT in May baseline (left untouched): "
          "%s" % missing_lines[:10])
if partial:
    print("[PT-APPLY] structural mismatches: %s" % str(partial[:6]))
print("[PT-APPLY] NOW: File > Save, close & REOPEN, then run check_car_count.")
print("[PT-APPLY] expected verification: ~56 distinct buses, obj ~133.5")
print("=" * 74)
