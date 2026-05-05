"""Quick diagnostic: green rates, side delay, network stats from latest batch."""
import csv, os

LOG_DIR = r"c:\Users\ahernz\github_for_aimsun\logan_road_new\logs"
det_csv = os.path.join(LOG_DIR, "detection_points_HARMONY_COORD_20260419_094803.csv")

print("=== GREEN RATES ===")
with open(det_csv, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

stats = {}
for r in rows:
    jid = r.get("junction_id", "")
    sp = int(float(r.get("signal_phase", "-1") or "-1"))
    bp = int(float(r.get("bus_phase", "-1") or "-1"))
    if jid not in stats:
        stats[jid] = {"g": 0, "r": 0}
    if sp >= 0 and bp >= 0 and sp == bp:
        stats[jid]["g"] += 1
    else:
        stats[jid]["r"] += 1

for jid in sorted(stats, key=lambda x: int(x)):
    s = stats[jid]
    total = s["g"] + s["r"]
    pct = round(100 * s["g"] / total, 1) if total else 0
    print(f"  jct={jid}: green={s['g']} red={s['r']} total={total} pct={pct}%")

# Check per-intersection data for side delay zeros
print("\n=== PER-INTERSECTION SIDE DELAY ===")
results_dir = r"c:\Users\ahernz\github_for_aimsun\logan_road_new\results"
for folder in sorted(os.listdir(results_dir)):
    inter_csv = os.path.join(results_dir, folder, "simulation_results_per_intersection.csv")
    if not os.path.isfile(inter_csv):
        continue
    with open(inter_csv, newline="", encoding="utf-8") as f:
        inter_rows = list(csv.DictReader(f))
    print(f"\n  {folder}:")
    for r in inter_rows:
        iid = r.get("IntersectionID", "?")
        side = r.get("SidePassDelay_hrs", "?")
        main = r.get("MainPassDelay_hrs", "?")
        n_side = r.get("N_SideSections", "?")
        side_ids = r.get("SideSectionIDs", "")
        resolved = r.get("SideSectionsResolved", "?")
        print(f"    jct={iid}: side_delay={side}h main_delay={main}h n_side={n_side} resolved={resolved} side_ids={side_ids[:60]}")

# Check batch_results for network stats
print("\n=== BATCH RESULTS NETWORK STATS ===")
batch_csv = r"c:\Users\ahernz\github_for_aimsun\logan_road_new\batch_results.csv"
with open(batch_csv, newline="", encoding="utf-8") as f:
    batch_rows = list(csv.DictReader(f))
for r in batch_rows:
    exp = r.get("run_experiment", "?")
    flow = r.get("stats_Net_TotalFlowVeh", "?")
    dens = r.get("stats_Net_AvgDensity_vkm", "?")
    spd = r.get("stats_Net_AvgSpeed_kmh", "?")
    aimsun_flow = r.get("aimsun_total_flow_veh", "")
    aimsun_dens = r.get("aimsun_avg_density_vkm", "")
    aimsun_spd = r.get("aimsun_avg_speed_kmh", "")
    print(f"  {exp}: stats_flow={flow} stats_dens={dens} stats_spd={spd} aimsun_flow={aimsun_flow} aimsun_dens={aimsun_dens} aimsun_spd={aimsun_spd}")
