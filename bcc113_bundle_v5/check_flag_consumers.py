#!/usr/bin/env python3
"""check_flag_consumers.py -- prove each set_reward_weights key is READ live.

A key is EFFECTIVE iff some consumer reads it per-run from either:
  (a) engine globals() populated by the AAPIInit run_config propagation tuple
      (globals().get('KEY') / globals()['KEY'] in engine.py), or
  (b) _spm module attrs in _spm.MODE_FLAGS (setattr per run), or
  (c) a top-level line in kg/intersection_controller.py (bound at load --
      static for the session, so per-run changes do NOT take effect this way).

A key in NONE of (a)/(b)/(c) is dead: arms setting it change nothing.
"""
import re

eng = open("shared_tsp_engine/engine.py", encoding="utf-8-sig").read()
spm = open("shared_tsp_engine/specialized_modes.py", encoding="utf-8-sig").read()
ctl = open("kg/intersection_controller.py", encoding="utf-8-sig").read()
br = open("kg/batch_runner.py", encoding="utf-8-sig").read()

# runner key universe = bool_cfg + float_cfg dict literals
ib = br.find("bool_cfg = {")
jf = br.find("float_cfg = {", ib)
bool_end = br.find("}", br.find("PHASE_SEQUENCE_MODE"))
bkeys = set(re.findall(r'"([A-Z0-9_]+)"', br[ib:bool_end]))
fkeys = set(re.findall(r'"([A-Z0-9_]+)"', br[jf:jf + 4500]))
keys = sorted(bkeys | fkeys)

# (a) engine-propagation tuple
anchor = eng.find("Propagate all mode flags")
mtup = re.search(r"for _k in \((.*?)\)\s*:", eng[anchor:anchor + 9000], re.S)
tup = set(re.findall(r"'([A-Z0-9_]+)'", mtup.group(1)))
# (b) _spm.MODE_FLAGS list
mspm = re.search(r"MODE_FLAGS = \[(.*?)\]", spm, re.S)
spmflags = set(re.findall(r"'([A-Z0-9_]+)'", mspm.group(1)))

print(f"{'key':32s} {'AAPIprop':8s} {'spmflag':7s} {'ctlfile':7s}  verdict")
print("-" * 80)
dead, static_only = [], []
for k in keys:
    in_tup = k in tup
    in_spm = k in spmflags
    in_ctl = re.search(r"(?m)^" + k + r"\s*=", ctl) is not None
    # consumer reads: engine globals(), _spm attr, or controller-module attr
    r_eng = bool(re.search(r"globals\(\)\.get\(['\"]" + k + r"['\"]", eng)
                 or re.search(r"[^_.a-zA-Z]" + k + r"\b", eng))
    r_spm = ("_spm." + k in spm) or ("getattr(_spm, '" + k + "'") in eng \
        or ('getattr(_spm, "' + k + '"') in eng
    r_ctl = bool(re.search(r"[^_.a-zA-Z]" + k + r"\b", ctl))
    live = (in_tup and (r_eng or r_spm)) or (in_spm and r_spm) or (in_ctl and r_ctl)
    tag = "LIVE" if live else ("STATIC-ONLY" if in_ctl else "DEAD")
    if tag == "DEAD":
        dead.append(k)
    if tag == "STATIC-ONLY":
        static_only.append(k)
    print(f"{k:32s} {str(in_tup):8s} {str(in_spm):7s} {str(in_ctl):7s}  {tag}")
print("-" * 80)
print(f"DEAD ({len(dead)}): {dead}")
print(f"STATIC-ONLY ({len(static_only)}): {static_only}")
