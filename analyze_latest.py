import csv, os, glob, math
from collections import defaultdict

for label, path in [
  ("CHAMPION", r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\champion_beatnotsp_logan_road_new.csv"),
  ("F", r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\f.csv"),
]:
    print("="*80)
    print(label, path)
    try:
        mtime = os.path.getmtime(path)
        import datetime
        print("mtime:", datetime.datetime.fromtimestamp(mtime))
    except Exception as e:
        print("mtime err", e)
    with open(path, newline='', errors='replace') as f:
        r = list(csv.DictReader(f))
    print("n_rows:", len(r))
    by_exp = defaultdict(list)
    for row in r:
        by_exp[row.get('run_experiment','?')].append(row)
    for exp, rows in by_exp.items():
        seeds = sorted(set(x.get('run_seed','?') for x in rows))
        ok = [x for x in rows if (x.get('run_success','')=='True' and x.get('stats_TotalPassDelay_hrs','').strip()!='')]
        print(f"  exp={exp} n={len(rows)} seeds={seeds} ok={len(ok)}")
        if ok:
            d = [float(x['stats_TotalPassDelay_hrs']) for x in ok]
            b = []
            for x in ok:
                try: b.append(float(x['stats_AvgBusTT_s']))
                except: pass
            mean = sum(d)/len(d)
            sd = math.sqrt(sum((v-mean)**2 for v in d)/len(d)) if len(d)>1 else 0.0
            bm = sum(b)/len(b) if b else float('nan')
            print(f"    TotalPassDelay mean={mean:.2f} sd={sd:.2f} details={[round(v,1) for v in d]}")
            print(f"    AvgBusTT mean={bm:.2f} details={b}")
            # also main/side if present
            try:
                md = [float(x['stats_MainPassDelay_hrs']) for x in ok if x.get('stats_MainPassDelay_hrs','').strip()!='']
                if md: print(f"    MainPassDelay mean={sum(md)/len(md):.2f} details={[round(v,1) for v in md]}")
            except Exception as e:
                print("    main err", e)
