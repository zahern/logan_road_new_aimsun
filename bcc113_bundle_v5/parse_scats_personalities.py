"""
parse_scats_personalities.py -- extract the REAL SCATS site config from the iMove
SCATS File Share personality files, so we can (a) validate that our Aimsun DS
decomposition uses the same strategic approaches / detectors, and (b) see the real
commissioned phase timings (candidate for loading instead of a generalized plan).

Reads, per site folder under Personalities/North:
  * LST*.LST  -- the NGEN assembler listing. We pull the human-readable tables:
        *!LN                        site location name
        APPDEF  (Approach definition)   approach -> detector numbers
        APPSIG  (Approach signal groups) approach -> signal group
        APPEXT  (Approach timer defn)   approach -> approach timers
        VN<n>   (Vehicle group names)   signal group names
  * TIM*.DAT  -- plain-text timing settings: per-phase MIN/MAX/AMBER/RED greens.

Pure text parsing, no SCATS tooling. Run locally on Windows:
    python parse_scats_personalities.py
Writes a summary to scats_personalities_summary.txt next to this script and prints it.
"""
import os
import re
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
# The share sits beside the bundle: ...\github_for_aimsun\iMove SCATS File Share
# REGION selects which corridor's personalities to read: North=KG (default,
# unchanged so KG's collection is untouched), South=Logan Road. Override with
# argv[1] or env SCATS_REGION.
REGION = (sys.argv[1] if len(sys.argv) > 1
          else os.environ.get("SCATS_REGION", "North")).strip() or "North"


def _region_root(region):
    for base in (os.path.join(os.path.dirname(HERE), "iMove SCATS File Share",
                              "Personalities", region),
                 r"C:\Users\ahernz\github_for_aimsun\iMove SCATS File Share"
                 r"\Personalities\%s" % region):
        if os.path.isdir(base):
            return base
    return None


NORTH = _region_root(REGION)   # name kept for back-compat; holds the chosen region


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def _fdb_list(line):
    """Parse the operands of an `FDB a,b,c,END` directive -> [a,b,c] (ints, END dropped)."""
    m = re.search(r"\bFDB\s+([0-9A-Za-z,\s]+)", line)
    if not m:
        return []
    out = []
    for tok in m.group(1).split(","):
        tok = tok.strip()
        if not tok or tok.upper() in ("END", "ZERO"):
            continue
        try:
            out.append(int(tok))
        except Exception:
            out.append(tok)
    return out


def parse_lst(txt):
    """Return dict: name, approaches=[{label, dets, timers, sg}], groups={n:name}."""
    name = ""
    m = re.search(r"\*!LN\s+(.+)", txt)
    if m:
        name = m.group(1).strip()
    groups = {}
    for m in re.finditer(r"\*!VN(\d+)\s+(.+)", txt):
        groups[int(m.group(1))] = m.group(2).split("\t")[0].strip()

    def _table(anchor):
        """Collect the FDB rows + their trailing ( label ) after an anchor EQU line."""
        rows = []
        mi = re.search(r"\b%s\b\s+EQU" % re.escape(anchor), txt)
        if not mi:
            return rows
        for ln in txt[mi.end():].splitlines():
            if "FDB" in ln:
                vals = _fdb_list(ln)
                lbl = ""
                ml = re.search(r"\(([^)]*)\)", ln)
                if ml:
                    lbl = ml.group(1).strip()
                rows.append((vals, lbl))
            elif rows and ("EQU" in ln or ln.strip().startswith("***")):
                break
        return rows

    appdef = _table("APPDEF")   # approach -> detectors
    appsig = _table("APPSIG")   # approach -> signal group(s)
    appext = _table("APPEXT")   # approach -> timers
    approaches = []
    for i, (dets, lbl) in enumerate(appdef):
        sg = appsig[i][0] if i < len(appsig) and appsig[i][0] else []
        tmr = appext[i][0] if i < len(appext) else []
        approaches.append({
            "label": lbl, "dets": dets,
            "sg": (appsig[i][0] if i < len(appsig) else []),
            "timers": (appext[i][0] if i < len(appext) else []),
        })
    return {"name": name, "approaches": approaches, "groups": groups}


def parse_tim(txt):
    """Return list of (phase, min, max, amber, red) from the PHASE TIMES block."""
    out = []
    blk = txt.split("PHASE TIMES")[-1].split("PEDESTRIANS")[0] if "PHASE TIMES" in txt else ""
    for ln in blk.splitlines():
        m = re.match(r"\s*([A-Z])\s+(.*)", ln)
        if not m:
            continue
        nums = re.findall(r"\d+\.\d+", m.group(2))
        if len(nums) >= 2:
            # columns: ALT LST MIN INC MVG MAX ECO AMB RED SRED (variable fill)
            out.append((m.group(1), nums))
    return out


def main():
    if not NORTH:
        print("Could not find Personalities/%s. Check the share path." % REGION)
        return
    print("REGION = %s  (%s)" % (REGION, NORTH))
    lines = []
    for site in sorted(os.listdir(NORTH)):
        sdir = os.path.join(NORTH, site)
        if not os.path.isdir(sdir):
            continue
        lst = glob.glob(os.path.join(sdir, "LST*.LST"))
        tim = glob.glob(os.path.join(sdir, "TIM*.DAT"))
        if not lst:
            continue
        info = parse_lst(_read(lst[0]))
        timrows = parse_tim(_read(tim[0])) if tim else []
        lines.append("=" * 78)
        lines.append("SITE %s  --  %s" % (site, info.get("name", "")))
        if info.get("groups"):
            lines.append("  signal groups: " + ", ".join(
                "SG%d=%s" % (k, v) for k, v in sorted(info["groups"].items())))
        lines.append("  STRATEGIC APPROACHES (approach -> detectors -> signal group):")
        for a in info["approaches"]:
            lines.append("    %-16s dets=%-14s SG=%s" % (
                a["label"], a["dets"], a["sg"]))
        if timrows:
            lines.append("  PHASE TIMES (phase: numbers = ALT/LST/MIN/INC/MVG/MAX/ECO/AMB/RED):")
            for ph, nums in timrows:
                lines.append("    PH %s: %s" % (ph, " ".join(nums)))
    out = "\n".join(lines)
    print(out)
    try:
        _fn = "scats_personalities_summary_%s.txt" % REGION.lower()
        with open(os.path.join(HERE, _fn), "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
        print("\n[written] %s" % _fn)
    except Exception as e:
        print("write failed: %r" % e)


if __name__ == "__main__":
    main()
