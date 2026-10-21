"""check_flag_propagation.py -- catch arm flags that silently never reach the engine.

An arm's reward_overrides key becomes a no-op (-> arms go byte-identical, or an
override is silently ignored, or a flag carries over between arms) UNLESS it is
propagated from run_config.py into the namespace that consumes it. A key is
"propagated" when it is in at least one of:
  * the engine AAPIInit generic whitelist   `for _k in (...): globals()[_k]=_rc_ns2[_k]`
  * a dedicated engine handler               `_rc_ns2.get('KEY' ...)` / `_rc_ns2['KEY']`
  * specialized_modes MODE_FLAGS             (reset+propagated to _spm AND engine
                                              globals each arm; the carry-over cure)

This scans champion_search.py's ARMS (resolving **BASE spreads), then reports any
arm reward_overrides key in NONE of the above. Run from anywhere:
    python -I check_flag_propagation.py
Exit code 1 if any orphan is found (usable as a preflight gate). Companion to
check_flag_coverage.py / check_flag_consumers.py. (added 2026-10-15)
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CS = os.path.join(ROOT, "champion_search.py")
ENG = os.path.join(ROOT, "shared_tsp_engine", "engine.py")
SPM = os.path.join(ROOT, "shared_tsp_engine", "specialized_modes.py")


def _src(p):
    return open(p, encoding="utf-8-sig").read()


def _dict_keys(dnode, bindings):
    """String keys of an ast.Dict, expanding **NAME spreads via `bindings`."""
    ks = set()
    for k, v in zip(dnode.keys, dnode.values):
        if k is None:  # ** spread
            if isinstance(v, ast.Name) and v.id in bindings:
                ks |= bindings[v.id]
        elif isinstance(k, ast.Constant) and isinstance(k.value, str):
            ks.add(k.value)
    return ks


def arms_and_overrides():
    """{arm_name: set(reward_overrides keys)} from champion_search.py ARMS."""
    tree = ast.parse(_src(CS))
    bindings = {}  # module-level  NAME = {..}  dicts, for ** resolution
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            bindings[node.targets[0].id] = _dict_keys(node.value, bindings)
    arms = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "ARMS"
                        for t in node.targets)
                and isinstance(node.value, ast.List)):
            for el in node.value.elts:
                if not isinstance(el, ast.Dict):
                    continue
                name = None
                ro = set()
                for k, v in zip(el.keys, el.values):
                    if (isinstance(k, ast.Constant) and k.value == "name"
                            and isinstance(v, ast.Constant)):
                        name = v.value
                    if (isinstance(k, ast.Constant)
                            and k.value == "reward_overrides"
                            and isinstance(v, ast.Dict)):
                        ro = _dict_keys(v, bindings)
                if name:
                    arms[name] = ro
            break
    return arms


def engine_propagated_keys():
    """Keys engine.py propagates from run_config: generic whitelist tuples that do
    globals()[_k]=_rc_ns2[_k], plus any dedicated _rc_ns2 reference."""
    tree = ast.parse(_src(ENG))
    whitelist = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.For) and isinstance(node.target, ast.Name)
                and node.target.id == "_k" and isinstance(node.iter, ast.Tuple)):
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
            if "_rc_ns2" in body and "globals" in body:
                for e in node.iter.elts:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        whitelist.add(e.value)
    src = _src(ENG)
    refs = set(re.findall(r"_rc_ns2\.get\(\s*['\"]([A-Za-z0-9_]+)['\"]", src))
    refs |= set(re.findall(r"_rc_ns2\[\s*['\"]([A-Za-z0-9_]+)['\"]\s*\]", src))
    refs |= set(re.findall(r"['\"]([A-Za-z0-9_]+)['\"]\s+in\s+_rc_ns2", src))
    return whitelist, refs


def mode_flags():
    """specialized_modes MODE_FLAGS list (reset+propagated to _spm & engine)."""
    tree = ast.parse(_src(SPM))
    mf = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "MODE_FLAGS"
                        for t in node.targets)
                and isinstance(node.value, ast.List)):
            for e in node.value.elts:
                if isinstance(e, ast.Constant) and isinstance(e.value, str):
                    mf.add(e.value)
    return mf


def main():
    arms = arms_and_overrides()
    whitelist, refs = engine_propagated_keys()
    mf = mode_flags()
    propagated = whitelist | refs | mf
    print("flag-propagation audit (%d arms)" % len(arms))
    print("  engine generic-whitelist keys : %d" % len(whitelist))
    print("  engine dedicated _rc_ns2 refs : %d" % len(refs))
    print("  SPM MODE_FLAGS keys           : %d" % len(mf))
    print()
    orphans = {}
    for name in sorted(arms):
        bad = sorted(k for k in arms[name] if k and k not in propagated)
        if bad:
            orphans[name] = bad
    if not orphans:
        print("OK: every arm reward_overrides key propagates.")
        return 0
    print("ORPHAN keys (set by an arm but never propagated -> override ignored / "
          "byte-identical risk):")
    # Group arms by identical orphan set for a compact report.
    by_set = {}
    for name, bad in orphans.items():
        by_set.setdefault(tuple(bad), []).append(name)
    for bad, names in sorted(by_set.items(), key=lambda kv: -len(kv[1])):
        print("  %s" % list(bad))
        for n in sorted(names):
            print("      %s" % n)
    print("\nFIX: give each a module default in specialized_modes.py AND add it to "
          "MODE_FLAGS (engine-read or SPM-read), or add a dedicated _rc_ns2 handler "
          "in engine.py AAPIInit.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
