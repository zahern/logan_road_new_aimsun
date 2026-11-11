"""Give the rollout a working adjacency under SUMO, and say why it is 1-hop.

[SPILLROLL-NA] why=no turning adjacency showed that _turning_adjacency() --
which walks every junction through ANGConnGetObjectIdByType + the AKI turn
primitives -- resolves nothing in this build. The per-junction maps DO resolve
([TURNTGT] match_set={2:9} ...), so the fallback builds the 1-hop adjacency from
them: each phase serves its ORIGIN sections into its turning TO sections.

So under SUMO the rollout is a 1-hop network (approaches -> receiving links)
rather than 2-hop: the second hop needs the global turn table, which is exactly
what fails here. The [TURNADJ] line records which step came back empty, so the
two-hop path can be finished when that lookup is fixed.

Idempotent.
"""
import io
import os
import sys

PATH = "shared_tsp_engine/engine.py"

EDITS = [
    # 1) remember the junction list so the diagnostic can report it
    (
        [
            "    _adj = {}",
            "    try:",
            "        try:",
            "            _jids = list(ANGConnGetObjectIdByType('junction'))",
        ],
        [
            "    _adj = {}",
            "    _jids = []",
            "    try:",
            "        try:",
            "            _jids = list(ANGConnGetObjectIdByType('junction'))",
        ],
    ),
    # 2) diagnostic on the tail
    (
        [
            "    if _adj:",
            "        try:",
            "            globals()['_TURN_ADJ_CACHE'] = _adj",
            "        except Exception:",
            "            pass",
            "    return _adj",
        ],
        [
            "    try:",
            "        if os.environ.get('SPILL_BLOCK_LOG') and not globals().get(",
            "                '_TURN_ADJ_LOGGED'):",
            "            globals()['_TURN_ADJ_LOGGED'] = True",
            "            log_to_file(\"[TURNADJ] jids=%d sections_with_out=%d edges=%d \"",
            "                        \"getter_present=%r\"",
            "                        % (len(_jids), len(_adj),",
            "                           sum(len(v) for v in _adj.values()),",
            "                           globals().get('ANGConnGetObjectIdByType') is not None),",
            "                        force=True)",
            "    except Exception:",
            "        pass",
            "    if _adj:",
            "        try:",
            "            globals()['_TURN_ADJ_CACHE'] = _adj",
            "        except Exception:",
            "            pass",
            "    return _adj",
        ],
    ),
    # 3) plan-derived fallback instead of giving up
    (
        [
            "            if not _adj:",
            "                return _na('no turning adjacency')",
        ],
        [
            "            if not _adj:",
            "                # No global turn table (under SUMO the AAPI junction",
            "                # enumeration resolves nothing), so build the 1-hop",
            "                # adjacency from this junction's own plans: a phase",
            "                # serves its ORIGINS into its turning TO sections.",
            "                for _p in _ring:",
            "                    _ps = [int(s) for s in (_po.get(_p) or [])]",
            "                    _pt = [int(t) for t in (_tt.get(_p) or [])]",
            "                    for _o in _ps:",
            "                        for _t in _pt:",
            "                            if _o != _t:",
            "                                _adj.setdefault(_o, set()).add(_t)",
            "                if not _adj:",
            "                    return _na('no adjacency (global or plan)')",
        ],
    ),
]


def main() -> int:
    with io.open(PATH, encoding="utf-8", newline="") as fh:
        src = fh.read()
    if "TURNADJ" in src:
        print("ALREADY_PATCHED")
        return 0
    nl = "\r\n" if "\r\n" in src[:4000] else "\n"

    def blk(lines):
        return "".join(l + nl for l in lines)

    pairs = [(blk(o), blk(n)) for o, n in EDITS]
    for i, (old, _new) in enumerate(pairs):
        c = src.count(old)
        print("edit %d anchor_matches=%d" % (i, c))
        if c != 1:
            print("REFUSING: edit %d anchor is not unique" % i)
            return 1
    out = src
    for old, new in pairs:
        out = out.replace(old, new, 1)
    tmp = PATH + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    os.replace(tmp, PATH)
    print("PATCHED size %d -> %d" % (len(src), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
