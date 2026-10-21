import re
from collections import Counter
p = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\Aimsun_TSP_Log_20261008_100913.txt"
keys = ["suppress", "veto", "VETO", "INS", "GE", "grant", "skip", "SKIP", "cooldown", "COOLDOWN",
        "stale", "noupdate", "ETA", "eta", "TRACK", "track", "Kalman", "SHOCKWAVE",
        "lead", "pre-arm", "prearm", "PREARM", "LATE", "missed", "MISSED", "expired", "discard"]
counts = Counter()
samples = {}
with open(p, errors='replace') as f:
    for line in f:
        for k in keys:
            if k in line:
                counts[k] += 1
                if k not in samples and len(samples) < 40:
                    samples[k] = line.strip()[:260]
for k, v in counts.most_common():
    print(f"{v:7d}  {k:12s}  :: {samples.get(k,'')[:150]}")
