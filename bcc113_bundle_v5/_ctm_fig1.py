"""Figure-1 style CTM mechanics, numbers taken from ctm_lightsim._geom_parts.

KG link s21546 (247.8 m, 2 lanes): 9 cells of 27.8 m, N=11.1 veh/cell, Q=2.0 veh/step.
Units: S, R in veh/h (per link = per-lane x lanes); q also shown per step.
"""
import sys
import types
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch

sys.path.insert(0, 'shared_tsp_engine')
import ctm_lightsim as LS

plt.rcParams.update({"font.family": "serif", "text.usetex": False, "font.size": 9})

g = types.SimpleNamespace(length_m=247.8, lanes=2, v_free_kmh=50.0,
                          w_back_kmh=18.0, k_jam_vkm_lane=200.0,
                          q_sat_vph_lane=1800.0)
K, LCELL, N, QSTEP, WR = LS._geom_parts(g)
VF, W, KJ, QL, LANES, DT = 50.0, 18.0, 200.0, 1800.0, 2, 2.0

k_up, k_dn = 120, 60                               # veh/km/lane
S = min(VF * k_up, QL) * LANES                     # veh/h, upstream sending
R = min(QL, W * (KJ - k_dn)) * LANES               # veh/h, downstream receiving
q = min(S, R)
print('cells=%d L=%.2fm N=%.2f Q=%.2fveh/step | S=%d R=%d q=%d veh/h = %.2f veh/step'
      % (K, LCELL, N, QSTEP, S, R, q, q / 3600.0 * DT))

fig = plt.figure(figsize=(11.4, 3.6))
gs = fig.add_gridspec(1, 3, width_ratios=[2.4, 1.4, 1.25], wspace=0.14)
axa, axb, axc = fig.add_subplot(gs[0]), fig.add_subplot(gs[1]), fig.add_subplot(gs[2])
cmap = plt.get_cmap('Reds')

kvals = [60, 60, 60, 120, 120]
for i, k in enumerate(kvals):
    axa.add_patch(Rectangle((i, 0), 0.92, 1.0, facecolor=cmap(0.15 + 0.7 * k / KJ),
                            edgecolor='#7f1d1d', lw=0.8, alpha=0.9))
    axa.text(i + 0.46, -0.20, 'Cell %d' % (i + 1), ha='center', fontsize=7.5)
    axa.text(i + 0.46, 1.08, 'k=%d' % k, ha='center', fontsize=7.5)
    if i < len(kvals) - 1:
        axa.annotate('', xy=(i + 1.0, 0.5), xytext=(i + 0.92, 0.5),
                     arrowprops=dict(arrowstyle='-|>', lw=0.9, color='#37474F'))
axa.plot([0.0, 4.92], [-0.42, -0.42], color='#607D8B', lw=1.0)
for xx in (0.0, 4.92):
    axa.plot([xx, xx], [-0.42, -0.35], color='#607D8B', lw=1.0)
axa.text(2.46, -0.60, 'Link: %d cells x %.1f m  ($v_f\Delta t$),  cells 1-5 of %d shown'
         % (K, LCELL, K), ha='center', fontsize=8, style='italic')
axa.set_xlim(-0.1, 5.05); axa.set_ylim(-0.78, 1.34); axa.set_axis_off()
axa.set_title('(a)  A link discretised into cells', fontsize=8.5, loc='left')

axb.add_patch(Rectangle((0.0, 0), 0.9, 1.0, facecolor=cmap(0.57), edgecolor='#7f1d1d', lw=0.8))
axb.add_patch(Rectangle((1.7, 0), 0.9, 1.0, facecolor=cmap(0.36), edgecolor='#7f1d1d', lw=0.8))
axb.text(0.45, -0.14, 'Cell i\nk=%d' % k_up, ha='center', fontsize=7.2)
axb.text(2.15, -0.14, 'Cell i+1\nk=%d' % k_dn, ha='center', fontsize=7.2)
axb.annotate('', xy=(1.72, 0.66), xytext=(0.92, 0.66),
             arrowprops=dict(arrowstyle='-|>', lw=1.5, color='#1B5E20'))
axb.text(1.31, 0.74, 'S$_i$=%d' % S, ha='center', fontsize=7.5, color='#1B5E20')
axb.annotate('', xy=(0.92, 0.34), xytext=(1.72, 0.34),
             arrowprops=dict(arrowstyle='-|>', lw=1.5, color='#B71C1C'))
axb.text(1.31, 0.13, 'R$_{i+1}$=%d' % R, ha='center', fontsize=7.5, color='#B71C1C')
axb.text(1.31, -0.52, 'q = min(S$_i$, R$_{i+1}$)  [veh/h]\n= %d veh/h = %.2f veh/step ($\Delta t$=%.0f s)'
         % (q, q / 3600.0 * DT, DT), ha='center', fontsize=7.4)
axb.set_xlim(-0.1, 2.72); axb.set_ylim(-0.88, 1.12); axb.set_axis_off()
axb.set_title('(b)  Flow = min(supply, demand)', fontsize=8.5, loc='left')

axc.add_patch(Rectangle((0.34, 0.34), 0.32, 0.32, facecolor='#ECEFF1',
                         edgecolor='#37474F', lw=1.0))
for dx, dy, col, lab in ((0, 1, '#1B5E20', 'N'), (0, -1, '#1B5E20', 'S'),
                         (1, 0, '#B71C1C', 'E'), (-1, 0, '#B71C1C', 'W')):
    axc.add_patch(FancyArrowPatch((0.5 + dx * 0.36, 0.5 + dy * 0.36),
                                  (0.5 + dx * 0.60, 0.5 + dy * 0.60),
                                  arrowstyle='-|>', mutation_scale=11, lw=2.2, color=col))
    axc.text(0.5 + dx * 0.74, 0.5 + dy * 0.74, lab, ha='center', va='center',
             fontsize=9, fontweight='bold', color=col)
axc.text(0.5, 0.5, r'$\sigma_m$', ha='center', va='center', fontsize=10)
axc.text(0.5, -0.52, r'flow$_m$ = $\sigma_m\cdot\min(S_i,\,R_{i+1})$',
         ha='center', fontsize=7.4)
axc.text(0.5, -0.70, r'$\sigma_m\in\{0,1\}$ per movement',
         ha='center', fontsize=7.0, style='italic')
axc.set_xlim(-0.30, 1.30); axc.set_ylim(-0.85, 1.40)
axc.set_axis_off()
axc.set_title('(c)  Signal mask at a junction', fontsize=8.5, loc='left', pad=10)

plt.savefig('ctm_mechanics_fig1_style.png', dpi=300, bbox_inches='tight', facecolor='white')
print('saved ctm_mechanics_fig1_style.png')
