"""Apply the three 2026-11-02 fixes found by inspecting cellq_held_kg.csv.

1. side_ratio gate used an aggregate-vs-single ratio (whole-approach veh*s over
   one bus's remaining wait), so it grew with the car population and vetoed
   54-73% of every candidate in both arms. Gate now compares marginal pax*s
   against NO_ACTION on both sides.

2. local_sat read `getattr(self,'UpDenList',[]) or []`, and UpDenList is
   np.zeros((n_phases,n_cols)). That raises ValueError on every call, the bare
   except swallowed it, and _local_sat was 0.000 on all 184 logged decisions.
   Now read via np.asarray, with the same measured-queue fallback the state
   dimension got on 2026-10-19.

3. CHAMP_ADAPTIVE_DSW_CELLQ_GATED_OPEN set CELLQLEARN_MIN_GAIN_S = 5.0 while
   the champion runs 1.0 -- a tightening, not a relaxation (log: min_gain
   refusals 8 -> 30). Set to 0.5.

Run: python -I _patch_side_ratio_and_sat.py
"""
import io
import sys

SM = "shared_tsp_engine/specialized_modes.py"
CS = "champion_search.py"


def load(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    nl = b"\r\n" if b"\r\n" in raw else b"\n"
    return raw, nl


def sub1(raw, old, new, label):
    n = raw.count(old)
    if n != 1:
        sys.exit("ABORT %s: expected 1 match, found %d" % (label, n))
    return raw.replace(old, new, 1)


# ---------------------------------------------------------------- specialized_modes.py
raw, NL = load(SM)
orig = raw

raw = sub1(
    raw,
    b"CELLQLEARN_MIN_GAIN_S = 0.0" + NL,
    b"CELLQLEARN_MIN_GAIN_S = 0.0" + NL
    + b"# 2026-11-02 FIX: gate the side_ratio veto (below) on the MARGINAL pax*s" + NL
    + b"# trade-off -- bus pax*s saved vs cross-traffic pax*s paid -- instead of the" + NL
    + b"# old aggregate-vs-single ratio, which latched the gate shut. False restores" + NL
    + b"# the old ratio so published runs stay reproducible." + NL
    + b"CELLQ_SIDE_RATIO_MARGINAL = True" + NL,
    "flag declaration",
)

raw = sub1(
    raw,
    b"    'CELLQLEARN_MIN_GAIN_S', 'CELLQLEARN_SAT_VETO'," + NL,
    b"    'CELLQLEARN_MIN_GAIN_S', 'CELLQLEARN_SAT_VETO'," + NL
    + b"    'CELLQ_SIDE_RATIO_MARGINAL'," + NL,
    "MODE_FLAGS whitelist",
)

MARG = (
    b"    # ------------------------------------------------------------------" + NL
    + b"    # 2026-11-02 FIX: the side_ratio gate compared INCOMMENSURABLE terms." + NL
    + b"    #   _side_ratio = (SUM of every other vehicle's standing delay, veh*s)" + NL
    + b"    #                 / (ONE bus's remaining wait, s)" + NL
    + b"    # The numerator aggregates the whole approach set; the denominator is a" + NL
    + b"    # single vehicle. The ratio therefore scales with the car population and" + NL
    + b"    # grows monotonically as queues build. KG seed-300 log evidence:" + NL
    + b"    #   o_d=223725 veh*s, eff_delay=56 s, BusOcc=40" + NL
    + b"    #   -> 223725 * 1.2 / (56 * 40) = 119.85   (logged side_ratio=119.853)" + NL
    + b"    # against thresholds of 1.0 / 2.0. The gate latched shut and vetoed 73%" + NL
    + b"    # (GATED) / 54% (OPEN) of candidates -- which is why the CELLQ_GATED vs" + NL
    + b"    # CELLQ_GATED_OPEN A/B came out indistinguishable: every arm that would" + NL
    + b"    # otherwise differ was killed by this one gate, identically." + NL
    + b"    #" + NL
    + b"    # The gate's INTENT is a marginal trade-off: does the cross traffic pay" + NL
    + b"    # more pax*s than the bus saves? Both sides are now pax*s deltas against" + NL
    + b"    # NO_ACTION, taken from the same _bxt_evals the reward uses, so they are" + NL
    + b"    # in the same currency and BXT_BALANCE_FACTOR=1.0 finally means what its" + NL
    + b"    # name says ('allow while side cost <= bus gain'). No threshold change." + NL
    + b"    #" + NL
    + b"    # [BXT] keeps logging the raw _side_ratio: it is the demand-regime signal" + NL
    + b"    # that _bxt_state_bin reads, and changing it would move the state bins." + NL
    + b"    # ------------------------------------------------------------------" + NL
    + b"    _side_ratio_gate = _side_ratio" + NL
    + b"    if (bool(globals().get('CELLQ_SIDE_RATIO_MARGINAL', True))" + NL
    + b"            and _chosen_atype != 'NO_ACTION'):" + NL
    + b"        try:" + NL
    + b"            _na_db = float(_bxt_evals[0][1])" + NL
    + b"            _na_ds = float(_bxt_evals[0][2])" + NL
    + b"            _ch_db, _ch_ds = _bxt_reward_for(" + NL
    + b"                _chosen_atype, _chosen_aparam)[1:3]" + NL
    + b"            _bus_gain = max(0.0, _na_db - float(_ch_db))" + NL
    + b"            _side_cost = max(0.0, float(_ch_ds) - _na_ds)" + NL
    + b"            _side_ratio_gate = _side_cost / max(_bus_gain, 1.0)" + NL
    + b"        except Exception:" + NL
    + b"            _side_ratio_gate = _side_ratio" + NL
)

raw = sub1(
    raw,
    b"    _cellq_prop = (_chosen_atype, _chosen_aparam)" + NL,
    b"    _cellq_prop = (_chosen_atype, _chosen_aparam)" + NL + MARG,
    "marginal-ratio insert",
)

GATE_OLD = (
    b"    elif (not _explore_bypass) and _side_ratio > float(" + NL
    + b"            BXT_GE_BALANCE_FACTOR if _chosen_atype == 'GE'" + NL
    + b"            else BXT_BALANCE_FACTOR):" + NL
    + b"        _cellq_veto = 'side_ratio(%.3f>%.3f)' % (" + NL
    + b"            _side_ratio," + NL
    + b"            float(BXT_GE_BALANCE_FACTOR if _chosen_atype == 'GE'" + NL
    + b"                  else BXT_BALANCE_FACTOR))" + NL
)
GATE_NEW = (
    b"    elif (not _explore_bypass) and _side_ratio_gate > float(" + NL
    + b"            BXT_GE_BALANCE_FACTOR if _chosen_atype == 'GE'" + NL
    + b"            else BXT_BALANCE_FACTOR):" + NL
    + b"        _cellq_veto = 'side_ratio(%.3f>%.3f)' % (" + NL
    + b"            _side_ratio_gate," + NL
    + b"            float(BXT_GE_BALANCE_FACTOR if _chosen_atype == 'GE'" + NL
    + b"                  else BXT_BALANCE_FACTOR))" + NL
)
raw = sub1(raw, GATE_OLD, GATE_NEW, "side_ratio gate")

SAT_OLD = (
    b"    try:" + NL
    + b"        _kj = max(float(getattr(self, 'JamDensity', 150.0)) or 150.0, 1.0)" + NL
    + b"        _ds = []" + NL
    + b"        for _row in (getattr(self, 'UpDenList', []) or []):" + NL
    + b"            try:" + NL
    + b"                for _v in _row:" + NL
    + b"                    _ds.append(float(_v))" + NL
    + b"            except TypeError:" + NL
    + b"                _ds.append(float(_row))" + NL
    + b"        _local_sat = max(_ds) / _kj if _ds else 0.0" + NL
    + b"    except Exception:" + NL
    + b"        _local_sat = 0.0" + NL
)
SAT_NEW = (
    b"    try:" + NL
    + b"        _kj = max(float(getattr(self, 'JamDensity', 150.0)) or 150.0, 1.0)" + NL
    + b"        # 2026-11-02 FIX: UpDenList is np.zeros((n_phases, n_cols)) and" + NL
    + b"        # SideUpDenList is np.zeros(n_side) (engine.py IntersectionController" + NL
    + b"        # __init__), and neither is ever re-assigned. The old idiom" + NL
    + b"        #     for _row in (getattr(self, 'UpDenList', []) or []):" + NL
    + b"        # therefore raised 'truth value of an array with more than one" + NL
    + b"        # element is ambiguous' on EVERY call; the bare except below swallowed" + NL
    + b"        # it and _local_sat was 0.000 on all 184 logged KG decisions, so this" + NL
    + b"        # gate has never vetoed anything and CELLQLEARN_SAT_VETO (0.85, or" + NL
    + b"        # 0.95 in the OPEN arm) has never been exercised. The state dimension" + NL
    + b"        # hit the same trap on 2026-10-19 and was given a fallback; this veto" + NL
    + b"        # was not, so it stayed dead. Read through np.asarray instead." + NL
    + b"        _ds = []" + NL
    + b"        for _attr in ('UpDenList', 'SideUpDenList'):" + NL
    + b"            _arr = np.asarray(getattr(self, _attr, ()), dtype=float)" + NL
    + b"            if _arr.size:" + NL
    + b"                _ds.extend([float(v) for v in _arr.ravel().tolist()])" + NL
    + b"        _dmax = max(_ds) if _ds else 0.0" + NL
    + b"        _local_sat = _dmax / _kj if _dmax > 0.0 else 0.0" + NL
    + b"        if _local_sat <= 0.0:" + NL
    + b"            # Mirror the 2026-10-19 state-dim fallback: the density arrays" + NL
    + b"            # can be all-zero at a tick, and a permanently dead gate is worse" + NL
    + b"            # than an approximate one. 20 veh ~= a saturated main queue." + NL
    + b"            _mq = self._measured_main_queue_veh()" + NL
    + b"            if _mq is not None and float(_mq) > 0.0:" + NL
    + b"                _local_sat = min(1.0, float(_mq) / 20.0)" + NL
    + b"    except Exception:" + NL
    + b"        _local_sat = 0.0" + NL
)
raw = sub1(raw, SAT_OLD, SAT_NEW, "local_sat density read")

raw = sub1(
    raw,
    b"        _cellq_held_log(self, time, veh_id, _cellq_veto, _cellq_prop," + NL
    + b"                        eff_delay, _side_ratio, _local_sat)" + NL,
    b"        _cellq_held_log(self, time, veh_id, _cellq_veto, _cellq_prop," + NL
    + b"                        eff_delay, _side_ratio_gate, _local_sat)" + NL,
    "held-log ratio field",
)
raw = sub1(
    raw,
    b"        _cellq_admit_log(self, time, veh_id, _chosen_atype, _chosen_aparam," + NL
    + b"                          eff_delay, _side_ratio, _local_sat)" + NL,
    b"        _cellq_admit_log(self, time, veh_id, _chosen_atype, _chosen_aparam," + NL
    + b"                          eff_delay, _side_ratio_gate, _local_sat)" + NL,
    "admit-log ratio field",
)

with open(SM, "wb") as fh:
    fh.write(raw)
print("patched %s (%d bytes -> %d)" % (SM, len(orig), len(raw)))

# ---------------------------------------------------------------- champion_search.py
cs, CNL = load(CS)
cs_orig = cs
cs = sub1(
    cs,
    b'{"CELLQLEARN_MIN_GAIN_S": 5.0,' + CNL,
    b'{"CELLQLEARN_MIN_GAIN_S": 0.5,   # 2026-11-02 FIX: champion runs 1.0, so' + CNL
    + b"         # 5.0 was a TIGHTENING not a relaxation (min_gain refusals 8 -> 30" + CNL
    + b"         # in the KG seed-300 A/B). 0.5 is below the champion, as intended." + CNL,
    "OPEN arm min_gain",
)
with open(CS, "wb") as fh:
    fh.write(cs)
print("patched %s (%d bytes -> %d)" % (CS, len(cs_orig), len(cs)))
print("OK")
