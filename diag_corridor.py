import glob, os, re
from collections import Counter
logs = sorted(glob.glob(r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\Aimsun_TSP_Log_20261008_171540.txt'))
p = logs[0]
txt = open(p, errors='replace').read()
nocc = Counter(); nodown = Counter()
for m in re.finditer(r'\[CASCADE_ZERO\] inter=(\d+).*?reason=(\S+)', txt):
    jct, reason = m.group(1), m.group(2)
    if reason == 'no_corridor_coord': nocc[jct] += 1
    elif reason == 'no_downstream_congestion': nodown[jct] += 1
print('no_corridor_coord by junction:', dict(nocc.most_common(20)))
print('no_downstream_congestion by junction:', dict(nodown.most_common(10)))
# eta_next distribution
etas = Counter()
for m in re.finditer(r'eta_next=(-?\d+)s', txt):
    netas = int(m.group(1))
    netas.append(netas)
buckets = Counter()
for e in netas:
netas = []
buckets = Counter()
for e in netas:
print('sample eta_next lines:')
for line in txt.splitlines():
    if 'eta_next=300' in line:
        print('  ', line.strip()[:160]); break
