"""Micro-benchmark ctm_lightsim.rollout_block on engine-sized subnets.

Pure model cost only: no AAPI calls, no Aimsun. Real subnets in the KG corridor
land at 8-18 links x 8 cells x 30 steps, so those three sizes bracket the
in-engine cost of the CTM math itself; the [CTMTIME] instrument then gives the
in-engine total (math + AAPI geometry fetch + seeding).
"""
import sys
import time

sys.path.insert(0, 'shared_tsp_engine')

import ctm_lightsim as ls  # noqa: E402


class G:
    def __init__(self, length_m, lanes=1, v_free_kmh=50.0, w_back_kmh=18.0,
                 k_jam_vkm_lane=200.0, q_sat_vph_lane=1800.0, dt_s=2.0,
                 max_cells=12):
        self.length_m = length_m
        self.lanes = lanes
        self.v_free_kmh = v_free_kmh
        self.w_back_kmh = w_back_kmh
        self.k_jam_vkm_lane = k_jam_vkm_lane
        self.q_sat_vph_lane = q_sat_vph_lane
        self.dt_s = dt_s
        self.max_cells = max_cells

    @property
    def vf_ms(self):
        return max(self.v_free_kmh / 3.6, 1.0)

    @property
    def cell_len_m(self):
        return max(self.vf_ms * self.dt_s, 5.0)

    @property
    def n_cells(self):
        import math
        return max(1, min(int(math.ceil(max(self.length_m, 1.0) / self.cell_len_m)),
                          self.max_cells))

    @property
    def storage_pcu(self):
        return max(self.k_jam_vkm_lane * (self.cell_len_m / 1000.0)
                   * max(self.lanes, 1), 1.0)

    @property
    def cap_pcu_step(self):
        return max(self.q_sat_vph_lane / 3600.0 * max(self.lanes, 1) * self.dt_s, 1e-6)

    @property
    def w_ratio(self):
        return min(1.0, max(self.w_back_kmh / 3.6, 0.1) / self.vf_ms)


def chain(n, length_m=120.0, veh=5):
    geoms = {i: G(length_m) for i in range(1, n + 1)}
    serving = {i: {i - 1} for i in range(1, n)}
    targets = {i - 1: [i + 1] for i in range(1, n)}
    ring = list(range(n - 1))
    vehicles = {i: veh for i in geoms}
    return geoms, serving, targets, ring, vehicles


print('cells/step per call = n_links * n_cells * steps')
for n in (8, 12, 18):
    geoms, serving, targets, ring, vehicles = chain(n)
    gseq = {p: [True] * 30 for p in ring}
    ls.rollout_block(geoms, vehicles, {}, serving, gseq, ring, targets, 30, 2.0)
    iters = 300
    t0 = time.perf_counter()
    for _ in range(iters):
        ls.rollout_block(geoms, vehicles, {}, serving, gseq, ring, targets, 30, 2.0)
    dt = (time.perf_counter() - t0) / iters
    cells = sum(g.n_cells for g in geoms.values())
    print('links=%2d cells=%3d cell_steps=%6d   us/call=%9.0f   ns/cell_step=%6.0f'
          % (n, cells, cells * 30, dt * 1e6, dt * 1e9 / (cells * 30)))
