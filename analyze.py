import csv
import math

with open(r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\champion_beatnotsp_logan_road_new.csv', 'r') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# NO_TSP seeds 300-700
notsp_rows = [r for r in rows if 'NO_TSP' in r['run_experiment'] and int(r['run_seed']) <= 700 and int(r['run_seed']) >= 300]

# DCTSP_MP_ECTM seeds 300-700 - use only rows with valid TotalPassDelay_hrs
dctsp_rows = [r for r in rows if 'DCTSP_MP_ECTM' in r['run_experiment'] 
              and int(r['run_seed']) <= 700 and int(r['run_seed']) >= 300
              and r['stats_TotalPassDelay_hrs'] and r['stats_AvgBusTT_s']]

print(f'NO_TSP rows (seeds 300-700): {len(notsp_rows)}')
print(f'DCTSP_MP_ECTM valid rows (seeds 300-700): {len(dctsp_rows)}')

# Compute means and stds
notsp_delays = [float(r['stats_TotalPassDelay_hrs']) for r in notsp_rows]
dctsp_delays = [float(r['stats_TotalPassDelay_hrs']) for r in dctsp_rows]

notsp_bustt = [float(r['stats_AvgBusTT_s']) for r in notsp_rows]
dctsp_bustt = [float(r['stats_AvgBusTT_s']) for r in dctsp_rows]

notsp_maindelay = [float(r['stats_MainPassDelay_hrs']) for r in notsp_rows]
dctsp_maindelay = [float(r['stats_MainPassDelay_hrs']) for r in dctsp_rows]

print()
print('=== TotalPassDelay_hrs ===')
notsp_mean = sum(notsp_delays)/len(notsp_delays)
notsp_std = math.sqrt(sum((x-notsp_mean)**2 for x in notsp_delays)/len(notsp_delays))
print(f'NO_TSP mean: {notsp_mean:.2f}, std: {notsp_std:.2f}')
print(f'  Details: {notsp_delays}')

dctsp_mean = sum(dctsp_delays)/len(dctsp_delays)
dctsp_std = math.sqrt(sum((x-dctsp_mean)**2 for x in dctsp_delays)/len(dctsp_delays))
print(f'DCTSP_MP_ECTM mean: {dctsp_mean:.2f}, std: {dctsp_std:.2f}')
print(f'  Details: {dctsp_delays}')

diff = dctsp_mean - notsp_mean
pct = diff / notsp_mean * 100
print(f'Difference (TSP - No TSP): {diff:.2f} hrs ({pct:.1f}%)')
if diff > 0:
    print(f'TSP is {abs(pct):.1f}% WORSE than No TSP')
else:
    print(f'TSP is {abs(pct):.1f}% BETTER than No TSP')

print()
print('=== AvgBusTT_s ===')
notsp_b_mean = sum(notsp_bustt)/len(notsp_bustt)
notsp_b_std = math.sqrt(sum((x-notsp_b_mean)**2 for x in notsp_bustt)/len(notsp_bustt))
print(f'NO_TSP mean: {notsp_b_mean:.2f}, std: {notsp_b_std:.2f}')
print(f'  Details: {notsp_bustt}')

dctsp_b_mean = sum(dctsp_bustt)/len(dctsp_bustt)
dctsp_b_std = math.sqrt(sum((x-dctsp_b_mean)**2 for x in dctsp_bustt)/len(dctsp_bustt))
print(f'DCTSP_MP_ECTM mean: {dctsp_b_mean:.2f}, std: {dctsp_b_std:.2f}')
print(f'  Details: {dctsp_bustt}')

bustt_diff = dctsp_b_mean - notsp_b_mean
bustt_pct = bustt_diff / notsp_b_mean * 100
if bustt_diff > 0:
    print(f'Difference (TSP - No TSP): {bustt_diff:.2f} s ({bustt_pct:.1f}% slower)')
else:
    print(f'Difference (TSP - No TSP): {abs(bustt_diff):.2f} s ({abs(bustt_pct):.1f}% faster)')

print()
print('=== MainPassDelay_hrs ===')
notsp_main_mean = sum(notsp_maindelay)/len(notsp_maindelay)
notsp_main_std = math.sqrt(sum((x-notsp_main_mean)**2 for x in notsp_maindelay)/len(notsp_maindelay))
print(f'NO_TSP mean: {notsp_main_mean:.2f}, std: {notsp_main_std:.2f}')

dctsp_main_mean = sum(dctsp_maindelay)/len(dctsp_maindelay)
dctsp_main_std = math.sqrt(sum((x-dctsp_main_mean)**2 for x in dctsp_maindelay)/len(dctsp_maindelay))
print(f'DCTSP_MP_ECTM mean: {dctsp_main_mean:.2f}, std: {dctsp_main_std:.2f}')

main_diff = dctsp_main_mean - notsp_main_mean
if main_diff > 0:
    print(f'Difference (TSP - No TSP): {main_diff:.2f} hrs (TSP has more main delay)')
else:
    print(f'Difference (TSP - No TSP): {main_diff:.2f} hrs (TSP has less main delay)')