"""
DynaROPAC Integration Module for Batch Runner

This module provides integration between the DynaROPAC optimizer and the 
batch_runner.py framework. It adds:

1. DynaROPAC as a new strategy option
2. System-wide delay minimization across all intersections
3. Adaptive coordination that turns on/off based on traffic conditions
4. Enhanced HTML dashboard with coordination status visualization

Usage:
    # Add to batch_runner.py EXPERIMENTS list:
    from dynaropac_batch_integration import DYNAOPAC_EXPERIMENTS
    EXPERIMENTS.extend(DYNAOPAC_EXPERIMENTS)
"""

# =============================================================================
# DynaROPAC Experiment Definitions
# =============================================================================

DYNAOPAC_EXPERIMENTS = [
    # DynaROPAC with coordination ON
    {
        "name":                 "DYNAOPAC_COORD",
        "strategy":             "DYNAOPAC",
        "coordinated":          True,
        "coordination_algo":    "ADAPTIVE",  # Uses DynaROPAC's built-in coordination
        "active_intersections": None,
    },
    # DynaROPAC with coordination OFF (independent intersections)
    {
        "name":                 "DYNAOPAC_INDEP",
        "strategy":             "DYNAOPAC",
        "coordinated":          False,
        "coordination_algo":    "KALMAN",
        "active_intersections": None,
    },
    # DynaROPAC with shockwave-based coordination
    {
        "name":                 "DYNAOPAC_COORD_SHOCKWAVE",
        "strategy":             "DYNAOPAC",
        "coordinated":          True,
        "coordination_algo":    "SHOCKWAVE",
        "active_intersections": None,
    },
]


# =============================================================================
# Adaptive Coordination Logic
# =============================================================================

def should_enable_coordination(
    total_delay: float,
    bus_count: int,
    demand_level: float,
    coordination_threshold: float = 0.7,
) -> bool:
    """
    Determine whether coordination should be enabled based on traffic conditions.
    
    Coordination is beneficial when:
    1. There are buses in the corridor (bus_count > 0)
    2. Demand is moderate to high (demand_level > threshold)
    3. Total delay exceeds a threshold indicating congestion
    
    Args:
        total_delay: Total system delay in vehicle-hours
        bus_count: Number of buses detected in the corridor
        demand_level: Demand level as fraction of capacity (0-1)
        coordination_threshold: Threshold for enabling coordination (default 0.7)
    
    Returns:
        True if coordination should be enabled, False otherwise
    """
    # Always enable if there are buses and demand is moderate+
    if bus_count > 0 and demand_level >= coordination_threshold:
        return True
    
    # Enable if delay is very high (indicating congestion that coordination can help)
    if total_delay > 100.0:  # 100 vehicle-hours threshold
        return True
    
    # Disable for low demand / no buses (coordination overhead not worth it)
    return False


def calculate_coordination_benefit(
    uncoordinated_delay: float,
    coordinated_delay: float,
    bus_delay_saved: float,
    car_delay_added: float,
    bus_occupancy: float = 40.0,
    car_occupancy: float = 1.5,
) -> float:
    """
    Calculate the net person-delay benefit of coordination.
    
    Args:
        uncoordinated_delay: Total delay without coordination (vehicle-hours)
        coordinated_delay: Total delay with coordination (vehicle-hours)
        bus_delay_saved: Bus delay reduction from coordination (vehicle-hours)
        car_delay_added: Car delay increase from coordination (vehicle-hours)
        bus_occupancy: Average bus occupancy (passengers)
        car_occupancy: Average car occupancy (passengers)
    
    Returns:
        Net person-delay benefit in passenger-hours (positive = coordination helps)
    """
    # Convert vehicle delay to person delay
    bus_person_delay_saved = bus_delay_saved * bus_occupancy
    car_person_delay_lost = car_delay_added * car_occupancy
    
    # Net benefit
    net_benefit = bus_person_delay_saved - car_person_delay_lost
    
    return net_benefit


# =============================================================================
# System-Wide Delay Minimization
# =============================================================================

def minimize_system_delay(
    intersection_states: dict,
    corridor_topology: dict,
    bus_positions: dict,
    time_horizon: float = 300.0,  # 5 minutes
) -> dict:
    """
    Minimize total delay across all intersections simultaneously.
    
    This function implements the system-wide optimization by:
    1. Building a model of the entire corridor
    2. Evaluating coordination patterns
    3. Selecting the pattern that minimizes total person-delay
    
    Args:
        intersection_states: Dict of {jct_id: IntersectionState}
        corridor_topology: Dict of {upstream_jct: [downstream_jcts]}
        bus_positions: Dict of {bus_id: (x, y, speed)}
        time_horizon: Optimization horizon in seconds
    
    Returns:
        Dict with optimal settings for each intersection
    """
    from dynaropac_controller import (
        DynaROPACOptimizer,
        CorridorCoordinator,
        IntersectionState,
    )
    
    # Create optimizer with system-wide settings
    optimizer = DynaROPACOptimizer(
        time_interval=5.0,
        eta_min=10.0,
        eta_max=60.0,
        ge_buffer=5.0,
        car_occupancy=1.5,
        shockwave_speed=4.17,
        phase_insertion_penalty=30.0,
        max_search_combinations=5000,  # Reduced for system-wide optimization
    )
    
    # Create corridor coordinator
    coordinator = CorridorCoordinator(
        optimizer=optimizer,
        platoon_speed=40.0,  # km/h
        coordination_lookahead=3,
    )
    
    # Add all intersections to coordinator
    for jct_id, state in intersection_states.items():
        coordinator.add_intersection(state)
    
    # Set corridor topology
    distances = {}  # Would be populated from network geometry
    coordinator.set_corridor_topology(corridor_topology, distances)
    
    # Run coordinated optimization
    results = coordinator.coordinate_optimization(consider_bus_priority=True)
    
    return results


# =============================================================================
# HTML Dashboard Enhancement for DynaROPAC
# =============================================================================

def add_dynaropac_dashboard_section(html_content: str, results: dict) -> str:
    """
    Add DynaROPAC-specific sections to the HTML dashboard.
    
    Adds:
    1. Coordination status indicator (ON/OFF based on conditions)
    2. System-wide delay comparison
    3. Per-intersection optimization metrics
    4. Bus priority effectiveness metrics
    
    Args:
        html_content: Existing HTML dashboard content
        results: Dict with optimization results
    
    Returns:
        Enhanced HTML content
    """
    
    # Calculate coordination metrics
    coordination_enabled = results.get('coordination_enabled', False)
    system_delay = results.get('system_delay', 0)
    bus_delay_saved = results.get('bus_delay_saved', 0)
    coordination_benefit = results.get('coordination_benefit', 0)
    
    # Create DynaROPAC section
    dynaropac_section = f'''
    <div class="dynaropac-section">
        <h2>DynaROPAC Adaptive Control</h2>
        
        <div class="coordination-status {'enabled' if coordination_enabled else 'disabled'}">
            <h3>Coordination Status</h3>
            <div class="status-indicator">
                <span class="status-dot"></span>
                <span class="status-text">{'ACTIVE' if coordination_enabled else 'INACTIVE'}</span>
            </div>
            <p class="status-reason">{results.get('coordination_reason', '')}</p>
        </div>
        
        <div class="metrics-grid">
            <div class="metric-card">
                <h4>System Delay</h4>
                <div class="metric-value">{system_delay:.1f}</div>
                <div class="metric-unit">vehicle-hours</div>
            </div>
            <div class="metric-card">
                <h4>Bus Delay Saved</h4>
                <div class="metric-value">{bus_delay_saved:.1f}</div>
                <div class="metric-unit">vehicle-hours</div>
            </div>
            <div class="metric-card">
                <h4>Coordination Benefit</h4>
                <div class="metric-value {'positive' if coordination_benefit > 0 else 'negative'}">
                    {coordination_benefit:+.1f}
                </div>
                <div class="metric-unit">passenger-hours</div>
            </div>
        </div>
        
        <div class="optimization-details">
            <h3>Per-Intersection Optimization</h3>
            <table class="intersection-table">
                <thead>
                    <tr>
                        <th>Intersection</th>
                        <th>Stage Length (s)</th>
                        <th>Delay (veh-hrs)</th>
                        <th>Bus Actions</th>
                        <th>Coordination Role</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(f'''
                    <tr>
                        <td>{jct_id}</td>
                        <td>{info.get('stage_length', 'N/A')}</td>
                        <td>{info.get('delay', 'N/A'):.1f}</td>
                        <td>{info.get('bus_actions', 'N/A')}</td>
                        <td>{info.get('coordination_role', 'N/A')}</td>
                    </tr>
                    ''' for jct_id, info in results.get('intersection_details', {}).items())}
                </tbody>
            </table>
        </div>
    </div>
    
    <style>
    .dynaropac-section {{
        margin: 20px 0;
        padding: 20px;
        background: #f8f9fa;
        border-radius: 8px;
    }}
    .coordination-status {{
        padding: 15px;
        border-radius: 8px;
        margin: 15px 0;
    }}
    .coordination-status.enabled {{
        background: #d4edda;
        border: 1px solid #c3e6cb;
    }}
    .coordination-status.disabled {{
        background: #fff3cd;
        border: 1px solid #ffeeba;
    }}
    .status-indicator {{
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 1.2em;
        font-weight: bold;
    }}
    .status-dot {{
        width: 16px;
        height: 16px;
        border-radius: 50%;
    }}
    .enabled .status-dot {{
        background: #28a745;
        box-shadow: 0 0 10px #28a745;
    }}
    .disabled .status-dot {{
        background: #6c757d;
    }}
    .metrics-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 15px;
        margin: 15px 0;
    }}
    .metric-card {{
        background: white;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }}
    .metric-value {{
        font-size: 2em;
        font-weight: bold;
        color: #007bff;
    }}
    .metric-value.positive {{
        color: #28a745;
    }}
    .metric-value.negative {{
        color: #dc3545;
    }}
    .metric-unit {{
        color: #6c757d;
        font-size: 0.9em;
    }}
    .intersection-table {{
        width: 100%;
        border-collapse: collapse;
        margin: 10px 0;
    }}
    .intersection-table th,
    .intersection-table td {{
        padding: 8px 12px;
        text-align: left;
        border-bottom: 1px solid #dee2e6;
    }}
    .intersection-table th {{
        background: #e9ecef;
        font-weight: bold;
    }}
    </style>
    '''
    
    # Insert before closing body tag
    html_content = html_content.replace(
        '</body>',
        f'{dynaropac_section}</body>'
    )
    
    return html_content


# =============================================================================
# Controller Patching for DynaROPAC
# =============================================================================

def patch_controller_for_dynaropac(controller_path: str, coordinated: bool):
    """
    Patch the intersection_controller.py to use DynaROPAC strategy.
    
    This function:
    1. Sets CONTROL_MODE = "DYNAOPAC"
    2. Sets COORDINATED_TSP based on coordination flag
    3. Imports and configures the DynaROPAC optimizer
    4. Sets up adaptive coordination logic
    
    Args:
        controller_path: Path to intersection_controller.py
        coordinated: Whether to enable coordination
    """
    import re
    
    with open(controller_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Set CONTROL_MODE to DYNAOPAC
    content = re.sub(
        r'^(CONTROL_MODE\s*=\s*)["\'].*?["\']',
        'CONTROL_MODE = "DYNAOPAC"',
        content,
        flags=re.MULTILINE
    )
    
    # Set coordination
    coord_val = "True" if coordinated else "False"
    content = re.sub(
        r'^COORDINATED_TSP\s*=\s*(True|False)',
        f'COORDINATED_TSP = {coord_val}',
        content,
        flags=re.MULTILINE
    )
    
    # Add DynaROPAC import if not present
    if 'from dynaropac_controller import' not in content:
        import_line = 'from dynaropac_controller import DynaROPACOptimizer, CorridorCoordinator\n'
        content = content.replace(
            'import intersection_configs\n',
            'import intersection_configs\n' + import_line
        )
    
    with open(controller_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"[DYNAOPAC] Controller patched: coordinated={coordinated}")


# =============================================================================
# Usage Example
# =============================================================================

if __name__ == "__main__":
    print("DynaROPAC Batch Integration Module")
    print("=" * 50)
    print("\nAvailable experiments:")
    for exp in DYNAOPAC_EXPERIMENTS:
        print(f"  - {exp['name']}: {exp['strategy']} (coordinated={exp['coordinated']})")
    
    print("\nTo use, add to batch_runner.py:")
    print("  from dynaropac_batch_integration import DYNAOPAC_EXPERIMENTS")
    print("  EXPERIMENTS.extend(DYNAOPAC_EXPERIMENTS)")