"""Add a gated [SPILLBLK] trace to _phase_downstream_block (bundle engine).

The live engine already resolves the turning TO-section map from the network's
connection table, so the block term is only 0.0 when the receiving sections are
EMPTY. To show a short run actually produces a non-zero block (rather than
assuming it), log the first few non-zero values per junction when
SPILL_BLOCK_LOG=1. Idempotent: refuses to patch twice.
"""
import io
import sys

PATH = "shared_tsp_engine/engine.py"

OLD = [
    "            if not _tos:",
    "                return 0.0",
    "            return max((self._section_jam_frac(int(t)) for t in _tos), default=0.0)",
]

NEW = [
    "            if not _tos:",
    "                return 0.0",
    "            _blk = max((self._section_jam_frac(int(t)) for t in _tos), default=0.0)",
    "            # Gated proof trace (SPILL_BLOCK_LOG=1): the first few NON-ZERO",
    "            # blocks per junction, so one short run shows the spillback term",
    "            # is live instead of 0.0. The env read is guarded so nothing here",
    "            # can take the block down with it.",
    "            _trace = False",
    "            try:",
    "                _trace = bool(os.environ.get('SPILL_BLOCK_LOG'))",
    "            except Exception:",
    "                _trace = False",
    "            if _blk > 0.0 and _trace:",
    "                try:",
    "                    _nl = int(getattr(self, '_spillblk_logged', 0) or 0)",
    "                    if _nl < 4:",
    "                        self._spillblk_logged = _nl + 1",
    "                        log_to_file(\"[SPILLBLK] jct=%s ph=%s n_to=%d blk=%.3f tos=%s\"",
    "                                    % (getattr(self, 'id', '?'), int(phase),",
    "                                       len(_tos), _blk,",
    "                                       sorted(int(t) for t in _tos)[:6]),",
    "                                    force=True)",
    "                except Exception:",
    "                    pass",
    "            return _blk",
]


def main() -> int:
    with io.open(PATH, encoding="utf-8", newline="") as fh:
        src = fh.read()
    if "SPILLBLK" in src:
        print("ALREADY_PATCHED")
        return 0
    nl = "\r\n" if "\r\n" in src[:4000] else "\n"
    old = nl.join(OLD) + nl
    new = nl.join(NEW) + nl
    n = src.count(old)
    print("anchor_matches=%d newline=%r size=%d" % (n, nl, len(src)))
    if n != 1:
        print("REFUSING: anchor is not unique")
        return 1
    with io.open(PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write(src.replace(old, new, 1))
    print("PATCHED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
