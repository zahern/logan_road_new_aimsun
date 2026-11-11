"""Add GAME_CTM2_ROLLOUT: a shared 2-hop network CTM rollout for the block term.

Replaces the scalar per-phase block (_phase_downstream_block: worst downstream
jam fraction RIGHT NOW) with what the receiving links will look like over
GAME_CTM2_HORIZON_S under the junction's CURRENT plan, simulated as a small
networked CTM over this junction's approaches (hop 0), their turning TO
sections (hop 1) and the links those discharge into (hop 2).

ONE rollout per decision, shared by every candidate action: downstream
receiving capacity is a property of the state and the plan, not of the action,
and the block has to stay consistent across candidates or the game compares
them against different cascades.

Flag off (default) => byte-identical behaviour to today.
Empty subnet / any failure => {} => caller keeps out_cap_frac = 1.0.

Three edits, each anchored and counted; refuses to run twice.
"""
import io
import sys

PATH = "shared_tsp_engine/engine.py"

ADJ = [

    "def _turning_adjacency():",
    '    """{from_section: set(to_section)} from the network\'s turning table.',
    "",
    "    Session-once. Walks every junction's turns through the AAPI turning",
    "    primitives (AKIInfNetNbTurnsInNode / AKIInfNetGet{Origin,Destination}",
    "    SectionInTurn), i.e. the network's own connection table -- under SUMO",
    "    that table is built from kg.net.xml <connection tl= linkIndex= from=",
    "    to=>. This is the GLOBAL downstream map a per-junction controller cannot",
    "    otherwise see, and it is what makes a 2-hop subnet possible.",
    "",
    "    Returns {} when nothing resolves (callers then keep the 1-hop scalar",
    "    path). Never raises.",
    "    \"\"\"",
    "    _c = globals().get('_TURN_ADJ_CACHE')",
    "    if isinstance(_c, dict) and _c:",
    "        return _c",
    "    _adj = {}",
    "    try:",
    "        try:",
    "            _jids = list(ANGConnGetObjectIdByType('junction'))",
    "        except Exception:",
    "            _jids = []",
    "        for _j in _jids:",
    "            try:",
    "                _nt = int(AKIInfNetNbTurnsInNode(int(_j)))",
    "            except Exception:",
    "                _nt = 0",
    "            for _ti in range(max(_nt, 0)):",
    "                try:",
    "                    _a = int(AKIInfNetGetOriginSectionInTurn(int(_j), _ti))",
    "                    _b = int(AKIInfNetGetDestinationSectionInTurn(int(_j), _ti))",
    "                except Exception:",
    "                    continue",
    "                if _a > 0 and _b > 0 and _a != _b:",
    "                    _adj.setdefault(int(_a), set()).add(int(_b))",
    "    except Exception:",
    "        _adj = {}",
    "    if _adj:",
    "        try:",
    "            globals()['_TURN_ADJ_CACHE'] = _adj",
    "        except Exception:",
    "            pass",
    "    return _adj",
]

ROLLOUT = [
    "    def _ctm2_rollout_block(self, ring, cur, rem, greens):",
    '        """{phase: downstream block 0..1} from a SHARED 2-hop CTM rollout.',
    "",
    "        One rollout of the current plan per decision, read out for every",
    "        phase and reused by every candidate action (GAME_CTM2_ROLLOUT).",
    "",
    "        Subnet: this junction's approaches (hop 0), their turning TO sections",
    "        (hop 1) and the sections those discharge into (hop 2), from",
    "        _turning_adjacency() -- the network's own connection table. Sections",
    "        are modelled at section level (vehicles vs jam storage); hop 0 -> 1",
    "        is signal-gated by the plan's green timeline, hop 1 -> 2 flows free.",
    "        Cell state seeds from the LIVE counts, so an empty subnet returns {}",
    "        and the caller keeps out_cap_frac = 1.0.",
    "",
    "        Costs ~1 ms: 30 steps x ~30 sections. Never raises.",
    "        \"\"\"",
    "        try:",
    "            _ring = [int(p) for p in (ring or [])]",
    "            if not _ring:",
    "                return {}",
    "            _po = self._phase_origin_sections() or {}",
    "            if not _po:",
    "                return {}",
    "            _tt = self._phase_turn_targets() or {}",
    "            if not _tt:",
    "                _tt = self._phase_origin_dests() or {}",
    "            _adj = _turning_adjacency() or {}",
    "            if not _adj:",
    "                return {}",
    "            _dt = float(globals().get('CBQL_CTM_DT_S', 2.0) or 2.0)",
    "            _h = float(globals().get('GAME_CTM2_HORIZON_S', 60.0) or 60.0)",
    "            _steps = max(1, int(round(_h / max(_dt, 1e-6))))",
    "            _orig = set()",
    "            _hop1 = set()",
    "            for _p in _ring:",
    "                _orig |= set(int(s) for s in (_po.get(_p) or []))",
    "                _hop1 |= set(int(t) for t in (_tt.get(_p) or []))",
    "            if not _orig:",
    "                return {}",
    "            _hop2 = set()",
    "            for _t in _hop1:",
    "                _hop2 |= set(int(v) for v in (_adj.get(int(_t)) or []))",
    "            _sub = sorted(_orig) + [s for s in sorted(_hop1) if s not in _orig]",
    "            _sub += [s for s in sorted(_hop2 - _orig - _hop1)][:24]",
    "            _n = {}",
    "            _stor = {}",
    "            _qs = {}",
    "            for _s in _sub:",
    "                try:",
    "                    _g = self._cbql_ctm_geom(int(_s))",
    "                    _lanes = max(int(getattr(_g, 'lanes', 1) or 1), 1)",
    "                    _len = max(float(getattr(_g, 'length_m', 0.0) or 0.0), 1.0)",
    "                    _qsat = float(getattr(_g, 'q_sat_vph_lane', 1800.0) or 1800.0)",
    "                except Exception:",
    "                    continue",
    "                _stor[_s] = max(_len * _lanes / 7.0, 1.0)",
    "                _qs[_s] = max(_qsat * _lanes / 3600.0 * _dt, 1e-6)",
    "                try:",
    "                    _n[_s] = float(max(int(AKIVehStateGetNbVehiclesSection(int(_s), False)), 0))",
    "                except Exception:",
    "                    _n[_s] = 0.0",
    "            if not _n or sum(_n.values()) <= 0.0:",
    "                return {}",
    "            _serving = {}",
    "            for _p in _ring:",
    "                for _s in (_po.get(_p) or []):",
    "                    _serving.setdefault(int(_s), set()).add(int(_p))",
    "            _gseq = None",
    "            try:",
    "                if int(cur) in _ring:",
    "                    _tl = _ctm2.action_timeline(",
    "                        'NA', 0.0, _ring, int(cur), float(rem or 0.0),",
    "                        {int(p): float((greens or {}).get(p, 0.0))",
    "                         for p in _ring},",
    "                        -1,",
    "                        float(globals().get('GAME_CTM2_IG_S', 5.0) or 5.0), _h)",
    "                    if _tl:",
    "                        _gseq = _ctm2.green_steps(_tl, _ring, _h, _dt)",
    "            except Exception:",
    "                _gseq = None",
    "            if not _gseq:",
    "                _gseq = {int(p): [True] * _steps for p in _ring}",
    "            _nsub = set(_n)",
    "            _peak = {s: 0.0 for s in _n}",
    "            for _k in range(_steps):",
    "                _moves = []",
    "                for _s in list(_n):",
    "                    _outs = [t for t in (_adj.get(int(_s)) or []) if t in _nsub]",
    "                    if not _outs:",
    "                        continue",
    "                    if _s in _orig:",
    "                        _go = False",
    "                        for _p in _serving.get(_s, ()):",
    "                            _seq = _gseq.get(int(_p)) or []",
    "                            if _k < len(_seq) and _seq[_k]:",
    "                                _go = True",
    "                                break",
    "                        if not _go:",
    "                            continue",
    "                    _d = min(_n[_s], _qs.get(_s, 0.0))",
    "                    if _d <= 0.0:",
    "                        continue",
    "                    _moves.append((_s, _outs, _d / float(len(_outs))))",
    "                for _s, _outs, _share in _moves:",
    "                    for _t in _outs:",
    "                        _sp = _stor[_t] - _n[_t]",
    "                        if _sp <= 0.0:",
    "                            continue",
    "                        _mv = min(_share, _sp)",
    "                        if _mv <= 0.0:",
    "                            continue",
    "                        _n[int(_t)] += _mv",
    "                        _n[int(_s)] -= _mv",
    "                for _s in _n:",
    "                    _occ = _n[_s] / max(_stor[_s], 1.0)",
    "                    if _occ > _peak[_s]:",
    "                        _peak[_s] = _occ",
    "            _out = {}",
    "            for _p in _ring:",
    "                _tos = [int(t) for t in (_tt.get(_p) or []) if int(t) in _peak]",
    "                if not _tos:",
    "                    continue",
    "                _out[int(_p)] = min(max(max(_peak[t] for t in _tos), 0.0), 1.0)",
    "            _trace = False",
    "            try:",
    "                _trace = bool(os.environ.get('SPILL_BLOCK_LOG'))",
    "            except Exception:",
    "                _trace = False",
    "            if _out and _trace:",
    "                try:",
    "                    _nl = int(getattr(self, '_spillroll_logged', 0) or 0)",
    "                    if _nl < 4:",
    "                        self._spillroll_logged = _nl + 1",
    "                        log_to_file(\"[SPILLROLL] jct=%s n_sub=%d n_veh=%.0f \"",
    "                                    \"blk=%s\" % (",
    "                                        getattr(self, 'id', '?'), len(_n),",
    "                                        sum(_n.values()),",
    "                                        ','.join('%d:%.2f' % (p, v)",
    "                                                 for p, v in sorted(_out.items()))),",
    "                                    force=True)",
    "                except Exception:",
    "                    pass",
    "            return _out",
    "        except Exception:",
    "            return {}",
]

OLD_BLK = [
    "        _blk = {}",
    "        if _spill:",
    "            for _p in _ring:",
    "                try:",
    "                    _blk[int(_p)] = max(0.0, float(self._phase_downstream_block(int(_p)) or 0.0))",
    "                except Exception:",
    "                    _blk[int(_p)] = 0.0",
]

NEW_BLK = [
    "        _blk = {}",
    "        if _spill:",
    "            if bool(globals().get('GAME_CTM2_ROLLOUT', False)):",
    "                # Shared 2-hop network CTM rollout (GAME_CTM2_ROLLOUT): ONE",
    "                # rollout of the current plan per decision, read out per phase",
    "                # and reused by every candidate. {} => fail open (1.0).",
    "                try:",
    "                    _blk = dict(self._ctm2_rollout_block(",
    "                        _ring, _cur, _rem, _greens) or {})",
    "                except Exception as _swx:",
    "                    _note_swallow('_game_ctm2_payoffs#rollout', _swx)",
    "                    _blk = {}",
    "            else:",
    "                for _p in _ring:",
    "                    try:",
    "                        _blk[int(_p)] = max(0.0, float(self._phase_downstream_block(int(_p)) or 0.0))",
    "                    except Exception:",
    "                        _blk[int(_p)] = 0.0",
]


def main() -> int:
    with io.open(PATH, encoding="utf-8", newline="") as fh:
        src = fh.read()
    if "_ctm2_rollout_block" in src:
        print("ALREADY_PATCHED")
        return 0
    nl = "\r\n" if "\r\n" in src[:4000] else "\n"

    def blk(lines):
        return "".join(l + nl for l in lines)

    adj_anchor = nl.join([
        "def _model_topo():",
        '    """Session-once network topology from the MODEL (PyANGKernel), as a',
    ]) + nl
    adj_new = blk(ADJ) + nl + adj_anchor

    # Insert the rollout method immediately after _phase_downstream_block, whose
    # tail (`return _blk`) is unique because the SPILLBLK trace patch added it.
    roll_anchor = nl.join([
        "            return _blk",
        "        except Exception:",
        "            return 0.0",
    ]) + nl
    roll_new = roll_anchor + nl + blk(ROLLOUT)

    old_blk = blk(OLD_BLK)
    new_blk = blk(NEW_BLK)

    for name, old in (("adjacency", adj_anchor), ("rollout", roll_anchor),
                      ("payoff", old_blk)):
        c = src.count(old)
        print("%-10s anchor_matches=%d" % (name, c))
        if c != 1:
            print("REFUSING: %s anchor is not unique" % name)
            return 1

    out = src.replace(adj_anchor, adj_new, 1)
    out = out.replace(roll_anchor, roll_new, 1)
    out = out.replace(old_blk, new_blk, 1)
    with io.open(PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    print("PATCHED size %d -> %d" % (len(src), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
