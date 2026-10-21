import csv, os
from collections import defaultdict
base = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\results"
for tag, folder in [
    ('BEST-delay','DCTSP_MP_ECTM_seed600_75206_75207_75210_20261008_114127'),
    ('WORST','DCTSP_MP_ECTM_seed400_75206_75207_75210_20261008_110633')]:
    with open(os.path.join(base,folder,'bus_trips.csv'), errors='replace') as f:
        bt=list(csv.DictReader(f))
    per = defaultdict(list)
    for x in bt:
        per[x['IntersectionID']].append(float(x['TravelTime_s']))
    print("="*70); print(tag, f"n={len(bt)}")
    rows = []
    for jid, v in per.items():
        v=sorted(v); n=len(v); mean=sum(v)/n
        rows.append((mean, jid, n, v[n//2], v[int(0.9*n)], v[-1]))
    rows.sort(reverse=True)
    print(" jid | n | mean | median | p90 | max")
    for mean, jid, n, med, p90, mx in rows[:8]:
        print(f" {jid} | {n} | {mean:.0f} | {med:.0f} | {p90:.0f} | {mx:.0f}")
