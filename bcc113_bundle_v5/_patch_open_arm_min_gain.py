"""Second half of the 2026-11-02 fix: retune CELLQLEARN_MIN_GAIN_S on both
CELLQ_*_OPEN arms.

The champion runs 1.0 s; both OPEN arms were set to 5.0 s, which REQUIRES more
benefit before acting -- a tightening, not a relaxation. The KG seed-300 log
shows the result: min_gain refusals 8 (GATED) -> 30 (OPEN), so the arm that was
meant to act more acted less on that gate and the A/B netted out to nothing.

Set to 0.5 s -- genuinely below the champion, but not 0.0, because 22% of KG
decisions report eff_delay=0.0 and a 0.0 threshold would admit them at random.

Run: python -I _patch_open_arm_min_gain.py
"""
import sys

CS = "champion_search.py"

with open(CS, "rb") as fh:
    raw = fh.read()
nl = b"\r\n" if b"\r\n" in raw else b"\n"
orig = raw

COMMENT = (
    b'         # 2026-11-02 FIX: champion runs 1.0, so 5.0 was a TIGHTENING not' + nl
    + b"         # a relaxation (KG seed-300: min_gain refusals 8 -> 30). 0.5 is" + nl
    + b"         # below the champion, as the A/B intended. Not 0.0: 22% of KG" + nl
    + b"         # decisions report eff_delay=0.0 and would be admitted at random." + nl
)

for arm in ("CHAMP_ADAPTIVE_DSW_CELLQ_GATED_LOGAN_OPEN",
            "CHAMP_ADAPTIVE_DSW_CELLQ_GATED_OPEN"):
    old = (b'        "' + arm.encode() + b'",' + nl
           + b'        {"CELLQLEARN_MIN_GAIN_S": 5.0,' + nl)
    new = (b'        "' + arm.encode() + b'",' + nl
           + b'        {"CELLQLEARN_MIN_GAIN_S": 0.5,' + nl + COMMENT)
    n = raw.count(old)
    if n != 1:
        sys.exit("ABORT %s: expected 1 match, found %d" % (arm, n))
    raw = raw.replace(old, new, 1)
    print("patched", arm)

with open(CS, "wb") as fh:
    fh.write(raw)
print("patched %s (%d -> %d bytes)" % (CS, len(orig), len(raw)))
