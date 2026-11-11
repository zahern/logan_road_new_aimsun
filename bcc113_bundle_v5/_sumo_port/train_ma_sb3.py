"""train_ma_sb3.py -- the paper's Stable-Baselines3 DQN, driven through the SAME
multi-agent shared-parameter loop as train_ma_dqn.py, so the numpy
shared_tsp_engine/dqn_base.NumpyDQN can be checked against it on the same env,
the same seed and the same transitions.

Why not model.learn(): SB3 has no multi-agent API. Its DQN owns a size-1 replay
buffer and a `train(gradient_steps, batch_size)` method, so this script keeps the
multi-agent loop (one shared network, 27 junctions, raw MAXG head action, done on
truncation) and swaps ONLY the learner:

    model = DQN("MlpPolicy", <spaces-only env>)
    model.replay_buffer.add(s, s2, a, r, done, {})     # per agent transition
    model.train(gradient_steps=1)                      # every --train-every

Hyperparameters are matched to NumpyDQN -- 2x64 ReLU, Adam lr 1e-3, gamma 0.99,
batch 32, target sync every 500 updates, epsilon 1.0 -> 0.05 over 4000
transitions, warmup 100, train every 4 transitions -- so the remaining
differences are implementation, not tuning: SB3 uses the Huber loss where the
numpy learner uses squared error, and its own init/optimiser bookkeeping.

Usage:
  python train_ma_sb3.py --sumocfg .../kg.sumocfg --decisions 2000 \
      --seed 0 --save ma_dqn_sb3
"""
import argparse
import os
import sys
import time

import gymnasium as gym
import numpy as np
from gymnasium import spaces

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "shared_tsp_engine"))

from lightsim_pax_env import LightSimPaxParallelEnv   # noqa: E402


class _SpacesEnv(gym.Env):
    """Spaces carrier only. SB3 needs an env to build the policy and its replay
    buffer; it is never stepped -- the multi-agent loop pushes every agent
    transition into model.replay_buffer directly."""

    metadata = {"render_modes": []}

    def __init__(self, obs_dim, n_actions):
        super().__init__()
        self.observation_space = spaces.Box(0.0, 1e6, (int(obs_dim),), np.float32)
        self.action_space = spaces.Discrete(int(n_actions))
        self._zeros = np.zeros(int(obs_dim), np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        return self._zeros, {}

    def step(self, action):
        return self._zeros, 0.0, False, False, {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--decisions", type=int, default=2000)
    ap.add_argument("--max-steps", type=float, default=1200.0)
    ap.add_argument("--save", default="ma_dqn_sb3")
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--gamma", type=float, default=0.99)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--buffer", type=int, default=50000)
    ap.add_argument("--eps-steps", type=int, default=4000)
    ap.add_argument("--eps-end", type=float, default=0.05)
    ap.add_argument("--warmup", type=int, default=100)
    ap.add_argument("--train-every", type=int, default=4)
    ap.add_argument("--target-every", type=int, default=500)
    ap.add_argument("--report-every", type=int, default=25)
    a = ap.parse_args()

    import torch
    from stable_baselines3 import DQN

    env = LightSimPaxParallelEnv(os.path.abspath(a.sumocfg), seed=a.seed,
                                 max_steps=float(a.max_steps))
    obs, _ = env.reset()
    print("[SB3-MA] agents=%d obs_dim=%d MAXG=%d MAXL=%d"
          % (len(env.agents), env._obs_dim, env._MAXG, env._MAXL), flush=True)

    model = DQN(
        "MlpPolicy", _SpacesEnv(env._obs_dim, env._MAXG), seed=a.seed,
        learning_rate=a.lr, buffer_size=a.buffer, learning_starts=0,
        batch_size=a.batch, gamma=a.gamma,
        train_freq=(a.train_every, "step"), gradient_steps=0,
        target_update_interval=a.target_every,
        exploration_fraction=1.0, exploration_initial_eps=1.0,
        exploration_final_eps=a.eps_end,
        policy_kwargs=dict(net_arch=[a.hidden, a.hidden]), verbose=0)
    # DQN.train() reads the LR schedule progress and records into self._logger;
    # both are learn()-time setup, and __init__ leaves _logger unset entirely
    # (base_class.py:430 assigns it in _setup_learn). This manual drive has to
    # install them itself.
    model._current_progress_remaining = 1.0
    from stable_baselines3.common.logger import configure
    model.set_logger(configure(folder=None, format_strings=[]))

    rng = np.random.default_rng(a.seed + 10007)
    n_trans = 0
    n_upd = 0
    episode = 0
    t0 = time.time()
    for step in range(1, a.decisions + 1):
        agents = list(env.agents)
        S = np.asarray([obs[ag] for ag in agents], np.float32)
        with torch.no_grad():
            q = model.q_net(torch.as_tensor(S)).cpu().numpy()
        greedy = q.argmax(axis=1)
        # epsilon is a function of AGENT TRANSITIONS, exactly like NumpyDQN's
        # self.steps, so both learners explore on the same budget.
        eps = 1.0 + min(1.0, n_trans / float(a.eps_steps)) * (a.eps_end - 1.0)
        acts, pending = {}, {}
        for i, ag in enumerate(agents):
            raw = int(greedy[i])
            if rng.random() < eps:
                raw = int(rng.integers(env._MAXG))
            acts[ag] = raw % env.tls[ag].n_green   # executed phase
            pending[ag] = (S[i], raw)              # store the raw head index
        obs2, rew, _term, _trunc, _info = env.step(acts)
        done = not env.agents
        for ag, (s, raw) in pending.items():
            s2 = np.asarray(obs2.get(ag, s), np.float32)
            model.replay_buffer.add(
                s[None, :], s2[None, :], np.array([raw], np.int64),
                np.array([float(rew.get(ag, 0.0))], np.float32),
                np.array([done], np.float32), [{}])
            n_trans += 1
            if n_trans > a.warmup and n_trans % a.train_every == 0:
                model.train(gradient_steps=1, batch_size=a.batch)
                n_upd += 1
        obs = obs2
        if done:
            episode += 1
            obs, _ = env.reset()
        if step % a.report_every == 0:
            loss = model.logger.name_to_value.get("train/loss", float("nan"))
            print("[SB3-MA] step=%d/%d eps=%.3f updates=%d loss=%.4f n=%d "
                  "episodes=%d wall=%.0fs"
                  % (step, a.decisions, eps, n_upd, loss,
                     model.replay_buffer.size(), episode, time.time() - t0),
                  flush=True)

    env.close()
    if a.save:
        model.save(a.save)
        print("[SB3-MA] saved -> %s.zip (transitions=%d updates=%d)"
              % (a.save, n_trans, n_upd), flush=True)


if __name__ == "__main__":
    main()
