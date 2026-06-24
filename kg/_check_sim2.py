import csv, glob, os

# Scan anywhere for simulation_results.csv near NO_TSP
base = "C:/Users/ahernz/github_for_aimsun/kg"
for root, dirs, files in os.walk(base):
    if "simulation_results.csv" in files and "NO_TSP" in root:
        simf = os.path.join(root, "simulation_results.csv")
        print("Found:", simf)
        with open(simf) as x:
            rows = list(csv.DictReader(x))
        if rows:
            row = rows[0]
            for k in ["TotalPassDelay_hrs", "AvgBusPassDelay_s", "Net_TotalFlowVeh", "AvgPassDelay_s"]:
                print(f"  {k}: {repr(row.get(k, 'MISSING'))}")
        break
else:
    # show all simulation_results.csv locations
    print("No NO_TSP simulation_results.csv, searching...")
    for root, dirs, files in os.walk(base):
        if "simulation_results.csv" in files:
            print(" Found:", root)
            if len(root) < 120:
                break
