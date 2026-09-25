"""test_milp_solver.py -- verify an EXACT MILP solver is available for MILP_MPC.

Run in the Aimsun Python console (or a plain terminal with Aimsun's Python):
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\test_milp_solver.py").read())

Checks, in order of preference:
  1. OR-Tools CP-SAT  (exact; but its bundled abseil/protobuf can collide with
     Aimsun's DLLs -> WinError 127. If import CRASHES the process, that's the
     known issue and you must use HiGHS.)
  2. HiGHS via scipy.optimize.milp (scipy>=1.9; statically linked, in-process
     safe -- the recommended backend inside Aimsun).
Each importable backend then SOLVES a trivial MILP to prove it actually runs.
Prints which backend MILP_MPC's 'auto' mode would pick.
"""
print("=" * 64)
print("MILP SOLVER AVAILABILITY TEST")
print("=" * 64)

_ortools_ok = False
_highs_ok = False

# ── 1. OR-Tools CP-SAT ───────────────────────────────────────────────────────
try:
    from ortools.sat.python import cp_model as _cp
    print("[ortools] import OK")
    try:
        m = _cp.CpModel()
        x = m.NewIntVar(0, 10, "x")
        y = m.NewIntVar(0, 10, "y")
        m.Add(x + 2 * y <= 14)
        m.Add(3 * x - y >= 0)
        m.Maximize(3 * x + 2 * y)
        s = _cp.CpSolver()
        st = s.Solve(m)
        print(f"[ortools] SOLVE OK: status={s.StatusName(st)} "
              f"x={s.Value(x)} y={s.Value(y)} obj={s.ObjectiveValue()}")
        _ortools_ok = True
    except Exception as _e:
        print(f"[ortools] imported but SOLVE FAILED: {_e!r}")
except Exception as _e:
    print(f"[ortools] NOT available: {type(_e).__name__}: {_e}")

# ── 2. HiGHS via scipy.optimize.milp ─────────────────────────────────────────
try:
    import scipy
    from scipy.optimize import milp, LinearConstraint, Bounds
    from scipy.sparse import csr_matrix  # noqa: F401
    import numpy as _np
    print(f"[highs] scipy {scipy.__version__} import OK")
    try:
        # maximize 3x+2y  ->  minimize -(3x+2y), integer x,y in [0,10]
        c = _np.array([-3.0, -2.0])
        A = _np.array([[1.0, 2.0], [-3.0, 1.0]])
        cons = LinearConstraint(A, -_np.inf, [14.0, 0.0])
        res = milp(c=c, constraints=cons, integrality=_np.ones(2),
                   bounds=Bounds(0, 10))
        print(f"[highs] SOLVE OK: success={res.success} "
              f"x={res.x} obj={-res.fun if res.success else None}")
        _highs_ok = bool(res.success)
    except Exception as _e:
        print(f"[highs] imported but SOLVE FAILED: {_e!r}")
except Exception as _e:
    print(f"[highs] NOT available: {type(_e).__name__}: {_e}")

# ── verdict ──────────────────────────────────────────────────────────────────
print("-" * 64)
if _ortools_ok:
    print("VERDICT: MILP_MPC 'auto' -> OR-Tools (exact CP-SAT). MILP_MPC will run.")
elif _highs_ok:
    print("VERDICT: MILP_MPC 'auto' -> HiGHS (scipy.milp). MILP_MPC will run.")
    print("         (OR-Tools unavailable/unsafe here; HiGHS is the exact fallback.)")
else:
    print("VERDICT: NO exact solver available. MILP_MPC cannot run.")
    print("         Install one into Aimsun's Python, e.g.:")
    print("           <aimsun_python> -m pip install scipy>=1.9   (HiGHS, recommended)")
    print("           <aimsun_python> -m pip install ortools       (CP-SAT, may DLL-clash)")
print("=" * 64)
