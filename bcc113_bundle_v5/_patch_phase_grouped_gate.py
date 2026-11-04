"""Rename the marginal gate's terms from vehicle-class to PHASE semantics.

The 2026-11-02 gate I added already compares phase-grouped quantities, because
_bxt_reward_for returns (r, d_current_phase, d_off_phases):

  * d_current_phase = _ctm_red_delay(n0_bus, ...) where n0_bus is the LWR
    estimate of the WHOLE approach queue in vehicles and _cell_occ blends
    BusOcc with CarOcc (see the 2026-xx comment at the n0_bus definition) --
    so it is every pax on the running phase, cars behind the bus included.
    d_current_phase also carries _bus_wait_pax (the bus's miss penalty).
  * d_off_phases = _dctsp_cross_traffic_delay_s(), which iterates
    _nonmain_phase_indices() -- the phases that are NOT running.

So `_bus_gain` / `_side_cost` were misleading names for a phase split, and the
comments ("bus pax*s saved vs cross-traffic pax*s paid") understated what the
terms contain: the current-phase term credits car gain as well as bus gain.
This patch renames them _served_gain / _off_cost and documents the grouping.
NO numerical change -- the arithmetic is untouched.

Run: python -I _patch_phase_grouped_gate.py
"""
import sys

SM = "shared_tsp_engine/specialized_modes.py"

with open(SM, "rb") as fh:
    raw = fh.read()
nl = b"\r\n" if b"\r\n" in raw else b"\n"
orig = raw


def sub1(old, new, label):
    global raw
    n = raw.count(old)
    if n != 1:
        sys.exit("ABORT %s: expected 1 match, found %d" % (label, n))
    raw = raw.replace(old, new, 1)


# ---- 1. the header comment: say "phase", not "bus vs side" -------------------
OLD_HDR = (
    b"    # The gate's INTENT is a marginal trade-off: does the cross traffic pay" + nl
    + b"    # more pax*s than the bus saves? Both sides are now pax*s deltas against" + nl
    + b"    # NO_ACTION, taken from the same _bxt_evals the reward uses, so they are" + nl
    + b"    # in the same currency and BXT_BALANCE_FACTOR=1.0 finally means what its" + nl
    + b"    # name says ('allow while side cost <= bus gain'). No threshold change." + nl
)
NEW_HDR = (
    b"    # The gate compares PHASES, not vehicle classes: pax*s given up on the" + nl
    + b"    # phases that are NOT running, against pax*s saved on the phase that IS." + nl
    + b"    # The running phase's term is the whole approach cell, so it credits the" + nl
    + b"    # cars behind the bus as well as the bus itself -- an extension that" + nl
    + b"    # clears 30 queued cars is worth 30 cars' worth of pax*s, not one bus's." + nl
    + b"    # Both sides are pax*s deltas against NO_ACTION from the same _bxt_evals" + nl
    + b"    # the reward uses, so BXT_BALANCE_FACTOR=1.0 finally means what its name" + nl
    + b"    # says ('allow while off-phase cost <= on-phase gain'). No threshold" + nl
    + b"    # change: 1.0 / 2.0 were always right for a marginal ratio." + nl
)
sub1(OLD_HDR, NEW_HDR, "gate header comment")

# ---- 2. the computation: rename + document ----------------------------------
OLD_CODE = (
    b"        try:" + nl
    + b"            _na_db = float(_bxt_evals[0][1])" + nl
    + b"            _na_ds = float(_bxt_evals[0][2])" + nl
    + b"            _ch_db, _ch_ds = _bxt_reward_for(" + nl
    + b"                _chosen_atype, _chosen_aparam)[1:3]" + nl
    + b"            _bus_gain = max(0.0, _na_db - float(_ch_db))" + nl
    + b"            _side_cost = max(0.0, float(_ch_ds) - _na_ds)" + nl
    + b"            _side_ratio_gate = _side_cost / max(_bus_gain, 1.0)" + nl
)
NEW_CODE = (
    b"        try:" + nl
    + b"            # Split by PHASE (see _bxt_reward_for):" + nl
    + b"            #   [1] = pax*s on the phase that is RUNNING. n0_bus is the" + nl
    + b"            #         whole approach queue in vehicles and _cell_occ blends" + nl
    + b"            #         BusOcc with CarOcc, so this is every pax on that" + nl
    + b"            #         phase -- the queued cars included, not just the bus." + nl
    + b"            #         It also carries _bus_wait_pax, the cost of the bus" + nl
    + b"            #         missing the green it is trying to catch." + nl
    + b"            #   [2] = pax*s on the OFF phases (_dctsp_cross_traffic_delay_s" + nl
    + b"            #         iterates _nonmain_phase_indices())." + nl
    + b"            _cur_na = float(_bxt_evals[0][1])" + nl
    + b"            _off_na = float(_bxt_evals[0][2])" + nl
    + b"            _cur_ch, _off_ch = _bxt_reward_for(" + nl
    + b"                _chosen_atype, _chosen_aparam)[1:3]" + nl
    + b"            _served_gain = max(0.0, _cur_na - float(_cur_ch))" + nl
    + b"            _off_cost = max(0.0, float(_off_ch) - _off_na)" + nl
    + b"            _side_ratio_gate = _off_cost / max(_served_gain, 1.0)" + nl
)
sub1(OLD_CODE, NEW_CODE, "marginal gate computation")

with open(SM, "wb") as fh:
    fh.write(raw)
print("patched %s (%d -> %d bytes)" % (SM, len(orig), len(raw)))
print("OK")
