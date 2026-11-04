"""Price the off-phase benefit of EARLY_RED, then let it be selected.

Why EARLY_RED never fires (stats_TSP_EarlyRed = 0.0 in all nine runs of
cellq_held_kg.csv), traced through every layer:

  1. REWARD. _bxt_reward_for prices an ER on the phase that is RUNNING as
     d_side = _dctsp_cross_traffic_delay_s(0.0), and that function returns 0.0
     for any argument <= 0 -- it models green TAKEN FROM the off phases and has
     no way to express green GIVEN TO them. So truncating the running phase
     recorded zero benefit on the phases that actually gain the seconds.

  2. HARD VETO. dctsp_bxt then forced NO_ACTION outright:
         if _chosen_atype == 'EARLY_RED' and not _wrong_phase: -> NO_ACTION
     on the stated grounds that right-phase ER "only hurts the bus". True of
     the harm, false of the benefit it was not pricing.

  3. MIN_GAIN. Even past (2), `eff_delay` is the BUS's remaining wait. A bus
     already on green has eff_delay ~ 0, so CELLQLEARN_MIN_GAIN_S vetoed ER
     every time -- grading a network-rebalancing action on bus benefit.

This patch: (a) adds _dctsp_off_phase_gain_paxs on the controller, (b) credits
it as a NEGATIVE d_side in the ER reward, (c) makes the hard veto conditional
on the new flag, (d) skips the bus-min-gain gate for right-phase ER.

Flags, both default-on but overridable per arm via MODE_FLAGS:
  BXT_ER_OFFPHASE_CREDIT      master switch; False reproduces the old build
                              exactly (zero credit + unconditional veto)
  BXT_ER_OFFPHASE_GAIN_WEIGHT scale on the priced gain (default 1.0). No
                              CROSS_TRAFFIC_COST_MULTIPLIER and no
                              NETWORK_FACTOR: the credit deliberately
                              under-predicts, because the far more costly error
                              here is a credit nobody has validated making ER
                              win every decision.

Run: python -I _patch_er_offphase.py
"""
import sys

EN = "shared_tsp_engine/engine.py"
SM = "shared_tsp_engine/specialized_modes.py"


def load(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    return raw, (b"\r\n" if b"\r\n" in raw else b"\n")


HELPER = b'''    def _dctsp_off_phase_gain_paxs(self, action_s: float,
                                   queue_elapsed_s: float = 0.0) -> float:
        """Pax-seconds SAVED on the OFF phases when the phase that is running
        gives up `action_s` of green to them.

        _dctsp_cross_traffic_delay_s prices green TAKEN FROM the off phases and
        returns 0.0 for any non-positive argument, so it can only ever charge a
        candidate -- never credit one. EARLY_RED on the running phase is the
        mirror case: it shortens the running phase, i.e. the off phases GAIN
        `action_s`. Before this existed that gain was priced at exactly zero, so
        ER could only be scored as pure harm.

        Two conservative terms, both >= 0:
          * standing queue Q_0 discharges for action_s longer, so vehicles that
            clear inside the window leave action_s earlier:
                min(Q_0, s_eff * action_s) * action_s * car_occ
          * vehicles arriving DURING the window no longer stop; they wait
            action_s/2 on average:
                flow * action_s * (action_s / 2) * car_occ

        Deliberately omits the residual-queue term the cost model carries
        (Q_end^2 / 2 s_eff), and applies no CROSS_TRAFFIC_COST_MULTIPLIER and no
        NETWORK_FACTOR. The cost model is known to UNDER-predict the real cross
        cost (hence a 100x multiplier); a newly introduced CREDIT must therefore
        under-predict too, or ER wins on a number nobody has validated.

        Returns 0.0 for action_s <= 0 or when no off-phase row carries flow.
        """
        try:
            if action_s <= 0.0:
                return 0.0
            car_occ = max(safe_float(getattr(self, 'CarOcc', 1.0)), 1.0)
            sat_flow_vps = float(
                getattr(self, 'SaturationFlow', 1800) or 1800
            ) / 3600.0
            upf = getattr(self, 'UpFlowList', np.zeros((1, 1)))
            n_phases = upf.shape[0] if hasattr(upf, 'shape') else 0
            try:
                _phase_iter = self._nonmain_phase_indices()
            except Exception:
                _phase_iter = None
            if _phase_iter is None:
                _phase_iter = range(1, n_phases)
            gain_pax_s = 0.0
            for p in _phase_iter:
                if p < 0 or p >= n_phases:
                    continue
                row = upf[p]
                avg_flow_vph = float(np.mean(row)) if len(row) > 0 else 0.0
                if avg_flow_vph <= 0:
                    continue
                flow_vps = avg_flow_vph / 3600.0
                Q_0 = flow_vps * max(0.0, queue_elapsed_s)
                s_eff = max(sat_flow_vps - flow_vps, sat_flow_vps * 0.10)
                gain_pax_s += (min(Q_0, s_eff * action_s)
                               * action_s * car_occ)
                gain_pax_s += flow_vps * action_s * (action_s / 2.0) * car_occ
            return max(0.0, gain_pax_s)
        except Exception:
            return 0.0

'''


def sub1(raw, old, new, label):
    n = raw.count(old)
    if n != 1:
        sys.exit("ABORT %s: expected 1 match, found %d" % (label, n))
    return raw.replace(old, new, 1)


# ------------------------------------------------------------------ engine.py
raw, NL = load(EN)
orig = raw
raw = sub1(
    raw,
    b"    def _cascade_spillback_paxs(self, action_s: float) -> float:" + NL,
    HELPER.replace(b"\n", NL)
    + b"    def _cascade_spillback_paxs(self, action_s: float) -> float:" + NL,
    "off-phase gain helper",
)
with open(EN, "wb") as fh:
    fh.write(raw)
print("patched %s (%d -> %d bytes)" % (EN, len(orig), len(raw)))

# --------------------------------------------------------- specialized_modes.py
raw, NL = load(SM)
orig = raw

# (1) flag declarations
raw = sub1(
    raw,
    b"BXT_ENABLE_ER = True   # early red (order/swap)" + NL,
    b"BXT_ENABLE_ER = True   # early red (order/swap)" + NL
    + b"# 2026-11-02: right-phase EARLY_RED gives its truncated seconds to the OFF" + NL
    + b"# phases. Until this flag the reward priced that gain at 0.0 and the decider" + NL
    + b"# vetoed the action outright, so ER could never fire. False restores the old" + NL
    + b"# build exactly (zero credit + unconditional suppression)." + NL
    + b"BXT_ER_OFFPHASE_CREDIT = True" + NL
    + b"# Scale on the priced off-phase gain. 1.0 keeps ER conservative on purpose:" + NL
    + b"# the gain model under-predicts (no cost multiplier, no NETWORK_FACTOR), so" + NL
    + b"# raising this is the lever if ER proves too timid in a run." + NL
    + b"BXT_ER_OFFPHASE_GAIN_WEIGHT = 1.0" + NL,
    "flag declarations",
)

# (2) MODE_FLAGS so an arm can override them
raw = sub1(
    raw,
    b"    'BXT_ENABLE_OC'," + NL,
    b"    'BXT_ER_OFFPHASE_CREDIT', 'BXT_ER_OFFPHASE_GAIN_WEIGHT'," + NL
    + b"    'BXT_ENABLE_OC'," + NL,
    "MODE_FLAGS",
)

# (3) credit the gain in the ER reward
ER_OLD = (
    b"                d_bus += _bus_wait_pax" + NL
    + b"                d_side = float(self._dctsp_cross_traffic_delay_s(0.0))" + NL
    + b"            return -(d_bus + d_side), d_bus, d_side" + NL
)
ER_NEW = (
    b"                d_bus += _bus_wait_pax" + NL
    + b"                # 2026-11-02: the seconds this truncates away go to the OFF" + NL
    + b"                # phases, and _dctsp_cross_traffic_delay_s returns 0.0 for a" + NL
    + b"                # non-positive argument -- it charges green TAKEN, never" + NL
    + b"                # credits green GIVEN. This branch used to record d_side = 0," + NL
    + b"                # so right-phase ER could only ever be scored as pure harm." + NL
    + b"                # Price the mirror-image gain, as a NEGATIVE cost." + NL
    + b"                d_side = 0.0" + NL
    + b"                if bool(globals().get('BXT_ER_OFFPHASE_CREDIT', True)):" + NL
    + b"                    try:" + NL
    + b"                        _er_w = float(globals().get(" + NL
    + b"                            'BXT_ER_OFFPHASE_GAIN_WEIGHT', 1.0) or 0.0)" + NL
    + b"                        d_side = -_er_w * float(" + NL
    + b"                            self._dctsp_off_phase_gain_paxs(a_s))" + NL
    + b"                    except Exception:" + NL
    + b"                        d_side = 0.0" + NL
    + b"            return -(d_bus + d_side), d_bus, d_side" + NL
)
raw = sub1(raw, ER_OLD, ER_NEW, "ER reward credit")

# (4) do not grade right-phase ER on the bus's own remaining wait
raw = sub1(
    raw,
    b"    if eff_delay < _bxt_min_delay_s and not _explore_bypass:" + NL,
    b"    # 2026-11-02: right-phase EARLY_RED is not a bus-benefit action -- the" + NL
    + b"    # bus is already on green -- so grading it on the bus's remaining wait" + NL
    + b"    # (eff_delay) asks the wrong question and vetoed it every time it was" + NL
    + b"    # offered. With the off-phase credit on, let the reward decide; with it" + NL
    + b"    # off this is byte-identical to the old gate." + NL
    + b"    _er_offphase = (_chosen_atype == 'EARLY_RED' and not _wrong_phase" + NL
    + b"                    and bool(globals().get('BXT_ER_OFFPHASE_CREDIT'," + NL
    + b"                                                     True)))" + NL
    + b"    if (eff_delay < _bxt_min_delay_s and not _explore_bypass" + NL
    + b"            and not _er_offphase):" + NL,
    "min_gain gate",
)

# (5) the unconditional suppression becomes conditional
raw = sub1(
    raw,
    b"    if _chosen_atype == 'EARLY_RED' and not _wrong_phase:" + NL,
    b"    # 2026-11-02: this used to force NO_ACTION unconditionally. That is right" + NL
    + b"    # about the HARM (shortening the bus's own green) and wrong about the" + NL
    + b"    # BENEFIT (the truncated seconds reach the off phases, which is what" + NL
    + b"    # _dctsp_off_phase_gain_paxs now prices). Keep the old unconditional" + NL
    + b"    # suppression when the credit is off so published runs reproduce." + NL
    + b"    if (_chosen_atype == 'EARLY_RED' and not _wrong_phase" + NL
    + b"            and not bool(globals().get('BXT_ER_OFFPHASE_CREDIT', True))):" + NL,
    "hard veto",
)

with open(SM, "wb") as fh:
    fh.write(raw)
print("patched %s (%d -> %d bytes)" % (SM, len(orig), len(raw)))
print("OK")
