import csv
from collections import defaultdict
p = r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\reward_cycle_ZIGDOG_20261009_104428.csv'
agg = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])  # n, sum_r, sum_bus, sum_other, sum_side
n = 0
with open(p, errors='replace') as f:
    for r in csv.DictReader(f):
        n += 1
        try:
            key = (r['action'], r['is_chosen'], r['stage'])
            a = agg[key]
            a[0] += 1
            a[1] += float(r['reward'] or 0)
            a[2] += float(r['bus_saved_pax_s'] or 0)
            a[3] += float(r['other_inc_pax_s'] or 0)
            a[4] += float(r['side_inc_pax_s'] or 0)
        except Exception:
            pass
        if n > 4000000:
            break
print('rows:', n)
for key in sorted(agg, key=lambda k: -agg[k][0])[:20]:
    c, sr, sb, so, ss = agg[key]
    print(f'{str(key):45s} n={c:7d} mean_r={sr/c:9.1f} bus={sb/c:9.1f} other={so/c:8.1f} side={ss/c:8.1f}')
