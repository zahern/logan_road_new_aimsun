"""Smoke-roll the KG multi-agent env with random actions.

    python run_smoke.py
    python run_smoke.py --steps 60 --shared-reward
"""
import argparse
import numpy as np

from kg_multiagent_env import KGMultiAgentEnv
from configs import kg as K


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", default=K.SUMOCFG)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--horizon", type=int, default=1200)
    ap.add_argument("--shared-reward", action="store_true")
    args = ap.parse_args()

    env = KGMultiAgentEnv({
        "sumocfg": args.sumocfg,
        "horizon": args.horizon,
        "warmup": K.WARMUP_S,
        "shared_reward": args.shared_reward,
    })
    obs, infos = env.reset()
    print("agents:", len(env.agents), "obs_size:", next(iter(obs.values())).shape)
    rng = np.random.default_rng(7)
    total = 0.0
    for i in range(args.steps):
        acts = {a: int(rng.integers(0, 4)) for a in env.agents}
        obs, rew, term, trunc, infos = env.step(acts)
        total += sum(rew.values())
        if i % 5 == 0:
            print("step %3d  t=%7.1f  mean_rew=%+.2f"
                  % (i, __import__("traci").simulation.getTime(),
                     np.mean(list(rew.values()))))
        if term.get("__all__"):
            print("episode ended at step", i)
            break
    print("smoke ok; cumulative reward = %.2f" % total)
    env.close()


if __name__ == "__main__":
    main()
