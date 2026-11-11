"""Payoff-scoped proof that the spillback term is non-zero.

_phase_downstream_block has nine call sites, so a [SPILLBLK] line shows the
FUNCTION returns something non-zero, not that _game_ctm2_payoffs ever put a
non-zero block into a candidate's sec_snap. This logs the term as the PAYOFF
computed it -- mode (scalar|rollout), how many phases were positive, and the
max -- capped per junction so a run stays readable.

Gated on SPILL_BLOCK_LOG. Idempotent (keyed on SPILLPAY).
"""
import io
import os
import sys

PATH = "shared_tsp_engine/engine.py"

ANCHOR = "        _chain_seed = bool(globals().get('GAME_CTM2_CHAIN_SEED', False))"

NEW = [
    "        if _spill:",
    "            # Payoff-scoped proof trace (SPILL_BLOCK_LOG): the block term as",
    "            # the payoff actually computed it, per decision. Capped per",
    "            # junction so the log stays readable.",
    "            try:",
    "                if os.environ.get('SPILL_BLOCK_LOG'):",
    "                    _nlg = int(getattr(self, '_spillpay_n', 0) or 0)",
    "                    if _nlg < 400:",
    "                        self._spillpay_n = _nlg + 1",
    "                        _posv = [float(v) for v in _blk.values()",
    "                                 if float(v) > 0.0]",
    "                        log_to_file(",
    "                            \"[SPILLPAY] jct=%s mode=%s n_ph=%d \"",
    "                            \"n_pos=%d max=%.3f\"",
    "                            % (getattr(self, 'id', '?'),",
    "                               'rollout' if bool(globals().get(",
    "                                   'GAME_CTM2_ROLLOUT', False)) else 'scalar',",
    "                               len(_blk), len(_posv),",
    "                               max(_posv) if _posv else 0.0),",
    "                            force=True)",
    "            except Exception:",
    "                pass",
]


def main() -> int:
    with io.open(PATH, encoding="utf-8", newline="") as fh:
        src = fh.read()
    if "SPILLPAY" in src:
        print("ALREADY_PATCHED")
        return 0
    nl = "\r\n" if "\r\n" in src[:4000] else "\n"
    anchor = ANCHOR + nl
    c = src.count(anchor)
    print("anchor_matches=%d" % c)
    if c != 1:
        print("REFUSING: anchor is not unique")
        return 1
    new = "".join(l + nl for l in NEW) + anchor
    out = src.replace(anchor, new, 1)
    tmp = PATH + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    os.replace(tmp, PATH)
    print("PATCHED size %d -> %d" % (len(src), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
