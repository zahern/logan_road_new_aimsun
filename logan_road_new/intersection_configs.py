# ======================================================
# intersection_configs.py -- Logan Road corridor
# Ported from kg (Kelvin Grove) controller logic -- every junction below is
# driven by the SAME intersection_controller.py used for the Kelvin Grove
# corridor (see ../kg/). Detector geometry (UpDetList/BusDet/BusCallDetectors/
# BusExitDetectors/DetDistance) is derived from
# logan_road_corridor_detectors(in).csv, cross-checked against
# Logan_RD_for_QUT_with_detectors.sqlite (all detector/node IDs confirmed to
# exist in the model, except 4 SB detectors each at junctions 22232 and 17249
# -- flagged below, controller skips missing detectors gracefully at runtime).
#
# Signal-group / phase data (SignalGroupIDList, PhaseIndex, GreenPhaseDuration)
# is preserved from the original Aimsun SCATS export for the 9 junctions that
# had it; the remaining junctions run on the controller's phase-index-0
# fallback until their SCATS data is extracted the same way.
#
# Corridor grouping (INTERSECTION_GROUPS / CORRIDOR_ROUTE_GROUPS) is carried
# over UNCHANGED from the previous file for the junctions it already covered
# -- HARMONY mode's corridor pre-arm coordination only works for grouped
# junctions. Newly-added junctions run standalone (fully functional TSP,
# just without corridor ETA hand-off) until real route-sequence order is
# confirmed and they are added to a group.
# ======================================================

INTERSECTIONS_CONFIG = {
    17249: {
        'IntersectionID': 17249,
        'BusPhase': 1,
        'BusPhaseDuration': 28.0,
        'NumberOfPhases': 5,
        'SignalGroupIDList': [[1, 2, 3, 4, 5, 6], [7, 8, 9, 10], [11, 12, 13, 14, 4], [11], [15, 16, 11, 10]],
        'SignalIDLookup': {1: 54532, 2: 54533, 3: 54534, 4: 54535, 5: 64652, 6: 64651, 7: 54536, 8: 54537, 9: 54538, 10: 64653, 11: 54539, 12: 54540, 13: 54541, 14: 64650, 15: 54542, 16: 54543},
        'GreenPhaseDuration': [28.0, 7.0, 17.0, 5.0, 8.0],
        'PhaseIndex': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 17: 0, 18: 0, 19: 0, 20: 0},
        'NumberOfLanes': 3,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86847, 86848, 86751]],
        'BusDet': [86847, 86848, 86751],
        'BusCallDetectors': [86847, 86848, 86751],
        'BusExitDetectors': [86849, 86753, 86754],
        'DetDistance': [[50, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 65.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    17308: {
        'IntersectionID': 17308,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86531, 86532, 86536, 86537]],
        'BusDet': [86531, 86532, 86536, 86537],
        'BusCallDetectors': [86531, 86532, 86536, 86537],
        'BusExitDetectors': [86533, 86534, 86538, 86539],
        'DetDistance': [[50, 50, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    17383: {
        'IntersectionID': 17383,
        'BusPhase': 1,
        'BusPhaseDuration': 6.0,
        'NumberOfPhases': 7,
        'SignalGroupIDList': [[1, 2, 3, 4, 5], [1, 6, 2, 3, 4], [7, 8], [9, 10, 11, 12], [9, 13, 10, 11], [14, 15], [3, 2]],
        'SignalIDLookup': {1: 54567, 2: 54568, 3: 54569, 4: 66036, 5: 66037, 6: 54570, 7: 54571, 8: 54572, 9: 54573, 10: 54574, 11: 54575, 12: 66038, 13: 54576, 14: 54577, 15: 54578},
        'GreenPhaseDuration': [6.0, 29.0, 22.0, 6.0, 18.0, 9.0, 5.0],
        'PhaseIndex': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 17: 0, 18: 0, 19: 0, 20: 0, 21: 0, 22: 0, 23: 0, 24: 0},
        'NumberOfLanes': 3,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86588, 86589, 86590, 86597, 86596, 86594]],
        'BusDet': [86588, 86589, 86590, 86597, 86596, 86594],
        'BusCallDetectors': [86588, 86589, 86590, 86597, 86596, 86594],
        'BusExitDetectors': [86591, 86592, 86593, 86598, 86599, 86600],
        'DetDistance': [[50, 50, 50, 21, 21, 21]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 95.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    17498: {
        'IntersectionID': 17498,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86553, 86555, 86556, 86561, 86562]],
        'BusDet': [86553, 86555, 86556, 86561, 86562],
        'BusCallDetectors': [86553, 86555, 86556, 86561, 86562],
        'BusExitDetectors': [86557, 86558, 86559, 86563, 86564],
        'DetDistance': [[33, 33, 33, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    17628: {
        'IntersectionID': 17628,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86498, 86499, 86502, 86503]],
        'BusDet': [86498, 86499, 86502, 86503],
        'BusCallDetectors': [86498, 86499, 86502, 86503],
        'BusExitDetectors': [86500, 86501, 86504, 86505],
        'DetDistance': [[50, 50, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    17963: {
        'IntersectionID': 17963,
        'BusPhase': 1,
        'BusPhaseDuration': 6.0,
        'NumberOfPhases': 6,
        'SignalGroupIDList': [[1, 2, 3, 4, 5], [1, 2, 3, 6, 5], [7, 8, 9, 10], [11, 12, 7, 13, 8, 14], [15, 16], [1]],
        'SignalIDLookup': {1: 54793, 2: 54794, 3: 54795, 4: 66325, 5: 66326, 6: 54796, 7: 54797, 8: 54798, 9: 66327, 10: 66328, 11: 54799, 12: 54800, 13: 54801, 14: 54802, 15: 54803, 16: 54804},
        'GreenPhaseDuration': [6.0, 46.0, 8.0, 15.0, 10.0, 5.0],
        'PhaseIndex': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 17: 0, 18: 0, 19: 0, 20: 0, 21: 0, 22: 0, 23: 0},
        'NumberOfLanes': 3,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86566, 86567, 86568, 86574, 86572]],
        'BusDet': [86566, 86567, 86568, 86574, 86572],
        'BusCallDetectors': [86566, 86567, 86568, 86574, 86572],
        'BusExitDetectors': [86569, 86570, 86571, 86575, 86576],
        'DetDistance': [[40, 40, 40, 24, 24]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 90.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    18044: {
        'IntersectionID': 18044,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86509, 86510, 86514, 86515]],
        'BusDet': [86509, 86510, 86514, 86515],
        'BusCallDetectors': [86509, 86510, 86514, 86515],
        'BusExitDetectors': [86511, 86512, 86516, 86517],
        'DetDistance': [[50, 50, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    18942: {
        'IntersectionID': 18942,
        'BusPhase': 1,
        'BusPhaseDuration': 6.0,
        'NumberOfPhases': 7,
        'SignalGroupIDList': [[1, 2, 3, 4], [1, 2, 5, 4], [5], [6, 5, 7, 8], [9, 7, 6, 5], [10, 11, 12, 13], [14, 15]],
        'SignalIDLookup': {1: 55120, 2: 55121, 3: 66198, 4: 66199, 5: 55122, 6: 55123, 7: 55124, 8: 66200, 9: 55125, 10: 55126, 11: 55127, 12: 55128, 13: 66201, 14: 55129, 15: 55130},
        'GreenPhaseDuration': [6.0, 24.0, 5.0, 6.0, 10.0, 19.0, 15.0],
        'PhaseIndex': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 17: 0, 18: 0, 19: 0, 20: 0, 21: 0, 22: 0, 23: 0},
        'NumberOfLanes': 3,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86578, 86579, 86583, 86584]],
        'BusDet': [86578, 86579, 86583, 86584],
        'BusCallDetectors': [86578, 86579, 86583, 86584],
        'BusExitDetectors': [86580, 86581, 86585, 86586],
        'DetDistance': [[50, 50, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 85.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    19185: {
        'IntersectionID': 19185,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86696, 86698, 86699, 86704, 86705]],
        'BusDet': [86696, 86698, 86699, 86704, 86705],
        'BusCallDetectors': [86696, 86698, 86699, 86704, 86705],
        'BusExitDetectors': [86700, 86701, 86702, 86706, 86707],
        'DetDistance': [[30, 30, 30, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    19196: {
        'IntersectionID': 19196,
        'BusPhase': 1,
        'BusPhaseDuration': 8.0,
        'NumberOfPhases': 7,
        'SignalGroupIDList': [[1, 2, 3, 4], [1, 5, 6, 2], [6], [7, 8, 9, 6, 10], [11, 12, 13], [12, 11, 14], [15, 16, 17]],
        'SignalIDLookup': {1: 55220, 2: 55221, 3: 66884, 4: 66885, 5: 55222, 6: 55223, 7: 55224, 8: 55225, 9: 55226, 10: 66886, 11: 55227, 12: 55228, 13: 66887, 14: 55229, 15: 55230, 16: 55231, 17: 55232},
        'GreenPhaseDuration': [8.0, 20.0, 5.0, 16.0, 8.0, 8.0, 20.0],
        'PhaseIndex': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 17: 0, 18: 0, 19: 0, 20: 0, 21: 0, 22: 0, 23: 0},
        'NumberOfLanes': 3,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86484, 86485, 86489, 86490]],
        'BusDet': [86484, 86485, 86489, 86490],
        'BusCallDetectors': [86484, 86485, 86489, 86490],
        'BusExitDetectors': [86486, 86487, 86493, 86494],
        'DetDistance': [[50, 50, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 85.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    19363: {
        'IntersectionID': 19363,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        # No detector CSV coverage for this junction -- physical bus
        # detection unavailable until detectors are surveyed/added.
        'UpDetList': [],
        'BusDet': [],
        'BusCallDetectors': [],
        'BusExitDetectors': [],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    19474: {
        'IntersectionID': 19474,
        'BusPhase': 1,
        'BusPhaseDuration': 6.0,
        'NumberOfPhases': 5,
        'SignalGroupIDList': [[1, 2, 3, 4, 5], [3, 6, 4, 2, 5], [4, 5, 2], [4, 7, 5, 2], [8, 9, 10, 11]],
        'SignalIDLookup': {1: 65035, 2: 65037, 3: 55339, 4: 55341, 5: 65038, 6: 55340, 7: 55342, 8: 55343, 9: 55344, 10: 55345, 11: 65036},
        'GreenPhaseDuration': [6.0, 18.0, 5.0, 10.0, 31.0],
        'PhaseIndex': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 17: 0, 18: 0, 19: 0, 20: 0, 21: 0},
        'NumberOfLanes': 3,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86722, 86723, 86724, 86728, 86729, 86730]],
        'BusDet': [86722, 86723, 86724, 86728, 86729, 86730],
        'BusCallDetectors': [86722, 86723, 86724, 86728, 86729, 86730],
        'BusExitDetectors': [86726, 86725, 86727, 86732, 86733, 86734],
        'DetDistance': [[50, 50, 50, 30, 30, 30]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 70.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    19882: {
        'IntersectionID': 19882,
        'BusPhase': 1,
        'BusPhaseDuration': 6.0,
        'NumberOfPhases': 4,
        'SignalGroupIDList': [[1, 2, 3], [4, 5, 1, 6, 7, 2], [8, 9, 10, 11, 12], [8, 9, 13, 10, 11, 14]],
        'SignalIDLookup': {1: 55500, 2: 55501, 3: 65938, 4: 55502, 5: 55503, 6: 55504, 7: 55505, 8: 55506, 9: 55507, 10: 55508, 11: 55509, 12: 65939, 13: 55510, 14: 55511},
        'GreenPhaseDuration': [6.0, 77.0, 8.0, 9.0],
        'PhaseIndex': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 17: 0, 18: 0, 19: 0, 20: 0},
        'NumberOfLanes': 3,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86601, 86602, 86607, 86609]],
        'BusDet': [86601, 86602, 86607, 86609],
        'BusCallDetectors': [86601, 86602, 86607, 86609],
        'BusExitDetectors': [86604, 86605, 86610, 86611],
        'DetDistance': [[37, 37, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 100.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    20270: {
        'IntersectionID': 20270,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86654, 86653, 86651]],
        'BusDet': [86654, 86653, 86651],
        'BusCallDetectors': [86654, 86653, 86651],
        'BusExitDetectors': [86655, 86656, 86657],
        'DetDistance': [[20, 20, 20]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    20280: {
        'IntersectionID': 20280,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86519, 86520, 86525, 86524]],
        'BusDet': [86519, 86520, 86525, 86524],
        'BusCallDetectors': [86519, 86520, 86525, 86524],
        'BusExitDetectors': [86522, 86523, 86527, 86528, 86529],
        'DetDistance': [[50, 50, 45, 45]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    20283: {
        'IntersectionID': 20283,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86685, 86686, 86687, 86692, 86693]],
        'BusDet': [86685, 86686, 86687, 86692, 86693],
        'BusCallDetectors': [86685, 86686, 86687, 86692, 86693],
        'BusExitDetectors': [86688, 86689, 86690, 86694, 86695],
        'DetDistance': [[50, 50, 50, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    20844: {
        'IntersectionID': 20844,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86462, 86463, 86478, 86489]],
        'BusDet': [86462, 86463, 86478, 86489],
        'BusCallDetectors': [86462, 86463, 86478, 86489],
        'BusExitDetectors': [86472, 86473, 86481, 86482],
        'DetDistance': [[50, 50, 48, 48]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    21197: {
        'IntersectionID': 21197,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86625, 86626, 86645, 86646, 86647]],
        'BusDet': [86625, 86626, 86645, 86646, 86647],
        'BusCallDetectors': [86625, 86626, 86645, 86646, 86647],
        'BusExitDetectors': [86641, 86642, 86643, 86634, 86635, 86636],
        'DetDistance': [[50, 50, 50, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    21553: {
        'IntersectionID': 21553,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86612, 86614, 86618, 86619]],
        'BusDet': [86612, 86614, 86618, 86619],
        'BusCallDetectors': [86612, 86614, 86618, 86619],
        'BusExitDetectors': [86616, 86615, 86621, 86622],
        'DetDistance': [[30, 30, 38, 10]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    21847: {
        'IntersectionID': 21847,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86541, 86542, 86548, 86550]],
        'BusDet': [86541, 86542, 86548, 86550],
        'BusCallDetectors': [86541, 86542, 86548, 86550],
        'BusExitDetectors': [86546, 86547, 86551, 86552],
        'DetDistance': [[40, 40, 30, 30]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    21895: {
        'IntersectionID': 21895,
        'BusPhase': 1,
        'BusPhaseDuration': 8.0,
        'NumberOfPhases': 5,
        'SignalGroupIDList': [[1, 2, 3, 4], [5, 1, 6, 7, 2], [8, 9, 10], [11, 12, 13], [14, 11, 12]],
        'SignalIDLookup': {1: 56241, 2: 56243, 3: 65138, 4: 65136, 5: 56244, 6: 56245, 7: 56242, 8: 56246, 9: 56247, 10: 56248, 11: 56250, 12: 56251, 13: 65137, 14: 56249},
        'GreenPhaseDuration': [8.0, 38.0, 9.0, 6.0, 4.0],
        'PhaseIndex': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 17: 0, 18: 0},
        'NumberOfLanes': 3,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86675, 86676, 86677, 86681, 86682, 86683]],
        'BusDet': [86675, 86676, 86677, 86681, 86682, 86683],
        'BusCallDetectors': [86675, 86676, 86677, 86681, 86682, 86683],
        'BusExitDetectors': [86678, 86679, 86680, 86667, 86668, 86669],
        'DetDistance': [[50, 50, 50, 50, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 65.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    22232: {
        'IntersectionID': 22232,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86736, 86737, 86842, 86841]],
        'BusDet': [86736, 86737, 86842, 86841],
        'BusCallDetectors': [86736, 86737, 86842, 86841],
        'BusExitDetectors': [86739, 86738, 86843, 86844],
        'DetDistance': [[50, 50, 50, 50]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    22400: {
        'IntersectionID': 22400,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86711, 86712, 86715, 86716, 86717]],
        'BusDet': [86711, 86712, 86715, 86716, 86717],
        'BusCallDetectors': [86711, 86712, 86715, 86716, 86717],
        'BusExitDetectors': [86713, 86714, 86718, 86719, 86720],
        'DetDistance': [[50, 50, 40, 40, 40]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
    22603: {
        'IntersectionID': 22603,
        'BusPhase': 1,
        # BusPhaseDuration omitted -- auto-discovered from the live
        # Aimsun signal plan at controller init (GetPhaseDuration).
        # SignalGroupIDList / PhaseIndex not yet extracted from Aimsun
        # SCATS export for this junction -- controller falls back to
        # per-phase-index-0 bookkeeping (works, just less granular).
        'NumberOfLanes': 2,
        'SaturationFlow': 1800,
        'JamDensity': 150,
        'SaturationDensity': 35,
        'CarOcc': 1.2,
        'BusOcc': 40.0,
        'VehLength': 4.5,
        'DetLength': 2,
        # -- detector geometry (from logan_road_corridor_detectors(in).csv) --
        # Bus-phase through movement serves NB+SB together (standard arterial
        # coordinated-phase signal plan) -- both directions feed BusDet so a
        # bus in EITHER direction can trigger priority on the shared phase.
        'UpDetList': [[86661, 86662, 86663, 86667, 86668, 86669]],
        'BusDet': [86661, 86662, 86663, 86667, 86668, 86669],
        'BusCallDetectors': [86661, 86662, 86663, 86667, 86668, 86669],
        'BusExitDetectors': [86664, 86665, 86666, 86670, 86671, 86672],
        'DetDistance': [[20, 30, 30, 45, 45, 45]],
        # MainSections / SideSections intentionally omitted -- the controller
        # auto-classifies approach sections as main (N-S, Logan Rd through)
        # vs side (E-W, cross street) from junction/section geometry at Aimsun
        # runtime (_classify_sections_by_geometry), covering both directions.
        'cycle_length': 135.0,
        'detection_window_m': 50.0,
        'GE_extension': 10.0,
        'insertion_min_duration': 5.0,
        'insertion_max_duration': 20.0,
        'priority_pt_line_ids': [],
    },
}

# Preserved unchanged from the pre-port file -- see module docstring above.
INTERSECTION_GROUPS = {'logan_north': [17249, 17383, 17963, 18942], 'logan_south': [19196, 19474, 19882, 21895]}

CORRIDOR_ROUTE_GROUPS = {'logan_north': [17249, 17308, 17383, 17498, 17628, 17963, 18044, 18942], 'logan_south': [19196, 19363, 19474, 19882, 21895]}

TSP_ACTIVE_INTERSECTIONS = None   # None = all configured junctions active

# Simple label lookup (matches kg's convention) — consumed by generate_dashboard.py
# to distinguish active vs passive corridor junctions. All 24 junctions here are
# in INTERSECTIONS_CONFIG (active), so there are no passive junctions to report.
Inter = {iid: f'INT{iid}' for iid in INTERSECTIONS_CONFIG}
