import heapq
import json
from models import NetworkData


def _build_adjacency(network_data):
    nodes = network_data.get("nodes", {})
    links = network_data.get("links", {})

    adj = {nid: [] for nid in nodes}
    for lid, link in links.items():
        sn = link.get("start_node") or link.get("start")
        en = link.get("end_node") or link.get("end")
        length = link.get("length", 100)
        if sn in adj and en in adj:
            adj[sn].append((en, length, lid))
            adj[en].append((sn, length, lid))

    return adj, nodes


def dijkstra(adj, start, end):
    if start == end:
        return 0.0, [start]

    dist = {start: 0.0}
    prev = {start: None}
    pq = [(0.0, start)]
    visited = set()

    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if u == end:
            break
        for v, w, lid in adj.get(u, []):
            if v in visited:
                continue
            nd = d + w
            if v not in dist or nd < dist[v]:
                dist[v] = nd
                prev[v] = (u, lid)
                heapq.heappush(pq, (nd, v))

    if end not in prev and end != start:
        return float("inf"), []

    path = []
    node = end
    while node is not None:
        path.append(node)
        info = prev.get(node)
        if info is None:
            break
        node = info[0]

    path.reverse()
    return dist.get(end, float("inf")), path


def plan_route(start_node_id, target_node_ids, target_link_ids, network_id=None):
    network_rec = NetworkData.query.first()
    if not network_rec:
        return {"error": "未找到管网数据", "code": 404}

    network_data = {
        "nodes": json.loads(network_rec.nodes_json) if network_rec.nodes_json else {},
        "links": json.loads(network_rec.links_json) if network_rec.links_json else {},
    }

    adj, nodes_map = _build_adjacency(network_data)

    visit_nodes = set(target_node_ids or [])
    for lid in (target_link_ids or []):
        link_info = network_data["links"].get(lid)
        if link_info:
            sn = link_info.get("start_node") or link_info.get("start")
            en = link_info.get("end_node") or link_info.get("end")
            if sn:
                visit_nodes.add(sn)
            if en:
                visit_nodes.add(en)

    if start_node_id in visit_nodes:
        visit_nodes.discard(start_node_id)

    if not visit_nodes:
        return {
            "route": [start_node_id],
            "total_distance": 0.0,
            "total_estimated_minutes": 0,
        }

    remaining = set(visit_nodes)
    current = start_node_id
    route = [start_node_id]
    total_distance = 0.0

    while remaining:
        nearest_node = None
        nearest_dist = float("inf")
        nearest_path = []

        for target in remaining:
            d, p = dijkstra(adj, current, target)
            if d < nearest_dist:
                nearest_dist = d
                nearest_node = target
                nearest_path = p

        if nearest_node is None or nearest_dist == float("inf"):
            break

        if len(nearest_path) > 1:
            route.extend(nearest_path[1:])
        else:
            route.append(nearest_node)

        total_distance += nearest_dist
        remaining.remove(nearest_node)
        current = nearest_node

    walking_speed = 80
    total_estimated_minutes = int(total_distance / walking_speed) if walking_speed > 0 else 0

    return {
        "route": route,
        "total_distance": round(total_distance, 2),
        "total_estimated_minutes": total_estimated_minutes,
    }
