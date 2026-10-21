import csv, json, os

base = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\logan_road_new\results"
runs = {
 'BEST-delay': 'DCTSP_MP_ECTM_seed600_75206_75207_75210_20261008_114127',
 'WORST': 'DCTSP_MP_ECTM_seed400_75206_75207_75210_20261008_110633',
 'BALANCED': 'DCTSP_MP_ECTM_seed500_75206_75207_75210_20261008_112857',
}
for tag, folder in runs.items():
    d = os.path.join(base, folder)
    print("="*78); print(tag, folder)
    with open(os.path.join(d,'simulation_results.csv'), errors='replace') as f:
        g = list(csv.DictReader(f))[0]
    keys = ['TotalPassDelay_hrs','SidePassDelay_hrs','MainPassDelay_hrs','AvgBusTT_s','StdBusTT_s',
            'AvgPassDelay_s','AvgBusPassDelay_s','AvgCarPassDelay_s','SimBusDelay_pax_s','SimCarDelay_pax_s',
            'TSP_Detections','TSP_Extensions','TSP_Insertions','TSP_Detected_NoAction','TSP_NaturalGreen',
            'TSP_AvgInsertion_s','TSP_AvgInsertionWait_s','TSP_TotalInsertion_s','N_BusTrips','N_DistinctBuses',
            'PaxEquivPassages','BusPaxEquivPassages','Objective_PaxPerDelayHr','Prearm_Fired','Prearm_Success',
            'Prearm_Missed','Prearm_Discarded','Net_AvgSpeed_kmh','SimDuration_hrs']
    for k in keys:
        print(f"  {k:28s} = {g.get(k)}")
    # bus trips: bunching / spread
    with open(os.path.join(d,'bus_trips.csv'), errors='replace') as f:
        bt = list(csv.DictReader(f))
    print(f"  bus_trips rows={len(bt)} cols={bt[0].keys() if bt else None}")
