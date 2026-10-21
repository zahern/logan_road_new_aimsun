import csv
from collections import defaultdict
for path in [r'Z:\tsp\sumo_hpc\champion_logan_road_new.csv',
             r'Z:\tsp\sumo_hpc\champion_kg.csv']:
    print('=' * 70); print(path)
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    g = defaultdict(list)
    for r in rows:
        if r.get('phase') == 'eval' and str(r.get('ok','')).lower() in ('true','1'):
            try: g[r['arm']].append((int(r['seed']), float(r['obj_pax_per_delay_hr'])))
            except Exception: pass
    for arm, v in sorted(g.items()):
        v.sort()
        mean = sum(x[1] for x in v) / len(v)
        print(f'  {arm:28s} n={len(v)} seeds={[s for s,_ in v]} mean_obj={mean:.1f}')
