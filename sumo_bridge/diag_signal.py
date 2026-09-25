# diag_signal.py — Run inside Aimsun console (Logan model open)
# Probes the actual signal control API to find where phases live.

model = GKSystem.getSystem().getActiveModel()
cat = model.getCatalog()

# 1. What control-plan types exist?
for tn in ("GKControlPlan", "GKControlJunction", "GKControlJunctionPhase",
           "GKPhase", "GKSignalGroup", "GKControlTurn"):
    t = model.getType(tn)
    if t:
        objs = cat.getObjectsByType(t)
        print(f"{tn}: {len(objs) if objs else 0}")
    else:
        print(f"{tn}: type not found")

# 2. Get first control plan, inspect getControlJunctions() return
plans = []
t_cp = model.getType("GKControlPlan")
if t_cp:
    raw = cat.getObjectsByType(t_cp)
    plans = list(raw.values()) if isinstance(raw, dict) else list(raw or [])
print(f"\ncontrol plans: {len(plans)}")

if plans:
    cp = plans[0]
    print(f"plan: {cp.getId()} '{cp.getName()}'")
    jcs = cp.getControlJunctions()
    print(f"getControlJunctions() -> {type(jcs).__name__}[{len(jcs)}]")
    if jcs:
        j0 = list(jcs)[0]
        print(f"  first item type: {type(j0).__name__}, value: {j0}")
        # If it's a GKNode, try plan.getControlJunction(node)
        fn = getattr(cp, "getControlJunction", None)
        if callable(fn):
            try:
                cj = fn(j0)
                print(f"  getControlJunction(node) -> {type(cj).__name__}")
                if cj and hasattr(cj, "getPhases"):
                    phases = cj.getPhases()
                    print(f"    phases: {len(phases)}")
                    for ph in list(phases)[:3]:
                        dur = ph.getDuration() if hasattr(ph, "getDuration") else "?"
                        print(f"      duration={dur}")
                elif cj and hasattr(cj, "getSignalGroups"):
                    sgs = cj.getSignalGroups()
                    print(f"    signal_groups: {len(sgs)}")
            except Exception as e:
                print(f"  getControlJunction(node) ERROR: {e}")
        # Try node methods directly
        if hasattr(j0, "getSignals"):
            sigs = j0.getSignals()
            print(f"  node.getSignals() -> {sigs}")

# 3. Check a node directly for signal/phase data
groups = {}
t_node = model.getType("GKNode")
nodes_raw = cat.getObjectsByType(t_node)
nodes = list(nodes_raw.values()) if isinstance(nodes_raw, dict) else list(nodes_raw or [])
for node in nodes[:5]:
    nid = node.getId()
    sigs = None
    for getter in ("getSignals", "getSignalGroups", "getControlPlan"):
        fn = getattr(node, getter, None)
        if callable(fn):
            try:
                r = fn()
                if r:
                    print(f"\nnode {nid}.{getter}() -> {type(r).__name__}")
                    if hasattr(r, "getPhases"):
                        phs = r.getPhases()
                        print(f"  phases: {len(phs)}")
                        for ph in list(phs)[:2]:
                            print(f"    dur={ph.getDuration() if hasattr(ph,'getDuration') else '?'}")
                    break
            except Exception:
                continue
