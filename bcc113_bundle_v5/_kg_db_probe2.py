"""Second pass: the companion DB has only 12 tables and none matched the name
filter, so dump them all and search every column for the four junction ids.
"""
import glob
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

IDS = ['10158157', '10158160', '11118206', '11127644']
db = [p for p in glob.glob('kg/*.sqlite') if os.path.getsize(p) > 0][0]
con = sqlite3.connect('file:' + db.replace(os.sep, '/') + '?mode=ro', uri=True)
cur = con.cursor()

tabs = [r[0] for r in cur.execute(
    "select name from sqlite_master where type='table' order by name")]
print('DB:', db)
print('tables:', len(tabs))
print()

info = []
for t in tabs:
    cols = [c[1] for c in cur.execute('pragma table_info("%s")' % t)]
    n = cur.execute('select count(*) from "%s"' % t).fetchone()[0]
    info.append((t, n, cols))
    print('%-40s rows=%-7d cols=%s' % (t, n, cols))
    if n:
        row = cur.execute('select * from "%s" limit 1' % t).fetchone()
        for c, v in list(zip(cols, row))[:8]:
            sv = str(v)
            print('      %-22s %s' % (c, sv[:70]))
    print()

print('== id search across every table/column ==')
hit_any = False
for t, n, cols in info:
    if n == 0 or n > 500000:
        continue
    for col in cols:
        for want in IDS:
            try:
                rows = cur.execute(
                    'select * from "%s" where cast("%s" as text) like ? limit 2'
                    % (t, col), ('%' + want + '%',)).fetchall()
            except Exception:
                continue
            for r in rows:
                hit_any = True
                print('\n  %s.%s ~ %s' % (t, col, want))
                for c, v in list(zip(cols, r))[:14]:
                    sv = str(v)
                    print('     %-24s %s' % (c, sv[:80]))
if not hit_any:
    print('  none -- the companion DB holds statistics, not the network topology')

con.close()
