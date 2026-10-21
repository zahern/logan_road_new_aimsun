import csv
from collections import Counter
p = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\reward_cycle_DCTSP_MP_ECTM_20261008_115259.csv"
with open(p, errors='replace') as f:
    rows = list(csv.DictReader(f))
ch = [r for r in rows if str(r['is_chosen']).strip().lower() in ('1','true','yes')]
print("chosen rows:", len(ch))
cnt = Counter()
for r in ch:
    a = r['action']
    fam = 'GE' if a.startswith('GE') else ('INS' if a.startswith('INS') else a)
    cnt[fam] += 1
print("chosen by family:", dict(cnt))
cnt2 = Counter(r['action'] for r in ch)
print("top chosen actions:", cnt2.most_common(10))
# reward stats by family among chosen
import math
for fam in ['GE','INS_POST','INS_PRETERM','NO_ACTION']:
    rr = [float(r['reward']) for r in ch if r['action'].startswith(fam)]
    if rr:
        print(fam, f"n={len(rr)} mean_reward={sum(rr)/len(rr):.1f}")
# how many eval events (distinct sim_time+junction+veh)?
ev = set((r['sim_time_s'], r['junction_id'], r['veh_id']) for r in rows)
print("eval events:", len(ev))
# chosen NO_ACTION share
noa = sum(1 for r in ch if r['action']=='NO_ACTION')
print(f"chosen NO_ACTION: {noa}/{len(ch)} = {100*noa/len(ch):.1f}%")
