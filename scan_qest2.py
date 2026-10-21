import re
p = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\Aimsun_TSP_Log_20261008_100913.txt"
n=0
with open(p, errors='replace') as f:
    for line in f:
        if "[Q_EST] inter=22232 " in line or "[Q_EST] inter=17249 " in line:
            print(line.strip()[10:220])
            n+=1
            if n>=8: break
