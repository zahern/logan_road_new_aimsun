"""plot_plan_evolution.py -- initial-vs-final cycle time and Purdue green bands.

Reads the per-run `plan_evolution_<experiment>_<timestamp>.csv` written at
AAPIFinish (initial plan from `_init_cycle_greens`, final plan from the live
durations) and writes three figures next to it:

  plan_evolution_<exp>_<ts>_cycle.png   cycle time, initial vs final, per junction
  plan_evolution_<exp>_<ts>_green.png   bus/main-phase green, initial vs final
  plan_evolution_<exp>_<ts>_purdue.png  time-space green band (Purdue diagram),
                                        INITIAL vs FINAL side by side

Offsets are the bus-phase green START within the cycle (sum of the preceding
greens), so the Purdue panels show how the coordinated green band moved.

Call `run(csv_path=...)`; returns the list of written paths.
"""

import csv
import glob
import os


def _f(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def _load(path):
    try:
        with open(path, newline='', encoding='utf-8', errors='replace') as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _draw_band(ax, jd, order, cmax, n_cycles=3, speed_ms=12.0,
               legend=False):
    """Purdue time-space band over several cycles.

    Each junction's bus/main green is repeated every C_j, so the cycle END and
    RESTART are visible; per-row dotted lines mark the cycle boundaries.

    The blue line is a SYNTHETIC platoon (NOT measured flow) leaving the first
    junction at its green start and travelling at `speed_ms`. At each
    downstream junction it must arrive on green; if it arrives on red it waits
    at that stop line (red dashed vertical) until the next green. It therefore
    never passes through a red window.
    """
    import matplotlib.patches as mpatches
    from matplotlib.lines import Line2D

    n_cycles = max(1, int(n_cycles))
    xmax = n_cycles * cmax
    for yi, j in enumerate(order):
        d = jd.get(j)
        if not d:
            continue
        C = d.get('C') or cmax
        g = d.get('g') or 0.0
        if g <= 0.0 or C <= 0.0:
            continue
        off = (d.get('off') or 0.0) % C
        for k in range(n_cycles):
            x0 = off + k * C
            if x0 >= xmax:
                break
            ax.add_patch(mpatches.Rectangle(
                (x0, yi - 0.34), g, 0.68, color='#43a047', alpha=0.9, lw=0))
            if off + g > C:
                # tail of the window that wrapped from the previous cycle
                ax.add_patch(mpatches.Rectangle(
                    (off - C + k * C, yi - 0.34), g, 0.68,
                    color='#43a047', alpha=0.9, lw=0))
        # cycle END / RESTART markers for this junction
        for k in range(1, n_cycles + 1):
            xb = k * C
            if xb <= xmax:
                ax.plot([xb, xb], [yi - 0.44, yi + 0.44],
                        color='#9e9e9e', lw=0.6, ls=':', zorder=1)

    # SYNTHETIC platoon trajectory, ONE per corridor group. It is NOT measured
    # flow: it leaves the first junction at its green start and travels at
    # `speed_ms`. At every downstream junction it must ARRIVE DURING GREEN;
    # if it arrives on red it WAITS at that stop line (red dashed vertical)
    # until the next green. The line therefore never passes through a red.
    groups = {}
    for yi, j in enumerate(order):
        d = jd.get(j) or {}
        groups.setdefault(d.get('grp') or 'all', []).append((yi, j))
    for _grp, rows in groups.items():
        if len(rows) < 2:
            continue
        d0 = jd.get(rows[0][1]) or {}
        C0 = d0.get('C') or 0.0
        g0 = d0.get('g') or 0.0
        if C0 <= 0.0 or g0 <= 0.0:
            continue
        off0 = (d0.get('off') or 0.0) % C0
        p0 = d0.get('pos', 0.0)
        for k in range(n_cycles):
            t_prev = off0 + k * C0          # depart at green START
            if t_prev > xmax:
                continue
            y_prev = rows[0][0]
            prev_pos = p0
            for idx, (yi, j) in enumerate(rows):
                if idx == 0:
                    continue
                d = jd.get(j) or {}
                C = d.get('C') or cmax
                g = d.get('g') or 0.0
                off = (d.get('off') or 0.0) % C if C > 0 else 0.0
                p = d.get('pos', prev_pos)
                dist = abs(p - prev_pos)
                if not (0.0 < dist < 5000.0):
                    dist = 200.0            # missing/odd position fallback
                t_arr = t_prev + dist / max(speed_ms, 1e-6)
                waited = False
                if C > 0.0 and g > 0.0:
                    rel = (t_arr - off) % C
                    if rel <= g:
                        t_dep = t_arr        # arrives on green: keep moving
                    else:
                        t_dep = t_arr + (C - rel)   # wait for next green
                        waited = True
                else:
                    t_dep = t_arr
                ax.plot([t_prev, t_arr], [y_prev, yi],
                        color='#1565c0', lw=1.1, alpha=0.9, zorder=3)
                if waited:
                    # vertical wait at the stop line: cannot pass on red
                    ax.plot([t_arr, t_dep], [yi, yi],
                            color='#e53935', lw=1.3, ls='--', zorder=3)
                t_prev = t_dep
                y_prev = yi
                prev_pos = p

    ax.set_xlim(0, xmax)
    ax.set_ylim(-0.6, max(len(order) - 0.4, 0.6))
    ax.set_xlabel('time (s), %d cycle(s)' % n_cycles)
    ax.grid(alpha=0.25)
    if legend:
        handles = [
            mpatches.Patch(color='#43a047', label='bus/main green'),
            Line2D([0], [0], color='#9e9e9e', ls=':',
                   label='cycle end / restart'),
            Line2D([0], [0], color='#1565c0',
                   label='platoon travel %.0f m/s (synthetic, not flow)'
                   % speed_ms),
            Line2D([0], [0], color='#e53935', ls='--',
                   label='wait at red (does not pass)'),
        ]
        ax.legend(handles=handles, fontsize=7, loc='upper right')


def run(csv_path=None, out_dir=None, n_cycles=3, speed_ms=12.0):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    if not csv_path or not os.path.isfile(csv_path):
        _dir = os.path.dirname(csv_path) if csv_path else '.'
        _c = sorted(glob.glob(os.path.join(_dir, 'plan_evolution_*.csv')),
                    key=os.path.getmtime)
        if not _c:
            return []
        csv_path = _c[-1]
    out_dir = out_dir or os.path.dirname(os.path.abspath(csv_path))
    rows = _load(csv_path)
    if not rows:
        return []
    exp = str(rows[0].get('experiment', 'ARM'))

    jcts = {}
    for r in rows:
        jid = int(_f(r.get('junction_id'), -1))
        if jid < 0:
            continue
        d = jcts.setdefault(jid, {
            'pos': _f(r.get('route_pos'), 1e9),
            'grp': r.get('corridor_group', ''),
            'init_C': _f(r.get('init_cycle_s')),
            'fin_C': _f(r.get('final_cycle_s')),
            'init_off': _f(r.get('init_bus_offset_s')),
            'fin_off': _f(r.get('final_bus_offset_s')),
            'init_bus_g': 0.0, 'fin_bus_g': 0.0, 'phase': None})
        p = int(_f(r.get('phase'), -1))
        if int(_f(r.get('is_bus_phase'))) == 1:
            d['phase'] = p
            d['init_bus_g'] = _f(r.get('init_green_s'))
            d['fin_bus_g'] = _f(r.get('final_green_s'))
    if not jcts:
        return []
    order = sorted(jcts,
                   key=lambda j: (jcts[j].get('grp', ''), jcts[j]['pos'], j))
    tag = os.path.splitext(os.path.basename(csv_path))[0]
    base = os.path.join(out_dir, tag)
    out = []

    # ---- 1. cycle time ------------------------------------------------------
    fig, ax = plt.subplots(figsize=(max(9.0, len(order) * 0.85), 4.8))
    xs = list(range(len(order)))
    w = 0.38
    ax.bar([x - w / 2 for x in xs], [jcts[j]['init_C'] for j in order], w,
           label='initial', color='#90a4ae')
    ax.bar([x + w / 2 for x in xs], [jcts[j]['fin_C'] for j in order], w,
           label='final', color='#1e88e5')
    ax.set_xticks(xs)
    ax.set_xticklabels([str(j) for j in order], rotation=45, ha='right',
                       fontsize=8)
    ax.set_ylabel('cycle (s)')
    ax.set_title('Cycle time: initial vs final - %s' % exp)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    p = base + '_cycle.png'
    fig.savefig(p, dpi=130)
    plt.close(fig)
    out.append(p)

    # ---- 2. bus-phase green -------------------------------------------------
    fig, ax = plt.subplots(figsize=(max(9.0, len(order) * 0.85), 4.8))
    ax.bar([x - w / 2 for x in xs], [jcts[j]['init_bus_g'] for j in order], w,
           label='initial', color='#a5d6a7')
    ax.bar([x + w / 2 for x in xs], [jcts[j]['fin_bus_g'] for j in order], w,
           label='final', color='#2e7d32')
    ax.set_xticks(xs)
    ax.set_xticklabels([str(j) for j in order], rotation=45, ha='right',
                       fontsize=8)
    ax.set_ylabel('bus/main-phase green (s)')
    ax.set_title('Coordinated phase green: initial vs final - %s' % exp)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    p = base + '_green.png'
    fig.savefig(p, dpi=130)
    plt.close(fig)
    out.append(p)

    # ---- 3. Purdue / time-space green band ---------------------------------
    cmax = max(max(d['init_C'], d['fin_C']) for d in jcts.values()) or 1.0
    fig, axes = plt.subplots(1, 2, figsize=(16.0, max(5.0, len(order) * 0.5)),
                             sharey=True)
    for ax, key_c, key_o, key_g, title in (
            (axes[0], 'init_C', 'init_off', 'init_bus_g', 'INITIAL plan'),
            (axes[1], 'fin_C', 'fin_off', 'fin_bus_g', 'FINAL plan')):
        jd = {j: {'C': d[key_c], 'off': d[key_o], 'g': d[key_g],
                  'pos': d['pos']} for j, d in jcts.items()}
        _draw_band(ax, jd, order, cmax, n_cycles=n_cycles,
                   speed_ms=speed_ms, legend=(ax is axes[0]))
        ax.set_title(title)
    axes[0].set_yticks(list(range(len(order))))
    axes[0].set_yticklabels(
        ["%s %s" % (j, jcts[j].get('grp', '')) for j in order], fontsize=8)
    axes[0].set_ylabel('junction (corridor group, route order)')
    fig.suptitle('Purdue time-space green band, %d cycles: initial vs final - %s'
                 % (n_cycles, exp))
    fig.tight_layout()
    p = base + '_purdue.png'
    fig.savefig(p, dpi=130)
    plt.close(fig)
    out.append(p)

    return out


def _final_plans(path):
    """{jid: {pos, C, off, g}} from a plan_evolution CSV's FINAL plan."""
    rows = _load(path)
    out = {}
    for r in rows:
        jid = int(_f(r.get('junction_id'), -1))
        if jid < 0:
            continue
        d = out.setdefault(jid, {
            'pos': _f(r.get('route_pos'), 1e9),
            'grp': r.get('corridor_group', ''),
            'C': _f(r.get('final_cycle_s')),
            'off': _f(r.get('final_bus_offset_s')),
            'g': 0.0})
        if int(_f(r.get('is_bus_phase'))) == 1:
            d['g'] = _f(r.get('final_green_s'))
    return out


def run_compare(csv_paths, labels=None, out_path=None, title=None,
                n_cycles=3, speed_ms=12.0):
    """Purdue time-space green band for N plans side by side.

    Use for BEFORE (NO_TSP / model plan) vs CYCLEFIX vs SCATS_STATE final
    plans. Each panel repeats the green every C_j so cycle END/RESTART is
    visible, and the blue platoon line shows how the wave maps onto greens.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    paths = [p for p in (csv_paths or []) if p and os.path.isfile(p)]
    if not paths:
        return None
    plans = [_final_plans(p) for p in paths]
    labels = list(labels or [os.path.basename(os.path.dirname(p)) or
                             os.path.basename(p) for p in paths])
    # Merge geometry across plans: NO_TSP has no coordinator, so its
    # route_pos/corridor_group are empty. Take the first VALID value from any
    # plan (the arms carry it) so the before/after panels share one order.
    pos_map, grp_map = {}, {}
    for pl in plans:
        for j, d in pl.items():
            p = d.get('pos', 1e9)
            if p is not None and p < 1e8:
                if j not in pos_map or p < pos_map[j]:
                    pos_map[j] = p
            g = d.get('grp') or ''
            if g and j not in grp_map:
                grp_map[j] = g
    allj = {}
    for pl in plans:
        for j in pl:
            allj[j] = pos_map.get(j, 1e9)
    order = sorted(allj, key=lambda j: (grp_map.get(j, ''), allj[j], j))
    for pl in plans:
        for j, d in pl.items():
            if j in pos_map:
                d['pos'] = pos_map[j]
            if j in grp_map:
                d['grp'] = grp_map[j]
    cmax = max([d['C'] for pl in plans for d in pl.values()] or [1.0]) or 1.0

    n = len(plans)
    fig, axes = plt.subplots(1, n,
                             figsize=(8.5 * n, max(5.0, len(order) * 0.48)),
                             sharey=True)
    if n == 1:
        axes = [axes]
    for i, (ax, pl, lab) in enumerate(zip(axes, plans, labels)):
        _draw_band(ax, pl, order, cmax, n_cycles=n_cycles,
                   speed_ms=speed_ms, legend=(i == 0))
        ax.set_title(lab)
    axes[0].set_yticks(list(range(len(order))))
    axes[0].set_yticklabels(
        ["%s %s" % (j, grp_map.get(j, '')) for j in order], fontsize=8)
    axes[0].set_ylabel('junction (corridor group, route order)')
    fig.suptitle(title or ('Purdue time-space green band, %d cycles: '
                           'before vs after' % n_cycles))
    fig.tight_layout()
    out_path = os.fspath(out_path or os.path.join(
        os.path.dirname(os.path.abspath(paths[0])),
        'purdue_before_after.png'))
    try:
        fig.savefig(out_path, dpi=120, format='png')
    finally:
        plt.close(fig)
    return out_path
