import pathlib
hpc = open(r'Z:\tsp\sumo_hpc\shared_tsp_engine\engine.py', errors='replace').read()
aim = open(r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\shared_tsp_engine\engine.py', errors='replace').read()
for tag in ['CELLQLEARN_SAT_VETO', 'BUS_QUEUED_SPEED_MS', 'Q_EST_CORRECTION_ALPHA',
            '_qe_geom_warn', 'no geometry for dets', 'TSP_COOLDOWN_OVERRIDE_S',
            'FOCUS_GATE_ENABLED', 'MAX_PREARM_DIST_M', 'DECIDER_COST_VETO_RATIO_GE']:
    print(f'{tag:32s} Aimsun={tag in aim}  SUMO={tag in hpc}')
sp = pathlib.Path(r'Z:\tsp\sumo_hpc\shared_tsp_engine\specialized_modes.py')
h = sp.read_text(errors='replace') if sp.exists() else ''
a = open(r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\shared_tsp_engine\specialized_modes.py',
         errors='replace').read()
print('spm lines: Aimsun', len(a.splitlines()), 'SUMO', len(h.splitlines()) if h else 'MISSING')
for tag in ['MEASURED_SIDE_COST       = True', 'CELLQLEARN_SAT_VETO', '_local_sat']:
    print(f'{tag:32s} Aimsun={tag in a}  SUMO={tag in h}')
# MainSections union in q_scan?
print('MainSections-in-qscan Aimsun=', "Union in cfg['MainSections']" in aim,
      ' SUMO=', "Union in cfg['MainSections']" in hpc)
# routes
import re
for p, t in [('Aimsun', aim), ('SUMO', hpc)]:
    m = re.search(r'CORRIDOR_ROUTE_GROUPS\s*=\s*\{[^}]*\}[^}]*\}', t, re.S)
    print(p, 'has route table:', bool(m))
