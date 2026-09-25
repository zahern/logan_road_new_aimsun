#!/usr/bin/env python3
"""test_global_reward_flags.py -- offline: GLOBAL_REWARD flag plumbing."""
import sys

sys.path.insert(0, "shared_tsp_engine")
import specialized_modes as spm

fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# 1. defaults: flag off, horizon sane
check("default GLOBAL_REWARD_MODE is False", spm.GLOBAL_REWARD_MODE is False)
check("default CHAIN_HORIZON is 3", spm.GLOBAL_REWARD_CHAIN_HORIZON == 3)
# 2. registered for propagation + reset
check("MODE_FLAGS has GLOBAL_REWARD_MODE", "GLOBAL_REWARD_MODE" in spm.MODE_FLAGS)
check("MODE_FLAGS has CHAIN_HORIZON", "GLOBAL_REWARD_CHAIN_HORIZON" in spm.MODE_FLAGS)
check("MODE_TOGGLES has GLOBAL_REWARD_MODE", "GLOBAL_REWARD_MODE" in spm.MODE_TOGGLES)
# 3. reset restores pristine defaults after a simulated run_config apply
spm.GLOBAL_REWARD_MODE = True
spm.GLOBAL_REWARD_CHAIN_HORIZON = 9
spm.reset_mode_flags()
check("reset restores MODE False", spm.GLOBAL_REWARD_MODE is False)
check("reset restores horizon 3", spm.GLOBAL_REWARD_CHAIN_HORIZON == 3)
# 4. snapshot captured the new defaults at import (not polluted)
check("snapshot has MODE default False",
      spm._MODE_FLAG_DEFAULTS.get("GLOBAL_REWARD_MODE") is False)
check("snapshot has horizon default 3",
      spm._MODE_FLAG_DEFAULTS.get("GLOBAL_REWARD_CHAIN_HORIZON") == 3)

print("ALL OK" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
