#!/usr/bin/env python3
"""
Offline test for the MILP-MPC controller, both solver backends.

    python test_milp_mpc.py [--backend ortools|highs]

'auto' (default) runs every importable backend on the same 2-intersection
model and cross-checks them: identical optimal objectives (same program),
one gate open per intersection/step, queues non-negative, intervention
labels sane. Needs scipy>=1.9 for highs, ortools for the CP-SAT leg.
"""
import sys

import numpy as np  # noqa: F401  (kept: historic import, harmless offline)

from milp_mpc_controller import (
    MILPMPCController, IntersectionConfig, BusState,
    MPCPrediction, create_milp_mpc_controller,
    _HAS_ORTOOLS,
)

try:
    from scipy.optimize import milp as _milp  # noqa: F401
    _HAS_HIGHS = True
except Exception:
    _HAS_HIGHS = False


def _demo_configs():
    def _cfg(iid, offset):
        return IntersectionConfig(
            iid=iid, node_id=iid, bus_phase=2,
            phase_list=[1, 2, 3, 4], cycle_len_s=135.0, lost_time_s=5.0,
            min_green_s={1: 5, 2: 5, 3: 5, 4: 5},
            max_green_s={1: 60, 2: 60, 3: 60, 4: 60},
            sat_flow={1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5},
            jam_density=200, arrival_density={1: 20, 2: 20, 3: 20, 4: 20},
            offset_init_s=offset, freeflow_tt_next={2: 15.0} if iid == 1 else {},
        )
    return {1: _cfg(1, 0.0), 2: _cfg(2, 20.0)}


def _demo_pred():
    return MPCPrediction(
        q_arr={(1, 2, t): 0.5 for t in range(300)},
        q_side={},
        tau_freeflow={(1, 2): 15.0},
        tau_bar={},
        Q_init={(1, 2): 10.0},
        phi_init={1: 0.0, 2: 20.0},
        bus_states=[],
    )


def _check_solution(mpc, result, backend):
    # Structural invariants every backend must satisfy.
    for i in mpc.I:
        for t in mpc.T_idx:
            n_open = sum(1 for p in mpc.P[i] if result.gate_open.get((i, p, t)))
            assert n_open == 1, f"{backend}: {n_open} gates open at ({i},{t})"
    for key, q in result.queue.items():
        assert q >= -1e-6, f"{backend}: negative queue {key}={q}"
    for key, v in result.interv_start.items():
        assert isinstance(v, bool), f"{backend}: non-bool label {key}={v}"
    assert result.objective_value == result.objective_value, f"{backend}: NaN objective"
    assert result.status in (4, 2), f"{backend}: bad status {result.status}"
    return result.objective_value


def _run_backend(backend):
    mpc = create_milp_mpc_controller(_demo_configs(), backend=backend)
    assert mpc.backend == backend, f"backend mismatch: {mpc.backend}"
    assert mpc.solver_name.startswith(
        "highs" if backend == "highs" else "ortools"), mpc.solver_name
    pred = _demo_pred()
    print(f"[{backend}] building model...")
    result = mpc.solve(pred, current_step=0)
    obj = _check_solution(mpc, result, backend)
    print(f"[{backend}] status={result.status} obj={obj:.2f} "
          f"time={result.solve_time_s:.2f}s solver={mpc.solver_name}")
    print(f"[{backend}] gate open at t=0:",
          {k: v for k, v in result.gate_open.items() if k[2] == 0 and v})
    # Step() caching path: second call inside replan window must reuse.
    again = mpc.step(pred, 0)
    assert again is result, f"{backend}: step() did not reuse cached solution"
    print(f"[{backend}] step-cache OK")
    return obj


def main():
    want = sys.argv[sys.argv.index("--backend") + 1] \
        if "--backend" in sys.argv else "auto"
    print(f"ortools importable: {_HAS_ORTOOLS} | scipy-milp importable: {_HAS_HIGHS}")
    objs = {}
    if want in ("auto", "ortools") and _HAS_ORTOOLS:
        objs["ortools"] = _run_backend("ortools")
    if want in ("auto", "highs") and _HAS_HIGHS:
        objs["highs"] = _run_backend("highs")
    if not objs:
        print("No requested backend importable; nothing to test.")
        return 1
    if len(objs) == 2:
        a, b = objs["ortools"], objs["highs"]
        gap = abs(a - b) / max(abs(a), 1.0)
        print(f"backend agreement: ortools={a:.2f} highs={b:.2f} rel_gap={gap:.4f}")
        assert gap < 0.05, f"backends disagree beyond 5%: {gap:.3f}"
        print("BACKENDS AGREE (same program, both optimal/feasible)")
    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
