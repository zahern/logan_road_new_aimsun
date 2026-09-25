#!/usr/bin/env python3
"""
Demand-scalar test -- verifies the Phase-3 demand axis is live.

Single mechanism ONLY: console-side GKODMatrix.multiply() via
batch_runner.scale_od_matrices_multiply() (commit + read-back assert).
The old version of this script double-scaled (multiply AND schedule factors)
and reset its anti-compounding cache every iteration; both bugs are gone.

Design: champion DCTSP_MARL config, ONE seed (300),
DEMAND_SCALARS = [1.0, 0.6, 0.8, 1.2, 1.4, 1.6] (1.0 first anchors the baseline).

PASS criteria (printed at the end):
  * every level verifies inside scale_od_matrices_multiply (else it raises), AND
  * N_DistinctCars / Net_TotalFlowVeh respond to the scalar
    (x1.6 distinctly above x0.6; not all rows byte-identical).

Run inside the Aimsun Python console with the corridor model open.
Result -> test_demand_scalars_<corridor>.csv (cleared at start).
Demand is restored to 1.0x at the end (finally block).
"""

import sys
import os
import time
import traceback

try:
    from PyANGKernel import GKSystem
except ImportError:
    print("ERROR: Run inside Aimsun Python console!")
    sys.exit(1)

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import champion_search as _cs
_br = _cs._br

print("Using batch_runner from: " + _br.__file__)

CORRIDOR = _cs.CORRIDOR

ARM = {
    "name": "DCTSP_MARL",
    "strategy": "GLOBAL_REWARD",
    "coordinated": True,
    "coordination_algo": "KALMAN",
    "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0,
        "REWARD_BETA": 1.0, "REWARD_GAMMA": 1.0,
        "DCTSP_GREEN_REALLOC_MODE": True,
        "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
        "DCTSP_W_H": 0.50, "DCTSP_CAR_WEIGHT": 1.00,
        "DECIDER_COST_VETO_RATIO": 3.0,
    },
}

# 1.0 FIRST: anchors the multiply baseline on the pristine model.
DEMAND_SCALARS = [1.0, 0.6, 0.8, 1.2, 1.4, 1.6]
TEST_SEED = 300
RESULTS_CSV = os.path.join(_HERE, "test_demand_scalars_" + CORRIDOR + ".csv")

# Patch controller (once -- identical for every level).
_br.set_control_mode("GLOBAL_REWARD", _br.CONTROLLER_PATH, None)
_br.set_coordinated(_br.CONTROLLER_PATH, True)
_br.set_coordination_algo(_br.CONTROLLER_PATH, "KALMAN")
rov = dict(ARM["reward_overrides"])
_numeric = {k: v for k, v in rov.items() if k != "GLOBAL_REWARD_MODE"}
_br.set_reward_weights(_br.CONTROLLER_PATH, _numeric)

print("=" * 70)
print("DEMAND SCALAR TEST - corridor=" + CORRIDOR)
print("Scalars: " + str(DEMAND_SCALARS))
print("Output: " + os.path.abspath(RESULTS_CSV))
print("=" * 70)

try:
    if os.path.exists(RESULTS_CSV):
        os.remove(RESULTS_CSV)
except Exception:
    pass

od_state = {}  # ONE persistent multiply state for the whole sweep -- never reset inside the loop
rows = []

try:
    for idx, scalar in enumerate(DEMAND_SCALARS):
        label = "DCTSP_MARL_Dx{:g}".format(scalar)
        print("\n--- [{}/{}] Running {} ---".format(idx + 1, len(DEMAND_SCALARS), label))

        # 1. THE demand lever (single mechanism). Raises on verification
        #    failure -- aborts here instead of appending flat rows.
        try:
            _br.scale_od_matrices_multiply(scalar, od_state)
        except Exception:
            traceback.print_exc()
            raise

        # 2. Single run config / replication / seed / run.
        _br.write_run_config(
            "DCTSP_MARL", "GLOBAL_REWARD", TEST_SEED, scalar,
            True, "KALMAN", _br.RUN_CONFIG_PATH,
            global_reward_mode=True, reward_cfg=rov,
            bus_predictor="ADAPTIVE_KALMAN",
            results_csv_name=os.path.basename(RESULTS_CSV))

        rep = _br.get_first_replication()
        _br.set_seed(rep, TEST_SEED)

        try:
            _br.run_replication(rep)
        except Exception:
            print("  EXCEPTION during run:")
            traceback.print_exc()
            continue

        # 3. Collect metrics.
        try:
            m = _br.collect_run_metrics(
                _br.PROJECT_DIR, "GLOBAL_REWARD", TEST_SEED, scalar,
                "DCTSP_MARL", True, 0.0, True,
                bus_predictor="ADAPTIVE_KALMAN")

            if m and m.get("run_success"):
                m["demand_scalar"] = scalar
                _br.append_master_csv(RESULTS_CSV, m)
                flow = m.get("stats_Net_TotalFlowVeh", 0)
                cars = m.get("stats_N_DistinctCars", 0)
                delay = m.get("stats_TotalPassDelay_hrs", 0)
                obj = m.get("stats_Objective_PaxPerDelayHr", 0)
                print("  Flow: {} | Cars: {} | Delay: {} | Obj: {}".format(flow, cars, delay, obj))
                rows.append({"scalar": scalar, "flow": flow, "cars": cars,
                             "delay": delay, "obj": obj})
            else:
                print("  FAILED: {}".format(m.get("run_success") if m else None))
        except Exception:
            print("  Metrics error:")
            traceback.print_exc()

        time.sleep(2)
finally:
    # Restore 1.0x demand; never leave the model at a swept level.
    # finally must not throw (integer-cell rounding note: +/-1 trip/cell vs
    # pristine is possible; reload the model for bit-exact pristine state).
    try:
        _br.scale_od_matrices_multiply(1.0, od_state)
    except Exception as _re:
        print("WARNING: OD restore to 1.0x failed: {} -- reload the model "
              "before the next sweep.".format(_re))

# ── Verdict (sanity gate: the old script produced 14/15 byte-identical rows) ──
print("\n" + "=" * 70)
print("RESULTS: " + os.path.abspath(RESULTS_CSV))
print("{:>7} | {:>9} | {:>6} | {:>10} | {:>9}".format(
    "scalar", "totalFlow", "cars", "paxDelay_h", "obj"))
print("-" * 55)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


for r in rows:
    print("{:>7.2f} | {:>9.0f} | {:>6d} | {:>10.2f} | {:>9.3f}".format(
        _f(r["scalar"]), _f(r["flow"]), int(_f(r["cars"])),
        _f(r["delay"]), _f(r["obj"])))

if len(rows) >= 2:
    _flows = sorted(set(_f(r["flow"]) for r in rows))
    _cars = sorted(set(_f(r["cars"]) for r in rows))
    _r06 = next((r for r in rows if abs(_f(r["scalar"]) - 0.6) < 1e-9), None)
    _r16 = next((r for r in rows if abs(_f(r["scalar"]) - 1.6) < 1e-9), None)
    if len(_flows) == 1 and len(_cars) == 1:
        print("FAIL: all {} rows byte-identical (flow={}, cars={}) -- demand "
              "did NOT scale.".format(len(rows), _flows[0], _cars[0]))
    elif _r06 is not None and _r16 is not None and _f(_r16["cars"]) > _f(_r06["cars"]):
        print("PASS: demand axis live (x0.6 cars={:.0f} -> x1.6 cars={:.0f}).".format(
            _f(_r06["cars"]), _f(_r16["cars"])))
    else:
        print("INCONCLUSIVE: rows vary but not monotonically -- inspect the CSV "
              "before running Phase 3.")
else:
    print("FAIL: fewer than 2 successful runs -- no verdict possible.")
print("=" * 70)
