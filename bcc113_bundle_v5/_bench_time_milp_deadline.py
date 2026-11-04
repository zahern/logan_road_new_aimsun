# -*- coding: utf-8 -*-
"""What do you get inside a real-time budget?

1 s time-indexed grid, one cycle horizon, killed after 1/5/10/30 s. Reports the
incumbent cost and the proven gap at the deadline -- i.e. what a controller
would actually commit.

Synthetic instance: see _bench_time_milp.py.
"""
import time

import numpy as np
from scipy import sparse
from scipy.optimize import milp, LinearConstraint, Bounds

P, M = 8, 4
MU, K = 0.5, 80.0
A0 = 0.02
TAU, SPLIT, GMIN = 15, 0.5, 6


def build(n_jct, T):
    nx, nq = n_jct * P * T, n_jct * M * T
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
                if p2 != p:
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
    c = np.zeros(nvar)
    for j in range(q0, q0 + nq):
        c[j] = 1.0
    integ = np.zeros(nvar); integ[:nx] = 1
    lo = np.zeros(nvar); hi = np.full(nvar, np.inf); hi[:nx] = 1.0
    return A, c, integ, lo, hi, np.array(lb), np.array(ub)


def run(n_jct, T, limit_s):
    A, c, integ, lo, hi, lb, ub = build(n_jct, T)
    t0 = time.perf_counter()
    res = milp(c, constraints=LinearConstraint(A, lb, ub), integrality=integ,
               bounds=Bounds(lo, hi),
               options={'time_limit': limit_s, 'mip_rel_gap': 0.0,
                        'disp': False})
    dt = time.perf_counter() - t0
    print('budget %5.1fs  jct=%2d  wall=%6.2fs status=%d incumbent=%s '
          'proven_bound=%s gap=%s'
          % (limit_s, n_jct, dt, res.status,
             ('%.1f' % res.fun) if res.fun is not None else 'n/a',
             ('%.1f' % res.mip_dual_bound) if getattr(res, 'mip_dual_bound',
                                                      None) is not None else 'n/a',
             ('%.0f%%' % (100 * res.mip_gap))
             if getattr(res, 'mip_gap', None) is not None else 'n/a'))


if __name__ == '__main__':
    print('synthetic; 1 s grid, one 120 s cycle, hard deadline')
    for lim in (1.0, 5.0, 10.0, 30.0):
        run(1, 120, lim)
    run(12, 120, 10.0)
