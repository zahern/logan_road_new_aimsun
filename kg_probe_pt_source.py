"""
kg_probe_pt_source.py -- find WHAT the simulator actually reads PT from.

Background: mutating GKPublicLine departure objects changes nothing in the
running simulation (probe2), yet saved edits DO change future loads. So the
per-replication vehicle generation must come from a structure we haven't
touched -- likely a scenario/demand-side copy of the services.

This probe (READ-ONLY -- mutates nothing):
  1. inventories every catalog type matching pt/transit/public/plan/schedule
  2. dumps candidate getters on sample instances of those types
  3. walks GKScenario / GKExperiment / GKTrafficDemand objects and prints
     whatever they reference (looking for a PT plan or per-line service copy)
  4. opens GKPublicLine timetables AND traffic-demand schedule items side by
     side so we can diff which copy carries the inflated departures

RUN inside Aimsun, KG model open. Nothing is modified.
"""

import re

from PyANGKernel import GKSystem

model = GKSystem.getSystem().getActiveModel()
cat = model.getCatalog()

INTEREST = re.compile(r"(pt|transit|public|plan|timetable|schedule)", re.I)
LOOSE = re.compile(r"(pt|transit|public|line|plan|timetable|schedule|demand)", re.I)


def _name(o):
    try:
        return o.getName()
    except Exception:
        return ""


def _id(o):
    try:
        return o.getId()
    except Exception:
        return "?"


def safe_call(obj, meth_name):
    try:
        fn = getattr(obj, meth_name)
        v = fn()
        s = str(v)
        return s[:120]
    except Exception as e:
        return "<err %r>" % e


print("=" * 76)
print("[PSOURCE] PT-source discovery probe (read-only)")
print("=" * 76)

# ── 1. type inventory ────────────────────────────────────────────────────────
hits = []
try:
    for t in model.getTypes():
        try:
            tn = t.getName()
        except Exception:
            continue
        if INTEREST.search(str(tn)):
            cnt = -1
            objs = None
            try:
                objs = cat.getObjectsByType(t)
                cnt = len(objs) if objs is not None else 0
            except Exception:
                pass
            hits.append((str(tn), cnt))
except Exception as e:
    print("[PSOURCE] type walk failed: %r" % e)

print("\n[PSOURCE] -- 1. matching catalog types --")
for tn, cnt in sorted(hits, key=lambda x: -(x[1] if x[1] > 0 else 0)):
    print("[PSOURCE]   %-34s count=%s" % (tn, cnt))

# ── 2. sample instances of strongly-matching types ───────────────────────────
STRONG = re.compile(r"(pt|transit|public|timetable|schedule)", re.I)
print("\n[PSOURCE] -- 2. instance inspection (up to 2 each) --")
seen_types = set()
for tn, cnt in hits:
    if cnt <= 0 or not STRONG.search(tn) or tn in seen_types:
        continue
    seen_types.add(tn)
    try:
        t = model.getType(tn)
        objs = cat.getObjectsByType(t)
        lst = list(objs.values()) if isinstance(objs, dict) else list(objs or [])
    except Exception:
        continue
    for obj in lst[:2]:
        print("[PSOURCE]   <%s> id=%s name=%r" % (tn, _id(obj), _name(obj)))
        getters = [m for m in dir(obj) if m.startswith("get")
                   and STRONG.search(m)]
        for g in getters[:10]:
            print("[PSOURCE]       %s() -> %s" % (g, safe_call(obj, g)))

# ── 3. scenario / experiment / demand traversal ──────────────────────────────
print("\n[PSOURCE] -- 3. scenario/experiment/demand graph --")


def dump_refs(obj, label, depth=0):
    pad = "  " * depth
    getters = [m for m in dir(obj) if m.startswith("get")
               and LOOSE.search(m)]
    for g in getters[:14]:
        v = safe_call(obj, g)
        if v and not v.startswith("<err"):
            print("[PSOURCE] %s%s.%s() -> %s" % (pad, label, g, v))


for tn in ("GKScenario", "GKExperiment", "GKTrafficDemand", "GKReplication"):
    try:
        t = model.getType(tn)
        objs = cat.getObjectsByType(t)
        lst = list(objs.values()) if isinstance(objs, dict) else list(objs or [])
    except Exception:
        continue
    print("[PSOURCE]   %s: %d instance(s)" % (tn, len(lst)))
    for obj in lst[:3]:
        print("[PSOURCE]     <%s> id=%s name=%r" % (tn, _id(obj), _name(obj)))
        dump_refs(obj, tn, depth=2)

# ── 4. traffic-demand schedule items: what classes live inside? ─────────────
print("\n[PSOURCE] -- 4. traffic-demand schedule item classes --")
try:
    t = model.getType("GKTrafficDemand")
    dems = cat.getObjectsByType(t)
    dems = list(dems.values()) if isinstance(dems, dict) else list(dems or [])
    for dem in dems[:4]:
        print("[PSOURCE]   demand id=%s name=%r" % (_id(dem), _name(dem)))
        try:
            sched = dem.getSchedule()
        except Exception as e:
            print("[PSOURCE]     getSchedule err: %r" % e)
            continue
        for si, item in enumerate(sched or []):
            cls = item.__class__.__name__ if item is not None else "?"
            extra = ""
            try:
                f = float(item.getFactor())
                extra += " factor=%.3f" % f
            except Exception:
                pass
            try:
                nm = item.getName()
                extra += " name=%r" % nm
            except Exception:
                pass
            if si < 8:
                print("[PSOURCE]     item[%d] class=%s%s"
                      % (si, cls, extra))
        if len(sched or []) > 8:
            print("[PSOURCE]     ... %d items total" % len(sched))
except Exception as e:
    print("[PSOURCE] demand walk failed: %r" % e)

# ── 5. GKPublicLine deep dive ────────────────────────────────────────────────
print("\n[PSOURCE] -- 5. GKPublicLine attribute surface --")
try:
    t = model.getType("GKPublicLine")
    lines = cat.getObjectsByType(t)
    lines = list(lines.values()) if isinstance(lines, dict) else list(lines or [])
    print("[PSOURCE]   total public lines: %d" % len(lines))
    for line in lines[:2]:
        print("[PSOURCE]   line id=%s name=%r" % (_id(line), _name(line)))
        tt = []
        try:
            tt = list(line.getTimeTables() or [])
        except Exception:
            pass
        print("[PSOURCE]     timetables: %d" % len(tt))
        for ti, tbl in enumerate(tt[:1]):
            try:
                schs = list(tbl.getSchedules() or [])
            except Exception:
                schs = []
            print("[PSOURCE]     timetable[%d]: %d schedule(s)" % (ti, len(schs)))
            for si, sch in enumerate(schs[:3]):
                ndeps = None
                mean = None
                try:
                    deps = list(sch.getDepartureTimes())
                    ndeps = len(deps)
                    if deps:
                        mt = deps[0].getMeanTime()
                        mean = int(mt.toSeconds()) if mt else None
                except Exception:
                    pass
                print("[PSOURCE]       schedule[%d]: ndeps=%s mean=%ss"
                      % (si, ndeps, mean))
        getters = [m for m in dir(line) if m.startswith("get")
                   and LOOSE.search(m) and "ection" not in m]
        for g in getters[:8]:
            print("[PSOURCE]       %s() -> %s" % (g, safe_call(line, g)))
except Exception as e:
    print("[PSOURCE] line walk failed: %r" % e)

print("=" * 76)
print("[PSOURCE] DONE (read-only). Send Zeke the whole block.")
