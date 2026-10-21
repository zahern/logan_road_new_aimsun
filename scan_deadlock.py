import csv, os
base = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\results"
for tag, folder in [
    ('BAD-600', 'CELLQLEARN_GATED_seed600_75206_75207_75210_20261008_153949'),
    ('GOOD-500', 'CELLQLEARN_GATED_seed500_75206_75207_75210_20261008_151917')]:
    d = os.path.join(base, folder)
    print("=" * 78); print(tag, folder)
    with open(os.path.join(d, 'section_stats.csv'), errors='replace') as f:
        ss = list(csv.DictReader(f))
    rows = []
    for r in ss:
        try:
            rows.append((float(r['AvgQueue_veh']), float(r['AvgDensity_vkm']),
                         float(r['AvgSpeed_kmh']), r['SectionID'], r['IntersectionID'], r['IsMain']))
        except Exception:
            pass
    rows.sort(reverse=True)
    print(" worst sections by AvgQueue_veh:")
    for q, den, spd, sec, jct, main in rows[:10]:
        print(f"  sec={sec} jct={jct} main={main} q={q:.1f} den={den:.0f} spd={spd:.1f}")
    print(" network means: q=%.2f den=%.0f" % (
        sum(r[0] for r in rows) / len(rows), sum(r[1] for r in rows) / len(rows)))
    sw = os.path.join(d, 'signal_wait_summary.json')
    if os.path.exists(sw):
        print(" signal_wait:", open(sw, errors='replace').read()[:300])
