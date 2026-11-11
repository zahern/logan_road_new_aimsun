"""train_ma_dqn.py -- multi-agent shared-parameter DQN over LightSimPaxParallelEnv.

The paper's multi-agent setup (Su & Deng 2026, grid 4x4): ONE policy shared by
every agent, independent learners, observations zero-padded to a common width.
LightSimPaxParallelEnv already emits a fixed network-wide width (MAXG/MAXL), so
sharing is exact here: every junction feeds the SAME network instance.

No torch / Stable-Baselines3 is required -- this reuses
shared_tsp_engine/dqn_base.NumpyDQN (2x64 ReLU MLP, Adam 1e-3, gamma 0.99,
replay, target net), the same agent used for the BASE_PLAN DQN work.

Two details that matter:

  * the network has MAXG outputs, so the action STORED in the replay buffer is
    the raw head index. The env maps it with `action % n_green` for junctions
    with fewer greens; two raw indices can therefore execute the same phase on
    a 2-green junction. That is the usual zero-padding artefact: the Q values
    stay consistent with what was executed, they are just duplicated.
  * a terminal observation is unavailable when the episode truncates, so the
    last transition of an episode reuses its own state and is marked done.

Usage:
  python train_ma_dqn.py --sumocfg .../kg.sumocfg --decisions 300 \
      --seed 0 --save ma_dqn_pax
"""
import argparse
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "shared_tsp_engine"))

from lightsim_pax_env import LightSimPaxParallelEnv   # noqa: E402
from dqn_base import NumpyDQN                         # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--decisions", type=int, default=300)
    ap.add_argument("--max-steps", type=float, default=1200.0)
    ap.add_argument("--save", default="ma_dqn_pax")
    ap.add_argument("--load", default="")
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--gamma", type=float, default=0.99)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--buffer", type=int, default=50000)
    ap.add_argument("--eps-steps", type=int, default=4000)
    ap.add_argument("--report-every", type=int, default=25)
    a = ap.parse_args()

    env = LightSimPaxParallelEnv(os.path.abspath(a.sumocfg), seed=a.seed,
                                 max_steps=float(a.max_steps))
    obs, _ = env.reset()
    n_agents = len(env.agents)
    print("[MA] agents=%d obs_dim=%d MAXG=%d MAXL=%d"
          % (n_agents, env._obs_dim, env._MAXG, env._MAXL), flush=True)

    pol = NumpyDQN(env._obs_dim, env._MAXG, hidden=a.hidden, lr=a.lr,
                   gamma=a.gamma, batch=a.batch, buffer=a.buffer,
                   eps_steps=a.eps_steps, target_every=500, train_every=4,
                   warmup=100, seed=a.seed)
    if a.load and os.path.exists(a.load):
        pol.load(a.load)
        print("[MA] resumed %s (steps=%d updates=%d)"
              % (a.load, pol.steps, pol.updates), flush=True)

    t0 = time.time()
    episode = 0
    for step in range(1, a.decisions + 1):
        acts, pending = {}, {}
        for ag in env.agents:
            t = env.tls[ag]
            s = np.asarray(obs[ag], np.float32)
            raw = int(pol.act(s))              # index into the MAXG head
            acts[ag] = raw % t.n_green         # what the env can execute
            pending[ag] = (s, raw)
        obs2, rew, _term, _trunc, _info = env.step(acts)
        done = not env.agents
        for ag, (s, raw) in pending.items():
            s2 = np.asarray(obs2.get(ag, s), np.float32)
            pol.observe(s, raw, float(rew.get(ag, 0.0)), s2, done)
        obs = obs2
        if done:
            episode += 1
            obs, _ = env.reset()
        if step % a.report_every == 0:
            st = pol.stats()
            print("[MA] step=%d/%d eps=%.3f updates=%d loss=%.4f n=%d "
                  "episodes=%d wall=%.0fs"
                  % (step, a.decisions, st["eps"], st["updates"],
                     st["loss"], st["n"], episode, time.time() - t0),
                  flush=True)

    env.close()
    if a.save:
        pol.save(a.save + ".npz")
        print("[MA] saved -> %s.npz (steps=%d updates=%d)"
              % (a.save, pol.steps, pol.updates), flush=True)


if __name__ == "__main__":
    main()
