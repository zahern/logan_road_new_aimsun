"""Test the FIXED_ARMS / FIXED_OUT stale-knob guard across the launcher family.

No Aimsun: each launcher is executed only up to its delegate exec (for the
shared delegate, up to its arm-suite exec) inside a controlled os.environ, and
only the effective knobs are inspected. Nothing runs a simulation.

Why this exists: os.environ lives for the whole Aimsun process, so before the
guard a launcher exec'd after a different one silently reused that launcher's
arm list and output name. Measured on 2026-11-09: the LightSim ladder picked up
the CELLQ arms and would have written cellq_held_kg.csv.

Three families, because they need different guard behaviour:

  ARM_SET     read BOTH knobs and set their own defaults (13 launchers)
  CELLQ       the shared delegate: reads both, leaves FIXED_OUT to the caller
  OUT_SETTERS set FIXED_OUT from their own variable and never read FIXED_ARMS,
              so a foreign arm list must be DROPPED -- otherwise the handover
              would launder a third launcher's arms into the delegate as if
              they were theirs.
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OWNER = "FIXED_ENV_OWNER"
DELEGATE = "run_cellq_held_kg.py"

LADDERS = [
    "run_game_ladder_logan_lightsim.py",
    "run_game_ladder_logan_spill.py",
    "run_game_ladder_logan_chain_ab.py",
    "run_game_ladder_logan.py",
    "run_game_ladder_kg.py",
    "run_game_ladder_kg_ctmcap_ab.py",
]

# Read both knobs and write their own. Their delegate (the arm suite) does not
# consult the knobs, so no handover is needed.
ARM_SET = LADDERS + [
    "run_cellq_act_ab_kg.py",
    "run_insx_kg.py",
    "run_ladder_5seeds_fixed.py",
    "run_ladder_priority_on_dsw.py",
    "run_ladder_priority_on_dsw_logan.py",
    "run_paper_kg_spillback.py",
]

CELLQ = DELEGATE
V2 = "run_cellq_held_kg_v2.py"
OUT_SETTERS = [
    "run_ladder_nashheld_kg.py",
    "run_ladder_nashheld_logan.py",
    "run_ladder_priority_logan_seeds_500_700.py",
]
ALL = ARM_SET + [CELLQ, V2] + OUT_SETTERS

# Launchers that delegate to a GUARDED launcher and must therefore hand the
# env over; the value is the file whose name they stamp before the exec.
HANDOFF = {p: DELEGATE for p in LADDERS}
HANDOFF[V2] = DELEGATE
HANDOFF["run_ladder_nashheld_kg.py"] = "run_ladder_priority_on_dsw.py"
HANDOFF["run_ladder_nashheld_logan.py"] = "run_ladder_priority_on_dsw_logan.py"
HANDOFF["run_ladder_priority_logan_seeds_500_700.py"] = \
    "run_ladder_priority_on_dsw_logan.py"

_KNOBS = (
    "FIXED_ARMS", "FIXED_OUT", OWNER, "FIXED_HERE", "FIXED_SEEDS",
    "FIXED_TRAIN_SEEDS", "FIXED_CORRIDOR", "FIXED_ALLOW_OVERWRITE",
    "LIGHTSIM_SOLS", "CHAIN_AB_SOLS", "GAME_SPILL_VARIANT",
    "GAME_LADDER_PAYOFF", "NASHHELD_SEEDS", "NASHHELD_OUT", "NASHHELD_DRYRUN",
)
_SNAP = ("FIXED_ARMS", "FIXED_OUT", OWNER)
_MARKERS = ("_launcher = _os.path.join", "_runner = _os.path.join",
            "_base = _os.path.join", "# Hand the env over:")

fails = []


def check(name, cond, detail=""):
    print("  %-64s %s%s" % (name, "PASS" if cond else "FAIL",
                            "" if cond else "  " + str(detail)))
    if not cond:
        fails.append(name)


def _source(path):
    return io.open(os.path.join(HERE, path), encoding="utf-8").read()


def head(path):
    """Everything before the delegate exec, one of _MARKERS."""
    src = _source(path)
    return src[:min(src.index(m) for m in _MARKERS if m in src)]


class _Sink(object):
    def __init__(self):
        self.parts = []

    def write(self, s):
        self.parts.append(s)

    def flush(self):
        pass


def _exec(sink, path):
    real = sys.stdout
    sys.stdout = sink
    try:
        exec(compile(head(path), path, "exec"),
             {"__name__": "__main__", "__file__": path})
    finally:
        sys.stdout = real


def _restore(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _reset(env_extra):
    saved = {k: os.environ.get(k) for k in _KNOBS}
    for k in _KNOBS:
        os.environ.pop(k, None)
    os.environ["FIXED_HERE"] = HERE
    os.environ.update(env_extra)
    return saved


def run(path, env_extra):
    """Exec one launcher's preamble; return (printed, {knob: value})."""
    saved = _reset(env_extra)
    sink, snap = _Sink(), {}
    try:
        _exec(sink, path)
        snap = {k: os.environ.get(k, "") for k in _SNAP}
    finally:
        _restore(saved)
    return "".join(sink.parts), snap


def chain(paths, env_extra):
    """Exec the preambles in order, simulating each tail's handover.

    Returns ([(path, printed)], {knob: value}) for the final env.
    """
    saved = _reset(env_extra)
    steps = []
    try:
        for i, p in enumerate(paths):
            if i:
                os.environ[OWNER] = p      # what the previous tail does
            sink = _Sink()
            _exec(sink, p)
            steps.append((p, "".join(sink.parts)))
        snap = {k: os.environ.get(k, "") for k in _SNAP}
    finally:
        _restore(saved)
    return steps, snap


# ── 1. clean session: own defaults, env claimed ──────────────────────────────
print("1. clean session -- own defaults, owner stamped")
clean = {}
for p in ARM_SET:
    out, snap = run(p, {})
    clean[p] = snap["FIXED_ARMS"]
    check("%s: owner stamped" % p, snap[OWNER] == p, snap[OWNER])
    check("%s: arms non-empty" % p, bool(snap["FIXED_ARMS"]),
          snap["FIXED_ARMS"])
    check("%s: no [ENV] line" % p, "[ENV]" not in out, out[-160:])

for p in [CELLQ, V2]:
    out, snap = run(p, {})
    clean[p] = snap["FIXED_ARMS"]
    check("%s: owner stamped" % p, snap[OWNER] == p, snap[OWNER])
    check("%s: no [ENV] line" % p, "[ENV]" not in out, out[-160:])

for p in OUT_SETTERS:
    out, snap = run(p, {})
    clean[p] = ""
    check("%s: owner stamped" % p, snap[OWNER] == p, snap[OWNER])
    check("%s: reads no arms" % p, snap["FIXED_ARMS"] == "",
          snap["FIXED_ARMS"])
    check("%s: own output name" % p,
          bool(snap["FIXED_OUT"]) and snap["FIXED_OUT"] != "stale.csv",
          snap["FIXED_OUT"])
    check("%s: no [ENV] line" % p, "[ENV]" not in out, out[-160:])

# The delegate's default must differ from every ladder's, or a leak of the arm
# list is undetectable in the first place.
check("delegate default differs from every ladder",
      all(clean[CELLQ] != clean[p] for p in LADDERS), clean[CELLQ])

# ── 2. a value left by a DIFFERENT launcher is discarded ─────────────────────
FOREIGN = {OWNER: "run_some_other_launcher.py",
           "FIXED_ARMS": "STALE_ARM_A,STALE_ARM_B",
           "FIXED_OUT": "stale.csv"}

print("2. foreign owner -- stale arms/out discarded, this launcher wins")
for p in ARM_SET:
    out, snap = run(p, dict(FOREIGN))
    check("%s: stale arms gone" % p, "STALE_ARM" not in snap["FIXED_ARMS"],
          snap["FIXED_ARMS"])
    check("%s: own arms restored" % p, snap["FIXED_ARMS"] == clean[p],
          snap["FIXED_ARMS"])
    check("%s: [ENV] names the other launcher" % p,
          "run_some_other_launcher.py" in out and "[ENV] FIXED_ARMS" in out,
          out[-200:])
    check("%s: stale output name dropped" % p,
          snap["FIXED_OUT"] != "stale.csv", snap["FIXED_OUT"])

# The delegate leaves FIXED_OUT to its caller, so check its banner line instead
# of the env (the [ENV] line quotes the discarded name).
out, snap = run(CELLQ, dict(FOREIGN))
check("%s: stale arms gone" % CELLQ, "STALE_ARM" not in snap["FIXED_ARMS"],
      snap["FIXED_ARMS"])
_banner = [l for l in out.splitlines() if "out  :" in l]
check("%s: banner uses the default, not stale.csv" % CELLQ,
      bool(_banner) and "stale.csv" not in _banner[0], _banner[:1])
check("%s: [ENV] announces the dropped FIXED_OUT" % CELLQ,
      "[ENV] FIXED_OUT" in out, out[-200:])

out, snap = run(V2, dict(FOREIGN))
check("%s: stale arms gone" % V2, "STALE_ARM" not in snap["FIXED_ARMS"],
      snap["FIXED_ARMS"])
check("%s: stale output name dropped" % V2, snap["FIXED_OUT"] != "stale.csv",
      snap["FIXED_OUT"])
check("%s: [ENV] names the other launcher" % V2,
      "run_some_other_launcher.py" in out, out[-200:])

for p in OUT_SETTERS:
    out, snap = run(p, dict(FOREIGN))
    check("%s: stale arms dropped, not kept as its own" % p,
          snap["FIXED_ARMS"] == "", snap["FIXED_ARMS"])
    check("%s: [ENV] announces the dropped FIXED_ARMS" % p,
          "[ENV] FIXED_ARMS" in out, out[-200:])
    check("%s: stale output name never used" % p,
          snap["FIXED_OUT"] != "stale.csv", snap["FIXED_OUT"])

# ── 3. an explicit value from a clean session, or a re-run, is honoured ──────
print("3. caller's own value -- honoured")
for p in ARM_SET:
    out, snap = run(p, {"FIXED_ARMS": "MINE_ARM_A,MINE_ARM_B"})
    check("%s: explicit arms kept" % p,
          snap["FIXED_ARMS"] == "MINE_ARM_A,MINE_ARM_B", snap["FIXED_ARMS"])
    out, snap = run(p, {OWNER: p, "FIXED_ARMS": "RERUN_A,RERUN_B",
                        "FIXED_OUT": "rerun.csv"})
    check("%s: same-owner re-run kept" % p,
          snap["FIXED_ARMS"] == "RERUN_A,RERUN_B", snap["FIXED_ARMS"])

out, snap = run(V2, {"FIXED_OUT": "mine.csv"})
check("%s: explicit output kept" % V2, snap["FIXED_OUT"] == "mine.csv",
      snap["FIXED_OUT"])
out, snap = run(V2, {OWNER: V2, "FIXED_OUT": "rerun.csv",
                     "FIXED_ARMS": "RERUN_A,RERUN_B"})
check("%s: same-owner re-run kept" % V2,
      snap["FIXED_ARMS"] == "RERUN_A,RERUN_B", snap["FIXED_ARMS"])

out, snap = run(OUT_SETTERS[0], {"FIXED_ARMS": "MINE_ARM_A,MINE_ARM_B"})
check("%s: clean-session arms left for the delegate" % OUT_SETTERS[0],
      snap["FIXED_ARMS"] == "MINE_ARM_A,MINE_ARM_B", snap["FIXED_ARMS"])

# ── 4. delegation: the handover must not launder a foreign value ────────────
# Behavioural half of the tail: the caller's own knobs survive the delegate,
# and a foreign arm list does not.
print("4. delegation -- own knobs survive, foreign arms do not")
for p, target in HANDOFF.items():
    steps, snap = chain([p, target], dict(FOREIGN))
    dout = steps[-1][1]
    check("%s -> %s: delegate printed no [ENV]" % (p, target),
          "[ENV]" not in dout, dout[-200:])
    want = clean[p] if p in LADDERS else clean[target]
    check("%s -> %s: arms correct after handover" % (p, target),
          snap["FIXED_ARMS"] == want, snap["FIXED_ARMS"][:80])
    check("%s -> %s: output name not the stale one" % (p, target),
          snap["FIXED_OUT"] != "stale.csv", snap["FIXED_OUT"])

# ── 5. the tail really performs that handoff (static) ───────────────────────
print("5. tail -- hands over, then reclaims")
for p, target in HANDOFF.items():
    src = _source(p)
    tail = src[min(src.index(m) for m in _MARKERS if m in src):]
    check("%s: hands the env over" % p,
          "_os.environ[_ENV_OWNER] = " in tail)
    check("%s: handover names %s" % (p, target),
          ('"%s"' % target) in tail or "_BASE" in tail)
    check("%s: reclaims in a finally" % p,
          "finally:" in tail and "_os.environ[_ENV_OWNER] = _MY_NAME" in tail)

print("")
if fails:
    print("RESULT: %d failure(s)" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("RESULT: 0 failure(s)")
