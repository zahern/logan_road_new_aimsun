"""
clear_markers.py
================
Standalone Aimsun script — removes all TSP bus-detection circle markers
(GKPolyline / GKAnnotation) from the active model.

HOW TO RUN FROM AIMSUN
-----------------------
  Aimsun menu:  Tools → Run Script...
  Browse to:    C:/Users/ahernz/github_for_aimsun/logan_road_new/clear_markers.py
  Click:        Run

Deletes every marker object whose name starts with one of the TSP prefixes:
  [BUS]  [WAVE]  [SEC]  [DET]  [IC-detect]  [NORMAL-detect]

Runs multiple sweep passes so objects missed by a partial first pass
(e.g. due to catalog-iterator invalidation during deletion) are caught
in the next pass.  Stops when a full pass finds nothing more to delete.
"""

_PREFIXES = (
    "[BUS]",
    "[WAVE]",
    "[SEC]",
    "[DET]",
    "[IC-detect]",
    "[NORMAL-detect]",
)

_TYPE_NAMES = ("GKPolyline", "GKAnnotation", "GKPolygon", "GKText")

_MAX_PASSES = 10   # safety limit so we never loop forever


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_name(obj) -> str:
    for fn in ("getName", "getExternalName", "getLabel"):
        try:
            v = getattr(obj, fn)()
            if v:
                return str(v)
        except Exception:
            pass
    return ""


def _try_delete(catalog, obj) -> bool:
    """Try every deletion API; return True on first success."""
    # catalog.remove() is the working method discovered in Aimsun Next 26
    for method in ("remove", "removeObject", "unmanageObject", "deleteObject"):
        try:
            getattr(catalog, method)(obj)
            return True
        except AttributeError:
            pass   # method doesn't exist
        except Exception:
            pass   # method exists but call failed
    # Last resort: GKObject self-deletion
    try:
        obj.remove()
        return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# One sweep: collect ALL matching objects then delete them
# ---------------------------------------------------------------------------

def _one_sweep(model, catalog) -> tuple:
    """
    Collect every TSP-prefixed object across all known types, then delete.
    Returns (n_found_this_pass, n_deleted_this_pass).

    We collect FIRST and delete SECOND so that deleting one object does not
    invalidate the iterator for the remaining objects in the same type bucket.
    Using a fresh getObjectsByType call per type-name also avoids holding a
    stale reference to a mutated collection.
    """
    to_delete = []

    for type_name in _TYPE_NAMES:
        gk_type = None
        try:
            gk_type = model.getType(type_name)
        except Exception:
            pass
        if gk_type is None:
            continue

        objs = None
        try:
            objs = catalog.getObjectsByType(gk_type)
        except Exception:
            pass
        if not objs:
            continue

        # Snapshot the collection into a plain Python list immediately
        obj_list = list(objs.values()) if isinstance(objs, dict) else list(objs)

        for obj in obj_list:
            name = _get_name(obj)
            if any(name.startswith(p) for p in _PREFIXES):
                to_delete.append(obj)

    n_found = len(to_delete)
    n_del   = 0
    for obj in to_delete:
        if _try_delete(catalog, obj):
            n_del += 1

    return n_found, n_del


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
    try:
        from PyANGKernel import GKSystem
    except ImportError:
        print("[clear_markers] ERROR: PyANGKernel not available. "
              "Run this script from inside Aimsun (Tools → Run Script).")
        return

    model = GKSystem.getSystem().getActiveModel()
    if model is None:
        print("[clear_markers] ERROR: no active Aimsun model.")
        return

    catalog = None
    try:
        catalog = model.getCatalog()
    except Exception:
        print("[clear_markers] ERROR: model.getCatalog() failed.")
        return

    total_found = 0
    total_del   = 0

    for pass_num in range(1, _MAX_PASSES + 1):
        n_found, n_del = _one_sweep(model, catalog)
        total_found += n_found
        total_del   += n_del

        if n_found == 0:
            # Nothing left to delete — done
            break

        print(f"[clear_markers] Pass {pass_num}: "
              f"found {n_found}, deleted {n_del}.")

        if n_del == 0 and n_found > 0:
            # Found objects but couldn't delete any — give up to avoid loop
            print(f"[clear_markers] ERROR: {n_found} marker(s) found but "
                  f"deletion failed on every attempt.")
            print("[clear_markers] WORKAROUND: In Aimsun network editor, "
                  "use Edit → Find (Ctrl+F), search for '[BUS]', "
                  "select all results and press Delete.")
            break

    # Final report
    if total_found == 0:
        print("[clear_markers] No TSP markers found — model is already clean.")
    else:
        print(f"[clear_markers] Done: {total_del}/{total_found} "
              f"marker(s) deleted across {pass_num} pass(es).")


# ── Auto-execute when Aimsun runs this file ──────────────────────────────────
run()
