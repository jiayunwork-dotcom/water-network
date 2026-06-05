import io
import numpy as np
from typing import Dict, Optional
from models import WaterNetwork, NodeType, ElementType, PipeMaterial


def export_node_pressure_csv(network: WaterNetwork) -> str:
    lines = ["节点编号,节点类型,地面标高(m),水头(m),压力(m),需水量(m³/h),自由水压(m)"]
    for nid, node in network.nodes.items():
        ntype = node.node_type.value
        elevation = node.elevation
        head = f"{node.head:.2f}" if node.head is not None else ""
        pressure = f"{node.pressure:.2f}" if node.pressure is not None else ""
        demand = f"{node.demand:.2f}"
        free_pressure = f"{node.pressure:.2f}" if node.pressure is not None else ""
        lines.append(f"{nid},{ntype},{elevation},{head},{pressure},{demand},{free_pressure}")
    return "\n".join(lines)


def export_link_flow_csv(network: WaterNetwork) -> str:
    lines = ["管段编号,管段类型,起始节点,终止节点,管径(mm),长度(m),粗糙系数,流量(m³/s),流速(m/s),水头损失(m)"]
    for lid, link in network.links.items():
        etype = link.element_type.value
        flow = f"{link.flow:.6f}" if link.flow is not None else ""
        velocity = f"{link.velocity:.4f}" if link.velocity is not None else ""
        head_loss = f"{link.head_loss:.4f}" if link.head_loss is not None else ""
        lines.append(
            f"{lid},{etype},{link.start_node},{link.end_node},"
            f"{link.diameter},{link.length},{link.get_roughness()},"
            f"{flow},{velocity},{head_loss}"
        )
    return "\n".join(lines)


def export_quality_csv(quality_result: Dict) -> str:
    lines = ["节点编号,水龄(s),余氯浓度(mg/L),是否达标"]
    water_age = quality_result.get("water_age", {})
    chlorine = quality_result.get("chlorine", {})
    non_compliant_ids = set(
        item["node_id"] for item in quality_result.get("non_compliant", [])
    )
    all_nodes = sorted(set(list(water_age.keys()) + list(chlorine.keys())))
    for nid in all_nodes:
        age = f"{water_age.get(nid, 0):.1f}"
        cl = f"{chlorine.get(nid, 0):.4f}"
        compliant = "不达标" if nid in non_compliant_ids else "达标"
        lines.append(f"{nid},{age},{cl},{compliant}")
    return "\n".join(lines)


def export_epanet_inp(network: WaterNetwork) -> str:
    lines = []
    lines.append("[TITLE]")
    lines.append("Water Network - Exported from Water Network Analysis Tool")
    lines.append("")

    lines.append("[JUNCTIONS]")
    lines.append(";ID             	Elev        	Demand      	Pattern")
    for nid, node in network.nodes.items():
        if node.node_type == NodeType.JUNCTION:
            demand_lps = node.demand / 3.6
            pattern = ""
            lines.append(f" {nid:<16s}\t{node.elevation:.2f}\t{demand_lps:.4f}\t{pattern}")
    lines.append("")

    lines.append("[RESERVOIRS]")
    lines.append(";ID             	Head        	Pattern")
    for nid, node in network.nodes.items():
        if node.node_type == NodeType.SOURCE:
            head = node.head if node.head else 50.0
            lines.append(f" {nid:<16s}\t{head:.2f}\t")
    lines.append("")

    lines.append("[TANKS]")
    lines.append(";ID             	Elevation   	InitLevel   	MinLevel    	MaxLevel    	Diameter    	MinVol      	VolCurve")
    for nid, node in network.nodes.items():
        if node.node_type == NodeType.TANK:
            lines.append(
                f" {nid:<16s}\t{node.elevation:.2f}\t{node.init_level:.2f}\t"
                f"{node.min_level:.2f}\t{node.max_level:.2f}\t0\t0\t"
            )
    lines.append("")

    lines.append("[PIPES]")
    lines.append(";ID             	Node1       	Node2       	Length      	Diameter    	Roughness   	MinorLoss  	Status")
    for lid, link in network.links.items():
        if link.element_type in (ElementType.PIPE, ElementType.CHECK_VALVE):
            status = link.status if link.status != "open" else "Open"
            minor = link.minor_loss
            lines.append(
                f" {lid:<16s}\t{link.start_node:<12s}\t{link.end_node:<12s}\t"
                f"{link.length:.1f}\t{link.diameter:.0f}\t{link.get_roughness():.0f}\t"
                f"{minor:.2f}\t{status}"
            )
    lines.append("")

    lines.append("[PUMPS]")
    lines.append(";ID             	Node1       	Node2       	Parameters")
    for lid, link in network.links.items():
        if link.element_type == ElementType.PUMP:
            lines.append(
                f" {lid:<16s}\t{link.start_node:<12s}\t{link.end_node:<12s}\t"
                f"HEAD\t{link.pump_a:.1f}\t{link.pump_b:.6f}"
            )
    lines.append("")

    lines.append("[VALVES]")
    lines.append(";ID             	Node1       	Node2       	Type     	Setting     	MinorLoss")
    for lid, link in network.links.items():
        if link.element_type == ElementType.VALVE:
            lines.append(
                f" {lid:<16s}\t{link.start_node:<12s}\t{link.end_node:<12s}\t"
                f"TCV\t{link.setting:.1f}\t0"
            )
    lines.append("")

    lines.append("[DEMANDS]")
    lines.append(";Junction       	Demand      	Pattern     	Category")
    lines.append("")

    lines.append("[STATUS]")
    lines.append(";ID             	Status/Setting")
    for lid, link in network.links.items():
        if link.element_type == ElementType.CHECK_VALVE:
            lines.append(f" {lid:<16s}\tCV")
    lines.append("")

    lines.append("[PATTERNS]")
    lines.append(";ID             	Multipliers")
    lines.append("")

    lines.append("[CURVES]")
    lines.append(";ID             	X-Value     	Y-Value")
    for lid, link in network.links.items():
        if link.element_type == ElementType.PUMP:
            for q in [0, 10, 20, 30, 40, 50]:
                h = link.pump_a - link.pump_b * (q ** 2)
                lines.append(f" PUMP_{lid:<12s}\t{q:.1f}\t{h:.2f}")
    lines.append("")

    lines.append("[CONTROLS]")
    lines.append("")

    lines.append("[RULES]")
    lines.append("")

    lines.append("[ENERGY]")
    lines.append("")

    lines.append("[EMITTERS]")
    lines.append("")

    lines.append("[QUALITY]")
    lines.append(";Node          	InitQual")
    lines.append("")

    lines.append("[SOURCES]")
    lines.append("")

    lines.append("[MIXING]")
    lines.append("")

    lines.append("[REACTIONS]")
    lines.append("")

    lines.append("[REPORT]")
    lines.append("")

    lines.append("[TIMES]")
    lines.append(" Duration           	0:00")
    lines.append(" Hydraulic Timestep 	1:00")
    lines.append(" Quality Timestep   	0:05")
    lines.append("")

    lines.append("[OPTIONS]")
    lines.append(" Units              	LPS")
    lines.append(" Headloss           	H-W")
    lines.append(" Specific Gravity   	1.0")
    lines.append(" Viscosity          	1.0")
    lines.append(" Trials             	40")
    lines.append(" Accuracy           	0.001")
    lines.append("")

    lines.append("[COORDINATES]")
    lines.append(";Node           	X-Coord     	Y-Coord")
    for nid, node in network.nodes.items():
        lines.append(f" {nid:<16s}\t{node.x:.2f}\t{node.y:.2f}")
    lines.append("")

    lines.append("[VERTICES]")
    lines.append("")

    lines.append("[TAGS]")
    lines.append("")

    lines.append("[END]")
    return "\n".join(lines)


def generate_pdf_report(network: WaterNetwork,
                        quality_result: Optional[Dict] = None,
                        verification_result: Optional[Dict] = None,
                        leak_result: Optional[Dict] = None,
                        eps_results: Optional[Dict] = None) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.colors import black, red, blue, green
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os

        font_paths = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        ]
        font_registered = False
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    pdfmetrics.registerFont(TTFont('ChineseFont', fp))
                    font_registered = True
                    break
                except Exception:
                    continue

        font_name = 'ChineseFont' if font_registered else 'Helvetica'

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        for key in styles.byName:
            styles[key].fontName = font_name

        elements = []

        title_style = styles['Title']
        elements.append(Paragraph("城市供水管网水力分析报告", title_style))
        elements.append(Spacer(1, 10 * mm))

        heading_style = styles['Heading2']
        normal_style = styles['Normal']

        elements.append(Paragraph("一、管网概况", heading_style))
        n_junctions = len(network.get_junction_nodes())
        n_sources = len(network.get_source_nodes())
        n_tanks = len(network.get_tank_nodes())
        n_pipes = sum(1 for l in network.links.values() if l.element_type == ElementType.PIPE)
        n_pumps = sum(1 for l in network.links.values() if l.element_type == ElementType.PUMP)
        n_valves = sum(1 for l in network.links.values() if l.element_type == ElementType.VALVE)
        total_demand = sum(n.demand for n in network.get_junction_nodes())
        total_length = sum(l.length for l in network.links.values())

        overview_data = [
            ["指标", "数值"],
            ["节点总数", str(len(network.nodes))],
            ["  水源节点", str(n_sources)],
            ["  水池节点", str(n_tanks)],
            ["  用户节点", str(n_junctions)],
            ["管段总数", str(len(network.links))],
            ["  普通管段", str(n_pipes)],
            ["  水泵", str(n_pumps)],
            ["  阀门", str(n_valves)],
            ["总需水量(m³/h)", f"{total_demand:.2f}"],
            ["管段总长度(m)", f"{total_length:.1f}"],
        ]
        table = Table(overview_data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), blue),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('GRID', (0, 0), (-1, -1), 0.5, black),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 5 * mm))

        elements.append(Paragraph("二、水力计算结果", heading_style))
        pressure_data = [["节点编号", "压力(m)", "水头(m)", "需水量(m³/h)"]]
        for nid, node in sorted(network.nodes.items()):
            if node.node_type == NodeType.JUNCTION:
                p = f"{node.pressure:.2f}" if node.pressure is not None else "-"
                h = f"{node.head:.2f}" if node.head is not None else "-"
                pressure_data.append([nid, p, h, f"{node.demand:.2f}"])
        if len(pressure_data) > 1:
            table2 = Table(pressure_data)
            table2.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), blue),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('GRID', (0, 0), (-1, -1), 0.5, black),
            ]))
            elements.append(table2)
        elements.append(Spacer(1, 5 * mm))

        if verification_result:
            elements.append(Paragraph("三、设计校核结果", heading_style))
            vel_ok = "通过" if verification_result.get("velocity_ok") else "不通过"
            pres_ok = "通过" if verification_result.get("pressure_ok") else "不通过"
            fire_ok = "-"
            if verification_result.get("fire_ok") is not None:
                fire_ok = "通过" if verification_result["fire_ok"] else "不通过"

            check_data = [
                ["校核项目", "结果"],
                ["流速校核(0.6-3.0m/s)", vel_ok],
                ["水压校核(≥28/35m)", pres_ok],
                ["消防校核(≥10m)", fire_ok],
            ]
            table3 = Table(check_data)
            table3.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), blue),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('GRID', (0, 0), (-1, -1), 0.5, black),
            ]))
            elements.append(table3)
            elements.append(Spacer(1, 5 * mm))

        if leak_result and leak_result.get("leaks"):
            elements.append(Paragraph("四、漏损分析结论", heading_style))
            leak_data = [["管段编号", "漏损位置", "估计漏损量(m³/h)", "置信度(%)"]]
            for leak in leak_result["leaks"]:
                lid = leak["link_id"]
                pos = f"{leak['position']:.2f}"
                area = leak["area_mm2"]
                from leak_sim import compute_leak_flow, get_leak_pressure
                link = network.links.get(lid)
                if link:
                    pressure = get_leak_pressure(network, lid, leak["position"])
                    q_leak = compute_leak_flow(area, pressure, "metal")
                    q_m3h = q_leak * 3600
                else:
                    q_m3h = 0
                conf = f"{leak_result.get('confidence', 0):.1f}"
                leak_data.append([lid, pos, f"{q_m3h:.3f}", conf])
            table4 = Table(leak_data)
            table4.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), red),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('GRID', (0, 0), (-1, -1), 0.5, black),
            ]))
            elements.append(table4)
            elements.append(Spacer(1, 5 * mm))

        if quality_result:
            elements.append(Paragraph("五、水质分析结果", heading_style))
            n_non_compliant = len(quality_result.get("non_compliant", []))
            elements.append(Paragraph(
                f"余氯不达标节点数: {n_non_compliant} (标准: ≥0.05 mg/L)",
                normal_style
            ))
            elements.append(Spacer(1, 3 * mm))

        elements.append(Paragraph("六、建议", heading_style))
        suggestions = []
        if verification_result and not verification_result.get("pressure_ok"):
            suggestions.append("部分节点自由水压不足，建议增大管径或增加供水压力")
        if verification_result and not verification_result.get("velocity_ok"):
            suggestions.append("部分管段流速异常，建议调整管径配置")
        if quality_result and quality_result.get("non_compliant"):
            suggestions.append("部分节点余氯浓度不足，建议增加加氯量或缩短管网停留时间")
        if leak_result and leak_result.get("leaks"):
            suggestions.append("检测到漏损管段，建议优先检修标记管段")
        if not suggestions:
            suggestions.append("管网运行状态良好，各项指标均满足要求")
        for s in suggestions:
            elements.append(Paragraph(f"• {s}", normal_style))

        doc.build(elements)
        return buffer.getvalue()
    except ImportError:
        return b"PDF generation requires reportlab package"
    except Exception as e:
        return f"PDF generation error: {str(e)}".encode('utf-8')
