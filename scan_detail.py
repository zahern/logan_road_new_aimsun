import re
p = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\Aimsun_TSP_Log_20261008_100913.txt"
# full SIDE_SCAN + TSP RULE samples
n1=n2=0
with open(p, errors='replace') as f:
    for line in f:
        if "[SIDE_SCAN]" in line and n1 < 2:
            print("SIDE_SCAN:", line.strip()[:600]); print(); n1+=1
        if "[TSP RULE]" in line and n2 < 6:
            print("RULE:", line.strip()[:300]); n2+=1
        if n1>=2 and n2>=6: break
print("="*60)
# Q_EST early (t<1800) vs late (t>3600) error
pat = re.compile(r"\[Q_EST\].*?t=(\d+).*?q_est=([0-9.\-]+)\s+q_scan=([0-9.\-]+)")
early, late = [], []
with open(p, errors='replace') as f:
    for line in f:
        if "[Q_EST]" in line:
            m = pat.search(line)
            if m:
                t=int(m.group(1)); e=abs(float(m.group(2))-float(m.group(3)))
                (early if t<1800 else late if t>3600 else None) if True else None
                if t<1800: early.append(e)
                elif t>3600: late.append(e)
import math
def stats(v):
    m=sum(v)/len(v)
    sd=math.sqrt(sum((x-m)**2 for x in v)/len(v))
    return f"n={len(v)} mean={m:.2f} sd={sd:.2f} max={max(v):.1f}"
print("QEST early t<1800:", stats(early))
print("QEST late  t>3600:", stats(late))
