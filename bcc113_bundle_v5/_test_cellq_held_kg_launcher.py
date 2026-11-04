"""Test run_cellq_held_kg.py's guard and tally without Aimsun.

Executes the launcher's source only up to the arm-suite exec (so no PyANGKernel
import), under different FIXED_OUT values, then exercises _tally() against a
synthetic log in a temp directory.
"""
import ast
import io
import os
import shutil
import sys
import tempfile
import time

LAUNCHER = 'run_cellq_held_kg.py'
src = io.open(LAUNCHER, encoding='utf-8').read()

CUT = '_runner = _os.path.join'
i = src.index(CUT)
head = src[:i]

fails = []


def check(name, cond, detail=''):
    print('  %-58s %s%s' % (name, 'PASS' if cond else 'FAIL',
                            '' if cond else '  ' + str(detail)))
    if not cond:
        fails.append(name)


def run_head(env_extra, quiet=True):
    """Exec the launcher preamble; return (exit_message_or_None, printed)."""
    saved = {k: os.environ.get(k) for k in
             ('FIXED_OUT', 'FIXED_ALLOW_OVERWRITE', 'FIXED_SEEDS', 'FIXED_ARMS')}
    for k in saved:
        os.environ.pop(k, None)
    os.environ.update(env_extra)
    buf = []
    real_print = print

    class _Sink(object):
        def write(self, s):
            buf.append(s)

        def flush(self):
            pass

    old = sys.stdout
    sys.stdout = _Sink()
    msg = None
    try:
        exec(compile(head, LAUNCHER, 'exec'), {'__name__': '__main__'})
    except SystemExit as e:
        msg = str(e.code) if e.code is not None else ''
    finally:
        sys.stdout = old
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return msg, ''.join(buf)


print('1. default target is accepted')
msg, out = run_head({})
check('no SystemExit on the default', msg is None, msg)
check('banner names the fresh CSV', 'cellq_held_kg.csv' in out)
check('banner prints an expected build', 'ENGINE_BUILD' in out and
      'sha1(engine.py)' in out)
check('post-run gate is armed', 'aborts after run 1' in out)

print('2. a published CSV is refused even with overwrite allowed')
msg, _ = run_head({'FIXED_OUT': 'paper_ladder_priority_kg.csv',
                   'FIXED_ALLOW_OVERWRITE': '1'})
check('refused', msg is not None, 'started anyway')
check('says it is published', 'published' in (msg or '').lower(), msg)
check('offers the safe default', 'cellq_held_kg.csv' in (msg or ''), msg)

print('3. an existing target is refused (champion_search would delete it)')
tmpname = '_tmp_guard_probe.csv'
tmppath = os.path.join(os.path.dirname(os.path.abspath(LAUNCHER)), tmpname)
io.open(tmppath, 'w', encoding='utf-8').write('x\n')
try:
    msg, _ = run_head({'FIXED_OUT': tmpname})
    check('refused', msg is not None, 'started anyway')
    check('explains the delete/resume hazard', 'DELETE' in (msg or ''),
          msg)
    print('4. FIXED_ALLOW_OVERWRITE=1 is the deliberate escape hatch')
    msg, _ = run_head({'FIXED_OUT': tmpname, 'FIXED_ALLOW_OVERWRITE': '1'})
    check('allowed', msg is None, msg)
finally:
    os.remove(tmppath)

print('5. _tally counts admits and groups refusals by constraint')
tree = ast.parse(src)
fn = next((n for n in tree.body
           if isinstance(n, ast.FunctionDef) and n.name == '_tally'), None)
check('_tally found at module level', fn is not None)

tmpd = tempfile.mkdtemp()
try:
    logs = os.path.join(tmpd, 'kg', 'logs')
    os.makedirs(logs)
    log = os.path.join(logs, 'Aimsun_TSP_Log_20260101_000000.txt')
    io.open(log, 'w', encoding='utf-8').write(
        '[CELLQ_ADMIT] inter=1 t=10.0 bus=7 action=GE_5s eff_delay=20.0s\n'
        '[CELLQ_ADMIT] inter=2 t=11.0 bus=8 action=INS_5s eff_delay=21.0s\n'
        '[CELLQ_HELD] inter=1 t=12.0 bus=7 veto=min_gain(4.0<15.0) x\n'
        '[CELLQ_HELD] inter=1 t=13.0 bus=7 veto=min_gain(3.0<15.0) x\n'
        '[CELLQ_HELD] inter=2 t=14.0 bus=8 veto=cost_veto(cost=900>benefit=200*ratio=1.50) x\n'
        '[CELLQ_HELD] inter=2 t=15.0 bus=8 veto=net_pax(cost=90>benefit=10*ratio=1.00) x\n'
        '[CELLQ_HELD] inter=3 t=16.0 bus=9 veto=main_floor(harm=500>benefit=100*ratio=1.00) x\n')
    os.utime(log, (time.time(), time.time()))

    ns = {'_HERE': tmpd, 'CORRIDOR': 'kg', '_os': os, '_glob': __import__('glob'),
          '_re': __import__('re'), 'print': print}
    exec(compile(ast.get_source_segment(src, fn), LAUNCHER, 'exec'), ns)
    print('')
    ns['_tally'](time.time() - 60)
    print('')
finally:
    shutil.rmtree(tmpd, ignore_errors=True)

print('')
if fails:
    sys.exit('FAILED: %s' % fails)
print('ALL CHECKS PASSED')
