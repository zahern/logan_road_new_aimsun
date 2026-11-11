"""show_load.py -- print the newest [LOAD] line and say whether it matches disk.

    python show_load.py                  # newest run log in EITHER corridor
    python show_load.py --logs kg/logs   # restrict to one log directory
    python show_load.py --log <path>     # a specific run log

Read-only: safe while a batch is running, and no model needs to be open. This is
the quick look; verify_kg_build.py is the full check (it also cross-checks the
runner's [PREFLIGHT] hashes and can wait for a run log written after you arm it).

Verdicts
  MATCHES       every stamped identity field equals the bundle on disk, AND no
                bundle file was written after this run loaded Aimsun
  DIFFERS       at least one field does not -- the run did not execute this build
  STALE         the identity matches, but one of the modules this build runs was
                written AFTER the model load. Aimsun caches engine.py,
                specialized_modes.py, intersection_controller.py and
                Simulation_Stats.py, so that run executed the older code and the
                log says nothing about what is on disk now (AGENTS RULE 2).
                This is what stops a MATCHES verdict from silently coming from
                an earlier session
  CANNOT TELL   no [LOAD] line, or fields this build does not stamp (e.g. a
                pre-SOURCE_HASH log, or SPM_SRC=disk, which describes the file
                on disk rather than the module that was imported)

Exit codes: 0 MATCHES, 1 DIFFERS, 2 CANNOT TELL / no evidence, 3 STALE.
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# Import the sibling verifier even under `python -I`, which does not put the
# script's own directory on sys.path. Every other command in the runbook uses
# -I, so failing there would be a trap.
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import verify_kg_build as V  # noqa: E402  (after the sys.path fix)

DEFAULT_DIRS = [("kg", os.path.join(HERE, "kg", "logs")),
                ("logan_road_new", os.path.join(HERE, "logan_road_new", "logs"))]


def _ago(sec):
    sec = max(0.0, sec)
    if sec < 90.0:
        return "%.0f s ago" % sec
    if sec < 5400.0:
        return "%.0f min ago" % (sec / 60.0)
    return "%.1f h ago" % (sec / 3600.0)


def _newest(dirs):
    """(mtime, corridor label, path) of the newest run log across dirs."""
    best = None
    for label, d in dirs:
        for p in V.run_logs(d):
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if best is None or m > best[0]:
                best = (m, label, p)
    return best


RULE2_FILES = ("intersection_controller.py", "Simulation_Stats.py")


def _corridor_dir(log):
    """The corridor directory owning a run log (kg / logan_road_new)."""
    base = os.path.dirname(os.path.abspath(log))
    if os.path.basename(base).lower() == "logs":
        base = os.path.dirname(base)
    return base


def bundle_files(log):
    """[(label, path, mtime)] for the sources whose mtime decides recency.

    The identity stamps only cover engine.py and specialized_modes.py, but the
    corridor's own intersection_controller.py and Simulation_Stats.py are
    cached by Aimsun just the same, and editing either one makes a run obsolete
    without moving any stamped hash. All four count.
    """
    cand = [("shared_tsp_engine/engine.py", V.ENG_PY),
            ("shared_tsp_engine/specialized_modes.py", V.SPM_PY)]
    corr = _corridor_dir(log)
    cand += [(n, os.path.join(corr, n)) for n in RULE2_FILES]
    out = []
    for label, p in cand:
        try:
            out.append((label, p, os.path.getmtime(p)))
        except OSError:
            pass
    return out


def _delta(sec):
    """'46 s AFTER the load' / '2.2 h BEFORE the load' / 'at the load'."""
    if abs(sec) < 2.0:
        return "at the load"
    side = "AFTER" if sec > 0 else "BEFORE"
    sec = abs(sec)
    if sec < 90.0:
        return "%.0f s %s the load" % (sec, side)
    if sec < 5400.0:
        return "%.0f min %s the load" % (sec / 60.0, side)
    return "%.1f h %s the load" % (sec / 3600.0, side)


def identity(fields, exp):
    """One row per identity field: (mark, label, detail)."""
    rows = []

    def add(label, seen, want, absent):
        seen = "" if seen is None else str(seen).strip()
        if seen in ("", "?"):
            rows.append(("NOT MEASURED", label, absent))
        elif seen == str(want):
            rows.append(("PASS", label, seen))
        else:
            rows.append(("FAIL", label, "%s   (disk: %s)" % (seen, want)))

    add("[LOAD] ENGINE_BUILD", fields.get("ENGINE_BUILD"), exp["tag"],
        "field absent")
    add("[LOAD] SOURCE_HASH", fields.get("SOURCE_HASH"), exp["eng"],
        "field absent: build predates SOURCE_HASH")

    # specialized_modes is cached separately from engine.py, so its hash is
    # decisive only when the engine reported the module it actually imported.
    src = str(fields.get("SPM_SRC") or "").strip().lower()
    if src == "loaded":
        add("[LOAD] SPM_HASH", fields.get("SPM_HASH"), exp["spm"],
            "field absent")
    elif str(fields.get("SPM_HASH") or "").strip():
        rows.append(("NOT MEASURED", "[LOAD] SPM_HASH",
                     "SPM_SRC=%s: describes the file, not what ran"
                     % (src or "?")))
    else:
        rows.append(("NOT MEASURED", "[LOAD] SPM_HASH",
                     "field absent: build predates the [LOAD] spm stamp"))

    # A matching tag from a copy outside the bundle is still the wrong code.
    for label, field, want in (("engine_file", "engine_file", V.ENG_PY),
                               ("spm_file", "SPM_FILE", V.SPM_PY)):
        seen = str(fields.get(field) or "").strip()
        if seen in ("", "?"):
            rows.append(("NOT MEASURED", label, "path unavailable"))
        elif V.is_bundle_copy(seen, want):
            rows.append(("PASS", label, "bundle"))
        else:
            rows.append(("FAIL", label, "%s   (OUTSIDE the bundle)" % seen))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--logs", action="append", default=[],
                    help="log directory (repeatable); default: both corridors")
    ap.add_argument("--log", default="", help="a specific run log to check")
    a = ap.parse_args(argv)

    exp = V.expected()
    if a.log:
        log = os.path.abspath(a.log)
        label = V.corridor_label(os.path.dirname(log))
    else:
        dirs = ([(os.path.basename(os.path.abspath(d)).lower(), d)
                 for d in a.logs] if a.logs else DEFAULT_DIRS)
        dirs = [(lab, os.path.abspath(d)) for lab, d in dirs]
        got = _newest(dirs)
        if not got:
            print("NO EVIDENCE: no Aimsun_TSP_Log_*.txt in %s"
                  % ", ".join(d for _, d in dirs))
            print("  Start a run in Aimsun, or pass --log <path>.")
            return 2
        _, label, log = got

    if not os.path.isfile(log):
        print("NO EVIDENCE: cannot read %s" % log)
        return 2

    text = V.read(log)
    fields, line = V.load_fields(text)
    try:
        mtime = os.path.getmtime(log)
    except OSError:
        mtime = time.time()

    # When the model loaded: the [LOAD] line is written then, and Aimsun binds
    # its modules at that moment. A source file written afterwards is code this
    # run never executed, however familiar its stamped hash looks. This is the
    # one failure the identity fields cannot see: they hash engine.py and
    # specialized_modes.py, but editing a cached module does not move a stamp
    # the log already carries.
    start = V.log_start(log)
    files = bundle_files(log)
    newest = max(files, key=lambda t: t[2]) if files else None
    # [LOAD] stamps whole seconds, so the load really happened somewhere in
    # [start, start+1). A file written inside that same second may well predate
    # it: ambiguous, not stale. A file written in a later second is provably
    # newer than the load, which is all this check needs to be exact.
    stale = ([f for f in files if f[2] >= start + 1.0]
             if start is not None else [])

    print("=" * 78)
    print("NEWEST [LOAD] -- %s" % label)
    print("  %s" % os.path.basename(log))
    print("  written %s (%s)" % (_ago(time.time() - mtime),
                                 time.strftime("%Y-%m-%d %H:%M",
                                               time.localtime(mtime))))
    print("")
    if line:
        print("  %s" % line)
    else:
        print("  [!] no '[LOAD] ... complete' line in this log")
    print("")
    print("BUNDLE ON DISK NOW")
    print("  ENGINE_BUILD            %s" % exp["tag"])
    print("  sha1(engine.py)[:12]    %s" % exp["eng"])
    print("  sha1(specialized_modes) %s" % exp["spm"])
    if newest:
        nm, _, nmt = newest
        print("  newest file written     %-32s %s  (%s)"
              % (nm, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(nmt)),
                 _delta(nmt - start) if start is not None
                 else "load time unknown"))
    print("=" * 78)

    if not line:
        print("")
        print("RESULT: CANNOT TELL -- this log has no [LOAD] line "
              "(truncated, or not a run log).")
        return 2

    rows = identity(fields, exp)
    for mark, lab, det in rows:
        print("  %-13s %-22s %s" % (mark, lab, det))

    fails = [r for r in rows if r[0] == "FAIL"]
    unknown = [r for r in rows if r[0] == "NOT MEASURED"]
    print("")
    if fails:
        print("RESULT: DIFFERS -- %d field(s) do not match the bundle on disk."
              % len(fails))
        print("  This log did NOT execute the current build. Quit Aimsun")
        print("  COMPLETELY, reopen the %s model, and re-run." % label)
        return 1
    if stale:
        print("")
        print("Written AFTER this log loaded (Aimsun had already cached it):")
        for nm, _, nmt in sorted(stale, key=lambda t: t[2]):
            print("  %s  %-40s %s"
                  % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(nmt)),
                     nm, _delta(nmt - start)))
        print("")
        print("RESULT: STALE -- identity matches disk, but this run loaded %d"
              % len(stale))
        print("  bundle file(s) before they were last written, so it executed")
        print("  the older code. Quit Aimsun COMPLETELY, reopen the %s" % label)
        print("  model, and re-run.")
        return 3
    if unknown:
        print("RESULT: CANNOT TELL -- %d field(s) not measured (see above)."
              % len(unknown))
        print("  verify_kg_build.py also cross-checks the runner's [PREFLIGHT]")
        print("  hashes, which cover specialized_modes.py independently.")
        return 2
    print("RESULT: MATCHES -- this log executed the bundle that is on disk now,")
    print("  and nothing in it has been written since that load.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
