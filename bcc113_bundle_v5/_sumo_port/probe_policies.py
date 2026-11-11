"""probe_policies.py -- compare the greedy actions of the numpy and SB3 shared
DQNs on the SAME observations from one sumo run.

A large benchmark gap has two very different explanations: the policy is a
legitimate but worse controller, or it collapsed onto one action (which would
look like a fixed-time plan). This measures the action histogram and the
top1-top2 Q margin of each model on observations taken from the same episode,
so the difference can be attributed instead of guessed.

Usage:
  python probe_policies.py --sumocfg .../kg.sumocfg \
      --npz ma_dqn_pax2.npz --zip ma_dqn_sb3.zip --decisions 40 --seed 0
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "shared_tsp_engine"))

from lightsim_pax_env import LightSimPaxParallelEnv   # noqa: E402
from dqn_base import NumpyDQN                         # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", required=True)
    ap.add_argument("--npz", default="ma_dqn_pax2.npz")
    ap.add_argument("--zip", default="ma_dqn_sb3.zip")
    ap.add_argument("--decisions", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    import torch
    from stable_baselines3 import DQN

    env = LightSimPaxParallelEnv(os.path.abspath(a.sumocfg), seed=a.seed,
                                 max_steps=1200.0)
    obs, _ = env.reset()
    print("[probe] agents=%d obs_dim=%d MAXG=%d"
          % (len(env.agents), env._obs_dim, env._MAXG), flush=True)

    S = []
    for _ in range(a.decisions):
        agents = list(env.agents)
        S.append(np.asarray([obs[ag] for ag in agents], np.float32))
        # neutral rollout: hold every junction on its current green
        obs, _r, _t, _tr, _i = env.step(
            {ag: env.tls[ag].cur_green_pos for ag in env.agents})
        if not env.agents:
            break
    env.close()
    S = np.concatenate(S, 0)
    print("[probe] observations collected: %d" % S.shape[0], flush=True)

    nb = NumpyDQN(int(env._obs_dim), int(env._MAXG))
    nb.load(a.npz)
    qn, _ = nb._forward(S, nb.p)

    sb = DQN.load(a.zip, device="cpu")
    with torch.no_grad():
        qs = sb.q_net(torch.as_tensor(S)).cpu().numpy()

    for name, q in (("numpy", qn), ("sb3", qs)):
        idx = q.argmax(axis=1)
        top2 = np.sort(q, axis=1)[:, -2:]
        margin = float(np.mean(top2[:, 1] - top2[:, 0]))
        hist = np.bincount(idx, minlength=int(env._MAXG))
        # how often the chosen action differs from "hold the current phase"
        print("[probe] %-5s argmax hist=%s  mean top1-top2 margin=%.4f  "
              "mean Q=%.4f"
              % (name, hist.tolist(), margin, float(q.mean())), flush=True)

    agree = float(np.mean(qn.argmax(1) == qs.argmax(1)))
    print("[probe] greedy agreement numpy vs sb3 = %.1f%%" % (100.0 * agree),
          flush=True)


if __name__ == "__main__":
    main()
