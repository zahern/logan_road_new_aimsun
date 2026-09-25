"""
gen_paper_figures.py — Generate figures for the paper:
  1. Bus delay distribution per strategy (histogram)
  2. Corridor coordinates for Figure 1 (from detection GeoJSON)
  3. Updated dashboard with all KPIs k

No pandas. Uses matplotlib if available, else writes CSV summaries.
"""
import csv, os, glob, json, math

RESULTS_DIR = 'results'
LOGS_DIR    = 'logs'
PLOTS_DIR   = 'plots'
os.makedirs(PLOTS_DIR, exist_ok=True)

HAS_MPL = False
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    pass

# ── 1. Bus delay distribution per strategy ────────────────────────────────────

print("=== Bus delay distribution per strategy ===")
result_dirs = sorted(glob.glob(os.path.join(RESULTS_DIR, '*seed*')))
strategy_delays = {}

for rd in result_dirs:
    bt_csv = os.path.join(rd, 'bus_trips.csv')
    if not os.path.isfile(bt_csv): continue
    
    # Extract strategy name
    exp_name = os.path.basename(rd).split('_seed')[0]
    delays = []
    with open(bt_csv, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                d = float(row.get('TravelTime_s', 0) or 0)
                if 10 < d < 600:  # filter outliers
                    delays.append(d)
            except: pass
    
    if delays:
        strategy_delays[exp_name] = delays
        print(f"  {exp_name}: {len(delays)} trips, mean={sum(delays)/len(delays):.1f}s, median={sorted(delays)[len(delays)//2]:.1f}s")

if HAS_MPL and len(strategy_delays) >= 2:
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ['#D62728', '#2F5496', '#FF7F0E', '#2CA02C', '#9467BD', '#17BECF']
    for i, (name, delays) in enumerate(sorted(strategy_delays.items())):
        ax.hist(delays, bins=30, alpha=0.5, label=f'{name} (n={len(delays)}, mu={sum(delays)/len(delays):.0f}s)',
                color=colors[i % len(colors)], edgecolor='white', linewidth=0.3)
    ax.set_xlabel('Bus Travel Time (s)')
    ax.set_ylabel('Frequency')
    ax.set_title('Bus Travel Time Distribution by Strategy')
    ax.legend(fontsize=8, frameon=False)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, 'fig_bus_delay_distribution.png'), dpi=200)
    plt.close()
    print(f"  Saved: plots/fig_bus_delay_distribution.png")
else:
    # Write CSV summary
    with open(os.path.join(PLOTS_DIR, 'bus_delay_summary.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['strategy', 'n_trips', 'mean_s', 'median_s', 'min_s', 'max_s'])
        for name, delays in sorted(strategy_delays.items()):
            w.writerow([name, len(delays), f'{sum(delays)/len(delays):.1f}', 
                       f'{sorted(delays)[len(delays)//2]:.1f}', f'{min(delays):.1f}', f'{max(delays):.1f}'])
    print(f"  Saved: plots/bus_delay_summary.csv")

# ── 2. Corridor coordinates for Figure 1 ──────────────────────────────────────

print("\n=== Corridor coordinates (most recent detection GeoJSON) ===")
geojson_files = sorted(glob.glob(os.path.join(LOGS_DIR, 'detection_points*.geojson')),
                       key=os.path.getmtime, reverse=True)

if geojson_files:
    latest = geojson_files[0]
    with open(latest, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    features = data.get('features', [])
    # Extract unique junction coordinates
    junctions = {}
    for feat in features:
        props = feat.get('properties', {})
        jct_id = props.get('junction_id', props.get('inter_id', 'unknown'))
        coords = feat.get('geometry', {}).get('coordinates', [0, 0])
        if jct_id not in junctions:
            junctions[jct_id] = coords
    
    print(f"  {len(features)} detection points, {len(junctions)} unique junctions")
    for jid, coords in sorted(junctions.items()):
        print(f"    Junction {jid}: ({coords[0]:.1f}, {coords[1]:.1f})")
    
    # Write to CSV for LaTeX
    with open(os.path.join(PLOTS_DIR, 'corridor_coordinates.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['junction_id', 'x', 'y'])
        for jid, coords in sorted(junctions.items()):
            w.writerow([jid, f'{coords[0]:.1f}', f'{coords[1]:.1f}'])
    print(f"  Saved: plots/corridor_coordinates.csv")

# ── 3. KPI summary for paper ──────────────────────────────────────────────────

print("\n=== KPI Summary for Paper ===")
batch_csv = 'batch_results.csv'
if os.path.isfile(batch_csv):
    with open(batch_csv, 'r', encoding='utf-8') as f:
        b_rows = list(csv.DictReader(f))
    
    kpi_rows = []
    for r in b_rows:
        exp = r.get('run_experiment', '?')
        td = float(r.get('stats_TotalPassDelay_hrs', 0) or 0)
        ad = float(r.get('stats_AvgPassDelay_s', 0) or 0)
        bt = float(r.get('stats_Net_TotalTT_h_Bus', 0) or 0)
        ct = float(r.get('stats_Net_TotalTT_h_Car', 0) or 0)
        sd = float(r.get('stats_SidePassDelay_hrs', 0) or 0)
        z1 = float(r.get('wobj_Z1_total', 0) or 0)
        z2 = float(r.get('wobj_Z2_total', 0) or 0)
        z3 = float(r.get('wobj_Z3_total', 0) or 0)
        z4 = float(r.get('wobj_Z4_total', 0) or 0)
        obj = float(r.get('wobj_objective_total', 0) or 0)
        nb = float(r.get('stats_N_DistinctBuses', 0) or 0)
        nc = float(r.get('stats_N_DistinctCars', 0) or 0)
        
        vs_no_tsp = ''
        if 'NO_TSP' in b_rows[0].get('run_experiment', ''):
            nt = b_rows[0]
            nt_td = float(nt.get('stats_TotalPassDelay_hrs', 0) or 0)
            if nt_td > 0:
                vs_no_tsp = f'{(td - nt_td)/nt_td*100:+.1f}%'
        
        kpi_rows.append({
            'Strategy': exp,
            'TotalPassDelay_h': f'{td:.1f}',
            'AvgDelay_s': f'{ad:.1f}',
            'BusTT_h': f'{bt:.1f}',
            'CarTT_h': f'{ct:.1f}',
            'SideDelay_h': f'{sd:.1f}',
            'Z1_pax_s': f'{z1:.0f}',
            'Z2_bw_s': f'{z2:.0f}',
            'Z3_late_s': f'{z3:.0f}',
            'Z4_veh_h': f'{z4:.1f}',
            'Objective': f'{obj:.0f}',
            'N_Buses': f'{nb:.0f}',
            'N_Cars': f'{nc:.0f}',
            'vs_NO_TSP': vs_no_tsp,
        })
        print(f"  {exp:30s} delay={td:7.1f}h  Z1={z1/1e6:5.2f}M  Z2={z2:6.0f}  Z3={z3:5.0f}  Z4={z4:6.1f}")
    
    # Write KPI table for paper
    if kpi_rows:
        with open(os.path.join(PLOTS_DIR, 'paper_kpi_table.csv'), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=kpi_rows[0].keys())
            w.writeheader()
            w.writerows(kpi_rows)
        print(f"\n  Saved: plots/paper_kpi_table.csv ({len(kpi_rows)} experiments)")

print("\nDone. Files in plots/:")
for f in sorted(os.listdir(PLOTS_DIR)):
    print(f"  {f}")
