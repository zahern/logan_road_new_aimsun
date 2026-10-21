import csv, os, math, datetime
from collections import defaultdict

path = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\champion_beatnotsp_logan_road_new.csv"
print("mtime:", datetime.datetime.fromtimestamp(os.path.getmtime(path)))
with open(path, newline='', errors='replace') as f:
    rows = list(csv.DictReader(f))
print("n_rows:", len(rows))
by_exp = defaultdict(list)
for r in rows:
    by_exp[r.get('run_experiment','?')].append(r)
for exp, rs in by_exp.items():
    print(f"--- {exp} n={len(rs)} ---")
    ok = [x for x in rs if x.get('stats_TotalPassDelay_hrs','').strip()!='']
    for x in rs:
        okflag = 'OK ' if x in ok else 'FAIL'
        print(f"  {okflag} seed={x.get('run_seed')} succ={x.get('run_success')} delay={x.get('stats_TotalPassDelay_hrs','-')} busTT={x.get('stats_AvgBusTT_s','-')} det={x.get('stats_TSP_Detections','-')} ext={x.get('stats_TSP_Extensions','-')} ins={x.get('stats_TSP_Insertions','-')} noact={x.get('stats_TSP_Detected_NoAction','-')} folder={os.path.basename(x.get('stats_results_folder',''))[:60]}")
    if ok:
        d=[float(x['stats_TotalPassDelay_hrs']) for x in ok]
        m=sum(d)/len(d); sd=math.sqrt(sum((v-m)**2 for v in d)/len(d))
        print(f"  => mean={m:.1f} sd={sd:.1f} min={min(d):.1f} max={max(d):.1f} range={max(d)-min(d):.1f} cv={100*sd/m:.1f}%")
