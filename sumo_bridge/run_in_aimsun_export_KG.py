# run_in_aimsun_export_KG.py
#
# RUN THIS INSIDE AIMSUN NEXT with TEG_KGER_T2_2025Base_QUT_AITAN1.ang OPEN.
#
# How to run:
#   Option A) Scripting view -> open this file -> press Run
#   Option B) paste the whole file into the scripting console and press Enter
#
# It writes: C:\Users\ahernz\github_for_aimsun\sumo_bridge\kg_aimsun_dump.json
# Then (outside Aimsun) build the scenario:
#   cd C:\Users\ahernz\github_for_aimsun\sumo_bridge
#   python build_sumo_scenario.py --corridor kg --dump kg_aimsun_dump.json --out kg_scenario

import builtins
import importlib.util
import os


EXPECTED_HINTS = ("KGER", "KING GEORGE")          # substring match on doc name, case-insensitive
OUT_PATH = r"C:\Users\ahernz\github_for_aimsun\sumo_bridge\kg_aimsun_dump.json"
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
        print("[KG EXPORT] Could not read active model name: %r" % e)
        return ""


def main():
    name = _active_model_name()
    print("[KG EXPORT] Active model: %s" % (name or "<unknown>"))
    if not name:
        cands = [n for n in dir(builtins) if "GK" in n or "aimsun" in n.lower()]
        print("[KG EXPORT] GKSystem not injected into this context.")
        print("[KG EXPORT] GK-ish builtins here: %s" % (cands[:20] or "none"))
        print("[KG EXPORT] If you are pasting this into the console, try instead:")
        print("[KG EXPORT]   import importlib.util")
        print("[KG EXPORT]   spec = importlib.util.spec_from_file_location("
              "'ex', r'%s')" % EXPORTER)
        print("[KG EXPORT]   ex = importlib.util.module_from_spec(spec); spec.loader.exec_module(ex)")
        print("[KG EXPORT]   ex.export(r'%s', model=GKSystem.getSystem().getActiveModel())"
              % OUT_PATH)
    if EXPECTED_HINTS and not any(h in name.upper() for h in EXPECTED_HINTS):
        print("[KG EXPORT] *** WARNING *** this does not look like the KG model.")
        print("[KG EXPORT] Expected a document whose name contains one of: %s" % ", ".join(EXPECTED_HINTS))
        print("[KG EXPORT] If you have the wrong .ang open, STOP and open "
              "TEG_KGER_T2_2025Base_QUT_AITAN1.ang first.")

    if not os.path.isfile(EXPORTER):
        raise RuntimeError("exporter not found: %s" % EXPORTER)

    spec = importlib.util.spec_from_file_location("export_aimsun_network", EXPORTER)
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)

    print("[KG EXPORT] Exporting ...")
    gks = _resolve_gksystem()
    model = gks.getSystem().getActiveModel() if gks is not None else None
    ex.export(OUT_PATH, model=model)

    # quick sanity summary
    try:
        import json
        with open(OUT_PATH, encoding="utf-8") as f:
            d = json.load(f)
        print("-" * 60)
        print("[KG EXPORT] DONE -> %s" % OUT_PATH)
        print("  sections      : %d" % len(d.get("sections", {})))
        print("  nodes         : %d" % len(d.get("nodes", {})))
        print("  turnings      : %d" % len(d.get("turnings", {})))
        print("  detectors     : %d" % len(d.get("detectors", [])))
        print("  control plans : %d" % len(d.get("control_plans", [])))
        print("  pt lines      : %d" % len(d.get("pt_lines", [])))
        print("  od matrices   : %d" % len(d.get("od_matrices", [])))
        print("-" * 60)
        print("NEXT (outside Aimsun):")
        print('  cd C:\\Users\\ahernz\\github_for_aimsun\\sumo_bridge')
        print("  python build_sumo_scenario.py --corridor kg "
              "--dump kg_aimsun_dump.json --out kg_scenario")
    except Exception as e:
        print("[KG EXPORT] dump written but summary failed: %r" % e)


main()
