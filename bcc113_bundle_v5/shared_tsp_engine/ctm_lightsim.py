"""LightSim-style NETWORK CTM, used as an alternative model for the game's
downstream-block term (engine flag GAME_CTM2_LIGHTSIM).

LightSim (Su & Deng, arXiv:2602.21852, github.com/AnthonySu/LightSim) is a
pure-Python Cell Transmission Model built for signal-control research: a
triangular fundamental diagram, cells of length v_free * dt, and a flow update

    n_i(t+dt) = n_i(t) + q_{i-1}(t) - q_i(t)

where a cell's sending flow is S(k) = min(v_free*k, Q)*lanes and its receiving
flow is R(k) = min(Q, w*(k_jam - k))*lanes.  What distinguishes it from the
per-approach CTM in ctm_twoclass.py is the INTERSECTION resolution: every
turning movement carries a turn ratio, is masked by the signal state, is capped
at the saturation rate, and is then scaled proportionally when the movements
into one receiving cell exceed its free space (merge) or the movements out of
one sending cell exceed what it can send (diverge).  This module reproduces that
resolution on the engine's own 2-hop subnet, so the game prices candidate
actions with a network CTM instead of the equal-split hop approximation in
Engine._ctm2_rollout_block.

It is a port of the formulation, not a wrapper: the vendored clone under
Z:/tsp/sumo_hpc/_lightsim_probe/vendor/LightSim needs gymnasium and its own venv
at import time, so it cannot be imported from inside the engine.

Interface contract (identical to Engine._ctm2_rollout_block):
    rollout_block(geoms, vehicles, adj, serving, gseq, ring, targets,
                  steps, dt, max_cells=12) -> {phase: block in [0,1]}

`serving` is keyed SECTION -> {phases}, exactly as Engine builds it
(`_serving.setdefault(origin_section, set()).add(phase)`); it is inverted once
per call below.
An empty dict means "no model" and the caller keeps out_cap_frac = 1.0.
Never raises on bad input; worst case returns {}.
"""

__all__ = ['rollout_block', 'simulate', 'build_links']

# Fallback CTM triangle, same values as ApproachGeom defaults.
_VF_KMH = 50.0
_W_KMH = 18.0
_KJAM = 200.0          # veh/km/lane
_QSAT = 1800.0         # veh/h/lane
_SPACING = 7.0         # veh/m storage spacing (JAM_VEH_SPACING_M)


def _geom_parts(g):
    """(n_cells, cell_len_m, storage_veh_per_cell, cap_veh_per_step, w_ratio)."""
    lanes = max(int(getattr(g, 'lanes', 1) or 1), 1)
    length = max(float(getattr(g, 'length_m', 0.0) or 0.0), 1.0)
    vf = max(float(getattr(g, 'v_free_kmh', _VF_KMH) or _VF_KMH), 1.0) / 3.6
    w = max(float(getattr(g, 'w_back_kmh', _W_KMH) or _W_KMH), 0.1) / 3.6
    kj = max(float(getattr(g, 'k_jam_vkm_lane', _KJAM) or _KJAM), 1.0)
    qsat = max(float(getattr(g, 'q_sat_vph_lane', _QSAT) or _QSAT), 1.0)
    try:
        k = int(getattr(g, 'n_cells', 0) or 0)
        L = float(getattr(g, 'cell_len_m', 0.0) or 0.0)
        N = float(getattr(g, 'storage_pcu', 0.0) or 0.0)
        Q = float(getattr(g, 'cap_pcu_step', 0.0) or 0.0)
        wr = float(getattr(g, 'w_ratio', 0.0) or 0.0)
    except Exception:
        k = L = N = Q = wr = 0
    if k <= 0:
        # LightSim's own sizing: cell_len >= vf*dt, capped.
        dt = 2.0
        L = max(vf * dt, 5.0)
        k = max(1, int(min(-(-int(length) // int(max(L, 1.0))), 12)))
    if L <= 0:
        L = max(length / max(k, 1), 5.0)
    if N <= 0:
        N = max(kj * (L / 1000.0) * lanes, 1.0)
    if Q <= 0:
        Q = max(qsat / 3600.0 * lanes * 2.0, 1e-6)
    if wr <= 0:
        wr = min(1.0, max(w / vf, 0.1))
    return max(int(k), 1), float(L), float(N), float(Q), float(wr)


def build_links(geoms, vehicles, max_cells=12):
    """One link per section: K cells, seeded from the STOP LINE backwards.

    Vehicles beyond the modelled domain (K cells) are dropped, exactly as
    LightSim drops density outside the horizon; the caller's fail-open keeps
    the term at 1.0 rather than inventing a jam.
    """
    links = {}
    for sid, g in (geoms or {}).items():
        try:
            k, L, N, Q, wr = _geom_parts(g)
        except Exception:
            continue
        k = max(1, min(int(k), int(max_cells or 12)))
        n = [0.0] * k
        left = max(float((vehicles or {}).get(sid, 0.0) or 0.0), 0.0)
        i = k - 1                       # i = k-1 is the stop-line cell
        while left > 0.0 and i >= 0:
            take = min(left, N)
            n[i] = take
            left -= take
            i -= 1
        links[int(sid)] = {'n': n, 'K': k, 'L': L, 'N': N, 'Q': Q, 'wr': wr,
                           'seed': sum(n) / max(N * k, 1.0)}
    return links


def _signal_mask(gseq, phase, step):
    try:
        seq = (gseq or {}).get(int(phase)) or []
        return bool(seq[step]) if step < len(seq) else True
    except Exception:
        return True


def simulate(links, adj, serving, gseq, ring, targets, steps, dt, dt_scale=1.0):
    """Run the network CTM. Returns (peak occupancy per section, mass moved)."""
    if not links:
        return {}, 0.0
    # serving is SECTION -> {phases} (Engine._serving); invert it once.
    _phase_orig = {}
    for _sec, _phs in (serving or {}).items():
        try:
            _sec = int(_sec)
            _plist = list(_phs)
        except Exception:
            continue
        for _p in _plist:
            try:
                _phase_orig.setdefault(int(_p), set()).add(_sec)
            except Exception:
                continue
    peak = {s: 0.0 for s in links}
    moved = 0.0
    # per-cell peaks, so the caller can ask WHICH cell saturates (see
    # rollout_block_detail: entry cell vs busiest cell are very different).
    for _s0, _L0 in links.items():
        _L0['peak_cells'] = [min(float(v) / max(_L0['N'], 1.0), 9.99)
                             for v in _L0['n']]
    for step in range(max(int(steps), 0)):
        # --- 1. sending / receiving per cell (triangular FD) ---
        send = {}
        recv = {}
        for sid, L in links.items():
            n = L['n']
            send[sid] = [min(n[i], L['Q']) for i in range(L['K'])]
            recv[sid] = [min(L['Q'], L['wr'] * max(0.0, L['N'] - n[i]))
                         for i in range(L['K'])]
        # --- 2. intra-link transfer (upstream cell -> downstream cell) ---
        intra = {}
        for sid, L in links.items():
            fl = [0.0] * L['K']
            for i in range(L['K'] - 1):
                fl[i] = min(send[sid][i], recv[sid][i + 1])
            intra[sid] = fl
        # --- 3. movements across the junction: mask, ratio, sat cap ---
        movs = []
        for p in (ring or []):
            ts = [int(t) for t in ((targets or {}).get(int(p)) or []) if int(t) in links]
            if not ts:
                continue
            share = 1.0 / float(len(ts))
            gate = _signal_mask(gseq, p, step)
            for o in _phase_orig.get(int(p), ()):
                o = int(o)
                if o not in links:
                    continue
                eff = send[o][-1] * (1.0 if gate else 0.0) * share
                if eff <= 0.0:
                    continue
                eff = min(eff, links[o]['Q'])
                for t in ts:
                    if t == o:
                        continue
                    movs.append([o, t, eff])
        # --- 4. merge: scale proportionally to the receiver's free space ---
        want_t = {}
        for o, t, eff in movs:
            want_t[t] = want_t.get(t, 0.0) + eff
        for m in movs:
            tot = want_t.get(m[1], 0.0)
            if tot > 0.0:
                m[2] *= min(1.0, recv[m[1]][0] / tot)
        # --- 5. diverge: scale if the source cannot send that much ---
        want_o = {}
        for o, t, eff in movs:
            want_o[o] = want_o.get(o, 0.0) + eff
        for m in movs:
            tot = want_o.get(m[0], 0.0)
            if tot > 0.0:
                m[2] *= min(1.0, send[m[0]][-1] / tot)
        # --- 6. apply the update: n_i(t+1) = n_i(t) + q_{i-1} - q_i ---
        # Cells run upstream (0) -> stop line (K-1) as in ctm_twoclass, so a
        # cell GAINS the flow of its upstream neighbour (i-1) and LOSES its own
        # outflow (i -> i+1).
        for sid, L in links.items():
            n = L['n']
            kk = L['K']
            for i in range(kk):
                gain = intra[sid][i - 1] if i > 0 else 0.0
                loss = intra[sid][i] if i < kk - 1 else 0.0
                n[i] = max(n[i] + gain - loss, 0.0)
        for o, t, eff in movs:
            if eff <= 0.0:
                continue
            take = min(eff, links[o]['n'][-1])
            if take <= 0.0:
                continue
            links[o]['n'][-1] -= take
            links[t]['n'][0] += take
            moved += take
        # --- 7. peak occupancy per cell and per section ---
        for sid, L in links.items():
            n = L['n']
            N = max(L['N'], 1.0)
            pc = L['peak_cells']
            occ = 0.0
            for i in range(L['K']):
                o = n[i] / N
                if o > pc[i]:
                    pc[i] = o
                if o > occ:
                    occ = o
            if occ > peak[sid]:
                peak[sid] = occ
    return peak, moved


READOUT_MODES = ('worst', 'entry', 'mean')


def rollout_block_detail(geoms, vehicles, adj, serving, gseq, ring, targets,
                         steps, dt, max_cells=12):
    """Per-phase read-outs, so the caller can choose what "full" means.

    worst : busiest cell ANYWHERE on the receiving link. Pessimistic -- a link
            whose OWN stop line is red fills its last cell (and, once that
            backs up, its whole link) without the entry being blocked at all.
    entry : cell 0, the cell a discharging movement actually enters. This is the
            quantity the model itself gates on (recv[t][0] in simulate), so it
            is the self-consistent answer to "can this phase discharge?".
    mean  : link-average peak occupancy.
    """
    try:
        links = build_links(geoms, vehicles, max_cells)
        if not links:
            return {}
        if sum(float(v) for v in (vehicles or {}).values()) <= 0.0:
            return {}
        simulate(links, adj, serving or {}, gseq or {}, ring, targets or {},
                 steps, dt)
        out = {}
        for p in (ring or []):
            ts = [int(t) for t in ((targets or {}).get(int(p)) or []) if int(t) in links]
            if not ts:
                continue
            worst = entry = mean = 0.0
            kk = 0
            seeded = 0.0
            for t in ts:
                L = links[t]
                pc = L.get('peak_cells') or []
                if not pc:
                    continue
                worst = max(worst, max(pc))
                entry = max(entry, pc[0])
                mean = max(mean, sum(pc) / float(len(pc)))
                kk = max(kk, int(L['K']))
                seeded = max(seeded, float(L.get('seed', 0.0)))
            out[int(p)] = {'worst': worst, 'entry': entry, 'mean': mean,
                           'k': kk, 'seeded': seeded}
        return out
    except Exception:
        return {}


def rollout_block(geoms, vehicles, adj, serving, gseq, ring, targets,
                  steps, dt, max_cells=12, readout='worst'):
    """{phase: downstream block 0..1} from the network CTM."""
    det = rollout_block_detail(geoms, vehicles, adj, serving, gseq, ring,
                               targets, steps, dt, max_cells)
    if not det:
        return {}
    mode = readout if readout in READOUT_MODES else 'worst'
    out = {}
    for p, v in det.items():
        try:
            out[int(p)] = min(max(float(v.get(mode, v.get('worst', 0.0))), 0.0), 1.0)
        except Exception:
            continue
    return out
