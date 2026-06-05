import numpy as np
from typing import Dict, List, Tuple
from models import WaterNetwork, NodeType, ElementType


def compute_water_age(network: WaterNetwork) -> Dict[str, float]:
    source_nodes = network.get_source_nodes()
    tank_nodes = network.get_tank_nodes()

    node_age = {}
    for nid in network.nodes:
        node_age[nid] = 0.0

    for src in source_nodes:
        node_age[src.id] = 0.0
    for tk in tank_nodes:
        node_age[tk.id] = 0.0

    upstream_count = {}
    for nid, node in network.nodes.items():
        count = 0
        for link in network.links.values():
            if link.end_node == nid and link.flow is not None and link.flow > 0:
                count += 1
            elif link.start_node == nid and link.flow is not None and link.flow < 0:
                count += 1
        upstream_count[nid] = count

    processed = set()
    for src in source_nodes:
        processed.add(src.id)
    for tk in tank_nodes:
        processed.add(tk.id)

    max_iterations = len(network.nodes) * 2
    for _ in range(max_iterations):
        changed = False
        for nid, node in network.nodes.items():
            if nid in processed:
                continue

            inflow_ages = []
            inflow_rates = []

            for link in network.links.values():
                if link.flow is None:
                    continue

                if link.end_node == nid and link.flow > 0:
                    upstream = link.start_node
                    if upstream in processed:
                        D_m = link.diameter / 1000.0
                        area = np.pi * (D_m ** 2) / 4.0
                        flow_abs = abs(link.flow)
                        if flow_abs > 1e-12 and area > 1e-15:
                            velocity = flow_abs / area
                            if velocity > 1e-12:
                                travel_time = link.length / velocity
                            else:
                                travel_time = 0.0
                        else:
                            travel_time = 3600.0

                        inflow_ages.append(node_age[upstream] + travel_time)
                        inflow_rates.append(flow_abs)

                elif link.start_node == nid and link.flow < 0:
                    upstream = link.end_node
                    if upstream in processed:
                        D_m = link.diameter / 1000.0
                        area = np.pi * (D_m ** 2) / 4.0
                        flow_abs = abs(link.flow)
                        if flow_abs > 1e-12 and area > 1e-15:
                            velocity = flow_abs / area
                            if velocity > 1e-12:
                                travel_time = link.length / velocity
                            else:
                                travel_time = 0.0
                        else:
                            travel_time = 3600.0

                        inflow_ages.append(node_age[upstream] + travel_time)
                        inflow_rates.append(flow_abs)

            if inflow_rates:
                total_flow = sum(inflow_rates)
                if total_flow > 1e-12:
                    node_age[nid] = sum(
                        a * f for a, f in zip(inflow_ages, inflow_rates)
                    ) / total_flow
                    processed.add(nid)
                    changed = True

        if not changed:
            remaining = [nid for nid in network.nodes if nid not in processed]
            if not remaining:
                break
            for nid in remaining:
                min_upstream = float('inf')
                for link in network.links.values():
                    if link.flow is None:
                        continue
                    if link.end_node == nid and link.flow > 0:
                        up = link.start_node
                        if up in node_age:
                            min_upstream = min(min_upstream, node_age[up])
                    elif link.start_node == nid and link.flow < 0:
                        up = link.end_node
                        if up in node_age:
                            min_upstream = min(min_upstream, node_age[up])
                if min_upstream < float('inf'):
                    node_age[nid] = min_upstream + 100.0
                    processed.add(nid)

    return node_age


def compute_chlorine(network: WaterNetwork,
                     source_chlorine: float = 1.0,
                     kb: float = 0.5
                     ) -> Dict[str, float]:
    kb_per_sec = kb / 86400.0

    node_chlorine = {}
    for nid in network.nodes:
        node_chlorine[nid] = 0.0

    source_nodes = network.get_source_nodes()
    tank_nodes = network.get_tank_nodes()
    for src in source_nodes:
        node_chlorine[src.id] = source_chlorine
    for tk in tank_nodes:
        node_chlorine[tk.id] = source_chlorine * 0.95

    processed = set()
    for src in source_nodes:
        processed.add(src.id)
    for tk in tank_nodes:
        processed.add(tk.id)

    max_iterations = len(network.nodes) * 2
    for _ in range(max_iterations):
        changed = False
        for nid, node in network.nodes.items():
            if nid in processed:
                continue

            inflow_conc = []
            inflow_rates = []

            for link in network.links.values():
                if link.flow is None:
                    continue

                upstream_nid = None
                if link.end_node == nid and link.flow > 0:
                    upstream_nid = link.start_node
                elif link.start_node == nid and link.flow < 0:
                    upstream_nid = link.end_node

                if upstream_nid is not None and upstream_nid in processed:
                    C0 = node_chlorine[upstream_nid]
                    D_m = link.diameter / 1000.0
                    area = np.pi * (D_m ** 2) / 4.0
                    flow_abs = abs(link.flow)
                    if flow_abs > 1e-12 and area > 1e-15:
                        velocity = flow_abs / area
                        if velocity > 1e-12:
                            travel_time = link.length / velocity
                        else:
                            travel_time = 3600.0
                    else:
                        travel_time = 3600.0

                    C_out = C0 * np.exp(-kb_per_sec * travel_time)
                    inflow_conc.append(C_out)
                    inflow_rates.append(flow_abs)

            if inflow_rates:
                total_flow = sum(inflow_rates)
                if total_flow > 1e-12:
                    mixed_conc = sum(
                        c * f for c, f in zip(inflow_conc, inflow_rates)
                    ) / total_flow
                    node_chlorine[nid] = mixed_conc
                    processed.add(nid)
                    changed = True

        if not changed:
            remaining = [nid for nid in network.nodes if nid not in processed]
            if not remaining:
                break
            for nid in remaining:
                node_chlorine[nid] = 0.0
                processed.add(nid)

    return node_chlorine


def run_water_quality(network: WaterNetwork,
                      source_chlorine: float = 1.0,
                      kb: float = 0.5
                      ) -> Dict:
    water_age = compute_water_age(network)
    chlorine = compute_chlorine(network, source_chlorine, kb)

    non_compliant = []
    for nid, conc in chlorine.items():
        if conc < 0.05:
            non_compliant.append({
                "node_id": nid,
                "chlorine": conc,
                "water_age": water_age.get(nid, 0.0),
            })

    return {
        "water_age": water_age,
        "chlorine": chlorine,
        "non_compliant": non_compliant,
    }
