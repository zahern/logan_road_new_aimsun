import csv, collections, statistics

fn = 'logs/reward_cycle_DCTSP_BARGAIN_SPM_20260529_111841.csv'
rows = list(csv.DictReader(open(fn)))

# Check network_factor values and other_delay_model columns
nf_vals = [float(r['network_factor']) for r in rows if r.get('network_factor','')]
print(f'network_factor: min={min(nf_vals):.3f} max={max(nf_vals):.3f} mean={statistics.mean(nf_vals):.3f}')

# Look at GE_5 chosen with bus_saved=-200
bad_ge = [r for r in rows if r.get('is_chosen','')=='1' and r.get('action','')=='GE_5' and float(r.get('bus_saved_pax_s',0)) < 0]
print(f'\nGE_5 chosen with bus_saved<0: {len(bad_ge)}')
for r in bad_ge[:5]:
    print(f'  jct={r["junction_id"]} reward={r["reward"]} no_act_rew={r["no_action_reward"]} sigma_in={r["sigma_in_s"]} sigma_out={r["sigma_out_s"]} bus_saved={r["bus_saved_pax_s"]} t={r["sim_time_s"]} phase={r["current_phase"]} nf={r["network_factor"]}')

# Compare other_delay_model_pax_s vs other_inc_pax_s for chosen non-NO_ACTION rows
print('\nother_delay_model vs other_inc for chosen non-NO_ACTION:')
for r in rows:
    if r.get('is_chosen','')=='1' and r.get('action','')!='NO_ACTION':
        try:
            odm = float(r.get('other_delay_model_pax_s','0'))
            oi = float(r.get('other_inc_pax_s','0'))
            odm_nf = float(r.get('other_delay_model_pax_s_nf1','0'))
            bus = float(r.get('bus_saved_pax_s','0'))
            print(f'  jct={r["junction_id"]} action={r["action"]} other_delay_model={odm:.0f} other_delay_nf1={odm_nf:.0f} other_inc={oi:.0f} bus_saved={bus:.0f}')
        except: pass

# Summary: what happens if we block bus_saved < 0 actions?
no_action_count = sum(1 for r in rows if r.get('is_chosen','')=='1' and r.get('action','')=='NO_ACTION')
non_no_action = [r for r in rows if r.get('is_chosen','')=='1' and r.get('action','')!='NO_ACTION']
block_count = sum(1 for r in non_no_action if float(r.get('bus_saved_pax_s',0)) < 0)
print(f'\nIf we block bus_saved<0: would block {block_count}/{len(non_no_action)} non-NO_ACTION chosen rows')
