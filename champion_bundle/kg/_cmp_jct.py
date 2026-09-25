import csv, os, glob

# Check what strategies are in BARGAIN_SPM file
d = glob.glob('results/DCTSP_BARGAIN_SPM_seed300_*')[0]
fn = os.path.join(d, 'simulation_results_per_intersection.csv')
rows = list(csv.DictReader(open(fn)))
strategies = set(r['TSP_Strategy'] for r in rows)
print(f'Strategies in BARGAIN_SPM per_intersection file: {strategies}')
print(f'Total rows: {len(rows)}')

for s in sorted(strategies):
    sub = [r for r in rows if r['TSP_Strategy']==s and r['IntersectionID'] in ('36393','36385')]
    if not sub: continue
    print(f'\n  Strategy={s}:')
    for r in sub:
        jct = r['IntersectionID']
        tpd = r['TotalPassDelay_hrs']
        spd = r['SidePassDelay_hrs']
        mpd = r['MainPassDelay_hrs']
        ext = r['TSP_Extensions']
        ins = r['TSP_Insertions']
        apd = r['AvgPassDelay_s']
        print(f'    jct={jct} TotalPassDelay={tpd}h SideDelay={spd}h MainDelay={mpd}h AvgDelay={apd}s ext={ext} ins={ins}')

# Also show NO_TSP for comparison
d2 = glob.glob('results/NO_TSP_seed300_*')[0]
fn2 = os.path.join(d2, 'simulation_results_per_intersection.csv')
rows2 = list(csv.DictReader(open(fn2)))
strats2 = set(r['TSP_Strategy'] for r in rows2)
print(f'\nStrategies in NO_TSP file: {strats2}')
for s in sorted(strats2):
    sub2 = [r for r in rows2 if r['TSP_Strategy']==s and r['IntersectionID'] in ('36393','36385')]
    if not sub2: continue
    print(f'\n  Strategy={s}:')
    for r in sub2:
        jct = r['IntersectionID']
        tpd = r['TotalPassDelay_hrs']
        spd = r['SidePassDelay_hrs']
        mpd = r['MainPassDelay_hrs']
        apd = r['AvgPassDelay_s']
        print(f'    jct={jct} TotalPassDelay={tpd}h SideDelay={spd}h MainDelay={mpd}h AvgDelay={apd}s')
