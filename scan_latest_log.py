import re, os
from collections import Counter

p = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\Aimsun_TSP_Log_20261008_100913.txt"
cats = Counter()
errs = []
tsp_events = []
focus = []
insert_waits = []
with open(p, errors='replace') as f:
    for i, line in enumerate(f):
        if "[Q_EST]" in line: cats["Q_EST"] += 1
        elif "[TSP EVENT]" in line:
            cats["TSP EVENT"] += 1
            if len(tsp_events) < 15: tsp_events.append(line.strip()[:220])
        elif "[BUS_FOCUS]" in line or "focus_" in line:
            cats["FOCUS"] += 1
            if len(focus) < 10: focus.append(line.strip()[:220])
        elif "[DELAY_RATE]" in line: cats["DELAY_RATE"] += 1
        elif "[SIDE_SCAN]" in line: cats["SIDE_SCAN"] += 1
        if re.search(r"ERROR|FATAL|Traceback|Exception|FAILED|failed", line):
            if len(errs) < 30: errs.append((i+1, line.strip()[:250]))
        if "InsertionWait" in line or "insertion_wait" in line:
            if len(insert_waits) < 10: insert_waits.append(line.strip()[:220])
print(dict(cats))
print("--- TSP EVENTS sample ---")
for t in tsp_events: print(t)
print("--- FOCUS sample ---")
for t in focus: print(t)
print(f"--- ERRORS ({len(errs)} shown, may be more) ---")
for n, e in errs: print(n, e)
