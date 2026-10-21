import re
txt = open(r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\intersection_configs.py', errors='replace').read()
for m in re.finditer(r"^    (\d+): \{'IntersectionID'.*?$", txt, re.M):
    jid = m.group(1)
    if jid in ('20280', '18044', '21847', '17628', '19196', '19363'):
        seg = txt[m.start():m.start() + 3000]
        dw = re.search(r"'detection_window_m':\s*([0-9.]+)", seg)
        ge = re.search(r"'GE_upper_bound':\s*([0-9.]+)", seg)
        print(jid, 'window=', dw.group(1) if dw else '?', 'GEub=', ge.group(1) if ge else '?')
