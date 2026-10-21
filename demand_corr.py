import csv, os, glob, math

base = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\results"
# demand vs delay across champion rows: need PaxEquivPassages per run -> from simulation_results.csv
champ = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\champion_beatnotsp_logan_road_new.csv"
with open(champ, newline='', errors='replace') as f:
    rows = list(csv.DictReader(f))
print(f"{'exp':18s} {'seed':6s} {'delay':>9s} {'pax':>9s} {'busTT':>7s} {'carD':>7s} {'busD':>7s} {'ins':>4s}")
pts = []
for r in rows:
    d = r.get('stats_TotalPassDelay_hrs','').strip()
    if not d: continue
    exp, seed = r['run_experiment'], r['run_seed']
    try:
        pax = float(r.get('stats_PaxEquivPassages',0) or 0)
    except: pax = 0
    print(f"{exp:18s} {seed:6s} {float(d):9.1f} {pax:9.0f} {r.get('stats_AvgBusTT_s','-'):>7s} {r.get('stats_AvgCarPassDelay_s','-'):>7s} {r.get('stats_AvgBusPassDelay_s','-'):>7s} {r.get('stats_TSP_Insertions','-'):>4s}")
    pts.append((exp, float(d), pax))
# correlation passages vs delay
xs = [p for _,_,p in pts if p>0]; ys=[d for _,d,p in pts if p>0]
mx=sum(xs)/len(xs); my=sum(ys)/len(ys)
cov=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/len(xs)
sx=math.sqrt(sum((x-mx)**2 for x in xs)/len(xs)); sy=math.sqrt(sum((y-my)**2 for y in ys)/len(ys))
print(f"\ncorr(PaxEquiv, TotalDelay) = {cov/(sx*sy):.2f}  (n={len(xs)})")

# trip-level: mean vs median vs max per run
print("\n--- bus trip TravelTime distribution ---")
for tag, folder in [
    ('BEST-delay','DCTSP_MP_ECTM_seed600_75206_75207_75210_20261008_114127'),
    ('WORST','DCTSP_MP_ECTM_seed400_75206_75207_75210_20261008_110633'),
    ('BALANCED','DCTSP_MP_ECTM_seed500_75206_75207_75210_20261008_112857')]:
    with open(os.path.join(base,folder,'bus_trips.csv'), errors='replace') as f:
        bt=list(csv.DictReader(f))
    # per-trip: group by? rows are per (trip x intersection)? check: N_BusTrips=1682 rows=1682 -> one row per trip
    tt=sorted(float(x['TravelTime_s']) for x in bt)
    n=len(tt); mean=sum(tt)/n
    med=tt[n//2]; p90=tt[int(0.9*n)]; mx=tt[-1]
    print(f"{tag:10s} n={n} mean={mean:.1f}s median={med:.1f}s p90={p90:.1f}s max={mx:.1f}s  frac>300s={sum(1 for v in tt if v>300)/n*100:.1f}%")
