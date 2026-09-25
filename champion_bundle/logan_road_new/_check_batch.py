import csv

with open("C:/Users/ahernz/github_for_aimsun/kg/batch_results.csv") as f:
    rows = list(csv.DictReader(f))

no_tsp = [r for r in rows if r.get("run_experiment","").upper() == "NO_TSP"]
print(f"Found {len(no_tsp)} NO_TSP rows")
if no_tsp:
    r = no_tsp[0]
    # Show all stats_ columns with their values
    print("\nAll stats_ columns:")
    for k, v in r.items():
        if k.startswith("stats_"):
            print(f"  {k}: {repr(v)}")
