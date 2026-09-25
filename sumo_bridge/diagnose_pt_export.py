"""
diagnose_pt_export.py -- Run INSIDE Aimsun Next with the Logan model open.
Pastes everything needed to fix the PT export into the console.

import importlib.util
spec = importlib.util.spec_from_file_location(
    "diag", r"C:\Users\ahernz\github_for_aimsun\sumo_bridge\diagnose_pt_export.py")
diag = importlib.util.module_from_spec(spec); spec.loader.exec_module(diag)
"""

import builtins

def _gks():
    gks = getattr(builtins, "GKSystem", None)
    if gks and hasattr(gks, "getSystem"):
        return gks.getSystem().getActiveModel()
    raise RuntimeError("Run inside Aimsun.")

model = _gks()
cat = model.getCatalog()

# ── 1. What PT-related types exist? ──────────────────────────────────────────
print("=" * 70)
print("PT-RELATED TYPES IN CATALOG")
for tn in ("GKPublicLine", "GKPTLine", "GKPTPlan", "GKPTStop", "GKBusStop",
           "GKPTLineRouteItem", "GKPTSchedule", "GKPTTransfer",
           "GKBusStop", "GKCentroid", "GKControlJunction"):
    t = model.getType(tn)
    if t is None:
        print("  %s : type NOT FOUND" % tn)
        continue
    objs = cat.getObjectsByType(t)
    n = len(objs) if objs else 0
    print("  %s : %d objects" % (tn, n))

# ── 2. Deep-probe the first 3 transit lines ──────────────────────────────────
t_line = model.getType("GKPublicLine")
lines_raw = cat.getObjectsByType(t_line)
lines = list(lines_raw.values()) if isinstance(lines_raw, dict) else list(lines_raw or [])
print("\n" + "=" * 70)
print("DEEP PROBE: first 3 transit lines (%d total)" % len(lines))

for li, line in enumerate(lines[:3]):
    lid = line.getId()
    lname = line.getName()
    print("\n--- Line %s '%s' ---" % (lid, lname[:60]))

    # Every method that might return sections or stops
    for meth_name in ("getSections", "getStops", "getRoute", "getRouteIds",
                      "getTurnsInRoute", "getIndexSection",
                      "getTimeTableStopToStopDelay", "getPTSectionData"):
        fn = getattr(line, meth_name, None)
        if not callable(fn):
            continue
        # try no-args
        try:
            r = fn()
            rtype = type(r).__name__
            if isinstance(r, (list, tuple)):
                print("  %s() -> %s[%d]" % (meth_name, rtype, len(r)))
                if r and len(r) > 0:
                    first = r[0]
                    print("       first: %s (type=%s)" % (first, type(first).__name__))
            elif r is None:
                print("  %s() -> None" % meth_name)
            elif isinstance(r, (int, float, str)):
                print("  %s() -> %r" % (meth_name, r))
            else:
                # object — introspect it
                sub = [a for a in dir(r) if not a.startswith("_")][:15]
                print("  %s() -> %s obj, attrs=%s" % (meth_name, rtype, sub))
                # if it has getSections, recurse once
                if hasattr(r, "getSections"):
                    try:
                        secs = r.getSections()
                        print("       r.getSections() -> %d items" % (
                            len(secs) if secs else 0))
                        if secs:
                            for s0 in list(secs)[:3]:
                                sid = s0.getId() if hasattr(s0, "getId") else s0
                                print("         sec id=%s" % sid)
                    except Exception as e2:
                        print("       r.getSections() ERROR: %s" % e2)
        except Exception as e:
            print("  %s() -> EXCEPTION: %s" % (meth_name, e))
        # try with int(0) arg
        try:
            r = fn(0)
            print("  %s(0) -> %r" % (meth_name, r if not isinstance(r, object) else type(r).__name__))
        except TypeError:
            pass
        except Exception as e:
            print("  %s(0) -> %s" % (meth_name, e))

# ── 3. TimeTables — where are they? ──────────────────────────────────────────
print("\n" + "=" * 70)
print("TIME TABLES")
if lines:
    line = lines[0]
    try:
        tts = line.getTimeTables()
        print("  getTimeTables() -> %d" % (len(tts) if tts else 0))
        for tt in (tts or [])[:2]:
            print("  TT id=%s name=%s" % (tt.getId(), tt.getName()))
            try:
                schs = tt.getSchedules()
                print("    schedules: %d" % (len(schs) if schs else 0))
                for sch in (schs or [])[:2]:
                    deps = list(sch.getDepartureTimes())
                    print("    sched depType=%s ndeps=%d" % (
                        sch.getDepartureType(), len(deps)))
                    if deps:
                        d0 = deps[0]
                        print("      dep[0] attrs: %s" %
                              [a for a in dir(d0) if not a.startswith("_")][:20])
            except Exception as e:
                print("    schedule ERROR: %s" % e)
    except Exception as e:
        print("  getTimeTables ERROR: %s" % e)

# ── 4. Transit Plans deep probe ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("TRANSIT PLANS DEEP PROBE")
for plan_type in ("GKPTPlan", "GKTransitPlan"):
    t = model.getType(plan_type)
    if t is None:
        continue
    plans_raw = cat.getObjectsByType(t)
    plans = list(plans_raw.values()) if isinstance(plans_raw, dict) else list(plans_raw or [])
    print("  %s: %d plans" % (plan_type, len(plans)))
    for plan in plans[:2]:
        pid = plan.getId()
        pname = plan.getName()
        print("  Plan %s '%s'" % (pid, pname[:50]))
        meths = [a for a in dir(plan) if any(
            k in a.lower() for k in ("line", "route", "stop", "depart",
                                     "schedule", "headway", "frequency"))
                 and not a.startswith("_")]
        print("    relevant methods: %s" % sorted(meths)[:25])
        for mn in sorted(meths)[:10]:
            fn = getattr(plan, mn, None)
            if callable(fn):
                try:
                    r = fn()
                    if r is not None:
                        if isinstance(r, (list, tuple)):
                            print("    %s() -> [%d]" % (mn, len(r)))
                            if r:
                                print("      first: %s" % r[0])
                        else:
                            print("    %s() -> %r" % (mn, r))
                except Exception as e:
                    print("    %s() -> ERR: %s" % (mn, e))

print("\n" + "=" * 70)
print("DONE — paste ALL output back for exporter wiring.")
