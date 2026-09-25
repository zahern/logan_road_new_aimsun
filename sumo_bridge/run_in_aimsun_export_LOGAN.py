# run_in_aimsun_export_LOGAN.py
#
# RUN THIS INSIDE AIMSUN NEXT with Logan_RD_for_QUT_with_detectors.ang OPEN.
#
# How to run:
#   Option A) Scripting view -> open this file -> press Run
#   Option B) paste the whole file into the scripting console and press Enter
#
# It writes: C:\Users\ahernz\github_for_aimsun\sumo_bridge\logan_aimsun_dump.json
# Then (outside Aimsun) build the scenario:
#   cd C:\Users\ahernz\github_for_aimsun\sumo_bridge
#   python build_sumo_scenario.py --corridor logan_road_new --dump logan_aimsun_dump.json --out logan_scenario
#
# NOTE for Logan: the corridor's intersection_configs.py only lists junction IDs -
# signals/detectors are discovered from the model at runtime. That makes THIS dump
# the thing that makes the SUMO scenario faithful (signal programs + detector
# placement). If detectors or control plans export as 0, fix that before building.

import builtins
import importlib.util
import os

EXPECTED_HINTS = ("LOGAN",)                       # substring match on doc name, case-insensitive
OUT_PATH = r"C:\Users\ahernz\github_for_aimsun\sumo_bridge\logan_aimsun_dump.json"
EXPORTER = r"C:\Users\ahernz\github_for_aimsun\sumo_bridge\export_aimsun_network.py"


def _resolve_gksystem():
    """Aimsun injects GKSystem into the scripting namespace - never import it."""
    gks = getattr(builtins, "GKSystem", None)
    if gks is not None and hasattr(gks, "getSystem"):
        return gks
    try:
        gks = globals().get("GKSystem")
        if gks is not None and hasattr(gks, "getSystem"):
            return gks
    except Exception:
        pass
    return None


def _active_model_name():
    try:
        gks = _resolve_gksystem()
        if gks is None:
            return ""
        return str(gks.getSystem().getActiveModel().getName())
    except Exception as e:
        print("[LOGAN EXPORT] Could not read active model name: %r" % e)
        return ""


def main():
    name = _active_model_name()
    print("[LOGAN EXPORT] Active model: %s" % (name or "<unknown>"))
    if not name:
        cands = [n for n in dir(builtins) if "GK" in n or "aimsun" in n.lower()]
        print("[LOGAN EXPORT] GKSystem not injected into this context.")
        print("[LOGAN EXPORT] GK-ish builtins here: %s" % (cands[:20] or "none"))
        print("[LOGAN EXPORT] If you are pasting this into the console, try instead:")
        print("[LOGAN EXPORT]   import importlib.util")
        print("[LOGAN EXPORT]   spec = importlib.util.spec_from_file_location("
              "'ex', r'%s')" % EXPORTER)
        print("[LOGAN EXPORT]   ex = importlib.util.module_from_spec(spec); spec.loader.exec_module(ex)")
        print("[LOGAN EXPORT]   ex.export(r'%s', model=GKSystem.getSystem().getActiveModel())"
              % OUT_PATH)
    if EXPECTED_HINTS and not any(h in name.upper() for h in EXPECTED_HINTS):
        print("[LOGAN EXPORT] *** WARNING *** this does not look like the Logan model.")
        print("[LOGAN EXPORT] Expected a document whose name contains: %s" % ", ".join(EXPECTED_HINTS))
        print("[LOGAN EXPORT] If you have the wrong .ang open, STOP and open "
              "Logan_RD_for_QUT_with_detectors.ang first.")

    if not os.path.isfile(EXPORTER):
        raise RuntimeError("exporter not found: %s" % EXPORTER)

    spec = importlib.util.spec_from_file_location("export_aimsun_network", EXPORTER)
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)

    print("[LOGAN EXPORT] Exporting ...")
    gks = _resolve_gksystem()
    model = gks.getSystem().getActiveModel() if gks is not None else None
    ex.export(OUT_PATH, model=model)

    # quick sanity summary + Logan-specific warnings
    try:
        import json
        with open(OUT_PATH, encoding="utf-8") as f:
            d = json.load(f)
        n_det = len(d.get("detectors", []))
        n_cp = len(d.get("control_plans", []))
        print("-" * 60)
        print("[LOGAN EXPORT] DONE -> %s" % OUT_PATH)
        print("  sections      : %d" % len(d.get("sections", {})))
        print("  nodes         : %d" % len(d.get("nodes", {})))
        print("  turnings      : %d" % len(d.get("turnings", {})))
        print("  detectors     : %d" % n_det)
        print("  control plans : %d" % n_cp)
        print("  pt lines      : %d" % len(d.get("pt_lines", [])))
        print("  od matrices   : %d" % len(d.get("od_matrices", [])))
        print("-" * 60)
        if n_det == 0:
            print("[LOGAN EXPORT] *** WARNING: 0 detectors exported.")
            print("  Logan relies on runtime detector discovery - without these the")
            print("  SUMO scenario will fall back to topology-only bus detection")
            print("  (works, but less faithful). Check the exporter log above.")
        if n_cp == 0:
            print("[LOGAN EXPORT] *** WARNING: 0 control plans exported - signal")
            print("  programs will be synthesized (arterial/side split by lane")
            print("  capacity), not Aimsun's real ring structure.")
        print("NEXT (outside Aimsun):")
        print('  cd C:\\Users\\ahernz\\github_for_aimsun\\sumo_bridge')
        print("  python build_sumo_scenario.py --corridor logan_road_new "
              "--dump logan_aimsun_dump.json --out logan_scenario")
    except Exception as e:
        print("[LOGAN EXPORT] dump written but summary failed: %r" % e)


main()
