"""
inspect_methodologies.py -- STANDALONE validator that checks every TSP methodology
in this system is actually WIRED and will run (not silently inert).

Runs with plain Python (NO Aimsun needed) by static analysis of the source, so you
can validate BEFORE burning a multi-hour sweep. It cross-checks, per champion arm:

  1. COMPILE     -- every engine/launcher file imports/compiles.
  2. ENGINE_BUILD-- the stamp is present (the stamp guard needs it).
  3. DECIDERS    -- each mode in engine.py's _mode_registry maps to a dctsp_* that
                    is actually defined in specialized_modes.py.
  4. ARM->DECIDER-- each arm's mode-toggle flag(s) resolve to a real decider (or the
                    reward-TSP / NORMAL baseline path), so no arm dispatches to a
                    dead flag (the "CENTRALISED is a dead flag" / stale-mode class).
  5. FLAG PROP   -- every reward_overrides key will actually reach the engine: it is
                    in specialized_modes.MODE_FLAGS, in engine.py's explicit AAPIInit
                    propagation list, or force-set. Keys in none of those are the
                    "BXT_SOLVER / BXT_BARGAIN never propagated -> inert" bug class.

Output: a per-arm table + PASS/WARN/FAIL summary to the console AND to
inspect_methodologies_report.txt next to this file.

RUN (from a terminal, in the bundle folder):
    python inspect_methodologies.py
It needs no Aimsun and touches nothing -- read-only.
"""

import os as _os
import re as _re
import ast as _ast
import py_compile as _pyc
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ENG = _os.path.join(_HERE, "shared_tsp_engine", "engine.py")
_SPM = _os.path.join(_HERE, "shared_tsp_engine", "specialized_modes.py")
_CS = _os.path.join(_HERE, "champion_search.py")

_LINES = []
def _log(msg=""):
    print(msg)
    _LINES.append(str(msg))

def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


# ── 1. COMPILE ────────────────────────────────────────────────────────────────
def check_compile():
    _log("=" * 78)
    _log("[1] COMPILE -- every engine / launcher file parses")
    _log("=" * 78)
    files = [_ENG, _SPM, _CS,
             _os.path.join(_HERE, "kg", "batch_runner.py"),
             _os.path.join(_HERE, "run_full_pipeline.py")]
    ok = True
    for f in files:
        if not _os.path.isfile(f):
            _log("  MISSING  %s" % f); ok = False; continue
        try:
            _pyc.compile(f, doraise=True)
            _log("  ok       %s" % _os.path.relpath(f, _HERE))
        except Exception as e:
            _log("  FAIL     %s -> %r" % (_os.path.relpath(f, _HERE), e)); ok = False
    return ok


# ── 2. ENGINE_BUILD ───────────────────────────────────────────────────────────
def check_build():
    _log("\n" + "=" * 78)
    _log("[2] ENGINE_BUILD stamp (needed by the engine-stamp guard)")
    _log("=" * 78)
    m = _re.search(r'^ENGINE_BUILD\s*=\s*["\']([^"\']+)["\']', _read(_ENG), _re.M)
    if m:
        _log("  ok       ENGINE_BUILD = %s" % m.group(1)); return True
    _log("  FAIL     no ENGINE_BUILD stamp found in engine.py"); return False


# ── parse: _mode_registry  {MODE_FLAG: (decider_name, tag)} ────────────────────
def parse_mode_registry(eng_src):
    m = _re.search(r'_mode_registry\s*=\s*\((.*?)\n\s*\)', eng_src, _re.S)
    reg = {}
    if not m:
        return reg
    body = m.group(1)
    # each row: (... 'FLAG' ...,  _spm.dctsp_xxx | getattr(_spm,'dctsp_xxx',..), 'TAG')
    for row in _re.finditer(
            r"(?:_spm\.(\w+)|getattr\(_spm,\s*'(\w+)')"       # the mode flag
            r".*?"
            r"(?:_spm\.(dctsp_\w+)|getattr\(_spm,\s*'(dctsp_\w+)')"  # the decider
            r".*?'(\w+)'", body, _re.S):
        flag = row.group(1) or row.group(2)
        decider = row.group(3) or row.group(4)
        tag = row.group(5)
        if flag and decider:
            reg[flag] = (decider, tag)
    return reg


# ── parse: specialized_modes deciders + MODE_FLAGS ─────────────────────────────
def parse_spm(spm_src):
    deciders = set(_re.findall(r'^def\s+(dctsp_\w+)\s*\(', spm_src, _re.M))
    flags = set()
    m = _re.search(r'MODE_FLAGS\s*=\s*\[(.*?)\]', spm_src, _re.S)
    if m:
        flags = set(_re.findall(r"'(\w+)'", m.group(1)))
    # module-level simple flag/const assignments (the known-flag universe)
    defaults = set(_re.findall(r'^([A-Z][A-Z0-9_]+)\s*=', spm_src, _re.M))
    return deciders, flags, defaults


# ── parse: engine.py explicit AAPIInit propagation list + force-set keys ───────
def parse_engine_prop(eng_src):
    explicit = set()
    # the tuple that carries CONTROL_MODE / COORDINATED_TSP
    for m in _re.finditer(r'for\s+_k\s+in\s+\((.*?)\):', eng_src, _re.S):
        if 'COORDINATED_TSP' in m.group(1) or 'CONTROL_MODE' in m.group(1):
            explicit |= set(_re.findall(r"'(\w+)'", m.group(1)))
    forced = set(_re.findall(r"setattr\(_spm,\s*'(\w+)'", eng_src))
    forced |= set(_re.findall(r"globals\(\)\[\s*'(\w+)'\s*\]\s*=", eng_src))
    return explicit, forced


# ── parse: champion_search ARMS (name, strategy, method, reward_overrides) ─────
def parse_arms(cs_src):
    tree = _ast.parse(cs_src)
    for node in _ast.walk(tree):
        if (isinstance(node, _ast.Assign)
                and any(getattr(t, "id", "") == "ARMS" for t in node.targets)
                and isinstance(node.value, (_ast.List, _ast.Tuple))):
            return _collect(node.value)
    return []

def _collect(list_node):
    arms = []
    for el in list_node.elts:
        if not isinstance(el, _ast.Dict):
            continue
        arm = {"name": "?", "strategy": "?", "method": "?", "ov": {}}
        for k, v in zip(el.keys, el.values):
            key = getattr(k, "value", None)
            if key == "name": arm["name"] = getattr(v, "value", "?")
            elif key == "strategy": arm["strategy"] = getattr(v, "value", "?")
            elif key == "method": arm["method"] = getattr(v, "value", "?")
            elif key == "reward_overrides" and isinstance(v, _ast.Dict):
                for kk, vv in zip(v.keys, v.values):
                    kn = getattr(kk, "value", None)
                    if kn is None: continue
                    try: arm["ov"][kn] = _ast.literal_eval(vv)
                    except Exception: arm["ov"][kn] = "<expr>"
        arms.append(arm)
    return arms


def main():
    ok_compile = check_compile()
    ok_build = check_build()

    eng = _read(_ENG); spm = _read(_SPM); cs = _read(_CS)
    registry = parse_mode_registry(eng)
    deciders, mode_flags, spm_defaults = parse_spm(spm)
    explicit, forced = parse_engine_prop(eng)
    arms = parse_arms(cs)

    # [3] DECIDERS exist for every registry mode
    _log("\n" + "=" * 78)
    _log("[3] DECIDER REGISTRY -- every dispatched mode maps to a defined decider")
    _log("=" * 78)
    reg_ok = True
    used_toggles = {f for arm in arms for f in registry if arm["ov"].get(f) is True}
    for flag, (dname, tag) in sorted(registry.items()):
        present = dname in deciders
        used = flag in used_toggles
        if present:
            st, note = "ok", ""
        elif used:
            st, note = "FAIL", "  <- MISSING decider, USED BY AN ARM"; reg_ok = False
        else:
            st, note = "warn", "  <- missing decider (no arm uses it; runtime-guarded)"
        _log("  %-4s %-22s -> %-26s (%s)%s" % (st, flag, dname, tag, note))
    if not registry:
        _log("  WARN   could not parse _mode_registry from engine.py")

    # propagatable universe for flag-prop check
    propagatable = mode_flags | explicit | forced
    # a few keys are structural/positional (written by write_run_config directly)
    propagatable |= {"GLOBAL_REWARD_MODE", "COORDINATED_TSP", "COORDINATION_ALGO",
                     "BUS_PREDICTOR_TYPE", "CONTROL_MODE", "Z4_CONSTRAINT_MODE",
                     "Z4_TOLERANCE_VEH_S", "DCTSP_GREEN_REALLOC_MODE",
                     "GREEN_REALLOC_RECOVER_FRACTION"}

    # mode-toggle flags that select a decider (from the registry)
    mode_toggles = set(registry.keys())

    # [4] + [5] per-arm
    _log("\n" + "=" * 78)
    _log("[4/5] PER-ARM -- decider resolves + every flag will propagate")
    _log("=" * 78)
    n_fail = 0; n_warn = 0
    for arm in arms:
        name = arm["name"]; ov = arm["ov"]
        on_toggles = [f for f in mode_toggles if ov.get(f) is True]
        # resolve path
        if arm["strategy"] == "NORMAL":
            path = "NORMAL (fixed-time baseline)"; dec_ok = True
        elif on_toggles:
            decs = [registry[f][0] for f in on_toggles]
            missing = [d for d in decs if d not in deciders]
            dec_ok = not missing
            path = "decider: " + ",".join("%s(%s)" % (registry[f][1], registry[f][0])
                                          for f in on_toggles)
            if missing:
                path += "  !! MISSING: " + ",".join(missing)
        else:
            # no registry toggle -> reward-TSP Pareto path (valid when GLOBAL_REWARD)
            dec_ok = True
            path = ("reward-TSP (run_reward_tsp / Pareto)"
                    if ov.get("GLOBAL_REWARD_MODE") or arm["strategy"] == "GLOBAL_REWARD"
                    else "reward-TSP (NO mode toggle, NO GLOBAL_REWARD?)")
        # flag propagation
        inert = [k for k in ov if k not in propagatable]
        status = "ok"
        if not dec_ok:
            status = "FAIL"; n_fail += 1
        elif inert:
            status = "WARN"; n_warn += 1
        _log("  [%-4s] %-22s %s" % (status, name, path))
        if inert:
            _log("         may-not-propagate (not in MODE_FLAGS/explicit/forced): %s"
                 % ", ".join(sorted(inert)))

    # [6] decider inventory + unused
    _log("\n" + "=" * 78)
    _log("[6] DECIDER INVENTORY (%d defined in specialized_modes)" % len(deciders))
    _log("=" * 78)
    used = {d for (d, _t) in registry.values()}
    _log("  dispatched : " + ", ".join(sorted(used)) or "  (none)")
    _log("  defined-but-not-in-registry : "
         + (", ".join(sorted(deciders - used)) or "(none)"))

    # ── summary ──
    _log("\n" + "=" * 78)
    _log("SUMMARY")
    _log("=" * 78)
    _log("  compile ......... %s" % ("PASS" if ok_compile else "FAIL"))
    _log("  engine_build .... %s" % ("PASS" if ok_build else "FAIL"))
    _log("  decider registry  %s" % ("PASS" if reg_ok else "FAIL"))
    _log("  arms ............ %d  (FAIL=%d, WARN=%d)" % (len(arms), n_fail, n_warn))
    overall = ok_compile and ok_build and reg_ok and n_fail == 0
    _log("  OVERALL ......... %s" % ("PASS" if overall else "FAIL (see above)"))
    if n_warn:
        _log("  NOTE: WARN = a reward_overrides key is not in any known propagation")
        _log("        path. Either it is applied another way, or it is INERT -- add")
        _log("        it to specialized_modes.MODE_FLAGS (the fix for the BXT_SOLVER /")
        _log("        BXT_BARGAIN carry-over class of bug).")

    rep = _os.path.join(_HERE, "inspect_methodologies_report.txt")
    try:
        with open(rep, "w", encoding="utf-8") as fh:
            fh.write("\n".join(_LINES) + "\n")
        _log("\n  report written -> %s" % rep)
    except Exception as e:
        _log("\n  (could not write report: %r)" % e)
    return 0 if overall else 1


if __name__ == "__main__":
    _sys.exit(main())
