model = GKSystem.getSystem().getActiveModel()
cat = model.getCatalog()

for tn in ("GKPublicLine", "GKPTLine", "GKPTPlan", "GKBusStop", "GKPTStop"):
    t = model.getType(tn)
    if t:
        objs = cat.getObjectsByType(t)
        n = len(objs) if objs else 0
        print(f"{tn}: {n}")
    else:
        print(f"{tn}: type not found")

lines_raw = cat.getObjectsByType(model.getType("GKPublicLine"))
lines = list(lines_raw.values()) if isinstance(lines_raw, dict) else list(lines_raw)
for line in lines[:3]:
    lid = line.getId()
    lname = str(line.getName() or "")[:50]
    print(f"\n--- Line {lid} '{lname}' ---")
    for mn in ("getSections", "getStops", "getRoute", "getRouteIds"):
        fn = getattr(line, mn, None)
        if not callable(fn):
            continue
        try:
            r = fn()
            if isinstance(r, (list, tuple)):
                print(f"  {mn}() -> list[{len(r)}]")
                for item in list(r)[:3]:
                    iid = item.getId() if hasattr(item, "getId") else item
                    print(f"    -> {iid}")
            elif hasattr(r, "getSections"):
                secs = r.getSections()
                n2 = len(secs) if secs else 0
                print(f"  {mn}() -> obj with getSections()[{n2}]")
            elif r is not None:
                iid = None
                try:
                    iid = r.getId()
                except Exception:
                    pass
                print(f"  {mn}() -> obj id={iid} type={type(r).__name__}")
            else:
                print(f"  {mn}() -> None")
        except Exception as e:
            print(f"  {mn}() ERROR: {e}")

# Also check first line's timetable
if lines:
    line = lines[0]
    try:
        tts = line.getTimeTables()
        print(f"\nTimeTables: {len(tts) if tts else 0}")
        for tt in (tts or [])[:2]:
            schs = tt.getSchedules()
            print(f"  TT '{tt.getName()}' schedules={len(schs) if schs else 0}")
            for sch in (schs or [])[:1]:
                deps = list(sch.getDepartureTimes())
                print(f"    depType={sch.getDepartureType()} ndeps={len(deps)}")
    except Exception as e:
        print(f"  getTimeTables ERROR: {e}")
