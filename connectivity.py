import networkx as nx
from typing import Dict, List, Set, Tuple
from models import WaterNetwork, NodeType


def build_graph(network: WaterNetwork) -> nx.Graph:
    G = nx.Graph()
    for nid in network.nodes:
        G.add_node(nid)
    for lid, link in network.links.items():
        G.add_edge(link.start_node, link.end_node, link_id=lid)
    return G


def find_connected_components(network: WaterNetwork) -> List[Set[str]]:
    G = build_graph(network)
    return list(nx.connected_components(G))


def find_isolated_nodes(network: WaterNetwork) -> Set[str]:
    G = build_graph(network)
    return {nid for nid in network.nodes if G.degree(nid) == 0}


def find_isolated_subnets(network: WaterNetwork) -> List[Set[str]]:
    G = build_graph(network)
    components = list(nx.connected_components(G))
    source_nodes = {n.id for n in network.get_source_nodes()}
    tank_nodes = {n.id for n in network.get_tank_nodes()}
    fixed_nodes = source_nodes | tank_nodes
    isolated_subnets = []
    for comp in components:
        if not (comp & fixed_nodes):
            isolated_subnets.append(comp)
    return isolated_subnets


def find_dead_end_pipes(network: WaterNetwork) -> List[str]:
    G = build_graph(network)
    source_ids = {n.id for n in network.get_source_nodes()}
    tank_ids = {n.id for n in network.get_tank_nodes()}
    dead_ends = []
    for lid, link in network.links.items():
        start_deg = G.degree(link.start_node)
        end_deg = G.degree(link.end_node)
        if start_deg == 1 and link.start_node not in source_ids and link.start_node not in tank_ids:
            dead_ends.append(lid)
        elif end_deg == 1 and link.end_node not in source_ids and link.end_node not in tank_ids:
            dead_ends.append(lid)
    return dead_ends


def check_pipe_removal_connectivity(network: WaterNetwork, link_id: str) -> Dict:
    if link_id not in network.links:
        return {"would_disconnect": False, "affected_nodes": set(), "message": ""}
    G = build_graph(network)
    link = network.links[link_id]
    if not G.has_edge(link.start_node, link.end_node):
        return {"would_disconnect": False, "affected_nodes": set(), "message": ""}
    G_copy = G.copy()
    G_copy.remove_edge(link.start_node, link.end_node)
    if nx.is_connected(G_copy):
        return {"would_disconnect": False, "affected_nodes": set(), "message": ""}
    source_ids = {n.id for n in network.get_source_nodes()}
    tank_ids = {n.id for n in network.get_tank_nodes()}
    fixed_nodes = source_ids | tank_ids
    components = list(nx.connected_components(G_copy))
    affected_nodes = set()
    for comp in components:
        if not (comp & fixed_nodes):
            affected_nodes |= comp
    would_disconnect = len(affected_nodes) > 0
    if would_disconnect:
        msg = (f"删除管段 {link_id} 将导致 {len(affected_nodes)} 个节点"
               f"与水源断开: {', '.join(sorted(affected_nodes))}")
    else:
        msg = ""
    return {
        "would_disconnect": would_disconnect,
        "affected_nodes": affected_nodes,
        "message": msg,
    }


def run_connectivity_analysis(network: WaterNetwork) -> Dict:
    G = build_graph(network)
    components = list(nx.connected_components(G))
    isolated_nodes = {nid for nid in network.nodes if G.degree(nid) == 0}
    source_nodes = {n.id for n in network.get_source_nodes()}
    tank_nodes = {n.id for n in network.get_tank_nodes()}
    fixed_nodes = source_nodes | tank_nodes
    isolated_subnets = []
    for comp in components:
        if not (comp & fixed_nodes) and len(comp) > 1:
            isolated_subnets.append(comp)
    dead_end_pipes = find_dead_end_pipes(network)
    source_component = None
    for comp in components:
        if comp & fixed_nodes:
            source_component = comp
            break
    return {
        "isolated_nodes": isolated_nodes,
        "isolated_subnets": isolated_subnets,
        "dead_end_pipes": dead_end_pipes,
        "components": components,
        "source_component": source_component,
        "n_components": len(components),
        "n_isolated_nodes": len(isolated_nodes),
        "n_isolated_subnets": len(isolated_subnets),
        "n_dead_end_pipes": len(dead_end_pipes),
    }
