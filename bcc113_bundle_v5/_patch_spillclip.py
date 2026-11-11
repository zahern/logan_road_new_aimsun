"""GAME_CTM2_SPILLCLIP.

1. _phase_downstream_block: clip the worst downstream jam fraction to the 0..1
   contract that _ctm2_rollout_block already enforces, keeping the raw ratio for
   the trace.  Two consumers treat this value as a FRACTION:
       out_cap_frac = 1 - gamma*block      (clamped in the payoff -> >1 only
                                            floors the receiver at 0)
       1 - block                           (BELLMAN_CTM_DOWNSTREAM, NOT
                                            clamped -> >1 gave negative spare
                                            capacity and over-penalised)
2. _section_jam_frac: log n / len / lanes / cap whenever the live ratio exceeds
   1.0, so the storage-basis mismatch is measured instead of guessed.

EOL-aware (the engine is CRLF).  Idempotent: re-running prints ALREADY_PATCHED.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, 'shared_tsp_engine', 'engine.py')
MARK = b'GAME_CTM2_SPILLCLIP'

with open(P, 'rb') as fh:
    data = fh.read()
if MARK in data:
    print('ALREADY_PATCHED')
    sys.exit(0)

E = b'\r\n' if b'\r\n' in data else b'\n'


def L(s):
    """Turn a \n-delimited literal into the file's own line endings."""
    return s.replace(b'\n', E)


before = len(data)

# ---------------------------------------------------------------- 1. clip
A1 = L(b'            _blk = max((self._section_jam_frac(int(t)) for t in _tos), '
       b'default=0.0)\n')
n1 = data.count(A1)
assert n1 == 1, 'A1 count=%d (EOL=%r)' % (n1, E)
R1 = L(b'            # GAME_CTM2_SPILLCLIP: keep the raw (unclipped) ratio for the\n'
       b'            # trace, then clip to the 0..1 contract that the CTM rollout\n'
       b'            # (_ctm2_rollout_block) already enforces. A live count/storage\n'
       b'            # ratio is NOT bounded by 1, yet both consumers read it as a\n'
       b'            # fraction:\n'
       b'            #   out_cap_frac = 1 - gamma*block   (clamped -> >1 just floors)\n'
       b'            #   1 - block      (BELLMAN_CTM_DOWNSTREAM, unclamped -> >1\n'
       b'            #                   became negative spare capacity)\n'
       b'            _fr = [(float(self._section_jam_frac(int(t))), int(t))\n'
       b'                   for t in _tos]\n'
       b'            _raw = max((f for f, _ in _fr), default=0.0)\n'
       b'            _blk = min(max(_raw, 0.0), 1.0)\n'
       b'            _wt = max(_fr, key=lambda _x: _x[0])[1] if _fr else -1\n')
data = data.replace(A1, R1, 1)

# ------------------------------------------------- 2. basis diagnostic
A2 = L(b'        return float(_n) / _cap\n')
n2 = data.count(A2)
assert n2 == 1, 'A2 count=%d' % n2
R2 = L(b'        _frac = float(_n) / _cap\n'
       b'        # GAME_CTM2_SPILLCLIP: a ratio above 1.0 is not a fraction -- log\n'
       b'        # the count and the storage it was divided by, so the basis\n'
       b'        # mismatch is visible (lane under-count vs trimmed length).\n'
       b'        try:\n'
       b'            if _frac > 1.0 and os.environ.get("SPILL_BLOCK_LOG"):\n'
       b'                _jf = int(getattr(self, "_jamfrac_logged", 0) or 0)\n'
       b'                if _jf < 12:\n'
       b'                    self._jamfrac_logged = _jf + 1\n'
       b'                    log_to_file("[JAMFRAC] jct=%s sec=%s n=%d len=%.1f "\n'
       b'                                "lanes=%d cap=%.1f frac=%.3f"\n'
       b'                                % (getattr(self, "id", "?"), int(sec),\n'
       b'                                   int(_n), float(_len), int(_lanes),\n'
       b'                                   float(_cap), _frac), force=True)\n'
       b'        except Exception:\n'
       b'            pass\n'
       b'        return _frac\n')
data = data.replace(A2, R2, 1)

# --------------------------------------- 3. extend the [SPILLBLK] trace
i = data.find(b'"[SPILLBLK]')
assert i > 0, 'no SPILLBLK trace'
j = data.find(b'force=True)', i)
assert j > i, 'no trace end'
seg = data[i:j]
assert seg.count(b'blk=%.3f tos=%s') == 1, 'trace fmt count=%d' % seg.count(
    b'blk=%.3f tos=%s')
assert seg.count(b'len(_tos), _blk,') == 1, 'trace args count=%d' % seg.count(
    b'len(_tos), _blk,')
seg2 = seg.replace(b'blk=%.3f tos=%s', b'blk=%.3f raw=%.3f wt=%s tos=%s')
seg2 = seg2.replace(b'len(_tos), _blk,', b'len(_tos), _blk, _raw, _wt,')
data = data[:i] + seg2 + data[j:]

tmp = P + '.spillclip.tmp'
with open(tmp, 'wb') as fh:
    fh.write(data)
os.replace(tmp, P)
print('PATCHED size %d -> %d (EOL=%r)' % (before, len(data), E))
