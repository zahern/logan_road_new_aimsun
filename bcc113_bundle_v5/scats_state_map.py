"""scats_state_map.py -- SCATS-grounded state channels for TSP learners.

Parses nothing at runtime: hand-compiled from the NGEN LST personalities
(South/B0xxx + North/B0xxx, *!CNx/*CDx classes, FUND demand roles, *!DNx
positions). Gives every learning controller the SAME structural picture of
an intersection that SCATS itself uses, instead of rediscovering it from
raw detector lists.

CHANNEL SCHEMA (site-level, direction-free on purpose):
  ART_CALL  arterial through call (CALLA-group demand on arterial classes)
  ART_PRES  arterial presence (PRESA-group demand)
  RT_BAY    dedicated turn-bay detectors (spillback risk into through lanes)
  SIDE      side-street call demand
  SLIP      slip-lane detectors (free-flow context, de-weight in queues)
  PED       pedestrian buttons/demands (phase-blocking context)
  COUNT     counting-only loops (EXPLICIT EXCLUSION list for queue measurement)

Channel-assignment rules (applied uniformly, uncertainties noted per class):
  1. Class name carries a turn token (RT/R/TURN/U-Turn/RIGHT, not THRU)
     -> RT_BAY. 2. Name carries SLIP -> SLIP. 3. COUNT/Counting or no
  qualifying FUND -> COUNT. 4. Ped buttons (BUTx) -> PED. 5. Cross-street
  names (Chatsworth, Arnold, Holland, Nursery, Gordon, ... -- see SITE notes)
  -> SIDE. 6. Numbered SG classes: CALLA-group FUND -> ART_CALL,
  CALLB/C/D-group FUND -> SIDE (SCATS controller-letter convention).
  7. Name beats letter-rule on conflict (e.g. 630/A1 VICTOR -> SIDE).

WHAT THIS DOES NOT DO: map SCATS detector numbers (1-14) to Aimsun detector
IDs (86xxx/11137xxx) -- the Aimsun dump stores empty detector names, so the
mapping must come from model geometry (SCATS *!DNx L/C/R side + lane +
approach, matched to Aimsun detector lane/section). Until that map exists,
consume channels like this:
  - COUNT: drop these detectors from queue/delay measurement NOW (needs only
    the Aimsun IDs you already configure; match by lane+approach geometry).
  - RT_BAY / SIDE / PED / ART_CALL / ART_PRES: wire as state bits once the
    per-site SCATS#->Aimsun-ID map is built (one Aimsun session per site:
    detector properties -> lane/position -> match POS side + class approach).

PROPOSED WIRING (no engine changes in this file):
  - BXT/CELLQU (_bxt_state_bin): 6th binary bin RT_BAY_OCC (turn bay occupied
    now). Table 128 -> 256 states. Highest value: spillback flips GE payoff.
  - CPDQL (_cpdql_state_bin): 5th dim RT_BAY (54 -> 108 states).
  - ZIGDOG_Q: new flags ZIGDOG_Q_STATE_RT / ZIGDOG_Q_STATE_PED mirroring the
    existing ZIGDOG_Q_STATE_QUEUE/_BUS flag pattern (default off).
  - PED_DEM as a decider-side gate (don't extend into a ped-blocked phase),
    not a state dim. Enable new dims ONE at a time (each binary dim ~doubles
    the table) with the existing train seeds before combining.
"""

CHANNELS = ("ART_CALL", "ART_PRES", "RT_BAY", "SIDE", "SLIP", "PED", "COUNT")

# Per site: loc, mapped Aimsun junction (None = unmapped), classes as
# (name, scats_dets, roles, channel, note). Roles abbreviated from FUNDs.
SITES = {
    # ---------------- LOGAN (South personalities) ----------------
    425: {"loc": "Logan Road & Chatsworth Road [GREENSLOPES]", "junction": 19185,
          "pos": {2: "L", 3: "R", 5: "L", 6: "R", 7: "L", 8: "C", 9: "L", 10: "R"},
          "classes": [
              ("A1 V1 Logan Road Outbound SEbound", [5, 6], "CALLA+EXAA", "ART_CALL", ""),
              ("A2 V4 Logan Road Inbound NWbound", [7, 8], "CALLA+EX4A", "ART_CALL", ""),
              ("A3/B1 V2 Logan Road Inbound NWbound Right turn", [9, 10], "PRESB/PRESD/CALLA(F12,d9)", "RT_BAY", "turn bay; det9 also calls"),
              ("C1 V3 Chatsworth Road", [2, 3], "PRESC+EXCA", "SIDE", "cross street"),
              ("Slip lane Logan Road SEbound", [4], "-", "SLIP", ""),
              ("Slip lane Chatsworth Road", [1], "-", "SLIP", "")]},
    426: {"loc": "Logan, Arnold & Yuletide [HOLLAND PARK]", "junction": 19882,
          "pos": {1: "L", 2: "R", 3: "RR", 4: "FR", 7: "L", 8: "R", 9: "RR", 10: "FR"},
          "classes": [
              ("DC2 Logan Rd Inbound", [1, 2], "CALLA+EXAA", "ART_CALL", ""),
              ("DC3 Logan Rd Outbound", [7, 8], "CALLA+EXAA", "ART_CALL", ""),
              ("DC4 Logan Rd Inbound Right turn", [3, 4], "PRESA+EXAA", "RT_BAY", "RR/FR bay positions"),
              ("DC5 Logan Rd Outbound", [9, 10], "PRESA+EXAA", "ART_PRES", "through presence"),
              ("DC6 Arnold St App", [5], "CALLB+EXBA", "SIDE", "cross street"),
              ("DC7 Arnold St Dep", [6], "PRESB+EXBA", "SIDE", ""),
              ("DC8 Yuletide St App", [11], "CALLB+EXBA", "SIDE", ""),
              ("DC9 Yuletide St Dep", [12], "PRESB+EXBA", "SIDE", "")]},
    450: {"loc": "LOGAN & JULIETTE", "junction": None,
          "pos": {1: "L", 2: "C", 3: "R", 4: "L", 5: "C", 6: "R", 8: "L", 9: "R"},
          "classes": [
              ("A1", [1, 2, 3], "PRESA+EXAA", "ART_PRES", "junction removed from control (22400)"),
              ("A2", [4, 5, 6], "CALLA+EX2A", "ART_CALL", ""),
              ("COUNTING", [7], "-", "COUNT", ""),
              ("COUNTING2", [8, 9], "-", "COUNT", "")]},
    476: {"loc": "Logan Road and Nicolson Street [GREENSLOPES]", "junction": 22603,
          "pos": {1: "L", 2: "R", 3: "L", 4: "C", 5: "R", 6: "L", 7: "C", 8: "R"},
          "classes": [
              ("A1 Logan Road Northbound", [3, 4, 5], "CALLA+EXAA", "ART_CALL", "L/C/R full approach"),
              ("A2 Logan Road Southbound", [6, 7, 8], "CALLA+EXAA", "ART_CALL", ""),
              ("B1 Nicholson Road", [1, 2], "CALLB+EXBA", "SIDE", "cross street"),
              ("Slip Lane into Nicholson Street", [9], "-", "SLIP", "")]},
    478: {"loc": "Logan Rd & Cornwall St [GREENSLOPES]", "junction": 19474,
          "pos": {1: "L", 2: "C", 3: "R", 5: "L", 6: "C", 7: "R", 8: "L", 9: "C", 10: "R"},
          "classes": [
              ("SG3", [8, 9, 10], "CALLA+EX3A", "ART_CALL", "numbered: A-group -> arterial"),
              ("SG1", [1, 2, 3], "CALLA+EXAA", "ART_CALL", "numbered: A-group -> arterial"),
              ("SG2", [5, 6, 7], "CALLC+EXCA", "SIDE", "numbered: C-group -> side"),
              ("SG4", [11], "CALLB+EXBA", "SIDE", ""),
              ("Cornwall St Westbound Slip Lane", [13], "-", "SLIP", ""),
              ("Cornwall St Eastbound Slip Lane", [4], "-", "SLIP", ""),
              ("I/P 22", [22], "-", "COUNT", "")]},
    486: {"loc": "Logan Rd/Birdwood Rd/Abbotsfield St", "junction": 21197,
          "pos": {1: "L", 2: "C", 3: "R", 4: "A", 5: "D", 8: "L", 9: "C", 10: "R"},
          "classes": [
              ("SG1", [8, 9, 10], "CALLA+EX1A", "ART_CALL", "numbered: A-group -> arterial"),
              ("SG2", [1, 2, 3], "CALLA+EX2A", "ART_CALL", "numbered: A-group -> arterial"),
              ("SG3", [11], "CALLD+EXDA", "SIDE", ""),
              ("SG4", [4, 5], "CALLB+EXBA", "SIDE", ""),
              ("SG7", [14], "CALLC+EXCA", "SIDE", ""),
              ("SG8", [13], "CALLD+EX8A", "SIDE", ""),
              ("Det7-Counter", [7], "-", "COUNT", "")]},
    497: {"loc": "Logan Rd & Ridge St, Greenslopes", "junction": 20283,
          "pos": {1: "L", 2: "R", 4: "C", 5: "R"},
          "classes": [
              ("A1-B3 LOGAN RD SE BND", [1, 2], "CALLA+EX1A", "ART_CALL", ""),
              ("A2 LOGAN RD NW BND", [4, 5], "CALLA+EXAA", "ART_CALL", ""),
              ("B1 LOGAN RD SE BND R/T", [6], "CALLB+EXBA", "RT_BAY", "right-turn bay"),
              ("B2-C2 RIDGE ST NTH BND L/T", [7], "PRESB+EXBA", "RT_BAY", "left-turn bay; spillback semantics"),
              ("C1 RIDGE ST NE BND", [8], "CALLC+EXCA", "SIDE", "cross street"),
              ("A3 Logan Rd Nth Bound LT", [3], "PRESA+EXAA", "RT_BAY", "left-turn presence") ]},
    611: {"loc": "Logan Road, Holland Road & Marshall Road [HOLLAND PARK]", "junction": 17383,
          "pos": {1: "L", 2: "C", 3: "R", 5: "L", 6: "R", 9: "L", 10: "C", 11: "R", 13: "L", 14: "R"},
          "classes": [
              ("A-B Logan Road Inbound", [9, 10, 11], "CALLA+EX1A", "ART_CALL", "L/C/R full approach"),
              ("A-C Logan Road Outbound", [1, 2, 3], "CALLA+EX2A", "ART_CALL", ""),
              ("B-G1 Logan Road Inbound Right turn", [12], "CALLB/CALLG", "RT_BAY", ""),
              ("C-G2 Logan Road Outbound Right turn", [4], "EX4A/CALLG", "RT_BAY", ""),
              ("D1-E-F1 Holland Road Westbound", [13, 14], "CALLE+EX5A", "SIDE", "cross street"),
              ("D1-F1 Holland Road Right turn", [15], "CALLF/CALLD", "RT_BAY", "turn bay on side road"),
              ("D2-E-F2 Marshall Road Eastbound", [5, 6], "CALLE+EX6A", "SIDE", ""),
              ("D2-F2 Marshall Road Right turn", [7], "CALLF/CALLD", "RT_BAY", ""),
              ("DC10 Slip lane Logan into Marshall", [8], "-", "SLIP", "")]},
    612: {"loc": "Logan Rd and Nursery Rd", "junction": 18942,
          "pos": {2: "C", 3: "R", 4: "L", 5: "R", 10: "L", 11: "R", 12: "C", 13: "R"},
          "classes": [
              ("A-B Logan Rd NB", [2, 3], "CALLA+EX1A", "ART_CALL", ""),
              ("A-C Logan Rd SB", [10, 11], "CALLA+EX2A", "ART_CALL", ""),
              ("B-F Logan Rd NB RT", [4, 5], "CALLB/CALLG", "RT_BAY", ""),
              ("C-F Logan Rd SB RT", [12, 13], "EX4A/CALLG", "RT_BAY", ""),
              ("Nursery EB Thru", [14], "CALLD+EXDA", "SIDE", ""),
              ("Nursery EB RT", [15], "CALLD+EXDA", "SIDE", ""),
              ("Nursery WB Thru", [7], "CALLF+EXFA", "SIDE", ""),
              ("Nursery WB RT", [8], "CALLF+EXFA", "SIDE", ""),
              ("Nursery WB slip Lane", [6], "-", "SLIP", ""),
              ("Logan SB slip lane", [9], "-", "SLIP", ""),
              ("DC12-Logan Road NB LT", [1], "CALLA+EXAA", "RT_BAY", "left-turn bay with call") ]},
    613: {"loc": "Logan Rd & Gordon Pde", "junction": 17963,
          "pos": {1: "L", 2: "R", 3: "L", 4: "C", 5: "R", 8: "L", 9: "R", 10: "L", 11: "R", 14: "SLIP"},
          "classes": [
              ("SG1", [1, 2], "CALLA+EX1A", "ART_CALL", "numbered: A-group -> arterial"),
              ("SG2", [3, 4, 5, 14], "CALLA+EX2A", "ART_CALL", "14 is slip-positioned; rest arterial"),
              ("SG3", [6], "CALLB/CALLE", "SIDE", "B-group -> side"),
              ("SG4", [7], "EX4A/CALLE", "SIDE", "E-overlap on side movement; uncertain, treat as side"),
              ("SG5", [8, 9], "CALLD+EXDA", "SIDE", ""),
              ("SG6", [10, 11], "CALLD+EXDA", "SIDE", "")]},
    614: {"loc": "Logan Rd, Shire Rd, Selborne St [Mount Gravatt]", "junction": 21847,
          "pos": {1: "L", 2: "R", 3: "C", 5: "L", 6: "R", 7: "C", 8: "L", 9: "R", 10: "L", 11: "L"},
          "classes": [
              ("SG1-A1B1", [5, 6], "CALLA+EX1A", "ART_CALL", "A-group -> arterial"),
              ("SG2-A3,C1", [1, 2], "CALLA+EX2A", "ART_CALL", "A-group -> arterial"),
              ("SG3-A2B2E1", [7, 11], "CALLA/CALLN/PRESE", "ART_CALL", "A-group -> arterial; E1 overlap noted"),
              ("SG4-A4,C2,E2", [3, 10], "CALLA/CALLN/PRESE", "ART_CALL", "A-group -> arterial; E2 overlap noted"),
              ("SG5-D", [4], "CALLD+EXDA", "SIDE", "D-group -> side"),
              ("SG6-D1", [8, 9], "CALLD+EXDA", "SIDE", "D-group -> side") ]},
    615: {"loc": "Logan & Creek [MT.GRAVATT]", "junction": 20280,
          "pos": {2: "L", 3: "R", 5: "L", 6: "C", 7: "R", 8: "L", 9: "R", 10: "L", 11: "R"},
          "classes": [
              ("A1 LOGAN OB", [5, 6, 7], "CALLA+EXAA", "ART_CALL", "L/C/R full approach"),
              ("A2 LOGAN IB", [8, 9], "CALLA+EX4A", "ART_CALL", ""),
              ("B1 CREEK RD", [10, 11], "CALLB+EXBA", "SIDE", "cross street"),
              ("C1 CREEK RD", [2, 3], "CALLC+EXCA", "SIDE", ""),
              ("CREEK RD SLIP", [1], "-", "SLIP", ""),
              ("LOGAN RD SLIP", [4], "-", "SLIP", "")]},
    616: {"loc": "LOGAN & BROADWATER", "junction": 18044,
          "pos": {1: "L", 2: "R", 3: "L", 4: "R"},
          "classes": [
              ("O/B LOGAN", [1, 2], "CALLA+EXAA", "ART_CALL", ""),
              ("I/B LOGAN", [3, 4], "CALLA+EX3A", "ART_CALL", ""),
              ("I/B R/T LOGAN", [5], "CALLB+EXBA", "RT_BAY", "right-turn bay"),
              ("L.LANE BROADW", [6], "PRESC+EXCA", "SIDE", ""),
              ("R.LANE BROADW", [7], "CALLC+EXCA", "SIDE", ""),
              ("DC7 COUNTING", [8], "-", "COUNT", "")]},
    617: {"loc": "Logan Rd, Dawson Rd & Klumpp Rd [UPPER MT GRAVATT]", "junction": 19196,
          "pos": {2: "C", 3: "R", 7: "L", 8: "R", 9: "L", 10: "R"},
          "classes": [
              ("A-B", [2, 3], "CALLA+EX1A", "ART_CALL", ""),
              ("A-C", [7, 8], "CALLA+EX2A", "ART_CALL", ""),
              ("B-F", [4], "CALLB/CALLF", "RT_BAY", "turn bay"),
              ("C-F", [9, 10], "EX4A/CALLF", "RT_BAY", "turn bay"),
              ("A33D11", [1], "CALLA+EX1A", "ART_CALL", "single arterial loop"),
              ("E11", [5], "CALLE+EXEA", "SIDE", "E-group -> side"),
              ("E22", [6], "CALLE+EXEA", "SIDE", ""),
              ("D22", [12], "CALLD+EXDA", "SIDE", ""),
              ("DC10", [13], "CALLD+EXDA", "SIDE", ""),
              ("DC11", [14], "CALLD+EXDA", "SIDE", ""),
              ("Count Detectors", [11], "-", "COUNT", "")]},
    625: {"loc": "LOGAN, ELLENA & SACKVILLE", "junction": 21895,
          "pos": {1: "L", 2: "R", 3: "L", 4: "C", 5: "RR", 7: "L", 8: "C", 9: "R", 10: "RF"},
          "classes": [
              ("A1 LOGAN O/B", [3, 4, 5, 10], "PRESA+EXAA", "ART_PRES", "through presence (RR/RF = bay-flare positions noted)"),
              ("A2 LOGAN I/B", [7, 8, 9], "PRESA+EXAA", "ART_PRES", ""),
              ("B1 SACKVILLE", [1, 2], "CALLB+EXBA", "SIDE", "cross street"),
              ("C1 ELLENA", [6], "CALLC+EXCA", "SIDE", "")]},
    626: {"loc": "Logan Road & Plimsoll Street, Greenslopes", "junction": 20270,
          "pos": {1: "L", 2: "C", 3: "R", 4: "L", 5: "C", 6: "R", 7: "APP", 10: "DEP"},
          "classes": [
              ("DC2 Logan Road Southbound", [1, 2, 3], "CALLA+EXAA", "ART_CALL", "L/C/R full SB approach; matches SB-only signal"),
              ("DC3 Logan Road Northbound Right Turn", [7, 10], "CALLB+EXBA", "RT_BAY", "APP/DEP pair on right-turn"),
              ("DC4 Plimsoll Street", [8], "CALLB+EXBA", "SIDE", "cross street"),
              ("Slip Lane Logan Road Southbound", [9], "-", "SLIP", ""),
              ("Counting Logan Road Northbound", [4, 5, 6], "-", "COUNT", "")]},
    630: {"loc": "Logan & Victor [HOLLAND PARK WEST]", "junction": 21553,
          "pos": {1: "R", 2: "Right App", 3: "Right Dep", 5: "L", 6: "R", 7: "L"},
          "classes": [
              ("A1 VICTOR WEST BO", [1, 2, 3, 7], "CALLA+EXAA", "SIDE", "name beats letter-rule: Victor = cross street"),
              ("B1 VICTOR", [4], "CALLB", "SIDE", ""),
              ("A2 LOGAN EAST BO", [5, 6], "CALLA+EXAA", "ART_CALL", "only Logan arterial class (L/R pair)") ]},
    645: {"loc": "Logan Road & Wishart Road", "junction": 17628,
          "pos": {1: "L", 2: "R", 3: "RR", 4: "L", 5: "R", 6: "L", 7: "R", 9: "RF"},
          "classes": [
              ("A1 LOGAN N/B", [1, 2], "CALLA+EX1A", "ART_CALL", ""),
              ("A2 LOGAN S/B", [6, 7], "CALLA+EXAA", "ART_CALL", ""),
              ("B1 R/T TO WISHART", [3, 9], "CALLB+EXBA", "RT_BAY", "RR/RF bay positions"),
              ("C1 WISHART", [4, 5], "CALLC+EXCA", "SIDE", "cross street"),
              ("AMBULANCE EXIT", [8], "-", "COUNT", "special-purpose; exclude from state"),
              ("CANCEL ROUTE", [12], "-", "COUNT", ""),
              ("ROUTE 2", [13], "-", "COUNT", ""),
              ("ROUTE 1", [14], "CALLG+NOCLR", "COUNT", "treat as special; exclude") ]},
    652: {"loc": "Logan & Montague", "junction": 22232,
          "pos": {1: "L", 2: "R", 3: "L", 4: "R", 7: "L", 8: "R"},
          "classes": [
              ("A1 Logan Road Northbound", [1, 2], "CALLA+EXAA", "ART_CALL", ""),
              ("A2 Montague Street Southbound", [3, 4], "CALLA+EX3A", "ART_CALL", "A-group -> arterial; phase-shared with Logan NB"),
              ("A3 Montague Street Southbound Right turn", [5], "CALLB+EXBA", "RT_BAY", "right-turn bay"),
              ("B1 Logan Road Southbound", [7, 8], "CALLC+EXCA", "ART_CALL", "C-letter but Logan Southbound arterial; phases with A2"),
              ("Slip lanes", [], "-", "SLIP", "class exists, no member dets listed") ]},
    653: {"loc": "Old Cleveland Road, Laura Street & Montague Street", "junction": 17249,
          "pos": {1: "L", 2: "R", 3: "L", 5: "R", 7: "L", 8: "R", 9: "L", 10: "R", 11: "L", 12: "R", 13: "L", 14: "R"},
          "classes": [
              ("A-B Old Cleveland Road Outbound", [7, 8], "CALLA+EX4A", "ART_CALL", ""),
              ("A-C Old Cleveland Road Inbound", [2, 3], "CALLA+EX1A", "ART_CALL", ""),
              ("B-F1 Old Cleveland Road Outbound Right turn", [9, 10], "CALLB/CALLF", "RT_BAY", "L/R bay pair"),
              ("C-F2 Old Cleveland Road Inbound Right turn", [4], "EX2A/CALLF", "RT_BAY", ""),
              ("E1 Montague Street", [13, 14], "CALLE+EXEA", "SIDE", "cross street"),
              ("BCEF2 Montague Street Left turn", [11, 12], "CALLF+EX6A", "RT_BAY", "left-turn bay; spillback semantics"),
              ("Slip lanes", [1, 5], "-", "SLIP", ""),
              ("D1 Laura Street", [6], "CALLD+EXDA", "SIDE", "")]},
    692: {"loc": "Logan & Invermore", "junction": 17498,
          "pos": {1: "L", 2: "C", 3: "R", 4: "L", 5: "R"},
          "classes": [
              ("A1C1", [1, 2, 3], "CALLA+EX1A", "ART_CALL", "L/C/R full approach"),
              ("A2", [4, 5], "CALLA+EXAA", "ART_CALL", ""),
              ("C2", [6], "CALLC+EXCA", "SIDE", "C-group -> side"),
              ("B1", [7], "CALLB+EXBA", "SIDE", "B-group -> side"),
              ("Count Only", [8], "-", "COUNT", "")]},
    755: {"loc": "LOGNA RD @ MT GRAVATT CENTRAL", "junction": 17308,
          "pos": {1: "L", 2: "R", 3: "L", 4: "R"},
          "classes": [
              ("A1", [1, 2], "PRESA+EXAA", "ART_PRES", "coordination-only site; presence roles"),
              ("A2", [3, 4], "PRESA+EXAA", "ART_PRES", "")]},
    # ---------------- KG (North personalities) ----------------
    # junction values resolved 2026-10 from the Aimsun KG model export
    # (sumo_bridge/kg_aimsun_dump_fresh.json): each GKNode carries the SCATS
    # site number in its `name`, which fixes site->junction for 11 sites and,
    # by elimination (the only unnamed corridor node), 8129 -> 1043762.
    #   node name   -> junction
    #   176  39572   306  39606 ("KGR-Herston Rd")   307  39590
    #   308  36393   309  36385   310  39593   311  39587   312  39576
    #   313  39578   314  39569   371  38339   8129 1043762 (inferred)
    176: {"loc": "South Pine Rd & Railway Place [ALDERLEY]", "junction": 39572,
          "pos": {1: "L", 2: "R", 3: "APP", 5: "L", 6: "R", 7: "APP", 8: "L", 9: "R", 10: "DEP", 11: "DEP"},
          "classes": [
              ("SG1", [5, 6], "CALLA+EX1A", "ART_CALL", "A-group -> arterial"),
              ("SG2", [1, 2], "CALLA+EX2A", "ART_CALL", "A-group -> arterial"),
              ("SG3", [7, 10], "EX3A/CALLA/CALLN", "ART_CALL", "CALLA present -> arterial; APP/DEP pair"),
              ("SG4", [3, 11], "EX4A/CALLA/CALLN", "ART_CALL", "CALLA present -> arterial"),
              ("SG5", [8, 9], "no qualifying FUND", "SIDE", "no call role; treat as side"),
              ("SG6", [4], "CALLD", "SIDE", "D-group -> side"),
              ("ARTERIALS", [], "PRESA/EXAA/PRESD", "ART_PRES", "arterial presence umbrella") ]},
    306: {"loc": "KELVIN GROVE & HERSTON", "junction": 39606,
          "pos": {1: "L", 2: "C", 3: "R", 4: "APP", 5: "L", 6: "R", 7: "L", 8: "C", 9: "R", 10: "DEP"},
          "classes": [
              ("A1 K.G. I/BOUND", [7, 8, 9], "CALLA+EXAA", "ART_CALL", "L/C/R full approach"),
              ("A2 K.G. O/BOUND", [1, 2, 3], "CALLA+EX2A", "ART_CALL", ""),
              ("B1 K.G. R/TURN", [4, 10], "CALLB+EXBA", "RT_BAY", "APP/DEP pair on right-turn"),
              ("C1 HERSTON", [5, 6], "CALLC", "SIDE", "cross street"),
              ("S/L TO S/EAST", [11], "-", "SLIP", "no DN position listed"),
              ("P3/p2 kerb", [20, 21], "CALLA/CALLB(BUT)", "PED", "kerb push buttons") ]},
    307: {"loc": "Kelvin Grove, Windsor & Bishop", "junction": 39590,
          "pos": {1: "L", 2: "C", 3: "R", 6: "app", 7: "dep", 8: "L", 9: "C", 10: "R"},
          "classes": [
              ("A-B", [8, 9, 10], "CALLA", "ART_CALL", "L/C/R full approach"),
              ("A-C", [1, 2, 3], "CALLA+EX2A", "ART_CALL", ""),
              ("B-E", [11], "CALLB", "RT_BAY", "turn movement"),
              ("C-E", [4], "CALLC/CALLF", "RT_BAY", "turn movement"),
              ("D1", [5], "EX5A", "COUNT", "extend-only; no call"),
              ("D3", [6, 7], "CALLD", "SIDE", "D-group -> side; app/dep pair"),
              ("D2", [12], "PRESE", "SIDE", ""),
              ("D4", [13], "PRESE", "SIDE", "")]},
    308: {"loc": "Enoggera, Parker & Davidson", "junction": 36393,
          "pos": {1: "L", 2: "C", 3: "R", 6: "L", 7: "C", 8: "R"},
          "classes": [
              ("SG1", [6, 7, 8], "CALLA+EXAA", "ART_CALL", "A-group -> arterial; L/C/R full approach"),
              ("SG2", [1, 2, 3], "CALLA+EX2A", "ART_CALL", "A-group -> arterial"),
              ("SG4", [4], "CALLB+EX4A", "SIDE", "B-group -> side"),
              ("SG3", [5], "CALLC", "SIDE", "C-group -> side") ]},
    309: {"loc": "Enoggera Rd, Edmonstone St & Ashgrove Ave", "junction": 36385,
          "pos": {1: "L", 2: "C", 3: "R", 4: "L", 5: "C", 6: "R", 7: "L", 8: "R", 9: "L", 10: "R", 11: "L", 12: "C", 13: "R", 14: "L", 15: "R", 16: "ASH", 17: "ENB", 18: "EDM", 19: "ESB", 20: "RADAR", 21: "RADAR"},
          "classes": [
              ("SG1", [4, 5, 6], "CALLA", "ART_CALL", "A-group -> arterial"),
              ("SG2", [11, 12, 13], "CALLA+EX2A", "ART_CALL", "A-group -> arterial"),
              ("SG3", [7, 8], "CALLB/CALLF", "RT_BAY", "B-group turn pair -> bay"),
              ("SG4", [14, 15], "CALLC/CALLF", "RT_BAY", "C-group turn pair -> bay"),
              ("SG5", [1, 2, 3, 21], "CALLD", "SIDE", "D-group -> side (21 RADAR position)"),
              ("SG6", [9, 10, 20], "no qualifying FUND", "SIDE", "no call role; treat as side"),
              ("COUNT", [16, 17, 18, 19], "-", "COUNT", "named counting loops (street-coded positions)") ]},
    310: {"loc": "Enoggera & Newmarket", "junction": 39593,
          "pos": {1: "R", 2: "C", 3: "L", 6: "R", 7: "L", 8: "R", 9: "C", 10: "L"},
          "classes": [
              ("A1", [1, 2, 3], "CALLA+EXAA", "ART_CALL", "note R/C/L mirrored positioning"),
              ("A2B2", [8, 9, 10], "CALLA", "ART_CALL", ""),
              ("B1", [6, 7], "CALLB/CALLD", "SIDE", "B-group -> side"),
              ("C1", [4], "CALLC", "SIDE", "C-group -> side"),
              ("C2", [5], "EXBA", "COUNT", "extend-only; no call"),
              ("S/LANE TO EAST", [11], "no FUND", "SLIP", "slip lane") ]},
    311: {"loc": "Enoggera Rd near Wickham St [NEWMARKET]", "junction": 39587,
          "pos": {1: "R", 2: "C", 3: "L", 4: "R", 5: "C", 6: "L", 21: "Ped 2", 24: "Ped 1"},
          "classes": [
              ("A1", [1, 2, 3], "CALLA+EXAA", "ART_CALL", "only vehicle call class on site"),
              ("B Special Approach Timers", [4, 5, 6], "no FUND", "SIDE", "special timers, no call role"),
              ("Outer Special Purpose Inputs", [21, 24], "CALLN", "SIDE", "special-purpose inputs") ]},
    312: {"loc": "Enoggera Road and Banks Street, Newmarket", "junction": 39576,
          "pos": {1: "L", 2: "R", 3: "L", 4: "C", 5: "R", 7: "L", 8: "C", 9: "R"},
          "classes": [
              ("A-B Enoggerra NB", [3, 4, 5], "CALLA", "ART_CALL", "L/C/R full NB approach (sic in source)"),
              ("A-C Enoggera SB", [7, 8, 9], "CALLA+EX2A", "ART_CALL", ""),
              ("B-E1 Enoggera U-Turn", [6], "CALLB/EX3A", "RT_BAY", "U-turn bay (no DN position listed)"),
              ("C-E2 Enoggera RT", [10], "CALLC/EX4A", "RT_BAY", "right-turn bay (no DN position listed)"),
              ("D1 Banks Street", [1, 2], "CALLD", "SIDE", "cross street"),
              ("SLIP LANE Enoggera to banks", [11], "no FUND", "SLIP", "no DN position listed") ]},
    313: {"loc": "ENOGGERA & ALDERSON", "junction": 39578,
          "pos": {1: "L", 2: "R", 3: "L", 4: "C", 5: "R", 6: "L", 7: "R", 9: "CL", 10: "CR", 11: "R"},
          "classes": [
              ("SG1", [1, 2, 3], "CALLA", "ART_CALL", "A-group -> arterial"),
              ("SG2", [9, 10, 11], "CALLA+EXAA", "ART_CALL", "A-group -> arterial (CL/CR centre positions)"),
              ("SG3", [6, 7], "CALLC", "SIDE", "C-group -> side"),
              ("SG4", [4], "CALLB+EXBA", "SIDE", "B-group -> side"),
              ("SG5", [8], "CALLA+EXAA", "SIDE", "CALLA role but single-det specials group; side by elimination"),
              ("SLIP", [5], "no FUND", "SLIP", "slip lane") ]},
    314: {"loc": "Enoggera , South-Pine & Samford", "junction": 39569,
          "pos": {1: "L", 2: "R", 3: "L", 4: "R", 5: "L", 6: "C", 7: "R"},
          "classes": [
              ("A3", [1, 2], "CALLA+EX3A", "ART_CALL", "A-group -> arterial"),
              ("A1", [3, 4], "CALLA", "ART_CALL", "A-group -> arterial"),
              ("A2C2", [5, 6, 7], "CALLA+EX2A", "ART_CALL", "A-group -> arterial"),
              ("C1", [8], "CALLC", "SIDE", "C-group -> side"),
              ("DC6", [10], "EXBA", "COUNT", "extend-only; no call"),
              ("DC7", [11], "CALLB+EXBA", "SIDE", "B-group -> side") ]},
    371: {"loc": "Sicklefield & Pckering @ Alderley (sic in source)", "junction": 38339,
          "pos": {1: "L", 2: "R", 3: "L", 4: "R", 7: "L", 8: "R", 11: "C", 12: "R", 14: "Train Inbound", 15: "Train Outbound", 16: "BOOM", 19: "L", 20: "R", 21: "L far", 22: "R far", 23: "L close", 24: "R close"},
          "classes": [
              ("A-B South Pine NB Thru", [3, 4], "CALLA+EX2A", "ART_CALL", ""),
              ("A Sicklefield Rd SB Thru", [1, 2], "CALLA", "ART_CALL", "two arterials cross here; both thru classes arterial"),
              ("C-F South Pine NB", [6], "CALLC/CALLF", "SIDE", "C/F-group on NB leg -> side/turn"),
              ("BF Sicklefield SB", [5], "CALLB/CALLF", "RT_BAY", "bay/flare position on SB leg"),
              ("D Raymont EB Thru", [7, 8], "CALLD", "SIDE", "D-group -> side"),
              ("D Raymont WB RT", [9], "CALLD", "RT_BAY", "right-turn bay"),
              ("E Pickering EB Thru", [10], "no qual FUND", "SIDE", "cross street, no call role"),
              ("E2 Pickering EB Thru/RT", [11, 12], "no qual FUND", "SIDE", ""),
              ("E/D Bike, Train Queue/Input", [14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24], "CALLD(F20 bike only)", "COUNT", "rail/active-transport specials; exclude from state") ]},
    8129: {"loc": "Enoggera Rd & Moran St", "junction": 1043762,
           "pos": {1: "L", 2: "C", 3: "R", 4: "L", 5: "C", 6: "R", 9: "L", 10: "R"},
           "classes": [
               ("A-B", [1, 2, 3], "CALLA", "ART_CALL", "L/C/R full approach"),
               ("A-C", [4, 5, 6], "CALLA+EX2A", "ART_CALL", ""),
               ("B-F", [7], "CALLB/CALLF", "RT_BAY", "turn bay"),
               ("C-F", [8], "CALLC/CALLF", "RT_BAY", "turn bay"),
               ("DC6", [9, 10], "CALLD", "SIDE", "D-group -> side"),
               ("DC7 Driveway Push button", [30], "no qual FUND", "SIDE", "driveway push button") ]},
}


def site_channel_dets(site, channel):
    """SCATS detector numbers for one channel at one site (see module docstring
    for the SCATS#->Aimsun-ID mapping TODO)."""
    s = SITES.get(int(site))
    if not s:
        return []
    out = []
    for name, dets, roles, ch, note in s["classes"]:
        if ch == channel:
            out.extend(dets)
    return sorted(set(out))


def site_summary(site):
    """One-line-per-channel summary for quick inspection."""
    s = SITES.get(int(site))
    if not s:
        return "unknown site %s" % site
    lines = ["site %s (%s) junction=%s" % (site, s["loc"], s["junction"])]
    for ch in CHANNELS:
        d = site_channel_dets(site, ch)
        lines.append("  %-8s %s" % (ch, d))
    return "\n".join(lines)


def arterial_call_sites():
    """Sites with at least one ART_CALL class (TSP-relevant signals)."""
    return sorted(s for s, v in SITES.items()
                  if any(c[3] == "ART_CALL" for c in v["classes"]))
