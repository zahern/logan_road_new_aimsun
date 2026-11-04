# -*- coding: utf-8 -*-
"""Resolution sweep: where does the time-indexed signal MILP stop closing?

Same synthetic corridor/junction, only the time grid changes. Minimum green is
kept at 6 SECONDS (so 6/stride steps), i.e. every row is the same traffic rule
observed on a coarser grid -- except that 6 s is not exactly representable
below stride=6, which is noted per row.

Synthetic instance: see _bench_time_milp.py. Measures shape, not KG.
"""
import time

import numpy as np
from scipy import sparse
from scipy.optimize import milp, LinearConstraint, Bounds

P, M = 8, 4
MU, K = 0.5, 80.0
A0 = 0.02
TAU_S = 15
SPLIT = 0.5
GMIN_S = 6


def build(n_jct, T, stride):
    gmin = max(1, int(round(GMIN_S / float(stride))))
    tau = max(1, int(round(TAU_S / float(stride))))
    a0 = A0 * stride
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
            for t in range(1, T - gmin):
                ent = [(x(i, p, t), float(gmin)), (x(i, p, t - 1), -float(gmin))]
                ent += [(x(i, p, t + k), -1.0) for k in range(gmin)]
                row(ent, -np.inf, 0.0)
        for m in range(M):
            p = m % P
            for t in range(T - 1):
                if i == 0 or t - tau < 0:
                    row([(Q(i, m, t + 1), 1.0), (Q(i, m, t), -1.0),
                         (d(i, m, t), 1.0)], a0, a0)
                else:
                    row([(Q(i, m, t + 1), 1.0), (Q(i, m, t), -1.0),
                         (d(i, m, t), 1.0),
                         (d(i - 1, m, t - tau), -SPLIT)], 0.0, 0.0)
                row([(d(i, m, t), 1.0), (x(i, p, t), -MU)], -np.inf, 0.0)
                row([(d(i, m, t), 1.0), (Q(i, m, t), -1.0)], -np.inf, 0.0)
                row([(Q(i, m, t + 1), 1.0)], -np.inf, K)

    A = sparse.csr_matrix((vals, (rows, cols)), shape=(r[0], nvar))
    c = np.zeros(nvar)
    for j in range(q0, q0 + nq):
        c[j] = 1.0
    integ = np.zeros(nvar); integ[:nx] = 1
    lo = np.zeros(nvar); hi = np.full(nvar, np.inf); hi[:nx] = 1.0
    return A, c, integ, lo, hi, np.array(lb), np.array(ub), nx


def run(n_jct, stride, horizon_s=120.0, limit_s=60.0):
    T = int(round(horizon_s / stride))
    A, c, integ, lo, hi, lb, ub, nbin = build(n_jct, T, stride)
    t0 = time.perf_counter()
    res = milp(c, constraints=LinearConstraint(A, lb, ub), integrality=integ,
               bounds=Bounds(lo, hi),
               options={'time_limit': limit_s, 'mip_rel_gap': 1e-4,
                        'disp': False})
    dt = time.perf_counter() - t0
    gap = getattr(res, 'mip_gap', None)
    print('%-30s bin=%6d rows=%7d %8.2fs status=%d%s gap=%s fun=%.1f'
          % ('%d jct, %g s grid, %ds' % (n_jct, stride, horizon_s),
             nbin, A.shape[0], dt, res.status,
             ' OPT' if res.status == 0 else ' LIMIT',
             ('%.1e' % gap) if gap is not None else 'n/a',
             res.fun if res.fun is not None else float('nan')))


if __name__ == '__main__':
    print('synthetic; resolution sweep, minimum green fixed at %.0f s' % GMIN_S)
    for s in (1, 2, 3, 5, 10):
        run(1, s, 120.0, 60.0)
    run(12, 5, 120.0, 120.0)
    run(12, 10, 120.0, 120.0)
