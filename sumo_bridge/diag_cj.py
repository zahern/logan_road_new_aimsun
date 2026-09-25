model = GKSystem.getSystem().getActiveModel()
cat = model.getCatalog()
t_cp = model.getType("GKControlPlan")
raw = cat.getObjectsByType(t_cp)
plans = list(raw.values()) if isinstance(raw, dict) else list(raw)
cp = plans[0]
print(f"plan: {cp.getId()} '{cp.getName()}'")
jcs = cp.getControlJunctions()
if isinstance(jcs, dict):
    jids = list(jcs.keys())[:5]
else:
    jids = list(jcs)[:5]
print(f"first 5 junction IDs: {jids}")
for jid in jids[:3]:
    node = cat.find(int(jid))
    print(f"\ncat.find({jid}) -> {type(node).__name__ if node else 'None'}")
    if node is None:
        continue
    try:
        cj = cp.getControlJunction(node)
        print(f"  getControlJunction -> {type(cj).__name__ if cj else 'None'}")
        if cj:
            attrs = [a for a in dir(cj) if not a.startswith("_")]
            print(f"    attrs({len(attrs)}): {attrs}")
            for mn in ("getPhases", "getSignalGroups", "getDuration"):
                fn = getattr(cj, mn, None)
                if callable(fn):
                    try:
                        r = fn()
                        print(f"    {mn}() -> {type(r).__name__} len={len(r) if isinstance(r,(list,tuple)) else r}")
                    except Exception as e2:
                        print(f"    {mn}() ERR: {e2}")
    except Exception as e:
        print(f"  getControlJunction ERROR: {e}")
