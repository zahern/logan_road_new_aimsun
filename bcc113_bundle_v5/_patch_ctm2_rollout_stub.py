"""Guard the rollout readout against zero/1 m stubs.

A stub shorter than a vehicle has storage ~1 pcu, so one queued vehicle reads as
occupancy 1.0 and out_cap_frac would go to 0.0 -- throttling the whole phase on
a section that cannot physically hold a queue. Such TO sections are now skipped;
if none survive for a phase the phase is omitted, which fails open to 1.0.

The real queue sits on the section downstream of the stub, which hop 2 already
carries. Idempotent.
"""
import io
import sys

PATH = "shared_tsp_engine/engine.py"

EDITS = [
    (
        [
            "            _n = {}",
            "            _stor = {}",
            "            _qs = {}",
        ],
        [
            "            _n = {}",
            "            _stor = {}",
            "            _qs = {}",
            "            _lenm = {}",
        ],
    ),
    (
        [
            "                _stor[_s] = max(_len * _lanes / 7.0, 1.0)",
        ],
        [
            "                _stor[_s] = max(_len * _lanes / 7.0, 1.0)",
            "                _lenm[_s] = _len",
        ],
    ),
    (
        [
            "                _tos = [int(t) for t in (_tt.get(_p) or []) if int(t) in _peak]",
        ],
        [
            "                _tos = [int(t) for t in (_tt.get(_p) or [])",
            "                        if int(t) in _peak",
            "                        and _lenm.get(int(t), 0.0) >= 5.0]",
        ],
    ),
]


def main() -> int:
    with io.open(PATH, encoding="utf-8", newline="") as fh:
        src = fh.read()
    if "_lenm" in src:
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
    with io.open(PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    print("PATCHED size %d -> %d" % (len(src), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
