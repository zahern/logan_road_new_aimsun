# run_in_aimsun_PROBE.py
#
# Run INSIDE Aimsun Next with the corridor model open.
# Dumps complete method lists (dir()) for one live object of each class we
# care about, plus the control-plan child chain (junction -> phase -> sg).
# Writes: C:\Users\ahernz\github_for_aimsun\sumo_bridge\aimsun_api_probe.txt

import builtins

OUT = r"C:\Users\ahernz\github_for_aimsun\sumo_bridge\aimsun_api_probe.txt"


def _resolve_gksystem():
    gks = getattr(builtins, "GKSystem", None)
    if gks is not None and hasattr(gks, "getSystem"):
        return gks
    gks = globals().get("GKSystem")
    return gks if gks is not None and hasattr(gks, "getSystem") else None


def first_of_type(cat, model, tname):
    try:
        t = model.getType(tname)
        got = cat.getObjectsByType(t) if t is not None else None
        if got:
            vals = list(got.values()) if isinstance(got, dict) else list(got)
            return vals[0] if vals else None
    except Exception:
        pass
    return None


def dump_dir(obj, label, lines, filter_sub=None):
    lines.append("")
    lines.append("=== %s ===" % label)
    try:
        names = [n for n in dir(obj)
                 if not n.startswith("_") and callable(getattr(obj, n, None))]
        if filter_sub:
            keep = [n for n in names if any(s in n.lower() for s in filter_sub)]
            rest = [n for n in names if n not in keep]
        else:
            keep, rest = [], names
        if keep:
            lines.append("  -- relevant --")
            for n in sorted(keep):
                lines.append("    %s" % n)
        lines.append("  -- all others --")
        for i in range(0, len(rest), 4):
            lines.append("    " + " ".join("%-34s" % x for x in rest[i:i + 4]))
    except Exception as e:
        lines.append("  !! dir failed: %r" % e)


def main():
    gks = _resolve_gksystem()
    if gks is None:
        print("[PROBE] GKSystem not injected")
        return
    model = gks.getSystem().getActiveModel()
    cat = model.getCatalog()
    lines = ["model: %s" % model.getName()]

    sec = first_of_type(cat, model, "GKSection")
    tur = first_of_type(cat, model, "GKTurning")
    nod = first_of_type(cat, model, "GKNode")
    det = first_of_type(cat, model, "GKDetector")
    cp = first_of_type(cat, model, "GKControlPlan")

    dump_dir(sec, "GKSection", lines,
             ["shape", "point", "node", "lane", "length", "speed", "origin",
              "dest", "turn", "entry", "exit", "id"])
    dump_dir(tur, "GKTurning", lines,
             ["section", "node", "lane", "origin", "dest", "source", "sink",
              "from", "to", "length"])
    dump_dir(nod, "GKNode", lines,
             ["turning", "section", "control", "position", "coordinate"])
    dump_dir(det, "GKDetector", lines,
             ["section", "lane", "position", "length", "initial", "final"])

    if cp is not None:
        dump_dir(cp, "GKControlPlan", lines,
                 ["junction", "phase", "signal", "cycle"])
        jc = None
        try:
            jcs = cp.getControlJunctions()
            jc = jcs[0] if jcs else None
        except Exception:
            pass
        if jc is not None:
            dump_dir(jc, "ControlJunction[0]", lines,
                     ["junction", "phase", "signal", "ring", "cycle", "control"])
            ph = None
            for getter in ("getPhases",):
                try:
                    phs = getattr(jc, getter)()
                    ph = phs[0] if phs else None
                except Exception:
                    pass
            if ph is not None:
                dump_dir(ph, "Phase[0]", lines,
                         ["duration", "signal", "state", "green", "yellow"])
                try:
                    sgs = jc.getSignalGroups()
                    if sgs:
                        dump_dir(sgs[0], "SignalGroup[0]", lines,
                                 ["turning", "id", "state"])
                except Exception:
                    pass

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("[PROBE] saved -> %s" % OUT)


main()
