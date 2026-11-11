"""CTMTIME: per-decision wall time of the two block models.

  [CTMTIME] jct=.. model=lightsim us=..   (_ctm2_rollout_block, LightSim branch)
  [CTMTIME] jct=.. model=rollout  us=..   (_ctm2_rollout_block, inline loop)

Both timings cover the SAME work: geometry fetch for the subnet, model build,
the horizon steps, and the per-phase read-out. The LightSim branch returns
before the inline loop, so one run exercises exactly one model.

Gated on env CTMTIME_LOG, capped at 400 samples per junction. EOL-aware.
Idempotent: re-running prints ALREADY_PATCHED.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, 'shared_tsp_engine', 'engine.py')

with open(P, 'rb') as fh:
    data = fh.read()
if b'[CTMTIME]' in data:
    print('ALREADY_PATCHED')
    sys.exit(0)
if b'GAME_CTM2_LIGHTSIM' not in data:
    raise SystemExit('apply _patch_lightsim_engine.py first')

E = b'\r\n' if b'\r\n' in data else b'\n'


def L(s):
    return s.replace(b'\n', E)


before = len(data)

START = L(b'''                        _ct_t0 = None
                        try:
                            import time as _ct_tm
                            _ct_t0 = _ct_tm.perf_counter()
                        except Exception:
                            _ct_t0 = None
''')

END = L(b'''                        if _ct_t0 is not None and os.environ.get('CTMTIME_LOG'):
                            try:
                                import time as _ct_tm2
                                _ct_us = (_ct_tm2.perf_counter() - _ct_t0) * 1e6
                                _ct_n = int(getattr(self, '_ctmtime_n', 0) or 0)
                                if _ct_n < 400:
                                    self._ctmtime_n = _ct_n + 1
                                    log_to_file("[CTMTIME] jct=%s model=lightsim "
                                                "us=%.0f n_link=%d n_step=%d"
                                                % (getattr(self, 'id', '?'), _ct_us,
                                                   len(_gmap), _steps), force=True)
                            except Exception:
                                pass
''')

# ---- 1. LightSim branch: start before the geometry map is fetched ----
A1 = L(b'                        _gmap = {}\n')
assert data.count(A1) == 1, 'A1 count=%d' % data.count(A1)
data = data.replace(A1, START + A1, 1)

# end: after the model call returns
A2 = b"int(globals().get('GAME_CTM2_LIGHTSIM_MAX_CELLS', 12) or 12))"
assert data.count(A2) == 1, 'A2 count=%d' % data.count(A2)
i2 = data.find(A2)
j2 = data.find(E, i2)
assert j2 > i2
data = data[:j2 + len(E)] + END + data[j2 + len(E):]

# ---- 2. inline rollout: start before the subnet geometry is fetched ----
A3 = L(b'            _sub = sorted(_orig) + [s for s in sorted(_hop1) if s not in _orig]\n')
assert data.count(A3) == 1, 'A3 count=%d' % data.count(A3)
data = data.replace(A3, L(b'''            _ct_t0 = None
            try:
                import time as _ct_tm
                _ct_t0 = _ct_tm.perf_counter()
            except Exception:
                _ct_t0 = None
''') + A3, 1)

# end: after the per-phase read-out, before the trace block
A4 = L(b'                _out[int(_p)] = min(max(max(_peak[t] for t in _tos), 0.0), 1.0)\n')
assert data.count(A4) == 1, 'A4 count=%d' % data.count(A4)
i4 = data.find(A4)
A5 = L(b'            _trace = False\n')
j4 = data.find(A5, i4)
assert j4 > i4, 'A5 not found after the read-out'
data = data[:j4] + L(b'''            if _ct_t0 is not None and os.environ.get('CTMTIME_LOG'):
                try:
                    import time as _ct_tm2
                    _ct_us = (_ct_tm2.perf_counter() - _ct_t0) * 1e6
                    _ct_n = int(getattr(self, '_ctmtime_n', 0) or 0)
                    if _ct_n < 400:
                        self._ctmtime_n = _ct_n + 1
                        log_to_file("[CTMTIME] jct=%s model=rollout "
                                    "us=%.0f n_link=%d n_step=%d"
                                    % (getattr(self, 'id', '?'), _ct_us,
                                       len(_n), _steps), force=True)
                except Exception:
                    pass
''') + data[j4:]

tmp = P + '.ctmtime.tmp'
with open(tmp, 'wb') as fh:
    fh.write(data)
os.replace(tmp, P)
print('PATCHED size %d -> %d' % (before, len(data)))
