import re
p = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\Aimsun_TSP_Log_20261008_100913.txt"
# CONFIG SUMMARY UpDetList lengths
print("--- CONFIG SUMMARY UpDetList ---")
with open(p, errors='replace') as f:
    cur = None
    for line in f:
        m = re.search(r"CONFIG SUMMARY.. Intersection (\d+)", line)
        if m: cur = m.group(1)
        if "UpDetList length" in line and cur:
            print(f"jct={cur} :: {line.strip()[:80]}")
# detector/geometry warnings
print("--- detector/geometry/call-geometry warnings (sample) ---")
n=0
with open(p, errors='replace') as f:
    for line in f:
        if re.search(r"detector|Detector|DET|call_geometry|GEOMETRY|geometry|AKIDet", line) and re.search(r"WARN|warn|fail|FAIL|miss|MISS|skip|SKIP|invalid|INVALID|unknown|0 groups|empty", line):
            print(line.strip()[:220]); n+=1
            if n>=15: break
print("total shown:", n)
# lam distribution in Q_EST
print("--- Q_EST lam distribution ---")
lams=[]
with open(p, errors='replace') as f:
    for line in f:
        if "[Q_EST]" in line:
            m=re.search(r"lam=([0-9.\-]+)", line)
            if m: lams.append(float(m.group(1)))
import math
nz=sum(1 for v in lams if v>0.001)
print(f"n={len(lams)} lam>0.001: {nz} ({100*nz/len(lams):.1f}%) mean={sum(lams)/len(lams):.4f} max={max(lams):.4f}")
