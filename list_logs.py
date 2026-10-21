import glob, os, datetime
logs = sorted(glob.glob(r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs\Aimsun_TSP_Log_20261008_15*.txt'), key=os.path.getmtime)
for p in logs[-8:]:
    print(os.path.basename(p), datetime.datetime.fromtimestamp(os.path.getmtime(p)), os.path.getsize(p))
