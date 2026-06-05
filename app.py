import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import json
from copy import deepcopy
from models import (
    WaterNetwork, Node, Link, NodeType, ElementType, PipeMaterial,
    MATERIAL_ROUGHNESS
)
from hydraulic import run_hydraulic_with_relaxation
from demand import (
    run_extended_period, set_demand_patterns_batch, DEMAND_PATTERNS,
    apply_demand_at_hour
)
from leak_sim import run_leak_simulation
from leak_locate import run_leak_localization
from quality import run_water_quality
from verification import run_design_check
from export_utils import (
    export_node_pressure_csv, export_link_flow_csv, export_quality_csv,
    export_epanet_inp, generate_pdf_report
)
from connectivity import (
    run_connectivity_analysis, check_pipe_removal_connectivity,
    find_connected_components, find_isolated_nodes
)
from dma import (
    compute_dma_statistics, find_boundary_links, get_zone_nodes,
    compute_zone_polygon, DMA_ZONE_COLORS
)


CONNECTIVITY_COLORS = [
    "#4CAF50", "#2196F3", "#FF9800", "#9C27B0", "#F44336",
    "#00BCD4", "#795548", "#607D8B", "#CDDC39", "#E91E63",
]


def init_session_state():
    if "network" not in st.session_state:
        st.session_state.network = WaterNetwork()
    if "hydraulic_results" not in st.session_state:
        st.session_state.hydraulic_results = None
    if "quality_results" not in st.session_state:
        st.session_state.quality_results = None
    if "verification_results" not in st.session_state:
        st.session_state.verification_results = None
    if "leak_locate_results" not in st.session_state:
        st.session_state.leak_locate_results = None
    if "eps_results" not in st.session_state:
        st.session_state.eps_results = None
    if "selected_node" not in st.session_state:
        st.session_state.selected_node = None
    if "selected_link" not in st.session_state:
        st.session_state.selected_link = None
    if "animation_hour" not in st.session_state:
        st.session_state.animation_hour = 0
    if "drawing_mode" not in st.session_state:
        st.session_state.drawing_mode = None
    if "temp_start_node" not in st.session_state:
        st.session_state.temp_start_node = None
    if "undo_stack" not in st.session_state:
        st.session_state.undo_stack = []
    if "redo_stack" not in st.session_state:
        st.session_state.redo_stack = []
    if "scenarios" not in st.session_state:
        st.session_state.scenarios = {}
    if "dma_zone_defs" not in st.session_state:
        st.session_state.dma_zone_defs = {}
    if "connectivity_result" not in st.session_state:
        st.session_state.connectivity_result = None


def save_undo_state():
    if "undo_stack" not in st.session_state:
        st.session_state.undo_stack = []
    if "redo_stack" not in st.session_state:
        st.session_state.redo_stack = []
    state = deepcopy(st.session_state.network)
    st.session_state.undo_stack.append(state)
    if len(st.session_state.undo_stack) > 10:
        st.session_state.undo_stack.pop(0)
    st.session_state.redo_stack.clear()


def do_undo():
    if not st.session_state.undo_stack:
        st.warning("没有可撤销的操作")
        return
    current = deepcopy(st.session_state.network)
    st.session_state.redo_stack.append(current)
    prev = st.session_state.undo_stack.pop()
    st.session_state.network = prev
    st.session_state.hydraulic_results = None
    st.rerun()


def do_redo():
    if not st.session_state.redo_stack:
        st.warning("没有可恢复的操作")
        return
    current = deepcopy(st.session_state.network)
    st.session_state.undo_stack.append(current)
    next_state = st.session_state.redo_stack.pop()
    st.session_state.network = next_state
    st.session_state.hydraulic_results = None
    st.rerun()


def create_demo_network():
    net = WaterNetwork()
    net.add_node(Node(id="S1", node_type=NodeType.SOURCE, x=100, y=300,
                      elevation=50, head=80))
    net.add_node(Node(id="J1", node_type=NodeType.JUNCTION, x=300, y=300,
                      elevation=45, demand=20))
    net.add_node(Node(id="J2", node_type=NodeType.JUNCTION, x=500, y=200,
                      elevation=42, demand=15))
    net.add_node(Node(id="J3", node_type=NodeType.JUNCTION, x=500, y=400,
                      elevation=43, demand=25))
    net.add_node(Node(id="J4", node_type=NodeType.JUNCTION, x=700, y=300,
                      elevation=40, demand=30, demand_group="居民区",
                      daily_demand=30))
    net.add_node(Node(id="J5", node_type=NodeType.JUNCTION, x=900, y=200,
                      elevation=38, demand=10, demand_group="商业区",
                      daily_demand=10))
    net.add_node(Node(id="J6", node_type=NodeType.JUNCTION, x=900, y=400,
                      elevation=39, demand=18, demand_group="居民区",
                      daily_demand=18))

    net.add_link(Link(id="P1", element_type=ElementType.PIPE,
                      start_node="S1", end_node="J1",
                      diameter=500, length=300, material=PipeMaterial.DUCTILE_IRON))
    net.add_link(Link(id="P2", element_type=ElementType.PIPE,
                      start_node="J1", end_node="J2",
                      diameter=400, length=250, material=PipeMaterial.DUCTILE_IRON))
    net.add_link(Link(id="P3", element_type=ElementType.PIPE,
                      start_node="J1", end_node="J3",
                      diameter=400, length=250, material=PipeMaterial.DUCTILE_IRON))
    net.add_link(Link(id="P4", element_type=ElementType.PIPE,
                      start_node="J2", end_node="J4",
                      diameter=300, length=300, material=PipeMaterial.DUCTILE_IRON))
    net.add_link(Link(id="P5", element_type=ElementType.PIPE,
                      start_node="J3", end_node="J4",
                      diameter=300, length=300, material=PipeMaterial.DUCTILE_IRON))
    net.add_link(Link(id="P6", element_type=ElementType.PIPE,
                      start_node="J4", end_node="J5",
                      diameter=200, length=250, material=PipeMaterial.PE))
    net.add_link(Link(id="P7", element_type=ElementType.PIPE,
                      start_node="J4", end_node="J6",
                      diameter=250, length=250, material=PipeMaterial.PE))
    net.add_link(Link(id="P8", element_type=ElementType.PIPE,
                      start_node="J5", end_node="J6",
                      diameter=150, length=300, material=PipeMaterial.PE))
    return net


def draw_network_plotly(network, color_by="none", highlight_leaks=None,
                        eps_hour_data=None, leak_locate_result=None,
                        connectivity_result=None, show_dma_zones=False,
                        show_dma_boundary=False):
    fig = go.Figure()

    if show_dma_zones and st.session_state.get("dma_zone_defs"):
        zone_defs = st.session_state.dma_zone_defs
        zone_nodes_map = get_zone_nodes(network)
        for zone_name, zone_info in zone_defs.items():
            if zone_name not in zone_nodes_map:
                continue
            zone_nids = zone_nodes_map[zone_name]
            coords = []
            for nid in zone_nids:
                node = network.nodes.get(nid)
                if node:
                    coords.append((node.x, node.y))
            if not coords:
                continue
            shape = compute_zone_polygon(coords, padding=50)
            if shape:
                shape["fillcolor"] = zone_info["color"]
                shape["opacity"] = 0.2
                shape["line"] = dict(width=1, color=zone_info["color"])
                fig.add_shape(shape)

    node_x = []
    node_y = []
    node_text = []
    node_colors = []
    node_sizes = []

    min_pressure = float('inf')
    max_pressure = float('-inf')
    for n in network.nodes.values():
        p = n.pressure if n.pressure is not None else 0
        if p < min_pressure:
            min_pressure = p
        if p > max_pressure:
            max_pressure = p

    min_flow = float('inf')
    max_flow = float('-inf')
    for l in network.links.values():
        f = abs(l.flow) if l.flow is not None else 0
        if f < min_flow:
            min_flow = f
        if f > max_flow:
            max_flow = f

    isolated_set = set()
    component_map = {}
    if connectivity_result:
        isolated_set = connectivity_result.get("isolated_nodes", set())
        components = connectivity_result.get("components", [])
        for i, comp in enumerate(components):
            for nid in comp:
                component_map[nid] = i

    boundary_link_set = set()
    if show_dma_boundary:
        boundary_link_set = set(find_boundary_links(network))

    for nid, node in network.nodes.items():
        x = node.x
        y = node.y
        if eps_hour_data and "node_pressures" in eps_hour_data:
            pressure = eps_hour_data["node_pressures"].get(nid, node.pressure or 0)
        else:
            pressure = node.pressure if node.pressure is not None else 0

        node_x.append(x)
        node_y.append(y)

        if node.node_type == NodeType.SOURCE:
            base_size = 18
        elif node.node_type == NodeType.TANK:
            base_size = 16
        else:
            base_size = max(8, min(20, 8 + node.demand / 5))

        if nid in isolated_set:
            node_colors.append("#AAAAAA")
        elif connectivity_result and color_by == "connectivity":
            comp_idx = component_map.get(nid, 0)
            node_colors.append(CONNECTIVITY_COLORS[comp_idx % len(CONNECTIVITY_COLORS)])
        elif color_by == "pressure" and max_pressure > min_pressure:
            norm_p = (pressure - min_pressure) / (max_pressure - min_pressure + 1e-10)
            node_colors.append(norm_p)
        elif color_by == "pressure":
            node_colors.append(0.5)
        else:
            node_colors.append(0.5)

        node_sizes.append(base_size)

        info = f"节点: {nid}<br>类型: {node.node_type.value}"
        info += f"<br>标高: {node.elevation:.1f}m"
        if node.pressure is not None:
            info += f"<br>压力: {pressure:.2f}m"
        if node.head is not None:
            info += f"<br>水头: {node.head:.2f}m"
        if node.node_type == NodeType.JUNCTION:
            info += f"<br>需水量: {node.demand:.2f}m³/h"
        if node.dma_zone:
            info += f"<br>分区: {node.dma_zone}"
        node_text.append(info)

    highlight_links = set()
    leak_positions = []
    if leak_locate_result and leak_locate_result.get("leaks"):
        for leak in leak_locate_result["leaks"]:
            highlight_links.add(leak["link_id"])
            link = network.links.get(leak["link_id"])
            if link:
                sn = network.nodes.get(link.start_node)
                en = network.nodes.get(link.end_node)
                if sn and en:
                    pos = leak["position"]
                    lx = sn.x * (1 - pos) + en.x * pos
                    ly = sn.y * (1 - pos) + en.y * pos
                    leak_positions.append((lx, ly, leak["link_id"]))

    if highlight_leaks:
        for lid in highlight_leaks:
            highlight_links.add(lid)

    for lid, link in network.links.items():
        sn = network.nodes.get(link.start_node)
        en = network.nodes.get(link.end_node)
        if sn is None or en is None:
            continue

        if eps_hour_data and "link_flows" in eps_hour_data:
            flow = eps_hour_data["link_flows"].get(lid, link.flow or 0)
        else:
            flow = link.flow if link.flow is not None else 0

        if color_by == "flow" and max_flow > min_flow:
            norm_f = (abs(flow) - min_flow) / (max_flow - min_flow + 1e-10)
        else:
            norm_f = 0.5

        line_width = max(2, min(10, link.diameter / 50))
        dash_style = None

        if lid in highlight_links:
            line_color = "red"
            line_width = line_width * 2
        elif lid in boundary_link_set:
            line_color = "#FF5722"
            dash_style = "dash"
            line_width = max(3, line_width)
        elif color_by == "flow":
            line_color = px.colors.sample_colorscale(
                "RdYlGn_r", [norm_f]
            )[0]
        elif color_by == "velocity":
            vel = link.velocity if link.velocity is not None else 0
            norm_v = min(vel / 3.0, 1.0)
            line_color = px.colors.sample_colorscale(
                "RdYlGn_r", [norm_v]
            )[0]
        else:
            line_color = "#667788"

        info = f"管段: {lid}<br>类型: {link.element_type.value}"
        info += f"<br>管径: {link.diameter:.0f}mm"
        info += f"<br>长度: {link.length:.0f}m"
        info += f"<br>粗糙系数: {link.get_roughness()}"
        if link.flow is not None:
            info += f"<br>流量: {abs(flow)*1000:.2f}L/s"
        if link.velocity is not None:
            info += f"<br>流速: {link.velocity:.3f}m/s"
        if link.head_loss is not None:
            info += f"<br>水头损失: {link.head_loss:.3f}m"
        if lid in boundary_link_set:
            info += "<br>⚡ 分区边界管段"

        line_dict = dict(color=line_color, width=line_width)
        if dash_style:
            line_dict["dash"] = dash_style

        fig.add_trace(go.Scatter(
            x=[sn.x, en.x],
            y=[sn.y, en.y],
            mode="lines",
            line=line_dict,
            hoverinfo="text",
            hovertext=info,
            name=lid,
            showlegend=False,
        ))

    for lx, ly, leak_lid in leak_positions:
        fig.add_trace(go.Scatter(
            x=[lx], y=[ly],
            mode="markers",
            marker=dict(symbol="x", size=15, color="red", line_width=3),
            hovertext=f"漏损点: {leak_lid}",
            showlegend=False,
        ))

    node_color_vals = None
    colorscale = None
    use_numeric_color = False

    if color_by == "connectivity" and connectivity_result:
        pass
    elif color_by == "pressure" and max_pressure > min_pressure:
        node_color_vals = node_colors
        colorscale = "RdYlBu"
        use_numeric_color = True

    marker_dict = dict(size=node_sizes, line=dict(width=1, color="white"))
    if use_numeric_color and node_color_vals:
        marker_dict["color"] = node_color_vals
        marker_dict["colorscale"] = colorscale
        marker_dict["cmin"] = 0
        marker_dict["cmax"] = 1
    else:
        marker_dict["color"] = node_colors

    fig.add_trace(go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        marker=marker_dict,
        text=[nid for nid in network.nodes.keys()],
        textposition="top center",
        textfont=dict(size=9),
        hoverinfo="text",
        hovertext=node_text,
        showlegend=False,
    ))

    fig.update_layout(
        plot_bgcolor="white",
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                   scaleanchor="x", scaleratio=1),
        margin=dict(l=20, r=20, t=30, b=20),
        height=600,
    )

    if color_by == "connectivity" and connectivity_result:
        fig.update_layout(
            title=dict(text=f"管网连通性分析 ({connectivity_result['n_components']}个连通分量)",
                       font=dict(size=14))
        )
    elif color_by == "pressure" and max_pressure > min_pressure:
        fig.update_layout(
            title=dict(text=f"管网拓扑 (节点按水压着色: {min_pressure:.1f}m ~ {max_pressure:.1f}m)",
                       font=dict(size=14))
        )
    elif color_by == "flow":
        fig.update_layout(
            title=dict(text="管网拓扑 (管段按流量着色)", font=dict(size=14))
        )
    elif color_by == "velocity":
        fig.update_layout(
            title=dict(text="管网拓扑 (管段按流速着色)", font=dict(size=14))
        )
    else:
        fig.update_layout(
            title=dict(text="管网拓扑图", font=dict(size=14))
        )

    return fig


def page_network_definition():
    st.header("📐 管网拓扑定义")

    network = st.session_state.network

    col_undo, col_redo = st.columns(2)
    with col_undo:
        if st.button("↩️ 撤销", disabled=not st.session_state.undo_stack):
            do_undo()
    with col_redo:
        if st.button("↪️ 重做", disabled=not st.session_state.redo_stack):
            do_redo()

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📂 加载示例管网"):
            save_undo_state()
            st.session_state.network = create_demo_network()
            st.session_state.hydraulic_results = None
            st.rerun()
    with col2:
        uploaded_nodes = st.file_uploader("导入节点CSV", type=["csv"], key="nodes_csv")
    with col3:
        uploaded_links = st.file_uploader("导入管段CSV", type=["csv"], key="links_csv")

    if uploaded_nodes and uploaded_links:
        if st.button("📥 导入管网数据"):
            try:
                nodes_csv = uploaded_nodes.read().decode("utf-8")
                links_csv = uploaded_links.read().decode("utf-8")
                new_net = WaterNetwork()
                new_net.from_csv(nodes_csv, links_csv)
                errors = new_net.validate()
                if errors:
                    st.error("导入验证失败: " + "; ".join(errors))
                else:
                    save_undo_state()
                    st.session_state.network = new_net
                    st.session_state.hydraulic_results = None
                    st.success(f"成功导入 {len(new_net.nodes)} 个节点, {len(new_net.links)} 条管段")
                    st.rerun()
            except Exception as e:
                st.error(f"导入失败: {str(e)}")

    st.subheader("节点拖拽移动")
    with st.expander("✥ 拖拽节点", expanded=False):
        node_ids = list(network.nodes.keys())
        if node_ids:
            move_node = st.selectbox("选择节点", node_ids, key="move_node_sel")
            if move_node and move_node in network.nodes:
                node = network.nodes[move_node]
                col1, col2 = st.columns(2)
                with col1:
                    new_x = st.number_input("X坐标", value=float(node.x),
                                            step=10.0, key="move_x")
                with col2:
                    new_y = st.number_input("Y坐标", value=float(node.y),
                                            step=10.0, key="move_y")
                if st.button("✅ 移动节点", key="btn_move_node"):
                    save_undo_state()
                    node.x = new_x
                    node.y = new_y
                    st.session_state.hydraulic_results = None
                    st.success(f"节点 {move_node} 已移动到 ({new_x}, {new_y})")
                    st.rerun()
        else:
            st.info("暂无节点可移动")

    st.subheader("管段分割")
    with st.expander("✂️ 分割管段", expanded=False):
        link_ids = list(network.links.keys())
        if link_ids:
            split_link_id = st.selectbox("选择要分割的管段", link_ids, key="split_link_sel")
            if split_link_id and split_link_id in network.links:
                link = network.links[split_link_id]
                sn = network.nodes.get(link.start_node)
                en = network.nodes.get(link.end_node)
                if sn and en:
                    mid_x = (sn.x + en.x) / 2
                    mid_y = (sn.y + en.y) / 2
                    st.info(f"管段 {split_link_id}: {link.start_node} → {link.end_node}, "
                            f"长度={link.length:.0f}m, 管径={link.diameter:.0f}mm")
                    st.info(f"将在中点 ({mid_x:.1f}, {mid_y:.1f}) 插入新节点")
                    if st.button("✂️ 确认分割", key="btn_split"):
                        save_undo_state()
                        new_node_id = f"SPLIT_{split_link_id}"
                        idx = 1
                        while new_node_id in network.nodes:
                            new_node_id = f"SPLIT_{split_link_id}_{idx}"
                            idx += 1
                        new_node = Node(
                            id=new_node_id,
                            node_type=NodeType.JUNCTION,
                            x=mid_x, y=mid_y,
                            elevation=(sn.elevation + en.elevation) / 2,
                            demand=0.0,
                        )
                        network.add_node(new_node)

                        new_link_id_1 = f"{split_link_id}a"
                        new_link_id_2 = f"{split_link_id}b"
                        idx2 = 1
                        while new_link_id_1 in network.links:
                            new_link_id_1 = f"{split_link_id}a_{idx2}"
                            new_link_id_2 = f"{split_link_id}b_{idx2}"
                            idx2 += 1

                        half_length = link.length / 2
                        new_link_1 = Link(
                            id=new_link_id_1,
                            element_type=link.element_type,
                            start_node=link.start_node,
                            end_node=new_node_id,
                            diameter=link.diameter,
                            length=half_length,
                            roughness=link.roughness,
                            material=link.material,
                            setting=link.setting,
                        )
                        new_link_2 = Link(
                            id=new_link_id_2,
                            element_type=link.element_type,
                            start_node=new_node_id,
                            end_node=link.end_node,
                            diameter=link.diameter,
                            length=half_length,
                            roughness=link.roughness,
                            material=link.material,
                            setting=link.setting,
                        )
                        del network.links[split_link_id]
                        network.add_link(new_link_1)
                        network.add_link(new_link_2)
                        st.session_state.hydraulic_results = None
                        st.success(f"管段 {split_link_id} 已分割为新节点 {new_node_id} 和管段 "
                                   f"{new_link_id_1}, {new_link_id_2}")
                        st.rerun()
        else:
            st.info("暂无管段可分割")

    st.subheader("添加节点")
    with st.expander("➕ 添加节点", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            new_node_id = st.text_input("节点编号", value=f"N{len(network.nodes)+1}")
            new_node_type = st.selectbox("节点类型", ["junction", "source", "tank"],
                                         format_func=lambda x: {"junction": "用户节点",
                                                                 "source": "水源节点",
                                                                 "tank": "水池节点"}.get(x, x))
            new_elevation = st.number_input("地面标高(m)", value=0.0, step=0.5)
            new_x = st.number_input("X坐标", value=float(100 + len(network.nodes) * 50))
            new_y = st.number_input("Y坐标", value=300.0)
        with col2:
            new_demand = st.number_input("需水量(m³/h)", value=0.0, step=1.0,
                                         disabled=(new_node_type != "junction"))
            new_head = st.number_input("设定水头(m)", value=80.0,
                                       disabled=(new_node_type != "source"))
            new_demand_group = st.selectbox("需水分组", ["", "居民区", "商业区", "工业区"],
                                            disabled=(new_node_type != "junction"))
            new_building_type = st.selectbox("建筑类型", ["multi", "high"],
                                             format_func=lambda x: {"multi": "多层建筑(28m)",
                                                                    "high": "高层建筑(35m)"}.get(x, x),
                                             disabled=(new_node_type != "junction"))

        if st.button("确认添加节点"):
            if new_node_id in network.nodes:
                st.error(f"节点编号 {new_node_id} 已存在")
            else:
                save_undo_state()
                ntype = NodeType(new_node_type)
                node = Node(
                    id=new_node_id, node_type=ntype,
                    x=new_x, y=new_y, elevation=new_elevation,
                    demand=new_demand, head=new_head if ntype == NodeType.SOURCE else None,
                    demand_group=new_demand_group,
                    building_type=new_building_type,
                )
                network.add_node(node)
                st.session_state.hydraulic_results = None
                st.success(f"已添加节点 {new_node_id}")
                st.rerun()

    st.subheader("添加管段")
    with st.expander("➕ 添加管段", expanded=False):
        node_ids = list(network.nodes.keys())
        if len(node_ids) >= 2:
            col1, col2 = st.columns(2)
            with col1:
                new_link_id = st.text_input("管段编号", value=f"P{len(network.links)+1}")
                new_link_type = st.selectbox("管段类型",
                                             ["pipe", "valve", "pump", "check_valve"],
                                             format_func=lambda x: {"pipe": "普通管段",
                                                                    "valve": "阀门",
                                                                    "pump": "水泵",
                                                                    "check_valve": "止回阀"}.get(x, x))
                start_node = st.selectbox("起始节点", node_ids)
                end_node = st.selectbox("终止节点", node_ids)
            with col2:
                new_diameter = st.number_input("管径(mm)", value=300, step=50, min_value=50, max_value=2000)
                new_length = st.number_input("长度(m)", value=100, step=10, min_value=1)
                new_material = st.selectbox("管材", ["铸铁", "球墨铸铁", "PE", "钢管"])
                new_roughness = st.number_input("粗糙系数C (0=使用默认)", value=0,
                                                min_value=0, max_value=150)
                new_setting = st.number_input("阀门开度(%)/水泵参数", value=100,
                                             min_value=0, max_value=100)

            if st.button("确认添加管段"):
                if start_node == end_node:
                    st.error("起始节点和终止节点不能相同")
                elif new_link_id in network.links:
                    st.error(f"管段编号 {new_link_id} 已存在")
                else:
                    save_undo_state()
                    mat_map = {"铸铁": PipeMaterial.CAST_IRON,
                               "球墨铸铁": PipeMaterial.DUCTILE_IRON,
                               "PE": PipeMaterial.PE,
                               "钢管": PipeMaterial.STEEL}
                    link = Link(
                        id=new_link_id,
                        element_type=ElementType(new_link_type),
                        start_node=start_node, end_node=end_node,
                        diameter=new_diameter, length=new_length,
                        roughness=new_roughness,
                        material=mat_map[new_material],
                        setting=new_setting,
                    )
                    network.add_link(link)
                    st.session_state.hydraulic_results = None
                    st.success(f"已添加管段 {new_link_id}")
                    st.rerun()
        else:
            st.info("请先添加至少2个节点")

    st.subheader("管网可视化")
    color_by = st.selectbox("着色方式", ["none", "pressure", "flow", "velocity"],
                            format_func=lambda x: {"none": "默认",
                                                   "pressure": "按水压",
                                                   "flow": "按流量",
                                                   "velocity": "按流速"}.get(x, x))
    fig = draw_network_plotly(network, color_by=color_by)
    st.plotly_chart(fig, width="stretch")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("节点列表")
        if network.nodes:
            node_data = []
            for nid, node in network.nodes.items():
                row = {
                    "编号": nid, "类型": node.node_type.value,
                    "标高(m)": node.elevation, "需水量(m³/h)": node.demand,
                    "水头(m)": f"{node.head:.2f}" if node.head else "-",
                    "压力(m)": f"{node.pressure:.2f}" if node.pressure else "-",
                }
                node_data.append(row)
            st.dataframe(pd.DataFrame(node_data), width="stretch")

            delete_node = st.selectbox("删除节点", [""] + list(network.nodes.keys()),
                                       key="del_node")
            if delete_node and st.button("🗑️ 删除选中节点"):
                save_undo_state()
                network.remove_node(delete_node)
                st.session_state.hydraulic_results = None
                st.rerun()
        else:
            st.info("暂无节点")

    with col2:
        st.subheader("管段列表")
        if network.links:
            link_data = []
            for lid, link in network.links.items():
                row = {
                    "编号": lid, "类型": link.element_type.value,
                    "起点": link.start_node, "终点": link.end_node,
                    "管径(mm)": link.diameter, "长度(m)": link.length,
                    "粗糙系数": link.get_roughness(),
                    "流量(L/s)": f"{abs(link.flow)*1000:.2f}" if link.flow else "-",
                    "流速(m/s)": f"{link.velocity:.3f}" if link.velocity else "-",
                }
                link_data.append(row)
            st.dataframe(pd.DataFrame(link_data), width="stretch")

            delete_link = st.selectbox("删除管段", [""] + list(network.links.keys()),
                                       key="del_link")
            if delete_link:
                conn_check = check_pipe_removal_connectivity(network, delete_link)
                if conn_check["would_disconnect"]:
                    st.warning(f"⚠️ {conn_check['message']}")
                if st.button("🗑️ 删除选中管段"):
                    save_undo_state()
                    network.remove_link(delete_link)
                    st.session_state.hydraulic_results = None
                    st.rerun()
        else:
            st.info("暂无管段")


def page_hydraulic():
    st.header("💧 水力计算")

    network = st.session_state.network

    if not network.nodes:
        st.warning("请先定义管网拓扑")
        return

    st.subheader("计算参数")
    col1, col2 = st.columns(2)
    with col1:
        method = st.selectbox("求解方法", ["gradient", "hardy_cross"],
                              format_func=lambda x: {"gradient": "梯度法(Global Gradient)",
                                                     "hardy_cross": "Hardy-Cross迭代法"}.get(x, x))
    with col2:
        max_iter = st.number_input("最大迭代次数", value=50, min_value=10, max_value=200)

    if st.button("▶️ 运行水力计算", type="primary"):
        with st.spinner("正在计算..."):
            try:
                result = run_hydraulic_with_relaxation(network, method, max_iter)
                st.session_state.hydraulic_results = result
                st.success("水力计算完成！")
            except Exception as e:
                st.error(f"计算失败: {str(e)}")

    if st.session_state.hydraulic_results is not None:
        st.subheader("计算结果")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**节点水压**")
            node_data = []
            for nid, node in network.nodes.items():
                node_data.append({
                    "编号": nid, "类型": node.node_type.value,
                    "标高(m)": node.elevation,
                    "水头(m)": f"{node.head:.2f}" if node.head else "-",
                    "压力(m)": f"{node.pressure:.2f}" if node.pressure else "-",
                    "自由水压(m)": f"{node.pressure:.2f}" if node.pressure and node.node_type == NodeType.JUNCTION else "-",
                })
            st.dataframe(pd.DataFrame(node_data), width="stretch")

        with col2:
            st.markdown("**管段流量**")
            link_data = []
            for lid, link in network.links.items():
                flow_lps = abs(link.flow) * 1000 if link.flow else 0
                link_data.append({
                    "编号": lid, "起点": link.start_node, "终点": link.end_node,
                    "管径(mm)": link.diameter,
                    "流量(L/s)": f"{flow_lps:.2f}",
                    "流速(m/s)": f"{link.velocity:.3f}" if link.velocity else "-",
                    "水头损失(m)": f"{link.head_loss:.3f}" if link.head_loss else "-",
                })
            st.dataframe(pd.DataFrame(link_data), width="stretch")

        st.subheader("管网着色图")
        color_by = st.selectbox("结果着色", ["pressure", "flow", "velocity"],
                                format_func=lambda x: {"pressure": "节点按水压",
                                                       "flow": "管段按流量",
                                                       "velocity": "管段按流速"}.get(x, x),
                                key="hydraulic_color")
        fig = draw_network_plotly(network, color_by=color_by)
        st.plotly_chart(fig, width="stretch")

        pressures = [n.pressure for n in network.nodes.values()
                     if n.pressure is not None and n.node_type == NodeType.JUNCTION]
        if pressures:
            st.subheader("水压统计")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("最小压力(m)", f"{min(pressures):.2f}")
            col2.metric("最大压力(m)", f"{max(pressures):.2f}")
            col3.metric("平均压力(m)", f"{np.mean(pressures):.2f}")
            col4.metric("低于28m节点数",
                        str(sum(1 for p in pressures if p < 28)))


def page_demand():
    st.header("📊 需水量分配与延时模拟")

    network = st.session_state.network
    if not network.nodes:
        st.warning("请先定义管网拓扑")
        return

    st.subheader("需水模式设定")
    st.markdown("为不同用户分组设置24小时变化系数曲线")

    groups = ["居民区", "商业区", "工业区"]
    for group in groups:
        with st.expander(f"📋 {group}变化模式"):
            default_pattern = DEMAND_PATTERNS[group]
            cols = st.columns(6)
            pattern = []
            for h in range(24):
                with cols[h % 6]:
                    val = st.number_input(
                        f"{h}:00",
                        value=float(default_pattern[h]),
                        min_value=0.0, max_value=3.0, step=0.1,
                        key=f"pattern_{group}_{h}"
                    )
                    pattern.append(val)
            if st.button(f"应用{group}模式", key=f"apply_{group}"):
                set_demand_patterns_batch(network, {group: pattern})
                st.success(f"已为 {group} 设置变化模式")

    if st.button("应用所有默认模式"):
        set_demand_patterns_batch(network)
        st.success("已应用所有默认需水模式")

    st.subheader("延时模拟")
    col1, col2 = st.columns(2)
    with col1:
        hours = st.number_input("模拟时长(h)", value=24, min_value=1, max_value=168)
    with col2:
        eps_method = st.selectbox("求解方法", ["gradient", "hardy_cross"],
                                  format_func=lambda x: {"gradient": "梯度法",
                                                         "hardy_cross": "Hardy-Cross法"}.get(x, x),
                                  key="eps_method")

    if st.button("▶️ 运行延时模拟", type="primary"):
        with st.spinner("正在运行延时模拟..."):
            try:
                results = run_extended_period(network, eps_method, hours)
                st.session_state.eps_results = results
                st.success(f"延时模拟完成，共 {hours} 个时段")
            except Exception as e:
                st.error(f"模拟失败: {str(e)}")

    if st.session_state.eps_results:
        results = st.session_state.eps_results
        st.subheader("延时模拟结果")

        junction_nodes = [nid for nid, n in network.nodes.items()
                          if n.node_type == NodeType.JUNCTION]

        selected_nodes = st.multiselect("选择节点查看压力变化",
                                        junction_nodes,
                                        default=junction_nodes[:5] if junction_nodes else [])

        if selected_nodes:
            fig = go.Figure()
            for nid in selected_nodes:
                pressures = []
                for h in range(min(hours, len(results))):
                    if "node_pressures" in results[h]:
                        pressures.append(results[h]["node_pressures"].get(nid, 0))
                    else:
                        pressures.append(None)
                fig.add_trace(go.Scatter(
                    x=list(range(len(pressures))),
                    y=pressures,
                    mode="lines+markers",
                    name=nid,
                ))
            fig.update_layout(
                title="节点水压时间序列",
                xaxis_title="时间(h)", yaxis_title="水压(m)",
                height=400,
            )
            st.plotly_chart(fig, width="stretch")

        selected_links = st.multiselect("选择管段查看流量变化",
                                        list(network.links.keys()),
                                        default=list(network.links.keys())[:5] if network.links else [])

        if selected_links:
            fig2 = go.Figure()
            for lid in selected_links:
                flows = []
                for h in range(min(hours, len(results))):
                    if "link_flows" in results[h]:
                        flows.append(abs(results[h]["link_flows"].get(lid, 0)) * 1000)
                    else:
                        flows.append(None)
                fig2.add_trace(go.Scatter(
                    x=list(range(len(flows))),
                    y=flows,
                    mode="lines+markers",
                    name=lid,
                ))
            fig2.update_layout(
                title="管段流量时间序列",
                xaxis_title="时间(h)", yaxis_title="流量(L/s)",
                height=400,
            )
            st.plotly_chart(fig2, width="stretch")

        st.subheader("时间序列动画")
        anim_hour = st.slider("选择时刻", 0, min(hours, len(results)) - 1, 0, key="anim_hour")
        if anim_hour in results and "node_pressures" in results[anim_hour]:
            fig3 = draw_network_plotly(network, color_by="pressure",
                                       eps_hour_data=results[anim_hour])
            st.plotly_chart(fig3, width="stretch")


def page_leak_simulation():
    st.header("🔍 漏损模拟")

    network = st.session_state.network
    if not network.nodes:
        st.warning("请先定义管网拓扑")
        return

    st.subheader("设置漏损点")
    link_ids = list(network.links.keys())
    if not link_ids:
        st.info("暂无管段可设置漏损")
        return

    with st.expander("➕ 添加漏损点"):
        leak_link = st.selectbox("选择管段", link_ids, key="leak_link")
        col1, col2, col3 = st.columns(3)
        with col1:
            leak_position = st.slider("漏损位置(管段上的相对位置)", 0.0, 1.0, 0.5, 0.01)
        with col2:
            leak_area = st.number_input("漏损面积(mm²)", value=5.0, min_value=0.1, step=0.5)
        with col3:
            leak_pipe_type = st.selectbox("管材类型", ["metal", "plastic"],
                                          format_func=lambda x: {"metal": "金属管",
                                                                 "plastic": "塑料管"}.get(x, x))

        if st.button("添加漏损"):
            network.add_leak(leak_link, leak_position, leak_area, leak_pipe_type)
            st.success(f"已在管段 {leak_link} 位置 {leak_position:.2f} 添加漏损")
            st.rerun()

    if network.leaks:
        st.markdown("**当前漏损点:**")
        leak_data = []
        for lid, info in network.leaks.items():
            leak_data.append({
                "管段": lid,
                "位置": f"{info['position']:.2f}",
                "面积(mm²)": info["area_mm2"],
                "管材": info["pipe_type"],
                "漏损流量(m³/h)": f"{info['flow']*3600:.3f}" if info.get("flow") else "-",
            })
        st.dataframe(pd.DataFrame(leak_data), width="stretch")

        remove_leak_lid = st.selectbox("删除漏损", [""] + list(network.leaks.keys()),
                                       key="remove_leak")
        if remove_leak_lid and st.button("🗑️ 删除漏损"):
            network.remove_leak(remove_leak_lid)
            st.rerun()

        if st.button("清除所有漏损"):
            network.clear_leaks()
            st.rerun()

    st.subheader("运行漏损模拟")
    leak_method = st.selectbox("求解方法", ["gradient", "hardy_cross"],
                               key="leak_method",
                               format_func=lambda x: {"gradient": "梯度法",
                                                      "hardy_cross": "Hardy-Cross法"}.get(x, x))

    if st.button("▶️ 运行漏损模拟", type="primary"):
        if not network.leaks:
            st.warning("请先设置漏损点")
        else:
            with st.spinner("正在模拟漏损..."):
                try:
                    result = run_leak_simulation(network, leak_method)
                    st.success("漏损模拟完成！")

                    total_leak = sum(info["flow"] * 3600 for info in network.leaks.values())
                    total_demand = sum(n.demand for n in network.get_junction_nodes())
                    leak_ratio = total_leak / (total_demand + total_leak) * 100 if (total_demand + total_leak) > 0 else 0

                    col1, col2, col3 = st.columns(3)
                    col1.metric("总漏损量(m³/h)", f"{total_leak:.2f}")
                    col2.metric("总供水量(m³/h)", f"{total_demand + total_leak:.2f}")
                    col3.metric("漏损率(%)", f"{leak_ratio:.1f}")

                    fig = draw_network_plotly(network, color_by="pressure",
                                              highlight_leaks=list(network.leaks.keys()))
                    st.plotly_chart(fig, width="stretch")
                except Exception as e:
                    st.error(f"模拟失败: {str(e)}")


def page_leak_localization():
    st.header("🎯 漏损定位")

    network = st.session_state.network
    if not network.nodes:
        st.warning("请先定义管网拓扑")
        return

    if st.session_state.hydraulic_results is None:
        st.warning("请先运行水力计算获取基准状态")
        return

    st.subheader("压力监测点设定")
    junction_nodes = [nid for nid, n in network.nodes.items()
                      if n.node_type == NodeType.JUNCTION]

    monitor_nodes = st.multiselect("选择监测节点",
                                   junction_nodes,
                                   default=junction_nodes[:min(3, len(junction_nodes))])

    st.subheader("输入实测水压")
    measured_pressures = {}
    if monitor_nodes:
        for mnid in monitor_nodes:
            default_p = network.nodes[mnid].pressure or 0.0
            p = st.number_input(f"节点 {mnid} 实测水压(m)",
                               value=float(default_p) - 2.0,
                               key=f"measured_{mnid}")
            measured_pressures[mnid] = p

    st.subheader("漏损定位参数")
    col1, col2 = st.columns(2)
    with col1:
        top_k = st.number_input("筛选可疑管段数", value=10, min_value=3, max_value=30)
    with col2:
        locate_method = st.selectbox("求解方法", ["gradient", "hardy_cross"],
                                     key="locate_method",
                                     format_func=lambda x: {"gradient": "梯度法",
                                                            "hardy_cross": "Hardy-Cross法"}.get(x, x))

    if st.button("▶️ 运行漏损定位", type="primary"):
        if not monitor_nodes:
            st.error("请选择至少一个监测节点")
        elif not measured_pressures:
            st.error("请输入监测点水压")
        else:
            with st.spinner("正在进行漏损定位分析(可能需要较时间)..."):
                try:
                    progress_text = st.empty()
                    progress_text.text("第一阶段: 计算灵敏度矩阵...")

                    result = run_leak_localization(
                        network, monitor_nodes, measured_pressures,
                        locate_method, top_k
                    )
                    st.session_state.leak_locate_results = result

                    progress_text.text("分析完成!")
                    st.success("漏损定位分析完成!")

                    if result["leaks"]:
                        st.subheader("漏损定位结果")
                        leak_table = []
                        for leak in result["leaks"]:
                            link = network.links.get(leak["link_id"])
                            link_name = leak["link_id"]
                            if link:
                                link_name += f" ({link.start_node}→{link.end_node})"
                            leak_table.append({
                                "管段": link_name,
                                "漏损位置": f"{leak['position']:.2f}",
                                "漏损面积(mm²)": f"{leak['area_mm2']:.1f}",
                                "置信度(%)": f"{result['confidence']:.1f}",
                            })
                        st.dataframe(pd.DataFrame(leak_table), width="stretch")

                        fig = draw_network_plotly(network, color_by="pressure",
                                                  leak_locate_result=result)
                        st.plotly_chart(fig, width="stretch")
                    else:
                        st.info("未检测到明显漏损")

                    st.subheader("灵敏度分析")
                    if result["suspect_links"]:
                        st.markdown("**最可疑管段排序:**")
                        for i, lid in enumerate(result["suspect_links"]):
                            st.write(f"  {i+1}. 管段 {lid}")

                except Exception as e:
                    st.error(f"定位失败: {str(e)}")


def page_water_quality():
    st.header("🧪 水质模拟")

    network = st.session_state.network
    if not network.nodes:
        st.warning("请先定义管网拓扑")
        return

    if st.session_state.hydraulic_results is None:
        st.warning("请先运行水力计算")
        return

    st.subheader("水质参数")
    col1, col2 = st.columns(2)
    with col1:
        source_chlorine = st.number_input("水源余氯浓度(mg/L)", value=1.0,
                                          min_value=0.0, step=0.1)
    with col2:
        kb = st.number_input("管壁衰减系数(/天)", value=0.5, min_value=0.01, step=0.1)

    if st.button("▶️ 运行水质模拟", type="primary"):
        with st.spinner("正在计算水质..."):
            try:
                result = run_water_quality(network, source_chlorine, kb)
                st.session_state.quality_results = result
                st.success("水质模拟完成!")
            except Exception as e:
                st.error(f"水质模拟失败: {str(e)}")

    if st.session_state.quality_results:
        result = st.session_state.quality_results

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**水龄分布**")
            age_data = []
            for nid in sorted(result["water_age"].keys()):
                age_data.append({
                    "节点": nid,
                    "水龄(s)": f"{result['water_age'][nid]:.0f}",
                    "水龄(h)": f"{result['water_age'][nid]/3600:.1f}",
                })
            st.dataframe(pd.DataFrame(age_data), width="stretch")

        with col2:
            st.markdown("**余氯浓度**")
            cl_data = []
            for nid in sorted(result["chlorine"].keys()):
                conc = result["chlorine"][nid]
                cl_data.append({
                    "节点": nid,
                    "余氯(mg/L)": f"{conc:.4f}",
                    "达标": "✅" if conc >= 0.05 else "❌",
                })
            st.dataframe(pd.DataFrame(cl_data), width="stretch")

        if result["non_compliant"]:
            st.warning(f"⚠️ 有 {len(result['non_compliant'])} 个节点余氯浓度低于0.05mg/L标准")
            nc_data = []
            for item in result["non_compliant"]:
                nc_data.append({
                    "节点": item["node_id"],
                    "余氯(mg/L)": f"{item['chlorine']:.4f}",
                    "水龄(h)": f"{item['water_age']/3600:.1f}",
                })
            st.dataframe(pd.DataFrame(nc_data), width="stretch")


def page_verification():
    st.header("✅ 设计校核")

    network = st.session_state.network
    if not network.nodes:
        st.warning("请先定义管网拓扑")
        return

    if st.session_state.hydraulic_results is None:
        st.warning("请先运行水力计算")
        return

    junction_nodes = [nid for nid, n in network.nodes.items()
                      if n.node_type == NodeType.JUNCTION]

    st.subheader("消防校核设定")
    fire_nodes = st.multiselect("选择消防栓节点", junction_nodes)

    if st.button("▶️ 运行设计校核", type="primary"):
        with st.spinner("正在校核..."):
            try:
                result = run_design_check(network, fire_nodes)
                st.session_state.verification_results = result
                st.success("设计校核完成!")
            except Exception as e:
                st.error(f"校核失败: {str(e)}")

    if st.session_state.verification_results:
        result = st.session_state.verification_results

        col1, col2, col3 = st.columns(3)

        with col1:
            vel_ok = result.get("velocity_ok", False)
            st.metric("流速校核", "通过 ✅" if vel_ok else "不通过 ❌")
            if result["velocity_warnings"]:
                with st.expander("流速异常管段"):
                    for w in result["velocity_warnings"]:
                        if w["type"] == "velocity_low":
                            st.warning(w["message"])
                        else:
                            st.error(w["message"])

        with col2:
            pres_ok = result.get("pressure_ok", False)
            st.metric("水压校核", "通过 ✅" if pres_ok else "不通过 ❌")
            if result["pressure_violations"]:
                with st.expander("水压不足节点"):
                    for v in result["pressure_violations"]:
                        st.error(v["message"])

        with col3:
            fire_ok = result.get("fire_ok")
            if fire_ok is not None:
                st.metric("消防校核", "通过 ✅" if fire_ok else "不通过 ❌")
                if result["fire_check"] and result["fire_check"]["violations"]:
                    with st.expander("消防不达标节点"):
                        for v in result["fire_check"]["violations"]:
                            st.error(f"节点 {v['node_id']} 消防水压 {v['pressure']:.1f}m < {v['limit']}m")
            else:
                st.metric("消防校核", "未设定消防栓")


def page_export():
    st.header("📁 结果导出")

    network = st.session_state.network
    if not network.nodes:
        st.warning("请先定义管网拓扑")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("CSV导出")
        if st.button("📥 导出节点水压表(CSV)"):
            csv_str = export_node_pressure_csv(network)
            st.download_button("下载", csv_str, "node_pressure.csv", "text/csv")

        if st.button("📥 导出管段流量表(CSV)"):
            csv_str = export_link_flow_csv(network)
            st.download_button("下载", csv_str, "link_flow.csv", "text/csv")

        if st.session_state.quality_results:
            if st.button("📥 导出水质结果(CSV)"):
                csv_str = export_quality_csv(st.session_state.quality_results)
                st.download_button("下载", csv_str, "quality.csv", "text/csv")

    with col2:
        st.subheader("EPANET格式导出")
        if st.button("📥 导出EPANET INP文件"):
            inp_str = export_epanet_inp(network)
            st.download_button("下载", inp_str, "network.inp", "text/plain")

        st.subheader("PDF报告")
        if st.button("📄 生成分析报告(PDF)"):
            with st.spinner("正在生成PDF报告..."):
                pdf_bytes = generate_pdf_report(
                    network,
                    quality_result=st.session_state.quality_results,
                    verification_result=st.session_state.verification_results,
                    leak_result=st.session_state.leak_locate_results,
                    eps_results=st.session_state.eps_results,
                )
                if pdf_bytes:
                    st.download_button("下载PDF", pdf_bytes,
                                       "water_network_report.pdf",
                                       "application/pdf")
                else:
                    st.error("PDF生成失败")


def page_scenario_comparison():
    st.header("📊 多工况对比分析")

    network = st.session_state.network
    if not network.nodes:
        st.warning("请先定义管网拓扑")
        return

    st.subheader("工况管理")

    with st.expander("💾 保存当前工况", expanded=True):
        scenario_name = st.text_input("工况名称", value="", key="scenario_name")
        if st.button("保存当前工况", key="save_scenario"):
            if not scenario_name:
                st.error("请输入工况名称")
            elif scenario_name in st.session_state.scenarios:
                st.error(f"工况 '{scenario_name}' 已存在，请使用其他名称")
            else:
                demands = {nid: node.demand for nid, node in network.nodes.items()}
                valve_settings = {lid: link.setting for lid, link in network.links.items()
                                  if link.element_type == ElementType.VALVE}
                st.session_state.scenarios[scenario_name] = {
                    "name": scenario_name,
                    "demands": demands,
                    "valve_settings": valve_settings,
                }
                st.success(f"工况 '{scenario_name}' 已保存")
                st.rerun()

    if st.session_state.scenarios:
        st.markdown("**已保存的工况:**")
        scenario_data = []
        for sname, sdata in st.session_state.scenarios.items():
            n_nodes = len(sdata["demands"])
            n_valves = len(sdata["valve_settings"])
            scenario_data.append({
                "工况名称": sname,
                "节点数": n_nodes,
                "阀门设置数": n_valves,
            })
        st.dataframe(pd.DataFrame(scenario_data), width="stretch")

        delete_scenario = st.selectbox("删除工况", [""] + list(st.session_state.scenarios.keys()),
                                       key="del_scenario")
        if delete_scenario and st.button("🗑️ 删除选中工况"):
            del st.session_state.scenarios[delete_scenario]
            st.rerun()

    st.subheader("工况对比分析")

    scenario_names = list(st.session_state.scenarios.keys())
    if len(scenario_names) < 2:
        st.info("请至少保存2个工况才能进行对比分析")
        return

    selected_scenarios = st.multiselect(
        "选择要对比的工况 (2-3个)",
        scenario_names,
        default=scenario_names[:min(3, len(scenario_names))],
        max_selections=3,
    )

    if len(selected_scenarios) < 2:
        st.info("请选择至少2个工况")
        return

    scenario_method = st.selectbox("求解方法", ["gradient", "hardy_cross"],
                                   format_func=lambda x: {"gradient": "梯度法",
                                                          "hardy_cross": "Hardy-Cross法"}.get(x, x),
                                   key="scenario_method")

    if st.button("▶️ 运行工况对比", type="primary"):
        scenario_results = {}
        for sname in selected_scenarios:
            sdata = st.session_state.scenarios[sname]
            net_copy = deepcopy(network)
            net_copy.leaks.clear()
            for nid, demand in sdata["demands"].items():
                if nid in net_copy.nodes:
                    net_copy.nodes[nid].demand = demand
            for lid, setting in sdata["valve_settings"].items():
                if lid in net_copy.links:
                    net_copy.links[lid].setting = setting
            try:
                run_hydraulic_with_relaxation(net_copy, scenario_method)
                node_pressures = {}
                link_flows = {}
                for nid, node in net_copy.nodes.items():
                    node_pressures[nid] = node.pressure if node.pressure else 0.0
                for lid, link in net_copy.links.items():
                    link_flows[lid] = abs(link.flow) * 1000 if link.flow else 0.0
                scenario_results[sname] = {
                    "node_pressures": node_pressures,
                    "link_flows": link_flows,
                    "success": True,
                }
            except Exception as e:
                scenario_results[sname] = {"success": False, "error": str(e)}

        successful = [s for s in selected_scenarios if scenario_results[s]["success"]]
        if not successful:
            st.error("所有工况计算均失败")
            return

        st.subheader("节点水压对比")

        all_nids = sorted(network.nodes.keys())
        compare_data = []
        for nid in all_nids:
            row = {"节点": nid, "类型": network.nodes[nid].node_type.value}
            for sname in successful:
                p = scenario_results[sname]["node_pressures"].get(nid, 0.0)
                row[f"{sname} 水压(m)"] = f"{p:.2f}"
            if len(successful) >= 2:
                pressures_list = [scenario_results[s]["node_pressures"].get(nid, 0.0)
                                  for s in successful]
                max_diff = max(pressures_list) - min(pressures_list)
                row["最大差值(m)"] = f"{max_diff:.2f}"
            compare_data.append(row)
        st.dataframe(pd.DataFrame(compare_data), width="stretch")

        fig_bar = go.Figure()
        junction_nids = [nid for nid in all_nids
                         if network.nodes[nid].node_type == NodeType.JUNCTION]
        for sname in successful:
            pressures = [scenario_results[sname]["node_pressures"].get(nid, 0.0)
                         for nid in junction_nids]
            fig_bar.add_trace(go.Bar(
                x=junction_nids,
                y=pressures,
                name=sname,
            ))
        fig_bar.update_layout(
            title="各工况节点水压对比",
            xaxis_title="节点", yaxis_title="水压(m)",
            barmode="group",
            height=400,
        )
        st.plotly_chart(fig_bar, width="stretch")

        st.subheader("管段流量对比")

        all_lids = sorted(network.links.keys())
        link_compare_data = []
        for lid in all_lids:
            link = network.links[lid]
            row = {"管段": lid, "起点": link.start_node, "终点": link.end_node}
            for sname in successful:
                f = scenario_results[sname]["link_flows"].get(lid, 0.0)
                row[f"{sname} 流量(L/s)"] = f"{f:.2f}"
            if len(successful) >= 2:
                flows_list = [scenario_results[s]["link_flows"].get(lid, 0.0)
                              for s in successful]
                max_diff = max(flows_list) - min(flows_list)
                row["最大差值(L/s)"] = f"{max_diff:.2f}"
            link_compare_data.append(row)
        st.dataframe(pd.DataFrame(link_compare_data), width="stretch")

        fig_line = go.Figure()
        for sname in successful:
            flows = [scenario_results[sname]["link_flows"].get(lid, 0.0)
                     for lid in all_lids]
            fig_line.add_trace(go.Scatter(
                x=all_lids,
                y=flows,
                mode="lines+markers",
                name=sname,
            ))
        fig_line.update_layout(
            title="各工况管段流量对比",
            xaxis_title="管段", yaxis_title="流量(L/s)",
            height=400,
        )
        st.plotly_chart(fig_line, width="stretch")


def page_connectivity_analysis():
    st.header("🔗 管网连通性分析")

    network = st.session_state.network
    if not network.nodes:
        st.warning("请先定义管网拓扑")
        return

    if st.button("▶️ 运行连通性分析", type="primary"):
        result = run_connectivity_analysis(network)
        st.session_state.connectivity_result = result

    if st.session_state.connectivity_result:
        result = st.session_state.connectivity_result

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("连通分量数", result["n_components"])
        col2.metric("孤立节点数", result["n_isolated_nodes"])
        col3.metric("孤立子网数", result["n_isolated_subnets"])
        col4.metric("死端管段数", result["n_dead_end_pipes"])

        if result["isolated_nodes"]:
            st.subheader("孤立节点")
            st.warning(f"以下节点与任何管段都不相连: {', '.join(sorted(result['isolated_nodes']))}")
            for nid in sorted(result["isolated_nodes"]):
                node = network.nodes.get(nid)
                if node:
                    st.write(f"  节点 {nid}: 类型={node.node_type.value}, 标高={node.elevation:.1f}m")

        if result["isolated_subnets"]:
            st.subheader("孤立子网")
            for i, subnet in enumerate(result["isolated_subnets"]):
                st.error(f"孤立子网 {i+1}: {', '.join(sorted(subnet))} (与水源不连通)")

        if result["dead_end_pipes"]:
            st.subheader("死端管段")
            st.warning("以下管段只有一端连接到管网:")
            for lid in result["dead_end_pipes"]:
                link = network.links.get(lid)
                if link:
                    st.write(f"  管段 {lid}: {link.start_node} → {link.end_node}")

        st.subheader("连通性可视化")
        fig = draw_network_plotly(network, color_by="connectivity",
                                  connectivity_result=result)
        st.plotly_chart(fig, width="stretch")

        st.subheader("各连通分量详情")
        for i, comp in enumerate(result["components"]):
            comp_links = []
            for lid, link in network.links.items():
                if link.start_node in comp and link.end_node in comp:
                    comp_links.append(lid)
            is_main = bool(comp & {n.id for n in network.get_source_nodes()})
            status = "✅ 主管网(连通水源)" if is_main else "❌ 孤立子网"
            with st.expander(f"连通分量 {i+1} - {status}"):
                st.write(f"节点数: {len(comp)}")
                st.write(f"管段数: {len(comp_links)}")
                st.write(f"节点: {', '.join(sorted(comp))}")
                if comp_links:
                    st.write(f"管段: {', '.join(comp_links)}")


def page_dma_management():
    st.header("🗺️ 压力分区管理 (DMA)")

    network = st.session_state.network
    if not network.nodes:
        st.warning("请先定义管网拓扑")
        return

    st.subheader("分区定义")

    with st.expander("➕ 新建分区", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            new_zone_name = st.text_input("分区名称", value="", key="new_zone_name")
        with col2:
            zone_color_idx = len(st.session_state.dma_zone_defs) % len(DMA_ZONE_COLORS)
            new_zone_color = st.color_picker("分区颜色",
                                             value=DMA_ZONE_COLORS[zone_color_idx],
                                             key="new_zone_color")
        if st.button("创建分区", key="create_zone"):
            if not new_zone_name:
                st.error("请输入分区名称")
            elif new_zone_name in st.session_state.dma_zone_defs:
                st.error(f"分区 '{new_zone_name}' 已存在")
            else:
                st.session_state.dma_zone_defs[new_zone_name] = {
                    "name": new_zone_name,
                    "color": new_zone_color,
                }
                st.success(f"分区 '{new_zone_name}' 已创建")
                st.rerun()

    if st.session_state.dma_zone_defs:
        st.markdown("**已定义的分区:**")
        zone_data = []
        for zname, zinfo in st.session_state.dma_zone_defs.items():
            n_nodes = sum(1 for n in network.nodes.values() if n.dma_zone == zname)
            zone_data.append({
                "分区名称": zname,
                "颜色": zinfo["color"],
                "节点数": n_nodes,
            })
        st.dataframe(pd.DataFrame(zone_data), width="stretch")

        delete_zone = st.selectbox("删除分区", [""] + list(st.session_state.dma_zone_defs.keys()),
                                   key="del_zone")
        if delete_zone and st.button("🗑️ 删除选中分区"):
            for node in network.nodes.values():
                if node.dma_zone == delete_zone:
                    node.dma_zone = ""
            del st.session_state.dma_zone_defs[delete_zone]
            st.rerun()

    st.subheader("节点分区分配")

    zone_names = list(st.session_state.dma_zone_defs.keys())
    if zone_names:
        with st.expander("批量分配节点到分区"):
            assign_zone = st.selectbox("选择目标分区", zone_names, key="assign_zone")
            all_node_ids = list(network.nodes.keys())
            nodes_to_assign = st.multiselect(
                "选择要分配的节点",
                all_node_ids,
                key="nodes_to_assign",
            )
            if st.button("分配节点到分区", key="btn_assign"):
                for nid in nodes_to_assign:
                    if nid in network.nodes:
                        network.nodes[nid].dma_zone = assign_zone
                st.success(f"已将 {len(nodes_to_assign)} 个节点分配到分区 '{assign_zone}'")
                st.rerun()

        with st.expander("单个节点分区调整"):
            for nid, node in network.nodes.items():
                current_zone = node.dma_zone if node.dma_zone else "(未分配)"
                cols = st.columns([1, 2])
                with cols[0]:
                    st.text(f"{nid}")
                with cols[1]:
                    zone_options = ["(未分配)"] + zone_names
                    selected_idx = zone_options.index(current_zone) if current_zone in zone_options else 0
                    new_zone = st.selectbox(
                        f"节点{nid}分区",
                        zone_options,
                        index=selected_idx,
                        key=f"node_zone_{nid}",
                    )
                    actual_zone = "" if new_zone == "(未分配)" else new_zone
                    if actual_zone != node.dma_zone:
                        node.dma_zone = actual_zone

    st.subheader("分区可视化")

    show_boundary = st.checkbox("显示分区边界管段(虚线)", value=True, key="show_boundary")

    any_zoned = any(n.dma_zone for n in network.nodes.values())
    if any_zoned and st.session_state.dma_zone_defs:
        fig = draw_network_plotly(
            network,
            show_dma_zones=True,
            show_dma_boundary=show_boundary,
        )
        st.plotly_chart(fig, width="stretch")

        legend_data = []
        for zname, zinfo in st.session_state.dma_zone_defs.items():
            n_nodes = sum(1 for n in network.nodes.values() if n.dma_zone == zname)
            legend_data.append({
                "分区": zname,
                "颜色": zinfo["color"],
                "节点数": n_nodes,
            })
        if legend_data:
            st.dataframe(pd.DataFrame(legend_data), width="stretch")
    else:
        fig = draw_network_plotly(network)
        st.plotly_chart(fig, width="stretch")
        st.info("请先将节点分配到分区以查看分区可视化")

    st.subheader("分区统计")

    if st.session_state.hydraulic_results is not None and any_zoned:
        stats = compute_dma_statistics(network)
        for zone_name, zone_stats in stats.items():
            with st.expander(f"📊 {zone_name}"):
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("节点数", zone_stats["node_count"])
                col2.metric("平均水压(m)", f"{zone_stats['avg_pressure']:.2f}")
                col3.metric("最低水压节点", zone_stats["min_pressure_node"] or "-")
                col4.metric("最低水压(m)", f"{zone_stats['min_pressure']:.2f}")
                col5, col6 = st.columns(2)
                col5.metric("总需水量(m³/h)", f"{zone_stats['total_demand']:.2f}")
                col6.metric("供水入口流量(m³/s)", f"{zone_stats['inlet_flow']:.4f}")
                if zone_stats["inlet_links"]:
                    st.write(f"入口管段: {', '.join(zone_stats['inlet_links'])}")
    elif not st.session_state.hydraulic_results:
        st.info("请先运行水力计算以查看分区统计")
    elif not any_zoned:
        st.info("请先将节点分配到分区")

    st.subheader("按分区筛选查看")

    if zone_names:
        filter_zone = st.selectbox("选择分区", ["全部"] + zone_names, key="filter_zone")
        if filter_zone != "全部":
            zone_nids = {nid for nid, n in network.nodes.items() if n.dma_zone == filter_zone}
            zone_lids = {lid for lid, link in network.links.items()
                         if link.start_node in zone_nids and link.end_node in zone_nids}
            boundary_lids = set(find_boundary_links(network)) & {
                lid for lid, link in network.links.items()
                if link.start_node in zone_nids or link.end_node in zone_nids
            }

            st.markdown(f"**分区 '{filter_zone}' 内的节点**")
            znode_data = []
            for nid in sorted(zone_nids):
                node = network.nodes[nid]
                znode_data.append({
                    "编号": nid, "类型": node.node_type.value,
                    "标高(m)": node.elevation,
                    "需水量(m³/h)": node.demand,
                    "压力(m)": f"{node.pressure:.2f}" if node.pressure else "-",
                })
            if znode_data:
                st.dataframe(pd.DataFrame(znode_data), width="stretch")

            st.markdown(f"**分区 '{filter_zone}' 内的管段**")
            zlink_data = []
            for lid in sorted(zone_lids):
                link = network.links[lid]
                zlink_data.append({
                    "编号": lid, "起点": link.start_node, "终点": link.end_node,
                    "管径(mm)": link.diameter, "长度(m)": link.length,
                    "流量(L/s)": f"{abs(link.flow)*1000:.2f}" if link.flow else "-",
                })
            if zlink_data:
                st.dataframe(pd.DataFrame(zlink_data), width="stretch")

            if boundary_lids:
                st.markdown(f"**分区 '{filter_zone}' 的边界管段**")
                blink_data = []
                for lid in sorted(boundary_lids):
                    link = network.links[lid]
                    sn = network.nodes.get(link.start_node)
                    en = network.nodes.get(link.end_node)
                    other_zone = ""
                    if sn and sn.dma_zone != filter_zone:
                        other_zone = sn.dma_zone
                    elif en and en.dma_zone != filter_zone:
                        other_zone = en.dma_zone
                    blink_data.append({
                        "编号": lid, "起点": link.start_node, "终点": link.end_node,
                        "相邻分区": other_zone or "(未分配)",
                        "流量(L/s)": f"{abs(link.flow)*1000:.2f}" if link.flow else "-",
                    })
                st.dataframe(pd.DataFrame(blink_data), width="stretch")


def main():
    st.set_page_config(
        page_title="城市供水管网水力分析与漏损定位工具",
        page_icon="🌊",
        layout="wide",
    )

    init_session_state()

    st.sidebar.title("🌊 供水管网分析系统")
    st.sidebar.markdown("---")

    page = st.sidebar.radio(
        "功能导航",
        ["📐 管网定义", "💧 水力计算", "📊 需水量与延时模拟",
         "🔍 漏损模拟", "🎯 漏损定位", "🧪 水质模拟",
         "✅ 设计校核", "📊 工况对比分析",
         "🔗 连通性分析", "🗺️ 压力分区管理",
         "📁 结果导出"],
        label_visibility="collapsed"
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("**管网信息**")
    net = st.session_state.network
    st.sidebar.text(f"节点: {len(net.nodes)}")
    st.sidebar.text(f"管段: {len(net.links)}")
    st.sidebar.text(f"漏损: {len(net.leaks)}")

    if page == "📐 管网定义":
        page_network_definition()
    elif page == "💧 水力计算":
        page_hydraulic()
    elif page == "📊 需水量与延时模拟":
        page_demand()
    elif page == "🔍 漏损模拟":
        page_leak_simulation()
    elif page == "🎯 漏损定位":
        page_leak_localization()
    elif page == "🧪 水质模拟":
        page_water_quality()
    elif page == "✅ 设计校核":
        page_verification()
    elif page == "📊 工况对比分析":
        page_scenario_comparison()
    elif page == "🔗 连通性分析":
        page_connectivity_analysis()
    elif page == "🗺️ 压力分区管理":
        page_dma_management()
    elif page == "📁 结果导出":
        page_export()


if __name__ == "__main__":
    main()