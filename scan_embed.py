import re
base = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\\"
for tag, fn in [('BAD-600', 'Aimsun_TSP_Log_20261008_153715.txt'),
                ('GOOD-500', 'Aimsun_TSP_Log_20261008_151648.txt')]:
    p = base + fn
    print("=" * 78); print(tag, fn)
    n_embed = n_audit = 0
    with open(p, errors='replace') as f:
        for line in f:
            if 'DET_EMBED' in line:
                print("EMBED:", line.strip()[10:280]); n_embed += 1
            elif 'DET_AUDIT' in line and ('19363' in line or 'DEAD' in line or 'SWAPPED' in line):
                print("AUDIT:", line.strip()[10:220]); n_audit += 1
    print(f"embed_lines={n_embed} audit_flagged={n_audit}")
