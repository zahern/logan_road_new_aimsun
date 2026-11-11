"""KG corridor in the LightSim Figure-3 idiom.

Palette, marker sizes, line weights, serif font and scale bar are taken from
the vendored LightSim scripts/gen_osm_figure.py::plot_network so the KG panel
is directly comparable to the paper's six city panels.

SUMO writes <edge> blocks BEFORE <junction> blocks, so endpoints are collected
as ids and resolved after the whole file is parsed.
"""
import xml.etree.ElementTree as ET
import collections
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Circle

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["DejaVu Serif", "Times New Roman", "serif"],
    "text.usetex": False, "font.size": 9,
    "figure.facecolor": "white", "savefig.facecolor": "white",
})

P = '_sumo_snaps/kg.net.xml'
junc, tl, raw = {}, set(), []
for ev, el in ET.iterparse(P, events=('end',)):
    if el.tag == 'junction':
        jid = el.get('id')
        if jid and not jid.startswith(':'):
            try:
                junc[jid] = (float(el.get('x')), float(el.get('y')))
            except Exception:
                pass
    elif el.tag == 'tlLogic':
        tl.add(el.get('id'))
    elif el.tag == 'edge' and el.get('function') is None:
        raw.append((el.get('from'), el.get('to')))
    el.clear()

segs = [[junc[a], junc[b]] for a, b in raw if a in junc and b in junc]
assert segs, 'no resolvable edge geometry'
indeg = collections.Counter(b for a, b in raw)
outdeg = collections.Counter(a for a, b in raw)

sig = [j for j in junc if j in tl]
src = [j for j in junc if indeg.get(j, 0) == 0 and outdeg.get(j, 0) > 0]
oth = [j for j in junc if j not in tl and j not in src]

SIG = dict(s=14, c='#C0504D', edgecolors='#802020', linewidths=0.2, zorder=4, marker='o')
ORG = dict(s=10, c='#548235', edgecolors='#2E5020', linewidths=0.2, zorder=3, marker='^')
OTH = dict(s=2, c='#B0BEC5', zorder=2, alpha=0.4)


def draw(ax):
    ax.add_collection(LineCollection(segs, colors='#78909C', linewidths=0.5, alpha=0.5))
    ax.scatter([junc[j][0] for j in oth], [junc[j][1] for j in oth], **OTH)
    ax.scatter([junc[j][0] for j in src], [junc[j][1] for j in src], **ORG)
    ax.scatter([junc[j][0] for j in sig], [junc[j][1] for j in sig], **SIG)
    ax.set_aspect('equal')
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_linewidth(0.5)
        sp.set_color('#CCC')


def frame(ax, pts, pad=0.03):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    dx = (max(xs) - min(xs)) * pad
    dy = (max(ys) - min(ys)) * pad
    ax.set_xlim(min(xs) - dx, max(xs) + dx)
    ax.set_ylim(min(ys) - dy, max(ys) + dy)


def scalebar(ax, metres):
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    w = (x1 - x0) * 0.02
    yb = y0 + (y1 - y0) * 0.045
    ax.plot([x0 + w, x0 + w + metres], [yb, yb], color='k', lw=2.2,
            solid_capstyle='butt', zorder=8)
    ax.text(x0 + w + metres / 2.0, yb + (y1 - y0) * 0.012, '%d m' % metres,
            ha='center', fontsize=7)


nodes_used = [junc[a] for a, b in raw if a in junc] + [junc[b] for a, b in raw if b in junc]
cx = sum(p[0] for p in nodes_used) / len(nodes_used)
cy = sum(p[1] for p in nodes_used) / len(nodes_used)
near = min(sig, key=lambda j: (junc[j][0] - cx) ** 2 + (junc[j][1] - cy) ** 2)
zx, zy = junc[near]

fig, axes = plt.subplots(1, 2, figsize=(9.8, 5.0),
                         gridspec_kw={'width_ratios': [1.0, 1.08]})

draw(axes[0])
frame(axes[0], [p for s in segs for p in s])
scalebar(axes[0], 500)
axes[0].set_title('KG corridor, full network\n%d signalised, %d origins, %d sections'
                  % (len(sig), len(src), len(segs)), fontsize=9, fontweight='bold', pad=4)

R = 500.0
draw(axes[1])
cam = Circle((zx, zy), R, transform=axes[1].transData)
for a in list(axes[1].collections):
    a.set_clip_path(cam)
axes[1].set_xlim(zx - R * 1.05, zx + R * 1.05)
axes[1].set_ylim(zy - R * 1.05, zy + R * 1.05)
axes[1].add_patch(Circle((zx, zy), R, transform=axes[1].transData, facecolor='none',
                         edgecolor='#999', lw=0.6, ls='--'))
n_sig = sum(1 for j in sig if (junc[j][0] - zx) ** 2 + (junc[j][1] - zy) ** 2 <= R * R)
n_src = sum(1 for j in src if (junc[j][0] - zx) ** 2 + (junc[j][1] - zy) ** 2 <= R * R)
axes[1].set_title('500 m radius around %s\n%d signalised, %d origins'
                  % (near, n_sig, n_src), fontsize=9, fontweight='bold', pad=4)

fig.legend(handles=[
    Line2D([], [], marker='o', ls='', ms=5, mfc='#C0504D', mec='#802020', mew=0.2, label='Signalised'),
    Line2D([], [], marker='^', ls='', ms=5, mfc='#548235', mec='#2E5020', mew=0.2, label='Origin'),
    Line2D([], [], marker='o', ls='', ms=2, mfc='#B0BEC5', mec='none', label='Other node'),
    Line2D([], [], color='#78909C', lw=0.8, alpha=0.6, label='Section'),
], loc='lower center', ncol=4, frameon=False, fontsize=8)
fig.subplots_adjust(left=0.02, right=0.98, top=0.86, bottom=0.10, wspace=0.06)
plt.savefig('kg_network_lightsim_style.png', dpi=300, facecolor='white')
print('signalised=%d origins=%d sections=%d junctions=%d' % (len(sig), len(src), len(segs), len(junc)))
print('zoom centre=%s (%.0f, %.0f)  in-radius: %d sig, %d orig' % (near, zx, zy, n_sig, n_src))
print('saved kg_network_lightsim_style.png')
