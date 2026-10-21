import csv
champ = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\champion_beatnotsp_logan_road_new.csv"
with open(champ, newline='', errors='replace') as f:
    rows = list(csv.DictReader(f))
print("exp | seed | pax | VQVeh | WaitVQ | EntryDly | Flow | BusTrips | CarPass")
for r in rows:
    if not r.get('stats_TotalPassDelay_hrs','').strip():
        continue
    pax = float(r.get('stats_PaxEquivPassages',0) or 0)
    print(r['run_experiment'], '|', r['run_seed'], '|', round(pax),
          '| VQVeh=' + str(r.get('stats_Net_VQVeh_All','-')),
          '| WaitVQ=' + str(r.get('stats_Net_WaitVQ_All','-')),
          '| EntryDly=' + str(r.get('stats_Net_EntryDelay_All','-')),
          '| Flow=' + str(r.get('stats_Net_TotalFlowVeh','-')),
          '| BusTrips=' + str(r.get('stats_N_BusTrips','-')),
          '| CarPass=' + str(r.get('stats_CarPaxEquivPassages','-')))
