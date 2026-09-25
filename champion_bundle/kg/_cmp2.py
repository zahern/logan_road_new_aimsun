import csv, os, glob, json

for name in ['DCTSP_BARGAIN_SPM_seed300', 'NO_TSP_seed300']:
    fd = glob.glob(f'results/{name}_*')[0]
    sj = os.path.join(fd, 'summary.json')
    if os.path.isfile(sj):
        d = json.load(open(sj))
        print(f'=== {name} ===')
        for k, v in d.items():
            print(f'  {k}: {v}')
        print()

# Also look at simulation_results.csv
for name in ['DCTSP_BARGAIN_SPM_seed300', 'NO_TSP_seed300']:
    fd = glob.glob(f'results/{name}_*')[0]
    fn = os.path.join(fd, 'simulation_results.csv')
    if os.path.isfile(fn):
        rows = list(csv.DictReader(open(fn)))
        print(f'=== {name} simulation_results.csv ===')
        for r in rows:
            print(dict(r))
