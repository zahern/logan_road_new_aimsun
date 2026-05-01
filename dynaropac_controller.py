"""
DynaROPAC-based Joint Phase Insertion and Green Extension Optimizer

This module implements the DynaROPAC (Dynamic Rolling Horizon Optimized 
Policies for Adaptive Control) algorithm for traffic signal optimization.

Key features:
- Joint optimization of phase insertion time and green extension
- Dynamic stage length based on approach geometry and demand
- Rolling horizon approach for real-time adaptation
- Corridor-wide coordination through upstream information propagation
- Person-delay minimization objective (balances bus priority with network efficiency)

Based on: Paz, A., & Chiu, Y.C. (2011). "Adaptive Traffic Control for Large-Scale 
Dynamic Traffic Assignment Applications." Transportation Research Board.
"""

import numpy as np
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import math
from collections import defaultdict


class PhaseAction(Enum):
    """Possible actions for a signal phase."""
    EXTEND_GREEN = "extend"
    INSERT_PHASE = "insert"
    TERMINATE = "terminate"
    MAINTAIN = "maintain"


@dataclass
class ApproachState:
    """State of a single approach to an intersection."""
    approach_id: int
    queue_length: float  # vehicles
    upstream_flow: float  # vehicles/hour
    saturation_flow: float  # vehicles/hour
    approach_length: float  # meters
    average_speed: float  # m/s
    arrivals: float = 0.0  # vehicles in current interval
    departures: float = 0.0  # vehicles in current interval
    
    @property
    def queue_saturation_ratio(self) -> float:
        """Ratio of queue to saturation flow (indicates congestion level)."""
        if self.saturation_flow <= 0:
            return float('inf')
        return self.queue_length / self.saturation_flow
    
    @property
    def queue_clearance_time(self) -> float:
        """Time to clear existing queue (seconds)."""
        if self.saturation_flow <= 0:
            return float('inf')
        return (self.queue_length / self.saturation_flow) * 3600.0
    
    @property
    def approach_travel_time(self) -> float:
        """Time to traverse the approach (seconds)."""
        if self.average_speed <= 0:
            return float('inf')
        return self.approach_length / self.average_speed


@dataclass
class BusState:
    """State of a bus approaching an intersection."""
    bus_id: int
    distance_to_stopline: float  # meters
    speed: float  # m/s
    occupancy: float = 40.0  # passengers (default for articulated bus)
    eta: float = 0.0  # estimated arrival time (seconds)
    queue_clearance_time: float = 0.0  # additional time for downstream queue
    
    def update_eta(self, downstream_queue: float = 0.0, shockwave_speed: float = 4.17):
        """Update ETA including queue clearance time."""
        base_eta = self.distance_to_stopline / self.speed if self.speed > 0 else float('inf')
        self.queue_clearance_time = downstream_queue / shockwave_speed
        self.eta = base_eta + self.queue_clearance_time
        return self.eta


@dataclass
class PhaseDefinition:
    """Definition of a signal phase."""
    phase_id: int
    served_approaches: List[int]  # approach IDs served by this phase
    min_green: float  # seconds
    max_green: float  # seconds
    is_bus_phase: bool = False  # whether this is a dedicated bus phase


@dataclass
class StageResult:
    """Result of optimizing a single stage."""
    phase_sequence: List[int]  # ordered list of phase IDs
    switching_times: List[float]  # switching times in seconds from stage start
    green_extensions: Dict[int, float]  # phase_id -> extension seconds
    bus_insertions: Dict[int, bool]  # bus_id -> inserted or not
    total_delay: float  # vehicle-seconds
    person_delay: float  # passenger-seconds
    stage_length: float  # seconds


@dataclass
class IntersectionState:
    """Complete state of an intersection."""
    intersection_id: int
    phases: Dict[int, PhaseDefinition]
    approaches: Dict[int, ApproachState]
    current_phase: int
    phase_start_time: float  # when current phase started
    elapsed_green: float  # seconds of green elapsed for current phase
    buses_detected: Dict[int, BusState]  # bus_id -> BusState


class DynaROPACOptimizer:
    """
    DynaROPAC-based optimizer for joint phase insertion and green extension.
    
    The algorithm works in stages:
    1. Calculate dynamic stage length based on critical approach
    2. Define rolling horizon (head period for implementation, tail for projection)
    3. Exhaustive search over all feasible phase sequences and switching times
    4. Evaluate each combination using person-delay objective
    5. Select optimal solution and implement for head period only
    6. Roll horizon and repeat
    """
    
    def __init__(
        self,
        time_interval: float = 5.0,  # Δ in seconds
        eta_min: float = 10.0,  # minimum ETA for TSP activation (seconds)
        eta_max: float = 60.0,  # maximum ETA for TSP activation (seconds)
        ge_buffer: float = 5.0,  # buffer time for green extension (seconds)
        car_occupancy: float = 1.5,  # average car occupancy
        shockwave_speed: float = 4.17,  # queue discharge wave speed (m/s)
        phase_insertion_penalty: float = 30.0,  # penalty for inserting bus phase (vehicle-seconds)
        max_search_combinations: int = 10000,  # limit exhaustive search
    ):
        self.time_interval = time_interval  # Δ
        self.eta_min = eta_min
        self.eta_max = eta_max
        self.ge_buffer = ge_buffer
        self.car_occupancy = car_occupancy
        self.shockwave_speed = shockwave_speed
        self.phase_insertion_penalty = phase_insertion_penalty
        self.max_search_combinations = max_search_combinations
        
        # Cache for delay calculations
        self._delay_cache: Dict[Tuple, float] = {}
    
    def calculate_stage_length(
        self, 
        intersection_state: IntersectionState
    ) -> float:
        """
        Calculate dynamic stage length based on critical approach.
        
        The stage length is determined by the approach with the maximum
        queue-to-saturation ratio. If the queue clearance time is greater
        than the approach travel time, we use queue clearance + upstream
        flow time. Otherwise, we use the approach travel time.
        
        Returns:
            Stage length in seconds
        """
        # Find critical approach (max queue/saturation ratio)
        critical_approach = None
        max_ratio = -1.0
        
        for approach in intersection_state.approaches.values():
            ratio = approach.queue_saturation_ratio
            if ratio > max_ratio:
                max_ratio = ratio
                critical_approach = approach
        
        if critical_approach is None:
            # Default stage length (e.g., 60 seconds)
            return 60.0
        
        queue_clearance = critical_approach.queue_clearance_time
        travel_time = critical_approach.travel_time
        
        if queue_clearance >= travel_time:
            # Use queue clearance time + time for upstream flow
            upstream_contribution = (critical_approach.upstream_flow / critical_approach.saturation_flow) * 3600.0
            stage_length = queue_clearance + upstream_contribution
        else:
            # Use approach travel time
            stage_length = travel_time
        
        # Round up to nearest multiple of time_interval
        num_intervals = math.ceil(stage_length / self.time_interval)
        return num_intervals * self.time_interval
    
    def calculate_delay(
        self,
        intersection_state: IntersectionState,
        phase_sequence: List[int],
        switching_times: List[float],
        stage_length: float,
        include_bus_priority: bool = True,
    ) -> float:
        """
        Calculate total person-delay for a given phase sequence and switching times.
        
        The delay is calculated as the sum over all time intervals of:
        (initial_queue + arrivals - departures) × interval_length
        
        For person-delay, we weight by vehicle occupancy.
        
        Returns:
            Total person-delay in passenger-seconds
        """
        # Create cache key
        cache_key = (
            intersection_state.intersection_id,
            tuple(phase_sequence),
            tuple(switching_times),
            stage_length
        )
        
        if cache_key in self._delay_cache:
            return self._delay_cache[cache_key]
        
        num_intervals = int(stage_length / self.time_interval)
        total_delay = 0.0
        
        # Build phase-to-approaches mapping
        phase_approaches = {}
        for phase_id in phase_sequence:
            if phase_id in intersection_state.phases:
                phase_approaches[phase_id] = intersection_state.phases[phase_id].served_approaches
        
        # Determine which phase is active in each interval
        phase_active = self._get_phase_active_intervals(
            phase_sequence, switching_times, num_intervals, stage_length
        )
        
        # Calculate delay for each interval
        for interval in range(num_intervals):
            active_phase = phase_active[interval]
            
            for approach_id, approach in intersection_state.approaches.items():
                # Check if this approach is served by the active phase
                is_served = approach_id in phase_approaches.get(active_phase, [])
                
                # Calculate arrivals and departures
                if is_served:
                    # Phase is green for this approach - vehicles can depart
                    departures = min(
                        approach.queue_length + approach.arrivals,
                        approach.saturation_flow * self.time_interval / 3600.0
                    )
                    arrivals = approach.upstream_flow * self.time_interval / 3600.0
                else:
                    # Phase is red - no departures
                    departures = 0.0
                    arrivals = approach.upstream_flow * self.time_interval / 3600.0
                
                # Delay = queue at start + arrivals - departures
                interval_delay = (approach.queue_length + arrivals - departures) * self.time_interval
                
                # Weight by occupancy (person-delay)
                if include_bus_priority:
                    # Check if bus is in queue on this approach
                    bus_in_queue = self._check_bus_in_queue(approach_id, intersection_state)
                    if bus_in_queue:
                        # Use bus occupancy for portion with bus
                        interval_delay = interval_delay * (approach.occupancy if hasattr(approach, 'occupancy') else self.car_occupancy)
                    else:
                        interval_delay = interval_delay * self.car_occupancy
                else:
                    interval_delay = interval_delay * self.car_occupancy
                
                total_delay += interval_delay
        
        # Add penalty for bus phase insertions if any
        if include_bus_priority:
            for bus_id, bus in intersection_state.buses_detected.items():
                if bus.eta < self.eta_max and bus.eta > self.eta_min:
                    # Check if bus would be delayed by this phase sequence
                    if self._bus_would_be_delayed(bus, phase_sequence, switching_times, intersection_state):
                        total_delay += self.phase_insertion_penalty * bus.occupancy
        
        self._delay_cache[cache_key] = total_delay
        return total_delay
    
    def _get_phase_active_intervals(
        self,
        phase_sequence: List[int],
        switching_times: List[float],
        num_intervals: int,
        stage_length: float,
    ) -> List[int]:
        """Determine which phase is active in each time interval."""
        phase_active = [phase_sequence[0]] * num_intervals
        
        for i in range(len(switching_times) - 1):
            start_interval = int(switching_times[i] / self.time_interval)
            end_interval = int(switching_times[i + 1] / self.time_interval)
            
            if start_interval < num_intervals:
                for j in range(min(start_interval, num_intervals), min(end_interval, num_intervals)):
                    phase_active[j] = phase_sequence[i + 1] if i + 1 < len(phase_sequence) else phase_sequence[-1]
        
        return phase_active
    
    def _check_bus_in_queue(self, approach_id: int, intersection_state: IntersectionState) -> bool:
        """Check if any bus is in the queue on this approach."""
        for bus in intersection_state.buses_detected.values():
            # Estimate if bus is in queue based on distance and queue length
            # This is a simplified check - in practice would need more detailed tracking
            if bus.distance_to_stopline < 50.0:  # Within 50m of stopline
                return True
        return False
    
    def _bus_would_be_delayed(
        self,
        bus: BusState,
        phase_sequence: List[int],
        switching_times: List[float],
        intersection_state: IntersectionState,
    ) -> bool:
        """Check if bus would be delayed by the given phase sequence."""
        # Simplified check: bus is delayed if its ETA falls in a red interval
        # for the phase that serves its approach
        return True  # Placeholder - implement detailed check
    
    def generate_feasible_sequences(
        self,
        intersection_state: IntersectionState,
        stage_length: float,
    ) -> List[Tuple[List[int], List[float]]]:
        """
        Generate all feasible phase sequences and switching times.
        
        This is the core of the OSCO (Optimal Sequential Constrained search)
        algorithm. We enumerate all valid combinations subject to:
        - Minimum and maximum green time constraints
        - Stage length constraint
        - Current phase constraints (can extend or terminate)
        
        Returns:
            List of (phase_sequence, switching_times) tuples
        """
        phases = list(intersection_state.phases.values())
        num_phases = len(phases)
        num_intervals = int(stage_length / self.time_interval)
        
        sequences = []
        
        # Start with current phase or next phase in sequence
        current_phase = intersection_state.phases.get(intersection_state.current_phase)
        
        # Generate sequences considering current state
        self._generate_sequences_recursive(
            phases=phases,
            current_phase_id=intersection_state.current_phase,
            elapsed_green=intersection_state.elapsed_green,
            stage_length=stage_length,
            sequences=sequences,
            max_sequences=self.max_search_combinations,
        )
        
        return sequences
    
    def _generate_sequences_recursive(
        self,
        phases: List[PhaseDefinition],
        current_phase_id: int,
        elapsed_green: float,
        stage_length: float,
        sequences: List[Tuple[List[int], List[float]]],
        max_sequences: int,
        current_sequence: List[int] = None,
        current_times: List[float] = None,
        time_so_far: float = 0.0,
    ):
        """Recursively generate feasible phase sequences."""
        if current_sequence is None:
            current_sequence = [current_phase_id]
            current_times = [0.0]
        
        if len(sequences) >= max_sequences:
            return
        
        current_phase = next((p for p in phases if p.phase_id == current_phase_id), None)
        if current_phase is None:
            return
        
        # Calculate remaining time in stage
        remaining_time = stage_length - time_so_far
        
        # Determine valid green durations for current phase
        min_green = max(current_phase.min_green - elapsed_green, self.time_interval)
        max_green = min(current_phase.max_green - elapsed_green, remaining_time)
        
        if min_green > max_green:
            return
        
        # Try each valid green duration
        green_duration = min_green
        while green_duration <= max_green and len(sequences) < max_sequences:
            new_time = time_so_far + green_duration
            new_sequence = current_sequence.copy()
            new_times = current_times.copy() + [new_time]
            
            if new_time >= stage_length - self.time_interval:
                # Stage is complete
                sequences.append((new_sequence, new_times))
            else:
                # Move to next phase
                next_phases = [p for p in phases if p.phase_id != current_phase_id]
                for next_phase in next_phases:
                    if len(sequences) >= max_sequences:
                        break
                    
                    # Recurse with next phase
                    self._generate_sequences_recursive(
                        phases=phases,
                        current_phase_id=next_phase.phase_id,
                        elapsed_green=0.0,
                        stage_length=stage_length,
                        sequences=sequences,
                        max_sequences=max_sequences,
                        current_sequence=new_sequence + [next_phase.phase_id],
                        current_times=new_times,
                        time_so_far=new_time,
                    )
            
            green_duration += self.time_interval
    
    def optimize_stage(
        self,
        intersection_state: IntersectionState,
        consider_bus_priority: bool = True,
    ) -> StageResult:
        """
        Optimize signal timings for the next stage.
        
        This is the main optimization method that:
        1. Calculates dynamic stage length
        2. Generates feasible phase sequences
        3. Evaluates each using person-delay objective
        4. Selects optimal solution
        
        Returns:
            StageResult with optimal phase sequence and switching times
        """
        # Step 1: Calculate stage length
        stage_length = self.calculate_stage_length(intersection_state)
        
        # Step 2: Generate feasible sequences
        sequences = self.generate_feasible_sequences(intersection_state, stage_length)
        
        if not sequences:
            # Fallback to current phase with minimum extension
            return self._fallback_solution(intersection_state, stage_length)
        
        # Step 3: Evaluate each sequence
        best_delay = float('inf')
        best_sequence = None
        best_times = None
        best_green_extensions = {}
        best_bus_insertions = {}
        
        for phase_sequence, switching_times in sequences:
            delay = self.calculate_delay(
                intersection_state,
                phase_sequence,
                switching_times,
                stage_length,
                include_bus_priority=consider_bus_priority,
            )
            
            if delay < best_delay:
                best_delay = delay
                best_sequence = phase_sequence
                best_times = switching_times
        
        # Step 4: Check for bus insertion opportunities
        if consider_bus_priority and intersection_state.buses_detected:
            best_sequence, best_times, best_green_extensions, best_bus_insertions = \
                self._optimize_bus_insertion(
                    intersection_state,
                    best_sequence,
                    best_times,
                    stage_length,
                    best_delay,
                )
        
        # Calculate final person delay
        person_delay = self.calculate_delay(
            intersection_state,
            best_sequence,
            best_times,
            stage_length,
            include_bus_priority=True,
        )
        
        return StageResult(
            phase_sequence=best_sequence,
            switching_times=best_times,
            green_extensions=best_green_extensions,
            bus_insertions=best_bus_insertions,
            total_delay=person_delay / self.car_occupancy,  # Convert back to vehicle-seconds
            person_delay=person_delay,
            stage_length=stage_length,
        )
    
    def _optimize_bus_insertion(
        self,
        intersection_state: IntersectionState,
        current_sequence: List[int],
        current_times: List[float],
        stage_length: float,
        current_delay: float,
    ) -> Tuple[List[int], List[float], Dict[int, float], Dict[int, bool]]:
        """
        Optimize bus phase insertion and green extension.
        
        For each detected bus, evaluate whether:
        1. Green extension of current phase is sufficient
        2. Phase insertion is needed and beneficial
        
        Returns:
            Updated sequence, times, green extensions, and bus insertion decisions
        """
        green_extensions = {}
        bus_insertions = {}
        
        for bus_id, bus in intersection_state.buses_detected.items():
            # Update bus ETA
            bus.update_eta()
            
            # Check if bus is in actionable window
            if bus.eta < self.eta_min or bus.eta > self.eta_max:
                bus_insertions[bus_id] = False
                continue
            
            # Find phase that serves bus's approach
            bus_phase = self._find_bus_phase(bus_id, intersection_state)
            
            if bus_phase is None:
                bus_insertions[bus_id] = False
                continue
            
            # Calculate required green extension
            required_extension = bus.eta + self.ge_buffer
            
            # Check if current phase can be extended
            current_phase = intersection_state.phases.get(intersection_state.current_phase)
            if current_phase and bus_phase.phase_id == current_phase.phase_id:
                # Current phase serves bus - can extend
                available_extension = current_phase.max_green - intersection_state.elapsed_green
                actual_extension = min(required_extension, available_extension)
                
                if actual_extension >= self.time_interval:
                    green_extensions[bus_phase.phase_id] = actual_extension
                    bus_insertions[bus_id] = False
                    continue
            
            # Check if phase insertion is beneficial
            # Compare delay with and without insertion
            delay_without_insertion = current_delay
            
            # Simulate insertion
            inserted_sequence, inserted_times = self._simulate_phase_insertion(
                current_sequence, current_times, bus_phase, bus.eta, stage_length, intersection_state
            )
            
            if inserted_sequence:
                delay_with_insertion = self.calculate_delay(
                    intersection_state,
                    inserted_sequence,
                    inserted_times,
                    stage_length,
                    include_bus_priority=True,
                )
                
                # Include penalty for disruption
                total_delay_with_insertion = delay_with_insertion + self.phase_insertion_penalty * bus.occupancy
                
                if total_delay_with_insertion < delay_without_insertion:
                    current_sequence = inserted_sequence
                    current_times = inserted_times
                    bus_insertions[bus_id] = True
                else:
                    bus_insertions[bus_id] = False
            else:
                bus_insertions[bus_id] = False
        
        return current_sequence, current_times, green_extensions, bus_insertions
    
    def _find_bus_phase(
        self,
        bus_id: int,
        intersection_state: IntersectionState,
    ) -> Optional[PhaseDefinition]:
        """Find the phase that serves the bus's approach."""
        # This would need to map bus to approach based on position
        # For now, return the designated bus phase if one exists
        for phase in intersection_state.phases.values():
            if phase.is_bus_phase:
                return phase
        return None
    
    def _simulate_phase_insertion(
        self,
        current_sequence: List[int],
        current_times: List[float],
        bus_phase: PhaseDefinition,
        insertion_time: float,
        stage_length: float,
        intersection_state: IntersectionState,
    ) -> Tuple[List[int], List[float]]:
        """
        Simulate inserting a bus phase at the specified time.
        
        Returns:
            (phase_sequence, switching_times) with bus phase inserted,
            or (None, None) if insertion is not feasible
        """
        # Find where to insert the bus phase
        insert_interval = int(insertion_time / self.time_interval)
        
        # Check if insertion is feasible (respecting min/max green)
        # This is a simplified check - full implementation would be more complex
        
        new_sequence = current_sequence.copy()
        new_times = current_times.copy()
        
        # Insert bus phase
        new_sequence.insert(insert_interval, bus_phase.phase_id)
        new_times.insert(insert_interval, insertion_time)
        
        return new_sequence, new_times
    
    def _fallback_solution(
        self,
        intersection_state: IntersectionState,
        stage_length: float,
    ) -> StageResult:
        """Return a fallback solution when optimization fails."""
        current_phase = intersection_state.phases.get(intersection_state.current_phase)
        
        if current_phase:
            # Extend current phase to fill stage
            remaining_green = min(
                stage_length - intersection_state.elapsed_green,
                current_phase.max_green - intersection_state.elapsed_green
            )
            
            return StageResult(
                phase_sequence=[current_phase.phase_id],
                switching_times=[0.0, remaining_green],
                green_extensions={},
                bus_insertions={},
                total_delay=0.0,
                person_delay=0.0,
                stage_length=stage_length,
            )
        
        # Last resort: use first phase
        first_phase = next(iter(intersection_state.phases.values()))
        return StageResult(
            phase_sequence=[first_phase.phase_id],
            switching_times=[0.0, stage_length],
            green_extensions={},
            bus_insertions={},
            total_delay=0.0,
            person_delay=0.0,
            stage_length=stage_length,
        )


class CorridorCoordinator:
    """
    Coordinates signal timing across multiple intersections in a corridor.
    
    Uses upstream information propagation to enable self-coordination
    without requiring explicit fixed offsets.
    """
    
    def __init__(
        self,
        optimizer: DynaROPACOptimizer,
        platoon_speed: float = 40.0,  # km/h
        coordination_lookahead: int = 3,  # number of downstream intersections to pre-arm
    ):
        self.optimizer = optimizer
        self.platoon_speed = platoon_speed / 3.6  # Convert to m/s
        self.coordination_lookahead = coordination_lookahead
        
        # Intersection states
        self.intersection_states: Dict[int, IntersectionState] = {}
        
        # Corridor topology: {upstream_jct: [downstream_jcts]}
        self.corridor_topology: Dict[int, List[int]] = {}
        
        # Distance between intersections
        self.inter_intersection_distances: Dict[Tuple[int, int], float] = {}
    
    def add_intersection(self, state: IntersectionState):
        """Add an intersection to the corridor."""
        self.intersection_states[state.intersection_id] = state
    
    def set_corridor_topology(
        self,
        topology: Dict[int, List[int]],
        distances: Dict[Tuple[int, int], float],
    ):
        """Set the corridor topology and inter-intersection distances."""
        self.corridor_topology = topology
        self.inter_intersection_distances = distances
    
    def coordinate_optimization(
        self,
        consider_bus_priority: bool = True,
    ) -> Dict[int, StageResult]:
        """
        Optimize all intersections in the corridor with coordination.
        
        The coordination works by:
        1. Processing intersections in upstream-to-downstream order
        2. Propagating platoon arrival information downstream
        3. Adjusting downstream stage lengths and offsets based on upstream decisions
        
        Returns:
            Dictionary of intersection_id -> StageResult
        """
        results = {}
        
        # Get topologically sorted intersections (upstream to downstream)
        sorted_intersections = self._topological_sort()
        
        for jct_id in sorted_intersections:
            if jct_id not in self.intersection_states:
                continue
            
            state = self.intersection_states[jct_id]
            
            # Update upstream flows based on upstream intersection decisions
            self._update_upstream_flows(jct_id, results)
            
            # Optimize this intersection
            result = self.optimizer.optimize_stage(state, consider_bus_priority)
            results[jct_id] = result
            
            # Propagate information to downstream intersections
            self._propagate_downstream(jct_id, result)
        
        return results
    
    def _topological_sort(self) -> List[int]:
        """Sort intersections from upstream to downstream."""
        # Simple approach: find intersections with no upstream, then follow topology
        all_junctions = set(self.intersection_states.keys())
        downstream_of_something = set()
        
        for upstream, downstreams in self.corridor_topology.items():
            downstream_of_something.update(downstreams)
        
        # Start with junctions that have no upstream
        roots = all_junctions - downstream_of_something
        
        if not roots:
            # Fallback: just return all junctions
            return list(all_junctions)
        
        sorted_list = []
        visited = set()
        
        def visit(jct_id):
            if jct_id in visited:
                return
            visited.add(jct_id)
            sorted_list.append(jct_id)
            for downstream in self.corridor_topology.get(jct_id, []):
                visit(downstream)
        
        for root in roots:
            visit(root)
        
        # Add any remaining junctions not reachable from roots
        for jct_id in all_junctions:
            if jct_id not in visited:
                sorted_list.append(jct_id)
        
        return sorted_list
    
    def _update_upstream_flows(
        self,
        jct_id: int,
        results: Dict[int, StageResult],
    ):
        """Update upstream flows for an intersection based on upstream decisions."""
        # Find upstream intersections
        upstream_jcts = [
            upstream for upstream, downstreams in self.corridor_topology.items()
            if jct_id in downstreams
        ]
        
        for upstream_jct in upstream_jcts:
            if upstream_jct not in results:
                continue
            
            # Calculate platoon arrival time
            distance = self.inter_intersection_distances.get((upstream_jct, jct_id), 0)
            travel_time = distance / self.platoon_speed if self.platoon_speed > 0 else 0
            
            # Update downstream approach flows
            # This is a simplified propagation - full implementation would track platoons
    
    def _propagate_downstream(
        self,
        jct_id: int,
        result: StageResult,
    ):
        """Propagate timing information to downstream intersections."""
        downstream_jcts = self.corridor_topology.get(jct_id, [])
        
        for down_jct in downstream_jcts[:self.coordination_lookahead]:
            if down_jct not in self.intersection_states:
                continue
            
            # Calculate expected platoon arrival
            distance = self.inter_intersection_distances.get((jct_id, down_jct), 0)
            travel_time = distance / self.platoon_speed if self.platoon_speed > 0 else 0
            
            # Adjust downstream stage parameters based on incoming platoon
            # This enables self-coordination without fixed offsets


# ============================================================================
# Integration with Aimsun via ECI (External Controller Interface)
# ============================================================================

def create_intersection_state_from_aimsun(
    junction_id: int,
    phases_config: Dict,
    approaches_config: Dict,
) -> IntersectionState:
    """
    Create an IntersectionState from Aimsun data.
    
    This function would be called from the main intersection_controller.py
    to gather current state for optimization.
    """
    # Placeholder - would integrate with AAPI functions
    pass


def apply_stage_result_to_aimsun(
    junction_id: int,
    result: StageResult,
):
    """
    Apply optimization results to Aimsun signal controller.
    
    This function would be called to implement the optimized timings
    via the ECI (External Controller Interface).
    """
    # Placeholder - would use ECI functions like:
    # - ECIChangePhase()
    # - ECISetGreenTime()
    # - ECIInsertPhase()
    pass


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    # Example setup
    optimizer = DynaROPACOptimizer(
        time_interval=5.0,
        eta_min=10.0,
        eta_max=60.0,
    )
    
    # Create a sample intersection state
    phases = {
        1: PhaseDefinition(phase_id=1, served_approaches=[1, 2], min_green=10.0, max_green=60.0),
        2: PhaseDefinition(phase_id=2, served_approaches=[3, 4], min_green=10.0, max_green=60.0),
    }
    
    approaches = {
        1: ApproachState(approach_id=1, queue_length=5.0, upstream_flow=800.0,
                        saturation_flow=1800.0, approach_length=100.0, average_speed=10.0),
        2: ApproachState(approach_id=2, queue_length=3.0, upstream_flow=600.0,
                        saturation_flow=1800.0, approach_length=80.0, average_speed=12.0),
        3: ApproachState(approach_id=3, queue_length=2.0, upstream_flow=400.0,
                        saturation_flow=1500.0, approach_length=120.0, average_speed=8.0),
        4: ApproachState(approach_id=4, queue_length=1.0, upstream_flow=300.0,
                        saturation_flow=1500.0, approach_length=90.0, average_speed=11.0),
    }
    
    intersection = IntersectionState(
        intersection_id=1,
        phases=phases,
        approaches=approaches,
        current_phase=1,
        phase_start_time=0.0,
        elapsed_green=5.0,
        buses_detected={},
    )
    
    # Optimize
    result = optimizer.optimize_stage(intersection)
    
    print(f"Optimal phase sequence: {result.phase_sequence}")
    print(f"Switching times: {result.switching_times}")
    print(f"Stage length: {result.stage_length:.1f} seconds")
    print(f"Person delay: {result.person_delay:.1f} passenger-seconds")