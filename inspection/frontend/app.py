import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
from datetime import datetime


def _get_api_base():
    env_val = os.environ.get("API_BASE")
    if env_val:
        return env_val
    try:
        return st.secrets.get("API_BASE", "http://localhost:5001")
    except Exception:
        return "http://localhost:5001"


API_BASE = _get_api_base()


def api_get(path, params=None):
    try:
        r = requests.get(f"{API_BASE}{path}", params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def api_post(path, data=None):
    try:
        r = requests.post(f"{API_BASE}{path}", json=data, timeout=10)
        return r.status_code, r.json()
    except Exception as e:
        return 500, {"error": str(e)}


def api_put(path, data=None):
    try:
        r = requests.put(f"{API_BASE}{path}", json=data, timeout=10)
        return r.status_code, r.json()
    except Exception as e:
        return 500, {"error": str(e)}


def api_delete(path):
    try:
        r = requests.delete(f"{API_BASE}{path}", timeout=10)
        return r.status_code, r.json()
    except Exception as e:
        return 500, {"error": str(e)}


SKILL_MAP = {"junior": "初级", "intermediate": "中级", "senior": "高级"}
SKILL_REV = {"初级": "junior", "中级": "intermediate", "高级": "senior"}
STATUS_MAP = {"on_duty": "在岗", "off": "休息", "out": "外出"}
STATUS_REV = {"在岗": "on_duty", "休息": "off", "外出": "out"}

TASK_TYPE_MAP = {
    "daily_inspection": "日常巡检",
    "valve_maintenance": "阀门检修",
    "leak_investigation": "漏损排查",
    "quality_sampling": "水质取样",
}
TASK_TYPE_REV = {v: k for k, v in TASK_TYPE_MAP.items()}

DIFFICULTY_MAP = {"easy": "简单", "medium": "中等", "hard": "困难"}
DIFFICULTY_REV = {"简单": "easy", "中等": "medium", "困难": "hard"}

TASK_STATUS_MAP = {
    "pending": "待分配",
    "assigned": "已分配",
    "in_progress": "进行中",
    "completed": "已完成",
    "anomaly": "异常",
}

ANOMALY_TYPE_MAP = {
    "pipe_break": "管段破损",
    "valve_stuck": "阀门卡死",
    "meter_abnormal": "水表异常",
    "quality_exceed": "水质超标",
    "other": "其他",
}
ANOMALY_TYPE_REV = {v: k for k, v in ANOMALY_TYPE_MAP.items()}

SEVERITY_MAP = {"minor": "轻微", "normal": "一般", "serious": "严重", "urgent": "紧急"}
SEVERITY_REV = {"轻微": "minor", "一般": "normal", "严重": "serious", "紧急": "urgent"}

ANOMALY_STATUS_MAP = {
    "unhandled": "未处理",
    "processing": "处理中",
    "resolved": "已解决",
    "accepted": "已验收",
}

ALERT_LEVEL_MAP = {"info": "提示", "warning": "警告", "critical": "严重"}
ALERT_LEVEL_REV = {"提示": "info", "警告": "warning", "严重": "critical"}
ALERT_STATUS_MAP = {"unread": "未读", "read": "已读"}
CERT_STATUS_MAP = {"valid": "有效", "expired": "已过期", "expiring_soon": "即将过期"}
TRAINING_RESULT_MAP = {"pass": "合格", "fail": "不合格"}


def page_inspectors():
    st.header("👷 巡检员管理")

    zones = api_get("/api/dma/zones") or []

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filter_area = st.selectbox("按片区筛选", ["全部"] + zones, key="insp_filter_area")
    with col_f2:
        filter_status = st.selectbox(
            "按状态筛选",
            ["全部", "在岗", "休息", "外出"],
            key="insp_filter_status",
        )

    params = {}
    if filter_area != "全部":
        params["area"] = filter_area
    if filter_status != "全部":
        params["status"] = STATUS_REV[filter_status]

    inspectors = api_get("/api/inspectors", params=params) or []

    if inspectors:
        rows = []
        for insp in inspectors:
            rows.append({
                "ID": insp["id"],
                "工号": insp["employee_id"],
                "姓名": insp["name"],
                "手机号": insp["phone"],
                "技能等级": SKILL_MAP.get(insp["skill_level"], insp["skill_level"]),
                "负责片区": ", ".join(insp.get("areas", [])),
                "当日状态": STATUS_MAP.get(insp["status"], insp["status"]),
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("暂无巡检员数据")

    st.subheader("添加巡检员")
    with st.form("add_inspector_form"):
        c1, c2 = st.columns(2)
        with c1:
            new_eid = st.text_input("工号", value=f"INS{len(inspectors)+1:03d}")
            new_name = st.text_input("姓名")
            new_phone = st.text_input("手机号")
        with c2:
            new_skill = st.selectbox("技能等级", ["初级", "中级", "高级"])
            new_areas = st.multiselect("负责片区", zones if zones else ["DMA-1", "DMA-2", "DMA-3", "DMA-4"])
            new_status = st.selectbox("当日状态", ["在岗", "休息", "外出"])

        submitted = st.form_submit_button("添加巡检员")
        if submitted:
            if not new_eid or not new_name:
                st.error("工号和姓名为必填项")
            else:
                code, resp = api_post("/api/inspectors", {
                    "employee_id": new_eid,
                    "name": new_name,
                    "phone": new_phone,
                    "skill_level": SKILL_REV[new_skill],
                    "areas": new_areas,
                    "status": STATUS_REV[new_status],
                })
                if code == 201:
                    st.success(f"巡检员 {new_name} 添加成功")
                    st.rerun()
                else:
                    st.error(resp.get("error", "添加失败"))

    if inspectors:
        st.subheader("编辑/删除巡检员")
        insp_options = {f"{i['employee_id']} - {i['name']}": i["id"] for i in inspectors}
        selected = st.selectbox("选择巡检员", list(insp_options.keys()), key="edit_insp_sel")
        selected_id = insp_options[selected]
        selected_insp = next((i for i in inspectors if i["id"] == selected_id), None)

        if selected_insp:
            with st.form("edit_inspector_form"):
                ec1, ec2 = st.columns(2)
                with ec1:
                    ed_name = st.text_input("姓名", value=selected_insp["name"])
                    ed_phone = st.text_input("手机号", value=selected_insp["phone"])
                    ed_skill = st.selectbox(
                        "技能等级",
                        ["初级", "中级", "高级"],
                        index=["初级", "中级", "高级"].index(
                            SKILL_MAP.get(selected_insp["skill_level"], "初级")
                        ),
                    )
                with ec2:
                    ed_areas = st.multiselect(
                        "负责片区",
                        zones if zones else ["DMA-1", "DMA-2", "DMA-3", "DMA-4"],
                        default=selected_insp.get("areas", []),
                    )
                    ed_status = st.selectbox(
                        "当日状态",
                        ["在岗", "休息", "外出"],
                        index=["在岗", "休息", "外出"].index(
                            STATUS_MAP.get(selected_insp["status"], "在岗")
                        ),
                    )

                col_save, col_del = st.columns(2)
                with col_save:
                    save_btn = st.form_submit_button("保存修改")
                with col_del:
                    del_btn = st.form_submit_button("删除巡检员")

                if save_btn:
                    code, resp = api_put(f"/api/inspectors/{selected_id}", {
                        "name": ed_name,
                        "phone": ed_phone,
                        "skill_level": SKILL_REV[ed_skill],
                        "areas": ed_areas,
                        "status": STATUS_REV[ed_status],
                    })
                    if code == 200:
                        st.success("修改成功")
                        st.rerun()
                    else:
                        st.error(resp.get("error", "修改失败"))

                if del_btn:
                    code, resp = api_delete(f"/api/inspectors/{selected_id}")
                    if code == 200:
                        st.success("删除成功")
                        st.rerun()
                    else:
                        st.error(resp.get("error", "删除失败"))


def page_tasks():
    st.header("📋 巡检任务管理")

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_type = st.selectbox(
            "任务类型",
            ["全部", "日常巡检", "阀门检修", "漏损排查", "水质取样"],
            key="task_filter_type",
        )
    with col_f2:
        filter_status = st.selectbox(
            "任务状态",
            ["全部", "待分配", "已分配", "进行中", "已完成", "异常"],
            key="task_filter_status",
        )
    with col_f3:
        filter_diff = st.selectbox(
            "难度等级",
            ["全部", "简单", "中等", "困难"],
            key="task_filter_diff",
        )

    params = {}
    if filter_type != "全部":
        params["task_type"] = TASK_TYPE_REV[filter_type]
    if filter_status != "全部":
        params["status"] = next(
            (k for k, v in TASK_STATUS_MAP.items() if v == filter_status), None
        )
    if filter_diff != "全部":
        params["difficulty"] = DIFFICULTY_REV[filter_diff]

    tasks = api_get("/api/tasks", params=params) or []
    inspectors = api_get("/api/inspectors") or []

    if tasks:
        rows = []
        for t in tasks:
            insp_name = ""
            if t.get("inspector_id"):
                insp = next((i for i in inspectors if i["id"] == t["inspector_id"]), None)
                insp_name = insp["name"] if insp else str(t["inspector_id"])
            rows.append({
                "ID": t["id"],
                "任务类型": TASK_TYPE_MAP.get(t["task_type"], t["task_type"]),
                "难度": DIFFICULTY_MAP.get(t["difficulty"], t["difficulty"]),
                "预计耗时(分钟)": t["estimated_minutes"],
                "状态": TASK_STATUS_MAP.get(t["status"], t["status"]),
                "巡检员": insp_name,
                "片区": t.get("area", ""),
                "目标节点": ", ".join(t.get("target_nodes", [])),
                "目标管段": ", ".join(t.get("target_links", [])),
                "描述": t.get("description", ""),
                "日期": t.get("scheduled_date", ""),
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("暂无任务数据")

    st.subheader("创建任务")
    network_nodes = api_get("/api/network/nodes") or []
    network_links = api_get("/api/network/links") or []
    zones = api_get("/api/dma/zones") or []

    with st.form("create_task_form"):
        tc1, tc2 = st.columns(2)
        with tc1:
            ct_type = st.selectbox("任务类型", ["日常巡检", "阀门检修", "漏损排查", "水质取样"])
            ct_diff = st.selectbox("难度等级", ["简单", "中等", "困难"])
            ct_minutes = st.number_input("预计耗时(分钟)", min_value=5, max_value=480, value=60)
            ct_area = st.selectbox("片区", zones if zones else ["DMA-1", "DMA-2", "DMA-3", "DMA-4"])
        with tc2:
            node_ids = [n["id"] for n in network_nodes] if network_nodes else []
            link_ids = [l["id"] for l in network_links] if network_links else []
            ct_nodes = st.multiselect("目标节点", node_ids if node_ids else ["J1", "J2", "J3", "J4", "J5", "J6"])
            ct_links = st.multiselect("目标管段", link_ids if link_ids else ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"])
            ct_desc = st.text_area("任务描述")
            ct_date = st.date_input("排班日期", value=datetime.now())

        insp_options = {f"{i['employee_id']} - {i['name']}": i["id"] for i in inspectors}
        ct_insp = st.selectbox("指定巡检员(可选)", ["不指定"] + list(insp_options.keys()))

        submitted = st.form_submit_button("创建任务")
        if submitted:
            task_data = {
                "task_type": TASK_TYPE_REV[ct_type],
                "difficulty": DIFFICULTY_REV[ct_diff],
                "estimated_minutes": ct_minutes,
                "area": ct_area,
                "target_nodes": ct_nodes,
                "target_links": ct_links,
                "description": ct_desc,
                "scheduled_date": str(ct_date),
            }
            if ct_insp != "不指定":
                task_data["inspector_id"] = insp_options[ct_insp]
            code, resp = api_post("/api/tasks", task_data)
            if code == 201:
                st.success("任务创建成功")
                st.rerun()
            else:
                st.error(resp.get("error", "创建失败"))

    if tasks:
        st.subheader("任务状态流转")
        task_options = {
            f"#{t['id']} {TASK_TYPE_MAP.get(t['task_type'], '')} - {TASK_STATUS_MAP.get(t['status'], '')}": t
            for t in tasks
        }
        sel_task_key = st.selectbox("选择任务", list(task_options.keys()), key="transition_task")
        sel_task = task_options[sel_task_key]

        current_status = sel_task["status"]
        valid_next = {
            "pending": ["assigned"],
            "assigned": ["in_progress", "pending"],
            "in_progress": ["completed", "anomaly"],
            "completed": [],
            "anomaly": ["in_progress"],
        }.get(current_status, [])

        if not valid_next:
            st.info("当前任务状态无法继续流转")
        else:
            next_labels = [TASK_STATUS_MAP.get(s, s) for s in valid_next]
            next_choice = st.selectbox("目标状态", next_labels, key="next_status_sel")
            next_status = valid_next[next_labels.index(next_choice)]

            insp_for_transition = None
            if next_status == "assigned":
                insp_for_transition = st.selectbox(
                    "分配巡检员",
                    list(insp_options.keys()),
                    key="transition_insp",
                )

            if st.button("执行状态变更"):
                trans_data = {"status": next_status}
                if insp_for_transition and next_status == "assigned":
                    trans_data["inspector_id"] = insp_options[insp_for_transition]
                code, resp = api_post(f"/api/tasks/{sel_task['id']}/transition", trans_data)
                if code == 200:
                    st.success("状态变更成功")
                    st.rerun()
                else:
                    st.error(resp.get("error", "变更失败"))


def page_scheduling():
    st.header("📅 智能排班")

    inspectors = api_get("/api/inspectors", params={"status": "on_duty"}) or []
    pending_tasks = api_get("/api/tasks", params={"status": "pending"}) or []

    st.subheader("在岗巡检员")
    if inspectors:
        rows = []
        for insp in inspectors:
            rows.append({
                "ID": insp["id"],
                "工号": insp["employee_id"],
                "姓名": insp["name"],
                "技能等级": SKILL_MAP.get(insp["skill_level"], ""),
                "负责片区": ", ".join(insp.get("areas", [])),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.warning("暂无在岗巡检员")

    st.subheader("待分配任务")
    if pending_tasks:
        rows = []
        for t in pending_tasks:
            rows.append({
                "ID": t["id"],
                "任务类型": TASK_TYPE_MAP.get(t["task_type"], ""),
                "难度": DIFFICULTY_MAP.get(t["difficulty"], ""),
                "预计耗时(分钟)": t["estimated_minutes"],
                "片区": t.get("area", ""),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("暂无待分配任务")

    insp_ids = [i["id"] for i in inspectors]
    task_ids = [t["id"] for t in pending_tasks]

    if st.button("🚀 执行智能排班", type="primary", disabled=not insp_ids or not task_ids):
        with st.spinner("正在计算排班方案..."):
            code, resp = api_post("/api/schedule/daily", {
                "inspector_ids": insp_ids,
                "task_ids": task_ids,
            })
        if code == 200:
            st.success("排班完成！")
            assignments = resp.get("assignments", {})
            unassigned = resp.get("unassigned", [])

            st.subheader("分配方案")
            for insp_id, detail in assignments.items():
                insp_info = detail.get("inspector", {})
                tasks_list = detail.get("tasks", [])
                total_minutes = detail.get("total_minutes", 0)
                hours = total_minutes / 60

                with st.expander(
                    f"👤 {insp_info.get('name', '')} - "
                    f"{len(tasks_list)}个任务, 预计{hours:.1f}小时",
                    expanded=True,
                ):
                    st.markdown(
                        f"**技能等级**: {SKILL_MAP.get(insp_info.get('skill_level', ''), '')} | "
                        f"**负责片区**: {', '.join(insp_info.get('areas', []))}"
                    )
                    if tasks_list:
                        task_rows = []
                        for t in tasks_list:
                            task_rows.append({
                                "任务ID": t["id"],
                                "类型": TASK_TYPE_MAP.get(t["task_type"], ""),
                                "难度": DIFFICULTY_MAP.get(t["difficulty"], ""),
                                "耗时(分钟)": t["estimated_minutes"],
                                "片区": t.get("area", ""),
                            })
                        st.dataframe(pd.DataFrame(task_rows), hide_index=True)
                    else:
                        st.info("无分配任务")

            if unassigned:
                st.subheader("未能分配的任务")
                for u in unassigned:
                    task_info = u.get("task", {})
                    st.warning(
                        f"任务 #{task_info.get('id', '')} "
                        f"({TASK_TYPE_MAP.get(task_info.get('task_type', ''), '')}) - "
                        f"原因: {u.get('reason', '')}"
                    )
            st.rerun()
        else:
            st.error(resp.get("error", "排班失败"))

    st.divider()
    st.subheader("🗺️ 路线规划")

    all_inspectors = api_get("/api/inspectors") or []
    network_nodes = api_get("/api/network/nodes") or []

    route_insp_options = {
        f"{i['employee_id']} - {i['name']}": i["id"] for i in all_inspectors
    }
    sel_route_insp = st.selectbox(
        "选择巡检员", list(route_insp_options.keys()), key="route_insp"
    )

    node_ids = [n["id"] for n in network_nodes] if network_nodes else []
    start_node = st.selectbox(
        "起始节点",
        node_ids if node_ids else ["S1", "J1", "J2", "J3", "J4", "J5", "J6"],
        key="route_start",
    )

    if st.button("规划路线", key="plan_route_btn"):
        insp_id = route_insp_options[sel_route_insp]
        code, resp = api_post(f"/api/route/plan/inspector/{insp_id}", {
            "start_node_id": start_node,
        })
        if code == 200:
            st.success("路线规划完成！")
            route = resp.get("route", [])
            total_dist = resp.get("total_distance", 0)
            total_min = resp.get("total_estimated_minutes", 0)

            col1, col2 = st.columns(2)
            col1.metric("总路程(m)", f"{total_dist:.1f}")
            col2.metric("预计步行时间(分钟)", f"{total_min}")

            st.markdown("**巡检路线:**")
            st.markdown(" → ".join(route))

            route_tasks = resp.get("tasks", [])
            if route_tasks:
                st.markdown("**沿途任务:**")
                task_rows = []
                for t in route_tasks:
                    task_rows.append({
                        "任务ID": t["id"],
                        "类型": TASK_TYPE_MAP.get(t["task_type"], ""),
                        "耗时(分钟)": t["estimated_minutes"],
                        "目标节点": ", ".join(t.get("target_nodes", [])),
                    })
                st.dataframe(pd.DataFrame(task_rows), hide_index=True)
        else:
            st.error(resp.get("error", "路线规划失败"))


def page_anomalies():
    st.header("🚨 异常上报与管理")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filter_severity = st.selectbox(
            "按严重程度筛选",
            ["全部", "轻微", "一般", "严重", "紧急"],
            key="anom_filter_sev",
        )
    with col_f2:
        filter_status = st.selectbox(
            "按状态筛选",
            ["全部", "未处理", "处理中", "已解决", "已验收"],
            key="anom_filter_status",
        )

    params = {}
    if filter_severity != "全部":
        params["severity"] = SEVERITY_REV[filter_severity]
    if filter_status != "全部":
        params["status"] = next(
            (k for k, v in ANOMALY_STATUS_MAP.items() if v == filter_status), None
        )

    anomalies = api_get("/api/anomalies", params=params) or []

    if anomalies:
        rows = []
        for a in anomalies:
            rows.append({
                "ID": a["id"],
                "上报人": a.get("reporter_name", ""),
                "上报时间": a.get("report_time", "")[:19] if a.get("report_time") else "",
                "关联任务": a.get("task_id", ""),
                "异常类型": ANOMALY_TYPE_MAP.get(a["anomaly_type"], a["anomaly_type"]),
                "严重程度": SEVERITY_MAP.get(a["severity"], a["severity"]),
                "状态": ANOMALY_STATUS_MAP.get(a["status"], a["status"]),
                "描述": a.get("description", ""),
                "关联节点": a.get("related_node", ""),
                "关联管段": a.get("related_link", ""),
                "GPS": f"({a.get('gps_lat', '')}, {a.get('gps_lon', '')})" if a.get("gps_lat") else "",
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("暂无异常记录")

    st.subheader("上报异常")
    inspectors = api_get("/api/inspectors") or []
    tasks = api_get("/api/tasks") or []
    network_nodes = api_get("/api/network/nodes") or []
    network_links = api_get("/api/network/links") or []

    with st.form("create_anomaly_form"):
        ac1, ac2 = st.columns(2)
        with ac1:
            insp_options = {f"{i['employee_id']} - {i['name']}": i["id"] for i in inspectors}
            reporter = st.selectbox("上报人", list(insp_options.keys()))

            task_options = {f"#{t['id']} {TASK_TYPE_MAP.get(t['task_type'], '')}": t["id"] for t in tasks}
            rel_task = st.selectbox("关联任务(可选)", ["无"] + list(task_options.keys()))

            anom_type = st.selectbox("异常类型", list(ANOMALY_TYPE_REV.keys()))
            severity = st.selectbox("严重程度", list(SEVERITY_REV.keys()))

        with ac2:
            node_ids = [n["id"] for n in network_nodes] if network_nodes else []
            link_ids = [l["id"] for l in network_links] if network_links else []
            rel_node = st.selectbox("关联节点(可选)", ["无"] + node_ids, key="anom_node")
            rel_link = st.selectbox("关联管段(可选)", ["无"] + link_ids, key="anom_link")
            gps_lat = st.number_input("GPS纬度", value=0.0, format="%.6f")
            gps_lon = st.number_input("GPS经度", value=0.0, format="%.6f")

        anom_desc = st.text_area("现场描述")

        submitted = st.form_submit_button("上报异常")
        if submitted:
            data = {
                "reporter_id": insp_options[reporter],
                "anomaly_type": ANOMALY_TYPE_REV[anom_type],
                "severity": SEVERITY_REV[severity],
                "description": anom_desc,
                "gps_lat": gps_lat if gps_lat != 0.0 else None,
                "gps_lon": gps_lon if gps_lon != 0.0 else None,
            }
            if rel_task != "无":
                data["task_id"] = task_options[rel_task]
            if rel_node != "无":
                data["related_node"] = rel_node
            if rel_link != "无":
                data["related_link"] = rel_link

            code, resp = api_post("/api/anomalies", data)
            if code == 201:
                st.success("异常上报成功！")
                if resp.get("auto_task_id"):
                    st.warning(f"⚠️ 紧急异常已自动生成漏损排查任务 #{resp['auto_task_id']}")
                st.rerun()
            else:
                st.error(resp.get("error", "上报失败"))

    if anomalies:
        st.subheader("异常状态流转")
        anom_options = {
            f"#{a['id']} {ANOMALY_TYPE_MAP.get(a['anomaly_type'], '')} - "
            f"{ANOMALY_STATUS_MAP.get(a['status'], '')}": a
            for a in anomalies
        }
        sel_anom_key = st.selectbox("选择异常", list(anom_options.keys()), key="trans_anom")
        sel_anom = anom_options[sel_anom_key]

        current_status = sel_anom["status"]
        valid_next = {
            "unhandled": ["processing"],
            "processing": ["resolved"],
            "resolved": ["accepted"],
            "accepted": [],
        }.get(current_status, [])

        if not valid_next:
            st.info("当前异常状态无法继续流转")
        else:
            next_labels = [ANOMALY_STATUS_MAP.get(s, s) for s in valid_next]
            next_choice = st.selectbox("目标状态", next_labels, key="anom_next_status")
            next_status = valid_next[next_labels.index(next_choice)]

            if st.button("执行异常状态变更"):
                code, resp = api_post(
                    f"/api/anomalies/{sel_anom['id']}/transition",
                    {"status": next_status},
                )
                if code == 200:
                    st.success("状态变更成功")
                    st.rerun()
                else:
                    st.error(resp.get("error", "变更失败"))


def page_dashboard():
    st.header("📊 数据统计看板")

    data = api_get("/api/statistics/dashboard")

    if not data:
        st.warning("无法获取统计数据，请确认后端服务已启动")
        return

    st.subheader("1. 今日任务完成率")
    completion = data.get("today_completion", {})
    total = completion.get("total", 0)
    completed = completion.get("completed", 0)
    rate = completion.get("rate", 0)

    col1, col2, col3 = st.columns(3)
    col1.metric("今日总任务", total)
    col2.metric("已完成", completed)
    col3.metric("完成率", f"{rate * 100:.1f}%")

    if total > 0:
        fig_pie = px.pie(
            values=[completed, total - completed],
            names=["已完成", "未完成"],
            title="今日任务完成率",
            color=["已完成", "未完成"],
            color_discrete_map={"已完成": "#4CAF50", "未完成": "#FF9800"},
        )
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("今日暂无任务")

    st.subheader("2. 各巡检员工作量分布")
    workload = data.get("workload_distribution", [])
    if workload:
        df_workload = pd.DataFrame(workload)
        fig_bar = px.bar(
            df_workload,
            x="inspector_name",
            y="total_minutes",
            title="各巡检员今日工作量(分钟)",
            color="task_count",
            labels={"inspector_name": "巡检员", "total_minutes": "工作量(分钟)", "task_count": "任务数"},
        )
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("暂无工作量数据")

    st.subheader("3. 本周异常趋势")
    trend = data.get("anomaly_trend", {})
    if trend:
        dates = list(trend.keys())
        counts = list(trend.values())
        fig_line = go.Figure()
        fig_line.add_trace(go.Scatter(
            x=dates, y=counts, mode="lines+markers",
            name="异常数量", line=dict(color="#F44336", width=2),
        ))
        fig_line.update_layout(
            title="本周异常趋势(按天统计)",
            xaxis_title="日期", yaxis_title="异常数量",
        )
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.info("暂无异常趋势数据")

    st.subheader("4. 各片区异常热力图")
    area_count = data.get("area_anomaly_count", {})
    if area_count:
        df_area = pd.DataFrame([
            {"片区": k, "异常次数": v} for k, v in area_count.items()
        ])
        fig_area = px.bar(
            df_area, x="片区", y="异常次数",
            title="各片区异常次数",
            color="异常次数",
            color_continuous_scale="Reds",
        )
        st.plotly_chart(fig_area, use_container_width=True)
    else:
        st.info("暂无片区异常数据")

    st.subheader("5. 巡检员绩效排名")
    ranking = data.get("inspector_ranking", [])
    if ranking:
        df_rank = pd.DataFrame(ranking)
        df_rank["排名"] = range(1, len(df_rank) + 1)
        df_rank = df_rank[["排名", "inspector_name", "completed_tasks", "found_anomalies", "score"]]
        df_rank.columns = ["排名", "姓名", "完成任务数", "发现异常数", "绩效得分"]
        st.dataframe(df_rank, use_container_width=True, hide_index=True)
    else:
        st.info("暂无绩效数据")


def page_trajectory():
    st.header("🗺️ 巡检轨迹回放与偏差检测")

    tasks = api_get("/api/tasks") or []
    completed_tasks = [t for t in tasks if t["status"] in ["completed", "anomaly", "in_progress"]]
    if not completed_tasks:
        st.info("暂无可查看轨迹的任务")
        return

    task_options = {
        f"#{t['id']} {TASK_TYPE_MAP.get(t['task_type'], '')} - {TASK_STATUS_MAP.get(t['status'], '')}": t["id"]
        for t in completed_tasks
    }
    sel_task_key = st.selectbox("选择任务", list(task_options.keys()), key="traj_task_sel")
    sel_task_id = task_options[sel_task_key]

    col1, col2 = st.columns(2)
    with col1:
        if st.button("加载轨迹数据", key="load_traj_btn"):
            st.session_state["traj_task_id"] = sel_task_id
    with col2:
        if st.button("上报模拟轨迹点", key="simulate_traj_btn"):
            import random
            lat_base, lon_base = 30.0, 120.0
            for i in range(10):
                lat = lat_base + random.uniform(-0.01, 0.01)
                lon = lon_base + random.uniform(-0.01, 0.01)
                ts = datetime.now().isoformat()
                api_post("/api/trajectories", {
                    "task_id": sel_task_id,
                    "gps_lat": lat,
                    "gps_lon": lon,
                    "timestamp": ts,
                })
            st.success("已模拟上报10个轨迹点")
            st.session_state["traj_task_id"] = sel_task_id

    if "traj_task_id" not in st.session_state or st.session_state["traj_task_id"] != sel_task_id:
        return

    trajectory = api_get("/api/trajectories", params={"task_id": sel_task_id}) or []
    if not trajectory:
        st.warning("该任务暂无轨迹数据，请先上报轨迹点")
        return

    deviation = api_get(f"/api/trajectories/{sel_task_id}/deviation")
    planned = api_get(f"/api/trajectories/planned-route/{sel_task_id}")

    st.subheader("轨迹偏差分析")
    if deviation:
        col_d1, col_d2, col_d3, col_d4 = st.columns(4)
        col_d1.metric("总轨迹点数", deviation.get("total_points", 0))
        col_d2.metric("偏离点数", deviation.get("deviation_points", 0))
        col_d3.metric("偏离率", f"{deviation.get('deviation_rate', 0)}%")
        col_d4.metric("路线异常", "⚠️ 是" if deviation.get("route_anomaly") else "✅ 否")
        if deviation.get("route_anomaly"):
            st.error("⚠️ 偏离率超过20%，该任务标记为路线异常")

    st.subheader("轨迹可视化")
    fig = go.Figure()

    if planned and planned.get("coords"):
        planned_lats = [c["x"] for c in planned["coords"]]
        planned_lons = [c["y"] for c in planned["coords"]]
        fig.add_trace(go.Scatter(
            x=planned_lons, y=planned_lats,
            mode="lines+markers",
            name="规划路线",
            line=dict(color="blue", width=3),
            marker=dict(symbol="square", size=10),
        ))

    actual_lats = [p["gps_lat"] for p in trajectory]
    actual_lons = [p["gps_lon"] for p in trajectory]
    fig.add_trace(go.Scatter(
        x=actual_lons, y=actual_lats,
        mode="lines+markers",
        name="实际轨迹",
        line=dict(color="green", width=2),
        marker=dict(size=6),
    ))

    if deviation and deviation.get("points_detail"):
        dev_points = [p for p in deviation["points_detail"] if p.get("is_deviation")]
        if dev_points:
            fig.add_trace(go.Scatter(
                x=[p["gps_lon"] for p in dev_points],
                y=[p["gps_lat"] for p in dev_points],
                mode="markers",
                name="偏离点",
                marker=dict(color="red", size=12, symbol="x"),
            ))

    fig.update_layout(
        title="巡检轨迹回放 (蓝=规划路线, 绿=实际轨迹, 红=偏离点)",
        xaxis_title="Y坐标/经度",
        yaxis_title="X坐标/纬度",
        height=500,
    )
    st.plotly_chart(fig, use_container_width=True)

    if deviation and deviation.get("points_detail"):
        st.subheader("偏差详情")
        detail_rows = []
        for p in deviation["points_detail"]:
            detail_rows.append({
                "轨迹点ID": p["id"],
                "纬度": p["gps_lat"],
                "经度": p["gps_lon"],
                "时间": p.get("timestamp", "")[:19] if p.get("timestamp") else "",
                "距规划路线(m)": p.get("distance_to_route", 0),
                "是否偏离": "🔴 是" if p.get("is_deviation") else "否",
            })
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)


def page_report():
    st.header("📄 巡检报告自动生成")

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_date = st.date_input("开始日期", value=datetime.now().replace(day=1), key="report_start")
    with col_d2:
        end_date = st.date_input("结束日期", value=datetime.now(), key="report_end")

    if st.button("生成报告", type="primary", key="gen_report_btn"):
        with st.spinner("正在生成报告..."):
            report = api_get("/api/reports/generate", params={
                "start_date": str(start_date),
                "end_date": str(end_date),
            })

        if not report:
            st.error("报告生成失败，请确认后端服务已启动")
            return

        st.session_state["report_data"] = report

    if "report_data" not in st.session_state:
        return

    report = st.session_state["report_data"]

    st.subheader("1. 巡检概况")
    overview = report.get("overview", {})
    col_o1, col_o2, col_o3, col_o4 = st.columns(4)
    col_o1.metric("总任务数", overview.get("total_tasks", 0))
    col_o2.metric("完成数", overview.get("completed_tasks", 0))
    col_o3.metric("异常数", overview.get("anomaly_tasks", 0))
    col_o4.metric("完成率", f"{overview.get('completion_rate', 0)}%")

    if overview.get("total_tasks", 0) > 0:
        fig_ov = px.pie(
            values=[
                overview.get("completed_tasks", 0),
                overview.get("anomaly_tasks", 0),
                max(0, overview.get("total_tasks", 0) - overview.get("completed_tasks", 0) - overview.get("anomaly_tasks", 0)),
            ],
            names=["已完成", "异常", "其他"],
            title="任务完成概况",
            color=["已完成", "异常", "其他"],
            color_discrete_map={"已完成": "#4CAF50", "异常": "#F44336", "其他": "#FF9800"},
        )
        st.plotly_chart(fig_ov, use_container_width=True)

    st.subheader("2. 巡检员工作量明细")
    workload = report.get("inspector_workload", [])
    if workload:
        df_wl = pd.DataFrame(workload)
        df_wl_display = df_wl.rename(columns={
            "inspector_name": "姓名",
            "completed_tasks": "完成任务数",
            "found_anomalies": "发现异常数",
            "total_inspection_minutes": "总巡检时长(分钟)",
            "avg_minutes_per_task": "平均每任务耗时(分钟)",
        })
        st.dataframe(df_wl_display[["姓名", "完成任务数", "发现异常数", "总巡检时长(分钟)", "平均每任务耗时(分钟)"]],
                     use_container_width=True, hide_index=True)

        fig_wl = px.bar(
            df_wl, x="inspector_name", y=["completed_tasks", "found_anomalies"],
            title="各巡检员工作量对比",
            barmode="group",
            labels={"inspector_name": "巡检员", "value": "数量"},
        )
        st.plotly_chart(fig_wl, use_container_width=True)
    else:
        st.info("暂无工作量数据")

    st.subheader("3. 异常统计")
    anomaly_stats = report.get("anomaly_stats", {})

    col_as1, col_as2, col_as3 = st.columns(3)
    with col_as1:
        by_type = anomaly_stats.get("by_type", {})
        if by_type:
            df_type = pd.DataFrame([{"异常类型": ANOMALY_TYPE_MAP.get(k, k), "数量": v} for k, v in by_type.items()])
            fig_type = px.pie(df_type, values="数量", names="异常类型", title="按类型分组")
            st.plotly_chart(fig_type, use_container_width=True)
        else:
            st.info("按类型: 暂无数据")

    with col_as2:
        by_severity = anomaly_stats.get("by_severity", {})
        if by_severity:
            df_sev = pd.DataFrame([{"严重程度": SEVERITY_MAP.get(k, k), "数量": v} for k, v in by_severity.items()])
            fig_sev = px.pie(df_sev, values="数量", names="严重程度", title="按严重程度分组")
            st.plotly_chart(fig_sev, use_container_width=True)
        else:
            st.info("按严重程度: 暂无数据")

    with col_as3:
        by_area = anomaly_stats.get("by_area", {})
        if by_area:
            df_area = pd.DataFrame([{"片区": k, "数量": v} for k, v in by_area.items()])
            fig_area = px.pie(df_area, values="数量", names="片区", title="按片区分组")
            st.plotly_chart(fig_area, use_container_width=True)
        else:
            st.info("按片区: 暂无数据")

    st.subheader("4. 轨迹合规分析")
    compliance = report.get("trajectory_compliance", [])
    route_anomaly = report.get("route_anomaly_tasks", [])
    if compliance:
        df_comp = pd.DataFrame(compliance)
        df_comp_display = df_comp.rename(columns={
            "task_id": "任务ID",
            "task_type": "任务类型",
            "inspector_name": "巡检员",
            "deviation_rate": "偏离率(%)",
            "route_anomaly": "路线异常",
        })
        df_comp_display["任务类型"] = df_comp_display["任务类型"].map(lambda x: TASK_TYPE_MAP.get(x, x))
        df_comp_display["路线异常"] = df_comp_display["路线异常"].map(lambda x: "⚠️ 是" if x else "否")
        st.dataframe(df_comp_display, use_container_width=True, hide_index=True)
    else:
        st.info("暂无轨迹合规数据")

    if route_anomaly:
        st.subheader("⚠️ 路线异常任务列表")
        for ra in route_anomaly:
            st.error(
                f"任务 #{ra['task_id']} ({TASK_TYPE_MAP.get(ra['task_type'], '')}) - "
                f"巡检员: {ra.get('inspector_name', '未知')} - 偏离率: {ra.get('deviation_rate', 0)}%"
            )

    st.subheader("导出PDF")
    if st.button("📄 导出报告为PDF", key="export_pdf_btn"):
        try:
            from fpdf import FPDF

            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            pdf.cell(200, 10, txt="Inspection Report", ln=True, align="C")
            pdf.ln(5)

            ov = report.get("overview", {})
            pdf.cell(200, 10, txt=f"Period: {ov.get('start_date', '')} ~ {ov.get('end_date', '')}", ln=True)
            pdf.cell(200, 10, txt=f"Total Tasks: {ov.get('total_tasks', 0)}", ln=True)
            pdf.cell(200, 10, txt=f"Completed: {ov.get('completed_tasks', 0)}", ln=True)
            pdf.cell(200, 10, txt=f"Anomaly: {ov.get('anomaly_tasks', 0)}", ln=True)
            pdf.cell(200, 10, txt=f"Completion Rate: {ov.get('completion_rate', 0)}%", ln=True)
            pdf.ln(5)

            wl = report.get("inspector_workload", [])
            if wl:
                pdf.cell(200, 10, txt="Inspector Workload:", ln=True)
                for w in wl:
                    line = f"  {w.get('inspector_name', '')}: Completed={w.get('completed_tasks', 0)}, Anomalies={w.get('found_anomalies', 0)}, Minutes={w.get('total_inspection_minutes', 0)}"
                    pdf.cell(200, 8, txt=line, ln=True)

            comp = report.get("trajectory_compliance", [])
            if comp:
                pdf.ln(3)
                pdf.cell(200, 10, txt="Trajectory Compliance:", ln=True)
                for c in comp:
                    line = f"  Task#{c['task_id']}: DevRate={c.get('deviation_rate', 0)}%, Anomaly={'Yes' if c.get('route_anomaly') else 'No'}"
                    pdf.cell(200, 8, txt=line, ln=True)

            pdf_output = pdf.output(dest="S")
            st.download_button(
                label="下载PDF文件",
                data=bytes(pdf_output),
                file_name=f"inspection_report_{start_date}_{end_date}.pdf",
                mime="application/pdf",
            )
        except ImportError:
            st.warning("PDF导出需要安装fpdf2库，正在尝试安装...")
            import subprocess
            subprocess.run(["pip", "install", "fpdf2"], capture_output=True)
            st.info("已安装fpdf2，请再次点击导出按钮")


def page_alerts():
    st.header("🔔 告警与消息推送")

    tab_rules, tab_records = st.tabs(["告警规则配置", "告警记录"])

    with tab_rules:
        st.subheader("已有告警规则")
        rules = api_get("/api/alert-rules") or []
        if rules:
            rule_rows = []
            for r in rules:
                cond = r.get("condition_json", {}) if isinstance(r.get("condition_json"), dict) else {}
                rule_rows.append({
                    "ID": r["id"],
                    "规则名称": r["name"],
                    "触发条件类型": cond.get("type", ""),
                    "告警级别": ALERT_LEVEL_MAP.get(r["level"], r["level"]),
                    "通知方式": r.get("notify_method", ""),
                    "启用": "✅" if r.get("enabled") else "❌",
                })
            st.dataframe(pd.DataFrame(rule_rows), use_container_width=True, hide_index=True)
        else:
            st.info("暂无告警规则")

        st.subheader("添加告警规则")
        with st.form("add_alert_rule_form"):
            ar_name = st.text_input("规则名称")
            ar_type = st.selectbox("触发条件类型", [
                "area_consecutive_anomaly",
                "inspector_overtime",
                "urgent_unhandled",
            ])
            ar_params_col1, ar_params_col2 = st.columns(2)
            with ar_params_col1:
                if ar_type == "area_consecutive_anomaly":
                    ar_area = st.text_input("片区", value="DMA-1")
                    ar_days = st.number_input("连续天数", min_value=1, value=3)
                elif ar_type == "inspector_overtime":
                    ar_hours = st.number_input("工作时长上限(小时)", min_value=1, value=10)
                elif ar_type == "urgent_unhandled":
                    ar_urgent_hours = st.number_input("未处理时长上限(小时)", min_value=1, value=2)
            with ar_params_col2:
                if ar_type == "area_consecutive_anomaly":
                    ar_threshold = st.number_input("异常数阈值", min_value=1, value=5)

            ar_level = st.selectbox("告警级别", ["提示", "警告", "严重"])
            ar_enabled = st.checkbox("启用规则", value=True)

            submitted = st.form_submit_button("添加规则")
            if submitted:
                if not ar_name:
                    st.error("规则名称为必填项")
                else:
                    cond = {"type": ar_type}
                    if ar_type == "area_consecutive_anomaly":
                        cond["area"] = ar_area
                        cond["days"] = ar_days
                        cond["threshold"] = ar_threshold
                    elif ar_type == "inspector_overtime":
                        cond["hours"] = ar_hours
                    elif ar_type == "urgent_unhandled":
                        cond["hours"] = ar_urgent_hours

                    code, resp = api_post("/api/alert-rules", {
                        "name": ar_name,
                        "condition_json": cond,
                        "level": ALERT_LEVEL_REV[ar_level],
                        "notify_method": "site_message",
                        "enabled": ar_enabled,
                    })
                    if code == 201:
                        st.success("告警规则添加成功")
                        st.rerun()
                    else:
                        st.error(resp.get("error", "添加失败"))

        if rules:
            st.subheader("删除告警规则")
            del_rule_id = st.selectbox("选择规则ID", [r["id"] for r in rules], key="del_rule_sel")
            if st.button("删除选中规则", key="del_rule_btn"):
                code, resp = api_delete(f"/api/alert-rules/{del_rule_id}")
                if code == 200:
                    st.success("删除成功")
                    st.rerun()
                else:
                    st.error(resp.get("error", "删除失败"))

        st.divider()
        st.subheader("执行告警检查")
        if st.button("🔍 手动执行告警检查", type="primary", key="check_alerts_btn"):
            with st.spinner("正在检查告警规则..."):
                code, resp = api_post("/api/alerts/check")
            if code == 200:
                count = resp.get("generated_count", 0)
                if count > 0:
                    st.warning(f"触发了 {count} 条告警！")
                    for a in resp.get("alerts", []):
                        level_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(a.get("level", ""), "ℹ️")
                        st.error(f"{level_emoji} [{ALERT_LEVEL_MAP.get(a.get('level', ''), '')}] {a.get('content', '')}")
                else:
                    st.success("✅ 当前无告警触发")
            else:
                st.error("告警检查执行失败")

    with tab_records:
        st.subheader("告警记录")
        col_af1, col_af2 = st.columns(2)
        with col_af1:
            filter_status = st.selectbox("状态筛选", ["全部", "未读", "已读"], key="alert_filter_status")
        with col_af2:
            filter_level = st.selectbox("级别筛选", ["全部", "提示", "警告", "严重"], key="alert_filter_level")

        params = {}
        if filter_status != "全部":
            params["status"] = "unread" if filter_status == "未读" else "read"
        if filter_level != "全部":
            params["level"] = ALERT_LEVEL_REV[filter_level]

        records = api_get("/api/alerts/records", params=params) or []
        if records:
            rec_rows = []
            for r in records:
                level_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(r.get("level", ""), "ℹ️")
                rec_rows.append({
                    "ID": r["id"],
                    "告警时间": r.get("alert_time", "")[:19] if r.get("alert_time") else "",
                    "规则名称": r.get("rule_name", ""),
                    "告警内容": r.get("content", ""),
                    "级别": f"{level_emoji} {ALERT_LEVEL_MAP.get(r.get('level', ''), '')}",
                    "状态": ALERT_STATUS_MAP.get(r.get("status", ""), ""),
                })
            st.dataframe(pd.DataFrame(rec_rows), use_container_width=True, hide_index=True)

            unread_records = [r for r in records if r.get("status") == "unread"]
            if unread_records:
                st.subheader("确认已读")
                sel_rec = st.selectbox(
                    "选择告警记录",
                    [f"#{r['id']} {r.get('content', '')[:30]}" for r in unread_records],
                    key="mark_read_sel",
                )
                sel_rec_id = unread_records[[f"#{r['id']} {r.get('content', '')[:30]}" for r in unread_records].index(sel_rec)]["id"]
                if st.button("确认已读", key="mark_read_btn"):
                    code, resp = api_put(f"/api/alerts/records/{sel_rec_id}/read")
                    if code == 200:
                        st.success("已标记为已读")
                        st.rerun()
                    else:
                        st.error(resp.get("error", "操作失败"))
        else:
            st.info("暂无告警记录")


def page_certifications():
    st.header("🎓 巡检员技能认证与培训记录")

    inspectors = api_get("/api/inspectors") or []
    if not inspectors:
        st.info("暂无巡检员数据")
        return

    insp_options = {f"{i['employee_id']} - {i['name']} ({SKILL_MAP.get(i['skill_level'], '')})": i["id"] for i in inspectors}
    sel_insp_key = st.selectbox("选择巡检员", list(insp_options.keys()), key="cert_insp_sel")
    sel_insp_id = insp_options[sel_insp_key]

    cert_status = api_get(f"/api/inspectors/{sel_insp_id}/cert-status")
    certs = api_get("/api/certificates", params={"inspector_id": sel_insp_id}) or []
    trainings = api_get("/api/training-records", params={"inspector_id": sel_insp_id}) or []

    st.subheader("证书信息")
    if cert_status and cert_status.get("certificates"):
        cert_rows = []
        for c in cert_status["certificates"]:
            status = c.get("status", "valid")
            status_label = CERT_STATUS_MAP.get(status, status)
            if status == "expired":
                status_display = f"🔴 {status_label}"
            elif status == "expiring_soon":
                status_display = f"🟡 {status_label}"
            else:
                status_display = f"🟢 {status_label}"
            cert_rows.append({
                "证书ID": c["id"],
                "证书名称": c["cert_name"],
                "发证机构": c.get("issuer", ""),
                "有效期至": c["valid_until"],
                "状态": status_display,
            })
        st.dataframe(pd.DataFrame(cert_rows), use_container_width=True, hide_index=True)
    else:
        st.info("该巡检员暂无证书信息")

    st.subheader("添加证书")
    with st.form("add_cert_form"):
        cc1, cc2 = st.columns(2)
        with cc1:
            cert_name = st.text_input("证书名称")
            cert_issuer = st.text_input("发证机构")
        with cc2:
            cert_valid = st.date_input("有效期至", value=datetime.now())
        submitted = st.form_submit_button("添加证书")
        if submitted:
            if not cert_name:
                st.error("证书名称为必填项")
            else:
                code, resp = api_post("/api/certificates", {
                    "inspector_id": sel_insp_id,
                    "cert_name": cert_name,
                    "issuer": cert_issuer,
                    "valid_until": str(cert_valid),
                })
                if code == 201:
                    st.success("证书添加成功")
                    st.rerun()
                else:
                    st.error(resp.get("error", "添加失败"))

    st.divider()
    st.subheader("培训记录")
    if trainings:
        train_rows = []
        for t in trainings:
            result_label = TRAINING_RESULT_MAP.get(t["result"], t["result"])
            result_display = f"✅ {result_label}" if t["result"] == "pass" else f"❌ {result_label}"
            train_rows.append({
                "培训ID": t["id"],
                "培训名称": t["training_name"],
                "培训日期": t["training_date"],
                "时长(小时)": t["duration_hours"],
                "考核结果": result_display,
            })
        st.dataframe(pd.DataFrame(train_rows), use_container_width=True, hide_index=True)
    else:
        st.info("该巡检员暂无培训记录")

    st.subheader("添加培训记录")
    with st.form("add_training_form"):
        tc1, tc2 = st.columns(2)
        with tc1:
            train_name = st.text_input("培训名称")
            train_date = st.date_input("培训日期", value=datetime.now())
        with tc2:
            train_duration = st.number_input("时长(小时)", min_value=0.5, value=4.0, step=0.5)
            train_result = st.selectbox("考核结果", ["合格", "不合格"])
        submitted = st.form_submit_button("添加培训记录")
        if submitted:
            if not train_name:
                st.error("培训名称为必填项")
            else:
                code, resp = api_post("/api/training-records", {
                    "inspector_id": sel_insp_id,
                    "training_name": train_name,
                    "training_date": str(train_date),
                    "duration_hours": train_duration,
                    "result": "pass" if train_result == "合格" else "fail",
                })
                if code == 201:
                    st.success("培训记录添加成功")
                    st.rerun()
                else:
                    st.error(resp.get("error", "添加失败"))

    st.divider()
    if cert_status:
        st.subheader("技能等级与降级状态")
        current_level = SKILL_MAP.get(cert_status.get("skill_level", ""), "")
        has_expired = any(c.get("status") == "expired" for c in cert_status.get("certificates", []))
        st.markdown(f"**当前技能等级**: {current_level}")
        if has_expired:
            st.error("⚠️ 存在过期证书，该巡检员已自动降级！证书过期巡检员不会被分配超出当前技能等级的任务。")
        has_expiring = any(c.get("status") == "expiring_soon" for c in cert_status.get("certificates", []))
        if has_expiring:
            st.warning("⚠️ 存在30天内即将过期的证书，请及时续证！")


def main():
    st.set_page_config(page_title="管网巡检任务调度系统", layout="wide")
    st.title("🔧 管网巡检任务调度系统")

    page = st.sidebar.selectbox(
        "功能模块",
        [
            "👷 巡检员管理", "📋 任务管理", "📅 智能排班与路线",
            "🚨 异常上报", "📊 统计看板",
            "🗺️ 轨迹回放", "📄 巡检报告",
            "🔔 告警管理", "🎓 认证与培训",
        ],
    )

    if page == "👷 巡检员管理":
        page_inspectors()
    elif page == "📋 任务管理":
        page_tasks()
    elif page == "📅 智能排班与路线":
        page_scheduling()
    elif page == "🚨 异常上报":
        page_anomalies()
    elif page == "📊 统计看板":
        page_dashboard()
    elif page == "🗺️ 轨迹回放":
        page_trajectory()
    elif page == "📄 巡检报告":
        page_report()
    elif page == "🔔 告警管理":
        page_alerts()
    elif page == "🎓 认证与培训":
        page_certifications()

    st.sidebar.divider()
    st.sidebar.markdown(f"后端地址: `{API_BASE}`")
    st.sidebar.markdown("管网巡检任务调度模块 v2.0")


if __name__ == "__main__":
    main()
