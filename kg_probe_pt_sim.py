"""
kg_probe_pt_sim.py -- phase-2 PT-scaling probe: timetable vs simulated buses.

Discriminates the three remaining suspects after kg_probe_pt_scaling.py proved
the scaler writes correctly:
  S1: the replication consumes PT from another source than the mutated objects
  S2: bus KPIs (N_DistinctBuses/N_BusTrips) under-count dense service
  S3: something between levels re-materialises/resets timetables

Per level (baseline, x1.5, x2.0, x3.0 -- shared cache, production scaler):
  1. snapshot timetables (incl. every departure time)
  2. count scheduled departures INSIDE the sim window
  3. run ONE real replication (seed 300)
  4. re-snapshot -> detect any reset/drift caused by the run itself
  5. pull N_DistinctBuses / N_BusTrips from the newest results folder

RUN inside Aimsun, KG model open (~3 min per level). Do NOT save afterwards.
"""

import os as _os
import sys as _sys
import glob as _glob
import importlib.util as _ilu

SEED         = 300
SIM_START_S  = 27000   # 07:30:00 -- must match the KG scenario window
SIM_END_S    = 31500   # 07:30 + 4500 s

try:
    _HERE = _os.path.dirname(_os.path.abspath(__file__))
except NameError:
    from PyANGKernel import GKSystem
    _HERE = _os.path.dirname(
        GKSystem.getSystem().getActiveModel().getDocumentFileName())

def _load(name, path):
    spec = _ilu.spec_from_file_location(name, path)
    mod = _ilu.module_from_spec(spec)
    _sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod

_bd = _load("_bd_probe2",
            _os.path.join(_HERE, "kg", "batch_runner_bus_demand.py"))
_br = _load("_br_probe2", _os.path.join(_HERE, "kg", "batch_runner.py"))

# ── Batch-quiet mode ─────────────────────────────────────────────────────────
# Without this, every probe replication inherits whatever logging the LAST
# sweep's cleanup restored (VERBOSE=True + dashboards + detection marking),
# paying ~3-5 min/run in console spam and finish-time plot pipelines.
import re as _re
try:
    _CP = _br.CONTROLLER_PATH
    _br._set_logging(_CP, enabled=False)
    _txt = open(_CP, encoding="utf-8", errors="replace").read()
    for _flag in ("MARK_DETECTION_POINTS", "OVERLAY_DETECTIONS_ON_MAP",
                  "TRACK_BUS_POSITIONS"):
        _txt = _re.sub(r"(?m)^(" + _flag + r"\s*:\s*bool\s*=\s*)(True|False)",
                       r"\g<1>False", _txt)
    _txt = _re.sub(r"(?m)^(STATUS_DASHBOARD_INTERVAL_S\s*:\s*float\s*=\s*)['\d.]+",
                   r"\g<1>0.0", _txt)
    with open(_CP, "w", encoding="utf-8", newline="") as f:
        f.write(_txt)
    print("[PROBE2] batch-quiet mode: VERBOSE/dashboards/marking disabled")
except Exception as _q_err:
    print("[PROBE2] WARN quiet setup failed: %r" % _q_err)


def _secs(t):
    try:
        return int(t.toSeconds())
    except Exception:
        try:
            return int(_bd._pt_time_to_secs(t))
        except Exception:
            return None


def snapshot():
    """Full timetable snapshot incl. every departure time."""
    from PyANGKernel import GKSystem
    model = GKSystem.getSystem().getActiveModel()
    ltype = model.getType("GKPublicLine")
    objs = model.getCatalog().getObjectsByType(ltype)
    out = {}
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
                times = []
                mean = None
                for d in deps:
                    s0 = _secs(d.getDepartureTime())
                    if s0 is not None:
                        times.append(s0)
                if deps:
                    try:
                        mt = deps[0].getMeanTime()
                        mean = _secs(mt) if mt is not None else None
                    except Exception:
                        pass
                out[key] = {
                    "interval": bool(_bd._is_interval_schedule(sch, deps)) and len(deps) <= 1,
                    "times": sorted(times),
                    "mean": mean,
                }
    return out


def window_departures(snap):
    """Scheduled departures inside [SIM_START_S, SIM_END_S] across all lines."""
    total = 0
    per = {}
    for k, v in snap.items():
        if v["interval"]:
            t0 = v["times"][0] if v["times"] else None
            h = v["mean"]
            if t0 is None or not h or h <= 0:
                c = 0
            else:
                first_k = max(0, -(-(SIM_START_S - t0) // h))  # ceil div
                c = 0 if t0 > SIM_END_S else max(0, (SIM_END_S - t0) // h - first_k + 1)
        else:
            c = sum(1 for t in v["times"] if SIM_START_S <= t <= SIM_END_S)
        per[k] = c
        total += c
    return total, per


def newest_results_folder():
    root = _os.path.join(_HERE, "kg", "results") if _os.path.isdir(
        _os.path.join(_HERE, "kg", "results")) else _os.path.join(_HERE, "results")
    dirs = [d for d in _glob.glob(_os.path.join(root, "*")) if _os.path.isdir(d)]
    return max(dirs, key=_os.path.getmtime) if dirs else None


def read_bus_kpis():
    d = newest_results_folder()
    if not d:
        return None
    csv_path = _os.path.join(d, "simulation_results.csv")
    if not _os.path.isfile(csv_path):
        return None
    import csv as _csv
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        row = list(_csv.DictReader(f))[0]
    def g(k):
        try:
            return float(row[k])
        except Exception:
            return None
    return {"folder": _os.path.basename(d),
            "distinct": g("N_DistinctBuses"), "trips": g("N_BusTrips"),
            "obj": g("Objective_PaxPerDelayHr")}


def diff_snapshots(a, b):
    if a.keys() != b.keys():
        return "KEYS CHANGED (%d -> %d)" % (len(a), len(b))
    changed = [k for k in a if a[k]["times"] != b[k]["times"]
               or a[k]["mean"] != b[k]["mean"]]
    return "%d/%d schedules changed" % (len(changed), len(a))


# ── main ──────────────────────────────────────────────────────────────────────
print("=" * 74)
print("[PROBE2] timetable-vs-simulated-bus probe | seed=%d window=%ds-%ds"
      % (SEED, SIM_START_S, SIM_END_S))
print("[PROBE2] NOTE: do NOT save the model afterwards.")
print("=" * 74)

rep = _br.get_first_replication()

shared_cache = {}          # production conditions: one cache across levels
prev_snap = None

for label, scalar in (("BASELINE(no-op)", 1.0), ("x1.5", 1.5),
                      ("x2.0", 2.0), ("x3.0", 3.0)):
    print("\n[PROBE2] ===== %s =====" % label)
    snap = snapshot()
    n_fixed = sum(1 for v in snap.values() if not v["interval"])
    tot_fixed = sum(len(v["times"]) for v in snap.values() if not v["interval"])
    print("[PROBE2] snapshot: %d schedules (%d fixed, %d interval) | "
          "fixed departures total=%d"
          % (len(snap), n_fixed, len(snap) - n_fixed, tot_fixed))
    if prev_snap is not None:
        print("[PROBE2] vs previous level: %s" % diff_snapshots(prev_snap, snap))
    prev_snap = snap

    wd, _per = window_departures(snap)
    print("[PROBE2] scheduled departures inside sim window: %d" % wd)

    _br.set_seed(rep, SEED)
    _br._purge_pyc(_br.CONTROLLER_PATH)   # force reload of the quieted flags
    print("[PROBE2] running replication ...")
    _br.run_replication(rep)

    post = snapshot()
    print("[PROBE2] post-run timetable check: %s" % diff_snapshots(snap, post))
    k = read_bus_kpis()
    if k:
        print("[PROBE2] simulated: distinct_buses=%.0f trips=%.0f obj=%.2f "
              "(%s)" % (k["distinct"], k["trips"], k["obj"] or 0, k["folder"]))
    else:
        print("[PROBE2] WARNING: no simulation_results.csv found")

print("\n[PROBE2] DONE. Close WITHOUT saving. Send Zeke the whole block.")
print("[PROBE2] Reading guide:")
print("  sched-window-departures rises ~linearly BUT distinct/trips flat  -> S2 (KPI proxy)")
print("  sched-window-departures flat across levels                      -> S1 (sim reads another source)")
print("  'post-run timetable check' shows changes                        -> S3 (run resets state)")
