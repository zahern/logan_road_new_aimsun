import pathlib
for f in pathlib.Path(r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\shared_tsp_engine').rglob('*.py'):
    try:
        txt = f.read_text(errors='replace')
    except Exception:
        continue
    for i, l in enumerate(txt.splitlines(), 1):
        if 'eta_next' in l.lower() or 'REASON_NO' in l or 'no_corridor' in l.lower() or 'REASON_' in l:
            print(f, i, l.strip()[:120])
