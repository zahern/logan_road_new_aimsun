"""_test_load_spm_stamp.py -- guard the [LOAD] specialized_modes stamp.

engine.py emits SPM_HASH / SPM_SRC on its [LOAD] line so ONE run log identifies
both cached modules. The failure this must not repeat: reporting the DISK hash
while the process ran a stale specialized_modes -- a green stamp over old code.

Part 1 execs the real [SPM_STAMP] block out of engine.py and checks the three
       resolutions: loaded module wins, importer-less -> disk hash is labelled
       'disk', nothing available -> 'absent' (never a hash).
Part 2 feeds synthetic [LOAD] lines to verify_kg_build.evaluate() and checks the
       verdict: PASS / FAIL / NOT MEASURED, with a disk hash never scoring PASS.
Part 3 checks the same-session cross-check: a [LOAD] stamp that disagrees with
       the runner's [PREFLIGHT] specialized_modes hash must FAIL, agreeing stamps
       must PASS, and the check must not run at all when SPM_SRC=disk or when the
       console belongs to an earlier session (nothing comparable).

Run: python -I _test_load_spm_stamp.py   (exit 0 = all good)
"""
import hashlib
import importlib.util as ilu
import os
import shutil
import sys
import tempfile
import textwrap
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ENG_PY = os.path.join(HERE, 'shared_tsp_engine', 'engine.py')
VERIFIER = os.path.join(HERE, 'verify_kg_build.py')

FAILS = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILS.append(label)
    print('  %-42s %s  (got %r, want %r)'
          % (label, 'ok  ' if ok else 'FAIL', got, want))


def stamp_block():
    """The SPM_STAMP block as real source, dedented for standalone exec."""
    src = open(ENG_PY, 'rb').read().decode('latin-1')
    a = src.index('# -- [SPM_STAMP] --')
    a = src.rindex('\n', 0, a) + 1          # include the line's leading spaces
    b = src.index('# -- [/SPM_STAMP] --')
    b = src.index('\n', b) + 1              # through the end of that line
    return textwrap.dedent(src[a:b])


def run_block(ns):
    ns = dict(ns or {})
    exec(compile(stamp_block(), '<spm_stamp>', 'exec'), ns)
    if '_spm_stamp' in ns:
        return ns['_spm_stamp']()
    return ns['_spm_hash'], ns['_spm_src']


def load_verifier():
    spec = ilu.spec_from_file_location('vkb', VERIFIER)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def part1():
    print('PART 1 -- the stamp resolution (exec of engine.py source)')
    d = tempfile.mkdtemp()
    try:
        pkg = os.path.join(d, 'shared_tsp_engine')
        os.makedirs(pkg)
        open(os.path.join(pkg, 'engine.py'), 'w').write('#')
        spm = os.path.join(pkg, 'specialized_modes.py')
        open(spm, 'w').write('# fake spm\n')
        disk = hashlib.sha1(open(spm, 'rb').read()).hexdigest()[:12]

        fake = types.ModuleType('specialized_modes')
        fake.SOURCE_HASH = 'deadbeef1234'
        fake.__file__ = os.path.join(d, 'nope.py')

        for name in ('specialized_modes', 'shared_tsp_engine.specialized_modes'):
            sys.modules.pop(name, None)
        # the engine's own `_spm` binding wins
        check('loaded via globals()["_spm"]', run_block({'os': os, '_spm': fake}),
              ('deadbeef1234', 'loaded', fake.__file__))
        # otherwise found through sys.modules under either import name
        sys.modules['specialized_modes'] = fake
        check('loaded via sys.modules', run_block({'os': os}),
              ('deadbeef1234', 'loaded', fake.__file__))
        sys.modules.pop('specialized_modes', None)
        sys.modules['shared_tsp_engine.specialized_modes'] = fake
        check('loaded via sys.modules (pkg name)', run_block({'os': os}),
              ('deadbeef1234', 'loaded', fake.__file__))
        sys.modules.pop('shared_tsp_engine.specialized_modes', None)

        # module never imported: hash the file, but LABEL it disk
        check('not imported -> disk hash, src=disk',
              run_block({'os': os, '__file__': os.path.join(pkg, 'engine.py')}),
              (disk, 'disk', spm))
        # nothing at all: no invented hash
        check('nothing available -> absent', run_block({'os': os}), ('?', 'absent', '?'))
        # a module imported from OUTSIDE the bundle reports that path, not the bundle's
        stray = types.ModuleType('specialized_modes')
        stray.SOURCE_HASH = 'feedface0001'
        stray.__file__ = os.path.join(d, 'elsewhere', 'specialized_modes.py')
        check('reports the file it came from', run_block({'os': os, '_spm': stray}),
              ('feedface0001', 'loaded', stray.__file__))

        # a module with no SOURCE_HASH must fall through, not report '?/loaded'
        blunted = types.ModuleType('specialized_modes')
        blunted.__file__ = spm
        sys.modules['specialized_modes'] = blunted
        check('module without SOURCE_HASH -> disk',
              run_block({'os': os}), (disk, 'disk', spm))
        sys.modules.pop('specialized_modes', None)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def part2():
    print('PART 2 -- verify_kg_build verdicts on synthetic [LOAD] lines')
    v = load_verifier()
    exp = v.expected()
    d = tempfile.mkdtemp()
    try:
        def verdict(name, extra):
            line = ('12:00:00 | [LOAD] AAPILoad complete | mode=NORMAL | '
                    'n_intersections=23 | ENGINE_BUILD=%s | SOURCE_HASH=%s | %s'
                    'STATS_BUILD=? | engine_file=%s'
                    % (exp['tag'], exp['eng'], extra, exp['eng_py']))
            path = os.path.join(d, 'Aimsun_TSP_Log_20261109_1200%02d.txt'
                                % len(os.listdir(d)))
            open(path, 'w').write(line + '\n')
            res = v.evaluate(path, d)
            for mark, label, _detail in res['lines']:
                if 'SPM_HASH' in label:
                    return mark
            return 'NO LINE'

        check('matching stamp, src=loaded',
              verdict('ok', 'SPM_HASH=%s | SPM_SRC=loaded | ' % exp['spm']), 'PASS')
        check('stale module (the 11:09 case)',
              verdict('stale', 'SPM_HASH=9be1e01e3fbb | SPM_SRC=loaded | '), 'FAIL')
        check('src=disk cannot score PASS',
              verdict('disk', 'SPM_HASH=%s | SPM_SRC=disk | ' % exp['spm']),
              'NOT MEASURED')
        check('field absent (older build)', verdict('absent', ''), 'NOT MEASURED')
        check('src empty cannot score PASS',
              verdict('weird', 'SPM_HASH=%s | SPM_SRC= | ' % exp['spm']),
              'NOT MEASURED')
    finally:
        shutil.rmtree(d, ignore_errors=True)


def part3():
    print('PART 3 -- [LOAD] stamp vs [PREFLIGHT] hash, same session')
    v = load_verifier()
    exp = v.expected()

    def session(load_hash, load_src, pf_hash, console_age=0.0):
        """One temp log dir: a [LOAD] line plus runner_console.txt, evaluated."""
        d = tempfile.mkdtemp()
        try:
            stamp = time.strftime('%Y%m%d_%H%M%S',
                                  time.localtime(time.time() - 60))
            path = os.path.join(d, 'Aimsun_TSP_Log_%s.txt' % stamp)
            open(path, 'w').write(
                '12:00:00 | [LOAD] AAPILoad complete | mode=NORMAL | '
                'ENGINE_BUILD=%s | SOURCE_HASH=%s | SPM_HASH=%s | SPM_SRC=%s | '
                'STATS_BUILD=? | engine_file=%s\n'
                % (exp['tag'], exp['eng'], load_hash, load_src, exp['eng_py']))
            con = os.path.join(d, 'runner_console.txt')
            open(con, 'w').write(
                '[PREFLIGHT] engine build matches disk (%s)\n'
                '[PREFLIGHT] engine content %s (loaded == disk)\n'
                '[PREFLIGHT] specialized_modes content %s (loaded == disk)\n'
                % (exp['tag'], exp['eng'], pf_hash))
            if console_age:
                then = time.time() - console_age
                os.utime(con, (then, then))
            res = v.evaluate(path, d)
            hit = [l for l in res['lines'] if 'vs [PREFLIGHT]' in l[1]]
            return hit[0][0] if hit else 'NO LINE'
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # the two stamps agree -> the cross-check runs and passes (so its presence
    # in the table confirms it was actually evaluated, not silently skipped)
    check('agreeing stamps -> PASS',
          session(exp['spm'], 'loaded', exp['spm']), 'PASS')
    # the run log and the console describe different bytes -> FAIL
    check('disagreeing stamps -> FAIL',
          session(exp['spm'], 'loaded', '9be1e01e3fbb'), 'FAIL')
    # a disk-sourced stamp is not comparable and must not be scored
    check('SPM_SRC=disk -> no line',
          session('fc22841112a4', 'disk', '9be1e01e3fbb'), 'NO LINE')
    # console from an earlier session is out of scope
    check('earlier-session console -> no line',
          session(exp['spm'], 'loaded', '9be1e01e3fbb', console_age=4000.0),
          'NO LINE')


if __name__ == '__main__':
    part1()
    part2()
    part3()
    print('\nRESULT: %d failure(s)' % len(FAILS))
    sys.exit(1 if FAILS else 0)
