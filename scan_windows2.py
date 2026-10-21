import re
txt = open(r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\intersection_configs.py', errors='replace').read()
lines = txt.splitlines()
for i, ln in enumerate(lines):
    if "'detection_window_m': 50.0" in ln:
        # find enclosing junction id by scanning backwards for "    NNNN: {"
        jid = '?'
        for j in range(i, max(0, i - 60), -1):
            m = re.match(r"    (\d+): \{'IntersectionID'", lines[j])
            if m:
                jid = m.group(1)
                break
        print(f"line {i+1} jct={jid}: {lines[i-1].strip()[:70]} || {ln.strip()}")
