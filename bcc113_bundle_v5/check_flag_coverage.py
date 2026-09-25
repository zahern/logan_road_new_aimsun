#!/usr/bin/env python3
"""Check: every set_reward_weights key must reach the engine somehow.

A key reaches the engine iff EITHER:
  (a) it exists as a top-level line in kg/intersection_controller.py
      (controller-file patch + bind_config), OR
  (b) it is in engine.py's AAPIInit run_config propagation tuple.
Otherwise the setting is silently dead.
"""
import re

eng = open("shared_tsp_engine/engine.py", encoding="utf-8-sig").read()
anchor = eng.find("Propagate all mode flags")
mtup = re.search(r"for _k in \((.*?)\)\s*:", eng[anchor:anchor + 8000], re.S)
tup = set(re.findall(r"'([A-Z0-9_]+)'", mtup.group(1)))

br = open("kg/batch_runner.py", encoding="utf-8-sig").read()
ib = br.find("bool_cfg = {")
jf = br.find("float_cfg = {", ib)
bool_end = br.find("}", br.find("PHASE_SEQUENCE_MODE"))
bool_keys = set(re.findall(r'"([A-Z0-9_]+)"', br[ib:bool_end]))
float_keys = set(re.findall(r'"([A-Z0-9_]+)"', br[jf:jf + 4500]))
keys = bool_keys | float_keys

ctl = open("kg/intersection_controller.py", encoding="utf-8-sig").read()
in_file = {k for k in keys if re.search(r"(?m)^" + k + r"\s*=", ctl)}

print(f"runner keys: {len(keys)} | in propagation tuple: {len(keys & tup)} | "
      f"in controller file: {len(in_file)}")
print("IN RUNNER, NOWHERE (dead settings):")
dead = sorted(keys - tup - in_file)
for k in dead:
    print("  ", k)
if not dead:
    print("   none -- all keys reach the engine")
