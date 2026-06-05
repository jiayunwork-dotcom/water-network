import numpy as np
from typing import Dict, List, Tuple
from models import WaterNetwork, NodeType
from hydraulic import run_hydraulic_with_relaxation


G = 9.81


def compute_leak_flow(area_mm2: float, pressure: float,
                      pipe_type: str = "metal",
                      Cd: float = 0.6,
                      P_ref: float = 30.0) -> float:
    A0 = area_mm2 * 1e-6
    if pressure <= 0:
        return 0.0
    if pipe_type == "plastic":
        A = A0 * (pressure / P_ref) ** 1.5
    else:
        A = A0 * (pressure / P_ref) ** 0.5
    Q_leak = Cd * A * np.sqrt(2 * G * pressure)
    return Q_leak


def get_leak_pressure(network: WaterNetwork, link_id: str,
                      position: float) -> float:
    link = network.links[link_id]
    start_node = network.nodes.get(link.start_node)
    end_node = network.nodes.get(link.end_node)
    if start_node is None or end_node is None:
        return 0.0
    p_start = start_node.pressure if start_node.pressure else 0.0
    p_end = end_node.pressure if end_node.pressure else 0.0
    p_leak = p_start * (1 - position) + p_end * position
    return max(p_leak, 0.0)


def run_leak_simulation(network: WaterNetwork, method: str = "gradient",
                        max_outer_iter: int = 20,
                        convergence_tol: float = 0.01,
                        Cd: float = 0.6) -> Dict[str, float]:
    if not network.leaks:
        return run_hydraulic_with_relaxation(network, method)

    leak_flows = {lid: 0.0 for lid in network.leaks}
    original_demands = {nid: node.demand for nid, node in network.nodes.items()}

    for outer_iter in range(max_outer_iter):
        for nid, node in network.nodes.items():
            node.demand = original_demands[nid]

        for lid, leak_info in network.leaks.items():
            if lid not in network.links:
                continue
            link = network.links[lid]
            position = leak_info["position"]
            area_mm2 = leak_info["area_mm2"]
            pipe_type = leak_info["pipe_type"]

            pressure = get_leak_pressure(network, lid, position)
            Q_leak = compute_leak_flow(area_mm2, pressure, pipe_type, Cd)
            leak_flows[lid] = Q_leak

            leak_node_id = link.start_node if position <= 0.5 else link.end_node
            if leak_node_id in network.nodes:
                network.nodes[leak_node_id].demand += Q_leak * 3600.0

        try:
            run_hydraulic_with_relaxation(network, method)
        except Exception:
            break

        converged = True
        for lid, leak_info in network.leaks.items():
            position = leak_info["position"]
            area_mm2 = leak_info["area_mm2"]
            pipe_type = leak_info["pipe_type"]
            pressure = get_leak_pressure(network, lid, position)
            new_Q_leak = compute_leak_flow(area_mm2, pressure, pipe_type, Cd)
            old_Q_leak = leak_flows[lid]
            if old_Q_leak > 1e-10:
                relative_change = abs(new_Q_leak - old_Q_leak) / old_Q_leak
            else:
                relative_change = abs(new_Q_leak)
            if relative_change > convergence_tol:
                converged = False
            leak_flows[lid] = new_Q_leak

        if converged:
            break

    for lid in network.leaks:
        network.leaks[lid]["flow"] = leak_flows[lid]

    for nid, node in network.nodes.items():
        node.demand = original_demands[nid]

    return {lid: network.links[lid].flow for lid in network.links}
