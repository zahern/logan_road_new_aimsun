import csv, os

simf = "C:/Users/ahernz/github_for_aimsun/kg/results/NO_TSP_seed300_11129236_11129237_11129240/simulation_results.csv"
with open(simf) as f:
    rows = list(csv.DictReader(f))
if rows:
    r = rows[0]
    print("All columns in simulation_results.csv:")
    for k, v in r.items():
        if v:
            print(f"  {k}: {repr(v)}")
    print("\nColumn list:", list(r.keys()))
