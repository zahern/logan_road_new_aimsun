import csv
p = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\reward_cycle_DCTSP_MP_ECTM_20261008_115259.csv"
with open(p, errors='replace') as f:
    rows = list(csv.DictReader(f))
from collections import defaultdict
import math
fams = defaultdict(list)
for r in rows:
    a = r['action']
    fam = 'GE' if a.startswith('GE') else ('INS' if a.startswith('INS') else 'NOA')
    try:
        fams[fam].append((float(r['reward']), float(r['bus_saved_pax_s']), float(r['side_inc_pax_s']), float(r['bus_eta_s'])))
    except: pass
for fam, v in fams.items():
    rw = sum(x[0] for x in v)/len(v)
    bs = sum(x[1] for x in v)/len(v)
    si = sum(x[2] for x in v)/len(v)
    et = sorted(x[3] for x in v)
    print(f"{fam:5s} n={len(v):5d} mean_rew={rw:9.1f} mean_busSaved={bs:9.1f} mean_sideInc={si:9.1f} eta_med={et[len(et)//2]:5.1f} eta_p90={et[int(0.9*len(et))]:5.1f}")
# GE-only: how often is best GE reward > its event NO_ACTION reward?
ev = defaultdict(list)
for r in rows:
    ev[(r['sim_time_s'], r['junction_id'], r['veh_id'])].append(r)
ge_wins = ge_eval = 0
ins_wins = 0
for k, rs in ev.items():
    nas = [float(x['reward']) for x in rs if x['action']=='NO_ACTION']
    ges = [float(x['reward']) for x in rs if x['action'].startswith('GE')]
    inss = [float(x['reward']) for x in rs if x['action'].startswith('INS')]
    if not nas: continue
    na = nas[0]
    if ges:
        ge_eval += 1
        if max(ges) > na: ge_wins += 1
    if inss and max(inss) > na: ins_wins += 1
print(f"events with GE evaluated: {ge_eval}, GE beats NOA: {ge_wins} ({100*ge_wins/max(ge_eval,1):.1f}%)")
print(f"events where INS beats NOA: {ins_wins}")
