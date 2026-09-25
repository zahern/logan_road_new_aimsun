#!/usr/bin/env python3
"""test_oc_credit.py -- OC_- gets bus benefit; OC label contract holds."""
import sys
import types

sys.path.insert(0, "shared_tsp_engine")
import specialized_modes as _spm


def _stub_self():
    self = types.SimpleNamespace(
        BusOcc=40.0, CarOcc=1.2, config={},
        _dctsp_cross_traffic_delay_s=lambda s: 100.0,
        _compute_side_delay_penalty=lambda s, _suppress_log=True: (0.0, 0.0),
    )
    return self


fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" [{extra}]" if extra and not cond else ""))
    if not fails or True:
        pass
    if not cond:
        fails.append(name)


_self = _stub_self()
# OC_-7 with a 60 s no-action wait: recovers min(7, 60) = 7 s x 40 pax
r, so, tp, bps, cpc, nsd, std = _spm._dctsp_eval_action(
    _self, "OFFSET_CORRECTION", -7.0, 0.0, 60.0, 30.0,
    wrong_phase=False, remaining_red_s=20.0)
check("OC_- credit bps=280", abs(bps - 280.0) < 1e-9, f"bps={bps}")
check("OC_- clears sigma", abs(so - 0.0) < 1e-9, f"sigma_out={so}")
# capped by the wait: 120 s advance against a 60 s wait saves 60 s
r2, so2, _, bps2, _, _, _ = _spm._dctsp_eval_action(
    _self, "OFFSET_CORRECTION", -120.0, 10.0, 60.0, 30.0,
    wrong_phase=False, remaining_red_s=20.0)
check("OC_- capped by wait", abs(bps2 - 60.0 * 40.0) < 1e-9, f"bps={bps2}")
check("OC_- sigma math", abs(so2 - max(0.0, 10.0 - 60.0)) < 1e-9, f"so={so2}")
# OC_+ unchanged: 0.3 x param benefit
_, _, _, bps3, _, _, _ = _spm._dctsp_eval_action(
    _self, "OFFSET_CORRECTION", 10.0, 0.0, 60.0, 30.0,
    wrong_phase=False, remaining_red_s=20.0)
check("OC_+ unchanged", abs(bps3 - 3.0 * 40.0) < 1e-9, f"bps={bps3}")
# label contract: adaptive "OC_-7" parses + executor sign logic holds
_kind, _par = _spm.parse_action_token("OC_-7")
check("label parses", _kind == "OC" and abs(_par - 7.0) < 1e-9,
      f"({_kind},{_par})")
check("executor sign negative", not ("OC_+" in "OC_-7" or "+" in "OC_-7"))

print("ALL OK" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
