"""train_plan_dqn.py -- train the PLAN-SELECTOR DQN (Layer 1) on the plan-select
env. The agent's action = which coordinated plan from the junction's library
runs the next period; coordination is preserved by construction, so it cannot
gridlock. Passenger weighting is in the state + reward.

Reuses the SB3 / numpy-linear-Q training from train_dqn_pax.py; only the env
differs (PlanSelectPaxSingleEnv instead of the free phase-select env).

Usage (HPC: install SB3+torch in the job, not the login node -- AGENTS RULE 1):
    python train_plan_dqn.py --sumocfg .../kg_scenario/kg.sumocfg \
        --agent <TLS_ID> --timesteps 200000 --period 90 --save plan_dqn_kg

Library selection:
    --plans commissioned,webster,scats_ds     explicit member list
    --scales 0.8,1.0,1.2                     back-compat: commissioned + cycles
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_select_env import PlanSelectPaxSingleEnv          # noqa: E402
from train_dqn_pax import _has_sb3, train_sb3, train_linear_q  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", required=True)
    ap.add_argument("--agent", required=True, help="TLS/junction id to control")
    ap.add_argument("--timesteps", type=int, default=200_000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--save", default="plan_dqn")
    ap.add_argument("--period", type=float, default=90.0,
                    help="decision period (s): how long a selected plan runs")
    ap.add_argument("--plans", default="",
                    help="comma-sep library members (default: --scales variants)")
    ap.add_argument("--scales", default="0.8,1.0,1.2",
                    help="cycle-length library members (comma-sep multipliers)")
    ap.add_argument("--bus-occ", type=float, default=40.0)
    ap.add_argument("--car-occ", type=float, default=1.2)
    ap.add_argument("--max-steps", type=float, default=3600.0)
    ap.add_argument("--force-linq", action="store_true")
    args = ap.parse_args()

    kw = dict(period_s=args.period, bus_occ=args.bus_occ,
              car_occ=args.car_occ, max_steps=args.max_steps, seed=args.seed)
    if args.plans.strip():
        kw["plans"] = [p for p in args.plans.split(",") if p.strip()]
        lib_desc = kw["plans"]
    else:
        kw["scales"] = tuple(float(x) for x in args.scales.split(",") if x.strip())
        lib_desc = ("commissioned",) + kw["scales"]

    env = PlanSelectPaxSingleEnv(os.path.abspath(args.sumocfg), args.agent, **kw)

    print("[train] plan-selector | library=%s | period=%.0fs"
          % (list(lib_desc), args.period))
    if args.force_linq:
        print("[train] --force-linq -> numpy linear-Q (SB3 skipped on request)")
        train_linear_q(env, args.timesteps, args.seed, args.save)
    elif _has_sb3():
        print("[train] stable-baselines3 DQN")
        train_sb3(env, args.timesteps, args.seed, args.save)
    else:
        print("[train] SB3/torch not available -> numpy linear-Q fallback")
        train_linear_q(env, args.timesteps, args.seed, args.save)
    env.close()


if __name__ == "__main__":
    main()
