"""Shared-parameter numpy linear-Q trainer on the KG gym env.

No torch / ray / SB3 required -- trains a single linear Q-function shared
across all 12 junction agents (CTRL-style shared-parameter MARL), using
epsilon-greedy control and a standard Q(lambda=0) update. Proves RL training
works end-to-end on the real KG SUMO corridor via the Gymnasium env.

    python train_numpyq.py --episodes 4 --horizon 1500

The learned weights export to kg_numpyq.npz as plain numpy, ready to drop
into an Aimsun arm (the engine runs numpy, no torch needed).
"""
import argparse
import numpy as np

from kg_multiagent_env import KGMultiAgentEnv
from configs import kg as K


def feats(obs):
    # obs is an 11-vector; append bias term.
    return np.concatenate([np.asarray(obs, dtype=np.float64), [1.0]])


def q_values(W, f):
    # W: (n_actions, n_features)  ->  (n_actions,)
    return W @ f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=4)
    ap.add_argument("--horizon", type=int, default=1500)
    ap.add_argument("--lr", type=float, default=0.02)
    ap.add_argument("--gamma", type=float, default=0.9)
    ap.add_argument("--eps0", type=float, default=0.5)
    ap.add_argument("--eps_min", type=float, default=0.05)
    ap.add_argument("--shared-reward", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="kg_numpyq.npz")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    n_actions = 2
    n_features = 11 + 1  # obs + bias
    W = np.zeros((n_actions, n_features))

    ep_returns = []
    for ep in range(args.episodes):
        eps = max(args.eps_min,
                  args.eps0 * (1.0 - ep / max(1, args.episodes - 1)))
        env = KGMultiAgentEnv({
            "sumocfg": K.SUMOCFG,
            "horizon": args.horizon,
            "warmup": K.WARMUP_S,
            "shared_reward": args.shared_reward,
        })
        obs, _ = env.reset()
        f = {a: feats(obs[a]) for a in env.agents}
        total = 0.0
        updates = 0
        done = False
        while not done:
            acts = {}
            for a in env.agents:
                if rng.random() < eps:
                    acts[a] = int(rng.integers(0, n_actions))
                else:
                    acts[a] = int(np.argmax(q_values(W, f[a])))
            nobs, rew, term, trunc, _ = env.step(acts)
            # Q-update (shared W, every agent's transition is a sample).
            gW = np.zeros_like(W)
            for a in env.agents:
                fa = f[a]
                r = rew[a]
                nf = feats(nobs[a])
                target = r + args.gamma * np.max(q_values(W, nf))
                td = target - q_values(W, fa)[acts[a]]
                gW[acts[a]] += td * fa
                total += r
                updates += 1
            W += args.lr * gW / max(1, len(env.agents))
            f = {a: feats(nobs[a]) for a in env.agents}
            done = bool(term.get("__all__") or trunc.get("__all__"))
        env.close()
        mean_step = total / max(1, updates)
        ep_returns.append(mean_step)
        print("episode %d  eps=%.2f  updates=%d  mean_step_reward=%+.3f"
              % (ep, eps, updates, mean_step))

    np.savez(args.out, W=W, n_actions=n_actions, n_features=n_features)
    print("\nsaved weights -> %s  (W shape %s)" % (args.out, W.shape))
    if len(ep_returns) >= 2:
        print("learning check: first=%+.3f  last=%+.3f  delta=%+.3f"
              % (ep_returns[0], ep_returns[-1], ep_returns[-1] - ep_returns[0]))


if __name__ == "__main__":
    main()
