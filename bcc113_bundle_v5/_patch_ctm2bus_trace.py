"""Add a [CTM2BUS] seeding trace to Engine._game_ctm2_payoffs.

The CTM2 bus payoff is
    b = sum_s (base[s].bus_delay_vs - act[s].bus_delay_vs) * bus_occ
so it is EXACTLY 0 whenever no bus reaches the modelled cells: seed_cells()
drops any vehicle farther than n_cells*cell_len_m, and marks a vehicle as a bus
only when bus_type_pos > 0 and type == bus_type_pos. This prints the seeding
facts (buses actually placed in cells, reach, bus_type_pos) so a zero bus payoff
can be attributed rather than guessed.

Gated on CTM2BUS_LOG (or SPILL_BLOCK_LOG), capped per junction. EOL-aware and
idempotent.

The `_dt = CBQL_CTM_DT_S` line appears twice in engine.py; the payoff's one is
selected by requiring `if not _snap:` a few bytes later.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, 'shared_tsp_engine', 'engine.py')
MARK = b'[CTM2BUS]'

with open(P, 'rb') as fh:
    data = fh.read()
if MARK in data:
    print('ALREADY_PATCHED')
    sys.exit(0)

E = b'\r\n' if b'\r\n' in data else b'\n'


def L(s):
    return s.replace(b'\n', E)


ANCHOR = b"_dt = float(globals().get('CBQL_CTM_DT_S', 2.0) or 2.0)"
starts = []
k = data.find(ANCHOR)
while k >= 0:
    starts.append(k)
    k = data.find(ANCHOR, k + 1)
if not starts:
    raise SystemExit('anchor not found')

picked = None
for k in starts:
    if b'if not _snap:' in data[k:k + 260]:
        picked = k
        break
if picked is None:
    raise SystemExit('payoff anchor not identified among %d candidates' % len(starts))

j = data.rfind(E, 0, picked)
assert j > 0
before = len(data)

NEW = L(b'''        # BUS-IN-HORIZON PROOF TRACE (2026-11-09): b (the bus payoff the
        # GAME_BUS_IN_HORIZON gate tests) is
        #   b = sum_s(base[s].bus_delay_vs - act[s].bus_delay_vs) * bus_occ
        # so it is EXACTLY 0 when no bus is seeded into the modelled cells:
        # seed_cells() drops vehicles beyond n_cells*cell_len_m and marks a bus
        # only when bus_type_pos > 0 and type == bus_type_pos. This logs the
        # seeding facts, so a u_bus=0 pick can be attributed:
        #   seeded_bus=0, btp<=0   -> bus class unresolved (BUS_TYPE_POS config)
        #   seeded_bus=0, btp>0    -> no bus on the modelled approaches/beyond reach
        #   seeded_bus>0           -> bus IS modelled; the zero comes from the
        #                             action not changing its discharge in the
        #                             horizon (green already sufficient / bus past
        #                             the stop line / saturated cell)
        try:
            if os.environ.get('CTM2BUS_LOG') or os.environ.get('SPILL_BLOCK_LOG'):
                _nbus_c = 0.0
                _ncar_c = 0.0
                _reach_m = 0.0
                for _e in _snap.values():
                    try:
                        _nbus_c += float(sum(_e[1].bus))
                        _ncar_c += float(sum(_e[1].car))
                        _reach_m = max(_reach_m, float(_e[0].length_m))
                    except Exception:
                        continue
                _nlgb = int(getattr(self, '_ctm2bus_n', 0) or 0)
                if _nlgb < 60:
                    self._ctm2bus_n = _nlgb + 1
                    log_to_file(
                        "[CTM2BUS] jct=%s t=%.0f btp=%d bus_occ=%.0f n_sec=%d "
                        "seeded_cars=%.0f seeded_bus=%.0f reach_m=%.0f "
                        "chain_seed=%r"
                        % (getattr(self, 'id', '?'), float(time),
                           int(getattr(self, 'bus_type_pos', -1) or -1),
                           float(getattr(self, 'BusOcc', 40.0) or 40.0),
                           len(_snap), _ncar_c, _nbus_c, _reach_m,
                           bool(globals().get('GAME_CTM2_CHAIN_SEED', False))),
                        force=True)
        except Exception:
            pass
''')
data = data[:j] + NEW + data[j:]

tmp = P + '.ctm2bus.tmp'
with open(tmp, 'wb') as fh:
    fh.write(data)
os.replace(tmp, P)
print('PATCHED size %d -> %d (EOL=%r, anchor at %d of %d)'
      % (before, len(data), E, picked, len(starts)))
