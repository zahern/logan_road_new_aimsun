import csv, os, math, datetime
path = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\champion_beatnotsp_logan_road_new.csv"
print("mtime:", datetime.datetime.fromtimestamp(os.path.getmtime(path)))
with open(path, newline='', errors='replace') as f:
    rows = list(csv.DictReader(f))
print("n_rows:", len(rows))
for r in rows:
    d = r.get('stats_TotalPassDelay_hrs','').strip()
    if not d: continue
    print(r['run_experiment'], '| seed', r['run_seed'], '| delay', round(float(d),1),
          '| busTT', r.get('stats_AvgBusTT_s','-'),
          '| carD', r.get('stats_AvgCarPassDelay_s','-'),
          '| busD', r.get('stats_AvgBusPassDelay_s','-'),
          '| pax', r.get('stats_PaxEquivPassages','-'),
          '| det', r.get('stats_TSP_Detections','-'),
          '| ext', r.get('stats_TSP_Extensions','-'),
          '| ins', r.get('stats_TSP_Insertions','-'),
          '| noact', r.get('stats_TSP_Detected_NoAction','-'),
          '| natg', r.get('stats_TSP_NaturalGreen','-'),
          '| insW', r.get('stats_TSP_AvgInsertionWait_s','-'),
          '| extS', r.get('stats_TSP_TotalExtension_s','-'),
          '| folder', os.path.basename(r.get('stats_results_folder',''))[:55])
