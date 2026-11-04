"""Train a multi-agent PPO policy on the KG signal-control env.

Mirrors the Flow tutorial14 multi-agent pattern (one policy per intersection,
policy_mapping_fn returns the agent id) using Ray RLlib's native
MultiAgentEnv interface.

Run (after installing requirements):
    python train_marl.py --iters 10
    python train_marl.py --iters 50 --sumocfg Z:\\tsp\\sumo_hpc\\sumo_bridge\\kg_scenario\\kg.sumocfg
"""
import argparse
import os

from ray.rllib.algorithms.ppo import PPOConfig
from ray.tune.registry import register_env

from kg_multiagent_env import KGMultiAgentEnv
from configs import kg as K


def env_creator(env_config):
    return KGMultiAgentEnv(env_config)


register_env("kg_marl", env_creator)


def build_config(args):
    probe = KGMultiAgentEnv({"agents": K.AGENTS})
    obs_space = probe.observation_space
    act_space = probe.action_space

    policies = {a: (None, obs_space, act_space, {}) for a in K.AGENTS}
    mapping = lambda aid, episode=None: aid  # noqa: E731

    cfg = (
        PPOConfig()
        .environment(
            "kg_marl",
            env_config={
                "sumocfg": args.sumocfg,
                "agents": K.AGENTS,
                "horizon": args.horizon,
                "warmup": args.warmup,
                "action_every": args.action_every,
                "shared_reward": args.shared_reward,
            },
        )
        .framework("torch")
        .training(gamma=0.99, lr=1e-4, train_batch_size=args.batch)
        .multi_agent(
            policies=policies,
            policy_mapping_fn=mapping,
            policies_to_train=list(K.AGENTS),
        )
    )
    # Local workers (one process) for a laptop smoke; Ray 2.9+ / older APIs.
    try:
        cfg = cfg.env_runners(num_env_runners=0)
    except Exception:
        try:
            cfg = cfg.rollouts(num_rollout_workers=0)
        except Exception:
            pass
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", default=K.SUMOCFG)
    ap.add_argument("--iters", type=int, default=5)
    ap.add_argument("--horizon", type=int, default=K.HORIZON_S)
    ap.add_argument("--warmup", type=int, default=K.WARMUP_S)
    ap.add_argument("--action-every", type=int, default=K.ACTION_EVERY_S)
    ap.add_argument("--batch", type=int, default=4000)
    ap.add_argument("--shared-reward", action="store_true")
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--checkpoint-dir", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "checkpoints"))
    args = ap.parse_args()

    algo = build_config(args).build()
    if args.checkpoint:
        algo.restore(args.checkpoint)

    for i in range(args.iters):
        res = algo.train()
        rew = res.get("env_runners", {}).get(
            "episode_return_mean", res.get("episode_reward_mean"))
        length = res.get("env_runners", {}).get(
            "episode_len_mean", res.get("episode_len_mean"))
        print("iter %d  return=%s  len=%s" % (i, rew, length))
        os.makedirs(args.checkpoint_dir, exist_ok=True)
        ckpt = algo.save(os.path.join(args.checkpoint_dir, "iter_%03d" % i))
        print("  checkpoint:", ckpt)

    algo.stop()


if __name__ == "__main__":
    main()
