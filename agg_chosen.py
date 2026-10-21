import csv
from collections import Counter, defaultdict
p = r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\reward_cycle_ZIGDOG_20261009_104428.csv'
stages = Counter()
chosen = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])
chosen_q = []
n = 0
with open(p, errors='replace') as f:
    for r in csv.DictReader(f):
        n += 1
        stages[(r['stage'], r['is_chosen'])] += 1
        if r['is_chosen'] == '1':
            try:
                a = chosen[(r['action'], r['stage'])]
                a[0] += 1
                a[1] += float(r['reward'] or 0)
                a[2] += float(r['bus_saved_pax_s'] or 0)
                a[3] += float(r['other_inc_pax_s'] or 0)
                a[4] += float(r['side_inc_pax_s'] or 0)
                if r['action'] != 'NO_ACTION' and len(chosen_q) < 5:
                    chosen_q.append({k: r[k] for k in
                        ['sim_time_s','junction_id','veh_id','bus_eta_s','action','reward','bus_saved_pax_s','other_inc_pax_s','side_inc_pax_s','queue_veh','max_queue_bus_veh','red_dur_bus_s','param_s','upflow_bus_vph']})
            except Exception:
                pass
print('rows:', n)
print('stage x chosen:', dict(stages))
for key in sorted(chosen, key=lambda k: -chosen[k][0])[:12]:
    c, sr, sb, so, ss = chosen[key]
    print(f'{str(key):28s} n={c:7d} mean_r={sr/c:10.1f} bus={sb/c:9.1f} other={so/c:9.1f} side={ss/c:9.1f}')
print('sample chosen non-NO_ACTION rows:')
for q in chosen_q:
    print(q)
