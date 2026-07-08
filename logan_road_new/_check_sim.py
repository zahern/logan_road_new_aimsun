import csv, glob, os

# Find NO_TSP folder
folders = glob.glob("C:/Users/ahernz/github_for_aimsun/kg/runs/NO_TSP*")
if not folders:
    folders = glob.glob("C:/Users/ahernz/github_for_aimsun/kg/NO_TSP*")

print("Folders:", folders[:3])

for f in sorted(folders)[:1]:
    simf = os.path.join(f, "simulation_results.csv")
    print("Sim file:", simf, "exists:", os.path.isfile(simf))
    if os.path.isfile(simf):
        with open(simf) as x:
            rows = list(csv.DictReader(x))
        if rows:
            row = rows[0]
            for k in ["TotalPassDelay_hrs", "AvgBusPassDelay_s", "Net_TotalFlowVeh", "AvgPassDelay_s", "SimTotalDelay_pax_s"]:
                print(f"  {k}: {repr(row.get(k, 'MISSING'))}")
        print("  All non-empty keys:", [k for k,v in (rows[0] if rows else {}).items() if v])
