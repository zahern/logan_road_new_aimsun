import csv, os

strategies = [
    'DCTSP_SELFORG', 'DCTSP_V2X', 'DCTSP_CONSERVATIVE',
    'DCTSP_MP_ECTM', 'DCTSP_MARL', 'DCTSP_ZIG', 'DCTSP_INV_DELAY',
]
base = r'c:\Users\ahernz\github_for_aimsun\kg\results'
print(f"{'Strategy':<22} {'AvgExt':>8} {'AvgIns':>8} {'TotExt':>10} {'TotIns':>10} {'Ext#':>6} {'Ins#':>6}")
print('-' * 75)
for s in strategies:
    d = os.path.join(base, s + '_seed300_11129236_11129237_11129240')
    f = os.path.join(d, 'simulation_results.csv')
    if not os.path.exists(f):
        continue
    with open(f) as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        print(
            f"{s:<22} "
            f"{float(r.get('TSP_AvgExtension_s') or 0):>8.2f} "
            f"{float(r.get('TSP_AvgInsertion_s') or 0):>8.2f} "
            f"{float(r.get('TSP_TotalExtension_s') or 0):>10.1f} "
            f"{float(r.get('TSP_TotalInsertion_s') or 0):>10.1f} "
            f"{float(r.get('TSP_Extensions') or 0):>6.0f} "
            f"{float(r.get('TSP_Insertions') or 0):>6.0f}"
        )
