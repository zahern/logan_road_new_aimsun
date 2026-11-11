"""train_dqn_pax.py -- train a phase-selection DQN on the pax-weighted LightSim
env (lightsim_pax_env.py).

Paper-faithful path: single-intersection DQN via stable-baselines3 (as in the
LightSim single-intersection experiments). If stable-baselines3 / torch are not
installed, falls back to a small self-contained linear Q-learner (numpy only) so
a smoke still runs in the gymnasium+pettingzoo+numpy venv.

Usage (HPC: install SB3+torch in the job, NOT on the login node -- AGENTS RULE 1):
    python train_dqn_pax.py --sumocfg .../kg_scenario/kg.sumocfg \
        --agent <TLS_ID> --timesteps 200000 --seed 0 --save dqn_pax_kg

Pick <TLS_ID> from the env smoke print, or the busiest junction from
_lightsim_probe/junction_rank.csv.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lightsim_pax_env import LightSimPaxSingleEnv   # noqa: E402


def _has_sb3():
    try:
        import stable_baselines3  # noqa: F401
        import torch              # noqa: F401
        return True
    except Exception:
        return False


def train_sb3(env, timesteps, seed, save):
    from stable_baselines3 import DQN
    model = DQN(
        "MlpPolicy", env, seed=seed, verbose=1,
        learning_rate=5e-4, buffer_size=100_000, learning_starts=2_000,
        batch_size=64, gamma=0.95, train_freq=4, target_update_interval=1_000,
        exploration_fraction=0.3, exploration_final_eps=0.02,
        policy_kwargs=dict(net_arch=[128, 128]))
    model.learn(total_timesteps=int(timesteps), progress_bar=False)
    if save:
        model.save(save)
        print("[SB3] saved ->", save + ".zip")
    return model


def train_linear_q(env, timesteps, seed, save):
    """Minimal linear-Q(lambda=0) learner -- no torch. Features = obs; one weight
    vector per action. Enough to sanity-check the env and get a non-random
    baseline; NOT a replacement for the DQN."""
    rng = np.random.default_rng(seed)
    nA = env.action_space.n
    dim = env.observation_space.shape[0]
    W = np.zeros((nA, dim + 1), np.float32)     # +1 bias
    alpha, gamma = 0.01, 0.95
    eps, eps_end, eps_frac = 1.0, 0.02, 0.3
    feat = lambda o: np.concatenate([o, [1.0]]).astype(np.float32)
    q = lambda f: W @ f
    obs, _ = env.reset(seed=seed)
    f = feat(obs)
    steps = int(timesteps)
    ret, ep_ret = [], 0.0
    for i in range(steps):
        e = max(eps_end, eps - (eps - eps_end) * (i / (eps_frac * steps)))
        a = int(rng.integers(nA)) if rng.random() < e else int(np.argmax(q(f)))
        nobs, r, term, trunc, _ = env.step(a)
        ep_ret += r
        nf = feat(nobs)
        target = r + (0.0 if (term or trunc) else gamma * float(np.max(q(nf))))
        W[a] += alpha * (target - float(q(f)[a])) * f
        f = nf
        if term or trunc:
            ret.append(ep_ret); ep_ret = 0.0
            obs, _ = env.reset()
            f = feat(obs)
            if len(ret) % 5 == 0:
                print("[linQ] episode %d  mean_ret(last5)=%.1f  eps=%.2f"
                      % (len(ret), np.mean(ret[-5:]), e))
    if save:
        np.save(save + "_linq.npy", W)
        print("[linQ] saved ->", save + "_linq.npy")
    return W


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", required=True)
    ap.add_argument("--agent", required=True, help="TLS/junction id to control")
    ap.add_argument("--timesteps", type=int, default=200_000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--save", default="dqn_pax")
    ap.add_argument("--bus-occ", type=float, default=40.0)
    ap.add_argument("--car-occ", type=float, default=1.2)
    ap.add_argument("--decision-steps", type=int, default=5)
    ap.add_argument("--min-green", type=float, default=6.0)
    ap.add_argument("--max-steps", type=float, default=3600.0)
    ap.add_argument("--force-linq", action="store_true",
                    help="skip SB3 even if present (use the numpy fallback)")
    args = ap.parse_args()

    env = LightSimPaxSingleEnv(
        os.path.abspath(args.sumocfg), args.agent,
        bus_occ=args.bus_occ, car_occ=args.car_occ,
        decision_steps=args.decision_steps, min_green=args.min_green,
        max_steps=args.max_steps, seed=args.seed)

    if args.force_linq:
        # Report the REASON: a forced run is not evidence that SB3 is absent,
        # and the old message said exactly that.
        print("[train] --force-linq -> numpy linear-Q (SB3 skipped on request)")
        train_linear_q(env, args.timesteps, args.seed, args.save)
    elif _has_sb3():
        print("[train] stable-baselines3 DQN (paper-faithful)")
        train_sb3(env, args.timesteps, args.seed, args.save)
    else:
        print("[train] SB3/torch not available -> numpy linear-Q fallback "
              "(install stable-baselines3+torch for the real DQN)")
        train_linear_q(env, args.timesteps, args.seed, args.save)
    env.close()


if __name__ == "__main__":
    main()
