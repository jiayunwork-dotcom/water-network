import numpy as np
from typing import Dict, List, Optional, Tuple
from models import WaterNetwork, NodeType
from hydraulic import run_hydraulic_with_relaxation


DEFAULT_RESIDENTIAL_PATTERN = [
    0.3, 0.2, 0.2, 0.2, 0.3, 0.5,
    1.2, 1.8, 1.6, 1.2, 1.0, 0.9,
    1.2, 1.0, 0.9, 0.9, 1.0, 1.2,
    1.6, 1.8, 1.4, 1.0, 0.6, 0.4,
]

DEFAULT_COMMERCIAL_PATTERN = [
    0.2, 0.1, 0.1, 0.1, 0.1, 0.2,
    0.5, 1.0, 1.5, 1.8, 1.8, 1.6,
    1.4, 1.6, 1.8, 1.8, 1.5, 1.0,
    0.8, 0.6, 0.4, 0.3, 0.3, 0.2,
]

DEFAULT_INDUSTRIAL_PATTERN = [
    0.8, 0.8, 0.8, 0.8, 0.8, 0.9,
    1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
    0.9, 1.0, 1.0, 1.0, 1.0, 1.0,
    0.9, 0.8, 0.8, 0.8, 0.8, 0.8,
]

DEMAND_PATTERNS = {
    "居民区": DEFAULT_RESIDENTIAL_PATTERN,
    "商业区": DEFAULT_COMMERCIAL_PATTERN,
    "工业区": DEFAULT_INDUSTRIAL_PATTERN,
}


def set_demand_pattern(network: WaterNetwork, group: str,
                       pattern: List[float]):
    for node in network.nodes.values():
        if node.node_type == NodeType.JUNCTION and node.demand_group == group:
            node.pattern_24h = pattern[:]
            node.daily_demand = node.demand


def set_demand_patterns_batch(network: WaterNetwork,
                              patterns: Optional[Dict[str, List[float]]] = None):
    if patterns is None:
        patterns = DEMAND_PATTERNS
    for group, pattern in patterns.items():
        set_demand_pattern(network, group, pattern)


def apply_demand_at_hour(network: WaterNetwork, hour: int):
    for node in network.nodes.values():
        if node.node_type == NodeType.JUNCTION:
            node.demand = node.get_demand_at_hour(hour)


def run_extended_period(network: WaterNetwork, method: str = "gradient",
                        hours: int = 24) -> Dict[int, Dict]:
    results = {}
    original_demands = {}
    for nid, node in network.nodes.items():
        original_demands[nid] = node.demand

    for hour in range(hours):
        apply_demand_at_hour(network, hour)
        try:
            run_hydraulic_with_relaxation(network, method)
        except Exception as e:
            results[hour] = {
                "error": str(e),
                "node_heads": {},
                "node_pressures": {},
                "link_flows": {},
                "link_velocities": {},
            }
            continue

        node_heads = {}
        node_pressures = {}
        node_demands = {}
        for nid, node in network.nodes.items():
            node_heads[nid] = node.head
            node_pressures[nid] = node.pressure
            node_demands[nid] = node.demand

        link_flows = {}
        link_velocities = {}
        link_head_losses = {}
        for lid, link in network.links.items():
            link_flows[lid] = link.flow
            link_velocities[lid] = link.velocity
            link_head_losses[lid] = link.head_loss

        results[hour] = {
            "node_heads": node_heads,
            "node_pressures": node_pressures,
            "node_demands": node_demands,
            "link_flows": link_flows,
            "link_velocities": link_velocities,
            "link_head_losses": link_head_losses,
        }

    for nid, node in network.nodes.items():
        node.demand = original_demands[nid]

    return results
