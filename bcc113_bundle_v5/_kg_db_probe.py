"""Probe the Aimsun companion SQLite for the split crossings' signal programs.

Answers: do n10158157/n10158160 and n11118206/n11127644 belong to one
controller (one signal program shared between two nodes) or two independent
programs? Reads the .ang companion DB read-only; no Aimsun needed.
"""
import glob
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

IDS = ['10158157', '10158160', '11118206', '11127644']
db = [p for p in glob.glob('kg/*.sqlite') if os.path.getsize(p) > 0][0]
uri = 'file:' + db.replace(os.sep, '/') + '?mode=ro'
print('DB:', db, '(%d bytes)' % os.path.getsize(db))
con = sqlite3.connect(uri, uri=True)
cur = con.cursor()

tabs = [r[0] for r in cur.execute(
    "select name from sqlite_master where type='table' order by name")]
print('tables:', len(tabs))

KW = ('junction', 'control', 'plan', 'signal', 'node', 'tls', 'id')
print('\n== schema: tables whose name looks relevant ==')
relevant = []
for t in tabs:
    if not any(k in t.lower() for k in KW):
        continue
    try:
        n = cur.execute('select count(*) from "%s"' % t).fetchone()[0]
    except Exception:
        continue
    if n == 0:
        continue
    cols = [c[1] for c in cur.execute('pragma table_info("%s")' % t)]
    relevant.append((t, n, cols))
    print('  %-30s rows=%-6d cols=%s' % (t, n, cols[:10]))

print('\n== rows mentioning any of the four junctions ==')
found = {}
for t, n, cols in relevant:
    if n > 400000:
        print('  [skip huge table %s rows=%d]' % (t, n))
        continue
    for col in cols:
        for want in IDS:
            q = ('select * from "%s" where cast("%s" as text) like ? limit 3'
                 % (t, col))
            try:
                rows = cur.execute(q, ('%' + want + '%',)).fetchall()
            except Exception:
                continue
            for r in rows:
                key = (t, want)
                if key in found:
                    continue
                found[key] = r
                print('\n  %s.%s matched %s' % (t, col, want))
                for c, v in zip(cols, r):
                    sv = str(v)
                    if len(sv) > 90:
                        sv = sv[:90] + '...'
                    print('     %-24s %s' % (c, sv))

if not found:
    print('  (no table carries the junction ids directly -- checking name/text columns next)')

print('\n== distinct controller/plan names, if any table exposes them ==')
for t, n, cols in relevant:
    for col in cols:
        if not any(k in col.lower() for k in ('name', 'controller', 'plan', 'program')):
            continue
        try:
            vals = [r[0] for r in cur.execute(
                'select distinct "%s" from "%s" where "%s" is not null limit 12'
                % (col, t, col))]
        except Exception:
            continue
        if vals:
            print('  %s.%s -> %s' % (t, col, vals))
con.close()
