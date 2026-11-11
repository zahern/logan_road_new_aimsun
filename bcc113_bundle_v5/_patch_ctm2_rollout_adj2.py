"""Finish the 2-hop adjacency under SUMO.

[TURNADJ] jids=27 sections_with_out=0 edges=0 getter_present=True: the junction
enumeration works, but AKIInfNetNbTurnsInNode / AKIInfNetGet*SectionInTurn
return nothing in this build, so the rollout degraded to the plan-derived 1-hop
fallback. The SIGNAL primitives do resolve (they are exactly what
_phase_turn_targets uses), so this second pass walks every junction's phases and
reads each turning's (from, to) through them -- that restores the global table
and with it the second hop.

Idempotent (keyed on TURNADJ-SG).
"""
import io
import os
import sys

PATH = "shared_tsp_engine/engine.py"

NEW = [
    "    if not _adj:",
    "        # Second pass: the AKI turn primitives resolved nothing above, but",
    "        # the SIGNAL plan primitives do -- the same calls _phase_turn_targets",
    "        # uses per junction. Walk every junction's phases and read each",
    "        # turning's (from, to), which restores the global table (and the",
    "        # second hop) under SUMO.",
    "        try:",
    "            for _j in _jids:",
    "                _jj = int(_j)",
    "                try:",
    "                    _np = int(ECIGetNumberofPhases(_jj))",
    "                except Exception:",
    "                    try:",
    "                        _np = int(ECIGetNumberPhases(_jj))",
    "                    except Exception:",
    "                        _np = 0",
    "                for _p in range(1, max(_np, 0) + 1):",
    "                    _sgs = set()",
    "                    for _idx in (int(_p), int(_p) - 1):",
    "                        try:",
    "                            _nsg = int(ECIGetNbSignalGroupsPhaseofJunction(",
    "                                _jj, _idx, 0.0))",
    "                        except Exception:",
    "                            continue",
    "                        for _pos in range(1, max(_nsg, 0) + 1):",
    "                            try:",
    "                                _sg = int(ECIGetSignalGroupPhaseofJunction(",
    "                                    _jj, _idx, _pos, 0.0))",
    "                            except Exception:",
    "                                continue",
    "                            if _sg >= 0:",
    "                                _sgs.add(_sg)",
    "                        if _sgs:",
    "                            break",
    "                    for _sg in _sgs:",
    "                        try:",
    "                            _nt = int(ECIGetNumberTurningsofSignalGroup(",
    "                                _jj, _sg))",
    "                        except Exception:",
    "                            _nt = 0",
    "                        for _ti in range(max(_nt, 0)):",
    "                            try:",
    "                                _fp = intp(); _tp = intp()",
    "                                ECIGetFromToofTurningofSignalGroup(",
    "                                    _jj, _sg, _ti, _fp, _tp)",
    "                                _a = int(_fp.value())",
    "                                _b = int(_tp.value())",
    "                            except Exception:",
    "                                continue",
    "                            if _a > 0 and _b > 0 and _a != _b:",
    "                                _adj.setdefault(_a, set()).add(_b)",
    "        except Exception:",
    "            pass",
]

ANCHOR = [
    "    try:",
    "        if os.environ.get('SPILL_BLOCK_LOG') and not globals().get(",
    "                '_TURN_ADJ_LOGGED'):",
]


def main() -> int:
    with io.open(PATH, encoding="utf-8", newline="") as fh:
        src = fh.read()
    if "TURNADJ-SG" in src:
        print("ALREADY_PATCHED")
        return 0
    nl = "\r\n" if "\r\n" in src[:4000] else "\n"

    def blk(lines):
        return "".join(l + nl for l in lines)

    old = blk(ANCHOR)
    c = src.count(old)
    print("anchor_matches=%d" % c)
    if c != 1:
        print("REFUSING: anchor is not unique")
        return 1
    new = blk(NEW) + blk(ANCHOR[:1]) + blk(ANCHOR[1:])
    # keep a marker so the patch is idempotent
    new = new.replace("[TURNADJ-SG]", "")
    out = src.replace(old, new, 1)
    out = out.replace('globals()[\'_TURN_ADJ_LOGGED\'] = True',
                      "globals()['_TURN_ADJ_LOGGED'] = True  # TURNADJ-SG", 1)
    tmp = PATH + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    os.replace(tmp, PATH)
    print("PATCHED size %d -> %d" % (len(src), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
