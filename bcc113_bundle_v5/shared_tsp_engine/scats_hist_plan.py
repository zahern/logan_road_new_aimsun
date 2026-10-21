"""scats_hist_plan.py -- SCATS HISTORICAL plan loader (PLAN_SCATS_HIST).

Purpose: when PLAN_SCATS_HIST is on, the engine seeds each junction's startup
plan from the junction's REAL commissioned SCATS plan instead of the Aimsun
network's plan. Source is the iMove SCATS File Share RAM export:

    <share>\\SCATS Regions\\<REGION>\\Ram\\YYYYMMDD_Ram.txt

(The Central Manager .bak is a raw SQL Server backup -- unreadable without a
restore; the region RAM export carries the same PDn plan data, so it is THE
data source here. If raw .ram files appear without a _Ram.txt decode, they are
skipped; a future .hist upload would slot into scats_hist_plan() the same way.)

RAM export format (verified against NORMAN 20251031_Ram.txt):
    SLOT=n!ZD! ;I=<site>! (RAM)          record header (one per site)
    PDnCL=<cycle>!                       plan n cycle length (seconds)
    PDnA=0!PDnB=..!...PDnF=..!           stage END times (seconds); A=0 start.
                                         Some values are 'C' (custom/cleared)
                                         and must be skipped.
    PDnR-/R+/Y-/Y+/Q-/Z-...              interstage / marker fields -- NOT
                                         stage ends, never decoded here.
    SCk>DD*HH:MM=plan!                   time-of-day schedule: day-type DD,
                                         time HH:MM, plan number.

Stage greens are the DIFF of consecutive stage ends (boundary i+1 - boundary i,
last stage = CL - last boundary) and are used only as PROPORTIONS -- the actual
green seconds are scaled to the model junction's cycle and lost time by the
engine (engine._plan_opt_scats_hist), because the model may run a different
cycle / phase count than the SCATS site.

Junction -> SCATS site mapping is RESOLVED, not guessed: every GKNode in the
KG model export carries its SCATS site number in its name (sumo_bridge/
kg_aimsun_dump_fresh.json; 8129 -> 1043762 by elimination of the only unnamed
corridor node). Same mapping as kg/scats_channel_map.py -- keep in sync if the
model changes.

Run-locally safe: no Aimsun imports, stdlib only.
    python scats_hist_plan.py            -> prints the corridor site report
"""
import os
import re

# Default share root (overridable via the SCATS_HIST_SHARE flag at runtime).
DEFAULT_SHARE = r'C:\Users\ahernz\github_for_aimsun\iMove SCATS File Share'

# Aimsun node id -> SCATS site number (RESOLVED from GKNode names in the KG
# model export; identical to kg/scats_channel_map.SCATS_CHANNELS).
JUNCTION_SITE = {
    39606: 306,    # KGR-Herston Rd           B0306 (external id '306' too)
    39590: 307,    # 307 (Kelvin Grove/Windsor/Bishop)
    36393: 308,    # 308 (Enoggera/Parker/Davidson)
    36385: 309,    # 309 (Enoggera/Edmonstone/Ashgrove)
    39593: 310,    # 310 (Enoggera & Newmarket)
    39587: 311,    # 311 (Enoggera Rd near Wickham)
    39576: 312,    # 312 (Enoggera Rd & Banks St)
    39578: 313,    # 313 (Enoggera & Alderson)
    39569: 314,    # 314 (Enoggera/SouthPine/Samford)
    38339: 371,    # 371 (Sicklefield & Pickering)
    39572: 176,    # 176 (South Pine Rd & Railway Pl)
    1043762: 8129, # 8129 (Enoggera Rd & Moran St; inferred)
}

_STAGES = ('A', 'B', 'C', 'D', 'E', 'F')

_HDR = re.compile(r'SLOT=\d+!ZD! ;I=(\d+)! \(RAM\)')
_SC = re.compile(r'SC(\d+)>(\d+)\*(\d+):(\d+)=(\d+)')
# key = one of PDnCL | PDn<stage letter>; value = number or 'C'.
# Markers like PDnR-/PDnY- keys contain '-'/'+' and are rejected by [A-F$].
_KEY = re.compile(r'PD(\d+)(CL|[A-F])=([^!]*)')
_TEXT_KEY = re.compile(r'([A-Z0-9+\-]+)=([^!]*)')

# {(region, site): {'plans': {n: {'cycle': s, 'ends': [sec,...]}},
#                   'sched': [(dd, tod_min, plan), ...], 'file': str}}
_CACHE = {}
_LOADED = False
_LAST_SHARE = None
# Sites seen in the export but NOT mapped to a model junction (diagnostics).
_UNMAPPED = set()


def junction_site(jid):
    return JUNCTION_SITE.get(int(jid))


def _flush_record(site, region, toks):
    plans = {}
    sched = []
    for _k, _v in toks:
        m = _KEY.match(_k + '=' + _v)
        if not m:
            continue
        n_s, tag, val = m.group(1), m.group(2), m.group(3).strip()
        n = int(n_s)
        if n <= 0:                      # PD0...: placeholder, always empty
            continue
        if tag == 'CL':
            try:
                _cl = float(val)
            except ValueError:
                continue
            if _cl > 0.0:
                plans.setdefault(n, {})['cycle'] = _cl
            continue
        try:
            _sec = float(val)
        except ValueError:
            continue                    # 'C' (custom/cleared): not numeric
        if 0.0 <= _sec <= 86400.0:
            plans.setdefault(n, {}).setdefault('ends', []).append((_sec, tag))
    for k, v in toks:
        m = _SC.match(k)
        if m:                           # SCn>DD*HH:MM=plan inside a PD line
            sched.append((int(m.group(2)),
                          int(m.group(3)) * 60 + int(m.group(4)),
                          int(m.group(5))))
    if not (plans or sched):
        return
    cur = _CACHE.setdefault((region, site),
                            {'plans': {}, 'sched': [], 'file': ''})
    for n, p in plans.items():
        if 'cycle' in p and p.get('ends'):
            cur['plans'][n] = {'cycle': p['cycle'],
                               'ends': [s for s, _ in
                                        sorted(p['ends'],
                                               key=lambda t: (t[0], t[1]))]}
    cur['sched'].extend(s for s in sched if s not in cur['sched'])


def _parse_ram_txt(path, region):
    site = None
    toks = []
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            h = _HDR.search(line)
            if h is not None:
                if site is not None:
                    _flush_record(site, region, toks)
                site = int(h.group(1))
                _UNMAPPED.add(site)          # optimistically; removed below
                toks = []
            elif site is not None:
                # the SCn>DD*HH:MM=plan schedule lines contain '>' and '*',
                # which the generic KEY tokeniser cannot key on -- capture
                # them straight from the raw line instead.
                for msc in _SC.finditer(line):
                    toks.append((msc.group(0), msc.group(5)))
                toks.extend(_TEXT_KEY.findall(line))
    if site is not None:
        _flush_record(site, region, toks)
    # every site we built a cache entry for IS mapped-present
    for _r, s in list(_CACHE):
        _UNMAPPED.discard(s)


def _ensure_loaded(share=None):
    """Scan <share>/SCATS Regions/<region>/Ram/*_Ram.txt (date order; newer
    files overwrite fields from older ones). Idempotent + refreshes when the
    share path changes."""
    global _LOADED, _LAST_SHARE, _CACHE, _UNMAPPED
    _share = str(share or DEFAULT_SHARE)
    if _LOADED and _LAST_SHARE == _share:
        return True
    root = os.path.join(_share, 'SCATS Regions')
    if not os.path.isdir(root):
        _LOADED = False
        return False
    _CACHE = {}
    _UNMAPPED = set()
    files = []
    for region in sorted(os.listdir(root)):
        ram_dir = os.path.join(root, region, 'Ram')
        if not os.path.isdir(ram_dir):
            continue
        for p in os.listdir(ram_dir):
            if p.lower().endswith('_ram.txt'):
                files.append((p, os.path.join(ram_dir, p), region))
    # date-ascending: later (newer) files overwrite older plans
    for _name, path, region in sorted(files, key=lambda t: t[0]):
        try:
            _parse_ram_txt(path, region)
        except OSError:
            continue
        for k in _CACHE:
            if k[0] == region and not _CACHE[k]['file']:
                _CACHE[k]['file'] = path
    _LOADED = True
    _LAST_SHARE = _share
    # note unsupported alternatives once, for the run log
    _n_hist = len([1 for _r, _d, _f in os.walk(root)
                   for _x in _f if _x.lower().endswith('.hist')])
    if _n_hist:
        print('[SCATS HIST] %d .hist file(s) present but unreadable '
              '(no decoder) -- RAM export used instead' % _n_hist)
    _n_bak = len([1 for _r, _d, _fl in os.walk(_share)
                  for _x in _fl if _x.lower().endswith('.bak')])
    if _n_bak:
        print('[SCATS HIST] %d Central Manager .bak backup(s) found -- SQL '
              'Server backup, not readable without a restore; RAM export '
              'used instead' % _n_bak)
    return True


def _plan_of_daytype(rec, daytype):
    """Pick (daytype, tod_min, plan) for the requested day-type: exact code
    first, then any larger code (e.g. an 'all days' 13/14 entry), then any."""
    sched = rec.get('sched') or []
    for _pref in (lambda d: d == daytype, lambda d: d > daytype,
                  lambda d: True):
        cands = [s for s in sched if _pref(s[0])]
        if cands:
            return min(cands, key=lambda s: s[1])     # earliest entry in-day
    return None


def scats_hist_plan(jid, daytype=8, tod_min=480.0, share=None):
    """The requested site's SCATS plan at (daytype, time-of-day).

    Returns {'site', 'region', 'plan', 'cycle_s', 'stage_ends', 'greens',
    'source_file'} or None (unmapped junction / no data / no numeric stages).
    The returned 'greens' are RAW stage seconds summing to cycle_s -- the
    engine scales them to the model's own cycle/lost time as proportions."""
    _ok = _ensure_loaded(share)
    site = junction_site(jid)
    if site is None or not _ok:
        return None
    rec = None
    reg = None
    for (r, s), v in _CACHE.items():
        if s == site:
            rec = v
            reg = r
            break
    if rec is None:
        return None
    sel = _plan_of_daytype(rec, int(daytype))
    if sel is None:
        return None
    _dd, e_tod, plan_n = sel
    if tod_min is not None and float(tod_min) > 0.0:
        # latest schedule entry at-or-before the requested time (wrap-after-
        # midnight falls back to the earliest entry). Prefer matching
        # day-type entries over the fallback ladder.
        _cands = [s for s in (rec.get('sched') or [])
                  if s[0] == _dd and s[1] <= float(tod_min)]
        if not _cands:
            _cands = [s for s in (rec.get('sched') or [])
                      if s[1] <= float(tod_min)]
        if _cands:
            _dd, e_tod, plan_n = max(_cands, key=lambda s: s[1])
    p = (rec.get('plans') or {}).get(plan_n)
    if not p:
        return None
    ends = list(p.get('ends') or [])
    cyc = float(p.get('cycle', 0.0) or 0.0)
    if cyc <= 0.0 or not ends:
        return None
    # boundaries: stage start (0) then stage ends B..F ascending
    bounds = [0.0] + [e for e in ends if 0.0 < e <= cyc]
    greens = []
    for i in range(1, len(bounds)):
        g = bounds[i] - bounds[i - 1]
        if g > 0.0:
            greens.append(round(g, 1))
    tail = cyc - bounds[-1]
    if tail > 0.0:
        greens.append(round(tail, 1))
    if not greens:
        return None
    return {'site': site, 'region': reg, 'plan': plan_n, 'cycle_s': cyc,
            'stage_ends': ends, 'greens': greens,
            'n_stages': len(greens), 'daytype': _dd, 'tod_min': e_tod,
            'source_file': rec.get('file') or ''}


def scats_hist_corridor_report(share=None, daytype=8, tod_min=480.0):
    """One line per mapped corridor junction with its selected SCATS plan --
    used by the engine's startup log AND by running this file directly."""
    out = []
    for jid in sorted(JUNCTION_SITE):
        seed = scats_hist_plan(jid, daytype=daytype, tod_min=tod_min,
                               share=share)
        if seed:
            out.append('jid=%-8d site=%-5d region=%-7s plan=%-3d C=%5.0fs '
                       'stages=%d greens=%s'
                       % (jid, seed['site'], seed['region'], seed['plan'],
                          seed['cycle_s'], seed['n_stages'], seed['greens']))
        else:
            out.append('jid=%-8d site=%-5s -- NO DECODABLE PLAN'
                       % (jid, junction_site(jid)))
    return out


def scats_hist_status(share=None):
    """Short loader status line for AAPIInit logging."""
    _ok = _ensure_loaded(share)
    if not _ok:
        return 'share not found (%s)' % (share or DEFAULT_SHARE)
    n_sites = len(_CACHE)
    n_files = len({v['file'] for v in _CACHE.values() if v['file']})
    n_regions = len({k[0] for k in _CACHE})
    return ('%d region(s) %d file(s) %d site(s) loaded from %s'
            % (n_regions, n_files, n_sites, _LAST_SHARE))


if __name__ == '__main__':
    print('[SCATS HIST]', scats_hist_status())
    for line in scats_hist_corridor_report():
        print(line)
