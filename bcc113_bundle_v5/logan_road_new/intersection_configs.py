# ======================================================
# intersection_configs.py -- Logan Road corridor
# Minimal config: only intersection IDs.
# The controller discovers phases, signal groups, sections,
# detector geometry, and cycle lengths from the Aimsun model
# at runtime.
# ======================================================

INTERSECTIONS_CONFIG = {
    17249: {'IntersectionID': 17249, 'MainSections': [8520, 60333]},
    17308: {'IntersectionID': 17308},
    17383: {'IntersectionID': 17383, 'MainSections': [10693, 60580]},
    17498: {'IntersectionID': 17498},
    17628: {'IntersectionID': 17628},
    17963: {'IntersectionID': 17963},
    18044: {'IntersectionID': 18044},
    18942: {'IntersectionID': 18942},
    19185: {'IntersectionID': 19185, 'MainSections': [5613, 16150, 16755],
            'SideSections': [60448, 60462]},
    19196: {'IntersectionID': 19196},
    19363: {'IntersectionID': 19363},
    19474: {'IntersectionID': 19474},
    19882: {'IntersectionID': 19882},
    20270: {'IntersectionID': 20270, 'MainSections': [8325, 60520],
            'SideSections': [8257]},
    20280: {'IntersectionID': 20280, 'MainSections': [9211, 8182],
            'SideSections': [4321, 61353, 61367]},
    20283: {'IntersectionID': 20283},
    20844: {'IntersectionID': 20844, 'MainSections': [10362, 16970],
            'SideSections': [61482]},
    21197: {'IntersectionID': 21197, 'MainSections': [8732, 15537, 60544],
            'SideSections': [3161, 11416, 16440]},
    21553: {'IntersectionID': 21553},
    21847: {'IntersectionID': 21847},
    21895: {'IntersectionID': 21895},
    22232: {'IntersectionID': 22232},
    # 22400 (Julliette St) removed entirely: uncontrolled/fixed-time junction —
    # no controller, no stats registration, no detection/section inspection.
    22603: {'IntersectionID': 22603, 'MainSections': [3690, 60499],
            'SideSections': [3804]},
}

INTERSECTION_GROUPS = {'logan_north': [17249, 17383, 17963, 18942], 'logan_south': [19196, 19474, 19882, 21895]}

CORRIDOR_ROUTE_GROUPS = {'logan_north': [17249, 17308, 17383, 17498, 17628, 17963, 18044, 18942], 'logan_south': [19196, 19363, 19474, 19882, 21895]}

TSP_ACTIVE_INTERSECTIONS = None

Inter = {iid: f'INT{iid}' for iid in INTERSECTIONS_CONFIG}
