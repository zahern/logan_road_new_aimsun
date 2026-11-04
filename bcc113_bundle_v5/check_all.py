"""check_all.py -- one command to validate every change made this round.

    cd C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5
    python check_all.py

Runs both checks against the newest Aimsun logs and prints a single verdict:

  check_ctm_now.py    CTM connector resolves, recv_q numeric, derived bins vary,
                      NASH_CTM priced, GAME_COOP no longer identical to GAME_BUS
  check_ds_regime.py  DS no longer pinned at the clamp, [DS_DECOMP] present,
                      [REGIME] state observed

Exit code 0 only when both pass.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _run(modname):
    print("\n" + "#" * 74)
    print("# " + modname)
    print("#" * 74)
    try:
        import importlib
        mod = importlib.import_module(modname)
        importlib.reload(mod)
        rc = mod.main()
        return 0 if rc is None else int(rc)
    except SystemExit as e:
        return int(e.code or 0)
    except Exception as e:
        print("ERROR running %s: %r" % (modname, e))
        return 2


def main():
    rc_ctm = _run("check_ctm_now")
    rc_ds = _run("check_ds_regime")
    print("\n" + "=" * 74)
    print("COMBINED VERDICT")
    print("  CTM / game :", "PASS" if rc_ctm == 0 else "FAIL")
    print("  DS / regime:", "PASS" if rc_ds == 0 else "FAIL")
    print("=" * 74)
    if rc_ctm == 0 and rc_ds == 0:
        print("ALL CHECKS PASSED")
        return 0
    print("NOT READY -- see the per-check reasons above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
