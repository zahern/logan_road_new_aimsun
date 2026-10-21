"""Per-intersection phase / detector layout diagrams.

Writes one PNG per managed junction showing, on the real model geometry:

  * every approach section (the legs feeding the junction), with lane count
  * every detector that physically sits on those legs, placed at its true
    distance from the stop line and styled by the ROLE the TSP config gives it
      - main call     (UpDetList)          blue circle
      - bus presence  (BusDet)             orange square
      - bus call      (BusCallDetectors)   red triangle
      - bus exit      (BusExitDetectors)   green triangle
      - NOT in config (on the approach)    grey x  <-- the visibility gap
  * a phase/approach grid: which phases serve which approach (read from the
    Aimsun ECI signal plan turnings, falling back to SignalGroupIDList)

The point is to answer "which approaches have no call detector, which phases
are unmapped, and which model detectors exist but are ignored by the engine"
without reading a log.

Called once per Aimsun session from AAPIFinish (see PLOT_INTERSECTION_LAYOUT).
Never raises: it is a diagnostic, not part of the control path.
"""

import math
import os

try:
    from AAPI import *          # noqa: F401,F403
except Exception:
    pass

try:
    import numpy as np
except Exception:
    np = None

_DONE = {}
TRIM_M = 140.0
ROLE_STYLE = {
    'bus_exit': ('#2ca02c', 'v', 'bus exit (BusExitDetectors)'),
    'bus_call': ('#d62728', '^', 'bus call (BusCallDetectors)'),
    'bus_det': ('#ff7f0e', 's', 'bus presence (BusDet)'),
    'call': ('#1f77b4', 'o', 'main call (UpDetList)'),
    'unused': ('#7f7f7f', 'x', 'on approach, NOT in config'),
}
_ROLE_ORDER = ('bus_exit', 'bus_call', 'bus_det', 'call', 'unused')


def _safe(fn, default=None):
    try:
        v = fn()
        return default if v is None else v
    except Exception:
        return default


def _pt(p):
    if p is None:
        return None
    try:
        return (float(p.getX()), float(p.getY()))
    except Exception:
        pass
    try:
        return (float(p.x), float(p.y))
    except Exception:
        return None


def _oid(o):
    if o is None:
        return None
    try:
        return int(o.getId())
    except Exception:
        pass
    try:
        return int(o)
    except Exception:
        return None


def _polyline(sec):
    pts = []
    try:
        n = int(sec.nbPoints())
        for i in range(n):
            q = _pt(sec.getPoint(i))
            if q is not None:
                pts.append(q)
    except Exception:
        pts = []
    if len(pts) >= 2:
        return pts
    try:
        for p in list(sec.getPoints() or []):
            q = _pt(p)
            if q is not None:
                pts.append(q)
    except Exception:
        pass
    return pts


def _cum(pts):
    out = [0.0]
    for a, b in zip(pts, pts[1:]):
        out.append(out[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    return out


def _trim_end(pts, keep_m):
    if not pts or len(pts) < 2:
        return list(pts or [])
    cum = _cum(pts)
    total = cum[-1]
    if total <= keep_m:
        return list(pts)
    cut = total - keep_m
    for i in range(1, len(pts)):
        if cum[i] >= cut:
            f = (cut - cum[i - 1]) / max(cum[i] - cum[i - 1], 1e-9)
            a, b = pts[i - 1], pts[i]
            start = (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
            return [start] + list(pts[i:])
    return list(pts)


def _point_from_end(pts, dist_m):
    """Point ``dist_m`` upstream of the stop line (last vertex)."""
    if not pts:
        return None
    if len(pts) < 2:
        return pts[0]
    cum = _cum(pts)
    total = cum[-1]
    d = max(0.0, min(float(dist_m), total))
    target = total - d
    for i in range(len(pts) - 1, 0, -1):
        if cum[i - 1] <= target:
            seg = max(cum[i] - cum[i - 1], 1e-9)
            f = (target - cum[i - 1]) / seg
            a, b = pts[i - 1], pts[i]
            return (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
    return pts[0]


def _sec_geom(cat, sid):
    if cat is None:
        return None
    sec = _safe(lambda: cat.find(int(sid)))
    if sec is None:
        return None
    pts = _polyline(sec)
    length = _safe(lambda: float(sec.length2D()), None)
    if (not length or length <= 0.0) and len(pts) > 1:
        length = _cum(pts)[-1]
    lanes = _safe(lambda: int(sec.getTotalNbLanes()), None)
    if not lanes:
        lanes = len(_safe(lambda: list(sec.getLanes() or []), []) or []) or 1
    return {
        'id': int(sid),
        'pts': pts,
        'len_m': float(length or 0.0),
        'lanes': int(lanes or 1),
        'name': str(_safe(lambda: sec.getName(), '') or ''),
    }


def _approach_ids(jid, ctrl, cat):
    out = []
    seen = set()

    def add(v):
        sid = _oid(v)
        if sid and sid > 0 and sid not in seen:
            seen.add(sid)
            out.append(sid)

    node = _safe(lambda: cat.find(int(jid))) if cat is not None else None
    if node is not None:
        for s in (_safe(lambda: list(node.getEntranceSections() or []), []) or []):
            add(s)
    try:
        n = int(AKIInfNetGetNbTurnsInNode(int(jid)))
        for ti in range(max(n, 0)):
            add(_safe(lambda: AKIInfNetGetOriginSectionInTurn(int(jid), ti)))
    except Exception:
        pass
    for s in (_safe(lambda: list(getattr(ctrl, 'incoming_sections', []) or []), []) or []):
        add(s)
    for s in (_safe(lambda: list(getattr(ctrl, 'MainSections', []) or []), []) or []):
        add(s)
    for s in (_safe(lambda: list(getattr(ctrl, 'SideSections', []) or []), []) or []):
        add(s)
    return out


def _det_index():
    idx = {}
    try:
        n = int(AKIDetGetNumberDetectors())
    except Exception:
        return idx
    for i in range(max(n, 0)):
        did = _safe(lambda: int(AKIDetGetIdDetector(i)), None)
        if not did:
            continue
        p = _safe(lambda: AKIDetGetPropertiesDetectorById(int(did)))
        if p is None or _safe(lambda: int(p.report), -1) < 0:
            continue
        sid = _safe(lambda: int(p.IdSection), 0) or 0
        ini = _safe(lambda: float(p.InitialPosition), 0.0) or 0.0
        fin = _safe(lambda: float(p.FinalPosition), ini) or ini
        idx[did] = {'id': int(did), 'sec': int(sid),
                    'pos': 0.5 * (ini + fin), 'ini': ini, 'fin': fin}
    return idx


def _config_roles(ctrl):
    roles = {}

    def put(det, role):
        try:
            det = int(det)
        except Exception:
            return
        cur = roles.setdefault(det, [])
        if role not in cur:
            cur.append(role)

    for grp in (_safe(lambda: list(getattr(ctrl, 'UpDetList', []) or []), []) or []):
        for det in (_safe(lambda: list(grp or []), []) or []):
            put(det, 'call')
    for det in (_safe(lambda: list(getattr(ctrl, 'BusDet', []) or []), []) or []):
        put(det, 'bus_det')
    for det in (_safe(lambda: list(getattr(ctrl, 'BusCallDetectors', []) or []), []) or []):
        put(det, 'bus_call')
    for det in (_safe(lambda: list(getattr(ctrl, 'BusExitDetectors', []) or []), []) or []):
        put(det, 'bus_exit')
    roles.pop(None, None)
    return roles


def _primary(roles):
    for r in _ROLE_ORDER:
        if r in roles:
            return r
    return 'unused'


def _phase_map(jid, ctrl):
    """{phase: {'sgs': [...], 'from_secs': set(), 'dur': s}} from the live plan."""
    phases = {}
    n_ph = 0
    try:
        n_ph = int(ECIGetNumberofPhases(int(jid)))
    except Exception:
        try:
            n_ph = int(ECIGetNumberPhases(int(jid)))
        except Exception:
            n_ph = 0

    def _dur(ph):
        try:
            d = doublep()
            ECIGetDurationsPhase(int(jid), int(ph), 0.0, d, doublep(), doublep())
            return float(d.value())
        except Exception:
            return None

    if n_ph > 0:
        for ph in range(1, n_ph + 1):
            sgs = []
            try:
                nsg = int(ECIGetNbSignalGroupsPhaseofJunction(int(jid), ph, 0.0))
            except Exception:
                nsg = 0
            for pos in range(1, nsg + 1):
                sg = _safe(lambda: int(ECIGetSignalGroupPhaseofJunction(
                    int(jid), ph, pos, 0.0)), None)
                if sg:
                    sgs.append(int(sg))
            from_secs = set()
            for sg in sgs:
                nt = _safe(lambda: int(ECIGetNumberTurningsofSignalGroup(
                    int(jid), int(sg))), 0) or 0
                for ti in range(max(nt, 0)):
                    try:
                        fp, tp = intp(), intp()
                        ECIGetFromToofTurningofSignalGroup(
                            int(jid), int(sg), ti, fp, tp)
                        s = int(fp.value())
                        if s > 0:
                            from_secs.add(s)
                    except Exception:
                        continue
            phases[ph] = {'sgs': sgs, 'from_secs': from_secs, 'dur': _dur(ph)}

    if not phases:
        sgl = _safe(lambda: list(getattr(ctrl, 'SignalGroupIDList', []) or []), []) or []
        for ph, grp in enumerate(sgl, start=1):
            sgs = []
            for sg in (_safe(lambda: list(grp or []), []) or []):
                v = _safe(lambda: int(sg), None)
                if v:
                    sgs.append(v)
            phases[ph] = {'sgs': sgs, 'from_secs': set(), 'dur': None}
    return phases


def build(jid, ctrl, cat, det_idx):
    approaches = []
    for sid in _approach_ids(jid, ctrl, cat):
        g = _sec_geom(cat, sid)
        if not g or g['len_m'] <= 0.0:
            continue
        approaches.append(g)
    approaches.sort(key=lambda g: g['id'])

    roles = _config_roles(ctrl)
    dets = []
    for did, d in det_idx.items():
        if any(d['sec'] == a['id'] for a in approaches):
            rs = roles.get(did, [])
            dets.append(dict(d, roles=list(rs), primary=_primary(rs)))

    phases = _phase_map(jid, ctrl)
    bus_ph = _safe(lambda: int(getattr(ctrl, 'BusPhase', -1)), -1)

    gaps = []
    for a in approaches:
        mine = [d for d in dets if d['sec'] == a['id']]
        call = [d for d in mine if d['primary'] in ('call', 'bus_call', 'bus_det')]
        exit_ = [d for d in mine if d['primary'] == 'bus_exit']
        unused = [d for d in mine if d['primary'] == 'unused']
        serving = [ph for ph, p in phases.items() if a['id'] in (p['from_secs'] or set())]
        a['serving'] = serving
        a['n_call'] = len(call)
        a['n_exit'] = len(exit_)
        a['n_unused'] = len(unused)
        if not call:
            gaps.append('approach %s has NO call/bus detector' % a['id'])
        if not serving and phases and any(p['from_secs'] for p in phases.values()):
            gaps.append('approach %s is served by NO phase (plan mapping gap)' % a['id'])
        if unused:
            gaps.append('approach %s has %d detector(s) not used by the engine'
                        % (a['id'], len(unused)))
    return {'jid': int(jid), 'approaches': approaches, 'dets': dets,
            'phases': phases, 'bus_phase': bus_ph, 'gaps': gaps,
            'node_xy': _node_xy(cat, jid)}


def _node_xy(cat, jid):
    if cat is None:
        return None
    node = _safe(lambda: cat.find(int(jid)))
    if node is None:
        return None
    return _pt(_safe(lambda: node.getPosition()))


def _synthetic(jn):
    n = len(jn['approaches'])
    for i, a in enumerate(jn['approaches']):
        if len(a['pts']) >= 2:
            continue
        ang = 2.0 * math.pi * i / max(n, 1)
        L = min(max(a['len_m'], 20.0), TRIM_M)
        x0, y0 = math.cos(ang) * 8.0, math.sin(ang) * 8.0
        x1, y1 = math.cos(ang) * (8.0 + L), math.sin(ang) * (8.0 + L)
        a['pts'] = [(x0, y0), (x1, y1)]
        a['synthetic'] = True
        a['len_m'] = L


def _draw(jn, ax, axg, meta):
    from matplotlib.lines import Line2D

    arts = [a for a in jn['approaches'] if len(a['pts']) >= 2]
    real = sum(1 for a in arts if not a.get('synthetic'))
    use_real = real >= max(2, int(0.6 * len(arts))) if arts else False
    if not use_real:
        for i, a in enumerate(arts):
            ang = 2.0 * math.pi * i / max(len(arts), 1)
            L = min(max(a['len_m'], 20.0), TRIM_M)
            a['pts'] = [(math.cos(ang) * 6.0, math.sin(ang) * 6.0),
                        (math.cos(ang) * (6.0 + L), math.sin(ang) * (6.0 + L))]
            a['synthetic'] = True
        ox, oy = 0.0, 0.0
    else:
        ox, oy = jn['node_xy'] if jn['node_xy'] else (0.0, 0.0)

    for idx, a in enumerate(arts):
        pts = a['pts']
        if not use_real:
            ang = 2.0 * math.pi * idx / max(len(arts), 1)
            L = min(max(a['len_m'], 20.0), TRIM_M)
            pts = [(math.cos(ang) * 6.0, math.sin(ang) * 6.0),
                   (math.cos(ang) * (6.0 + L), math.sin(ang) * (6.0 + L))]
        else:
            pts = _trim_end(pts, TRIM_M)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        lw = 2.0 + 0.7 * a['lanes']
        ax.plot(xs, ys, color='#37474f', lw=lw, solid_capstyle='butt', zorder=2)
        ax.plot(xs, ys, color='#b0bec5', lw=max(lw - 1.6, 0.8), zorder=3)
        tip = _point_from_end(pts, 0.0)
        if tip:
            ax.plot([tip[0]], [tip[1]], marker='s', ms=4, color='#111111', zorder=6)

        ph_txt = ''
        if a['serving']:
            ph_txt = ' [' + ','.join('P%d%s' % (p, '*' if p == jn['bus_phase'] else '')
                                     for p in a['serving']) + ']'
        far = _point_from_end(pts, min(a['len_m'], TRIM_M) * 0.92)
        if far:
            ax.annotate('%d  %dl%s' % (a['id'], a['lanes'], ph_txt), xy=far,
                        fontsize=7.5, color='#263238', ha='center', va='center',
                        bbox=dict(boxstyle='round,pad=0.18', fc='white',
                                  ec='#90a4ae', lw=0.6, alpha=0.92), zorder=8)
        if a['n_call'] == 0:
            ax.plot([tip[0]], [tip[1]], marker='o', ms=16, mfc='none',
                    mec='#e53935', mew=2.0, zorder=7)

        for d in jn['dets']:
            if d['sec'] != a['id']:
                continue
            dist = max(a['len_m'] - d['pos'], 0.0)
            p = _point_from_end(pts, min(dist, TRIM_M))
            if p is None:
                continue
            col, mk, _ = ROLE_STYLE[d['primary']]
            ax.plot([p[0]], [p[1]], marker=mk, ms=7.5, color=col,
                    mec='white', mew=0.6, zorder=9,
                    mfc='none' if d['primary'] == 'unused' else col)
            if d['primary'] == 'unused':
                ax.plot([p[0]], [p[1]], marker='x', ms=7.5, color=col,
                        mew=1.6, zorder=10)
            ax.annotate(str(d['id']), xy=p, xytext=(4, 4),
                        textcoords='offset points', fontsize=5.5,
                        color=col, zorder=10)

    if use_real:
        cx, cy = ox, oy
        ax.plot([cx], [cy], marker='*', ms=15, color='#263238', zorder=11)
        try:
            import matplotlib.patches as _mp
            for r in (25.0, 50.0, 100.0):
                ax.add_patch(_mp.Circle((cx, cy), r, fill=False, ec='#cfd8dc',
                                        lw=0.6, ls=':', zorder=1))
                ax.annotate('%dm' % r, xy=(cx + r * 0.71, cy + r * 0.71),
                            fontsize=5.5, color='#b0bec5', zorder=1)
        except Exception:
            pass
        ax.set_aspect('equal', adjustable='datalim')
        ext = 0.0
        for a in arts:
            for p in a['pts']:
                ext = max(ext, math.hypot(p[0] - cx, p[1] - cy))
        R = max(ext * 1.15, 25.0)
        ax.set_xlim(cx - R, cx + R)
        ax.set_ylim(cy - R, cy + R)
    else:
        ax.set_aspect('equal', adjustable='datalim')
    ax.set_xlabel('model X (m)', fontsize=8)
    ax.set_ylabel('model Y (m)', fontsize=8)
    ax.grid(alpha=0.15, lw=0.5)
    ax.set_title('Approaches, detectors and stop lines', fontsize=9)

    handles = [Line2D([0], [0], marker=ROLE_STYLE[r][1], color='none',
                      markerfacecolor='none' if r == 'unused' else ROLE_STYLE[r][0],
                      markeredgecolor=ROLE_STYLE[r][0], ms=7, label=ROLE_STYLE[r][2])
               for r in _ROLE_ORDER]
    handles.append(Line2D([0], [0], marker='o', color='none', mfc='none',
                          mec='#e53935', mew=2, ms=12,
                          label='approach with NO call detector'))
    ax.legend(handles=handles, fontsize=6.2, loc='upper center',
              bbox_to_anchor=(0.5, -0.20), ncol=2, frameon=False)

    _draw_grid(jn, axg)


def _draw_grid(jn, ax):
    phases = jn['phases']
    arts = [a for a in jn['approaches'] if len(a['pts']) >= 2]
    if not phases or not arts:
        ax.text(0.5, 0.5, 'no phase/approach mapping available',
                ha='center', va='center', fontsize=9, color='#b71c1c')
        ax.axis('off')
        return
    ph_ids = sorted(phases)
    cols = [a['id'] for a in arts]
    known = any(phases[p]['from_secs'] for p in ph_ids)

    c_green = [0.40, 0.73, 0.42]
    c_grey = [0.93, 0.94, 0.95]
    c_unk = [0.78, 0.78, 0.78]
    rgba = []
    for i, ph in enumerate(ph_ids):
        fs = phases[ph]['from_secs'] or set()
        row = []
        for j, sid in enumerate(cols):
            if sid in fs:
                row.append(c_green)
            elif known:
                row.append(c_grey)
            else:
                row.append(c_unk)
            v = 1.0 if sid in fs else 0.0
            txt = 'green' if v == 1.0 else ''
            if not known:
                txt = '?'
            if v == 1.0:
                sgs = ','.join('SG%d' % s for s in phases[ph]['sgs'])
                txt = sgs or 'green'
            ax.text(j, i, txt, ha='center', va='center', fontsize=5.6,
                    color='#1b5e20' if v == 1.0 else '#455a64')
        rgba.append(row)

    if np is not None:
        ax.imshow(np.array(rgba), aspect='auto', interpolation='nearest')
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(['%d' % c for c in cols], fontsize=7, rotation=0)
    ax.set_yticks(range(len(ph_ids)))
    ax.set_yticklabels(['P%d%s' % (p, ' (BUS)' if p == jn['bus_phase'] else '')
                        for p in ph_ids], fontsize=7)
    ax.set_xlabel('approach section', fontsize=7)
    ax.set_title('Phase -> approach (green = served)', fontsize=9)
    ax.set_xticks([x - 0.5 for x in range(1, len(cols))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(ph_ids))], minor=True)
    ax.grid(which='minor', color='white', lw=1.2)
    ax.tick_params(which='minor', length=0)

    dur = []
    for p in ph_ids:
        d = phases[p].get('dur')
        if d:
            dur.append('P%d=%ds' % (p, int(round(d))))
    if dur:
        ax.set_xlabel('approach section   |   ' + '  '.join(dur), fontsize=6)


def draw(jn, meta, out_path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(13.5, 8.6), dpi=130)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.55, 1.0], wspace=0.18)
    ax = fig.add_subplot(gs[0, 0])
    axg = fig.add_subplot(gs[0, 1])
    _draw(jn, ax, axg, meta)

    title = ('INT %s  -  %s / %s' % (jn['jid'], meta.get('experiment', '?'),
                                      meta.get('control_mode', '?')))
    if meta.get('name'):
        title += '  [' + str(meta['name']) + ']'
    fig.suptitle(title, fontsize=11, y=0.995)
    sub = ('%d approaches | %d detectors on approaches | %d phases | bus phase %s'
           % (len(jn['approaches']), len(jn['dets']), len(jn['phases']),
              jn['bus_phase'] if jn['bus_phase'] > 0 else '?'))
    if jn['gaps']:
        sub += '\nGAPS: ' + '; '.join(jn['gaps'][:4])
        if len(jn['gaps']) > 4:
            sub += ' (+%d more, see CSV)' % (len(jn['gaps']) - 4)
    fig.text(0.5, 0.955, sub, ha='center', va='top', fontsize=7.4,
             color='#b71c1c' if jn['gaps'] else '#2e7d32')
    fig.subplots_adjust(left=0.05, right=0.985, top=0.87, bottom=0.24)
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def run(controllers=None, config=None, out_dir=None, experiment='UNKNOWN',
        control_mode='?', timestamp='', log=None, enable=True):
    """Write one PNG per junction plus a gap CSV. Returns list of file paths."""
    if not bool(enable):
        return []
    controllers = controllers or {}
    config = config or {}
    if not controllers:
        return []
    out_dir = out_dir or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)

    key = tuple(sorted(int(k) for k in controllers))
    if _DONE.get('key') == key:
        return []
    _DONE['key'] = key

    try:
        from PyANGKernel import GKSystem
        model = GKSystem.getSystem().getActiveModel()
        cat = model.getCatalog() if model is not None else None
    except Exception:
        cat = None

    det_idx = _det_index()
    written = []
    rows = []
    for jid, ctrl in sorted(controllers.items()):
        try:
            jn = build(jid, ctrl, cat, det_idx)
            if not jn['approaches']:
                if log:
                    log('[LAYOUT] inter=%s skipped: no approach geometry' % jid)
                continue
            cfg = config.get(jid, {}) or {}
            meta = {'experiment': experiment, 'control_mode': control_mode,
                    'name': cfg.get('Name') or cfg.get('name') or ''}
            path = os.path.join(
                out_dir, 'intersection_layout_%s_%s_%s.png'
                % (experiment, timestamp, jid))
            draw(jn, meta, path)
            written.append(path)
            for g in jn['gaps']:
                rows.append([jid, g])
            for a in jn['approaches']:
                rows.append([jid, 'approach %s: lanes=%d len=%.0fm serving=%s '
                                  'call_dets=%d exit_dets=%d unused_dets=%d'
                                  % (a['id'], a['lanes'], a['len_m'],
                                     a['serving'] or 'none', a['n_call'],
                                     a['n_exit'], a['n_unused'])])
        except Exception as e:
            if log:
                log('[LAYOUT] inter=%s failed: %r' % (jid, e), force=True)

    try:
        csv_path = os.path.join(out_dir,
                                'intersection_layout_%s_%s.csv'
                                % (experiment, timestamp))
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            f.write('junction_id,item\n')
            for r in rows:
                f.write('%s,"%s"\n' % (r[0], str(r[1]).replace('"', "'")))
        written.append(csv_path)
    except Exception:
        pass

    if log:
        gaps = sum(1 for r in rows if not r[1].startswith('approach '))
        log('[LAYOUT] wrote %d intersection diagrams -> %s (%d gaps logged)'
            % (len(written) - 1, out_dir, gaps), force=True)
    return written
