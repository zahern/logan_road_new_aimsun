"""Figure-2 style environment management, using the vertwined LightSim API.

Signatures are the vendored package's own:
  lightsim.envs.single_agent.LightSimEnv(gym.Env)
      reset(seed=, options=) -> (obs, info)
      step(action) -> (obs, reward, terminated, truncated, info)
  lightsim.envs.multi_agent.LightSimParallelEnv(ParallelEnv)
      agents == possible_agents == ['signal_<node_id>', ...]
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams.update({"font.family": "serif", "text.usetex": False, "font.size": 8.5})

fig, ax = plt.subplots(figsize=(9.6, 4.2))
ax.set_xlim(0, 10); ax.set_ylim(0, 4.4); ax.axis('off')

def box(x, y, w, h, title, body='', fc='#FFFFFF', ec='#37474F', tc='#102027'):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.06,rounding_size=0.08',
                                fc=fc, ec=ec, lw=1.0, zorder=2))
    ax.text(x + w / 2, y + h - 0.16, title, ha='center', va='top',
            fontsize=8.4, fontweight='bold', color=tc, zorder=3)
    if body:
        ax.text(x + w / 2, y + h - 0.50, body, ha='center', va='top',
                fontsize=7.1, color='#37474F', zorder=3, linespacing=1.35)

def arrow(p, q, style='-|>', col='#37474F', lw=1.1, rad=0.0):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=10,
                                 lw=lw, color=col, zorder=1,
                                 connectionstyle='arc3,rad=%s' % rad))

box(0.15, 3.05, 2.55, 1.05, 'OSM network',
    'from_osm_point(lat, lon, r=500 m)\n-> lightsim Network', fc='#F4F7F9')
box(3.30, 2.95, 2.85, 1.25, 'LightSimEnv  (gymnasium.Env)',
    'one signalised node\nreset() -> (obs, info)\nstep(a) -> obs, r, term, trunc, info')
box(3.30, 1.35, 2.85, 1.25, 'LightSimParallelEnv  (PettingZoo)',
    "agents = ['signal_<nid>']\nreset() -> {agent: obs}\nstep({a}) -> {agent: (...)}",
    fc='#F2F7F2')
arrow((2.75, 3.58), (3.28, 3.58))
arrow((2.75, 3.20), (3.28, 2.00))

box(6.60, 2.15, 3.10, 1.15, 'Signal controller',
    'action_handler = phase_select\nobs_builder / reward_fn\n= queue | delay | throughput')
arrow((6.17, 3.58), (6.58, 3.10))
arrow((6.17, 1.98), (6.58, 2.30))

ax.add_patch(FancyBboxPatch((0.15, 0.30), 9.55, 0.72,
                            boxstyle='round,pad=0.06,rounding_size=0.08',
                            fc='#FBFBFB', ec='#90A4AE', lw=0.9, zorder=2))
ax.text(0.35, 0.86, 'SimulationEngine.step()  x sim_steps_per_action',
        fontsize=8.0, fontweight='bold', va='top', zorder=3)
ax.text(0.35, 0.62, 'cell update  n_i(t+dt) = n_i(t) + q_{i-1}(t) - q_i(t)      '
        'q_m = sigma_m * min(S_i, R_{i+1})      demand injected at origin links',
        fontsize=7.2, va='top', color='#37474F', zorder=3)
arrow((8.15, 2.12), (8.15, 1.06), col='#1B5E20')
arrow((1.42, 1.04), (1.42, 2.93), col='#B71C1C', rad=0.0)
ax.text(1.52, 1.95, 'obs / reward\nback to agent', fontsize=6.9, color='#B71C1C', va='center')

ax.set_title('Environment management: one CTM, two agent APIs',
             fontsize=9.5, fontweight='bold', pad=6)
plt.tight_layout()
plt.savefig('ctm_environment_fig2_style.png', dpi=300, bbox_inches='tight', facecolor='white')
print('saved ctm_environment_fig2_style.png')
