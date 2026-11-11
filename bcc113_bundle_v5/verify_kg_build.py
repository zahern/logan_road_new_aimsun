"""verify_kg_build.py -- prove a run executed the CURRENT engine bytes.

Covers BOTH corridors: engine.py and specialized_modes.py are shared, so only the
log directory differs. --logs picks it (default kg/logs; for Logan pass
logan_road_new/logs). champion_search calls check_or_raise() with the OPEN
corridor's directory, so the same gate protects either ladder. The filename is
historical (it was written for KG first); nothing in it is KG-specific.

WHY. Aimsun caches engine.py / specialized_modes.py for the process lifetime, so a
stale module re-runs the OLD code and the old numbers with a tag that looks
plausible. This checks the two places the identity is actually recorded, against
the files on disk right now:

 1. The run's own [LOAD] line
        [LOAD] AAPILoad complete | ... | ENGINE_BUILD=<tag> | SOURCE_HASH=<h> |
               SPM_HASH=<h> | SPM_SRC=loaded | SPM_FILE=<path> |
               STATS_BUILD=<s> | engine_file=<path>
    SOURCE_HASH is sha1(engine.py)[:12] captured AT IMPORT, so it identifies the
    bytes Aimsun executed. A log written before that field existed shows no
    SOURCE_HASH at all -- which is itself proof it is not the patched build.
    SPM_HASH is specialized_modes' own import-time stamp, so ONE run log now
    identifies BOTH modules without reading runner_console.txt. It is only
    checked when SPM_SRC=loaded: "disk" means spm was not importable and the
    value describes the file on disk, so it cannot prove what executed.
    The [LOAD] stamp and the runner's [PREFLIGHT] hash must also AGREE within
    one session: a disagreement means the two sources describe different
    specialized_modes bytes (one is from another session, or a foreign copy
    shadowed the bundle), which is a failure even when each value looks
    plausible on its own.

 2. The batch runner's preflight in <logs>/runner_console.txt
        [PREFLIGHT] engine build matches disk (<tag>)
        [PREFLIGHT] engine content <h> (loaded == disk)
        [PREFLIGHT] specialized_modes content <h> (loaded == disk)
    This is the only one that covers specialized_modes.py, where the cascade,
    Nash and [NASH_HELD] code lives. champion_search FATALs on a mismatch, so if
    a run got past this, the module was fresh.

    NOTE those lines are written to runner_console.txt, NOT the per-run TSP log.

USAGE (outside Aimsun; no model needed, safe while a batch is running):

    python verify_kg_build.py                    # newest KG run log
    python verify_kg_build.py --wait 20          # wait up to 20 min for a NEW run
    python verify_kg_build.py --log <path>       # a specific run log
    python verify_kg_build.py --logs <dir>       # a different log directory

--wait exists so you can arm the check BEFORE pasting the launcher into Aimsun: it
polls until a run log appears that was modified after this script started, then
checks that one. Exit codes: 0 all checks pass, 1 a check failed, 2 no evidence.

ALSO IMPORTED BY champion_search.py, which calls check_or_raise() after the first
completed run of a sweep when CHAMPION_POSTRUN_BUILD_CHECK=1 (the KG launcher
sets it). That turns a stale-module run from "24 more runs of garbage" into an
abort at run 1.
"""
import argparse
import hashlib
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOGS = os.path.join(HERE, "kg", "logs")
ENG_PY = os.path.join(HERE, "shared_tsp_engine", "engine.py")
SPM_PY = os.path.join(HERE, "shared_tsp_engine", "specialized_modes.py")

_EMITS = ("CASCADE", "NASH_BARGAIN", "NASH_HELD", "CTM_CONN",
          "PLAN_OPT", "HARMONY", "SPILLOVER")


def sha12(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()[:12]
    except OSError as exc:
        return "? (%s)" % exc


def engine_tag(path=ENG_PY):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            m = re.search(r'^ENGINE_BUILD\s*=\s*["\']([^"\']+)', fh.read(), re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def expected():
    return {"tag": engine_tag(), "eng": sha12(ENG_PY), "spm": sha12(SPM_PY),
            "eng_py": ENG_PY, "spm_py": SPM_PY}


def corridor_label(logs_dir):
    """'logan_road_new' / 'kg' -- for messages, so a Logan run is not told to
    reopen the KG model."""
    try:
        return os.path.basename(os.path.dirname(
            os.path.abspath(logs_dir).rstrip('/' + os.sep)))
    except Exception:
        return "the"


def run_logs(logs_dir):
    if not os.path.isdir(logs_dir):
        return []
    out = []
    for name in os.listdir(logs_dir):
        if name.startswith("Aimsun_TSP_Log_") and name.endswith(".txt"):
            p = os.path.join(logs_dir, name)
            try:
                out.append((os.path.getmtime(p), p))
            except OSError:
                pass
    return [p for _, p in sorted(out, reverse=True)]


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def load_fields(text):
    """Parse the last [LOAD] ... complete line into a dict of key=value pairs."""
    fields = {}
    line = ""
    for ln in text.splitlines():
        if "[LOAD]" in ln and "complete" in ln:
            line = ln
    for part in line.split("|"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            fields[k.strip()] = v.strip()
    return fields, line.strip()


_START_RE = re.compile(r"Aimsun_TSP_Log_(\d{8})_(\d{6})\.txt$")


def log_start(path):
    """Epoch seconds when this run started, parsed from its filename.

    Aimsun_TSP_Log_YYYYMMDD_HHMMSS.txt. Needed because a run log's MTIME is its
    LAST write: on Logan the newest log ran 08:49->09:00 while the runner's
    console stopped being written at 08:49:30 (one [RUNNER] line per run), so
    comparing console mtime to log mtime declared a same-session preflight
    stale. Comparing to the START is the relationship that actually holds.
    """
    m = _START_RE.search(os.path.basename(path or ""))
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"))
    except ValueError:
        return None


def preflight(text, key):
    m = re.search(r"\[PREFLIGHT\] %s content (\w+) \(loaded == disk\)" % key, text)
    return m.group(1) if m else None


def preflight_tag(text):
    m = re.search(r"\[PREFLIGHT\] engine build matches disk \(([^)]*)\)", text)
    return m.group(1) if m else None


def is_bundle_copy(observed, want):
    """True when a logged import path resolves to the bundle file.

    Aimsun may report the path with either separator or different case, so both
    sides are normalised. Anything that does not land on the bundle is a SHADOWED
    module regardless of how familiar its hash or tag looks: the process ran code
    from somewhere else on sys.path, which no content comparison can reveal.
    """
    if not observed:
        return False
    n = os.path.normcase(os.path.normpath(observed)).replace("/", "\\")
    w = os.path.normcase(os.path.normpath(want)).replace("/", "\\")
    return n == w


def _verdict(res, label, observed, want, note=""):
    if observed is None:
        res["unmeasured"] += 1
        mark, detail = "NOT MEASURED", "absent"
    elif observed == want:
        mark, detail = "PASS", str(observed)
    else:
        res["fails"] += 1
        mark, detail = "FAIL", "%s  (expected %s)" % (observed, want)
    if note and mark != "PASS":
        detail += "  " + note
    res["lines"].append((mark, label, detail))


def evaluate(log_path, logs_dir=None, since=0.0):
    """Check one run log + its session's preflight against the files on disk.

    `since` (epoch seconds) is the moment this batch started. If the newest log
    predates it, the run wrote no log of its own -- an UNMEASURED result, never
    a FAIL borrowed from a previous session.
    """
    logs_dir = logs_dir or DEFAULT_LOGS
    exp = expected()
    res = {"log": log_path, "tag": exp["tag"], "eng": exp["eng"], "spm": exp["spm"],
           "fails": 0, "unmeasured": 0, "lines": [], "fields": {}, "load_line": "",
           "counts": {}, "note": ""}

    if not log_path or not os.path.isfile(log_path):
        res["unmeasured"] += 1
        res["lines"].append(("NO EVIDENCE", "run log", "not found in %s" % logs_dir))
        return res
    try:
        log_mtime = os.path.getmtime(log_path)
    except OSError:
        log_mtime = 0.0
    if since and log_mtime + 1.0 < since:
        res["unmeasured"] += 4
        res["note"] = ("the newest run log predates this batch, so the run wrote "
                       "no log of its own")
        res["lines"].append(("NO EVIDENCE", "run log",
                             "predates the batch: %s"
                             % time.strftime("%Y-%m-%d %H:%M",
                                             time.localtime(log_mtime))))
        return res

    text = read(log_path)
    fields, line = load_fields(text)
    res["fields"], res["load_line"] = fields, line
    _verdict(res, "[LOAD] ENGINE_BUILD", fields.get("ENGINE_BUILD"), exp["tag"])
    if "SOURCE_HASH" not in fields:
        _verdict(res, "[LOAD] SOURCE_HASH", None, exp["eng"],
                 note="field absent: pre-SOURCE_HASH build")
    else:
        _verdict(res, "[LOAD] SOURCE_HASH", fields.get("SOURCE_HASH"), exp["eng"])

    # specialized_modes is cached separately from engine.py, so a run can carry
    # a fresh engine hash and a stale spm. The stamp is only decisive when the
    # engine reported the hash of the module it actually imported (SPM_SRC
    # loaded); a disk hash must never be scored as a pass for what ran.
    if "SPM_HASH" not in fields:
        _verdict(res, "[LOAD] SPM_HASH", None, exp["spm"],
                 note="field absent: build predates the [LOAD] spm stamp")
    elif str(fields.get("SPM_SRC", "")).strip().lower() == "loaded":
        _verdict(res, "[LOAD] SPM_HASH", fields.get("SPM_HASH"), exp["spm"])
    else:
        _verdict(res, "[LOAD] SPM_HASH", None, exp["spm"],
                 note="SPM_SRC=%s: value describes the file, not the loaded "
                      "module ([PREFLIGHT] covers that)"
                      % (fields.get("SPM_SRC") or "?"))

    # WHICH FILE each module was imported from. A copy outside the bundle is a
    # shadowed module, not a stale one, and a matching tag from the wrong copy is
    # still the wrong code. Both modules are checked because Aimsun caches them
    # independently and each can be shadowed independently.
    for _label, _field, _want in (("engine_file", "engine_file", ENG_PY),
                                  ("spm_file", "SPM_FILE", SPM_PY)):
        _seen = str(fields.get(_field, "") or "").strip()
        if _field not in fields:
            _verdict(res, _label, None, "bundle",
                     note="field absent: pre-SPM_FILE build")
        elif _seen in ("", "?"):
            _verdict(res, _label, None, "bundle",
                     note="path unavailable: __file__ was unset at import")
        else:
            _verdict(res, _label,
                     "bundle" if is_bundle_copy(_seen, _want) else _seen, "bundle",
                     note="imported from OUTSIDE the bundle: a foreign copy "
                          "shadowed it on sys.path")

    console = os.path.join(logs_dir, "runner_console.txt")
    ptext = read(console)
    p_mtime = os.path.getmtime(console) if os.path.exists(console) else 0.0
    # 120 s of slack: the runner's console is first written just BEFORE the first
    # run's log is created, and clocks/rounding are not exact.
    _start = log_start(log_path)
    _session_cut = (_start if _start is not None else log_mtime) - 120.0
    if not ptext:
        res["unmeasured"] += 3
        res["lines"].append(("NOT MEASURED", "[PREFLIGHT]", "runner_console.txt missing"))
    elif p_mtime < _session_cut:
        res["unmeasured"] += 3
        res["lines"].append(("NOT MEASURED", "[PREFLIGHT]",
                             "runner_console.txt belongs to an earlier session"))
    else:
        _verdict(res, "[PREFLIGHT] engine build", preflight_tag(ptext), exp["tag"])
        _verdict(res, "[PREFLIGHT] engine content", preflight(ptext, "engine"), exp["eng"])
        _verdict(res, "[PREFLIGHT] specialized_modes",
                 preflight(ptext, "specialized_modes"), exp["spm"])

        # CROSS-CHECK (2026-11-09): both stamps claim to describe the module
        # THIS session loaded, so they must be equal. Each can look plausible
        # while disagreeing -- a console line borrowed from the previous
        # session inside the 120 s slack, or a foreign specialized_modes
        # shadowing the bundle -- and independent verdicts would not catch it.
        # Only comparable when the [LOAD] hash came from the loaded module; a
        # SPM_SRC=disk value describes a file, so it may legitimately differ.
        _load_spm = str(fields.get("SPM_HASH") or "").strip()
        _load_spm_src = str(fields.get("SPM_SRC") or "").strip().lower()
        _pf_spm = preflight(ptext, "specialized_modes")
        if (_load_spm_src == "loaded" and _load_spm not in ("", "?")
                and _pf_spm):
            _verdict(res, "[LOAD] vs [PREFLIGHT] spm", _load_spm, _pf_spm,
                     note="the run log and the runner console describe "
                          "DIFFERENT specialized_modes bytes: one of them "
                          "belongs to another session, or a foreign copy "
                          "of the module was imported")

    for name in _EMITS:
        res["counts"][name] = len(re.findall(r"\[%s\]" % name, text))
    return res


def check_or_raise(logs_dir, since=0.0, log=print):
    """Post-run gate for champion_search: abort the sweep on a FAILED build check.

    Only FAILs abort. NOT MEASURED (missing/foreign-session runner_console.txt)
    is reported and allowed through: the preflight already hard-fails a stale
    module, so an unverifiable extra is not worth killing a multi-hour sweep --
    but it must never be silently counted as a pass either.
    """
    logs = run_logs(logs_dir)
    res = evaluate(logs[0] if logs else "", logs_dir, since=since)
    for mark, label, detail in res["lines"]:
        log("[POSTRUN] %-13s %-30s %s" % (mark, label, detail))
    if res["fails"]:
        raise RuntimeError(
            "[POSTRUN] ABORTING sweep at the first completed run: it did NOT "
            "execute the build on disk (%d check(s) failed). Quit Aimsun "
            "completely, reopen the %s model, re-run. Expected %s / %s."
            % (res["fails"], corridor_label(logs_dir), res["tag"], res["eng"]))
    if res["unmeasured"]:
        log("[POSTRUN] build gate INCONCLUSIVE (%d check(s) not measured) -- "
            "continuing; see [POSTRUN] lines above." % res["unmeasured"])
        return res
    log("[POSTRUN] build gate OK: %s (%s / %s)"
        % (res["tag"], res["eng"], res["spm"]))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--logs", default=DEFAULT_LOGS, help="log directory")
    ap.add_argument("--log", default="", help="a specific run log to check")
    ap.add_argument("--wait", type=float, default=0.0,
                    help="minutes to wait for a run log written after this script "
                         "started (arm it, then launch in Aimsun)")
    ap.add_argument("--poll", type=float, default=10.0, help="poll interval, s")
    a = ap.parse_args(argv)

    logs_dir = os.path.abspath(a.logs)
    exp = expected()

    print("=" * 78)
    print("BUILD VERIFICATION -- expected, from the files on disk now")
    print("  engine.py               %s" % exp["eng_py"])
    print("  ENGINE_BUILD            %s" % exp["tag"])
    print("  sha1(engine.py)[:12]    %s" % exp["eng"])
    print("  sha1(specialized_modes) %s" % exp["spm"])
    print("  logs                    %s" % logs_dir)
    print("=" * 78)

    started = time.time()
    log_path = os.path.abspath(a.log) if a.log else ""
    if not log_path:
        existing = run_logs(logs_dir)
        baseline = os.path.getmtime(existing[0]) if existing else 0.0
        deadline = started + a.wait * 60.0
        log_path = existing[0] if existing and not a.wait else ""
        if a.wait:
            print("[WAIT] polling for a run log newer than %s (up to %s)..."
                  % (time.strftime("%H:%M:%S", time.localtime(baseline)),
                     "%.0f s" % (a.wait * 60.0) if a.wait < 1 else "%.0f min" % a.wait))
            while time.time() < deadline:
                for p in run_logs(logs_dir):
                    try:
                        if os.path.getmtime(p) > max(baseline, started - 1.0):
                            log_path = p
                            break
                    except OSError:
                        pass
                if log_path and "[LOAD]" in read(log_path):
                    break
                log_path = ""
                time.sleep(a.poll)
        if not log_path:
            print("[NO EVIDENCE] no run log found%s."
                  % (" before the wait expired" if a.wait else ""))
            print("  Start the run in Aimsun, or pass --log <path>.")
            return 2

    if not os.path.isfile(log_path):
        print("[NO EVIDENCE] cannot read %s" % log_path)
        return 2

    res = evaluate(log_path, logs_dir)
    text = read(log_path)
    print("\nRUN LOG  %s  (%d lines, %s)"
          % (os.path.basename(log_path), text.count("\n") + 1,
             time.strftime("%Y-%m-%d %H:%M",
                           time.localtime(os.path.getmtime(log_path)))))
    if res["load_line"]:
        print("  %s" % res["load_line"][:300])
    else:
        print("  [!] no '[LOAD] ... complete' line -- truncated or non-run log")
    if res.get("note"):
        print("  [!] %s" % res["note"])

    print("")
    for mark, label, detail in res["lines"]:
        print("  %-13s %-32s %s" % (mark, label, detail))

    print("\nEMITTED IN THIS LOG (zeros are expected on a NO_TSP run)")
    for name in _EMITS:
        print("  %-14s %d" % (name, res["counts"].get(name, 0)))

    print("\n" + "=" * 78)
    if res["fails"]:
        print("RESULT: %d FAILED, %d not measured -> this run did NOT execute the"
              " build on disk." % (res["fails"], res["unmeasured"]))
        print("  Quit Aimsun COMPLETELY, reopen the %s model, and re-run."
              % corridor_label(logs_dir))
        print("=" * 78)
        return 1
    if res["unmeasured"]:
        print("RESULT: no failures, but %d check(s) NOT MEASURED -- see above."
              % res["unmeasured"])
        print("=" * 78)
        return 1
    print("RESULT: PASS -- all checks match the build on disk (%s, %s / %s)."
          % (res["tag"], res["eng"], res["spm"]))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
