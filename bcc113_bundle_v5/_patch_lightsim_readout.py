"""GAME_CTM2_LIGHTSIM_READOUT: which cell decides "the receiver is full".

  worst (default, current behaviour) : busiest cell anywhere on the link
  entry                              : cell 0, the cell a movement enters
  mean                               : link-average

Also adds the [LSBLK] diagnosis trace (SPILL_BLOCK_LOG=1) showing all three
read-outs plus the link's cell count and its initial fill, so saturation can be
attributed (own stop line vs entry vs a link already full at t0).

Engine + flags, EOL-aware, idempotent.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.join(HERE, 'shared_tsp_engine', 'engine.py')
SPM = os.path.join(HERE, 'shared_tsp_engine', 'specialized_modes.py')


def eol(data):
    return b'\r\n' if b'\r\n' in data else b'\n'


# ---------------------------------------------------------------- engine
with open(ENG, 'rb') as fh:
    data = fh.read()
E = eol(data)


def L(s):
    return s.replace(b'\n', E)


if b'GAME_CTM2_LIGHTSIM_READOUT' in data:
    print('engine ALREADY_PATCHED')
else:
    before = len(data)
    A0 = b'from ctm_lightsim import rollout_block as _ls_rb'
    n0 = data.count(A0)
    assert n0 == 2, 'import count=%d' % n0
    data = data.replace(A0, b'from ctm_lightsim import rollout_block_detail as _ls_rb')

    A1 = L(b'''                        _blk_ls = _ls_rb(
                            _gmap, _n, _adj, _serving, _gseq or {},
                            _ring, _tt, _steps, _dt,
                            int(globals().get('GAME_CTM2_LIGHTSIM_MAX_CELLS', 12) or 12))
''')
    n1 = data.count(A1)
    assert n1 == 1, 'call block count=%d' % n1
    R1 = L(b'''                        _ls_det = _ls_rb(
                            _gmap, _n, _adj, _serving, _gseq or {},
                            _ring, _tt, _steps, _dt,
                            int(globals().get('GAME_CTM2_LIGHTSIM_MAX_CELLS', 12) or 12))
                        # GAME_CTM2_LIGHTSIM_READOUT picks which cell decides
                        # "full": worst (busiest cell anywhere, pessimistic),
                        # entry (cell 0, what the model itself gates on) or mean.
                        _blk_ls = {}
                        _ls_mode = str(globals().get('GAME_CTM2_LIGHTSIM_READOUT',
                                                     'worst') or 'worst')
                        if _ls_mode not in ('worst', 'entry', 'mean'):
                            _ls_mode = 'worst'
                        for _ls_p, _ls_v in (_ls_det or {}).items():
                            try:
                                _blk_ls[int(_ls_p)] = min(max(float(
                                    _ls_v.get(_ls_mode, _ls_v.get('worst', 0.0))),
                                    0.0), 1.0)
                            except Exception:
                                continue
                        if _ls_det:
                            try:
                                if os.environ.get('SPILL_BLOCK_LOG'):
                                    _lsn = int(getattr(self, '_lsblk_n', 0) or 0)
                                    if _lsn < 60:
                                        self._lsblk_n = _lsn + 1
                                        log_to_file(
                                            "[LSBLK] jct=%s mode=%s %s"
                                            % (getattr(self, 'id', '?'), _ls_mode,
                                               ' '.join(
                                                   'ph%d:worst=%.2f,entry=%.2f,mean=%.2f,k=%d,seed=%.2f'
                                                   % (int(_ls_p),
                                                      float(_ls_v.get('worst', 0.0)),
                                                      float(_ls_v.get('entry', 0.0)),
                                                      float(_ls_v.get('mean', 0.0)),
                                                      int(_ls_v.get('k', 0)),
                                                      float(_ls_v.get('seeded', 0.0)))
                                                   for _ls_p, _ls_v in sorted(_ls_det.items()))),
                                            force=True)
                            except Exception:
                                pass
''')
    data = data.replace(A1, R1, 1)
    tmp = ENG + '.readout.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, ENG)
    print('engine PATCHED size %d -> %d' % (before, len(data)))

# ----------------------------------------------------------------- flags
with open(SPM, 'rb') as fh:
    spm = fh.read()
if b'GAME_CTM2_LIGHTSIM_READOUT' in spm:
    print('flags ALREADY_PATCHED')
else:
    before = len(spm)
    E2 = eol(spm)

    def M(s):
        return s.replace(b'\n', E2)

    A1 = M(b'GAME_CTM2_LIGHTSIM_MAX_CELLS = 12\n')
    assert spm.count(A1) == 1, 'flag def count=%d' % spm.count(A1)
    spm = spm.replace(A1, A1 + M(b"""# Which cell decides "the receiver is full" for the LightSim block:
#   'worst' busiest cell anywhere on the link (default, original behaviour;
#           pessimistic -- a link whose OWN stop line is red fills it without
#           blocking entry)
#   'entry' cell 0, the cell a discharging movement enters, which is what the
#           model itself gates on (recv[t][0])
#   'mean'  link-average peak occupancy
GAME_CTM2_LIGHTSIM_READOUT = 'worst'
"""), 1)

    A2 = M(b"    'GAME_CTM2_LIGHTSIM', 'GAME_CTM2_LIGHTSIM_MAX_CELLS',\n")
    assert spm.count(A2) == 1, 'MODE_FLAGS count=%d' % spm.count(A2)
    spm = spm.replace(A2, A2 + M(b"    'GAME_CTM2_LIGHTSIM_READOUT',\n"), 1)

    tmp = SPM + '.readout.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(spm)
    os.replace(tmp, SPM)
    print('flags PATCHED size %d -> %d' % (before, len(spm)))
