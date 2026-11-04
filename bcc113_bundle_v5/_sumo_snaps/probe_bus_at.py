"""Probe: which buses reach n39576, when, and on which approach.

Also dumps the n39576 tlLogic so an action can be aimed at a real phase.
"""
from __future__ import annotations
import os
import sys

SUMO_HOME = os.environ.get("SUMO_HOME", r"C:\Program Files (x86)\Eclipse\Sumo")
sys.path.insert(0, os.path.join(SUMO_HOME, "tools"))
import sumolib          # noqa: E402
import traci            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.join(HERE, "kg.sumocfg")
NET = os.path.join(HERE, "kg.net.xml")
JID = "n39576"

net = sumolib.net.readNet(NET)
node = net.getNode(JID)
tls = node.getTLSID()
print("[PROBE] node %s tls=%s  x,y=%.1f,%.1f" % (JID, tls, *node.getCoord()))

# --- approaches ------------------------------------------------------------
incoming = []
for e in node.getIncoming():
    incoming.append(e.getID())
print("[PROBE] incoming edges: %s" % incoming)
for e in node.getIncoming():
    print("        %-12s from %-8s lanes=%d" % (e.getID(), e.getFromNode().getID(),
                                               len(e.getLanes())))

# --- tlLogic ---------------------------------------------------------------
for tl in net.getTrafficLights():
    if tl.getID() != tls:
        continue
    phases = tl.getPrograms()
    for pname, prog in phases.items():
        print("[PROBE] program %r offset=%s" % (pname, prog.getOffset()))
        for i, ph in enumerate(prog.getPhases()):
            print("        phase %d dur=%5.1f %s" % (i, ph.duration, ph.state))

# --- which buses pass through, and when ------------------------------------
binary = os.path.join(SUMO_HOME, "bin", "sumo.exe")
cmd = [binary, "-c", SCEN, "--seed", "300", "--no-step-log", "true",
       "--duration-log.statistics", "false"]
traci.start(cmd, label="probe")
c = traci.getConnection("probe")

inc = set(incoming)
seen = {}
bus_ids = set()
classified = {}          # vid -> is_bus, filled once per vehicle
for eid in inc:
    try:
        vids = c.edge.getLastStepVehicleIDs(eid)
    except Exception:
        vids = []
    for vid in vids:
        if vid in classified:
            continue
        try:
            cls = (c.vehicle.getVehicleClass(vid) or "").lower()
            vtype = (c.vehicle.getTypeID(vid) or "").lower()
        except Exception:
            cls, vtype = "", ""
        classified[vid] = ("bus" in cls) or ("bus" in vtype)

t = 0
while t < 4500 and len(seen) < 200:
    c.simulationStep()
    t += 1
    # classify each vehicle ONCE -- getVehicleClass per vehicle per step is
    # ~22M TraCI calls over a 4500 s run and dominates the wall clock
    for vid in c.vehicle.getIDList():
        if vid in classified:
            continue
        try:
            cls = (c.vehicle.getVehicleClass(vid) or "").lower()
            vtype = (c.vehicle.getTypeID(vid) or "").lower()
        except Exception:
            classified[vid] = False
            continue
        classified[vid] = ("bus" in cls) or ("bus" in vtype)
    for eid in inc:
        try:
            for vid in c.edge.getLastStepVehicleIDs(eid):
                if classified.get(vid) and vid not in seen:
                    seen[vid] = (t, eid, round(c.vehicle.getSpeed(vid), 2))
        except Exception:
            pass

print("[PROBE] %d buses total; %d enter an approach of %s" %
      (len(bus_ids), len(seen), JID))
for vid, (t, eid, v) in sorted(seen.items(), key=lambda kv: kv[1][0]):
    print("        %-14s t=%5d edge=%-12s speed=%.2f" % (vid, t, eid, v))

c.close()
