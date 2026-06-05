import numpy as np
from typing import Dict, List, Set, Tuple, Optional
from models import WaterNetwork, NodeType


DMA_ZONE_COLORS = [
    "#FFB3BA", "#BAFFC9", "#BAE1FF", "#FFFFBA", "#E8BAFF",
    "#FFD9BA", "#BAFFEE", "#FFB3E6", "#B3FFE0", "#FFE0B3",
]


def find_boundary_links(network: WaterNetwork) -> List[str]:
    boundary = []
    for lid, link in network.links.items():
        sn = network.nodes.get(link.start_node)
        en = network.nodes.get(link.end_node)
        if sn and en and sn.dma_zone and en.dma_zone:
            if sn.dma_zone != en.dma_zone:
                boundary.append(lid)
    return boundary


def get_zone_nodes(network: WaterNetwork) -> Dict[str, List[str]]:
    zones = {}
    for nid, node in network.nodes.items():
        zone = node.dma_zone
        if zone:
            if zone not in zones:
                zones[zone] = []
            zones[zone].append(nid)
    return zones


def compute_dma_statistics(network: WaterNetwork) -> Dict[str, Dict]:
    zones = get_zone_nodes(network)
    boundary_links = find_boundary_links(network)
    stats = {}
    for zone_name, node_ids in zones.items():
        pressures = []
        min_pressure = float('inf')
        min_pressure_node = ""
        total_demand = 0.0
        for nid in node_ids:
            node = network.nodes[nid]
            if node.pressure is not None and node.node_type == NodeType.JUNCTION:
                pressures.append(node.pressure)
                if node.pressure < min_pressure:
                    min_pressure = node.pressure
                    min_pressure_node = nid
            if node.node_type == NodeType.JUNCTION:
                total_demand += node.demand

        avg_pressure = np.mean(pressures) if pressures else 0.0
        if min_pressure == float('inf'):
            min_pressure = 0.0
            min_pressure_node = ""

        inlet_links = []
        for lid, link in network.links.items():
            if lid not in boundary_links:
                continue
            sn = network.nodes.get(link.start_node)
            en = network.nodes.get(link.end_node)
            if sn and en:
                if sn.dma_zone != zone_name and en.dma_zone == zone_name:
                    inlet_links.append(lid)
                elif en.dma_zone != zone_name and sn.dma_zone == zone_name:
                    inlet_links.append(lid)

        inlet_flow = 0.0
        for lid in inlet_links:
            link = network.links.get(lid)
            if link and link.flow is not None:
                sn = network.nodes.get(link.start_node)
                en = network.nodes.get(link.end_node)
                if sn and en:
                    if sn.dma_zone != zone_name and en.dma_zone == zone_name:
                        inlet_flow += abs(link.flow)
                    elif en.dma_zone != zone_name and sn.dma_zone == zone_name:
                        inlet_flow += abs(link.flow)

        stats[zone_name] = {
            "node_count": len(node_ids),
            "avg_pressure": avg_pressure,
            "min_pressure": min_pressure,
            "min_pressure_node": min_pressure_node,
            "total_demand": total_demand,
            "inlet_flow": inlet_flow,
            "inlet_links": inlet_links,
        }
    return stats


def compute_zone_polygon(nodes_coords: List[Tuple[float, float]],
                         padding: float = 40.0) -> Optional[Dict]:
    if not nodes_coords:
        return None
    if len(nodes_coords) == 1:
        x, y = nodes_coords[0]
        return {
            "type": "circle",
            "xref": "x", "yref": "y",
            "x0": x - padding, "y0": y - padding,
            "x1": x + padding, "y1": y + padding,
        }
    if len(nodes_coords) == 2:
        xs = [p[0] for p in nodes_coords]
        ys = [p[1] for p in nodes_coords]
        return {
            "type": "rect",
            "xref": "x", "yref": "y",
            "x0": min(xs) - padding, "y0": min(ys) - padding,
            "x1": max(xs) + padding, "y1": max(ys) + padding,
        }
    points = np.array(nodes_coords)
    try:
        from scipy.spatial import ConvexHull
        hull = ConvexHull(points)
        hull_points = points[hull.vertices]
        center = hull_points.mean(axis=0)
        expanded = []
        for p in hull_points:
            direction = p - center
            norm = np.linalg.norm(direction)
            if norm > 0:
                expanded.append(p + direction / norm * padding)
            else:
                expanded.append(p)
        expanded = np.array(expanded)
        path = "M " + " L ".join([f"{p[0]},{p[1]}" for p in expanded]) + " Z"
        return {"type": "path", "path": path, "xref": "x", "yref": "y"}
    except Exception:
        xs = [p[0] for p in nodes_coords]
        ys = [p[1] for p in nodes_coords]
        return {
            "type": "rect",
            "xref": "x", "yref": "y",
            "x0": min(xs) - padding, "y0": min(ys) - padding,
            "x1": max(xs) + padding, "y1": max(ys) + padding,
        }
