"""Add the max_phases / worst_vs_sum / max_sec counter to Aimsun's game-side
marginal-competitor path.

WHY: on SUMO the flag was live (5076 payoff evaluations) but inert --
max_phases=1 over up to 9 competing sections, so min() over one key is
identically the sum.  A null A/B there was arithmetic, not evidence.  Aimsun
had the same grouping and NO counter, so a null Aimsun run would be just as
ambiguous.  This adds the counter and routes it through engine.py's log sink,
because in Aimsun a print() from ctm_twoclass does not reach the run log.

SEMANTICS: max_phases counts competing phases with NON-ZERO loss.  A phase can
have a section present and still contribute exactly 0.0 pax.s (its queue clears
inside the horizon either way); counting those would report "several phases"
while min() still equals the sum -- the exact ambiguity this is meant to
remove.  gap (= sum - worst) is the direct proof: gap 0.0 means the flag cannot
change any decision.

Idempotent, including the refinement pass on an already-patched tree.
Backups: <file>.bak_margdiag_<stamp>.

    python _patch_aimsun_marg_diag.py            # patch + gate
    python _patch_aimsun_marg_diag.py --dry-run  # report only

RULE 2: Aimsun caches imported modules -- quit Aimsun fully and relaunch before
the build stamp below can be trusted.
"""
import argparse
import importlib.util
import os
import py_compile
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
CTM = os.path.join(ROOT, "shared_tsp_engine", "ctm_twoclass.py")
ENG = os.path.join(ROOT, "shared_tsp_engine", "engine.py")
STAMP_OLD = "2026-11-11T0100-game-ctm2-marginal-competitor"
STAMP_NEW = "2026-11-11T0100-game-ctm2-marginal-competitor-diag"

HELPER = '''# GAME_MARGINAL_DIAG: how often the marginal-competitor cost can differ from
# the sum.  Where every non-main approach feeds the SAME competing phase --
# or where the extra phases carry exactly zero loss -- min() over the phase
# totals is identically the sum, so the flag can only be a no-op there.  This
# counter is what separates a null A/B from an inert flag.
_MARG_DIAG = {"calls": 0, "multi": 0, "maxph": 0, "gap": 0.0, "maxsec": 0}
_MARG_PENDING = []


def _marg_diag_note(nph, worst_saved, cc, nsec=0):
    """Record one marginal-cost evaluation (one ACTION, not one junction).

    nph  competing phases with NON-ZERO loss (only when two or more of them
         carry loss can min() differ from the sum);  nsec  non-main sections
         priced;  worst_saved  pax.s of the worst phase (the cost charged);
    cc  pax.s summed over every non-main section (what the flag replaces).
    Queues a line every 25th call; engine.py drains it (Aimsun's print() does
    not reach the run log)."""
    d = _MARG_DIAG
    d["calls"] += 1
    if nph > 1:
        d["multi"] += 1
    if nph > d["maxph"]:
        d["maxph"] = nph
    if nsec > d["maxsec"]:
        d["maxsec"] = nsec
    d["gap"] += (cc - worst_saved)
    if d["calls"] % 25 == 1:
        _MARG_PENDING.append(
            "[GAME_MARGINAL] calls=%d multi_phase=%d max_phases=%d "
            "worst_vs_sum=%+.1f pax.s max_sec=%d"
            % (d["calls"], d["multi"], d["maxph"], d["gap"], d["maxsec"]))


def drain_marginal_diag():
    """Return and clear the counter lines queued since the last drain."""
    out = list(_MARG_PENDING)
    del _MARG_PENDING[:]
    return out


def marginal_diag():
    """Final snapshot, for a one-line summary at the end of a run."""
    d = _MARG_DIAG
    return ("calls=%d multi_phase=%d max_phases=%d worst_vs_sum=%+.1f pax.s "
            "max_sec=%d" % (d["calls"], d["multi"], d["maxph"], d["gap"],
                            d["maxsec"]))


'''

ENGINE_OLD = '''        if bool(globals().get('SIDE_COST_MARGINAL_COMPETITOR', False)) \\
                and not getattr(self, '_game_marginal_logged', False):
            self._game_marginal_logged = True
            log_to_file("[GAME_MARGINAL] CTM2 game cross-cost = WORST single "
                        "competing phase (SIDE_COST_MARGINAL_COMPETITOR on), "
                        "not the sum over all non-main approaches", force=True)
        return _ctm2.game_payoffs(
            _snap, _ring, _cur, _rem, _greens,
            int(getattr(self, 'BusPhase', -1) or -1), list(actions),
            intergreen=float(globals().get('GAME_CTM2_IG_S',
                                           globals().get('INS_INTERGREEN_S', 5.0)) or 5.0),
            horizon=float(globals().get('GAME_CTM2_HORIZON_S', 60.0) or 60.0),
            dt=_dt, bus_pce=float(globals().get('CBQL_CTM_BUS_PCE', 2.0) or 2.0),
            bus_occ=float(getattr(self, 'BusOcc', 40.0) or 40.0),
            car_occ=float(getattr(self, 'CarOcc', 1.5) or 1.5), lead=_lead,
            cross_mult=float(globals().get('GAME_CROSS_STARVE_MULT', 1.0) or 1.0),
            marginal=bool(globals().get('SIDE_COST_MARGINAL_COMPETITOR', False)))
'''

ENGINE_NEW = '''        _gmarg = bool(globals().get('SIDE_COST_MARGINAL_COMPETITOR', False))
        if _gmarg and not getattr(self, '_game_marginal_logged', False):
            self._game_marginal_logged = True
            log_to_file("[GAME_MARGINAL] CTM2 game cross-cost = WORST single "
                        "competing phase (SIDE_COST_MARGINAL_COMPETITOR on), "
                        "not the sum over all non-main approaches", force=True)
        _pay = _ctm2.game_payoffs(
            _snap, _ring, _cur, _rem, _greens,
            int(getattr(self, 'BusPhase', -1) or -1), list(actions),
            intergreen=float(globals().get('GAME_CTM2_IG_S',
                                           globals().get('INS_INTERGREEN_S', 5.0)) or 5.0),
            horizon=float(globals().get('GAME_CTM2_HORIZON_S', 60.0) or 60.0),
            dt=_dt, bus_pce=float(globals().get('CBQL_CTM_BUS_PCE', 2.0) or 2.0),
            bus_occ=float(getattr(self, 'BusOcc', 40.0) or 40.0),
            car_occ=float(getattr(self, 'CarOcc', 1.5) or 1.5), lead=_lead,
            cross_mult=float(globals().get('GAME_CROSS_STARVE_MULT', 1.0) or 1.0),
            marginal=_gmarg)
        # GAME_MARGINAL_DIAG: the payoff evaluator queues a counter line every
        # 25th action.  Aimsun's print() does not reach the run log, so drain
        # it through the engine's own sink.  No-op when the flag is off.
        if _gmarg:
            _drain = getattr(_ctm2, 'drain_marginal_diag', None)
            if _drain is not None:
                for _gml in _drain():
                    log_to_file(_gml, force=True)
        return _pay
'''

ART = "def game_payoffs(sec_snap, ring, cur, rem, greens, bus_phase, actions,\n"

BRANCH_OLD = ("            _worst_saved = min(_loss_by_phase.values()) "
              "if _loss_by_phase else cc\n"
              "            C = max(0.0, -_worst_saved) * cross_mult\n")
BRANCH_NEW = ("            _worst_saved = min(_loss_by_phase.values()) "
              "if _loss_by_phase else cc\n"
              "            _nz = [_v for _v in _loss_by_phase.values()\n"
              "                   if abs(_v) > 1e-9]\n"
              "            _marg_diag_note(len(_nz), _worst_saved, cc, len(_cross))\n"
              "            C = max(0.0, -_worst_saved) * cross_mult\n")

# refinement of the first cut, which counted phases that merely exist
CALL_OLD = ("            _marg_diag_note(len(_loss_by_phase), _worst_saved, cc,\n"
            "                            len(_cross))\n")
CALL_NEW = ("            _nz = [_v for _v in _loss_by_phase.values()\n"
            "                   if abs(_v) > 1e-9]\n"
            "            _marg_diag_note(len(_nz), _worst_saved, cc, len(_cross))\n")
DOC_OLD = "    nph  competing phases carrying loss;  nsec  non-main sections priced;\n"
DOC_NEW = ("    nph  competing phases with NON-ZERO loss (only when two or more\n"
           "         of them carry loss can min() differ from the sum);\n"
           "    nsec  non-main sections priced;\n")


def rd(p):
    raw = open(p, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        raw = raw[3:]
    t = raw.decode("utf-8")
    nl = "\r\n" if "\r\n" in t else "\n"
    t = t.replace("\r\n", "\n")
    if "\r" in t:
        raise SystemExit("lone CR in %s -- refusing to rewrite" % p)
    return t, nl, bom


def wr(p, t, nl, bom):
    body = t.replace("\n", nl).encode("utf-8")
    open(p, "wb").write((b"\xef\xbb\xbf" if bom else b"") + body)


def bak(p):
    s = p + ".bak_margdiag_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(p, s)
    return s


def patch_ctm(dry):
    t, nl, bom = rd(CTM)
    if "_MARG_DIAG = {" in t:
        if "_nz = [_v for _v in _loss_by_phase.values()" in t:
            print("ctm_twoclass: already patched and refined")
            return False
        if t.count(CALL_OLD) != 1:
            raise SystemExit("refine anchor count %d (expected 1)"
                             % t.count(CALL_OLD))
        if dry:
            print("ctm_twoclass: WOULD refine the counter to non-zero phases")
            return False
        s = bak(CTM)
        t = t.replace(CALL_OLD, CALL_NEW, 1).replace(DOC_OLD, DOC_NEW, 1)
        wr(CTM, t, nl, bom)
        print("ctm_twoclass: refined to non-zero phases  (backup %s)"
              % os.path.basename(s))
        return True
    if t.count(ART) != 1 or t.count(BRANCH_OLD) != 1:
        raise SystemExit("ctm_twoclass anchors: %d / %d (expected 1 / 1)"
                         % (t.count(ART), t.count(BRANCH_OLD)))
    if dry:
        print("ctm_twoclass: WOULD insert helper (%d chars) + counting call"
              % len(HELPER))
        return False
    s = bak(CTM)
    t = t.replace(ART, HELPER + ART, 1).replace(BRANCH_OLD, BRANCH_NEW, 1)
    wr(CTM, t, nl, bom)
    print("ctm_twoclass: patched  (backup %s)" % os.path.basename(s))
    return True


def patch_eng(dry):
    t, nl, bom = rd(ENG)
    if "drain_marginal_diag" in t:
        print("engine: already patched")
        return False
    if t.count(ENGINE_OLD) != 1:
        raise SystemExit("engine anchor count %d (expected 1)"
                         % t.count(ENGINE_OLD))
    if dry:
        print("engine: WOULD capture _gmarg, drain the counter into log_to_file")
        return False
    s = bak(ENG)
    t = t.replace(ENGINE_OLD, ENGINE_NEW, 1)
    n = t.count(STAMP_OLD)
    t = t.replace(STAMP_OLD, STAMP_NEW)
    wr(ENG, t, nl, bom)
    print("engine: patched, %d build stamp(s) -> %s  (backup %s)"
          % (n, STAMP_NEW, os.path.basename(s)))
    return True


def gates():
    for f in (CTM, ENG):
        py_compile.compile(f, doraise=True)
        print("compile ok  %s" % os.path.basename(f))

    spec = importlib.util.spec_from_file_location("ctm_diag", CTM)
    m = importlib.util.module_from_spec(spec)
    sys.modules["ctm_diag"] = m
    spec.loader.exec_module(m)

    def geom():
        return m.ApproachGeom(length_m=140.0, lanes=1, dt_s=2.0)

    gA, gB, gC = geom(), geom(), geom()
    # phase 1 carries the bus; phases 2 and 3 BOTH queue, so both lose real
    # car delay when the bus phase is extended -- the only configuration in
    # which worst-phase and sum can differ.
    snap = {10: (gA, m.seed_cells(gA, [(3, False), (8, False), (12, True)]),
                 300.0, (1,)),
            20: (gB, m.seed_cells(gB, [(2, False), (5, False), (8, False),
                                       (11, False), (14, False)]), 300.0, (2,)),
            30: (gC, m.seed_cells(gC, [(2, False), (5, False), (7, False),
                                       (9, False), (12, False)]), 300.0, (3,))}
    ring, greens = [1, 2, 3], {1: 20.0, 2: 30.0, 3: 20.0}
    # INS is the discriminating action on a 3-phase ring: it displaces BOTH
    # downstream phases, so worst-phase and sum genuinely differ.  GE only
    # compresses the NEXT phase (phase 3 keeps its absolute window), so GE and
    # ER are no-ops for this flag -- asserted below, not assumed.
    acts = [('INS', 8.0)]
    kw = dict(intergreen=5.0, horizon=60.0)

    before = m._MARG_DIAG["calls"]
    off1 = m.game_payoffs(snap, ring, 1, 2.0, greens, 1, acts, **kw)
    off2 = m.game_payoffs(snap, ring, 1, 2.0, greens, 1, acts, **kw)
    assert off1 == off2, "flag off must stay deterministic"
    assert m._MARG_DIAG["calls"] == before, "flag off must not touch the counter"
    print("flag off: %r, counter untouched (%d)"
          % (off1[0], m._MARG_DIAG["calls"]))

    on = m.game_payoffs(snap, ring, 1, 2.0, greens, 1, acts, marginal=True, **kw)
    d = m._MARG_DIAG
    print("flag on : %r" % (on[0],))
    print("counter : calls=%d multi=%d maxph=%d gap=%+.1f maxsec=%d"
          % (d["calls"], d["multi"], d["maxph"], d["gap"], d["maxsec"]))
    assert d["maxph"] == 2, ("expected 2 loss-carrying competing phases", d)
    assert d["multi"] == 1, ("expected 1 multi-phase evaluation", d)
    assert d["maxsec"] == 2, ("expected 2 non-main sections", d)
    assert d["gap"] < -50.0, ("phases must each carry real loss", d)
    assert on[0][1] < off1[0][1] * 0.75, ("worst-phase cost must sit materially "
                                          "below the sum", on[0], off1[0])
    print("cost    : worst-phase %.1f  <  sum %.1f pax.s"
          % (on[0][1], off1[0][1]))

    lines = m.drain_marginal_diag()
    assert len(lines) == 1, lines
    assert "max_phases=2" in lines[0] and "max_sec=2" in lines[0], lines
    assert m.drain_marginal_diag() == [], "drain must clear"
    print("drained : %s" % lines[0])
    print("summary : %s" % m.marginal_diag())

    snap1 = {10: snap[10], 20: snap[20]}
    one_on = m.game_payoffs(snap1, [1, 2], 1, 2.0, {1: 20.0, 2: 30.0}, 1, acts,
                            marginal=True, **kw)
    one_off = m.game_payoffs(snap1, [1, 2], 1, 2.0, {1: 20.0, 2: 30.0}, 1, acts,
                             **kw)
    assert one_on == one_off, ("one competing phase must be EXACTLY the sum",
                               one_on, one_off)
    print("1 phase : worst == sum exactly -> %r" % (one_on[0],))

    # The SUMO situation in miniature: an extension compresses only the next
    # phase, and an early return leaves both phases better off (C clamps to 0).
    # In both cases the flag must leave the payoff untouched.
    for _at, _ap in (('GE', 8.0), ('ER', 4.0)):
        _s = m.game_payoffs(snap, ring, 1, 2.0, greens, 1, [(_at, _ap)], **kw)
        _mg = m.game_payoffs(snap, ring, 1, 2.0, greens, 1, [(_at, _ap)],
                             marginal=True, **kw)
        assert _s == _mg, ("%s must be a no-op for this flag" % _at, _s, _mg)
        print("%-3s     : no-op on a 3-phase ring (worst == sum) -> %r"
              % (_at, _s[0]))

    # a phase that exists but carries EXACTLY zero loss must not be counted as
    # one that can make min() differ -- the reading that misled the first gate.
    # An empty section is priced (it is non-main) yet saves 0.0 pax.s.
    gD = geom()
    snap2 = {10: snap[10], 20: snap[20],
             40: (gD, m.seed_cells(gD, []), 300.0, (3,))}
    m._MARG_DIAG.update({"calls": 0, "multi": 0, "maxph": 0, "gap": 0.0,
                         "maxsec": 0})
    m.game_payoffs(snap2, ring, 1, 2.0, greens, 1, [('GE', 8.0)],
                   marginal=True, **kw)
    d2 = m._MARG_DIAG
    assert d2["maxsec"] == 2, ("2 non-main sections priced", d2)
    assert d2["maxph"] == 1, ("an empty phase-3 section must not count", d2)
    assert d2["gap"] == 0.0, ("worst == sum exactly", d2)
    print("empty ph3: priced (max_sec=%d) but max_phases=%d, gap=%+.1f"
          % (d2["maxsec"], d2["maxph"], d2["gap"]))
    print("ALL GATES PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    changed = patch_ctm(a.dry_run) or patch_eng(a.dry_run)
    if a.dry_run:
        return
    if changed:
        gates()
    else:
        print("nothing to do -- running the gates anyway")
        gates()


if __name__ == "__main__":
    main()
