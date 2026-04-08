# intersection_configs.py
# Logan Rd Corridor – Selective TSP Scenarios
# Only one intersection should be active at a time.

INTERSECTIONS_CONFIG = {
    
    
    
    
     17383: {
        'IntersectionID': 17383,
        'BusPhase': 1,
        'BusPhaseDuration': 60,

        'UpDetList': [
            [86588, 86589, 86590],  # NB
            [86597, 86596, 86594],  # SB
        ],

        'BusDet': [86588, 86589, 86590],
        'BusCallDetectors': [86588, 86589, 86590, 86597, 86596, 86594],
        'BusExitDetectors': [86591, 86592, 86593, 86598, 86599, 86600],

        'DetDistance': [
            [50.0, 50.0, 50.0],
            [21.0, 21.0, 21.0],
        ],

        'NumberOfLanes': 3,
        'VehLength': 4.5,
        'DetLength': 2,
        'JamDensity': 200,
        'SaturationFlow': 1800,
        'SaturationDensity': 36,

        'GE_extension': 10.0,
        'insertion_min_duration': 10.0,
        'insertion_max_duration': 60.0,
        'cycle_length': 120.0,
        'detection_window_m': 50.0,

        'GroupBasedConfig': {
            'sg_list': [],
            'min_green': {},
            'max_green': {},
            'sections': [],
            'bus_det': [86588, 86589, 86590, 86597, 86596, 86594],
            'bus_sg': 1,
            'intergreen_duration': 4.0,
            'starvation_threshold': 240.0,
            'max_extension': 15.0,
        },
    },


    # ============================================================
    # INTERSECTION 19882 (CSV Int. 12 – Arnold St)
    19882: {
        'IntersectionID': 19882,
        'BusPhase': 1,
        'BusPhaseDuration': 60,

        'UpDetList': [
            [86601, 86602],  # NB
            [86607, 86609],  # SB
        ],

        'BusDet': [86601, 86602],
        'BusCallDetectors': [86601, 86602, 86607, 86609],
        'BusExitDetectors': [86604, 86605, 86610, 86611],

        'DetDistance': [
            [37.0, 37.0],
            [50.0, 50.0],
        ],

        'NumberOfLanes': 2,
        'VehLength': 4.5,
        'DetLength': 2,
        'JamDensity': 200,
        'SaturationFlow': 1800,
        'SaturationDensity': 36,

        'GE_extension': 10.0,
        'insertion_min_duration': 10.0,
        'insertion_max_duration': 60.0,
        'cycle_length': 120.0,
        'detection_window_m': 50.0,

        'GroupBasedConfig': {
            'sg_list': [],
            'min_green': {},
            'max_green': {},
            'sections': [],
            'bus_det': [86601, 86602, 86607, 86609],
            'bus_sg': 1,
            'intergreen_duration': 4.0,
            'starvation_threshold': 240.0,
            'max_extension': 15.0,
        },
    },


    # ============================================================
    # INTERSECTION 21895 (CSV Int. 17 – Sackville St)
    21895: {
        'IntersectionID': 21895,
        'BusPhase': 1,
        'BusPhaseDuration': 60,

        'UpDetList': [
            [86675, 86676, 86677],  # NB
            [86681, 86682, 86683],  # SB
        ],

        'BusDet': [86675, 86676, 86677],
        'BusCallDetectors': [86675, 86676, 86677, 86681, 86682, 86683],
        'BusExitDetectors': [86678, 86679, 86680, 86667, 86668, 86669],

        'DetDistance': [
            [50.0, 50.0, 50.0],
            [50.0, 50.0, 50.0],
        ],

        'NumberOfLanes': 3,
        'VehLength': 4.5,
        'DetLength': 2,
        'JamDensity': 200,
        'SaturationFlow': 1800,
        'SaturationDensity': 36,

        'GE_extension': 10.0,
        'insertion_min_duration': 10.0,
        'insertion_max_duration': 60.0,
        'cycle_length': 120.0,
        'detection_window_m': 50.0,

        'GroupBasedConfig': {
            'sg_list': [],
            'min_green': {},
            'max_green': {},
            'sections': [],
            'bus_det': [86675, 86676, 86677, 86681, 86682, 86683],
            'bus_sg': 1,
            'intergreen_duration': 4.0,
            'starvation_threshold': 240.0,
            'max_extension': 15.0,
        },
    },


    # ============================================================
    # INTERSECTION 19474 (CSV Int. 21 – Cornwall St)
    19474: {
        'IntersectionID': 19474,
        'BusPhase': 1,
        'BusPhaseDuration': 60,

        'UpDetList': [
            [86722, 86723, 86724],  # NB
            [86728, 86729, 86730],  # SB
        ],

        'BusDet': [86722, 86723, 86724],
        'BusCallDetectors': [86722, 86723, 86724, 86728, 86729, 86730],
        'BusExitDetectors': [86726, 86725, 86727, 86732, 86733, 86734],

        'DetDistance': [
            [50.0, 50.0, 50.0],
            [30.0, 30.0, 30.0],
        ],

        'NumberOfLanes': 3,
        'VehLength': 4.5,
        'DetLength': 2,
        'JamDensity': 200,
        'SaturationFlow': 1800,
        'SaturationDensity': 36,

        'GE_extension': 10.0,
        'insertion_min_duration': 10.0,
        'insertion_max_duration': 60.0,
        'cycle_length': 120.0,
        'detection_window_m': 50.0,

        'GroupBasedConfig': {
            'sg_list': [],
            'min_green': {},
            'max_green': {},
            'sections': [],
            'bus_det': [86722, 86723, 86724, 86728, 86729, 86730],
            'bus_sg': 1,
            'intergreen_duration': 4.0,
            'starvation_threshold': 240.0,
            'max_extension': 15.0,
        },
    },


    # ============================================================
    # INTERSECTION 17249 (CSV Int. 23 – Old Cleveland Road)
    17249: {
        'IntersectionID': 17249,
        'BusPhase': 1,
        'BusPhaseDuration': 60,

        'UpDetList': [
            [86847, 86848],  # NB
            [86751],         # SB
        ],

        'BusDet': [86847, 86848],
        'BusCallDetectors': [86847, 86848, 86751],
        'BusExitDetectors': [86849, 86753, 86754],

        'DetDistance': [
            [50.0, 50.0],
            [50.0],
        ],

        'NumberOfLanes': 2,
        'VehLength': 4.5,
        'DetLength': 2,
        'JamDensity': 200,
        'SaturationFlow': 1800,
        'SaturationDensity': 36,

        'GE_extension': 10.0,
        'insertion_min_duration': 10.0,
        'insertion_max_duration': 60.0,
        'cycle_length': 120.0,
        'detection_window_m': 50.0,

        'GroupBasedConfig': {
            'sg_list': [],
            'min_green': {},
            'max_green': {},
            'sections': [],
            'bus_det': [86847, 86848, 86751],
            'bus_sg': 1,
            'intergreen_duration': 4.0,
            'starvation_threshold': 240.0,
            'max_extension': 15.0,
        },
    },

 
    
    
    

    # ============================================================
    # INTERSECTION 19196 (CSV Int. 2 – Klumpp Rd/Dawson Rd)
    19196: {
        'IntersectionID': 19196,
        'BusPhase': 1,
        'BusPhaseDuration': 60,

        'UpDetList': [
            [86484, 86485],      # NB
            [86489, 86490],      # SB
        ],

        'BusDet': [86484, 86485],
        'BusCallDetectors': [86484, 86485, 86489, 86490],
        'BusExitDetectors': [86486, 86487, 86493, 86494],

        'DetDistance': [
            [50.0, 50.0],
            [50.0, 50.0],
        ],

        'NumberOfLanes': 2,
        'VehLength': 4.5,
        'DetLength': 2,
        'JamDensity': 200,
        'SaturationFlow': 1800,
        'SaturationDensity': 36,

        'GE_extension': 10.0,
        'insertion_min_duration': 10.0,
        'insertion_max_duration': 60.0,
        'cycle_length': 120.0,
        'detection_window_m': 50.0,

        'GroupBasedConfig': {
            'sg_list': [],
            'min_green': {},
            'max_green': {},
            'sections': [],
            'bus_det': [86484, 86485, 86489, 86490],
            'bus_sg': 1,
            'intergreen_duration': 4.0,
            'starvation_threshold': 240.0,
            'max_extension': 15.0,
        },
    },


    # ============================================================
    # INTERSECTION 17963 (CSV Int. 9 – Gordon Pde)
    17963: {
        'IntersectionID': 17963,
        'BusPhase': 1,
        'BusPhaseDuration': 60,

        'UpDetList': [
            [86566, 86567, 86568],
            [86574, 86572],
        ],

        'BusDet': [86566, 86567, 86568],
        'BusCallDetectors': [86566, 86567, 86568, 86574, 86572],
        'BusExitDetectors': [86569, 86570, 86571, 86575, 86576],

        'DetDistance': [
            [40.0, 40.0, 40.0],
            [24.0, 24.0],
        ],

        'NumberOfLanes': 3,
        'VehLength': 4.5,
        'DetLength': 2,
        'JamDensity': 200,
        'SaturationFlow': 1800,
        'SaturationDensity': 36,

        'GE_extension': 10.0,
        'insertion_min_duration': 10.0,
        'insertion_max_duration': 60.0,
        'cycle_length': 120.0,
        'detection_window_m': 50.0,

        'GroupBasedConfig': {
            'sg_list': [],
            'min_green': {},
            'max_green': {},
            'sections': [],
            'bus_det': [86566, 86567, 86568, 86574, 86572],
            'bus_sg': 1,
            'intergreen_duration': 4.0,
            'starvation_threshold': 240.0,
            'max_extension': 15.0,
        },
    },


    # ============================================================
    # INTERSECTION 18942 (CSV Int. 10 – Nursery Rd)
    18942: {
        'IntersectionID': 18942,
        'BusPhase': 1,
        'BusPhaseDuration': 60,

        'UpDetList': [
            [86578, 86579],
            [86583, 86584],
        ],

        'BusDet': [86578, 86579],
        'BusCallDetectors': [86578, 86579, 86583, 86584],
        'BusExitDetectors': [86580, 86581, 86585, 86586],

        'DetDistance': [
            [50.0, 50.0],
            [50.0, 50.0],
        ],

        'NumberOfLanes': 2,
        'VehLength': 4.5,
        'DetLength': 2,
        'JamDensity': 200,
        'SaturationFlow': 1800,
        'SaturationDensity': 36,

        'GE_extension': 10.0,
        'insertion_min_duration': 10.0,
        'insertion_max_duration': 60.0,
        'cycle_length': 120.0,
        'detection_window_m': 50.0,

        'GroupBasedConfig': {
            'sg_list': [],
            'min_green': {},
            'max_green': {},
            'sections': [],
            'bus_det': [86578, 86579, 86583, 86584],
            'bus_sg': 1,
            'intergreen_duration': 4.0,
            'starvation_threshold': 240.0,
            'max_extension': 15.0,
        },
    },

}




