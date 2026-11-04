# -*- coding: utf-8 -*-
"""Diagnose WHY the time-indexed signal MILP does not close.

Same synthetic instance, four variants on one junction x one cycle (T=120,
960 binaries):
  A  min total queue          (the manuscript's objective shape)
  B  LP relaxation of A       (the bound branch-and-bound is working with)
  C  max total discharge      (throughput objective instead)
  D  min queue at 5 s steps   (coarser grid, 4x fewer binaries)
"""
import time

import numpy as np
from scipy import sparse
from scipy.optimize import milp, LinearConstraint, Bounds

P, M = 8, 4
MU, K = 0.5, 80.0
GMIN = 6
A0 = 0.02
TAU = 15
SPLIT = 0.5


def build(n_jct, T, stride=1):
    nx = n_jct * P * T
    nq = n_jct * M * T
    x0, q0, d0 = 0, nx, nx + nq
    nvar = nx + 2 * nq
    rows, cols, vals, lb, ub = [], [], [], [], []
    r = [0]

    def row(entries, lo, hi):
        for j, v in entries:
            rows.append(r[0]); cols.append(j); vals.append(v)
        lb.append(lo); ub.append(hi); r[0] += 1

    def x(i, p, t): return x0 + (i * P + p) * T + t
    def Q(i, m, t): return q0 + (i * M + m) * T + t
    def d(i, m, t): return d0 + (i * M + m) * T + t

    for i in range(n_jct):
        for t in range(T):
            row([(x(i, p, t), 1.0) for p in range(P)], 0.0, 1.0)
        for p in range(P):
            for p2 in range(P):
                if p2 == p:
                    continue
                for t in range(T - 1):
                    row([(x(i, p, t), 1.0), (x(i, p2, t + 1), 1.0)],
                        -np.inf, 1.0)
        for p in range(P):
            for t in range(1, T - GMIN):
                ent = [(x(i, p, t), float(GMIN)), (x(i, p, t - 1), -float(GMIN))]
                ent += [(x(i, p, t + k), -1.0) for k in range(GMIN)]
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
    return A, np.array(lb), np.array(ub), nvar, nx, q0, d0, nq


def solve(label, n_jct, T, kind='queue', integer=True, limit_s=60.0):
    A, lb, ub, nvar, nx, q0, d0, nq = build(n_jct, T)
    c = np.zeros(nvar)
    if kind == 'queue':
        for j in range(q0, q0 + nq):
            c[j] = 1.0
    else:
        for j in range(d0, d0 + nq):
            c[j] = -1.0
    integ = np.zeros(nvar)
    if integer:
        integ[:nx] = 1
    lo = np.zeros(nvar); hi = np.full(nvar, np.inf); hi[:nx] = 1.0
    t0 = time.perf_counter()
    res = milp(c, constraints=LinearConstraint(A, lb, ub), integrality=integ,
               bounds=Bounds(lo, hi),
               options={'time_limit': limit_s, 'mip_rel_gap': 1e-4,
                        'disp': False})
    dt = time.perf_counter() - t0
    gap = getattr(res, 'mip_gap', None)
    bound = getattr(res, 'mip_dual_bound', None)
    fun = ('%12.3f' % res.fun) if res.fun is not None else '        n/a'
    print('%-40s %7.2fs status=%d fun=%s bound=%s gap=%s'
          % (label, dt, res.status, fun,
             ('%.3f' % bound) if bound is not None else 'n/a',
             ('%.1e' % gap) if gap is not None else 'n/a'))
    return res


if __name__ == '__main__':
    print('synthetic 1 junction, HiGHS')
    solve('A  min queue, 1 s, integer  (T=120)', 1, 120, 'queue', True, 60)
    solve('B  min queue, 1 s, LP relax  (T=120)', 1, 120, 'queue', False, 60)
    solve('C  max discharge, 1 s, integer(T=120)', 1, 120, 'disch', True, 60)
    solve('D  min queue, 5 s grid, integer(T=24)', 1, 24, 'queue', True, 60)
