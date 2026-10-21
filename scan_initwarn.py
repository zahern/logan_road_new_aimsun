import re
p = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\Aimsun_TSP_Log_20261008_100913.txt"
with open(p, errors='replace') as f:
    for line in f:
        if "INIT_WARN" in line:
            print(line.strip())
            print("-"*100)
