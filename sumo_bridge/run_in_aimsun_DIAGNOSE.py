# run_in_aimsun_DIAGNOSE.py  (v2 - type-definition based, build-agnostic)
#
# Run INSIDE Aimsun Next with the corridor model open.
# Writes: C:\Users\ahernz\github_for_aimsun\sumo_bridge\aimsun_class_inventory.txt
#
# Paste into the scripting console, or Scripting view -> open -> Run.

import builtins

OUT = r"C:\Users\ahernz\github_for_aimsun\sumo_bridge\aimsun_class_inventory.txt"

INTERESTING = ("section", "turning", "detect", "controlplan", "publicline",
               "odmatrix", "centroid", "node", "pt", "bus", "lane")


def _resolve_gksystem():
    gks = getattr(builtins, "GKSystem", None)
    if gks is not None and hasattr(gks, "getSystem"):
        return gks
    gks = globals().get("GKSystem")
    if gks is not None and hasattr(gks, "getSystem"):
        return gks
    return None


def _call(obj, *names):
    """first method of `names` that exists on obj -> its result (or None)"""
    for n in names:
        f = getattr(obj, n, None)
        if f is None:
            continue
        try:
            r = f()
            return n, r
        except TypeError:
            continue          # wrong signature, try next
        except Exception:
            continue
    return None, None


def main():
    gks = _resolve_gksystem()
    if gks is None:
        print("[DIAG] GKSystem not injected. GK-ish names here:")
        print([n for n in dir(builtins) if "GK" in n][:30])
        return

    model = gks.getSystem().getActiveModel()
    cat = model.getCatalog()
    lines = []
    say = lambda s: (lines.append(s), print(s))

    say("model name : %s" % model.getName())
    m, fv = _call(model, "getFileName", "getPath", "getFilePath")
    if fv:
        say("model file (%s): %s" % (m, fv))

    # ---------------------------------------------------- enumerate types --
    types_src, types = _call(model, "getTypes", "getTypeNames")
    if not types:
        types_src, types = _call(cat, "getTypes", "getTypeNames")
    say("types via  : %s" % (types_src or "<none found>"))

    tnames = []
    if types:
        for t in types:
            if isinstance(t, str):
                tnames.append(t)
                continue
            _, nm = _call(t, "getName", "getNameStr", "typeName", "name")
            if nm is None and isinstance(getattr(t, "name", None), str):
                nm = t.name
            if nm:
                tnames.append(str(nm))
    say("total type names: %d" % len(tnames))

    interesting = sorted({t for t in tnames
                          if any(k in t.lower() for k in INTERESTING)})
    say("")
    say("=== types matching section/turning/detect/control/pt/od/node/lane ===")
    for t in interesting:
        say("  %s" % t)

    # ------------------------------------- count objects per matched type --
    # resolve each NAME back to a type object and ask the catalog for counts
    def type_by_name(name):
        # direct
        try:
            t = model.getType(name)
            if t is not None:
                return t
        except Exception:
            pass
        try:
            t = cat.getType(name)
            if t is not None:
                return t
        except Exception:
            pass
        # scan the types collection again
        if types:
            for t in types:
                if isinstance(t, str):
                    continue
                _, nm = _call(t, "getName", "getNameStr", "typeName", "name")
                if nm is not None and str(nm) == name:
                    return t
        return None

    say("")
    say("=== live object counts (via catalog.getObjectsByType) ===")
    first_of = {}
    total_named = 0
    for tname in interesting:
        tobj = type_by_name(tname)
        if tobj is None:
            continue
        got = None
        for meth in ("getObjectsByType",):
            f = getattr(cat, meth, None)
            if f is None:
                continue
            try:
                got = f(tobj)
                break
            except Exception:
                continue
        if not got:
            continue
        vals = list(got.values()) if isinstance(got, dict) else list(got)
        if not vals:
            continue
        total_named += len(vals)
        say("%7d  %s" % (len(vals), tname))
        first_of.setdefault("probe", (tname, vals[0]))
        first_of[tname] = vals[0]

    # ------------------------------------------------ probe sample objects -
    def probe(obj, label):
        say("")
        say("--- probing %s ---" % label)
        _, cn = _call(obj, "getClassName", "className")
        say("  className      : %s" % cn)
        _, oid = _call(obj, "getId")
        say("  getId()        : %s" % oid)
        _, nmv = _call(obj, "getName")
        say("  getName()      : %s" % str(nmv)[:60])
        for meth in ("getShape", "getLanes", "getNodeOrigin", "getNodeDestination",
                     "getSpeed", "getOriginSection", "getDestinationSection",
                     "getSection", "getInitialPosition", "getFinalPosition",
                     "getLane", "getPosition", "getNbLanes",
                     "getEntryPoint3D", "getExitPoint3D"):
            if hasattr(obj, meth):
                extra = ""
                try:
                    v = getattr(obj, meth)()
                    if meth == "getShape":
                        try:
                            extra = " len=%d first=%s" % (
                                len(v), "%s,%s" % (v[0].getX(), v[0].getY()))
                        except Exception:
                            extra = " (shape unreadable)"
                    elif v is not None and hasattr(v, "getId"):
                        extra = " -> id=%s" % v.getId()
                    elif v is not None:
                        extra = " -> %r" % (str(v)[:40],)
                except Exception as e:
                    extra = " (call failed: %r)" % e
                say("  %-22s yes%s" % (meth + "()", extra))

    probe_targets = [(tn, first_of[tn]) for tn in first_of
                     if tn != "probe" and any(
                         k in tn.lower() for k in ("section", "turning", "detect"))]
    for tn, obj in probe_targets[:4]:
        probe(obj, tn)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    say("")
    say("saved -> %s" % OUT)


main()
