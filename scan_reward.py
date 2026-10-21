import csv
from collections import Counter
p = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\reward_cycle_DCTSP_MP_ECTM_20261008_115259.csv"
with open(p, errors='replace') as f:
    rows = list(csv.DictReader(f))
print("cols:", list(rows[0].keys()))
print("n_rows:", len(rows))
# action label col? guess: find col with GE/INS/NO_ACTION
import re
labcol = None
for c in rows[0].keys():
    vals = set(r[c] for r in rows[:200])
    s = ' '.join(str(v) for v in vals)
    if 'GE' in s and 'INS' in s:
        labcol = c; break
print("label col:", labcol)
if labcol:
    cnt = Counter(r[labcol] for r in rows)
    for k, v in cnt.most_common(25):
        print(f"  {k:22s} {v}")
    # chosen only?
    chosencols = [c for c in rows[0].keys() if 'chos' in c.lower() or 'is_chosen' in c.lower()]
    print("chosen cols:", chosencols)
