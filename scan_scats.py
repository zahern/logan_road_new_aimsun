import re
for site in ['B0652', 'B0653']:
    base = rf"C:\Users\ahernz\github_for_aimsun\iMove SCATS File Share\Personalities\South\{site}"
    print("="*70); print(site)
    # CIS inputs
    try:
        cis = open(base + [f for f in __import__('os').listdir(base) if f.startswith('CIS')][0] if False else None)
    except Exception:
        pass
    import os
    for f in sorted(os.listdir(base)):
        if f.startswith('CIS') or f.startswith('LST'):
            p = os.path.join(base, f)
            txt = open(p, errors='replace').read()
            if f.startswith('CIS'):
                print(f"--- {f} ---"); print(txt[:2200])
            else:
                for ln in txt.splitlines():
                    if re.search(r"FUND\d.*FDB", ln):
                        print(ln[:150])
