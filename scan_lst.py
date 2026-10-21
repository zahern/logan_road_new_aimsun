import re
p = r"C:\Users\ahernz\github_for_aimsun\iMove SCATS File Share\Personalities\South\B0653\LST00653.LST"
lines = open(p, errors='replace').read().splitlines()
print('total lines:', len(lines))
hits = []
for i, ln in enumerate(lines):
    if re.search(r'DETECTOR|LOOP|CALLA|PRESA|\bCALL\b|DEMAND|EXTEND|COUNT|INPUT', ln):
        hits.append((i+1, ln[:160]))
print('hits:', len(hits))
for n, h in hits[:80]:
    print(f'{n}: {h}')
