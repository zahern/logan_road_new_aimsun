import csv, collections

fn = 'logs/reward_cycle_DCTSP_BARGAIN_SPM_20260529_111841.csv'
rows = list(csv.DictReader(open(fn)))
print(f'Total rows: {len(rows)}')

# Count actions chosen (is_chosen=True)
action_counts = collections.Counter(r.get('action','') for r in rows)
print('\nAll action counts:', dict(action_counts))

chosen_rows = [r for r in rows if str(r.get('is_chosen','0')).strip().lower() in ('1','true','yes')]
print(f'\nChosen rows (is_chosen=1): {len(chosen_rows)}')
chosen_counts = collections.Counter(r.get('action','') for r in chosen_rows)
print('Chosen action counts:', dict(chosen_counts))

# For non-NO_ACTION chosen rows, compare car_cost vs bus_saved
print('\nNon-NO_ACTION chosen rows (first 10):')
count_bad = 0
count_good = 0
for r in chosen_rows:
    act = r.get('action','')
    if act == 'NO_ACTION':
        continue
    try:
        bus = float(r.get('bus_saved_pax_s', 0))
        car = float(r.get('other_inc_pax_s', 0))
        rew = float(r.get('reward', 0))
        no_rew = float(r.get('no_action_reward', 0))
        sin = float(r.get('sigma_in_s', 0))
        sout = float(r.get('sigma_out_s', 0))
        if car > bus:
            count_bad += 1
            if count_bad <= 8:
                print(f'  WORSE: jct={r["junction_id"]} action={act} bus_saved={bus:.0f} car_cost={car:.0f} net={bus-car:.0f} reward={rew:.3f} no_act_rew={no_rew:.3f} sigma_in={sin:.1f} sigma_out={sout:.1f}')
        else:
            count_good += 1
            if count_good <= 3:
                print(f'  BETTER: jct={r["junction_id"]} action={act} bus_saved={bus:.0f} car_cost={car:.0f} net={bus-car:.0f} reward={rew:.3f} no_act_rew={no_rew:.3f}')
    except Exception as e:
        print(f'  ERR: {e} row={r}')

print(f'\nTotal non-NO_ACTION chosen: net_bad(car>bus)={count_bad}, net_good(bus>=car)={count_good}')

# Summary stats for all chosen non-NO_ACTION
totals_bus = 0; totals_car = 0; n = 0
for r in chosen_rows:
    if r.get('action','') == 'NO_ACTION': continue
    try:
        totals_bus += float(r.get('bus_saved_pax_s', 0))
        totals_car += float(r.get('other_inc_pax_s', 0))
        n += 1
    except: pass
print(f'\nSummary {n} non-NO_ACTION chosen: total_bus_saved={totals_bus:.0f} pax_s, total_car_cost={totals_car:.0f} pax_s, net={totals_bus-totals_car:.0f} pax_s')
