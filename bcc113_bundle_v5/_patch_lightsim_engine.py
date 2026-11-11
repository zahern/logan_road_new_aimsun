"""GAME_CTM2_LIGHTSIM (engine side).

Wires ctm_lightsim.rollout_block into Engine._ctm2_rollout_block as the
ALTERNATIVE network CTM model, and makes the LightSim flag imply the rollout
path so the model is actually reachable.

EOL-aware (engine.py is CRLF). Idempotent: re-running prints ALREADY_PATCHED.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, 'shared_tsp_engine', 'engine.py')
MARK = b'GAME_CTM2_LIGHTSIM'

with open(P, 'rb') as fh:
    data = fh.read()
if MARK in data:
    print('ALREADY_PATCHED')
    sys.exit(0)

E = b'\r\n' if b'\r\n' in data else b'\n'


def L(s):
    return s.replace(b'\n', E)


before = len(data)

# ---- 1. the LightSim model, inserted just before the inline rollout loop ----
A1 = L(b'            _nsub = set(_n)\n')
n1 = data.count(A1)
assert n1 == 1, 'A1 count=%d' % n1
R1 = L(b'''            # GAME_CTM2_LIGHTSIM: LightSim-style NETWORK CTM as the alternative
            # model for this block term (ctm_lightsim.py). Same subnet, same
            # seeded live counts and same green timeline as the inline rollout
            # below; the difference is the flow resolution -- per-movement turn
            # ratios, saturation cap, and proportional merge/diverge scaling --
            # instead of the equal-split hop approximation.
            if bool(globals().get('GAME_CTM2_LIGHTSIM', False)):
                _ls_rb = None
                try:
                    from ctm_lightsim import rollout_block as _ls_rb
                except Exception:
                    try:
                        import sys as _lsys
                        _lsdir = os.path.dirname(os.path.abspath(__file__))
                        if _lsdir and _lsdir not in _lsys.path:
                            _lsys.path.insert(0, _lsdir)
                        from ctm_lightsim import rollout_block as _ls_rb
                    except Exception:
                        _ls_rb = None
                if _ls_rb is not None:
                    try:
                        _gmap = {}
                        for _ls in _n:
                            try:
                                _gmap[int(_ls)] = self._cbql_ctm_geom(int(_ls))
                            except Exception:
                                pass
                        _blk_ls = _ls_rb(
                            _gmap, _n, _adj, _serving, _gseq or {},
                            _ring, _tt, _steps, _dt,
                            int(globals().get('GAME_CTM2_LIGHTSIM_MAX_CELLS', 12) or 12))
                        if _blk_ls:
                            try:
                                if os.environ.get('SPILL_BLOCK_LOG'):
                                    _nls = int(getattr(self, '_lightsim_logged', 0) or 0)
                                    if _nls < 4:
                                        self._lightsim_logged = _nls + 1
                                        log_to_file(
                                            "[LIGHTSIM] jct=%s n_link=%d blk=%s"
                                            % (getattr(self, 'id', '?'), len(_gmap),
                                               ','.join('%d:%.2f' % (int(_p), float(_v))
                                                        for _p, _v in sorted(_blk_ls.items()))),
                                            force=True)
                            except Exception:
                                pass
                            return _blk_ls
                    except Exception:
                        pass
            _nsub = set(_n)
''')
data = data.replace(A1, R1, 1)

# ---- 2. the flag implies the rollout path ----
A2 = b"_roll_on = bool(globals().get('GAME_CTM2_ROLLOUT', False))"
n2 = data.count(A2)
assert n2 == 1, 'A2 count=%d' % n2
R2 = (b"_roll_on = bool(globals().get('GAME_CTM2_ROLLOUT', False) "
      b"or globals().get('GAME_CTM2_LIGHTSIM', False))")
data = data.replace(A2, R2, 1)

tmp = P + '.lightsim.tmp'
with open(tmp, 'wb') as fh:
    fh.write(data)
os.replace(tmp, P)
print('PATCHED size %d -> %d (EOL=%r)' % (before, len(data), E))
