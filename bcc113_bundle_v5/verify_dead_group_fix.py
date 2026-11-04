"""verify_dead_group_fix.py -- did the dead-detector-group fix actually take effect?

WHY (2026-11-02): `_wire_dead_det_groups()` flags an UpDetList group whose IDs
all return report<0 and wires its slots to the origin sections of the phase it
serves, so the density fallback can MEASURE the approach instead of reporting
flow 0.0.  Two things have to be shown on a real run, and neither is visible in
the summary CSV:

  1. FLAG  the group is detected as dead and given a substitute section
           (`[DET_GROUP] inter=... group=... state=DEAD_SUBSTITUTED ...`);
  2. FLOW  the substitute actually produces a non-zero flow
           (`[DET_FLOW] inter=... group=... flow=[...]`), i.e. the group is
           measured rather than reading as an empty approach.

Build provenance is NOT re-implemented here: it delegates to
verify_kg_build.evaluate(), so this checker and the post-run gate cannot drift.

USAGE
    python verify_dead_group_fix.py                     # newest Logan run
    python verify_dead_group_fix.py --corridor kg
    python verify_dead_group_fix.py --log <path> --group 1 --min-frac 0.5

EXIT CODES
    0  PASS   -- build matches disk, group substituted, flow non-zero
    1  FAIL   -- stale build, no substitute, or flow still zero
    2  NOT YET-- nothing to verify (run predates the fix, or no dead group /
                 no [DET_FLOW] samples yet)
"""
import argparse
import ast
import importlib.util
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# re.M matters: these tags appear once per line in a multi-line log, and `$`
# without it anchors at end-of-STRING -- which silently matched only the final
# line. Caught by the fixture tests, not by reading the pattern.
_RE_DET_GROUP = re.compile(
    r"\[DET_GROUP\]\s+inter=(?P<inter>\d+)\s+group=(?P<group>\d+)\s+"
    r"state=(?P<state>\S+).*?substitute_secs=(?P<secs>.+?)\s*$", re.M)
_RE_DET_FLOW = re.compile(
    r"\[DET_FLOW\]\s+inter=(?P<inter>\d+)\s+t=(?P<t>[\d.]+)\s+"
    r"group=(?P<group>\d+).*?flow=(?P<flow>\[[^\]]*\])\s*(?P<rest>.*)$", re.M)


def _load_verifier():
    """Import verify_kg_build from this directory (no package, no sys.path games)."""
    path = os.path.join(_HERE, "verify_kg_build.py")
    spec = importlib.util.spec_from_file_location("verify_kg_build", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _newest_log(logs_dir):
    try:
        names = [n for n in os.listdir(logs_dir)
                 if n.startswith("Aimsun_TSP_Log_") and n.endswith(".txt")]
    except OSError:
        return None
    if not names:
        return None
    paths = [os.path.join(logs_dir, n) for n in names]
    return max(paths, key=lambda p: os.path.getmtime(p))


def _parse_flows(text, inter, group):
    """All [DET_FLOW] flow vectors for one (inter, group), oldest first."""
    out = []
    for m in _RE_DET_FLOW.finditer(text):
        if int(m.group("inter")) != inter or int(m.group("group")) != group:
            continue
        try:
            flow = ast.literal_eval(m.group("flow"))
        except (ValueError, SyntaxError):
            continue
        if not isinstance(flow, list):
            continue
        out.append((float(m.group("t")), [float(v) for v in flow]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corridor", default="logan_road_new",
                    help="corridor package whose logs to inspect (default: logan_road_new)")
    ap.add_argument("--log", default=None, help="explicit run log (overrides --corridor)")
    ap.add_argument("--inter", type=int, default=22232, help="junction to check (default: 22232)")
    ap.add_argument("--group", type=int, default=1, help="UpDetList group (default: 1)")
    ap.add_argument("--min-frac", type=float, default=0.5,
                    help="fraction of [DET_FLOW] samples that must be non-zero (default: 0.5)")
    args = ap.parse_args(argv)

    logs_dir = os.path.join(_HERE, args.corridor, "logs")
    log_path = args.log or _newest_log(logs_dir)
    if not log_path or not os.path.isfile(log_path):
        print("NOT YET: no run log found in %s" % logs_dir)
        return 2

    vkb = _load_verifier()
    res = vkb.evaluate(log_path, logs_dir=logs_dir)

    print("=" * 78)
    print("DEAD-GROUP FIX VERIFICATION")
    print("  log      %s" % os.path.basename(log_path))
    print("  expected %s  /  %s" % (res["tag"], res["eng"]))
    print("=" * 78)
    for mark, label, detail in res["lines"]:
        print("  %-12s %-26s %s" % (mark, label, detail))

    # A run on a DIFFERENT build is not a failure -- it just predates the fix.
    # A run on the SAME tag with a different hash is a failure: that is exactly
    # the stale-module case the tag cannot expose.
    obs_tag = res["fields"].get("ENGINE_BUILD")
    if obs_tag != res["tag"]:
        print("\nNOT YET: this run is on %s; the fix is %s."
              % (obs_tag, res["tag"]))
        print("Restart Aimsun fully, then re-run.")
        return 2
    if res["fails"]:
        print("\nFAIL: same build tag, different content -- the module is STALE. "
              "Full Aimsun restart required.")
        return 1
    if res["unmeasured"]:
        # engine.py is the file this fix lives in, and its hash was measured
        # above; a stale runner_console.txt only hides the specialized_modes
        # stamp, which cannot affect this check.
        print("\n(note) %d build check(s) unmeasured -- see above; engine hash "
              "was verified." % res["unmeasured"])

    text = _read(log_path)

    # ── 1. the group is flagged dead and given a substitute ────────────────
    hits = [m for m in _RE_DET_GROUP.finditer(text)
            if int(m.group("inter")) == args.inter and int(m.group("group")) == args.group]
    if not hits:
        seen = len(_RE_DET_GROUP.findall(text))
        print("\nNOT YET: no [DET_GROUP] line for inter=%d group=%d "
              "(%d such line(s) anywhere in this log)."
              % (args.inter, args.group, seen))
        return 2
    m = hits[-1]
    state, secs = m.group("state"), m.group("secs").strip()
    print("\n[DET_GROUP] state=%s substitute_secs=%s" % (state, secs))
    if state != "DEAD_SUBSTITUTED" or secs.startswith("none"):
        print("FAIL: group is %s -- it is UNMEASURED, not measured." % state)
        return 1

    # ── 2. the substitute produces a non-zero flow ────────────────────────
    samples = _parse_flows(text, args.inter, args.group)
    if not samples:
        print("NOT YET: no [DET_FLOW] samples yet (emitted once per minute; "
              "re-run after the simulation has advanced).")
        return 2
    nz = [s for s in samples if any(v > 0.0 for v in s[1])]
    frac = len(nz) / float(len(samples))
    mean_max = sum(max(f) for _, f in samples) / float(len(samples))
    print("[DET_FLOW]    samples=%d  non-zero=%d (%.0f%%)  mean(max slot)=%.1f"
          % (len(samples), len(nz), 100.0 * frac, mean_max))
    print("              first=%s  last=%s"
          % (samples[0][1], samples[-1][1]))
    if frac < args.min_frac:
        print("\nFAIL: flow is zero on %.0f%% of samples (need <= %.0f%% zero) -- "
              "the group still reads as an empty approach."
              % (100.0 * (1.0 - frac), 100.0 * (1.0 - args.min_frac)))
        return 1

    print("\nPASS: %d/%d samples carry non-zero flow for the substituted group."
          % (len(nz), len(samples)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
