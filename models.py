import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class NodeType(Enum):
    SOURCE = "source"
    TANK = "tank"
    JUNCTION = "junction"


class PipeMaterial(Enum):
    CAST_IRON = "铸铁"
    DUCTILE_IRON = "球墨铸铁"
    PE = "PE"
    STEEL = "钢管"


MATERIAL_ROUGHNESS = {
    PipeMaterial.CAST_IRON: 100,
    PipeMaterial.DUCTILE_IRON: 130,
    PipeMaterial.PE: 140,
    PipeMaterial.STEEL: 120,
}


class ElementType(Enum):
    PIPE = "pipe"
    VALVE = "valve"
    PUMP = "pump"
    CHECK_VALVE = "check_valve"


@dataclass
class Node:
    id: str
    node_type: NodeType
    x: float = 0.0
    y: float = 0.0
    elevation: float = 0.0
    demand: float = 0.0
    head: Optional[float] = None
    pressure: Optional[float] = None
    demand_group: str = ""
    daily_demand: float = 0.0
    pattern_24h: Optional[List[float]] = None
    min_level: float = 0.0
    max_level: float = 10.0
    init_level: float = 5.0
    building_type: str = "multi"
    dma_zone: str = ""

    def get_demand_at_hour(self, hour: int) -> float:
        if self.node_type == NodeType.SOURCE:
            return 0.0
        if self.node_type == NodeType.TANK:
            return 0.0
        if self.pattern_24h is not None and self.daily_demand > 0:
            idx = hour % 24
            return self.daily_demand * self.pattern_24h[idx]
        return self.demand


@dataclass
class Link:
    id: str
    element_type: ElementType
    start_node: str
    end_node: str
    diameter: float = 300.0
    length: float = 100.0
    roughness: float = 130.0
    material: PipeMaterial = PipeMaterial.DUCTILE_IRON
    flow: Optional[float] = None
    velocity: Optional[float] = None
    head_loss: Optional[float] = None
    status: str = "open"
    setting: float = 100.0
    pump_a: float = 50.0
    pump_b: float = 0.001
    minor_loss: float = 0.0

    def get_roughness(self) -> float:
        if self.roughness > 0:
            return self.roughness
        return MATERIAL_ROUGHNESS.get(self.material, 120)


class WaterNetwork:
    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.links: Dict[str, Link] = {}
        self.leaks: Dict[str, dict] = {}

    def add_node(self, node: Node):
        self.nodes[node.id] = node

    def remove_node(self, node_id: str):
        links_to_remove = [
            lid for lid, l in self.links.items()
            if l.start_node == node_id or l.end_node == node_id
        ]
        for lid in links_to_remove:
            del self.links[lid]
        if node_id in self.nodes:
            del self.nodes[node_id]

    def add_link(self, link: Link):
        self.links[link.id] = link

    def remove_link(self, link_id: str):
        if link_id in self.links:
            del self.links[link_id]

    def get_source_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.node_type == NodeType.SOURCE]

    def get_tank_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.node_type == NodeType.TANK]

    def get_junction_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.node_type == NodeType.JUNCTION]

    def get_fixed_head_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values()
                if n.node_type in (NodeType.SOURCE, NodeType.TANK)]

    def get_connected_links(self, node_id: str) -> List[Link]:
        return [l for l in self.links.values()
                if l.start_node == node_id or l.end_node == node_id]

    def add_leak(self, link_id: str, position: float, area_mm2: float,
                 pipe_type: str = "metal"):
        self.leaks[link_id] = {
            "position": position,
            "area_mm2": area_mm2,
            "pipe_type": pipe_type,
            "flow": 0.0,
        }

    def remove_leak(self, link_id: str):
        if link_id in self.leaks:
            del self.leaks[link_id]

    def clear_leaks(self):
        self.leaks.clear()

    def get_node_index_map(self) -> Dict[str, int]:
        idx = 0
        mapping = {}
        for nid in sorted(self.nodes.keys()):
            mapping[nid] = idx
            idx += 1
        return mapping

    def get_link_index_map(self) -> Dict[str, int]:
        idx = 0
        mapping = {}
        for lid in sorted(self.links.keys()):
            mapping[lid] = idx
            idx += 1
        return mapping

    def to_dataframe(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        node_rows = []
        for n in self.nodes.values():
            node_rows.append({
                "id": n.id, "type": n.node_type.value,
                "x": n.x, "y": n.y, "elevation": n.elevation,
                "demand": n.demand, "head": n.head, "pressure": n.pressure,
                "demand_group": n.demand_group,
                "daily_demand": n.daily_demand,
                "building_type": n.building_type,
            })
        link_rows = []
        for l in self.links.values():
            link_rows.append({
                "id": l.id, "type": l.element_type.value,
                "start_node": l.start_node, "end_node": l.end_node,
                "diameter": l.diameter, "length": l.length,
                "roughness": l.get_roughness(),
                "material": l.material.value,
                "status": l.status, "setting": l.setting,
                "pump_a": l.pump_a, "pump_b": l.pump_b,
            })
        return pd.DataFrame(node_rows), pd.DataFrame(link_rows)

    def from_csv(self, nodes_csv: str, links_csv: str):
        import io
        df_nodes = pd.read_csv(io.StringIO(nodes_csv))
        df_links = pd.read_csv(io.StringIO(links_csv))
        self.nodes.clear()
        self.links.clear()
        for _, row in df_nodes.iterrows():
            ntype = NodeType(row.get("type", "junction"))
            n = Node(
                id=str(row["id"]),
                node_type=ntype,
                x=float(row.get("x", 0)),
                y=float(row.get("y", 0)),
                elevation=float(row.get("elevation", 0)),
                demand=float(row.get("demand", 0)),
                demand_group=str(row.get("demand_group", "")),
                daily_demand=float(row.get("daily_demand", 0)),
                building_type=str(row.get("building_type", "multi")),
            )
            if ntype == NodeType.SOURCE:
                n.head = float(row.get("head", 50))
            elif ntype == NodeType.TANK:
                n.min_level = float(row.get("min_level", 0))
                n.max_level = float(row.get("max_level", 10))
                n.init_level = float(row.get("init_level", 5))
                n.head = n.elevation + n.init_level
            self.nodes[n.id] = n
        for _, row in df_links.iterrows():
            etype = ElementType(row.get("type", "pipe"))
            mat = PipeMaterial(row.get("material", "球墨铸铁"))
            l = Link(
                id=str(row["id"]),
                element_type=etype,
                start_node=str(row["start_node"]),
                end_node=str(row["end_node"]),
                diameter=float(row.get("diameter", 300)),
                length=float(row.get("length", 100)),
                roughness=float(row.get("roughness", 0)),
                material=mat,
                status=str(row.get("status", "open")),
                setting=float(row.get("setting", 100)),
                pump_a=float(row.get("pump_a", 50)),
                pump_b=float(row.get("pump_b", 0.001)),
            )
            self.links[l.id] = l

    def get_adjacency(self) -> Dict[str, List[Tuple[str, str, str]]]:
        adj = {nid: [] for nid in self.nodes}
        for lid, link in self.links.items():
            adj[link.start_node].append((link.end_node, lid, "forward"))
            adj[link.end_node].append((link.start_node, lid, "reverse"))
        return adj

    def validate(self) -> List[str]:
        errors = []
        if not self.nodes:
            errors.append("管网为空，没有节点")
        if not self.links:
            errors.append("管网为空，没有管段")
        sources = self.get_source_nodes()
        if not sources:
            errors.append("缺少水源节点")
        for lid, link in self.links.items():
            if link.start_node not in self.nodes:
                errors.append(f"管段 {lid} 的起始节点 {link.start_node} 不存在")
            if link.end_node not in self.nodes:
                errors.append(f"管段 {lid} 的终止节点 {link.end_node} 不存在")
        if len(self.nodes) > 500:
            errors.append(f"节点数 {len(self.nodes)} 超过上限500")
        if len(self.links) > 800:
            errors.append(f"管段数 {len(self.links)} 超过上限800")
        return errors
