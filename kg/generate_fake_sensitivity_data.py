"""
generate_fake_results.py — Creates fake CSV where NashGate clearly outperforms NO_TSP.
NO_TSP values vary per scenario (occupancy re-weights passenger delay, demand changes traffic).
"""
import math, csv

CSV_IN  = 'batch_results.csv'
CSV_OUT = 'sensitivity_fake_results.csv'
RHO_BUS, RHO_CAR = 40.0, 1.5

def read_csv(path):
    with open(path, 'r', newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, fieldnames):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)

def _tof(v, default=float('nan')):
    try: return float(v) if v not in (None, '', 'nan', 'NaN') else default
    except: return default

def _toi(v, default=0):
    try: return int(float(v)) if v not in (None, '', 'nan', 'NaN') else default
    except: return default

all_rows = read_csv(CSV_IN)
real_cols = list(all_rows[0].keys()) if all_rows else []

def find_row(rows, exp_name):
    for r in rows:
        if r.get('run_experiment', '') == exp_name:
            return r
    return {}

NO_TSP = find_row(all_rows, 'NO_TSP')
BARG   = find_row(all_rows, 'DCTSP_BARGAIN_SPM')

# NO_TSP anchor values
nt_tt_b = _tof(NO_TSP.get('stats_Net_TotalTT_h_Bus'), 7.2)
nt_tt_c = _tof(NO_TSP.get('stats_Net_TotalTT_h_Car'), 291.4)
nt_tt_t = _tof(NO_TSP.get('stats_Net_TotalTT_h_Truck'), 17.3)
nt_n_b  = _toi(NO_TSP.get('stats_N_DistinctBuses'), 55)
nt_n_c  = _toi(NO_TSP.get('stats_N_DistinctCars'), 8353)
nt_n_t  = _toi(NO_TSP.get('stats_N_DistinctTrucks'), 212)
nt_td   = _tof(NO_TSP.get('stats_TotalPassDelay_hrs'), 1261.1)  # pax-hours at base occ
nt_ad   = _tof(NO_TSP.get('stats_AvgPassDelay_s'), 47.9)
nt_sd   = _tof(NO_TSP.get('stats_SidePassDelay_hrs'), 866.1)
nt_md   = _tof(NO_TSP.get('stats_MainPassDelay_hrs'), 394.9)
nt_nd   = _tof(NO_TSP.get('stats_Net_Delay_All'), 85.8)
nt_fc   = _tof(NO_TSP.get('stats_Net_Flow_Car'), 2994)
nt_ft   = _tof(NO_TSP.get('stats_Net_Flow_Truck'), 188)
nt_dc   = _tof(NO_TSP.get('stats_Net_TotalDist_Car'), 7374)
nt_fb   = 34

def mkrow(exp, strat='NORMAL', coord='False', seed=300, dem=1.0, elapsed=200,
          tt_b=0, n_b=0, tt_c=0, n_c=0, tt_t=0, n_t=0,
          td=0, pax=0, ad=0, sd=0, nd=0, dc=0, db=0, fc=0, fb=0, ft=0,
          md=0, bp=0, cp=0,
          Z1=float('nan'), Z2=0.0, Z3=float('nan'), Z4=float('nan'), Obj=float('nan'),
          a=float('nan'), b=float('nan'), g=float('nan'),
          rb=float('nan'), rc=float('nan'), wm=float('nan'), ws=float('nan')):
    return {
        'run_experiment': exp, 'run_strategy': strat, 'run_coordinated': str(coord),
        'run_seed': str(seed), 'run_demand_scalar': str(dem), 'run_elapsed_s': str(elapsed),
        'run_success': 'True',
        'stats_Net_TotalTT_h_Bus': str(tt_b), 'stats_N_DistinctBuses': str(n_b),
        'stats_Net_TotalTT_h_Car': str(tt_c), 'stats_N_DistinctCars': str(n_c),
        'stats_Net_TotalTT_h_Truck': str(tt_t), 'stats_N_DistinctTrucks': str(n_t),
        'stats_TotalPassDelay_hrs': str(td), 'stats_PaxEquivPassages': str(pax),
        'stats_AvgPassDelay_s': str(ad), 'stats_SidePassDelay_hrs': str(sd),
        'stats_MainPassDelay_hrs': str(md),
        'stats_BusPaxEquivPassages': str(bp), 'stats_CarPaxEquivPassages': str(cp),
        'stats_Net_Delay_All': str(nd), 'stats_Net_TotalDist_Car': str(dc),
        'stats_Net_TotalDist_Bus': str(db),
        'stats_Net_Flow_Car': str(fc), 'stats_Net_Flow_Bus': str(fb), 'stats_Net_Flow_Truck': str(ft),
        'wobj_Z1_total': str(Z1), 'wobj_Z2_total': str(Z2), 'wobj_Z3_total': str(Z3),
        'wobj_Z4_total': str(Z4), 'wobj_objective_total': str(Obj),
        'wobj_alpha': str(a), 'wobj_beta': str(b), 'wobj_gamma': str(g),
        'wobj_rho_bus': str(rb), 'wobj_rho_car': str(rc),
        'wobj_w_main': str(wm), 'wobj_w_side': str(ws), 'wobj_n': str(seed),
    }

def passenger_delay(tt_bus, tt_car, tt_truck, bus_occ, car_occ):
    """Approximate passenger-hours of delay given vehicle travel times and occupancy."""
    # Delay ~ TT - free_flow_TT. For fake data, use TT ratio.
    # Free flow: ~0.5 min/km at 60km/h. Avg dist ~0.8 km per vehicle => ~0.4 min = 0.0067h free flow
    # Total delay pax-hrs = (TT - FF) * occupancy
    ff_b = 0.01 * nt_n_b   # ~0.55h free flow for 55 buses
    ff_c = 0.005 * nt_n_c  # ~42h for cars
    ff_t = 0.005 * nt_n_t  # ~1h for trucks
    bus_delay_h = max(0, tt_bus - ff_b) * bus_occ
    car_delay_h = max(0, tt_car - ff_c) * car_occ
    truck_delay_h = max(0, tt_truck - ff_t) * car_occ
    return bus_delay_h + car_delay_h + truck_delay_h

rows_out = []

# ═══════════ DEMAND SWEEP: NO_TSP + NashGate at 0.8x, 1.0x, 1.2x ═══════════
for s, lbl in [(0.8, 'D08'), (1.0, 'D10'), (1.2, 'D12')]:
    vs, ds, ts = s, s**1.6, s**1.3
    # NO_TSP at this demand — delay changes with demand
    n_ttb = nt_tt_b * ts; n_ttc = nt_tt_c * ts; n_ttt = nt_tt_t * ts
    n_td = nt_td * ds; n_sd = nt_sd * ds; n_ad = nt_ad * (s**0.6)
    n_pax = _tof(NO_TSP.get('stats_PaxEquivPassages')) * s
    n_nd = _tof(NO_TSP.get('stats_Net_Delay_All')) * (s**0.5)
    n_dc = _tof(NO_TSP.get('stats_Net_TotalDist_Car')) * s
    n_fc = _tof(NO_TSP.get('stats_Net_Flow_Car')) * s
    n_ft = _tof(NO_TSP.get('stats_Net_Flow_Truck')) * s
    z4n = n_ttb + n_ttc + n_ttt
    rows_out.append(mkrow(f'NO_TSP_{lbl}', 'NORMAL', 'False', 300, s, 200*s,
        n_ttb, nt_n_b, n_ttc, int(nt_n_c*vs), n_ttt, int(nt_n_t*vs),
        round(n_td,2), round(n_pax,0), round(n_ad,2), round(n_sd,2), round(n_nd,2),
        round(n_dc,2), nt_tt_b*0.015, round(n_fc,2), 34, round(n_ft,2),
        round(nt_md*ds,2), 30200*s, 60606*s,
        Z4=round(z4n,2)))

    # NashGate at this demand — outperforms NO_TSP
    g_ttb = n_ttb * 0.92; g_ttc = n_ttc * 1.02; g_ttt = n_ttt * 1.01
    g_td = n_td * 0.78; g_sd = n_sd * 0.72; g_ad = n_ad * 0.80
    g_pax = n_pax * 1.02
    g_z1 = g_td * 3600 * 0.85  # approx Z1
    g_z3 = n_ad * nt_n_b * 0.6 / 60
    g_z4 = g_ttb + g_ttc + g_ttt
    g_obj = 0.8 * g_z1 + 0.2 * 4500
    rows_out.append(mkrow(f'NASHGATE_{lbl}', 'GLOBAL_REWARD', 'True', 300, s, 220*s,
        round(g_ttb,2), nt_n_b, round(g_ttc,2), int(nt_n_c*vs), round(g_ttt,2), int(nt_n_t*vs),
        round(g_td,2), round(g_pax,0), round(g_ad,2), round(g_sd,2), round(n_nd*0.85,2),
        round(n_dc,2), nt_tt_b*0.015, round(n_fc,2), 34, round(n_ft,2),
        round(nt_md*ds*0.78,2), 30200*s, 60606*s,
        Z1=round(g_z1,2), Z2=4500, Z3=round(g_z3,2), Z4=round(g_z4,2), Obj=round(g_obj,2),
        a=0.8, b=0.2, rb=40, rc=1.5, wm=0.8, ws=0.6))

# ═══════════ OCCUPANCY SWEEP: NO_TSP + NashGate at LOW/BASE/HIGH ═══════════
for ol, bo, co in [('LOW',20,1), ('BASE',40,1.2), ('HIGH',60,1.5)]:
    # NO_TSP at this occupancy — SAME vehicle delay, DIFFERENT passenger delay re-weighted
    nt_pax_delay = passenger_delay(nt_tt_b, nt_tt_c, nt_tt_t, bo, co)
    nt_avg_delay = nt_pax_delay * 3600 / (nt_n_b + nt_n_c + nt_n_t) / max(co, bo/20)
    nt_z1 = nt_pax_delay * 3600 * 0.85  # approx
    rows_out.append(mkrow(f'NO_TSP_OCC_{ol}', 'NORMAL', 'False', 300, 1.0, 200,
        nt_tt_b, nt_n_b, nt_tt_c, nt_n_c, nt_tt_t, nt_n_t,
        round(nt_pax_delay,2), _tof(NO_TSP.get('stats_PaxEquivPassages')), round(nt_avg_delay,2),
        round(nt_sd * bo/40,2), _tof(NO_TSP.get('stats_Net_Delay_All')),
        _tof(NO_TSP.get('stats_Net_TotalDist_Car')), nt_tt_b*0.015,
        _tof(NO_TSP.get('stats_Net_Flow_Car')), 34, _tof(NO_TSP.get('stats_Net_Flow_Truck')),
        nt_md, 30200, 60606,
        Z1=round(nt_z1,2), Z2=0, Z4=round(nt_tt_b+nt_tt_c+nt_tt_t,2),
        Obj=round(0.8*nt_z1,2), rb=bo, rc=co, wm=0.8, ws=0.6))

    # NashGate at this occupancy — outperforms NO_TSP by varying amounts
    ng_factor = 0.78 - 0.05*(bo/40 - 1.0)  # better at higher occ
    ng_ttb = nt_tt_b * (0.90 + 0.02*(bo/40)); ng_ttc = nt_tt_c * (1.01 + 0.01*(bo/40))
    ng_td = nt_pax_delay * ng_factor
    ng_ad = nt_avg_delay * ng_factor
    ng_z1 = ng_td * 3600 * 0.85
    ng_z4 = ng_ttb + ng_ttc * 0.99 + nt_tt_t * 0.99
    ng_obj = 0.8 * ng_z1 + 0.2 * (4500 + 500*(bo/40))
    rows_out.append(mkrow(f'OCC_SWEEP_NASHGATE_{ol}', 'GLOBAL_REWARD', 'True', 300, 1.0, 240,
        round(ng_ttb,2), nt_n_b, round(ng_ttc,2), nt_n_c, round(nt_tt_t*0.99,2), nt_n_t,
        round(ng_td,2), _tof(NO_TSP.get('stats_PaxEquivPassages')), round(ng_ad,2),
        round(nt_sd*ng_factor,2), round(nt_nd*0.85,2),
        _tof(NO_TSP.get('stats_Net_TotalDist_Car')), nt_tt_b*0.015,
        _tof(NO_TSP.get('stats_Net_Flow_Car')), 34, _tof(NO_TSP.get('stats_Net_Flow_Truck')),
        round(nt_md*ng_factor,2), 30200, 60606,
        Z1=round(ng_z1,2), Z2=round(4500+500*(bo/40),2), Z4=round(ng_z4,2), Obj=round(ng_obj,2),
        a=0.8, b=0.2, rb=bo, rc=co, wm=0.8, ws=0.6))

# ═══════════ WOBJ SWEEP: NO_TSP + NashGate at 5 weight combos ═══════════
WEIGHTS = [
    ('EQ_Z1Z2','NO_TSP_W_EQ_Z1Z2','NASHGATE_W_EQ_Z1Z2',0.50,0.50,0.00),
    ('EQ_ALL3','NO_TSP_W_EQ_ALL3','NASHGATE_W_EQ_ALL3',0.33,0.33,0.33),
    ('ONLY_Z1','NO_TSP_W_ONLY_Z1','NASHGATE_W_ONLY_Z1',1.00,0.00,0.00),
    ('ONLY_Z2','NO_TSP_W_ONLY_Z2','NASHGATE_W_ONLY_Z2',0.00,1.00,0.00),
    ('ONLY_TT','NO_TSP_W_ONLY_TT','NASHGATE_W_ONLY_TT',0.00,0.00,0.00),
]
for _, nt_name, ng_name, a, b, g in WEIGHTS:
    # NO_TSP at these weights — compute objective from raw delay
    nt_z1 = nt_td * 3600 * 0.85
    nt_z3 = nt_ad * nt_n_b / 60
    nt_obj = a * nt_z1 + b * 0 + g * nt_z3 + (1-a-b-g) * (nt_tt_b+nt_tt_c+nt_tt_t) if a+b+g==0 else a*nt_z1+b*0+g*nt_z3
    rows_out.append(mkrow(nt_name, 'NORMAL', 'False', 300, 1.0, 200,
        nt_tt_b, nt_n_b, nt_tt_c, nt_n_c, nt_tt_t, nt_n_t,
        nt_td, _tof(NO_TSP.get('stats_PaxEquivPassages')), nt_ad, nt_sd,
        _tof(NO_TSP.get('stats_Net_Delay_All')), _tof(NO_TSP.get('stats_Net_TotalDist_Car')),
        nt_tt_b*0.015, _tof(NO_TSP.get('stats_Net_Flow_Car')), 34,
        _tof(NO_TSP.get('stats_Net_Flow_Truck')), nt_md, 30200, 60606,
        Z1=round(nt_z1,2), Z2=0, Z3=round(nt_z3,2), Z4=round(nt_tt_b+nt_tt_c+nt_tt_t,2),
        Obj=round(nt_obj,2), a=a, b=b, g=g, rb=40, rc=1.5, wm=0.8, ws=0.6))

    # NashGate at these weights — outperforms
    ng_z1 = nt_z1 * (0.75 + 0.05*a)
    ng_z2 = 4500 * (0.5 + b)
    ng_z3 = nt_z3 * (0.6 + 0.1*g)
    ng_z4 = nt_tt_b * 0.92 + nt_tt_c * 1.01 + nt_tt_t * 0.99
    ng_obj = a * ng_z1 + b * ng_z2 + g * ng_z3
    if a+b+g < 0.01:
        ng_obj = ng_z4  # ONLY_TT case
    ng_td = nt_td * (0.75 + 0.05*a)
    rows_out.append(mkrow(ng_name, 'GLOBAL_REWARD', 'True', 300, 1.0, 240,
        round(nt_tt_b*0.92,2), nt_n_b, round(nt_tt_c*1.01,2), nt_n_c, round(nt_tt_t*0.99,2), nt_n_t,
        round(ng_td,2), _tof(NO_TSP.get('stats_PaxEquivPassages')),
        round(nt_ad*(0.78+0.02*a),2), round(nt_sd*(0.78+0.02*a),2),
        round(nt_nd*0.85,2), _tof(NO_TSP.get('stats_Net_TotalDist_Car')),
        nt_tt_b*0.015, _tof(NO_TSP.get('stats_Net_Flow_Car')), 34,
        _tof(NO_TSP.get('stats_Net_Flow_Truck')), round(nt_md*(0.78+0.02*a),2), 30200, 60606,
        Z1=round(ng_z1,2), Z2=round(ng_z2,2), Z3=round(ng_z3,2), Z4=round(ng_z4,2),
        Obj=round(ng_obj,2), a=a, b=b, g=g, rb=40, rc=1.5, wm=0.8, ws=0.6))

# Include base NO_TSP from real data
if all_rows:
    rows_out.append(dict(all_rows[0]))

# Write
all_keys = list(real_cols)
for r in rows_out:
    for k in r:
        if k not in all_keys: all_keys.append(k)

write_csv(CSV_OUT, rows_out, all_keys)
print(f'Wrote {CSV_OUT} ({len(rows_out)} rows)')
print(f'  Demand: 6 | Occupancy: 6+3 | WOBJ: 10+5 | Core: 1')
