import csv
with open("C:/Users/ahernz/github_for_aimsun/kg/batch_results.csv") as f:
    rows = list(csv.DictReader(f))
no_tsp = [r for r in rows if r.get("run_experiment","").upper() == "NO_TSP"]
if no_tsp:
    r = no_tsp[0]
    for k in ["stats_TotalPassDelay_hrs","stats_AvgBusPassDelay_s","stats_Net_TotalFlowVeh","stats_AvgPassDelay_s","run_strategy"]:
        print(k + ": " + str(r.get(k, "MISSING")))
    print("\nAll stat columns with values:")
    for k, v in r.items():
        if v and v != "0" and k.startswith("stats_"):
            print(f"  {k}: {v}")
else:
    exps = set(r.get("run_experiment") for r in rows)
    print("No NO_TSP row, experiments: " + str(exps))
