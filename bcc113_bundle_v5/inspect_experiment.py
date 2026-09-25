"""
inspect_experiment.py -- READ-ONLY probe of the Aimsun experiment/scenario:
what demand + OD matrices the micro sim reads, whether that OD is a Static-OD-
Adjustment output, and the route-choice / stored-path settings that drive the
per-replication rebuild.

RUN in the Aimsun console (model open), makes NO changes:
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\inspect_experiment.py").read())

Optional: set TARGET_EXP_ID below to a specific experiment id; else it auto-picks
the micro/SRC experiment (or the active one).
"""
from PyANGKernel import GKSystem

TARGET_EXP_ID = None   # e.g. 11129237; None = auto-detect the micro experiment

_model = GKSystem.getSystem().getActiveModel()


def _s(fn, default="?"):
    try:
        return fn()
    except Exception as _e:
        return default


def _name(o):
    return _s(lambda: o.getName())


def _id(o):
    return _s(lambda: o.getId())


def _cls(o):
    return _s(lambda: o.getTypeName(), type(o).__name__)


def _objs(type_name):
    t = _model.getType(type_name)
    if t is None:
        return []
    objs = _model.getCatalog().getObjectsByType(t)
    if not objs:
        return []
    return list(objs.values()) if isinstance(objs, dict) else list(objs)


def _simple(val):
    """Render a getter result compactly, or None if it's not worth printing."""
    try:
        if val is None or isinstance(val, (int, float, bool, str)):
            return val
        if hasattr(val, "getName"):
            return "<%s '%s'>" % (type(val).__name__, _s(lambda: val.getName()))
        # short containers
        if isinstance(val, (list, tuple)) and len(val) <= 6:
            return "[%d items]" % len(val)
        return "<%s>" % type(val).__name__
    except Exception:
        return "<?>"


def _dump_getters(obj, keywords, indent="      "):
    """Fallback: call every no-arg get*() and print name -> value.

    First prints getters whose NAME matches a keyword; if none match, prints
    ALL simple-valued getters so nothing route/path/DTA-related is missed.
    """
    names = [n for n in sorted(dir(obj))
             if n.startswith("get") and callable(getattr(obj, n, None))]

    def _emit(subset):
        printed = 0
        for nm in subset:
            fn = getattr(obj, nm, None)
            try:
                val = fn()          # no-arg call only
            except Exception:
                continue
            rendered = _simple(val)
            print("%s%s() = %s" % (indent, nm, rendered))
            printed += 1
        return printed

    matched = [n for n in names
               if keywords and any(k in n.lower() for k in keywords)]
    n1 = _emit(matched)
    if n1 == 0:
        print(indent + "(no name-matched getters; dumping ALL simple getters)")
        _emit(names)


def _dump_attrs(obj, keywords, indent="      "):
    """Best-effort: print every attribute of obj whose name matches a keyword."""
    printed = 0
    t = _s(lambda: obj.getType(), None)
    if t is None:
        print(indent + "(no type -- cannot enumerate attributes)")
        return
    cols = None
    for attempt in (
        lambda: t.getColumns(),
        lambda: t.getColumns(1),        # some builds want a search-depth int
        lambda: t.getColumns(True),
    ):
        try:
            cols = attempt()
            if cols:
                break
        except Exception:
            continue
    if not cols:
        print(indent + "(column enumeration unavailable on this build -- "
                       "falling back to method introspection)")
        _dump_getters(obj, keywords, indent)
        return
    for c in cols:
        nm = _s(lambda: c.getName(), None)
        if not nm:
            continue
        low = nm.lower()
        if keywords and not any(k in low for k in keywords):
            continue
        val = None
        for getter in (
            lambda: obj.getDataValue(c),
            lambda: obj.getDataValueDouble(c),
            lambda: obj.getDataValueInt(c),
            lambda: obj.getDataValueString(c),
        ):
            try:
                val = getter()
                break
            except Exception:
                continue
        # QVariant-ish -> str
        try:
            if hasattr(val, "toString"):
                val = val.toString()
        except Exception:
            pass
        print(f"{indent}{nm} = {val}")
        printed += 1
    if printed == 0:
        print(indent + "(no matching attributes found for keywords "
              + str(keywords) + ")")


print("=" * 72)
print("EXPERIMENTS in this model")
print("=" * 72)
_exps = _objs("GKExperiment")
for e in _exps:
    print(f"  id={_id(e)}  class={_cls(e):22}  name='{_name(e)}'")

# ── pick the target experiment ──────────────────────────────────────────────
_target = None
if TARGET_EXP_ID is not None:
    _target = next((e for e in _exps if str(_id(e)) == str(TARGET_EXP_ID)), None)
if _target is None:
    _target = next((e for e in _exps
                    if "micro" in _name(e).lower() or "src" in _name(e).lower()), None)
if _target is None and _exps:
    _target = _exps[0]

print()
print("=" * 72)
print(f"TARGET EXPERIMENT: id={_id(_target)} '{_name(_target)}' class={_cls(_target)}")
print("=" * 72)

# ── scenario + demand ───────────────────────────────────────────────────────
_scen = None
for getter in (lambda: _target.getScenario(),):
    _scen = _s(getter, None)
    if _scen is not None:
        break
print(f"scenario: id={_id(_scen)} '{_name(_scen)}' class={_cls(_scen)}"
      if _scen is not None else "scenario: <none / not resolvable>")

_dem = None
for getter in (lambda: _target.getDemand(),
               lambda: _scen.getDemand() if _scen is not None else None):
    _dem = _s(getter, None)
    if _dem is not None:
        break
if _dem is None:
    print("demand: <could not resolve experiment/scenario demand>")
else:
    print(f"demand: id={_id(_dem)} '{_name(_dem)}' class={_cls(_dem)}")
    print()
    print("  --- Traffic demand items (what the sim actually reads) ---")
    _sched = _s(lambda: _dem.getSchedule(), []) or []
    for _si in _sched:
        _it = _s(lambda: _si.getTrafficDemandItem(), None)
        if _it is None:
            continue
        _veh = _s(lambda: _it.getVehicle(), None)
        _vn = _name(_veh) if _veh is not None else "?"
        _fac = _s(lambda: _si.getFactor())
        print(f"    item id={_id(_it)} class={_cls(_it):16} veh='{_vn}' "
              f"factor={_fac}  name='{_name(_it)}'")
        # If the item IS an OD matrix, report whether it links to an OD
        # adjustment (i.e. the sim depends on the adjustment being current).
        if "odmatrix" in _cls(_it).lower() or "matrix" in _cls(_it).lower():
            _dump_attrs(_it, ("adjust", "src", "scaling", "stored", "path",
                              "origin"), indent="        [OD] ")

# ── route choice / path assignment / stored-path settings ───────────────────
print()
print("  --- ROUTE-CHOICE / PATH-ASSIGNMENT / STORED-PATH settings (experiment) ---")
_dump_attrs(_target, ("path", "route", "assign", "stored", "warm", "initial",
                      "src", "shortest", "kfactor", "reuse", "cache"))
if _scen is not None:
    print("  --- same, on the SCENARIO ---")
    _dump_attrs(_scen, ("path", "route", "assign", "stored", "warm", "initial",
                        "src", "adjust", "od", "demand", "reuse", "cache"))

# ── OUTPUT / STORAGE / PATH-REUSE settings that DRIVE the per-run cost ───────
# Two per-run costs we want to eliminate:
#   (A) writing statistics/detection into the model DATABASE (we read KPIs from
#       SimulationStats CSVs instead -> DB output is pure waste), and
#   (B) recomputing car trips + SRC route trees every run (identical across arms
#       -> should be stored ONCE and reused, not rebuilt). This dumps the exact
# getters/setters on the REPLICATION + EXPERIMENT so we can flip them via API.
_STORE_KW = ("store", "statist", "path", "output", "keep", "result",
             "detect", "database", "history", "warm", "reuse", "cache",
             "trajector", "gis", "raster")


def _dump_store_methods(obj, indent="      "):
    for _mn in sorted(dir(obj)):
        _ml = _mn.lower()
        if _mn.startswith(("get", "is")) and any(k in _ml for k in _STORE_KW):
            fn = getattr(obj, _mn, None)
            if not callable(fn):
                continue
            try:
                _v = fn()          # no-arg getters only
            except Exception:
                continue
            # note the matching SETTER if one exists (so we know what to flip)
            _set = "set" + _mn[3:] if _mn.startswith("get") else None
            _has_set = _set and callable(getattr(obj, _set, None))
            print("%s%s() = %s%s" % (indent, _mn, _simple(_v),
                                     ("   [settable: %s()]" % _set) if _has_set else ""))


print()
print("  --- OUTPUT / DATABASE / STORE-PATHS toggles (the per-run cost knobs) ---")
_reps = _s(lambda: list(_target.getReplications()), []) or []
if not _reps:
    _reps = _objs("GKReplication")
if not _reps:
    print("    (no GKReplication found under experiment or in catalog)")
for _rep in _reps[:3]:
    print(f"    replication id={_id(_rep)} '{_name(_rep)}' class={_cls(_rep)}")
    _dump_store_methods(_rep, indent="      [REP] ")
    _dump_attrs(_rep, _STORE_KW, indent="      [REP-attr] ")
print("  --- same store/output knobs on the EXPERIMENT ---")
_dump_store_methods(_target, indent="    [EXP] ")
_dump_attrs(_target, _STORE_KW, indent="    [EXP-attr] ")

print()
print("=" * 72)
print("DONE (read-only). Paste this whole output back.")
print("Key questions it answers: (1) is the demand the ADJUSTED-OD RESULT or the")
print("adjustment experiment? (2) does the experiment/scenario recompute paths")
print("each run, or can it reuse stored paths? (3) which store*/output* toggles")
print("can we flip to SKIP the database write and REUSE car trips/paths?")
print("=" * 72)
