"""Report or set the ENGINE_BUILD tag on the shared engine modules.

RETIRED AS A ONE-SHOT. This used to hardcode

    NEW_TAG = '2026-11-09T1500-lightsim-ctm-busdiag'

and rewrite ENGINE_BUILD to it unconditionally, so re-running it after the
tag had moved on would silently revert the banner to a value that no longer
described the bytes on disk -- exactly the drift the [PREFLIGHT] build gate
exists to catch. It is now read-only unless you ask for a write.

Usage (all paths relative to this file):

    python -I _patch_engine_build.py                  # report current tags
    python -I _patch_engine_build.py --set <TAG>      # rewrite to <TAG>
    python -I _patch_engine_build.py --set <TAG> --dry-run
    python -I _patch_engine_build.py --set <TAG> --force

Exit codes: 0 ok / no-op, 2 no ENGINE_BUILD found, 3 refused (retired tag
without --force), 4 bad arguments.

Remember the project convention is <date>T<HHMM>-<feature>, and that changing
engine.py invalidates any Aimsun session that already loaded it (AGENTS RULE 2).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = [
    os.path.join(HERE, 'shared_tsp_engine', 'engine.py'),
    os.path.join(HERE, 'shared_tsp_engine', 'specialized_modes.py'),
    os.path.join(HERE, 'shared_tsp_engine', 'version.py'),
    os.path.join(HERE, 'shared_tsp_engine', '__init__.py'),
]

PAT = re.compile(br"^([ \t]*ENGINE_BUILD[ \t]*=[ \t]*)(['\"])([^'\"\r\n]+)\2", re.M)

# Tags that no longer describe the build on disk. Writing one of these is a
# revert, not a retag, so it needs --force and a stated reason.
RETIRED_TAGS = frozenset([
    b'2026-11-09T1500-lightsim-ctm-busdiag',
])


def parse_args(argv):
    """Return (tag, dry_run, force, ok). ok is False on any parse error."""
    tag = None
    dry_run = False
    force = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--set':
            i += 1
            if i >= len(argv) or not argv[i].strip():
                print('ERROR: --set needs a tag argument')
                return None, False, False, False
            tag = argv[i].strip().encode('ascii', 'replace')
        elif a == '--dry-run':
            dry_run = True
        elif a == '--force':
            force = True
        elif a in ('-h', '--help'):
            print(__doc__)
            sys.exit(0)
        else:
            print('ERROR: unknown argument %r' % a)
            return None, False, False, False
        i += 1
    return tag, dry_run, force, True


def main(argv):
    tag, dry_run, force, ok = parse_args(argv)
    if not ok:
        return 4
    if tag is None and (dry_run or force):
        print('ERROR: --dry-run / --force only make sense with --set')
        return 4

    found = False
    wrote = False
    for path in CANDIDATES:
        if not os.path.exists(path):
            continue
        with open(path, 'rb') as fh:
            data = fh.read()
        m = PAT.search(data)
        if not m:
            continue
        found = True
        name = os.path.basename(path)
        cur = m.group(3)

        if tag is None:
            print('CURRENT  %-20s %s' % (name, cur.decode('ascii', 'replace')))
            continue

        if cur == tag:
            print('ALREADY  %-20s %s' % (name, cur.decode('ascii', 'replace')))
            continue

        if tag in RETIRED_TAGS and not force:
            print('REFUSED  %-20s %s -> %s is a retired tag; pass --force '
                  'only if you really mean to revert'
                  % (name, cur.decode('ascii', 'replace'),
                     tag.decode('ascii', 'replace')))
            return 3

        if dry_run:
            print('WOULD SET %-19s %s -> %s'
                  % (name, cur.decode('ascii', 'replace'),
                     tag.decode('ascii', 'replace')))
            continue

        new = data[:m.start(3)] + tag + data[m.end(3):]
        tmp = path + '.buildtag.tmp'
        try:
            with open(tmp, 'wb') as fh:
                fh.write(new)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        wrote = True
        print('TAGGED   %-20s %s -> %s'
              % (name, cur.decode('ascii', 'replace'),
                 tag.decode('ascii', 'replace')))

    if not found:
        print('NO ENGINE_BUILD FOUND -- verify the build by content hash instead')
        return 2
    if wrote:
        print('\nengine.py changed: any running Aimsun session is now stale '
              '(AGENTS RULE 2). Quit and relaunch before the next run.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
