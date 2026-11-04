# -*- coding: utf-8 -*-
"""How long does a time-expanded signal MILP actually take?

SYNTHETIC benchmark: same dimensions and constraint shape as the manuscript's
program (one binary per junction-phase-step, integer queues and discharges, a
queue recursion, a discharge cap, storage, minimum green, intergreen), but the
data are made up. This measures the SHAPE, not the KG instance.

Reported per case: variables, binaries, rows, wall time, status, gap.
"""
import time

import numpy as np
from scipy import sparse
from scipy.optimize import milp, LinearConstraint, Bounds

P, M = 8, 4            # phases, movements
MU, K = 0.5, 80.0      # saturation veh/s, storage veh
GMIN = 6               # min green, steps
A0 = 0.02              # boundary demand veh/s (low enough to stay feasible)
TAU = 15               # link lag, steps
SPLIT = 0.5            # fraction carried downstream


def build(n_jct, T):
    nx = n_jct * P * T
    nq = n_jct * M * T
    x0 = 0
    q0 = nx
    d0 = nx + nq
    nvar = nx + 2 * nq

    rows, cols, vals, lb, ub = [], [], [], [], []
    r = [0]

    def add(i, j, v):
        rows.append(r[0]); cols.append(j); vals.append(v)

    def row(entries, lo, hi):
        for j, v in entries:
            add(r[0], j, v)
        lb.append(lo); ub.append(hi); r[0] += 1

    def x(i, p, t): return x0 + (i * P + p) * T + t
    def Q(i, m, t): return q0 + (i * M + m) * T + t
    def d(i, m, t): return d0 + (i * M + m) * T + t

    for i in range(n_jct):
        for t in range(T):
            # at most one phase open (all-red carries the intergreen)
            row([(x(i, p, t), 1.0) for p in range(P)], 0.0, 1.0)
        # intergreen: one all-red step between any two different phases
        for p in range(P):
            for p2 in range(P):
                if p2 == p:
                    continue
                for t in range(T - 1):
                    row([(x(i, p, t), 1.0), (x(i, p2, t + 1), 1.0)],
                        -np.inf, 1.0)
        # minimum green when a phase opens
        for p in range(P):
            for t in range(1, T - GMIN):
                ent = [(x(i, p, t), float(GMIN)), (x(i, p, t - 1), -float(GMIN))]
                for k in range(GMIN):
                    ent.append((x(i, p, t + k), -1.0))
                row(ent, -np.inf, 0.0)
        for m in range(M):
            p = m % P
            for t in range(T - 1):
                if i == 0 or t - TAU < 0:
                    row([(Q(i, m, t + 1), 1.0), (Q(i, m, t), -1.0),
                         (d(i, m, t), 1.0)], A0, A0)
                else:
                    row([(Q(i, m, t + 1), 1.0), (Q(i, m, t), -1.0),
                         (d(i, m, t), 1.0),
                         (d(i - 1, m, t - TAU), -SPLIT)], 0.0, 0.0)
                row([(d(i, m, t), 1.0), (x(i, p, t), -MU)], -np.inf, 0.0)
                row([(d(i, m, t), 1.0), (Q(i, m, t), -1.0)], -np.inf, 0.0)
                row([(Q(i, m, t + 1), 1.0)], -np.inf, K)

    A = sparse.csr_matrix((vals, (rows, cols)), shape=(r[0], nvar))
    c = np.zeros(nvar)
    for i in range(n_jct):
        for m in range(M):
            for t in range(T):
                c[Q(i, m, t)] = 1.0
    # binaries on the phase gates only; queues/discharges continuous so the
    # flow equalities stay feasible (integer flows would need integer demand)
    integ = np.zeros(nvar)
    integ[:nx] = 1
    lo = np.zeros(nvar); hi = np.full(nvar, np.inf)
    hi[:nx] = 1.0
    return A, c, integ, lo, hi, np.array(lb), np.array(ub), nx


def run(n_jct, T, limit_s=120.0):
    A, c, integ, lo, hi, lb, ub, nbin = build(n_jct, T)
    t0 = time.perf_counter()
    res = milp(c, constraints=LinearConstraint(A, lb, ub), integrality=integ,
               bounds=Bounds(lo, hi),
               options={'time_limit': limit_s, 'mip_rel_gap': 1e-3, 'disp': False})
    dt = time.perf_counter() - t0
    gap = getattr(res, 'mip_gap', None)
    print('%-22s vars=%6d bin=%6d rows=%7d  %7.2fs  status=%d%s gap=%s'
          % ('%d jct x %d steps' % (n_jct, T), A.shape[1], nbin, A.shape[0],
             dt, res.status,
             '  (OPT)' if res.status == 0 else '',
             ('%.2e' % gap) if gap is not None else 'n/a'))
    return dt, res.status


if __name__ == '__main__':
    print('synthetic; scipy %s, HiGHS' % __import__('scipy').__version__)
    run(1, 120, 60)      # one junction, one cycle
    run(1, 600, 120)     # one junction, 5 cycles
    run(12, 120, 120)    # corridor, one cycle
    run(12, 360, 180)    # corridor, 3 cycles
