# Temporary seed diagnostics — safe to overwrite
import pandas as pd, glob

files = sorted(glob.glob('logs/reward_cycle_DCTSP_BARGAIN_SPM_*.csv'))
seeds = [300, 301, 302, 303, 304]

for seed, f in zip(seeds, files):
    df = pd.read_csv(f)
    chosen = df[df['is_chosen']==1]
    ins   = chosen[chosen['action'].str.startswith('INS')]
    ge    = chosen[chosen['action'].str.startswith('GE')]
    noact = chosen[chosen['action']=='NO_ACTION']
    act_counts = chosen['action'].value_counts().to_dict()

    def safe_mean(s, col):
        return round(s[col].mean(), 1) if len(s) else 'N/A'

    # Flag high-cost actions that slipped through
    hi_ins = ins[ins['other_inc_pax_s'] > 300] if len(ins) else ins
    hi_ge  = ge[ge['other_inc_pax_s'] > 300]   if len(ge)  else ge

    print(f'=== Seed {seed} ({f[-27:]}) ===')
    print(f'  Actions chosen: {act_counts}')
    print(f'  INS n={len(ins):3d}  avg_car_cost={safe_mean(ins,"other_inc_pax_s")}  avg_bus_saved={safe_mean(ins,"bus_saved_pax_s")}  avg_reward={safe_mean(ins,"reward")}')
    print(f'  GE  n={len(ge):3d}  avg_car_cost={safe_mean(ge,"other_inc_pax_s")}   avg_bus_saved={safe_mean(ge,"bus_saved_pax_s")}  avg_reward={safe_mean(ge,"reward")}')
    print(f'  sigma_in: INS mean={safe_mean(ins,"sigma_in_s")}  GE mean={safe_mean(ge,"sigma_in_s")}')
    print(f'  INS car_cost>300: n={len(hi_ins)}')
    print(f'  GE  car_cost>300: n={len(hi_ge)}')
    # Show worst INS actions by car cost
    if len(ins):
        worst = ins.nlargest(5, 'other_inc_pax_s')[['sim_time_s','junction_id','action','other_inc_pax_s','bus_saved_pax_s','reward','sigma_in_s','no_act_delay_s']]
        print(f'  Top-5 INS by car cost:')
        print(worst.to_string(index=False))
    print()
