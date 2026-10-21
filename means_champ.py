import csv
from collections import defaultdict
p = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\champion_beatnotsp_logan_road_new.csv"
rows = list(csv.DictReader(open(p, newline='', errors='replace')))
print('n_rows:', len(rows))
g = defaultdict(list)
for r in rows:
    try:
        d = float(r.get('stats_TotalPassDelay_hrs', '') or 'nan')
    except Exception:
        continue
    import math
    if math.isnan(d):
        continue
    g[(r.get('run_experiment', ''), r.get('run_seed', ''))].append(d)
# mean per experiment over eval seeds 300-700 only
agg = defaultdict(list)
for (exp, seed), ds in g.items():
    if seed.strip() in ('300', '400', '500', '600', '700'):
        agg[exp].append(sum(ds) / len(ds))
base = sum(agg.get('NO_TSP', [float('nan')])) / max(1, len(agg.get('NO_TSP', [])))
for exp in sorted(agg):
    v = agg[exp]
    m = sum(v) / len(v)
    print(f'{exp:24s} n={len(v)} mean={m:8.1f}  d_vs_NOTSP={m-base:+7.1f} ({(m-base)/base*100:+.2f}%)')
