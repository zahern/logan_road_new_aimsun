"""
pipeline_preflight.py -- OFFLINE pre-flight for run_champion_pipeline.py.

Runs from a NORMAL terminal (no Aimsun, no simulation):

    python pipeline_preflight.py

It answers "will the intended behaviours actually change?" for the layers that
can be proven WITHOUT running the 1.5 h x 55-run sim:

  [A] DISPATCH WIRING (static). Every champion arm that declares a specialised
      decider is cross-checked against the engine `_mode_registry` and
      `_spm.MODE_FLAGS`: the flag must be propagatable (in MODE_FLAGS) AND bound
      to a live, callable decider. This catches the exact class of bug that made
      arms byte-identical (a dead flag -> the arm silently ran the generic path).
      CONTROL_MODE arms (MILP_MPC) are checked for their OR-Tools skip-guard.

  [B] ALGORITHM DIFFERENTIATION (behavioural, stubbed). The NEW / changed
      deciders are driven on IDENTICAL synthetic input and must return DISTINCT
      actions -- proving they are different algorithms, not relabels. Covers the
      Nash bargaining tiers, CENTRALISED, and the generalized-Nash bargaining
      powers.

What this does NOT cover (needs a short in-Aimsun smoke -- see --help notes):
  bus-demand scaling and car-demand resolution are Aimsun-runtime; run one short
  replication (1 seed) to observe those. This script only proves the decision
  layer changes behaviour.

Exit code 0 = all checks pass; 1 = a problem was found (details printed).
"""
import importlib.util as _ilu
import os as _os
import re as _re
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ENGINE = _os.path.join(_HERE, "shared_tsp_engine", "engine.py")
_MODES = _os.path.join(_HERE, "shared_tsp_engine", "specialized_modes.py")
_CHAMP = _os.path.join(_HERE, "champion_search.py")

_PASS, _FAIL, _WARN = [], [], []
def _ok(msg):   _PASS.append(msg); print(f"  [PASS] {msg}")
def _bad(msg):  _FAIL.append(msg); print(f"  [FAIL] {msg}")
def _warn(msg): _WARN.append(msg); print(f"  [WARN] {msg}")


def _load_modes():
    spec = _ilu.spec_from_file_location("_pf_spm", _MODES)
    m = _ilu.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def _parse_registry(engine_src):
    """Extract (flag_name, decider_attr, tag) from the engine _mode_registry."""
    blk = _re.search(r"_mode_registry\s*=\s*\((.*?)\n\s*\)\n", engine_src, _re.S)
    if not blk:
        return []
    out = []
    # (getattr(_spm, 'FLAG', False), _spm.decider / getattr(_spm,'decider',None), 'TAG')
    for m in _re.finditer(
            r"getattr\(_spm,\s*'([A-Z_]+)',\s*False\)\s*,\s*"
            r"(?:getattr\(_spm,\s*'([a-z_]+)'|_spm\.([a-z_]+))"
            r".*?'([A-Z_]+)'\)", blk.group(1), _re.S):
        flag = m.group(1); dec = m.group(2) or m.group(3); tag = m.group(4)
        out.append((flag, dec, tag))
    # also the plain-tuple entries: (_spm.FLAG, _spm.decider, 'TAG')
    for m in _re.finditer(
            r"\(_spm\.([A-Z_]+)\s*,\s*_spm\.([a-z_]+)\s*,\s*'([A-Z_]+)'\)",
            blk.group(1)):
        out.append((m.group(1), m.group(2), m.group(3)))
    return out


def _parse_expected(champ_src):
    """Extract the _EXPECTED_ACTIVE_MODE dict {arm: token/None}."""
    blk = _re.search(r"_EXPECTED_ACTIVE_MODE\s*=\s*\{(.*?)\n\}", champ_src, _re.S)
    if not blk:
        return {}
    out = {}
    for m in _re.finditer(r'"([A-Z_]+)"\s*:\s*(None|"[^"]*"|@?[A-Z_]+)',
                          blk.group(1)):
        k = m.group(1); v = m.group(2)
        out[k] = None if v == "None" else v.strip('"')
    return out


# ── [A] DISPATCH WIRING ──────────────────────────────────────────────────────
def check_wiring(spm):
    print("\n[A] DISPATCH WIRING (static)")
    engine_src = open(_ENGINE, encoding="utf-8").read()
    champ_src = open(_CHAMP, encoding="utf-8").read()
    registry = _parse_registry(engine_src)
    expected = _parse_expected(champ_src)
    mode_flags = set(spm.MODE_FLAGS)

    # tags that an actual arm depends on (token -> registry-tag spelling)
    _tok_to_tag = {"CENTRALIZED": "CENTRALISED"}
    used_tags = {_tok_to_tag.get(t, t) for t in expected.values()
                 if t and not str(t).startswith("@")}

    # 1. every registered decider is callable & its flag is propagatable.
    #    A missing decider is only a FAILURE if an arm actually uses that tag;
    #    an unused dead registry entry is just a warning.
    for flag, dec, tag in registry:
        if not callable(getattr(spm, dec, None)):
            if tag in used_tags:
                _bad(f"registry tag {tag}: decider _spm.{dec} missing but an ARM "
                     f"uses it -> that arm would run generic")
            else:
                _warn(f"registry tag {tag}: decider _spm.{dec} absent (inert -- no "
                      f"arm uses it)")
        elif flag not in mode_flags:
            _bad(f"registry tag {tag}: flag {flag} NOT in _spm.MODE_FLAGS "
                 f"(won't propagate from run_config -> silently generic)")
        else:
            _ok(f"{tag:15s} -> _spm.{dec} (flag {flag} propagatable)")

    # 2. every arm that declares a decider token maps to a live registry entry
    #    (that has a callable decider, per check 1)
    tags_present = {t for (_, _, t) in registry
                    if callable(getattr(spm, dict((tg, d) for _, d, tg in registry)
                                        .get(t, ""), None))}
    for arm, tok in sorted(expected.items()):
        if tok is None:
            _ok(f"arm {arm:16s} generic-by-design (exempt)")
            continue
        if tok.startswith("@"):
            cm = tok[1:]
            if f'strategy": "{cm}"' in champ_src or f"'{cm}'" in champ_src:
                _ok(f"arm {arm:16s} CONTROL_MODE={cm} (checked separately)")
            else:
                _bad(f"arm {arm}: CONTROL_MODE {cm} not found in champion_search")
            continue
        tag = _tok_to_tag.get(tok, tok)
        if tag in tags_present:
            _ok(f"arm {arm:16s} -> token {tok} -> registered decider")
        else:
            _bad(f"arm {arm}: token {tok} has NO registered decider (dead flag)")

    # 3. MILP_MPC OR-Tools skip-guard present (so a missing dep can't abort the run)
    if "_ortools_available()" in champ_src and "SKIP" in champ_src:
        _ok("MILP_MPC OR-Tools skip-guard present (missing dep -> skip, not abort)")
    else:
        _bad("MILP_MPC OR-Tools skip-guard MISSING (missing dep would abort run)")


# ── [B] ALGORITHM DIFFERENTIATION ────────────────────────────────────────────
def _stub(spm, table):
    """A fake controller + eval so deciders can run without Aimsun."""
    spm._log_func = lambda self, msg, **k: None
    def ev(self, at, ap, sigma, nad, eta, wrong_phase=False, remaining_red_s=0.0):
        if at == 'NO_ACTION':
            return (0, 0.0, 0.0, 0.0, 0.0, nad, nad)
        b, c = table.get(at, (0, 0))
        return (0, 0.0, eta, b * (ap / 10.0), c * (ap / 10.0), nad, nad * 0.5)
    spm._dctsp_eval_action = ev
    class S:
        id = 7; BusPhase = 1; BusOcc = 40.0
        config = {'CycleTime': 120.0}; _corridor_coord = None
    return S()


def check_algorithms(spm):
    print("\n[B] ALGORITHM DIFFERENTIATION (behavioural, stubbed)")
    # Nash selector: interior compromise, not an extreme
    fr = [(40, 10), (80, 50), (120, 200)]
    bi, _ = spm._nash_bargain_pick(fr, 1, 1)
    _ok("Nash product picks interior action") if bi == 1 else \
        _bad(f"Nash selector picked {bi}, expected interior (1)")

    # scale invariance (Nash axiom)
    bi2, _ = spm._nash_bargain_pick([(40, 100), (80, 500), (120, 2000)], 1, 1)
    _ok("Nash selection scale-invariant") if bi2 == 1 else \
        _bad(f"Nash not scale-invariant: {bi2}")

    # bargaining power actually shifts the compromise
    s = _stub(spm, {'GE': (400, 120), 'GREEN_REALLOC': (400, 300)})
    spm.NASH_BUS_WEIGHT, spm.NASH_CROSS_WEIGHT = 0.5, 3.0
    r_car = spm.dctsp_nash_bargain(s, 100., 100., 1, 30., 55, 1, 25., 0.0)
    spm.NASH_BUS_WEIGHT, spm.NASH_CROSS_WEIGHT = 3.0, 0.5
    r_bus = spm.dctsp_nash_bargain(s, 100., 100., 1, 30., 55, 1, 25., 0.0)
    spm.NASH_BUS_WEIGHT = spm.NASH_CROSS_WEIGHT = 1.0
    if r_car[1] != r_bus[1] and r_car[0] == 'GE' and r_bus[0] == 'GE':
        _ok(f"Nash bargaining power shifts choice (car->GE_{r_car[1]:.0f}, "
            f"bus->GE_{r_bus[1]:.0f})")
    else:
        _bad(f"bargaining power had no effect: car={r_car[:2]} bus={r_bus[:2]}")

    # Tier-2 corridor iteration changes the outcome vs a single sweep
    occ = 40.0
    F = lambda *r: [(a, p, b, c, b / occ) for (a, p, b, c) in r]
    mk = lambda: F(('GE', 5, 200, 40), ('GE', 10, 400, 80), ('GE', 15, 600, 300))
    proj = lambda j, e, sv: (4.0 * sv * sv if j == 7 else 0.0)
    ch1 = spm._nash_corridor_solve([7, 9], {7: mk(), 9: mk()}, {7: 20., 9: 60.},
                                   proj, occ, w_nb=1.0, max_iter=1, tol=1e-6)
    chN = spm._nash_corridor_solve([7, 9], {7: mk(), 9: mk()}, {7: 20., 9: 60.},
                                   proj, occ, w_nb=1.0, max_iter=10, tol=1e-6)
    if ch1[7] != chN[7]:
        _ok(f"Tier-2 iteration changes outcome (1-sweep idx{ch1[7]} -> "
            f"converged idx{chN[7]})")
    else:
        _bad(f"Tier-2 iteration had no effect: {ch1[7]} == {chN[7]}")

    # CENTRALISED gates: not-delayed / unreachable -> NO_ACTION; delayed -> acts
    s = _stub(spm, {'GE': (400, 120), 'GREEN_REALLOC': (400, 120)})
    class Coord:
        def oncoming_buses(self, j, t, max_eta_s=180.0): return [(1, 10., 40.)]
    s._corridor_coord = Coord()
    r_act = spm.dctsp_centralised(s, 100., 100., 1, 30., 55, current_phase=1,
                                  no_act_delay=25., sigma_in=0.0)
    r_idle = spm.dctsp_centralised(s, 100., 100., 1, 30., 55, current_phase=1,
                                   no_act_delay=1., sigma_in=0.0)
    if r_act[0] != 'NO_ACTION' and r_idle[0] == 'NO_ACTION':
        _ok(f"CENTRALISED acts when delayed ({r_act[0]}), idles when not")
    else:
        _bad(f"CENTRALISED gate broken: delayed={r_act[0]} idle={r_idle[0]}")


def main():
    print("=" * 70)
    print("PIPELINE PRE-FLIGHT (offline -- no Aimsun, no simulation)")
    print("=" * 70)
    spm = _load_modes()
    check_wiring(spm)
    check_algorithms(spm)
    print("\n" + "=" * 70)
    print(f"RESULT: {len(_PASS)} passed, {len(_FAIL)} failed, {len(_WARN)} warnings")
    if _WARN:
        print("WARNINGS (inert -- not run-blocking):")
        for w in _WARN:
            print("  - " + w)
    if _FAIL:
        print("FAILURES:")
        for f in _FAIL:
            print("  - " + f)
        print("=" * 70)
        return 1
    print("All dispatch-wiring and algorithm-differentiation checks PASS.")
    print("The decision layer will change behaviour per arm. Bus/car demand")
    print("still need one short in-Aimsun replication to observe (see header).")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    # NOTE: run from a normal terminal OR the Aimsun Python console. We only
    # raise SystemExit on FAILURE -- a clean pass returns without sys.exit(0),
    # because Aimsun's console surfaces even a successful SystemExit(0) as a
    # "Python Error". A real terminal still ends with exit code 0 on success and
    # 1 on failure (for CI/scripting).
    _rc = main()
    if _rc != 0:
        _sys.exit(_rc)
