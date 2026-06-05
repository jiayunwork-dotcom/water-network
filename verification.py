import numpy as np
from copy import deepcopy
from typing import Dict, List
from models import WaterNetwork, NodeType, ElementType
from hydraulic import run_hydraulic_with_relaxation


VELOCITY_MIN = 0.6
VELOCITY_MAX = 3.0
MIN_FREE_PRESSURE_MULTI = 28.0
MIN_FREE_PRESSURE_HIGH = 35.0
FIRE_FLOW_RATE = 0.015
FIRE_MIN_FREE_PRESSURE = 10.0


def check_velocity(network: WaterNetwork) -> List[Dict]:
    warnings = []
    for lid, link in network.links.items():
        if link.element_type in (ElementType.PUMP, ElementType.VALVE, ElementType.CHECK_VALVE):
            continue
        if link.velocity is not None:
            if link.velocity < VELOCITY_MIN:
                warnings.append({
                    "type": "velocity_low",
                    "link_id": lid,
                    "value": link.velocity,
                    "limit": VELOCITY_MIN,
                    "message": f"管段 {lid} 流速 {link.velocity:.2f} m/s 低于下限 {VELOCITY_MIN} m/s",
                })
            elif link.velocity > VELOCITY_MAX:
                warnings.append({
                    "type": "velocity_high",
                    "link_id": lid,
                    "value": link.velocity,
                    "limit": VELOCITY_MAX,
                    "message": f"管段 {lid} 流速 {link.velocity:.2f} m/s 超过上限 {VELOCITY_MAX} m/s",
                })
    return warnings


def check_pressure(network: WaterNetwork) -> List[Dict]:
    violations = []
    for nid, node in network.nodes.items():
        if node.node_type != NodeType.JUNCTION:
            continue
        if node.pressure is not None:
            free_pressure = node.pressure
            if node.building_type == "high":
                min_pressure = MIN_FREE_PRESSURE_HIGH
                building_label = "高层"
            else:
                min_pressure = MIN_FREE_PRESSURE_MULTI
                building_label = "多层"

            if free_pressure < min_pressure:
                violations.append({
                    "type": "pressure_low",
                    "node_id": nid,
                    "value": free_pressure,
                    "limit": min_pressure,
                    "building_type": building_label,
                    "message": f"节点 {nid} 自由水压 {free_pressure:.1f} m 低于{building_label}建筑要求 {min_pressure} m",
                })
    return violations


def check_fire_flow(network: WaterNetwork,
                    fire_nodes: List[str],
                    method: str = "gradient") -> Dict:
    net_copy = deepcopy(network)
    net_copy.leaks.clear()

    for nid in fire_nodes:
        if nid in net_copy.nodes:
            net_copy.nodes[nid].demand += FIRE_FLOW_RATE * 3600.0

    try:
        run_hydraulic_with_relaxation(net_copy, method)
    except Exception as e:
        return {
            "converged": False,
            "error": str(e),
            "violations": [],
            "worst_node": None,
            "worst_pressure": None,
        }

    violations = []
    worst_pressure = float('inf')
    worst_node = None

    for nid, node in net_copy.nodes.items():
        if node.node_type != NodeType.JUNCTION:
            continue
        if node.pressure is not None:
            free_pressure = node.pressure
            if free_pressure < FIRE_MIN_FREE_PRESSURE:
                violations.append({
                    "node_id": nid,
                    "pressure": free_pressure,
                    "limit": FIRE_MIN_FREE_PRESSURE,
                })
            if free_pressure < worst_pressure:
                worst_pressure = free_pressure
                worst_node = nid

    return {
        "converged": True,
        "violations": violations,
        "worst_node": worst_node,
        "worst_pressure": worst_pressure if worst_node else None,
    }


def run_design_check(network: WaterNetwork,
                     fire_nodes: List[str] = None,
                     method: str = "gradient") -> Dict:
    velocity_warnings = check_velocity(network)
    pressure_violations = check_pressure(network)

    fire_result = None
    if fire_nodes:
        fire_result = check_fire_flow(network, fire_nodes, method)

    return {
        "velocity_warnings": velocity_warnings,
        "pressure_violations": pressure_violations,
        "fire_check": fire_result,
        "velocity_ok": len(velocity_warnings) == 0,
        "pressure_ok": len(pressure_violations) == 0,
        "fire_ok": fire_result["converged"] and len(fire_result["violations"]) == 0 if fire_result else None,
    }
