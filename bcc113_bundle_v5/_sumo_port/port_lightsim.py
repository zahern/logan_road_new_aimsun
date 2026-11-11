"""Port GAME_CTM2_LIGHTSIM (LightSim-style network CTM) from the Aimsun bundle
into the SUMO fork, so the SPILL2 LIGHTSIM arms can be run on Logan.

Idempotent: every step checks for its own marker first. Backups are written
next to each file with the same stamp. Compile-checks all touched Python.
"""
import io
import os
import shutil
import sys

AIM = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\shared_tsp_engine"
FORK = "Z:/tsp/sumo_hpc/shared_tsp_engine"
ARMS = "Z:/tsp/sumo_hpc/sumo_bridge/sweep_arms.py"
GEN = "Z:/tsp/sumo_hpc/qb_gameladder_gen.sh"
STAMP = ".bak_lightsimport_20261109"

FAILS = []


def read(p):
    with io.open(p, encoding="utf-8", newline="") as fh:
        return fh.read()


def write(p, s):
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(s)


def nl_of(s):
    return "\r\n" if "\r\n" in s else "\n"


# ---- 1. ctm_lightsim.py: copy verbatim -------------------------------------
src_ls = os.path.join(AIM, "ctm_lightsim.py")
dst_ls = os.path.join(FORK, "ctm_lightsim.py")
if os.path.exists(dst_ls) and not os.path.exists(dst_ls + STAMP):
    shutil.copyfile(dst_ls, dst_ls + STAMP)
shutil.copyfile(src_ls, dst_ls)
print("1. ctm_lightsim.py copied (%d bytes)" % os.path.getsize(dst_ls))

# ---- 2. engine.py: insert _ctm2_rollout_block ------------------------------
aim_eng = read(os.path.join(AIM, "engine.py"))
aim_lines = aim_eng.splitlines()
start = next(i for i, l in enumerate(aim_lines)
             if l.startswith("    def _ctm2_rollout_block(self, ring, cur, rem, greens):"))
end = next(i for i in range(start + 1, len(aim_lines))
           if aim_lines[i].startswith("    def "))
method = "\n".join(aim_lines[start:end]).rstrip("\n") + "\n"
print("2. extracted _ctm2_rollout_block: Aimsun lines %d-%d (%d lines)"
      % (start + 1, end, end - start))

old_adj = "            _adj = _turning_adjacency() or {}"
new_adj = ("            try:\n"
           "                _adj = _turning_adjacency() or {}\n"
           "            except NameError:\n"
           "                # SUMO fork: no module-level turn table; the plan-based\n"
           "                # adjacency below is the documented fallback.\n"
           "                _adj = {}")
if method.count(old_adj) != 1:
    FAILS.append("rollout adjacency anchor count %d" % method.count(old_adj))
else:
    method = method.replace(old_adj, new_adj, 1)

eng_path = os.path.join(FORK, "engine.py")
eng = read(eng_path)
nl = nl_of(eng)
anchor = "    def _game_ctm2_na(self, reason):"
if eng.count(anchor) != 1:
    FAILS.append("engine insert anchor count %d" % eng.count(anchor))
elif "_ctm2_rollout_block" in eng:
    print("   engine already carries the rollout method")
else:
    if nl != "\n":
        method = method.replace("\n", nl)
    eng = eng.replace(anchor, method + nl + anchor, 1)
    print("   rollout method inserted before _game_ctm2_na")

old_blk = (
    "        _blk = {}\n"
    "        if _spill:\n"
    "            for _p in _ring:\n"
    "                try:\n"
    "                    _blk[int(_p)] = max(0.0, float(self._phase_downstream_block(int(_p)) or 0.0))\n"
    "                except Exception:\n"
    "                    _blk[int(_p)] = 0.0\n"
).replace("\n", nl)
new_blk = (
    "        _blk = {}\n"
    "        if _spill:\n"
    "            _roll_on = bool(globals().get('GAME_CTM2_ROLLOUT', False)\n"
    "                            or globals().get('GAME_CTM2_LIGHTSIM', False))\n"
    "            if _roll_on:\n"
    "                # Shared 2-hop network CTM rollout (GAME_CTM2_ROLLOUT);\n"
    "                # GAME_CTM2_LIGHTSIM prices the block term with\n"
    "                # ctm_lightsim.py instead. {} => fail open.\n"
    "                try:\n"
    "                    _blk = dict(self._ctm2_rollout_block(\n"
    "                        _ring, _cur, _rem, _greens) or {})\n"
    "                except Exception as _swx:\n"
    "                    _note_swallow('_game_ctm2_payoffs#rollout', _swx)\n"
    "                    _blk = {}\n"
    "            else:\n"
    "                for _p in _ring:\n"
    "                    try:\n"
    "                        _blk[int(_p)] = max(0.0, float(self._phase_downstream_block(int(_p)) or 0.0))\n"
    "                    except Exception:\n"
    "                        _blk[int(_p)] = 0.0\n"
).replace("\n", nl)
if eng.count(old_blk) != 1:
    FAILS.append("block-term anchor count %d" % eng.count(old_blk))
else:
    eng = eng.replace(old_blk, new_blk, 1)
    print("   block term: rollout branch wired")
if not os.path.exists(eng_path + STAMP):
    shutil.copyfile(eng_path, eng_path + STAMP)
write(eng_path, eng)

# ---- 3. specialized_modes.py: defaults + propagation list ------------------
spm_path = os.path.join(FORK, "specialized_modes.py")
spm = read(spm_path)
nl2 = nl_of(spm)
if "GAME_CTM2_LIGHTSIM" in spm:
    print("3. specialized_modes already declares the LIGHTSIM flags")
else:
    flag_anchor = "GAME_CTM2_HORIZON_S = 60.0" + nl2 + "GAME_CTM2_IG_S = 5.0" + nl2
    flags = (
        "# Shared 2-hop network CTM rollout for the block term (port 2026-11-09\n"
        "# of the Aimsun model). Off keeps the scalar per-phase jam fraction.\n"
        "GAME_CTM2_ROLLOUT = False\n"
        "# LightSim-style NETWORK CTM as the block model (ctm_lightsim.py).\n"
        "# Implies GAME_CTM2_ROLLOUT; READOUT picks the cell that decides 'full'.\n"
        "GAME_CTM2_LIGHTSIM = False\n"
        "GAME_CTM2_LIGHTSIM_MAX_CELLS = 12\n"
        "GAME_CTM2_LIGHTSIM_READOUT = 'worst'\n"
    ).replace("\n", nl2)
    if spm.count(flag_anchor) != 1:
        FAILS.append("flags anchor count %d" % spm.count(flag_anchor))
    else:
        spm = spm.replace(flag_anchor, flag_anchor + flags, 1)
        prop_old = "    'GAME_CTM2_SPILLBACK', 'GAME_CTM2_SPILLBACK_GAMMA'," + nl2
        prop_new = (prop_old
                    + "    'GAME_CTM2_ROLLOUT'," + nl2
                    + "    'GAME_CTM2_LIGHTSIM', 'GAME_CTM2_LIGHTSIM_MAX_CELLS'," + nl2
                    + "    'GAME_CTM2_LIGHTSIM_READOUT'," + nl2)
        if spm.count(prop_old) != 1:
            FAILS.append("propagation anchor count %d" % spm.count(prop_old))
        else:
            spm = spm.replace(prop_old, prop_new, 1)
            if not os.path.exists(spm_path + STAMP):
                shutil.copyfile(spm_path, spm_path + STAMP)
            write(spm_path, spm)
            print("3. specialized_modes: flags + propagation list wired")

# ---- 4. sweep_arms.py: SPILL2_LIGHTSIM config + two arms -------------------
arms = read(ARMS)
nl3 = nl_of(arms)
if "_CTM2_SPILL2_LIGHTSIM" in arms:
    print("4. sweep_arms already declares SPILL2_LIGHTSIM")
else:
    cfg_anchor = "CTM2_ARMS = [" + nl3
    cfg = (
        "#   _CTM2_SPILL2_LIGHTSIM  the SPILL2 flag set with the block term priced\n"
        "#                by the LightSim-style network CTM (ctm_lightsim.py)\n"
        "#                instead of the scalar per-phase jam fraction. Mirrors the\n"
        "#                Aimsun twins: READOUT='entry' (worst saturates on a red\n"
        "#                own stop line), MAX_CELLS=24. LIGHTSIM implies ROLLOUT.\n"
        "_CTM2_SPILL2_LIGHTSIM = dict(\n"
        "    _CTM2_SPILL2,\n"
        "    NASH_CORRIDOR_MODE=False,\n"
        "    GAME_CTM2_ROLLOUT=True,\n"
        "    GAME_CTM2_LIGHTSIM=True,\n"
        "    GAME_CTM2_LIGHTSIM_MAX_CELLS=24,\n"
        "    GAME_CTM2_LIGHTSIM_READOUT='entry',\n"
        ")\n"
    ).replace("\n", nl3)
    tail_anchor = ('    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_LIGHTSIM", "utilitarian", _CTM2_LIGHTSIM),'
                   + nl3)
    tail_new = (tail_anchor
                + '    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM", "nash", _CTM2_SPILL2_LIGHTSIM),' + nl3
                + '    ("CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_LIGHTSIM", "utilitarian", _CTM2_SPILL2_LIGHTSIM),' + nl3)
    ok = True
    for an in (cfg_anchor, tail_anchor):
        if arms.count(an) != 1:
            FAILS.append("sweep_arms anchor %r count %d" % (an.strip()[:40], arms.count(an)))
            ok = False
    if ok:
        arms = arms.replace(cfg_anchor, cfg + cfg_anchor, 1)
        arms = arms.replace(tail_anchor, tail_new, 1)
        if not os.path.exists(ARMS + STAMP):
            shutil.copyfile(ARMS, ARMS + STAMP)
        write(ARMS, arms)
        print("4. sweep_arms: +2 arms (NASH/UTIL _CTM2_SPILL2_LIGHTSIM)")

# ---- 5. generator PORTABLE list -------------------------------------------
gen = read(GEN)
nl4 = nl_of(gen)
if "SPILL2_LIGHTSIM" in gen:
    print("5. generator already lists the arms")
else:
    g_anchor = ("  CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2" + nl4
                + ")" + nl4)
    g_new = ("  CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2" + nl4
             + "  CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM" + nl4
             + "  CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_LIGHTSIM" + nl4
             + ")" + nl4)
    if gen.count(g_anchor) != 1:
        FAILS.append("generator PORTABLE anchor count %d" % gen.count(g_anchor))
    else:
        gen = gen.replace(g_anchor, g_new, 1)
        if not os.path.exists(GEN + STAMP):
            shutil.copyfile(GEN, GEN + STAMP)
        write(GEN, gen)
        print("5. generator: +2 portable arms")

# ---- 6. compile checks ----------------------------------------------------
for p in (dst_ls, eng_path, spm_path, ARMS):
    try:
        compile(read(p), p, "exec")
        print("   compile ok  %s" % os.path.basename(p))
    except SyntaxError as exc:
        FAILS.append("%s: %s line %s" % (p, exc.msg, exc.lineno))

if FAILS:
    print("\nFAILURES:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("\nport complete")
