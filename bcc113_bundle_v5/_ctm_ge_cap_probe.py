import sys, csv, glob, types, collections
import xml.etree.ElementTree as ET
sys.path.insert(0, 'shared_tsp_engine')
import ctm_lightsim as LS

NET = '_sumo_snaps/kg.net.xml'
edges, nlanes, conns = {}, {}, set()
for ev, el in ET.iterparse(NET, events=('end',)):
    if el.tag == 'edge':
        if el.get('function') is None and el.get('from') and el.get('to'):
            eid = el.get('id')
            edges[eid] = (el.get('from'), el.get('to'))
            nlanes[eid] = max(1, len(el.findall('lane')))
        el.clear()
    elif el.tag == 'connection':
        a, b = el.get('from'), el.get('to')
        if a and b:
            conns.add((a, b))
        el.clear()

S = {e: int(e[1:]) for e in edges}
adj = collections.defaultdict(set)
for a, b in conns:
    if a in S and b in S and a != b:
        adj[S[a]].add(S[b])
ap, dp = collections.defaultdict(set), collections.defaultdict(set)
for e, (f, t) in edges.items():
    ap[t].add(S[e]); dp[f].add(S[e])

D = sorted(glob.glob('kg/results/CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM_seed300*'))[0]
stats = {}
for r in csv.DictReader(open(D + '/section_stats.csv', newline='', encoding='utf-8-sig')):
    try:
        stats[int(r['SectionID'])] = (float(r['Length_km']) * 1000.0, float(r['AvgDensity_vkm']))
    except Exception:
        pass

def geom(sid):
    L, dens = stats.get(sid, (150.0, 20.0))
    return types.SimpleNamespace(length_m=L, lanes=max(1, nlanes.get('s%d' % sid, 1)),
                                 v_free_kmh=50.0, w_back_kmh=18.0,
                                 k_jam_vkm_lane=200.0, q_sat_vph_lane=1800.0)

DT, STEPS, MC = 2.0, 30, 24

def curve(J, mode):
    O, H1 = sorted(ap[J]), sorted(dp[J])
    if not O or not H1:
        return None
    hop2 = [x for t in H1 for x in sorted(adj[t])][:24]
    sub = list(dict.fromkeys(O + H1 + hop2))
    geoms = {sid: geom(sid) for sid in sub}
    veh = {}
    for sid in sub:
        L, dens = stats.get(sid, (150.0, 20.0))
        if mode == 'origins' and sid not in O:
            dens = 0.0
        veh[sid] = dens * (L / 1000.0) * max(1, nlanes.get('s%d' % sid, 1))
    serving = {sid: {1} for sid in O}
    targets = {1: H1}
    rows = []
    for dd in (0, 2, 4, 6, 8, 10, 12, 16, 20, 30, 40):
        gseq = {p: [(p == 1 and (i * DT) < dd) for i in range(STEPS)] for p in range(1, 13)}
        det = LS.rollout_block_detail(geoms, veh, adj, serving, gseq, [1], targets, STEPS, DT, MC)
        v = (det or {}).get(1) or {}
        rows.append((dd, v.get('entry', 0.0), v.get('worst', 0.0), v.get('k', 0)))
    return rows

for J in ('n39590', 'n39573', 'n1026382', 'n39569'):
    for mode in ('origins', 'all'):
        rows = curve(J, mode)
        if not rows:
            continue
        print('\n== junction %s  seed=%s  (|O|=%d |H1|=%d)' % (J, mode, len(ap[J]), len(dp[J])))
        print('   d(s)  blk_entry  blk_worst  cells')
        for dd, e, w, k in rows:
            print('   %4d  %9.4f  %9.4f  %5d' % (dd, e, w, k))
        e40 = rows[-1][1]
        sat = next((dd for dd, e, w, k in rows if abs(e - e40) < 0.01), None)
        e10 = dict((dd, e) for dd, e, w, k in rows)[10]
        print('   entry@10=%.4f  entry@40=%.4f  delta=%+.4f  saturates_by=%s' % (e10, e40, e40 - e10, sat))
