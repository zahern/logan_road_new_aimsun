"""Print the bus/car reward decomposition for a few steps."""
import numpy as np
from kg_multiagent_env import KGMultiAgentEnv
from configs import kg as K

env = KGMultiAgentEnv({"horizon": 700, "warmup": K.WARMUP_S})
obs, infos = env.reset()
rng = np.random.default_rng(3)
for i in range(8):
    acts = {a: int(rng.integers(0, 4)) for a in env.agents}
    obs, rew, term, trunc, infos = env.step(acts)

parts = env._parts
keys = ("bus_delay_pax_s", "car_delay_pax_s", "bus_waiting", "bus_cleared", "reward")
tot = {k: 0.0 for k in keys}
for p in parts.values():
    for k in keys:
        tot[k] += float(p.get(k, 0.0))
print("last-step reward decomposition (all agents):")
for k in keys:
    print("  %-18s %9.2f" % (k, tot[k]))
print("  %-18s %9.2f" % ("sum(rewards)", sum(rew.values())))
print("\nSample agent:", list(parts.keys())[0], parts[list(parts.keys())[0]])
env.close()
