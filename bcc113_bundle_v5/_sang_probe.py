"""Open the Aimsun .sang (SQLite model) and find the signal control objects.

Goal: decide whether the two split crossings
    n10158157 <-> n10158160   (12.1 m apart)
    n11118206 <-> n11127644   (15.2 m apart)
are driven by one controller / one control plan, or by two independent ones.

Prints the schema first, then every row that mentions one of the four junction
ids, then any table that links junctions to control plans/controllers.
"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

P = 'kg/TEG_KGER_T2_2025Base_QUT_AITAN1_RECOVER.sang'
IDS = [10158157, 10158160, 11118206, 11127644]
IDT = [str(i) for i in IDS]

print('file :', P, '(%d bytes)' % os.path.getsize(P))
with open(P, 'rb') as fh:
    magic = fh.read(16)
print('magic:', magic)
if not magic.startswith(b'SQLite format 3'):
    print('NOT a SQLite container -- cannot read without Aimsun')
    raise SystemExit(1)

con = sqlite3.connect('file:' + P.replace(os.sep, '/') + '?mode=ro', uri=True)
cur = con.cursor()
tabs = [r[0] for r in cur.execute(
    "select name from sqlite_master where type='table' order by name")]
print('tables:', len(tabs))

info = []
for t in tabs:
    try:
        cols = [c[1] for c in cur.execute('pragma table_info("%s")' % t)]
        n = cur.execute('select count(*) from "%s"' % t).fetchone()[0]
    except Exception as e:
        print('  [skip %s: %r]' % (t, e))
        continue
    info.append((t, n, cols))

print('\n== tables (non-empty) ==')
for t, n, cols in info:
    if n:
        print('  %-32s rows=%-6d cols=%s' % (t, n, ', '.join(cols[:9])))

print('\n== tables whose name/columns mention control or signal ==')
KEY = ('control', 'signal', 'plan', 'cntl', 'tls', 'phase')
cand = [(t, n, c) for t, n, c in info
        if any(k in t.lower() for k in KEY)
        or any(k in ' '.join(c).lower() for k in KEY)]
for t, n, cols in cand:
    print('  %-32s rows=%-6d cols=%s' % (t, n, ', '.join(cols[:14])))

print('\n== rows mentioning the four junction ids ==')
hits = 0
for t, n, cols in info:
    if not n or n > 300000:
        continue
    for col in cols:
        for want in IDT:
            try:
                rows = cur.execute(
                    'select * from "%s" where cast("%s" as text)=? limit 4'
                    % (t, col), (want,)).fetchall()
            except Exception:
                continue
            for r in rows:
                hits += 1
                print('\n  %s.%s = %s' % (t, col, want))
                for c, v in list(zip(cols, r))[:16]:
                    sv = str(v)
                    print('     %-26s %s' % (c, sv[:80]))
if not hits:
    print('  (no exact-id match; ids may live in a blob or under different keys)')

print('\n== junction <-> control-plan linkage, if the schema exposes it ==')
for t, n, cols in cand:
    low = [c.lower() for c in cols]
    if not n:
        continue
    jcol = next((c for c in cols if 'junction' in c.lower()), None)
    ccol = next((c for c in cols if 'control' in c.lower() or 'plan' in c.lower()), None)
    if jcol and ccol:
        print('  table %s: junction col=%s, control col=%s' % (t, jcol, ccol))
        try:
            for r in cur.execute(
                    'select "%s","%s" from "%s" limit 25' % (jcol, ccol, t)):
                print('     %s -> %s' % (r[0], r[1]))
        except Exception as e:
            print('     query failed: %r' % (e,))
con.close()
