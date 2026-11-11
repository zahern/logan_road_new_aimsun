"""Name the model that priced the decision in the [SPILLPAY] trace.

The label expression is LINE-WRAPPED in the source, so the earlier
single-line anchor could not match; this one spans the wrap.

EOL-aware. Idempotent: re-running prints ALREADY_PATCHED.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, 'shared_tsp_engine', 'engine.py')

with open(P, 'rb') as fh:
    data = fh.read()
if b'GAME_CTM2_LIGHTSIM' not in data:
    raise SystemExit('engine lighting patch not applied - run _patch_lightsim_engine.py first')
if b"'lightsim' if bool(globals().get('GAME_CTM2_LIGHTSIM'" in data:
    print('ALREADY_PATCHED')
    sys.exit(0)

START = b"'rollout' if bool(globals().get("
END = b"else 'scalar'"
i = data.find(START)
assert i > 0, 'label start not found'
j = data.find(END, i)
assert j > i, 'label end not found'
seg = data[i:j + len(END)]
assert b'GAME_CTM2_ROLLOUT' in seg, 'label span does not contain the rollout flag'
assert len(seg) < 200, 'unexpected label span %d bytes' % len(seg)

NEW = (b"'lightsim' if bool(globals().get('GAME_CTM2_LIGHTSIM', False)) "
       b"else ('rollout' if bool(globals().get('GAME_CTM2_ROLLOUT', False)) "
       b"else 'scalar')")
before = len(data)
data = data[:i] + NEW + data[j + len(END):]

tmp = P + '.lslabel.tmp'
with open(tmp, 'wb') as fh:
    fh.write(data)
os.replace(tmp, P)
print('PATCHED size %d -> %d' % (before, len(data)))
