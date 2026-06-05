import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
import networkx as nx
from typing import Dict, List, Optional, Tuple
from models import WaterNetwork, Node, Link, NodeType, ElementType


def hazen_williams_head_loss(Q: float, L: float, C: float, D: float) -> float:
    if abs(Q) < 1e-12:
        return 0.0
    D_m = D / 1000.0
    sign = 1.0 if Q > 0 else -1.0
    hf = 10.67 * L * (abs(Q) ** 1.852) / ((C ** 1.852) * (D_m ** 4.87))
    return sign * hf


def hazen_williams_derivative(Q: float, L: float, C: float, D: float) -> float:
    if abs(Q) < 1e-12:
        Q = 1e-6
    D_m = D / 1000.0
    dhf_dQ = 10.67 * L * 1.852 * (abs(Q) ** 0.852) / ((C ** 1.852) * (D_m ** 4.87))
    return dhf_dQ


def pipe_resistance(L: float, C: float, D: float) -> float:
    D_m = D / 1000.0
    return 10.67 * L / ((C ** 1.852) * (D_m ** 4.87))


def compute_initial_flows(network: WaterNetwork) -> Dict[str, float]:
    flows = {}
    G = nx.Graph()
    for nid, node in network.nodes.items():
        G.add_node(nid)
    for lid, link in network.links.items():
        G.add_edge(link.start_node, link.end_node, link_id=lid)

    sources = [n.id for n in network.get_source_nodes()]
    tanks = [n.id for n in network.get_tank_nodes()]
    fixed_nodes = set(sources + tanks)

    total_demand = sum(n.demand for n in network.get_junction_nodes())
    if total_demand <= 0:
        for lid in network.links:
            flows[lid] = 0.001
        return flows

    for lid in network.links:
        flows[lid] = 0.0

    for jnode in network.get_junction_nodes():
        if jnode.demand <= 0:
            continue
        nearest_source = None
        min_dist = float('inf')
        for sid in fixed_nodes:
            try:
                dist = nx.shortest_path_length(G, jnode.id, sid)
                if dist < min_dist:
                    min_dist = dist
                    nearest_source = sid
            except nx.NetworkXNoPath:
                continue
        if nearest_source is None:
            continue
        try:
            path = nx.shortest_path(G, jnode.id, nearest_source)
        except nx.NetworkXNoPath:
            continue
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            edge_data = G.get_edge_data(u, v)
            lid = edge_data['link_id']
            link = network.links[lid]
            direction = 1.0
            if link.start_node == v and link.end_node == u:
                direction = -1.0
            flows[lid] += direction * jnode.demand / 3600.0

    for lid in network.links:
        if abs(flows[lid]) < 1e-10:
            flows[lid] = 0.0001
    return flows


def find_loops(network: WaterNetwork) -> List[List[Tuple[str, int]]]:
    G = nx.Graph()
    for lid, link in network.links.items():
        G.add_edge(link.start_node, link.end_node, link_id=lid)

    try:
        cycles = nx.cycle_basis(G)
    except Exception:
        return []

    loops = []
    link_map = {}
    for lid, link in network.links.items():
        key1 = (link.start_node, link.end_node)
        key2 = (link.end_node, link.start_node)
        link_map[key1] = (lid, 1)
        link_map[key2] = (lid, -1)

    for cycle in cycles:
        loop_pipes = []
        for i in range(len(cycle)):
            u = cycle[i]
            v = cycle[(i + 1) % len(cycle)]
            key = (u, v)
            if key in link_map:
                lid, direction = link_map[key]
                loop_pipes.append((lid, direction))
        if loop_pipes:
            loops.append(loop_pipes)
    return loops


def hardy_cross(network: WaterNetwork, max_iter: int = 50,
                tolerance: float = 0.01,
                relaxation: float = 1.0) -> Dict[str, float]:
    flows = compute_initial_flows(network)
    loops = find_loops(network)

    if not loops:
        return gradient_algorithm(network)

    for iteration in range(max_iter):
        max_imbalance = 0.0
        for loop in loops:
            sum_hf = 0.0
            sum_dhf = 0.0
            for lid, direction in loop:
                link = network.links[lid]
                Q = flows[lid] * direction
                if link.element_type == ElementType.PUMP:
                    pump_h = link.pump_a - link.pump_b * (Q ** 2) * (3600 ** 2)
                    sum_hf -= direction * pump_h
                    sum_dhf += link.pump_b * 2 * abs(Q) * (3600 ** 2)
                else:
                    C = link.get_roughness()
                    D = link.diameter
                    L = link.length
                    if link.element_type == ElementType.VALVE:
                        opening = link.setting / 100.0
                        if opening < 0.01:
                            continue
                        effective_L = L / (opening ** 2)
                    else:
                        effective_L = L
                    hf = hazen_williams_head_loss(Q, effective_L, C, D)
                    dhf = hazen_williams_derivative(Q, effective_L, C, D)
                    sum_hf += hf
                    sum_dhf += dhf

            if sum_dhf > 1e-12:
                delta_Q = -sum_hf / sum_dhf * relaxation
                for lid, direction in loop:
                    link = network.links[lid]
                    if link.element_type == ElementType.CHECK_VALVE:
                        new_flow = flows[lid] + delta_Q * direction
                        if new_flow < 0:
                            delta_Q = 0
                            break
                for lid, direction in loop:
                    flows[lid] += delta_Q * direction

            max_imbalance = max(max_imbalance, abs(sum_hf))

        if max_imbalance < tolerance:
            break

    for lid, flow in flows.items():
        network.links[lid].flow = flow
        D_m = network.links[lid].diameter / 1000.0
        area = np.pi * (D_m ** 2) / 4.0
        if area > 0:
            network.links[lid].velocity = abs(flow) / area
    return flows


def gradient_algorithm(network: WaterNetwork, max_iter: int = 100,
                       tolerance: float = 0.001,
                       relaxation: float = 1.0) -> Dict[str, float]:
    node_ids = sorted(network.nodes.keys())
    link_ids = sorted(network.links.keys())
    n_nodes = len(node_ids)
    n_links = len(link_ids)

    node_idx = {nid: i for i, nid in enumerate(node_ids)}

    fixed_head_nids = []
    variable_nids = []
    for nid in node_ids:
        node = network.nodes[nid]
        if node.node_type in (NodeType.SOURCE, NodeType.TANK):
            fixed_head_nids.append(nid)
        else:
            variable_nids.append(nid)

    var_idx = {nid: i for i, nid in enumerate(variable_nids)}
    n_var = len(variable_nids)

    if n_var == 0 or n_links == 0:
        return {}

    H = np.zeros(n_nodes)
    for nid in node_ids:
        node = network.nodes[nid]
        if node.node_type == NodeType.SOURCE:
            H[node_idx[nid]] = node.head if node.head else 50.0
        elif node.node_type == NodeType.TANK:
            H[node_idx[nid]] = node.elevation + node.init_level
        else:
            avg_fixed = 0.0
            for fnid in fixed_head_nids:
                fnode = network.nodes[fnid]
                fh = fnode.head if fnode.head else (fnode.elevation + fnode.init_level)
                avg_fixed += fh
            if fixed_head_nids:
                H[node_idx[nid]] = avg_fixed / len(fixed_head_nids) - 10.0
            else:
                H[node_idx[nid]] = 30.0

    flows = compute_initial_flows(network)
    Q = np.array([flows.get(lid, 0.0001) for lid in link_ids])

    n_fixed = len(fixed_head_nids)

    A12_rows = []
    A12_cols = []
    A12_vals = []
    A10_rows = []
    A10_cols = []
    A10_vals = []

    for j, lid in enumerate(link_ids):
        link = network.links[lid]
        sn = link.start_node
        en = link.end_node

        if sn in var_idx:
            A12_rows.append(j)
            A12_cols.append(var_idx[sn])
            A12_vals.append(-1.0)
        if en in var_idx:
            A12_rows.append(j)
            A12_cols.append(var_idx[en])
            A12_vals.append(1.0)

        if sn in fixed_head_nids:
            fi = fixed_head_nids.index(sn)
            A10_rows.append(j)
            A10_cols.append(fi)
            A10_vals.append(-1.0)
        if en in fixed_head_nids:
            fi = fixed_head_nids.index(en)
            A10_rows.append(j)
            A10_cols.append(fi)
            A10_vals.append(1.0)

    A12 = sparse.coo_matrix(
        (A12_vals, (A12_rows, A12_cols)),
        shape=(n_links, n_var)
    ).tocsc()

    if n_fixed > 0:
        A10 = sparse.coo_matrix(
            (A10_vals, (A10_rows, A10_cols)),
            shape=(n_links, n_fixed)
        ).tocsc()
    else:
        A10 = sparse.csc_matrix((n_links, 0))

    A21 = A12.T

    demand_vec = np.zeros(n_var)
    for nid in variable_nids:
        vi = var_idx[nid]
        demand_vec[vi] = network.nodes[nid].demand / 3600.0

    H_fixed = np.array([H[node_idx[nid]] for nid in fixed_head_nids])

    for iteration in range(max_iter):
        diag_G = np.zeros(n_links)
        hf_vec = np.zeros(n_links)

        for j, lid in enumerate(link_ids):
            link = network.links[lid]
            C = link.get_roughness()
            D = link.diameter
            L = link.length

            if link.element_type == ElementType.VALVE:
                opening = link.setting / 100.0
                if opening < 0.01:
                    diag_G[j] = 1e12
                    hf_vec[j] = Q[j] * 1e12
                    continue
                effective_L = L / (opening ** 2)
            else:
                effective_L = L

            R = pipe_resistance(effective_L, C, D)

            if link.element_type == ElementType.PUMP:
                Q_m3h = Q[j] * 3600.0
                pump_h = link.pump_a - link.pump_b * (Q_m3h ** 2)
                dpump_dQ = -2.0 * link.pump_b * Q_m3h * 3600.0
                diag_G[j] = max(abs(dpump_dQ), 1e-6)
                hf_vec[j] = -pump_h
            else:
                Q_abs = abs(Q[j])
                if Q_abs < 1e-10:
                    Q_abs = 1e-8

                hf = R * (Q_abs ** 1.852)
                G_j = R * 1.852 * (Q_abs ** 0.852)

                sign_Q = 1.0 if Q[j] >= 0 else -1.0
                hf_vec[j] = sign_Q * hf
                diag_G[j] = G_j

        H_var = np.array([H[node_idx[nid]] for nid in variable_nids])

        e1 = hf_vec + A12 @ H_var
        if n_fixed > 0:
            e1 += A10 @ H_fixed

        e2 = A21 @ Q - demand_vec

        G_inv = 1.0 / (diag_G + 1e-15)
        A11_inv = sparse.diags(G_inv, format='csc')

        A_norm = A21 @ A11_inv @ A12
        b_norm = e2 - A21 @ (A11_inv @ e1)

        try:
            delta_H = spsolve(A_norm, b_norm)
        except Exception:
            break

        if np.any(np.isnan(delta_H)) or np.any(np.isinf(delta_H)):
            break

        delta_Q = A11_inv @ (-e1 - A12 @ delta_H)

        Q = Q + relaxation * delta_Q
        for i, nid in enumerate(variable_nids):
            H[node_idx[nid]] += relaxation * delta_H[i]

        for j, lid in enumerate(link_ids):
            link = network.links[lid]
            if link.element_type == ElementType.CHECK_VALVE:
                if Q[j] < 0:
                    Q[j] = 0.0

        max_dH = np.max(np.abs(delta_H)) if len(delta_H) > 0 else 0
        max_dQ = np.max(np.abs(delta_Q)) if len(delta_Q) > 0 else 0

        if max_dH < tolerance and max_dQ < tolerance * 0.001:
            break

    result = {}
    for j, lid in enumerate(link_ids):
        link = network.links[lid]
        result[lid] = Q[j]
        link.flow = Q[j]
        D_m = link.diameter / 1000.0
        area = np.pi * (D_m ** 2) / 4.0
        if area > 0:
            link.velocity = abs(Q[j]) / area
        link.head_loss = hazen_williams_head_loss(
            Q[j], link.length, link.get_roughness(), link.diameter
        )

    for nid in node_ids:
        node = network.nodes[nid]
        ni = node_idx[nid]
        node.head = H[ni]
        node.pressure = H[ni] - node.elevation

    return result


def run_hydraulic(network: WaterNetwork, method: str = "gradient",
                  max_iter: int = 50, tolerance: float = 0.01) -> Dict[str, float]:
    errors = network.validate()
    if errors:
        raise ValueError("管网验证失败: " + "; ".join(errors))

    if method == "hardy_cross":
        return hardy_cross(network, max_iter, tolerance)
    else:
        return gradient_algorithm(network, max_iter, tolerance)


def run_hydraulic_with_relaxation(network: WaterNetwork,
                                  method: str = "gradient",
                                  max_iter: int = 50,
                                  tolerance: float = 0.01) -> Dict[str, float]:
    relaxation = 1.0
    result = run_hydraulic(network, method, max_iter, tolerance)

    converged = True
    for node in network.get_junction_nodes():
        if node.pressure is not None and node.pressure < -100:
            converged = False
            break
    for link in network.links.values():
        if link.flow is not None and abs(link.flow) > 10:
            converged = False
            break

    if not converged:
        for relaxation in [0.9, 0.8, 0.7, 0.6, 0.5]:
            if method == "hardy_cross":
                result = hardy_cross(network, max_iter, tolerance, relaxation)
            else:
                result = gradient_algorithm(network, max_iter, tolerance, relaxation)

            converged = True
            for node in network.get_junction_nodes():
                if node.pressure is not None and node.pressure < -100:
                    converged = False
                    break
            if converged:
                break

    return result
