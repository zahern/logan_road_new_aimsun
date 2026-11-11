"""linq_obs_ab.py -- does the pax-channel normalisation change the learned policy?

Evidence for "the policy changes", not just "the observation changes".

Trains the SAME linear-Q learner (reuses train_dqn_pax.train_linear_q), with the
same seed and the same number of decisions, twice:

  old : the pax channel divided by its own per-junction max   (the removed code)
  new : the absolute channel now in lightsim_pax_env.py

The `new` weights are the ones train_dqn_pax.py already produced
(--timesteps 600 --max-steps 600 --seed 0), so only the `old` arm is trained
here. Both policies are then asked for a greedy action on the SAME states and
the disagreement rate is reported -- if the channel mattered, the policies must
differ on states where a bus is present.

Usage:
  python linq_obs_ab.py --sumocfg .../kg.sumocfg --agent n39606 \
      --weights linq_pax_linq.npy
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lightsim_pax_env as L                                  # noqa: E402
from train_dqn_pax import train_linear_q                      # noqa: E402

_ORIG_OBS = L.LightSimPaxParallelEnv._obs_one


def _obs_normalised(self, t):
    """The removed behaviour: divide the pax channel by its current max."""
    o = _ORIG_OBS(self, t).copy()
    g = self._MAXG
    m = float(o[-g:].max()) or 1.0
    o[-g:] = o[-g:] / m
    return o


def _feat(o):
    return np.concatenate([o, [1.0]]).astype(np.float32)


def train(patched, cfg, agent, seed, steps, max_steps):
    L.LightSimPaxParallelEnv._obs_one = _obs_normalised if patched else _ORIG_OBS
    env = L.LightSimPaxSingleEnv(cfg, agent, seed=seed, max_steps=max_steps)
    W = train_linear_q(env, steps, seed, None)
    env.close()
    return W


def sample_states(cfg, agent, seed, n, max_steps):
    """States from the CURRENT (absolute) env, to score both policies on."""
    L.LightSimPaxParallelEnv._obs_one = _ORIG_OBS
    env = L.LightSimPaxSingleEnv(cfg, agent, seed=seed, max_steps=max_steps)
    rng = np.random.default_rng(seed + 7)
    out = []
    obs, _ = env.reset()
    for _ in range(n):
        out.append(obs.copy())
        a = int(env.action_space.sample())
        obs, _r, term, trunc, _i = env.step(a)
        if term or trunc:
            obs, _ = env.reset()
    g = env._p._MAXG
    env.close()
    return np.asarray(out, np.float32), g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", required=True)
    ap.add_argument("--agent", default="n39606")
    ap.add_argument("--weights", default="linq_pax_linq.npy")
    ap.add_argument("--steps", type=int, default=600)
    ap.add_argument("--max-steps", type=float, default=600.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-states", type=int, default=300)
    a = ap.parse_args()

    cfg = os.path.abspath(a.sumocfg)
    print("[AB] training the OLD-observation arm (same seed/steps)...", flush=True)
    W_old = train(True, cfg, a.agent, a.seed, a.steps, a.max_steps)
    W_new = np.load(a.weights)
    print("[AB] W_old=%s  W_new=%s" % (W_old.shape, W_new.shape), flush=True)

    flat_old, flat_new = W_old.ravel(), W_new.ravel()
    cos = float(flat_old @ flat_new /
                (np.linalg.norm(flat_old) * np.linalg.norm(flat_new) + 1e-12))
    print("[AB] identical=%s  max|dW|=%.4f  cosine=%.4f"
          % (np.allclose(W_old, W_new), float(np.abs(W_old - W_new).max()), cos),
          flush=True)

    S, g = sample_states(cfg, a.agent, a.seed, a.n_states, a.max_steps)
    S_old = S.copy()
    for i in range(len(S_old)):
        m = float(S_old[i, -g:].max()) or 1.0
        S_old[i, -g:] /= m
    F_new = np.concatenate([S, np.ones((len(S), 1), np.float32)], axis=1)
    F_old = np.concatenate([S_old, np.ones((len(S_old), 1), np.float32)], axis=1)
    A_new = np.argmax(F_new @ W_new.T, axis=1)
    A_old = np.argmax(F_old @ W_old.T, axis=1)
    dis = float(np.mean(A_new != A_old))
    print("[AB] states=%d  greedy_disagreement=%.1f%%" % (len(S), 100.0 * dis),
          flush=True)
    for name, A in (("new", A_new), ("old", A_old)):
        h = np.bincount(A, minlength=W_new.shape[0])
        print("[AB] %s action mix: %s" % (name, h.tolist()), flush=True)
    print("[AB] policy_changed=%s" % (dis > 0.0), flush=True)


if __name__ == "__main__":
    main()
