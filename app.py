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
                        eps_hour_data=None, leak_locate_result=None):
    fig = go.Figure()

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
            symbol = "diamond"
            base_size = 18
        elif node.node_type == NodeType.TANK:
            symbol = "square"
            base_size = 16
        else:
            symbol = "circle"
            base_size = max(8, min(20, 8 + node.demand / 5))

        if color_by == "pressure" and max_pressure > min_pressure:
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

        if lid in highlight_links:
            line_color = "red"
            line_width = line_width * 2
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

        mid_x = (sn.x + en.x) / 2
        mid_y = (sn.y + en.y) / 2

        fig.add_trace(go.Scatter(
            x=[sn.x, en.x],
            y=[sn.y, en.y],
            mode="lines",
            line=dict(color=line_color, width=line_width),
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

    node_color_vals = node_colors if color_by == "pressure" else None
    if node_color_vals and (max_pressure > min_pressure):
        colorscale = "RdYlBu"
    else:
        colorscale = None

    marker_dict = dict(size=node_sizes, line=dict(width=1, color="white"))
    if colorscale and node_color_vals:
        marker_dict["color"] = node_color_vals
        marker_dict["colorscale"] = colorscale
        marker_dict["cmin"] = 0
        marker_dict["cmax"] = 1
    else:
        marker_dict["color"] = [
            "#2196F3" if n.node_type == NodeType.SOURCE
            else "#FF9800" if n.node_type == NodeType.TANK
            else "#4CAF50"
            for n in network.nodes.values()
        ]

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

    if color_by == "pressure" and max_pressure > min_pressure:
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

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📂 加载示例管网"):
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
                    st.session_state.network = new_net
                    st.session_state.hydraulic_results = None
                    st.success(f"成功导入 {len(new_net.nodes)} 个节点, {len(new_net.links)} 条管段")
                    st.rerun()
            except Exception as e:
                st.error(f"导入失败: {str(e)}")

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
                ntype = NodeType(new_node_type)
                node = Node(
                    id=new_node_id, node_type=ntype,
                    x=new_x, y=new_y, elevation=new_elevation,
                    demand=new_demand, head=new_head if ntype == NodeType.SOURCE else None,
                    demand_group=new_demand_group,
                    building_type=new_building_type,
                )
                network.add_node(node)
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
                network.remove_node(delete_node)
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
            if delete_link and st.button("🗑️ 删除选中管段"):
                network.remove_link(delete_link)
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
         "✅ 设计校核", "📁 结果导出"],
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
    elif page == "📁 结果导出":
        page_export()


if __name__ == "__main__":
    main()
