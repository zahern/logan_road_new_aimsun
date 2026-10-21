import csv, os
from collections import defaultdict
base = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\results"
for tag, folder in [
    ('BAD-600', 'CELLQLEARN_GATED_seed600_75206_75207_75210_20261008_153949'),
    ('GOOD-500', 'CELLQLEARN_GATED_seed500_75206_75207_75210_20261008_151917')]:
    with open(os.path.join(base, folder, 'section_timeseries.csv'), errors='replace') as f:
        rows = list(csv.DictReader(f))
    # network totals per time bin: sum n_veh, queue; mean speed; entries ~ sum q_veh_h
    bins = defaultdict(lambda: [0.0, 0.0, 0.0, 0])
    for r in rows:
        try:
            t = int(float(r['t_start_s']) // 600)  # 10-min bins
            bins[t][0] += float(r['n_veh'] or 0)
            bins[t][1] += float(r['queue_veh'] or 0)
            bins[t][2] += float(r['q_veh_h'] or 0)
            bins[t][3] += 1
        except Exception:
            pass
    print("=" * 70); print(tag, "bin | n_veh | queue | flow_sum")
    for t in sorted(bins):
        n, q, fl, c = bins[t]
        print(f"  {t*10:4d}-{(t+1)*10:4d}min | {n:7.0f} | {q:6.0f} | {fl:9.0f}")
