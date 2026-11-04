"""check_ctm_now.py -- verify the CTM cell/connector layer actually works.

Run from a normal terminal AFTER the quick probe has finished:

    cd C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5
    python check_ctm_now.py

It reads the newest kg log per arm and reports whether the connector resolved,
whether recv_q is a real number, whether the derived bins vary, and whether the
games' NASH_CTM cost is contributing or silently zero. Exit code 0 = PASS.
"""
import collections
import glob
import io
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(BASE, "kg", "logs")
ARMS = ("CHAMP_ADAPTIVE_DSW_CELLQ_GATED",
        "CHAMP_ADAPTIVE_DSW_GAME_BUS",
        "CHAMP_ADAPTIVE_DSW_GAME_COOP")


def _newest_logs():
    out = {}
    files = sorted(glob.glob(os.path.join(LOGS, "Aimsun_TSP_Log_*.txt")),
                   key=os.path.getmtime)
    for f in files:
        head = io.open(f, encoding="utf-8", errors="replace").read(8000)
        m = re.search(r"\[ARM\] exp=(\S+)", head)
        if not m:
            continue
        arm = m.group(1)
        if arm in ARMS:
            out[arm] = f
    return out


def _stamp(p):
    return time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(p)))


def check_cellq(path):
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    n = txt.count("[CTM]")
    conn_ok = len(re.findall(r"\[CTM\].*conn=\[[0-9]", txt))
    conn_empty = len(re.findall(r"\[CTM\].*conn=\[\]", txt))
    recv_num = len(re.findall(r"recv_q=[0-9]", txt))
    recv_na = txt.count("recv_q=n/a")
    bind = len(re.findall(r"recv_bind=1", txt))
    derived = collections.Counter(
        re.findall(r"\[CTM\].*?derived=\[([0-9, ]*)\]", txt))
    status = collections.Counter(
        re.findall(r"\[CTM\].*?conn_status=([a-z_?]+)", txt))
    conn_src = collections.Counter(
        re.findall(r"\[CTM_CONN\] inter=\d+ ok tgt=\d+ src=([a-z]+)", txt))
    actions = collections.Counter(
        re.findall(r"\[CTM\].*?action=([A-Za-z_]+)_", txt))
    err = (txt.count("solve_bus_phase_green error")
           + txt.count("solve_green_extension error"))

    print("CELLQ  %s  (%s)" % (os.path.basename(path), _stamp(path)))
    print("  decisions            : %d" % n)
    print("  connector resolved   : %d  (empty %d)" % (conn_ok, conn_empty))
    print("  recv_q numeric / n-a : %d / %d" % (recv_num, recv_na))
    print("  recv_bind=1          : %d" % bind)
    print("  distinct derived     : %d  %s" % (
        len(derived), derived.most_common(6)))
    print("  conn_status          : %s" % status.most_common(6))
    print("  connector source     : %s" % conn_src.most_common(6))
    print("  CTM actions          : %s" % actions.most_common(5))
    print("  solver errors        : %d" % err)
    reasons = []
    if n == 0:
        reasons.append("no [CTM] lines")
    if n and "[CTM_CONN]" not in txt:
        reasons.append("STALE CODE: no [CTM_CONN] tag -> this log predates "
                       "the connector rewrite (Aimsun not restarted)")
    if conn_ok == 0:
        reasons.append("connector never resolved")
    elif n and conn_ok < 0.5 * n:
        reasons.append("connector resolved only %d/%d decisions" % (conn_ok, n))
    _bad = sum(int(status.get(_k, 0)) for _k in
               ("no_data", "no_down", "no_coord", "raised", "no_index"))
    if _bad:
        reasons.append("%d unresolved connector(s): %s" % (
            _bad, dict((k, status.get(k, 0)) for k in
                       ("no_data", "no_down", "no_coord", "raised", "no_index")
                       if status.get(k, 0))))
    if recv_num == 0:
        reasons.append("recv_q never numeric")
    if len(derived) < 3:
        reasons.append("derived state still degenerate (%d value)" % len(derived))
    if err:
        reasons.append("%d solver errors" % err)
    return reasons, txt


def check_game(path):
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    ub = txt.count("[NASH_UB]")
    err = txt.count("[NASH_BARGAIN] error")
    commits = len(re.findall(r"\[(?:NASH_BARGAIN|COOP_GAME)\][^\n]*chosen=", txt))
    ctm_lines = txt.count("[NASH_CTM]")
    ctm_pos = len(re.findall(r"\[NASH_CTM\][^\n]*ctm=[1-9]", txt))
    ctm_zero = len(re.findall(r"\[NASH_CTM\][^\n]*ctm=0 ", txt))
    ctm_err = txt.count("ctm=ERR")
    nside0 = len(re.findall(r"\[NASH_CTM\][^\n]*nside=0", txt))
    first = None
    for line in txt.splitlines():
        if re.search(r"\[(?:NASH_BARGAIN|COOP_GAME)\][^\n]*chosen=", line):
            m = re.search(r"t=([0-9.]+)", line)
            if m:
                first = float(m.group(1))
                break
    print("GAME   %s  (%s)" % (os.path.basename(path), _stamp(path)))
    print("  commits              : %d   first at t=%s" % (
        commits, ("%.0f s" % first) if first is not None else "never"))
    print("  bargain errors       : %d" % err)
    print("  [NASH_CTM] lines     : %d  (ctm>0 %d, ctm=0 %d, ERR %d, nside=0 %d)"
          % (ctm_lines, ctm_pos, ctm_zero, ctm_err, nside0))
    reasons = []
    if err:
        reasons.append("%d bargain errors" % err)
    if commits == 0:
        reasons.append("game never committed an action")
    if ctm_lines == 0:
        reasons.append("NASH_CTM never logged (STALE CODE: engine/"
                       "specialized_modes not reloaded)")
    if ctm_lines and ctm_pos == 0:
        reasons.append("game CTM cost always 0 (nside=0 or no cells)")
    return reasons, txt


def _commits(path):
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    out = []
    for line in txt.splitlines():
        m = re.search(r"\[(?:NASH_BARGAIN|COOP_GAME)\][^\n]*chosen=([A-Z_0-9]+)", line)
        if not m:
            continue
        t = re.search(r"t=([0-9.]+)", line)
        inter = re.search(r"inter=(\d+)", line)
        obj = re.search(r"obj=([a-z]+)", line)
        out.append((inter.group(1) if inter else "?",
                    t.group(1) if t else "?",
                    m.group(1),
                    obj.group(1) if obj else "?"))
    return out


def main():
    logs = _newest_logs()
    if not logs:
        sys.exit("no Aimsun logs with [ARM] found in %s" % LOGS)
    print("=" * 74)
    print("CTM / GAME VERDICT")
    print("=" * 74)
    fails = []
    for arm in ARMS:
        p = logs.get(arm)
        if p is None:
            print("%s: NO LOG\n" % arm)
            fails.append("%s: no log" % arm)
            continue
        if "CELLQ" in arm:
            reasons, _ = check_cellq(p)
        else:
            reasons, _ = check_game(p)
        if reasons:
            fails.append("%s: %s" % (arm.split("DSW_")[-1], "; ".join(reasons)))
        print()
    # GAME SEPARATION (2026-10-30): GAME_BUS and GAME_COOP produced byte-identical
    # results because argmax(joint) coincided with the Nash product on every
    # frontier. Report whether the two games now diverge; identical sequences with
    # two different objectives means the cooperative method is not distinct.
    bus_p = logs.get("CHAMP_ADAPTIVE_DSW_GAME_BUS")
    coop_p = logs.get("CHAMP_ADAPTIVE_DSW_GAME_COOP")
    if bus_p and coop_p:
        sb, sc = _commits(bus_p), _commits(coop_p)
        print("GAME SEPARATION")
        print("  GAME_BUS commits  : %d" % len(sb))
        print("  GAME_COOP commits : %d  (objectives: %s)" % (
            len(sc), sorted(set(c[3] for c in sc)) or "?"))
        same = (sb == sc and len(sb) > 0)
        print("  sequences identical: %s" % same)
        if same:
            fails.append("GAME_COOP: decision sequence identical to GAME_BUS "
                         "(cooperative objective not distinct)")
        print()
    print("=" * 74)
    if fails:
        print("FAIL")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS -- connector resolves, recv_q numeric, derived bins vary,")
    print("        game CTM priced and games commit actions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
