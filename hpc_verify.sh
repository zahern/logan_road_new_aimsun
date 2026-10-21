#!/bin/bash
grep -m1 ENGINE_BUILD /home/ahernz/tsp/sumo_hpc/shared_tsp_engine/engine.py
grep -c CORRIDOR_ROUTE_GROUPS /home/ahernz/tsp/sumo_hpc/logan_road_new/intersection_configs.py
ls /home/ahernz/tsp/sumo_hpc/jobs/job_logan_road_new_CHAMP_CELLQ_CONT_DE_train0.pbs /home/ahernz/tsp/sumo_hpc/submit_champ9_seeds_nonlearner.sh 2>&1
head -12 /home/ahernz/tsp/sumo_hpc/jobs/job_logan_road_new_CHAMP_CELLQ_CONT_DE_train0.pbs
