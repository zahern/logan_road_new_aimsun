import re
p = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\Aimsun_TSP_Log_20261008_100913.txt"
for jct in ["17249", "22232"]:
    with open(p, errors='replace') as f:
        for line in f:
            if f"[SIDE_SCAN] inter={jct} " in line:
                m = re.search(r"secs=\[([^\]]*)\]", line)
                m2 = re.search(r"len_m=\[(.*?)\] flow=", line)
                print(f"jct={jct} secs=[{m.group(1) if m else '?'}]")
                print(f"  len_m=[{m2.group(1)[:300] if m2 else '?'}]")
                break
