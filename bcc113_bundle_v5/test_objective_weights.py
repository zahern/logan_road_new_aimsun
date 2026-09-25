#!/usr/bin/env python3
"""test_objective_weights.py -- pin the pure-delay + small-schedule objective.

Decision layer (controller files): WOBJ_ALPHA/BETA/GAMMA == 1.0/1.0/0.1.
Reporting layer (Simulation_Stats): WOBJ_W_Z3 default == 0.1 (both the
run_config-namespace default and the computation fallback).
"""
import io
import re
import sys

fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


def read(p):
    return io.open(p, encoding="utf-8-sig", errors="ignore").read()


for corr in ("kg", "logan_road_new"):
    txt = read(f"{corr}/intersection_controller.py")
    for key, want in (("WOBJ_ALPHA", 1.0), ("WOBJ_BETA", 1.0),
                      ("WOBJ_GAMMA", 0.1)):
        m = re.search(rf"^{key}\s*=\s*([0-9.]+)", txt, re.M)
        got = float(m.group(1)) if m else None
        check(f"{corr} {key}=={want}", got is not None and abs(got - want) < 1e-9,
              f"got={got}")

for corr in ("kg", "logan_road_new"):
    txt = read(f"{corr}/Simulation_Stats.py")
    m1 = re.search(r"_ns\.get\('WOBJ_W_Z3',\s*([0-9.]+)\)", txt)
    m2 = re.search(r"getattr\(self,\s*'WOBJ_W_Z3',\s*([0-9.]+)\)", txt)
    g1 = float(m1.group(1)) if m1 else None
    g2 = float(m2.group(1)) if m2 else None
    check(f"{corr} WOBJ_W_Z3 namespace==0.1", g1 is not None and abs(g1 - 0.1) < 1e-9,
          f"got={g1}")
    check(f"{corr} WOBJ_W_Z3 fallback==0.1", g2 is not None and abs(g2 - 0.1) < 1e-9,
          f"got={g2}")

print("ALL OK" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
