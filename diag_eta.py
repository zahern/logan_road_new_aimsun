import glob, os, re
from collections import Counter
p = r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\Aimsun_TSP_Log_20261008_171540.txt'
txt = open(p, errors='replace').read()
netas = [int(m.group(1)) for m in re.finditer(r'eta_next=(-?\d+)s', txt)]
buckets = Counter()
for e in netas:
    if e < 0: buckets['<0 (no target)'] += 1
    elif e >= 290: buckets['~300 (capped)'] += 1
    elif e >= 60: buckets['60-300s'] += 1
    else: buckets['0-60s'] += 1
print('eta_next total:', len(netas), dict(buckets))
neg = sum(1 for e in netas if e < 0)
print('negative (no target):', neg)
print('sample eta_next=300 line:')
for line in txt.splitlines():
    if 'eta_next=300' in line:
        print('  ', line.strip()[:160]); break
# also check BUS_ROUTE next_jct=-1 frequency
nj = len(re.findall(r'next_jct=-1 ', txt))
print('next_jct=-1 count:', nj)
