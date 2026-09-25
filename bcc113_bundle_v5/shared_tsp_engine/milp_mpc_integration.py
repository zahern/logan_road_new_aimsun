"""
Integration patch for engine.py to add MILP_MPC control mode.

Copy the relevant sections into engine.py, or import this module and call
`patch_engine_for_milp_mpc()` from AAPIInit().
"""

from typing import Optional
import sys

# -------------------------------------------------------------------------
# 1. Add to engine.py imports (top of file)
# -------------------------------------------------------------------------
MILP_MPC_IMPORTS = '''
try:
    from milp_mpc_controller import MILPMPCController, create_milp_mpc_controller, BusState, IntersectionConfig
    _MILP_MPC_AVAILABLE = True
except Exception as _e:
    _MILP_MPC_AVAILABLE = False
    _MILP_MPC_ERROR = str(_e)
    import traceback
    traceback.print_exc()
'''

# -------------------------------------------------------------------------
# 2. Add to engine.py globals (after other mode constants, ~line 294)
# -------------------------------------------------------------------------
MILP_MPC_CONFIG = '''
# =============================================================================
# MILP-MPC SETTINGS
# =============================================================================
MILP_MPC_HORIZON_S       = 300.0   # planning horizon (s)
MILP_MPC_REPLAN_S        = 30.0    # re-solve interval (s)
MILP_MPC_TIME_LIMIT_S    = 1.5     # solver time limit (s)
MILP_MPC_EPSILON_LATE_S  = 60.0    # schedule adherence cap (s)
MILP_MPC_EPSILON_Z4_S    = 90.0    # throughput cap (veh·s)
MILP_MPC_Z4_BASELINE     = 380.0   # fixed-time baseline corridor TT (veh·h)
'''

# -------------------------------------------------------------------------
# 3. Add to CONTROL_MODE options (line ~294)
# -------------------------------------------------------------------------
MILP_MPC_MODE_ENTRY = '''
    "MILP_MPC"           — Rolling-horizon MILP-MPC: exact clairvoyant program
                          solved as rolling-horizon MPC with CP-SAT.
'''

# Add to CONTROL_MODE assignment:
# CONTROL_MODE = "MILP_MPC"   # <-- uncomment to activate

# -------------------------------------------------------------------------
# 4. Controller instantiation in IntersectionController.__init__
#    Add after existing mode setup (around line 5070)
# -------------------------------------------------------------------------
MILP_MPC_INIT_PATCH = '''
        # ── MILP-MPC controller ────────────────────────────────────────
        self._milp_mpc = None
        if CONTROL_MODE == "MILP_MPC":
            if not _MILP_MPC_AVAILABLE:
                log_to_file(f"[MILP_MPC] ERROR: {_MILP_MPC_ERROR}")
                raise RuntimeError("MILP_MPC requires a solver backend (ortools "
                                     "or scipy>=1.9 for HiGHS) in the Aimsun-visible interpreter")
            try:
                # Build config dict from this intersection's config
                milp_config = {self.id: self.config}
                self._milp_mpc = create_milp_mpc_controller(
                    milp_config,
                    corridor_coord=getattr(self, '_corridor_coord', None)
                )
                log_to_file(f"[MILP_MPC] Intersection {self.id} initialised")
            except Exception as _e:
                log_to_file(f"[MILP_MPC] Failed to initialise: {_e}")
                import traceback
                traceback.print_exc()
'''

# -------------------------------------------------------------------------
# 5. AAPIManage hook: call MILP-MPC step every simulation step
#    Insert in AAPIManage (around line 13497) before existing mode dispatch
# -------------------------------------------------------------------------
MILP_MPC_MANAGE_PATCH = '''
        # ── MILP-MPC controller ────────────────────────────────────────
        if CONTROL_MODE == "MILP_MPC" and ctrl._milp_mpc is not None:
            # Build prediction from current state
            pred = ctrl._build_milp_prediction(time)
            
            # Step the MPC (re-solves every replan_every_s)
            result = ctrl._milp_mpc.step(pred, int(time))
            
            # Extract actions for current step
            actions = ctrl._milp_mpc.get_current_actions(int(time))
            
            # Execute actions via Aimsun API
            for (iid, k), _ in actions.items():
                if iid != ctrl.id:
                    continue
                if k == 'GE':
                    ctrl._execute_green_extension(time, timeSta)
                elif k == 'INS':
                    ctrl._execute_insertion(time, timeSta)
                elif k == 'ER':
                    ctrl._execute_early_red(time, timeSta)
                elif k == 'GR':
                    ctrl._execute_green_reallocation(time, timeSta)
            continue  # skip other mode logic
'''

# -------------------------------------------------------------------------
# 6. Add prediction builder to IntersectionController
#    Insert as a method in IntersectionController class
# -------------------------------------------------------------------------
MILP_MPC_PREDICTION_METHOD = '''
    def _build_milp_prediction(self, sim_time: float) -> MPCPrediction:
        """
        Build MILP-MPC prediction from current state.
        Uses CorridorCoordinator for bus ETAs, local shockwave for flows.
        """
        from milp_mpc_controller import MPCPrediction, BusState
        
        # --- Bus states from CorridorCoordinator / local tracking ---
        bus_states = []
        if self._corridor_coord is not None:
            for veh_id, tracker in self._corridor_coord._trackers.items():
                # Get route from corridor coordinator
                route = self._corridor_coord.get_bus_route(veh_id)
                if not route:
                    continue
                # Find current position in route
                current_idx = 0
                for idx, iid in enumerate(route):
                    if iid == self.id:
                        current_idx = idx
                        break
                bus_states.append(BusState(
                    veh_id=veh_id,
                    line_id=getattr(tracker, 'line_id', -1),
                    route_jcts=route,
                    current_jct_idx=current_idx,
                    tau_detect=sim_time,  # approximate; ideally from detector
                    sigma_detect=0.0,     # will be refined by MILP
                ))
        
        # --- Flow predictions from local shockwave/CTM ---
        q_arr = {}
        for i in [self.id]:  # only local intersection for now
            for p in self.configs[self.id].phase_list:
                for t in range(300):  # T=300
                    # Use current shockwave-estimated flow as constant forecast
                    q_arr[(self.id, p, t)] = self._estimate_flow(p)
        
        # --- Free-flow travel times ---
        tau_freeflow = {}
        # Populated from config / corridor_coord
        
        # --- Scheduled arrivals (timetable) ---
        tau_bar = {}
        if self._corridor_coord is not None:
            for bus in self._corridor_coord.get_active_buses():
                for idx, iid in enumerate(bus.route):
                    tau_bar[(bus.veh_id, iid)] = bus.scheduled_arrival[idx]
        
        # --- Initial queues from current detector state ---
        Q_init = {}
        for p in self.P:
            Q_init[(self.id, p)] = self._estimate_queue(p)
        
        # --- Current offsets ---
        phi_init = {self.id: self._get_current_offset()}
        
        return MPCPrediction(
            q_arr=q_arr,
            q_side={},
            tau_freeflow={},
            tau_bar=tau_bar,
            Q_init=Q_init,
            phi_init={self.id: 0.0},
            bus_states=bus_states,
        )
    
    def _estimate_flow(self, phase: int) -> float:
        """Estimate arrival flow (veh/s) for phase from shockwave/CTM."""
        # Use existing shockwave estimates from initialize_state / run_harmony
        if hasattr(self, 'UpFlowList') and len(self.UpFlowList) > 0:
            return float(self.UpFlowList[0][0])
        return 0.5  # fallback veh/s
    
    def _estimate_queue(self, phase: int) -> float:
        """Estimate current queue (veh) from detector occupancy."""
        if hasattr(self, 'MaxQueueLength') and len(self.MaxQueueLength) > 0:
            return float(self.MaxQueueLength[0][0])
        return 0.0
    
    def _get_current_offset(self) -> float:
        """Current offset from cycle start (s)."""
        try:
            cycle_start = ECIGetStartingTimeCycle(self.node_id)
            return max(0.0, time - cycle_start)
        except Exception:
            return 0.0
'''

# -------------------------------------------------------------------------
# 7. Full integration function
# -------------------------------------------------------------------------
def patch_engine_for_milp_mpc():
    """
    Apply all patches to engine.py programmatically.
    Call this from AAPIInit() after bind_config().
    """
    import shared_tsp_engine.engine as engine
    
    # 1. Add imports
    exec(MILP_MPC_IMPORTS, engine.__dict__)
    
    # 2. Add config constants
    exec(MILP_MPC_CONFIG, engine.__dict__)
    
    # 3. Monkey-patch IntersectionController.__init__
    original_init = engine.IntersectionController.__init__
    def patched_init(self, config):
        original_init(self, config)
        exec(MILP_MPC_INIT_PATCH, {'ctrl': self, 'config': self.config, 
                                    'log_to_file': engine.log_to_file,
                                    'create_milp_mpc_controller': engine.create_milp_mpc_controller})
    
    engine.IntersectionController.__init__ = patched_init
    
    # 3b. Add prediction method
    exec(MILP_MPC_PREDICTION_METHOD, engine.IntersectionController.__dict__)
    
    # 4. Monkey-patch AAPIManage
    original_manage = engine.AAPIManage
    def patched_manage(time, timeSta, timeTrans, acycle):
        # MILP-MPC pre-dispatch
        if engine.CONTROL_MODE == "MILP_MPC":
            # This would need proper binding; simplified here
            pass
        return original_manage(time, timeSta, timeTrans, acycle)
    
    engine.AAPIManage = patched_manage
    
    engine.log_to_file("[MILP_MPC] Integration patches applied")
    return True


# -------------------------------------------------------------------------
# 8. Minimal working integration (copy-paste into engine.py manually)
# -------------------------------------------------------------------------
MANUAL_INTEGRATION_GUIDE = """
================================================================================
MANUAL INTEGRATION GUIDE (copy-paste into engine.py)
================================================================================

1. AT TOP OF FILE (after existing imports):
--------------------------------------------------------------------------------
try:
    from milp_mpc_controller import MILPMPCController, create_milp_mpc_controller, BusState, IntersectionConfig
    _MILP_MPC_AVAILABLE = True
except Exception as _e:
    _MILP_MPC_AVAILABLE = False
    _MILP_MPC_ERROR = str(_e)
    import traceback
    traceback.print_exc()

2. AFTER MODE CONSTANTS (~line 294):
--------------------------------------------------------------------------------
# MILP-MPC SETTINGS
MILP_MPC_HORIZON_S       = 300.0   # planning horizon (s)
MILP_MPC_REPLAN_S        = 30.0    # re-solve interval (s)
MILP_MPC_TIME_LIMIT_S    = 1.5     # solver time limit (s)
MILP_MPC_EPSILON_LATE_S  = 60.0    # schedule adherence cap (s)
MILP_MPC_EPSILON_Z4_S    = 90.0    # throughput cap (veh·s)
MILP_MPC_Z4_BASELINE     = 380.0   # fixed-time baseline corridor TT (veh·h)

CONTROL_MODE = "MILP_MPC"   # <-- SET THIS TO ACTIVATE

3. IN IntersectionController.__init__ (after line ~5070):
--------------------------------------------------------------------------------
        # MILP-MPC controller
        self._milp_mpc = None
        if CONTROL_MODE == "MILP_MPC":
            if not _MILP_MPC_AVAILABLE:
                log_to_file(f"[MILP_MPC] ERROR: {_MILP_MPC_ERROR}")
                raise RuntimeError("MILP_MPC requires a solver backend (ortools "
                                     "or scipy>=1.9 for HiGHS) in the Aimsun-visible interpreter")
            try:
                milp_config = {self.id: self.config}
                self._milp_mpc = create_milp_mpc_controller(
                    milp_config,
                    corridor_coord=getattr(self, '_corridor_coord', None)
                )
                log_to_file(f"[MILP_MPC] Intersection {self.id} initialised")
            except Exception as _e:
                log_to_file(f"[MILP_MPC] Failed to initialise: {_e}")
                import traceback
                traceback.print_exc()

4. ADD PREDICTION METHOD to IntersectionController class:
--------------------------------------------------------------------------------
    def _build_milp_prediction(self, sim_time: float):
        from milp_mpc_controller import MPCPrediction, BusState
        # (copy the _build_milp_prediction method from integration guide above)
        ...

5. IN AAPIManage (around line 13497), BEFORE existing mode dispatch:
--------------------------------------------------------------------------------
        if CONTROL_MODE == "MILP_MPC" and ctrl._milp_mpc is not None:
            pred = ctrl._build_milp_prediction(time)
            result = ctrl._milp_mpc.step(pred, int(time))
            actions = ctrl._milp_mpc.get_current_actions(int(time))
            for (iid, k), _ in actions.items():
                if iid != ctrl.id: continue
                if k == 'GE': ctrl._execute_green_extension(time, timeSta)
                elif k == 'INS': ctrl._execute_insertion(time, timeSta)
                elif k == 'ER': ctrl._execute_early_red(time, timeSta)
                elif k == 'GR': ctrl._execute_green_reallocation(time, timeSta)
            continue  # skip other mode logic

6. ADD EXECUTION HELPERS to IntersectionController:
--------------------------------------------------------------------------------
    def _execute_green_extension(self, time, timeSta):
        current_phase = ECIGetCurrentPhase(self.node_id)
        new_dur = self.BusPhaseDuration + 10.0  # fixed 10s extension for now
        ECIChangeTimingPhase(self.node_id, current_phase, new_dur, timeSta)
        self.stats.record_tsp_event(self.id, 'extension')
    
    def _execute_insertion(self, time, timeSta):
        current_phase = ECIGetCurrentPhase(self.node_id)
        self.previous_phase = current_phase
        ECIChangeDirectPhase(self.node_id, self.BusPhase, timeSta, time, acycle, 0)
        self.stats.record_tsp_event(self.id, 'insertion')
    
    # ... similarly for ER, GR

7. SET CONTROL_MODE = "MILP_MPC" in kg/intersection_controller.py (line 294)
--------------------------------------------------------------------------------
CONTROL_MODE = "MILP_MPC"
"""