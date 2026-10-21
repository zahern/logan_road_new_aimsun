import re
p = r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\intersection_configs.py'
lines = open(p, errors='replace').read().splitlines(keepends=True)
# locate block starts: "    NNNN: {'IntersectionID'"
starts = {}
for i, ln in enumerate(lines):
    m = re.match(r"    (\d+): \{'IntersectionID'", ln)
    if m:
        starts[m.group(1)] = i
traps = ['17628', '18044', '19196', '20280', '21847']
order = sorted(starts, key=lambda j: starts[j])
changed = []
for t in traps:
    s = starts[t]
    e = starts[order[order.index(t) + 1]]
    hit = False
    for i in range(s, e):
        if "'detection_window_m': 50.0" in lines[i]:
            lines[i] = lines[i].replace(
                "'detection_window_m': 50.0,",
                "'detection_window_m': 80.0,  # 2026-10-08 trap-junction: earlier visibility")
            changed.append((t, i + 1))
            hit = True
    if not hit:
        print("NO WINDOW KEY in", t)
open(p, 'w', errors='replace').write(''.join(lines))
print("changed:", changed)
