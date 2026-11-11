"""Diagnose the CTM locator panel: does the red link follow its own edge shape?

Prints the selected edge's geometry and writes _ctm_locator_debug.png, a 500 m
window where the selected edge is ALSO drawn as a black dotted line. If the red
bar leaves the road, the dotted line shows whether the data or the drawing is
at fault: red should sit exactly on top of the dotted line.
"""
import math
import sys

import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

root = ET.parse('_sumo_snaps/kg.net.xml').getroot()
junc, edges = {}, {}
for j in root.findall('junction'):
    jid = j.get('id', '')
    if jid.startswith(':'):
        continue
    junc[jid] = (float(j.get('x', 0)), float(j.get('y', 0)))
for e in root.findall('edge'):
    eid = e.get('id', '')
    if eid.startswith(':') or e.get('function') == 'internal':
        continue
    lanes = e.findall('lane')
    if not lanes:
        continue
    length = float(e.get('length') or lanes[0].get('length') or 0)
    shape = lanes[0].get('shape')
    pts = [tuple(float(v) for v in p.split(',')) for p in shape.split()] if shape else []
    has_shape = len(pts) >= 2
    if not has_shape:
        pts = [junc[e.get('from')], junc[e.get('to')]]
    edges[eid] = dict(id=eid, frm=e.get('from'), to=e.get('to'), lanes=len(lanes),
                      length=length, pts=pts, npts=len(pts), shaped=has_shape)

two = [e for e in edges.values() if e['lanes'] == 2 and e['length'] > 40]
pick = min(two, key=lambda e: abs(e['length'] - 248.0))

print('picked      : %s  %.1f m  %d lanes' % (pick['id'], pick['length'], pick['lanes']))
print('frm -> to   : %s -> %s' % (pick['frm'], pick['to']))
print('has shape   : %s  (%d points)' % (pick['shaped'], pick['npts']))
print('polyline    :', ['(%.1f, %.1f)' % p for p in pick['pts']])

seg = sum(math.hypot(pick['pts'][i][0] - pick['pts'][i - 1][0],
                     pick['pts'][i][1] - pick['pts'][i - 1][1])
          for i in range(1, pick['npts']))
chord = math.hypot(pick['pts'][-1][0] - pick['pts'][0][0],
                   pick['pts'][-1][1] - pick['pts'][0][1])
print('geometry    : shape=%.1f m  chord=%.1f m  sag=%.1f m' % (seg, chord, seg - chord))

ax_, ay_ = pick['pts'][0]
bx_, by_ = pick['pts'][-1]
den = math.hypot(bx_ - ax_, by_ - ay_) or 1.0
dev = max(abs((bx_ - ax_) * (ay_ - p[1]) - (ax_ - p[0]) * (by_ - ay_)) / den
          for p in pick['pts'])
print('max dev from chord: %.1f m' % dev)

# how many edges in the net lack a shape (falls back to a junction-to-junction chord)
noshape = [e['id'] for e in edges.values() if not e['shaped']]
print('edges without a shape attribute: %d / %d' % (len(noshape), len(edges)))
if noshape:
    print('   e.g.', noshape[:8])

cx = sum(p[0] for p in pick['pts']) / pick['npts']
cy = sum(p[1] for p in pick['pts']) / pick['npts']
W = 250.0
fig, ax = plt.subplots(figsize=(6.4, 6.4))
for e in edges.values():
    xs = [p[0] for p in e['pts']]
    ys = [p[1] for p in e['pts']]
    if max(xs) < cx - W or min(xs) > cx + W or max(ys) < cy - W or min(ys) > cy + W:
        continue
    ax.plot(xs, ys, color='#B0BEC5', lw=0.8, zorder=1)
    if e['id'] == pick['id']:
        ax.plot(xs, ys, color='black', lw=1.0, ls=':', zorder=2)
ax.plot([p[0] for p in pick['pts']], [p[1] for p in pick['pts']],
        color='#C0504D', lw=3.0, zorder=3, solid_capstyle='round')
ax.scatter([pick['pts'][0][0], pick['pts'][-1][0]],
           [pick['pts'][0][1], pick['pts'][-1][1]], s=34, color='#37474F', zorder=4)
for n in (pick['frm'], pick['to']):
    x, y = junc[n]
    ax.annotate(n, (x, y), textcoords='offset points', xytext=(5, 5), fontsize=8)
ax.set_xlim(cx - W, cx + W)
ax.set_ylim(cy - W, cy + W)
ax.set_aspect('equal')
ax.grid(alpha=0.3, lw=0.4)
ax.set_title('debug: %s  (black dotted = its own edge shape)' % pick['id'], fontsize=8)
plt.savefig('_ctm_locator_debug.png', dpi=140, bbox_inches='tight', facecolor='white')
print('saved _ctm_locator_debug.png')
