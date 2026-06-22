import csv, os

base = r'c:\Users\ahernz\github_for_aimsun\kg\results'

KEY_COLS = [
    'Net_EntryDelay_All', 'Net_ExitDelay_All', 'Net_Delay_All',
    'Net_EntryDelay_Car', 'Net_EntryDelay_Bus',
    'SimTotalDelay_pax_s', 'AvgBusPassDelay_s',
    'TSP_Extensions', 'TSP_Insertions', 'TSP_Detected_NoAction',
]

rows = []
for d in sorted(os.listdir(base)):
    path = os.path.join(base, d)
    csv_file = os.path.join(path, 'simulation_results.csv')
    if not os.path.exists(csv_file):
        continue
    name = d.split('_seed')[0]
    with open(csv_file) as f:
        data = list(csv.DictReader(f))
    if not data:
        continue
    rec = {'name': name, 'n': len(data)}
    for col in KEY_COLS:
        vals = []
        for row in data:
            try:
                vals.append(float(row.get(col, '') or 0))
            except ValueError:
                pass
        rec[col] = sum(vals)/len(vals) if vals else 0.0
    rows.append(rec)

# Baseline
baseline = next((r for r in rows if r['name'] == 'NO_TSP'), None)
rows.sort(key=lambda r: r['Net_EntryDelay_All'])

hdr = (f"{'Strategy':<28} {'EntryDel':>9} {'Δentry%':>8} {'ExitDel':>9} "
       f"{'Δexit%':>8} {'NetDel':>9} {'EntBus':>9} {'BusAvgDel':>10} "
       f"{'Ext':>6} {'Ins':>6} {'NoAct':>6}")
print(hdr)
print('-' * len(hdr))
for r in rows:
    b_entry = baseline['Net_EntryDelay_All'] if baseline else 1
    b_exit  = baseline['Net_ExitDelay_All']  if baseline else 1
    d_entry = (r['Net_EntryDelay_All'] - b_entry) / b_entry * 100 if b_entry else 0
    d_exit  = (r['Net_ExitDelay_All']  - b_exit)  / b_exit  * 100 if b_exit  else 0
    marker = ' <<<' if r['name'] in ('DCTSP_ZIG', 'DCTSP_INV_DELAY') else ''
    print(f"{r['name']:<28} "
          f"{r['Net_EntryDelay_All']:>9.3f} {d_entry:>+8.1f}% "
          f"{r['Net_ExitDelay_All']:>9.3f} {d_exit:>+8.1f}% "
          f"{r['Net_Delay_All']:>9.3f} "
          f"{r['Net_EntryDelay_Bus']:>9.3f} "
          f"{r['AvgBusPassDelay_s']:>10.2f} "
          f"{r['TSP_Extensions']:>6.0f} {r['TSP_Insertions']:>6.0f} "
          f"{r['TSP_Detected_NoAction']:>6.0f}"
          f"{marker}")
