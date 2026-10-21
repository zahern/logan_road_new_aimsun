import os, re, datetime

logdir = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\logs"
for fname in ["Aimsun_TSP_Log_20261008_100913.txt", "Aimsun_TSP_Log_20261008_101708.txt"]:
    p = os.path.join(logdir, fname)
    print("="*80)
    print(fname, "exists:", os.path.exists(p))
    if not os.path.exists(p):
        continue
    mt = datetime.datetime.fromtimestamp(os.path.getmtime(p))
    print("mtime:", mt, "size:", os.path.getsize(p))
    n_qest = 0
    errs = []
    scans_nz = 0
    ests_nz = 0
    pat = re.compile(r"q_est=([0-9.\-]+)\s+q_scan=([0-9.\-]+).*?err_ema=([0-9.\-]+)")
    with open(p, errors='replace') as f:
        for line in f:
            if "[Q_EST]" in line:
                n_qest += 1
                m = pat.search(line)
                if m:
                    qe = float(m.group(1)); qs = float(m.group(2)); ee = float(m.group(3))
                    errs.append(abs(qe-qs))
                    if qs > 0: scans_nz += 1
                    if qe > 0.05: ests_nz += 1
    print(f"Q_EST lines: {n_qest}, q_scan>0 frac: {scans_nz}/{n_qest}, q_est>0.05 frac: {ests_nz}/{n_qest}")
    if errs:
        import math
        mean = sum(errs)/len(errs)
        print(f"mean|q_est-q_scan|={mean:.2f} max={max(errs):.1f} p90={sorted(errs)[int(0.9*len(errs))]:.1f}")

eng = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\shared_tsp_engine\engine.py"
print("="*80)
print("engine.py mtime:", datetime.datetime.fromtimestamp(os.path.getmtime(eng)))
with open(eng, errors='replace') as f:
    txt = f.read()
print("has Q_EST_CORRECTION_ALPHA:", "Q_EST_CORRECTION_ALPHA" in txt)
print("has Auto-correction comment:", "Auto-correction" in txt)
