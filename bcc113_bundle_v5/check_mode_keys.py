#!/usr/bin/env python3
"""check_mode_keys.py -- verify the 5 mode-dispatch keys propagate per run."""
import re

eng = open("shared_tsp_engine/engine.py", encoding="utf-8-sig").read()
anchor = eng.find("Propagate all mode flags")
mtup = re.search(r"for _k in \((.*?)\)\s*:", eng[anchor:anchor + 9000], re.S)
tup = set(re.findall(r"'([A-Z0-9_]+)'", mtup.group(1)))

br = open("kg/batch_runner.py", encoding="utf-8-sig").read()
ok = True
for k in ["CONTROL_MODE", "COORDINATED_TSP", "COORDINATION_ALGO",
          "GROUP_BASED_BUS_PRIORITY", "TSP_ACTIVE_INTERSECTIONS",
          "BUS_PREDICTOR_TYPE"]:
    in_tup = k in tup
    written = ('"%s = "' % k) in br or ("'%s = '" % k) in br or (k + " = ") in br
    # engine reads the bare global at runtime (not just init)?
    reads = len(re.findall(r"[^_.a-zA-Z'\"]" + k + r"\b", eng))
    print(f"{k:28s} tuple={in_tup!s:5s} written_by_batch={written!s:5s} engine_refs={reads}")
    if k != "BUS_PREDICTOR_TYPE" and not in_tup:
        ok = False
print("MODE KEYS OK" if ok else "MODE KEYS GAP")
