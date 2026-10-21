"""scats_det_map.py -- Aimsun-detector -> SCATS-channel map (Logan + 12 KG sites).

Built from scats_state_map.py (SCATS classes/roles) crossed with the
configured UpDetList groups (CSV/model geometry). Purpose: let learner state
code ask "which SCATS channel does this detector belong to" without
rediscovering intersection structure.

CONFIDENCE: H = name+count match (under the global NB~=Inbound/NW,
SB~=Outbound/SE assumption, stated below); M = count-tie or subset where
every candidate shares the channel; L = approach-level fallback only;
U = unmapped (gap). SPLIT-GROUP = one approach group spans two SCATS
classes (needs model geometry to split members) -- group channel given,
members U.

GLOBAL ASSUMPTION (flagged, not proven): CSV NB ~= SCATS Inbound/North/NW,
SB ~= Outbound/South/SE. It only affects WHICH class a group maps to; the
channel is unaffected wherever tied classes share it (the common case).
Decisive check: Aimsun GUI -> detector 86588 properties -> approach road;
if it serves Logan Rd Inbound, the assumption holds corridor-wide.

LATERAL ORDER (L/C/R vs lane index) is deliberately NOT encoded: channels
are per-class, so within-class permutation cannot change any bit. Per-loop
(SCATS#) identity is a documented non-goal for state bits (needed only if
per-loop ETA features are added later).

Helper API at bottom: channel_of(junction, det_id), group_channel(junction,
group_idx), unmapped(junction).
"""

# conf: H high, M medium (tie/subset, channel-certain), L low (fallback),
#       U unmapped gap.
JUNCTIONS = {
    17249: {"site": 653, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "M",
            "note": "tie A-B-OB[7,8]/A-C-IB[2,3]; both ART",
            "members": {86847: ("ART_CALL", "M", "tie; same channel"),
                        86848: ("ART_CALL", "M", "tie; same channel")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "M",
            "note": "single-lane build; subset of A-C-IB[2,3] or A-B-OB[7,8]",
            "members": {86751: ("ART_CALL", "M", "subset; same channel")}},
    }},
    17308: {"site": 755, "groups": {
        0: {"dir": "NB", "ch": "ART_PRES", "conf": "M",
            "note": "tie A1[1,2]/A2[3,4]; presence roles; coord-only site",
            "members": {86531: ("ART_PRES", "M", "tie"),
                        86532: ("ART_PRES", "M", "tie")}},
        1: {"dir": "SB", "ch": "ART_PRES", "conf": "M",
            "note": "tie A1/A2",
            "members": {86536: ("ART_PRES", "M", "tie"),
                        86537: ("ART_PRES", "M", "tie")}},
    }},
    17383: {"site": 611, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "H",
            "note": "A-B Logan Road Inbound[9,10,11]",
            "members": {86588: ("ART_CALL", "H", ""),
                        86589: ("ART_CALL", "H", ""),
                        86590: ("ART_CALL", "H", "")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "H",
            "note": "A-C Logan Road Outbound[1,2,3]",
            "members": {86597: ("ART_CALL", "H", ""),
                        86596: ("ART_CALL", "H", ""),
                        86594: ("ART_CALL", "H", "")}},
    }},
    17498: {"site": 692, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "H",
            "note": "A1C1[1,2,3]",
            "members": {86553: ("ART_CALL", "H", ""),
                        86555: ("ART_CALL", "H", ""),
                        86556: ("ART_CALL", "H", "")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "H",
            "note": "A2[4,5]",
            "members": {86561: ("ART_CALL", "H", ""),
                        86562: ("ART_CALL", "H", "")}},
    }},
    17628: {"site": 645, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "H",
            "note": "A1 LOGAN N/B[1,2]",
            "members": {86498: ("ART_CALL", "H", ""),
                        86499: ("ART_CALL", "H", "")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "H",
            "note": "A2 LOGAN S/B[6,7]",
            "members": {86502: ("ART_CALL", "H", ""),
                        86503: ("ART_CALL", "H", "")}},
    }},
    17963: {"site": 613, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "M",
            "note": "SG2[3,4,5] through subset (slip 14 excluded)",
            "members": {86566: ("ART_CALL", "M", "SG2 subset"),
                        86567: ("ART_CALL", "M", "SG2 subset"),
                        86568: ("ART_CALL", "M", "SG2 subset")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "H",
            "note": "SG1[1,2]",
            "members": {86574: ("ART_CALL", "H", ""),
                        86572: ("ART_CALL", "H", "")}},
    }},
    18044: {"site": 616, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "M",
            "note": "tie O/B[1,2]/I/B[3,4]; direction O/B<->SB unconfirmed",
            "members": {86509: ("ART_CALL", "M", "tie"),
                        86510: ("ART_CALL", "M", "tie")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "M",
            "note": "tie O/B/I/B",
            "members": {86514: ("ART_CALL", "M", "tie"),
                        86515: ("ART_CALL", "M", "tie")}},
    }},
    18942: {"site": 612, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "H",
            "note": "A-B Logan Rd NB[2,3]",
            "members": {86578: ("ART_CALL", "H", ""),
                        86579: ("ART_CALL", "H", "")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "H",
            "note": "A-C Logan Rd SB[10,11]",
            "members": {86583: ("ART_CALL", "H", ""),
                        86584: ("ART_CALL", "H", "")}},
    }},
    19185: {"site": 425, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "L",
            "note": "SPLIT-GROUP: no size-3 ART class (A1-OB 2, A2-IB 2); "
                    "approach-level fallback; members need geometry to split "
                    "IB-through vs IB-right-turn",
            "members": {86696: (None, "U", "split-group; geometry needed"),
                        86698: (None, "U", "split-group; geometry needed"),
                        86699: (None, "U", "split-group; geometry needed")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "M",
            "note": "tie A1-OB[5,6]/A2-IB[7,8]",
            "members": {86704: ("ART_CALL", "M", "tie"),
                        86705: ("ART_CALL", "M", "tie")}},
    }},
    19196: {"site": 617, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "M",
            "note": "tie A-B[2,3]/A-C[7,8]; A33D11[1] unassigned (single loop)",
            "members": {86484: ("ART_CALL", "M", "tie"),
                        86485: ("ART_CALL", "M", "tie")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "M",
            "note": "tie A-B/A-C",
            "members": {86489: ("ART_CALL", "M", "tie"),
                        86490: ("ART_CALL", "M", "tie")}},
    }},
    19474: {"site": 478, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "M",
            "note": "tie SG3[8,9,10]/SG1[1,2,3]; both ART",
            "members": {86722: ("ART_CALL", "M", "tie"),
                        86723: ("ART_CALL", "M", "tie"),
                        86724: ("ART_CALL", "M", "tie")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "M",
            "note": "tie SG3/SG1",
            "members": {86728: ("ART_CALL", "M", "tie"),
                        86729: ("ART_CALL", "M", "tie"),
                        86730: ("ART_CALL", "M", "tie")}},
    }},
    19882: {"site": 426, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "H",
            "note": "DC2 Logan Rd Inbound[1,2]",
            "members": {86601: ("ART_CALL", "H", ""),
                        86602: ("ART_CALL", "H", "")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "H",
            "note": "DC3 Logan Rd Outbound[7,8]",
            "members": {86607: ("ART_CALL", "H", ""),
                        86609: ("ART_CALL", "H", "")}},
    }},
    20270: {"site": 626, "groups": {
        0: {"dir": "SB", "ch": "ART_CALL", "conf": "H",
            "note": "DC2 Logan Road Southbound[1,2,3]; SB-only signal matches",
            "members": {86654: ("ART_CALL", "H", ""),
                        86653: ("ART_CALL", "H", ""),
                        86651: ("ART_CALL", "H", "")}},
    }},
    20280: {"site": 615, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "M",
            "note": "A2-IB[8,9] exact or A1-OB[5,6,7] subset; direction unconfirmed",
            "members": {86519: ("ART_CALL", "M", "exact-or-subset"),
                        86520: ("ART_CALL", "M", "exact-or-subset")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "M",
            "note": "same ambiguity, mirrored",
            "members": {86525: ("ART_CALL", "M", "exact-or-subset"),
                        86524: ("ART_CALL", "M", "exact-or-subset")}},
    }},
    20283: {"site": 497, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "L",
            "note": "SPLIT-GROUP: likely A2-NW[4,5] + A3-North-LT[3]; "
                    "members need geometry to split through vs turn bay",
            "members": {86685: (None, "U", "split-group; geometry needed"),
                        86686: (None, "U", "split-group; geometry needed"),
                        86687: (None, "U", "split-group; geometry needed")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "M",
            "note": "A1-B3 SE[1,2] likely (SE~=SB); confirm via model",
            "members": {86692: ("ART_CALL", "M", "likely SE class"),
                        86693: ("ART_CALL", "M", "likely SE class")}},
    }},
    20844: {"site": 794, "groups": {
        0: {"dir": "NB", "ch": None, "conf": "U",
            "note": "no SCATS personality (794 missing)",
            "members": {86462: (None, "U", "no personality"),
                        86463: (None, "U", "no personality")}},
        1: {"dir": "SB", "ch": None, "conf": "U",
            "note": "no SCATS personality (794 missing)",
            "members": {86478: (None, "U", "no personality"),
                        86489: (None, "U", "no personality")}},
    }},
    21197: {"site": 486, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "M",
            "note": "subset of SG1[8,9,10] or SG2[1,2,3] (model built 2 of 3)",
            "members": {86625: ("ART_CALL", "M", "subset"),
                        86626: ("ART_CALL", "M", "subset")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "M",
            "note": "tie SG1/SG2 (both size 3, both ART)",
            "members": {86645: ("ART_CALL", "M", "tie"),
                        86646: ("ART_CALL", "M", "tie"),
                        86647: ("ART_CALL", "M", "tie")}},
    }},
    21553: {"site": 630, "groups": {
        0: {"dir": "NB", "ch": None, "conf": "U",
            "note": "GAP: B0630 has no Logan class for this direction "
                    "(only A2 LOGAN EAST BO[5,6]); approach uncovered in SCATS",
            "members": {86612: (None, "U", "no SCATS class"),
                        86614: (None, "U", "no SCATS class")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "H",
            "note": "A2 LOGAN EAST BO[5,6] (EAST~=SE~=SB)",
            "members": {86618: ("ART_CALL", "H", ""),
                        86619: ("ART_CALL", "H", "")}},
    }},
    21847: {"site": 614, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "M",
            "note": "4-way tie SG1/SG2/SG3/SG4 (all size 2, all ART)",
            "members": {86541: ("ART_CALL", "M", "tie"),
                        86542: ("ART_CALL", "M", "tie")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "M",
            "note": "4-way tie, all ART",
            "members": {86548: ("ART_CALL", "M", "tie"),
                        86550: ("ART_CALL", "M", "tie")}},
    }},
    21895: {"site": 625, "groups": {
        0: {"dir": "NB", "ch": "ART_PRES", "conf": "M",
            "note": "A2-IB[7,8,9] exact or A1-OB[3,4,5,10] subset; "
                    "presence (not call) roles at this site",
            "members": {86675: ("ART_PRES", "M", "exact-or-subset"),
                        86676: ("ART_PRES", "M", "exact-or-subset"),
                        86677: ("ART_PRES", "M", "exact-or-subset")}},
        1: {"dir": "SB", "ch": "ART_PRES", "conf": "M",
            "note": "same ambiguity, mirrored; presence roles",
            "members": {86681: ("ART_PRES", "M", "exact-or-subset"),
                        86682: ("ART_PRES", "M", "exact-or-subset"),
                        86683: ("ART_PRES", "M", "exact-or-subset")}},
    }},
    22232: {"site": 652, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "H",
            "note": "A1 Logan Road Northbound[1,2]",
            "members": {86736: ("ART_CALL", "H", ""),
                        86737: ("ART_CALL", "H", "")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "H",
            "note": "B1 Logan Road Southbound[7,8] (C-letter, name wins)",
            "members": {86841: ("ART_CALL", "H", ""),
                        86842: ("ART_CALL", "H", "")}},
    }},
    22603: {"site": 476, "groups": {
        0: {"dir": "NB", "ch": "ART_CALL", "conf": "H",
            "note": "A1 Logan Road Northbound[3,4,5]",
            "members": {86661: ("ART_CALL", "H", ""),
                        86662: ("ART_CALL", "H", ""),
                        86663: ("ART_CALL", "H", "")}},
        1: {"dir": "SB", "ch": "ART_CALL", "conf": "H",
            "note": "A2 Logan Road Southbound[6,7,8]",
            "members": {86667: ("ART_CALL", "H", ""),
                        86668: ("ART_CALL", "H", ""),
                        86669: ("ART_CALL", "H", "")}},
    }},
    # KG corridor (all 12 sites). Groups = kg/intersection_configs.py UpDetList;
    # site ids = Aimsun GKNode names; channels = SCATS class counts, generated by
    # build_scats_det_map.py. EVERY UpDetList group is a MAIN-corridor approach
    # -> ART_CALL (group 0 is the BusDet group). conf M = count-tie between the
    # two arterial directions (A1 inbound / A2 outbound) -- same channel either
    # way; bearing_deg records the two opposite headings.
    # GAP: KG UpDetList monitors ONLY the arterial approaches. The SCATS SIDE /
    # RT_BAY / SLIP / PED classes at every KG site have NO Aimsun loop wired, so
    # those channels are unmonitored (see build_scats_det_map.py coverage report).
    36385: {"site": 309, "groups": {
        0: {"dir": 'N', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 3.3, "note": 'BusDet / corridor arterial approach (config', "members": {11135314: ('ART_CALL', 'H', ''), 11137190: ('ART_CALL', 'H', ''), 11137191: ('ART_CALL', 'H', '')}},
        1: {"dir": 'S', "ch": 'ART_CALL', "conf": 'M', "bearing_deg": 166.1, "note": 'tie across {ART_CALL,SIDE}', "members": {11135316: ('ART_CALL', 'M', ''), 11137196: ('ART_CALL', 'M', ''), 11137198: ('ART_CALL', 'M', '')}},
    }},
    36393: {"site": 308, "groups": {
        0: {"dir": 'N', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 2.2, "note": 'BusDet / corridor arterial approach (config', "members": {11137177: ('ART_CALL', 'H', ''), 11137178: ('ART_CALL', 'H', ''), 11137179: ('ART_CALL', 'H', '')}},
        1: {"dir": 'S', "ch": 'ART_CALL', "conf": 'M', "bearing_deg": 188.6, "note": 'tie, same channel: SG1[6, 7, 8]', "members": {11137183: ('ART_CALL', 'M', ''), 11137184: ('ART_CALL', 'M', ''), 11137185: ('ART_CALL', 'M', '')}},
    }},
    38339: {"site": 371, "groups": {
        0: {"dir": 'N', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 354.0, "note": 'BusDet / corridor arterial approach (config', "members": {11137302: ('ART_CALL', 'H', ''), 11137303: ('ART_CALL', 'H', '')}},
        1: {"dir": 'S', "ch": 'ART_CALL', "conf": 'M', "bearing_deg": 188.8, "note": 'tie across {ART_CALL,SIDE}', "members": {11137307: ('ART_CALL', 'M', ''), 11137308: ('ART_CALL', 'M', '')}},
    }},
    39569: {"site": 314, "groups": {
        0: {"dir": 'NW', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 330.6, "note": 'BusDet / corridor arterial approach (config', "members": {11137276: ('ART_CALL', 'H', ''), 11137277: ('ART_CALL', 'H', '')}},
        1: {"dir": 'SE', "ch": 'ART_CALL', "conf": 'M', "bearing_deg": 151.5, "note": 'tie, same channel: A3[1, 2]', "members": {11137282: ('ART_CALL', 'M', ''), 11137283: ('ART_CALL', 'M', '')}},
    }},
    39572: {"site": 176, "groups": {
        0: {"dir": 'NW', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 335.7, "note": 'BusDet / corridor arterial approach (config', "members": {11137289: ('ART_CALL', 'H', ''), 11137290: ('ART_CALL', 'H', '')}},
        1: {"dir": 'S', "ch": 'ART_CALL', "conf": 'M', "bearing_deg": 158.1, "note": 'tie across {ART_CALL,SIDE}', "members": {11137294: ('ART_CALL', 'M', ''), 11137295: ('ART_CALL', 'M', '')}},
    }},
    39576: {"site": 312, "groups": {
        0: {"dir": 'N', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 338.6, "note": 'BusDet / corridor arterial approach (config', "members": {11137231: ('ART_CALL', 'H', ''), 11137232: ('ART_CALL', 'H', ''), 11137233: ('ART_CALL', 'H', '')}},
        1: {"dir": 'S', "ch": 'ART_CALL', "conf": 'M', "bearing_deg": 186.9, "note": 'tie, same channel: A-B Enoggerra NB[3, 4, 5]', "members": {11137238: ('ART_CALL', 'M', ''), 11137239: ('ART_CALL', 'M', ''), 11137240: ('ART_CALL', 'M', '')}},
    }},
    39578: {"site": 313, "groups": {
        0: {"dir": 'SE', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 131.7, "note": 'BusDet / corridor arterial approach (config', "members": {11137253: ('ART_CALL', 'H', ''), 11137254: ('ART_CALL', 'H', ''), 11137255: ('ART_CALL', 'H', '')}},
    }},
    39587: {"site": 311, "groups": {
        0: {"dir": 'N', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 342.1, "note": 'BusDet / corridor arterial approach (config', "members": {11137216: ('ART_CALL', 'H', ''), 11137217: ('ART_CALL', 'H', ''), 11137218: ('ART_CALL', 'H', '')}},
        1: {"dir": 'S', "ch": 'ART_CALL', "conf": 'M', "bearing_deg": 158.0, "note": 'tie across {ART_CALL,SIDE}', "members": {11137223: ('ART_CALL', 'M', ''), 11137224: ('ART_CALL', 'M', ''), 11137225: ('ART_CALL', 'M', '')}},
    }},
    39590: {"site": 307, "groups": {
        0: {"dir": 'NW', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 327.6, "note": 'BusDet / corridor arterial approach (config', "members": {11137139: ('ART_CALL', 'H', ''), 11137140: ('ART_CALL', 'H', ''), 11137162: ('ART_CALL', 'H', '')}},
        1: {"dir": 'S', "ch": 'ART_CALL', "conf": 'M', "bearing_deg": 158.2, "note": 'tie, same channel: A-B[8, 9, 10]', "members": {11137168: ('ART_CALL', 'M', ''), 11137169: ('ART_CALL', 'M', ''), 11137170: ('ART_CALL', 'M', '')}},
    }},
    39593: {"site": 310, "groups": {
        0: {"dir": 'N', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 345.5, "note": 'BusDet / corridor arterial approach (config', "members": {11137201: ('ART_CALL', 'H', ''), 11137203: ('ART_CALL', 'H', ''), 11137204: ('ART_CALL', 'H', '')}},
        1: {"dir": 'S', "ch": 'ART_CALL', "conf": 'M', "bearing_deg": 159.6, "note": 'tie, same channel: A1[1, 2, 3]', "members": {11137209: ('ART_CALL', 'M', ''), 11137210: ('ART_CALL', 'M', ''), 11137211: ('ART_CALL', 'M', '')}},
    }},
    39606: {"site": 306, "groups": {
        0: {"dir": 'NW', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 322.2, "note": 'BusDet / corridor arterial approach (config', "members": {11137146: ('ART_CALL', 'H', '')}},
        1: {"dir": 'SE', "ch": 'ART_CALL', "conf": 'M', "bearing_deg": 145.1, "note": 'tie, same channel: A1 K.G. I/BOUND[7, 8, 9]', "members": {11137149: ('ART_CALL', 'M', ''), 11137153: ('ART_CALL', 'M', ''), 11137154: ('ART_CALL', 'M', '')}},
    }},
    1043762: {"site": 8129, "groups": {
        0: {"dir": 'NW', "ch": 'ART_CALL', "conf": 'H', "bearing_deg": 321.3, "note": 'BusDet / corridor arterial approach (config', "members": {11137260: ('ART_CALL', 'H', ''), 11137261: ('ART_CALL', 'H', ''), 11137262: ('ART_CALL', 'H', '')}},
        1: {"dir": 'SE', "ch": 'ART_CALL', "conf": 'M', "bearing_deg": 149.6, "note": 'tie, same channel: A-B[1, 2, 3]', "members": {11137269: ('ART_CALL', 'M', ''), 11137270: ('ART_CALL', 'M', ''), 11137271: ('ART_CALL', 'M', '')}},
    }},
}


def channel_of(junction, det_id):
    """(channel, conf, note) for one Aimsun detector; (None,'U',...) if unmapped."""
    j = JUNCTIONS.get(int(junction))
    if not j:
        return None, "U", "junction not mapped"
    for g in j["groups"].values():
        if int(det_id) in g["members"]:
            return g["members"][int(det_id)]
    return None, "U", "detector not in any mapped group"


def group_channel(junction, group_idx):
    """(channel, conf, note) for a whole UpDetList group (incl. SPLIT fallbacks)."""
    j = JUNCTIONS.get(int(junction))
    if not j or group_idx not in j["groups"]:
        return None, "U", "unknown junction/group"
    g = j["groups"][group_idx]
    return g["ch"], g["conf"], g["note"]


def coverage():
    """Counts of member mappings by confidence (excl. group fallbacks)."""
    from collections import Counter
    c = Counter()
    for j in JUNCTIONS.values():
        for g in j["groups"].values():
            for ch, conf, _ in g["members"].values():
                c[(ch or "UNMAPPED", conf)] += 1
    return dict(sorted(c.items()))
