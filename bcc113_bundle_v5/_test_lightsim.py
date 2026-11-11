"""Local unit test for ctm_lightsim (no Aimsun / SUMO / cluster needed).

Chain: link 1 -> link 2 -> link 3, phase 0 serves 1->2, phase 1 serves 2->3, so
the receiving link of phase 0 can actually drain and its occupancy means
something.

Checks:
  1. mass conservation inside the modelled subnet
  2. free downstream gives a low block and real discharge
  3. a full downstream gives block 1.0 and chokes discharge
  4. a red mask moves nothing
  5. block always in [0, 1]
  6. empty subnet fails open
"""
import sys

sys.path.insert(0, 'shared_tsp_engine')

import ctm_lightsim as ls  # noqa: E402


class G:
    """Minimal stand-in for ctm_twoclass.ApproachGeom (same formulas)."""

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


GEOMS = {1: G(200.0), 2: G(200.0), 3: G(200.0)}
SERVING = {1: {0}, 2: {1}}          # SECTION -> {phases}, as Engine builds it
TARGETS = {0: [2], 1: [3]}
RING = [0, 1]

FAILS = []


def chk(name, cond, detail=''):
    print(('PASS  ' if cond else 'FAIL  ') + name + ('   ' + detail if detail else ''))
    if not cond:
        FAILS.append(name)


def moved_p0(veh, steps=30):
    """Discharge of phase 0 (1->2) ONLY: phase 1 held red, so `moved` is 1->2.
    Without this the pre-seeded jam also drains through phase 1 and inflates
    the total, which has nothing to do with spillback choking phase 0."""
    links = ls.build_links(GEOMS, veh)
    gseq = {0: [True] * steps, 1: [False] * steps}
    _peak, moved = ls.simulate(links, {1: {2}, 2: {3}}, SERVING, gseq, RING,
                              TARGETS, steps, 2.0)
    return moved


def run(veh, green=True, green1=True, steps=30):
    links = ls.build_links(GEOMS, veh)
    total0 = sum(sum(L['n']) for L in links.values())
    gseq = {0: [green] * steps, 1: [green1] * steps}
    peak, moved = ls.simulate(links, {1: {2}, 2: {3}}, SERVING, gseq, RING,
                              TARGETS, steps, 2.0)
    total1 = sum(sum(L['n']) for L in links.values())
    block = ls.rollout_block(GEOMS, veh, {1: {2}, 2: {3}}, SERVING, gseq, RING,
                             TARGETS, steps, 2.0)
    return total0, total1, moved, peak, block, links


# 1 + 2: free downstream, real sink
t0, t1, moved, peak, block, links = run({1: 10, 2: 0, 3: 0})
chk('mass conserved (free downstream)', abs(t0 - t1) < 1e-9,
    'before=%.2f after=%.2f' % (t0, t1))
m_free = moved_p0({1: 10, 2: 0, 3: 0})
chk('vehicles actually discharge', m_free > 0.0, 'moved(1->2)=%.2f' % m_free)
chk('free downstream block is low', block.get(0, 0.0) < 0.5,
    'block=%.3f' % block.get(0, 0.0))

# 3: jammed receiver
N = links[2]['N']
K = links[2]['K']
t0j, t1j, movedj, peakj, blockj, linksj = run({1: 10, 2: K * N, 3: 0})
chk('jammed receiver gives block 1.0', abs(blockj.get(0, 0.0) - 1.0) < 1e-9,
    'block=%.3f' % blockj.get(0, 0.0))
m_jam = moved_p0({1: 10, 2: K * N, 3: 0})
chk('jammed receiver chokes discharge', m_jam < m_free,
    'jammed(1->2)=%.2f vs free(1->2)=%.2f' % (m_jam, m_free))
chk('mass conserved (jammed)', abs(t0j - t1j) < 1e-9,
    'before=%.2f after=%.2f' % (t0j, t1j))

# 4: red mask on the served phase
r0, r1, movedr, _p, _b, _l = run({1: 10, 2: 0, 3: 0}, green=False)
chk('red moves nothing', movedr == 0.0, 'moved=%.2f' % movedr)
chk('red keeps mass', abs(r0 - r1) < 1e-9)

# 5: bounds over a sweep
worst = 0.0
bad = ''
for va in (0, 1, 5, 20, 60):
    for vb in (0, 1, 5, 20, 60):
        for vc in (0, 30):
            _a, _b2, _c, _d, blk, _e = run({1: va, 2: vb, 3: vc})
            for v in blk.values():
                worst = max(worst, v)
                if not (0.0 <= v <= 1.0):
                    bad = 'va=%d vb=%d blk=%.4f' % (va, vb, v)
chk('block within [0,1] over sweep', bad == '', bad or 'max=%.3f' % worst)

# 6: fail-open
chk('empty subnet fails open',
    ls.rollout_block({}, {}, {}, {}, {}, [], {}, 30, 2.0) == {})

# 7: the two read-outs disagree exactly where predicted -- a link whose OWN
# stop line is jammed but whose entry is empty. worst=1.0, entry=0.0.
_geoms = {2: G(200.0)}
_N = ls.build_links(_geoms, {2: 0})[2]['N']
_det = ls.rollout_block_detail(_geoms, {2: _N}, {}, {3: {0}}, {0: [False] * 30},
                               [0], {0: [2]}, 30, 2.0)
_d = _det.get(0, {})
chk('stop-line-only jam: worst saturates', abs(_d.get('worst', 0.0) - 1.0) < 1e-9,
    'worst=%.3f' % _d.get('worst', 0.0))
chk('stop-line-only jam: entry is empty', _d.get('entry', 1.0) < 1e-9,
    'entry=%.3f k=%d' % (_d.get('entry', 1.0), _d.get('k', 0)))

# 8: entry never exceeds worst, worst never exceeds the true cell max
_bad = ''
for va in (0, 5, 20, 60):
    for vb in (0, 5, 20, 60):
        _dd = ls.rollout_block_detail(GEOMS, {1: va, 2: vb, 3: 0}, {1: {2}, 2: {3}},
                                      SERVING, {0: [True] * 30, 1: [True] * 30}, RING,
                                      TARGETS, 30, 2.0)
        for _p, _v in _dd.items():
            if not (_v['entry'] <= _v['worst'] + 1e-12 and _v['mean'] <= _v['worst'] + 1e-12):
                _bad = 'ph=%d worst=%.3f entry=%.3f mean=%.3f' % (
                    _p, _v['worst'], _v['entry'], _v['mean'])
chk('entry <= mean <= worst holds', _bad == '', _bad)

# 9: readout selection actually changes the returned value
_w = ls.rollout_block(_geoms, {2: _N}, {}, {3: {0}}, {0: [False] * 30}, [0],
                      {0: [2]}, 30, 2.0, readout='worst')
_e = ls.rollout_block(_geoms, {2: _N}, {}, {3: {0}}, {0: [False] * 30}, [0],
                      {0: [2]}, 30, 2.0, readout='entry')
chk('readout=entry lowers the block', _w.get(0, 0.0) > _e.get(0, 0.0) + 0.5,
    'worst=%.2f entry=%.2f' % (_w.get(0, 0.0), _e.get(0, 0.0)))

print('')
print('RESULT: %d failure(s)' % len(FAILS))
sys.exit(1 if FAILS else 0)
