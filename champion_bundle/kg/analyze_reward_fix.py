#!/usr/bin/env python
"""
Analyze the impact of the reward delta fix.
Compares the old (absolute) vs new (delta) calculation for INS actions.
"""
import csv
import pandas as pd
import glob
from pathlib import Path

# Find the most recent DRL_DENSITY reward CSV
reward_files = sorted(glob.glob('logs/reward_cycle_DRL_DENSITY_*.csv'))
if not reward_files:
    print("No DRL_DENSITY reward files found")
    exit(1)

latest_file = reward_files[-1]
print(f"Analyzing: {latest_file}\n")

# Load the data
df = pd.read_csv(latest_file)

print("=== BEFORE FIX (Current Data) ===")
print(f"Total reward evaluations: {len(df)}")
print(f"Positive rewards: {len(df[df['reward'] > 0])} ({100*len(df[df['reward'] > 0])/len(df):.1f}%)")
print(f"Negative rewards: {len(df[df['reward'] < 0])} ({100*len(df[df['reward'] < 0])/len(df):.1f}%)")
print(f"Zero rewards: {len(df[df['reward'] == 0])} ({100*len(df[df['reward'] == 0])/len(df):.1f}%)")
print(f"\nReward statistics:")
print(f"  Min: {df['reward'].min():,.1f}")
print(f"  Mean: {df['reward'].mean():,.1f}")
print(f"  Median: {df['reward'].median():,.1f}")
print(f"  Max: {df['reward'].max():,.1f}")
print(f"  Std Dev: {df['reward'].std():,.1f}")

# Separate by action type
print("\n=== By Action Type ===")
for action_type in ['NO_ACTION', 'GE_5', 'GE_10', 'GE_15', 'GE_20', 'INS']:
    subset = df[df['action'].str.contains(action_type, na=False)]
    if len(subset) > 0:
        pos_pct = 100 * len(subset[subset['reward'] > 0]) / len(subset)
        print(f"{action_type:15} n={len(subset):4d}  Pos%={pos_pct:5.1f}%  Mean={subset['reward'].mean():10,.1f}")

# Show most extreme cases
print("\n=== Top 10 Most Negative (Usually INS) ===")
top_neg = df.nsmallest(10, 'reward')[['sim_time_s', 'action', 'reward', 'bus_saved_pax_s', 'other_inc_pax_s', 'side_inc_pax_s']]
print(top_neg.to_string(index=False))

# Estimate impact of delta fix for INS
print("\n=== Impact of Delta Fix (Estimated) ===")
ins_rows = df[df['action'].str.contains('INS', na=False)]
if len(ins_rows) > 0:
    print(f"\nFor INS actions before fix:")
    print(f"  Current other_inc mean: {ins_rows['other_inc_pax_s'].mean():,.1f}")
    print(f"  Current other_inc max: {ins_rows['other_inc_pax_s'].max():,.1f}")
    print(f"  Current reward mean: {ins_rows['reward'].mean():,.1f}")
    
    # Estimate: if we reduce other_inc by 75% (typical ratio of delta vs absolute)
    estimated_other_inc_delta = ins_rows['other_inc_pax_s'] * 0.25  # rough estimate
    estimated_reward_with_delta = (ins_rows['bus_saved_pax_s'] 
                                   - estimated_other_inc_delta 
                                   - ins_rows['side_inc_pax_s'] 
                                   - 2.0 * ins_rows['density_inc_pax_s'])
    
    print(f"\nEstimated after fix (if other_inc → 25% of current):")
    print(f"  Estimated other_inc: {estimated_other_inc_delta.mean():,.1f}")
    print(f"  Estimated reward mean: {estimated_reward_with_delta.mean():,.1f}")
    print(f"  Estimated positive%: {100*len(estimated_reward_with_delta[estimated_reward_with_delta > 0])/len(estimated_reward_with_delta):.1f}%")

print("\n✓ The fix changes _reward_evaluate_insertion() to compute:")
print("  other_increase = max(0.0, cost_WITH_insertion - cost_WITHOUT_insertion)")
print("  Instead of the buggy absolute-value calculation that inflates penalties.")
print("\n→ Expected impact: INS rewards should shift from -17.5M to reasonable ±1000s range")
