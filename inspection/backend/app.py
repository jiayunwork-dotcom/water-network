import json
import math as _math
import os
import sys
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
from flask_cors import CORS

from models import db, Inspector, Task, Anomaly, NetworkData, TrackPoint, AlertRule, AlertRecord, Certificate, TrainingRecord
from scheduler import daily_schedule
from route_planner import plan_route

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "inspection.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

CORS(app)
db.init_app(app)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)


def _error(message, code=400):
    return jsonify({"error": message, "code": code}), code


# ============================================================
# Inspector CRUD
# ============================================================

@app.route("/api/inspectors", methods=["GET"])
def list_inspectors():
    query = Inspector.query
    area = request.args.get("area")
    status = request.args.get("status")
    skill = request.args.get("skill_level")
    if area:
        query = query.filter(Inspector.areas.contains(area))
    if status:
        query = query.filter(Inspector.status == status)
    if skill:
        query = query.filter(Inspector.skill_level == skill)
    inspectors = query.all()
    return jsonify([i.to_dict() for i in inspectors])


@app.route("/api/inspectors", methods=["POST"])
def create_inspector():
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    employee_id = data.get("employee_id")
    name = data.get("name")
    if not employee_id or not name:
        return _error("工号和姓名为必填项")
    if Inspector.query.filter_by(employee_id=employee_id).first():
        return _error(f"工号 {employee_id} 已存在")
    valid_skills = [Inspector.SKILL_JUNIOR, Inspector.SKILL_INTERMEDIATE, Inspector.SKILL_SENIOR]
    skill_level = data.get("skill_level", Inspector.SKILL_JUNIOR)
    if skill_level not in valid_skills:
        return _error(f"技能等级必须是 {valid_skills} 之一")
    valid_statuses = [Inspector.STATUS_ON_DUTY, Inspector.STATUS_OFF, Inspector.STATUS_OUT]
    status = data.get("status", Inspector.STATUS_ON_DUTY)
    if status not in valid_statuses:
        return _error(f"状态必须是 {valid_statuses} 之一")
    areas_list = data.get("areas", [])
    areas_str = ",".join(areas_list) if isinstance(areas_list, list) else str(areas_list)
    insp = Inspector(
        employee_id=employee_id,
        name=name,
        phone=data.get("phone", ""),
        skill_level=skill_level,
        areas=areas_str,
        status=status,
    )
    db.session.add(insp)
    db.session.commit()
    return jsonify(insp.to_dict()), 201


@app.route("/api/inspectors/<int:insp_id>", methods=["GET"])
def get_inspector(insp_id):
    insp = Inspector.query.get(insp_id)
    if not insp:
        return _error("巡检员不存在", 404)
    return jsonify(insp.to_dict())


@app.route("/api/inspectors/<int:insp_id>", methods=["PUT"])
def update_inspector(insp_id):
    insp = Inspector.query.get(insp_id)
    if not insp:
        return _error("巡检员不存在", 404)
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    if "employee_id" in data:
        existing = Inspector.query.filter_by(employee_id=data["employee_id"]).first()
        if existing and existing.id != insp_id:
            return _error(f"工号 {data['employee_id']} 已被其他巡检员使用")
        insp.employee_id = data["employee_id"]
    if "name" in data:
        insp.name = data["name"]
    if "phone" in data:
        insp.phone = data["phone"]
    if "skill_level" in data:
        valid = [Inspector.SKILL_JUNIOR, Inspector.SKILL_INTERMEDIATE, Inspector.SKILL_SENIOR]
        if data["skill_level"] not in valid:
            return _error(f"技能等级必须是 {valid} 之一")
        insp.skill_level = data["skill_level"]
    if "areas" in data:
        areas_list = data["areas"]
        insp.areas = ",".join(areas_list) if isinstance(areas_list, list) else str(areas_list)
    if "status" in data:
        valid = [Inspector.STATUS_ON_DUTY, Inspector.STATUS_OFF, Inspector.STATUS_OUT]
        if data["status"] not in valid:
            return _error(f"状态必须是 {valid} 之一")
        insp.status = data["status"]
    db.session.commit()
    return jsonify(insp.to_dict())


@app.route("/api/inspectors/<int:insp_id>", methods=["DELETE"])
def delete_inspector(insp_id):
    insp = Inspector.query.get(insp_id)
    if not insp:
        return _error("巡检员不存在", 404)
    assigned = Task.query.filter_by(inspector_id=insp_id).filter(
        Task.status.in_([Task.STATUS_ASSIGNED, Task.STATUS_IN_PROGRESS])
    ).first()
    if assigned:
        return _error("该巡检员有进行中的任务，无法删除")
    db.session.delete(insp)
    db.session.commit()
    return jsonify({"message": "删除成功"})


# ============================================================
# Task CRUD & Status Transition
# ============================================================

@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    query = Task.query
    task_type = request.args.get("task_type")
    status = request.args.get("status")
    difficulty = request.args.get("difficulty")
    area = request.args.get("area")
    date = request.args.get("scheduled_date")
    if task_type:
        query = query.filter(Task.task_type == task_type)
    if status:
        query = query.filter(Task.status == status)
    if difficulty:
        query = query.filter(Task.difficulty == difficulty)
    if area:
        query = query.filter(Task.area == area)
    if date:
        query = query.filter(Task.scheduled_date == date)
    tasks = query.order_by(Task.created_at.desc()).all()
    return jsonify([t.to_dict() for t in tasks])


@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    task_type = data.get("task_type")
    if not task_type:
        return _error("任务类型为必填项")
    valid_types = [Task.TYPE_DAILY, Task.TYPE_VALVE, Task.TYPE_LEAK, Task.TYPE_QUALITY]
    if task_type not in valid_types:
        return _error(f"任务类型必须是 {valid_types} 之一")
    valid_diff = [Task.DIFFICULTY_EASY, Task.DIFFICULTY_MEDIUM, Task.DIFFICULTY_HARD]
    difficulty = data.get("difficulty", Task.DIFFICULTY_EASY)
    if difficulty not in valid_diff:
        return _error(f"难度等级必须是 {valid_diff} 之一")
    nodes_list = data.get("target_nodes", [])
    links_list = data.get("target_links", [])
    insp_id = data.get("inspector_id")
    initial_status = Task.STATUS_PENDING
    if insp_id:
        insp = Inspector.query.get(insp_id)
        if not insp:
            return _error(f"巡检员 {insp_id} 不存在")
        initial_status = Task.STATUS_ASSIGNED
    task = Task(
        task_type=task_type,
        difficulty=difficulty,
        estimated_minutes=data.get("estimated_minutes", 30),
        status=initial_status,
        inspector_id=insp_id,
        area=data.get("area", ""),
        target_nodes=",".join(nodes_list) if isinstance(nodes_list, list) else "",
        target_links=",".join(links_list) if isinstance(links_list, list) else "",
        description=data.get("description", ""),
        scheduled_date=data.get("scheduled_date", ""),
    )
    db.session.add(task)
    db.session.commit()
    return jsonify(task.to_dict()), 201


@app.route("/api/tasks/<int:task_id>", methods=["GET"])
def get_task(task_id):
    task = Task.query.get(task_id)
    if not task:
        return _error("任务不存在", 404)
    return jsonify(task.to_dict())


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def update_task(task_id):
    task = Task.query.get(task_id)
    if not task:
        return _error("任务不存在", 404)
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    if "task_type" in data:
        valid = [Task.TYPE_DAILY, Task.TYPE_VALVE, Task.TYPE_LEAK, Task.TYPE_QUALITY]
        if data["task_type"] not in valid:
            return _error(f"任务类型必须是 {valid} 之一")
        task.task_type = data["task_type"]
    if "difficulty" in data:
        valid = [Task.DIFFICULTY_EASY, Task.DIFFICULTY_MEDIUM, Task.DIFFICULTY_HARD]
        if data["difficulty"] not in valid:
            return _error(f"难度等级必须是 {valid} 之一")
        task.difficulty = data["difficulty"]
    if "estimated_minutes" in data:
        task.estimated_minutes = data["estimated_minutes"]
    if "area" in data:
        task.area = data["area"]
    if "target_nodes" in data:
        nodes_list = data["target_nodes"]
        task.target_nodes = ",".join(nodes_list) if isinstance(nodes_list, list) else ""
    if "target_links" in data:
        links_list = data["target_links"]
        task.target_links = ",".join(links_list) if isinstance(links_list, list) else ""
    if "description" in data:
        task.description = data["description"]
    if "scheduled_date" in data:
        task.scheduled_date = data["scheduled_date"]
    if "inspector_id" in data:
        new_insp_id = data["inspector_id"]
        if new_insp_id:
            insp = Inspector.query.get(new_insp_id)
            if not insp:
                return _error(f"巡检员 {new_insp_id} 不存在")
            task.inspector_id = new_insp_id
            if task.status == Task.STATUS_PENDING:
                task.status = Task.STATUS_ASSIGNED
        else:
            task.inspector_id = None
            if task.status in [Task.STATUS_ASSIGNED]:
                task.status = Task.STATUS_PENDING
    db.session.commit()
    return jsonify(task.to_dict())


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    task = Task.query.get(task_id)
    if not task:
        return _error("任务不存在", 404)
    if task.status in [Task.STATUS_ASSIGNED, Task.STATUS_IN_PROGRESS]:
        return _error("已分配或进行中的任务不能删除")
    db.session.delete(task)
    db.session.commit()
    return jsonify({"message": "删除成功"})


@app.route("/api/tasks/<int:task_id>/transition", methods=["POST"])
def transition_task(task_id):
    task = Task.query.get(task_id)
    if not task:
        return _error("任务不存在", 404)
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    new_status = data.get("status")
    if not new_status:
        return _error("目标状态为必填项")
    valid_transitions = Task.VALID_TRANSITIONS.get(task.status, [])
    if new_status not in valid_transitions:
        return _error(
            f"任务状态不能从 '{task.status}' 跳转到 '{new_status}'，"
            f"允许的转换: {valid_transitions}"
        )
    task.status = new_status
    if new_status == Task.STATUS_ASSIGNED:
        insp_id = data.get("inspector_id")
        if not insp_id:
            return _error("分配任务时必须指定巡检员(inspector_id)")
        insp = Inspector.query.get(insp_id)
        if not insp:
            return _error(f"巡检员 {insp_id} 不存在")
        task.inspector_id = insp_id
    if new_status == Task.STATUS_IN_PROGRESS and not task.inspector_id:
        return _error("进行中的任务必须指定巡检员")
    if new_status == Task.STATUS_PENDING:
        task.inspector_id = None
    db.session.commit()
    return jsonify(task.to_dict())


# ============================================================
# Scheduling
# ============================================================

@app.route("/api/schedule/daily", methods=["POST"])
def schedule_daily():
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    inspector_ids = data.get("inspector_ids", [])
    task_ids = data.get("task_ids", [])
    if not inspector_ids:
        return _error("巡检员列表不能为空")
    if not task_ids:
        return _error("待分配任务列表不能为空")
    result = daily_schedule(inspector_ids, task_ids)

    assignments = result["assignments"]
    for insp_id, tids in assignments.items():
        if not insp_id:
            continue
        insp = Inspector.query.get(insp_id)
        if not insp:
            continue
        for tid in tids:
            task = Task.query.get(tid)
            if task and task.status == Task.STATUS_PENDING:
                task.inspector_id = insp_id
                task.status = Task.STATUS_ASSIGNED
    db.session.commit()

    detailed_assignments = {}
    for insp_id, tids in assignments.items():
        insp = Inspector.query.get(insp_id)
        tasks_list = []
        total_minutes = 0
        for tid in tids:
            t = Task.query.get(tid)
            if t:
                tasks_list.append(t.to_dict())
                total_minutes += t.estimated_minutes
        detailed_assignments[insp_id] = {
            "inspector": insp.to_dict() if insp else None,
            "tasks": tasks_list,
            "total_minutes": total_minutes,
        }

    unassigned_details = []
    for u in result["unassigned"]:
        t = Task.query.get(u["task_id"])
        unassigned_details.append({
            "task": t.to_dict() if t else None,
            "reason": u["reason"],
        })

    return jsonify({
        "assignments": detailed_assignments,
        "unassigned": unassigned_details,
    })


# ============================================================
# Route Planning
# ============================================================

@app.route("/api/route/plan", methods=["POST"])
def route_plan():
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    start_node = data.get("start_node_id")
    if not start_node:
        return _error("起始节点ID为必填项")
    target_nodes = data.get("target_node_ids", [])
    target_links = data.get("target_link_ids", [])
    result = plan_route(start_node, target_nodes, target_links)
    if "error" in result:
        return _error(result["error"], result.get("code", 404))
    return jsonify(result)


@app.route("/api/route/plan/inspector/<int:insp_id>", methods=["POST"])
def route_plan_for_inspector(insp_id):
    insp = Inspector.query.get(insp_id)
    if not insp:
        return _error("巡检员不存在", 404)
    data = request.get_json() or {}
    date = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    tasks = Task.query.filter_by(inspector_id=insp_id, scheduled_date=date).all()
    if not tasks:
        tasks = Task.query.filter_by(inspector_id=insp_id).filter(
            Task.status.in_([Task.STATUS_ASSIGNED, Task.STATUS_IN_PROGRESS])
        ).all()
    if not tasks:
        return _error("该巡检员无已分配任务")
    all_target_nodes = []
    all_target_links = []
    for t in tasks:
        if t.target_nodes:
            all_target_nodes.extend(t.target_nodes.split(","))
        if t.target_links:
            all_target_links.extend(t.target_links.split(","))
    all_target_nodes = list(set(filter(None, all_target_nodes)))
    all_target_links = list(set(filter(None, all_target_links)))
    start_node = data.get("start_node_id") or (all_target_nodes[0] if all_target_nodes else None)
    if not start_node:
        return _error("未指定起始节点且无法从任务中推断")
    result = plan_route(start_node, all_target_nodes, all_target_links)
    if "error" in result:
        return _error(result["error"], result.get("code", 404))
    result["inspector_id"] = insp_id
    result["inspector_name"] = insp.name
    result["tasks"] = [t.to_dict() for t in tasks]
    return jsonify(result)


# ============================================================
# Anomaly CRUD & Auto-task
# ============================================================

@app.route("/api/anomalies", methods=["GET"])
def list_anomalies():
    query = Anomaly.query
    severity = request.args.get("severity")
    status = request.args.get("status")
    anomaly_type = request.args.get("anomaly_type")
    if severity:
        query = query.filter(Anomaly.severity == severity)
    if status:
        query = query.filter(Anomaly.status == status)
    if anomaly_type:
        query = query.filter(Anomaly.anomaly_type == anomaly_type)
    anomalies = query.order_by(Anomaly.report_time.desc()).all()
    return jsonify([a.to_dict() for a in anomalies])


@app.route("/api/anomalies", methods=["POST"])
def create_anomaly():
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    anomaly_type = data.get("anomaly_type")
    severity = data.get("severity")
    if not anomaly_type:
        return _error("异常类型为必填项")
    if not severity:
        return _error("严重程度为必填项")
    valid_types = [
        Anomaly.TYPE_PIPE_BREAK, Anomaly.TYPE_VALVE_STUCK,
        Anomaly.TYPE_METER_ABNORMAL, Anomaly.TYPE_QUALITY_EXCEED, Anomaly.TYPE_OTHER,
    ]
    if anomaly_type not in valid_types:
        return _error(f"异常类型必须是 {valid_types} 之一")
    valid_sev = [Anomaly.SEVERITY_MINOR, Anomaly.SEVERITY_NORMAL, Anomaly.SEVERITY_SERIOUS, Anomaly.SEVERITY_URGENT]
    if severity not in valid_sev:
        return _error(f"严重程度必须是 {valid_sev} 之一")
    anomaly = Anomaly(
        reporter_id=data.get("reporter_id"),
        task_id=data.get("task_id"),
        anomaly_type=anomaly_type,
        severity=severity,
        description=data.get("description", ""),
        gps_lat=data.get("gps_lat"),
        gps_lon=data.get("gps_lon"),
        related_node=data.get("related_node"),
        related_link=data.get("related_link"),
        status=Anomaly.STATUS_UNHANDLED,
    )
    db.session.add(anomaly)
    db.session.flush()

    if severity == Anomaly.SEVERITY_URGENT:
        senior = Inspector.query.filter_by(
            skill_level=Inspector.SKILL_SENIOR,
            status=Inspector.STATUS_ON_DUTY,
        ).first()
        auto_task = Task(
            task_type=Task.TYPE_LEAK,
            difficulty=Task.DIFFICULTY_HARD,
            estimated_minutes=120,
            status=Task.STATUS_ASSIGNED if senior else Task.STATUS_PENDING,
            inspector_id=senior.id if senior else None,
            area="",
            target_nodes=data.get("related_node", ""),
            target_links=data.get("related_link", ""),
            description=f"紧急异常自动生成: {anomaly_type}",
            scheduled_date=datetime.now().strftime("%Y-%m-%d"),
        )
        db.session.add(auto_task)
        db.session.flush()
        anomaly.auto_task_id = auto_task.id

    db.session.commit()
    return jsonify(anomaly.to_dict()), 201


@app.route("/api/anomalies/<int:anomaly_id>", methods=["GET"])
def get_anomaly(anomaly_id):
    anomaly = Anomaly.query.get(anomaly_id)
    if not anomaly:
        return _error("异常记录不存在", 404)
    return jsonify(anomaly.to_dict())


@app.route("/api/anomalies/<int:anomaly_id>", methods=["PUT"])
def update_anomaly(anomaly_id):
    anomaly = Anomaly.query.get(anomaly_id)
    if not anomaly:
        return _error("异常记录不存在", 404)
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    if "description" in data:
        anomaly.description = data["description"]
    if "severity" in data:
        valid = [Anomaly.SEVERITY_MINOR, Anomaly.SEVERITY_NORMAL, Anomaly.SEVERITY_SERIOUS, Anomaly.SEVERITY_URGENT]
        if data["severity"] not in valid:
            return _error(f"严重程度必须是 {valid} 之一")
        anomaly.severity = data["severity"]
    if "anomaly_type" in data:
        anomaly.anomaly_type = data["anomaly_type"]
    if "gps_lat" in data:
        anomaly.gps_lat = data["gps_lat"]
    if "gps_lon" in data:
        anomaly.gps_lon = data["gps_lon"]
    if "related_node" in data:
        anomaly.related_node = data["related_node"]
    if "related_link" in data:
        anomaly.related_link = data["related_link"]
    db.session.commit()
    return jsonify(anomaly.to_dict())


@app.route("/api/anomalies/<int:anomaly_id>/transition", methods=["POST"])
def transition_anomaly(anomaly_id):
    anomaly = Anomaly.query.get(anomaly_id)
    if not anomaly:
        return _error("异常记录不存在", 404)
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    new_status = data.get("status")
    if not new_status:
        return _error("目标状态为必填项")
    valid_transitions = Anomaly.ANOMALY_VALID_TRANSITIONS.get(anomaly.status, [])
    if new_status not in valid_transitions:
        return _error(
            f"异常状态不能从 '{anomaly.status}' 跳转到 '{new_status}'，"
            f"允许的转换: {valid_transitions}"
        )
    anomaly.status = new_status
    db.session.commit()
    return jsonify(anomaly.to_dict())


# ============================================================
# Network Data (for route planning)
# ============================================================

@app.route("/api/network", methods=["GET"])
def get_network():
    net = NetworkData.query.first()
    if not net:
        return _error("未找到管网数据", 404)
    return jsonify(net.to_dict())


@app.route("/api/network", methods=["POST"])
def save_network():
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    nodes = data.get("nodes", {})
    links = data.get("links", {})
    net = NetworkData.query.first()
    if net:
        net.nodes_json = json.dumps(nodes, ensure_ascii=False)
        net.links_json = json.dumps(links, ensure_ascii=False)
        net.updated_at = datetime.utcnow()
    else:
        net = NetworkData(
            name=data.get("name", "default"),
            nodes_json=json.dumps(nodes, ensure_ascii=False),
            links_json=json.dumps(links, ensure_ascii=False),
        )
        db.session.add(net)
    db.session.commit()
    return jsonify(net.to_dict())


# ============================================================
# Statistics
# ============================================================

@app.route("/api/statistics/dashboard", methods=["GET"])
def dashboard():
    today = datetime.now().strftime("%Y-%m-%d")

    total_tasks_today = Task.query.filter(
        Task.scheduled_date == today
    ).count()
    completed_today = Task.query.filter(
        Task.scheduled_date == today,
        Task.status == Task.STATUS_COMPLETED
    ).count()

    all_inspectors = Inspector.query.all()
    workload_data = []
    for insp in all_inspectors:
        task_count = Task.query.filter(
            Task.inspector_id == insp.id,
            Task.scheduled_date == today
        ).count()
        total_minutes = 0
        tasks = Task.query.filter(
            Task.inspector_id == insp.id,
            Task.scheduled_date == today
        ).all()
        for t in tasks:
            total_minutes += t.estimated_minutes
        workload_data.append({
            "inspector_id": insp.id,
            "inspector_name": insp.name,
            "task_count": task_count,
            "total_minutes": total_minutes,
        })

    week_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    all_anomalies = Anomaly.query.filter(
        db.func.date(Anomaly.report_time) >= week_ago
    ).all()
    anomaly_trend = {}
    for i in range(7):
        d = (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%d")
        anomaly_trend[d] = 0
    for a in all_anomalies:
        d = a.report_time.strftime("%Y-%m-%d") if a.report_time else None
        if d and d in anomaly_trend:
            anomaly_trend[d] += 1

    area_anomaly_count = {}
    all_anoms = Anomaly.query.all()
    for a in all_anoms:
        if a.task_id:
            t = Task.query.get(a.task_id)
            if t and t.area:
                area_anomaly_count[t.area] = area_anomaly_count.get(t.area, 0) + 1
        if a.related_node or a.related_link:
            area_name = "未知片区"
            if a.related_node:
                node_parts = a.related_node.split("_")
                if len(node_parts) > 1:
                    area_name = node_parts[0]
            area_anomaly_count[area_name] = area_anomaly_count.get(area_name, 0) + 1

    inspector_stats = []
    for insp in all_inspectors:
        completed = Task.query.filter(
            Task.inspector_id == insp.id,
            Task.status == Task.STATUS_COMPLETED
        ).count()
        found_anomalies = Anomaly.query.filter_by(reporter_id=insp.id).count()
        score = completed * 1.0 + found_anomalies * 0.5
        inspector_stats.append({
            "inspector_id": insp.id,
            "inspector_name": insp.name,
            "completed_tasks": completed,
            "found_anomalies": found_anomalies,
            "score": score,
        })
    inspector_stats.sort(key=lambda x: x["score"], reverse=True)

    return jsonify({
        "today_completion": {
            "total": total_tasks_today,
            "completed": completed_today,
            "rate": round(completed_today / total_tasks_today, 4) if total_tasks_today > 0 else 0,
        },
        "workload_distribution": workload_data,
        "anomaly_trend": anomaly_trend,
        "area_anomaly_count": area_anomaly_count,
        "inspector_ranking": inspector_stats,
    })


# ============================================================
# DMA Zones (for area selection)
# ============================================================

@app.route("/api/dma/zones", methods=["GET"])
def list_dma_zones():
    net = NetworkData.query.first()
    if not net:
        return jsonify([])
    nodes = json.loads(net.nodes_json) if net.nodes_json else {}
    zones = set()
    for nid, node_data in nodes.items():
        zone = node_data.get("dma_zone", "") if isinstance(node_data, dict) else ""
        if zone:
            zones.add(zone)
    return jsonify(sorted(list(zones)))


# ============================================================
# Network Nodes/Links (for target selection)
# ============================================================

@app.route("/api/network/nodes", methods=["GET"])
def list_network_nodes():
    net = NetworkData.query.first()
    if not net:
        return jsonify([])
    nodes = json.loads(net.nodes_json) if net.nodes_json else {}
    result = []
    for nid, ndata in nodes.items():
        if isinstance(ndata, dict):
            result.append({
                "id": nid,
                "type": ndata.get("type", "junction"),
                "dma_zone": ndata.get("dma_zone", ""),
                "x": ndata.get("x", 0),
                "y": ndata.get("y", 0),
            })
        else:
            result.append({"id": nid})
    return jsonify(result)


@app.route("/api/network/links", methods=["GET"])
def list_network_links():
    net = NetworkData.query.first()
    if not net:
        return jsonify([])
    links = json.loads(net.links_json) if net.links_json else {}
    result = []
    for lid, ldata in links.items():
        if isinstance(ldata, dict):
            result.append({
                "id": lid,
                "type": ldata.get("type", "pipe"),
                "start_node": ldata.get("start_node", ldata.get("start", "")),
                "end_node": ldata.get("end_node", ldata.get("end", "")),
                "length": ldata.get("length", 0),
            })
        else:
            result.append({"id": lid})
    return jsonify(result)




def _haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = _math.radians(lat1), _math.radians(lat2)
    dphi = _math.radians(lat2 - lat1)
    dlam = _math.radians(lon2 - lon1)
    a = _math.sin(dphi / 2) ** 2 + _math.cos(phi1) * _math.cos(phi2) * _math.sin(dlam / 2) ** 2
    return R * 2 * _math.atan2(_math.sqrt(a), _math.sqrt(1 - a))


def _point_to_segment_distance(lat, lon, lat1, lon1, lat2, lon2):
    dx, dy = lon2 - lon1, lat2 - lat1
    if dx == 0 and dy == 0:
        return _haversine(lat, lon, lat1, lon1)
    t = max(0, min(1, ((lon - lon1) * dx + (lat - lat1) * dy) / (dx * dx + dy * dy)))
    proj_lon = lon1 + t * dx
    proj_lat = lat1 + t * dy
    return _haversine(lat, lon, proj_lat, proj_lon)


# ============================================================
# Trajectory Tracking & Deviation Detection
# ============================================================

@app.route("/api/trajectories", methods=["POST"])
def record_track_point():
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    task_id = data.get("task_id")
    gps_lat = data.get("gps_lat")
    gps_lon = data.get("gps_lon")
    if not task_id:
        return _error("任务ID为必填项")
    if gps_lat is None or gps_lon is None:
        return _error("GPS坐标为必填项")
    task = Task.query.get(task_id)
    if not task:
        return _error("任务不存在", 404)
    ts = data.get("timestamp")
    if ts:
        try:
            timestamp = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            timestamp = datetime.utcnow()
    else:
        timestamp = datetime.utcnow()
    point = TrackPoint(
        task_id=task_id,
        gps_lat=float(gps_lat),
        gps_lon=float(gps_lon),
        timestamp=timestamp,
    )
    db.session.add(point)
    db.session.commit()
    return jsonify(point.to_dict()), 201


@app.route("/api/trajectories", methods=["GET"])
def get_trajectory():
    task_id = request.args.get("task_id")
    if not task_id:
        return _error("task_id参数为必填项")
    points = TrackPoint.query.filter_by(task_id=task_id).order_by(TrackPoint.timestamp.asc()).all()
    return jsonify([p.to_dict() for p in points])


@app.route("/api/trajectories/<int:task_id>/deviation", methods=["GET"])
def get_trajectory_deviation(task_id):
    task = Task.query.get(task_id)
    if not task:
        return _error("任务不存在", 404)
    points = TrackPoint.query.filter_by(task_id=task_id).order_by(TrackPoint.timestamp.asc()).all()
    if not points:
        return jsonify({"task_id": task_id, "total_points": 0, "deviation_points": 0, "deviation_rate": 0.0, "route_anomaly": False, "points_detail": []})
    net = NetworkData.query.first()
    planned_coords = []
    if net:
        nodes = json.loads(net.nodes_json) if net.nodes_json else {}
        route_result = plan_route(
            list(nodes.keys())[0] if nodes else "S1",
            task.target_nodes.split(",") if task.target_nodes else [],
            task.target_links.split(",") if task.target_links else [],
        )
        if "route" in route_result:
            for nid in route_result["route"]:
                nd = nodes.get(nid, {})
                if isinstance(nd, dict) and "x" in nd and "y" in nd:
                    planned_coords.append((nd.get("x", 0), nd.get("y", 0)))
    deviation_threshold = 50
    points_detail = []
    deviation_count = 0
    for pt in points:
        min_dist = float("inf")
        if planned_coords:
            for i in range(len(planned_coords) - 1):
                lat1, lon1 = planned_coords[i]
                lat2, lon2 = planned_coords[i + 1]
                d = _point_to_segment_distance(pt.gps_lat, pt.gps_lon, lat1, lon1, lat2, lon2)
                if d < min_dist:
                    min_dist = d
            for pc in planned_coords:
                d = _haversine(pt.gps_lat, pt.gps_lon, pc[0], pc[1])
                if d < min_dist:
                    min_dist = d
        else:
            min_dist = 0
        is_deviation = min_dist > deviation_threshold
        if is_deviation:
            deviation_count += 1
        points_detail.append({
            "id": pt.id,
            "gps_lat": pt.gps_lat,
            "gps_lon": pt.gps_lon,
            "timestamp": pt.timestamp.isoformat() if pt.timestamp else None,
            "distance_to_route": round(min_dist, 2),
            "is_deviation": is_deviation,
        })
    total = len(points)
    deviation_rate = round(deviation_count / total * 100, 2) if total > 0 else 0.0
    route_anomaly = deviation_rate > 20
    return jsonify({
        "task_id": task_id,
        "total_points": total,
        "deviation_points": deviation_count,
        "deviation_rate": deviation_rate,
        "deviation_threshold": deviation_threshold,
        "route_anomaly": route_anomaly,
        "points_detail": points_detail,
    })


@app.route("/api/trajectories/planned-route/<int:task_id>", methods=["GET"])
def get_planned_route_coords(task_id):
    task = Task.query.get(task_id)
    if not task:
        return _error("任务不存在", 404)
    net = NetworkData.query.first()
    if not net:
        return jsonify({"route": [], "coords": []})
    nodes = json.loads(net.nodes_json) if net.nodes_json else {}
    start = list(nodes.keys())[0] if nodes else "S1"
    target_nodes = task.target_nodes.split(",") if task.target_nodes else []
    target_links = task.target_links.split(",") if task.target_links else []
    target_nodes = [n for n in target_nodes if n]
    target_links = [l for l in target_links if l]
    route_result = plan_route(start, target_nodes, target_links)
    route = route_result.get("route", [])
    coords = []
    for nid in route:
        nd = nodes.get(nid, {})
        if isinstance(nd, dict):
            coords.append({"node_id": nid, "x": nd.get("x", 0), "y": nd.get("y", 0)})
    return jsonify({"route": route, "coords": coords})


# ============================================================
# Inspection Report Generation
# ============================================================

@app.route("/api/reports/generate", methods=["GET"])
def generate_report():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if not start_date or not end_date:
        return _error("start_date和end_date参数为必填项")
    tasks_in_range = Task.query.filter(
        Task.scheduled_date >= start_date,
        Task.scheduled_date <= end_date,
    ).all()
    total_tasks = len(tasks_in_range)
    completed_tasks = len([t for t in tasks_in_range if t.status == Task.STATUS_COMPLETED])
    anomaly_tasks = len([t for t in tasks_in_range if t.status == Task.STATUS_ANOMALY])
    completion_rate = round(completed_tasks / total_tasks * 100, 2) if total_tasks > 0 else 0.0
    overview = {
        "start_date": start_date,
        "end_date": end_date,
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "anomaly_tasks": anomaly_tasks,
        "completion_rate": completion_rate,
    }
    inspector_ids = set(t.inspector_id for t in tasks_in_range if t.inspector_id)
    inspector_workload = []
    for iid in inspector_ids:
        insp = Inspector.query.get(iid)
        if not insp:
            continue
        insp_tasks = [t for t in tasks_in_range if t.inspector_id == iid]
        insp_completed = len([t for t in insp_tasks if t.status == Task.STATUS_COMPLETED])
        insp_anomalies = Anomaly.query.filter(
            Anomaly.reporter_id == iid,
            db.func.date(Anomaly.report_time) >= start_date,
            db.func.date(Anomaly.report_time) <= end_date,
        ).count()
        total_minutes = sum(t.estimated_minutes for t in insp_tasks)
        avg_minutes = round(total_minutes / insp_completed, 2) if insp_completed > 0 else 0
        inspector_workload.append({
            "inspector_id": iid,
            "inspector_name": insp.name,
            "completed_tasks": insp_completed,
            "found_anomalies": insp_anomalies,
            "total_inspection_minutes": total_minutes,
            "avg_minutes_per_task": avg_minutes,
        })
    anomalies_in_range = Anomaly.query.filter(
        db.func.date(Anomaly.report_time) >= start_date,
        db.func.date(Anomaly.report_time) <= end_date,
    ).all()
    by_type = {}
    for a in anomalies_in_range:
        by_type[a.anomaly_type] = by_type.get(a.anomaly_type, 0) + 1
    by_severity = {}
    for a in anomalies_in_range:
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
    by_area = {}
    for a in anomalies_in_range:
        area = "未知"
        if a.task_id:
            t = Task.query.get(a.task_id)
            if t and t.area:
                area = t.area
        by_area[area] = by_area.get(area, 0) + 1
    anomaly_stats = {
        "by_type": by_type,
        "by_severity": by_severity,
        "by_area": by_area,
    }
    trajectory_compliance = []
    route_anomaly_tasks = []
    for t in tasks_in_range:
        if t.status not in [Task.STATUS_COMPLETED, Task.STATUS_ANOMALY]:
            continue
        pt_count = TrackPoint.query.filter_by(task_id=t.id).count()
        if pt_count == 0:
            continue
        dev_result = get_trajectory_deviation(t.id)
        dev_data = dev_result[0].get_json() if isinstance(dev_result, tuple) else dev_result.get_json()
        entry = {
            "task_id": t.id,
            "task_type": t.task_type,
            "inspector_name": t.inspector.name if t.inspector else None,
            "deviation_rate": dev_data.get("deviation_rate", 0),
            "route_anomaly": dev_data.get("route_anomaly", False),
        }
        trajectory_compliance.append(entry)
        if dev_data.get("route_anomaly", False):
            route_anomaly_tasks.append(entry)
    return jsonify({
        "overview": overview,
        "inspector_workload": inspector_workload,
        "anomaly_stats": anomaly_stats,
        "trajectory_compliance": trajectory_compliance,
        "route_anomaly_tasks": route_anomaly_tasks,
    })


# ============================================================
# Alert Rules & Records
# ============================================================

@app.route("/api/alert-rules", methods=["GET"])
def list_alert_rules():
    rules = AlertRule.query.order_by(AlertRule.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rules])


@app.route("/api/alert-rules", methods=["POST"])
def create_alert_rule():
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    name = data.get("name")
    condition_json = data.get("condition_json")
    if not name:
        return _error("规则名称为必填项")
    if not condition_json:
        return _error("触发条件为必填项")
    level = data.get("level", AlertRule.LEVEL_INFO)
    valid_levels = [AlertRule.LEVEL_INFO, AlertRule.LEVEL_WARNING, AlertRule.LEVEL_CRITICAL]
    if level not in valid_levels:
        return _error(f"告警级别必须是 {valid_levels} 之一")
    rule = AlertRule(
        name=name,
        condition_json=json.dumps(condition_json, ensure_ascii=False) if isinstance(condition_json, dict) else str(condition_json),
        level=level,
        notify_method=data.get("notify_method", "site_message"),
        enabled=data.get("enabled", True),
    )
    db.session.add(rule)
    db.session.commit()
    return jsonify(rule.to_dict()), 201


@app.route("/api/alert-rules/<int:rule_id>", methods=["PUT"])
def update_alert_rule(rule_id):
    rule = AlertRule.query.get(rule_id)
    if not rule:
        return _error("告警规则不存在", 404)
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    if "name" in data:
        rule.name = data["name"]
    if "condition_json" in data:
        cj = data["condition_json"]
        rule.condition_json = json.dumps(cj, ensure_ascii=False) if isinstance(cj, dict) else str(cj)
    if "level" in data:
        valid = [AlertRule.LEVEL_INFO, AlertRule.LEVEL_WARNING, AlertRule.LEVEL_CRITICAL]
        if data["level"] not in valid:
            return _error(f"告警级别必须是 {valid} 之一")
        rule.level = data["level"]
    if "notify_method" in data:
        rule.notify_method = data["notify_method"]
    if "enabled" in data:
        rule.enabled = data["enabled"]
    db.session.commit()
    return jsonify(rule.to_dict())


@app.route("/api/alert-rules/<int:rule_id>", methods=["DELETE"])
def delete_alert_rule(rule_id):
    rule = AlertRule.query.get(rule_id)
    if not rule:
        return _error("告警规则不存在", 404)
    AlertRecord.query.filter_by(rule_id=rule_id).delete()
    db.session.delete(rule)
    db.session.commit()
    return jsonify({"message": "删除成功"})


@app.route("/api/alerts/check", methods=["POST"])
def execute_alert_check():
    rules = AlertRule.query.filter_by(enabled=True).all()
    now = datetime.utcnow()
    generated = []
    for rule in rules:
        try:
            cond = json.loads(rule.condition_json) if isinstance(rule.condition_json, str) else rule.condition_json
        except (json.JSONDecodeError, TypeError):
            continue
        rule_type = cond.get("type")
        triggered = False
        content = ""
        if rule_type == "area_consecutive_anomaly":
            area = cond.get("area", "")
            days = cond.get("days", 3)
            threshold = cond.get("threshold", 5)
            for d in range(days):
                check_date = (now - timedelta(days=d)).strftime("%Y-%m-%d")
                count = 0
                anomalies_day = Anomaly.query.filter(
                    db.func.date(Anomaly.report_time) == check_date
                ).all()
                for a in anomalies_day:
                    if a.task_id:
                        t = Task.query.get(a.task_id)
                        if t and t.area == area:
                            count += 1
                if count <= threshold:
                    break
            else:
                triggered = True
                content = f"片区 {area} 连续 {days} 天异常数超过 {threshold}"
        elif rule_type == "inspector_overtime":
            hours_limit = cond.get("hours", 10)
            today_str = now.strftime("%Y-%m-%d")
            inspectors = Inspector.query.filter_by(status=Inspector.STATUS_ON_DUTY).all()
            for insp in inspectors:
                today_tasks = Task.query.filter(
                    Task.inspector_id == insp.id,
                    Task.scheduled_date == today_str,
                ).all()
                total_min = sum(t.estimated_minutes for t in today_tasks)
                if total_min > hours_limit * 60:
                    triggered = True
                    content = f"巡检员 {insp.name} 当日工作时长超过 {hours_limit} 小时(当前: {round(total_min/60, 1)}小时)"
                    break
        elif rule_type == "urgent_unhandled":
            hours_limit = cond.get("hours", 2)
            cutoff = now - timedelta(hours=hours_limit)
            urgent_unhandled = Anomaly.query.filter(
                Anomaly.severity == Anomaly.SEVERITY_URGENT,
                Anomaly.status == Anomaly.STATUS_UNHANDLED,
                Anomaly.report_time <= cutoff,
            ).first()
            if urgent_unhandled:
                triggered = True
                content = f"紧急异常 #{urgent_unhandled.id} 未处理已超过 {hours_limit} 小时"
        if triggered:
            record = AlertRecord(
                rule_id=rule.id,
                alert_time=now,
                content=content,
                level=rule.level,
                status=AlertRecord.STATUS_UNREAD,
            )
            db.session.add(record)
            generated.append(record.to_dict())
    db.session.commit()
    return jsonify({"generated_count": len(generated), "alerts": generated})


@app.route("/api/alerts/records", methods=["GET"])
def list_alert_records():
    query = AlertRecord.query
    status = request.args.get("status")
    level = request.args.get("level")
    if status:
        query = query.filter(AlertRecord.status == status)
    if level:
        query = query.filter(AlertRecord.level == level)
    records = query.order_by(AlertRecord.alert_time.desc()).all()
    return jsonify([r.to_dict() for r in records])


@app.route("/api/alerts/records/<int:record_id>/read", methods=["PUT"])
def mark_alert_read(record_id):
    record = AlertRecord.query.get(record_id)
    if not record:
        return _error("告警记录不存在", 404)
    record.status = AlertRecord.STATUS_READ
    db.session.commit()
    return jsonify(record.to_dict())


# ============================================================
# Certificates & Training Records
# ============================================================

@app.route("/api/certificates", methods=["GET"])
def list_certificates():
    insp_id = request.args.get("inspector_id")
    query = Certificate.query
    if insp_id:
        query = query.filter_by(inspector_id=insp_id)
    certs = query.order_by(Certificate.valid_until.asc()).all()
    return jsonify([c.to_dict() for c in certs])


@app.route("/api/certificates", methods=["POST"])
def create_certificate():
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    insp_id = data.get("inspector_id")
    cert_name = data.get("cert_name")
    valid_until = data.get("valid_until")
    if not insp_id or not cert_name or not valid_until:
        return _error("巡检员ID、证书名称、有效期为必填项")
    insp = Inspector.query.get(insp_id)
    if not insp:
        return _error("巡检员不存在", 404)
    cert = Certificate(
        inspector_id=insp_id,
        cert_name=cert_name,
        issuer=data.get("issuer", ""),
        valid_until=valid_until,
    )
    db.session.add(cert)
    db.session.commit()
    _check_and_downgrade(insp_id)
    return jsonify(cert.to_dict()), 201


@app.route("/api/certificates/<int:cert_id>", methods=["DELETE"])
def delete_certificate(cert_id):
    cert = Certificate.query.get(cert_id)
    if not cert:
        return _error("证书不存在", 404)
    insp_id = cert.inspector_id
    db.session.delete(cert)
    db.session.commit()
    _check_and_downgrade(insp_id)
    return jsonify({"message": "删除成功"})


@app.route("/api/training-records", methods=["GET"])
def list_training_records():
    insp_id = request.args.get("inspector_id")
    query = TrainingRecord.query
    if insp_id:
        query = query.filter_by(inspector_id=int(insp_id))
    records = query.order_by(TrainingRecord.training_date.desc()).all()
    return jsonify([r.to_dict() for r in records])


@app.route("/api/training-records", methods=["POST"])
def create_training_record():
    data = request.get_json()
    if not data:
        return _error("请求体不能为空")
    insp_id = data.get("inspector_id")
    training_name = data.get("training_name")
    training_date = data.get("training_date")
    if not insp_id or not training_name or not training_date:
        return _error("巡检员ID、培训名称、培训日期为必填项")
    insp = Inspector.query.get(insp_id)
    if not insp:
        return _error("巡检员不存在", 404)
    result_val = data.get("result", TrainingRecord.RESULT_FAIL)
    if result_val not in [TrainingRecord.RESULT_PASS, TrainingRecord.RESULT_FAIL]:
        return _error("考核结果必须是 pass 或 fail")
    record = TrainingRecord(
        inspector_id=insp_id,
        training_name=training_name,
        training_date=training_date,
        duration_hours=data.get("duration_hours", 0.0),
        result=result_val,
    )
    db.session.add(record)
    db.session.commit()
    return jsonify(record.to_dict()), 201


def _check_and_downgrade(inspector_id):
    insp = Inspector.query.get(inspector_id)
    if not insp:
        return
    certs = Certificate.query.filter_by(inspector_id=inspector_id).all()
    today_str = datetime.now().strftime("%Y-%m-%d")
    has_expired = any(c.valid_until < today_str for c in certs)
    if has_expired:
        if insp.skill_level == Inspector.SKILL_SENIOR:
            insp.skill_level = Inspector.SKILL_INTERMEDIATE
        elif insp.skill_level == Inspector.SKILL_INTERMEDIATE:
            insp.skill_level = Inspector.SKILL_JUNIOR
    db.session.commit()


@app.route("/api/inspectors/<int:insp_id>/cert-status", methods=["GET"])
def get_inspector_cert_status(insp_id):
    insp = Inspector.query.get(insp_id)
    if not insp:
        return _error("巡检员不存在", 404)
    certs = Certificate.query.filter_by(inspector_id=insp_id).all()
    today_str = datetime.now().strftime("%Y-%m-%d")
    soon_str = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    cert_status_list = []
    for c in certs:
        status = "valid"
        if c.valid_until < today_str:
            status = "expired"
        elif c.valid_until < soon_str:
            status = "expiring_soon"
        cert_status_list.append({
            "id": c.id,
            "cert_name": c.cert_name,
            "issuer": c.issuer,
            "valid_until": c.valid_until,
            "status": status,
        })
    return jsonify({
        "inspector_id": insp_id,
        "skill_level": insp.skill_level,
        "certificates": cert_status_list,
    })


# ============================================================
# Init DB & seed data
# ============================================================

def init_db_and_seed():
    db.create_all()
    if Inspector.query.count() == 0:
        seed_inspectors = [
            Inspector(employee_id="INS001", name="张伟", phone="13800001111",
                      skill_level=Inspector.SKILL_SENIOR, areas="DMA-1,DMA-2",
                      status=Inspector.STATUS_ON_DUTY),
            Inspector(employee_id="INS002", name="李明", phone="13800002222",
                      skill_level=Inspector.SKILL_INTERMEDIATE, areas="DMA-1,DMA-3",
                      status=Inspector.STATUS_ON_DUTY),
            Inspector(employee_id="INS003", name="王芳", phone="13800003333",
                      skill_level=Inspector.SKILL_JUNIOR, areas="DMA-2",
                      status=Inspector.STATUS_ON_DUTY),
            Inspector(employee_id="INS004", name="赵强", phone="13800004444",
                      skill_level=Inspector.SKILL_SENIOR, areas="DMA-3,DMA-4",
                      status=Inspector.STATUS_ON_DUTY),
            Inspector(employee_id="INS005", name="陈静", phone="13800005555",
                      skill_level=Inspector.SKILL_INTERMEDIATE, areas="DMA-2,DMA-4",
                      status=Inspector.STATUS_OFF),
        ]
        db.session.add_all(seed_inspectors)
    if Task.query.count() == 0:
        today = datetime.now().strftime("%Y-%m-%d")
        seed_tasks = [
            Task(task_type=Task.TYPE_DAILY, difficulty=Task.DIFFICULTY_EASY,
                 estimated_minutes=90, area="DMA-1", scheduled_date=today,
                 target_nodes="J1,J2,J4", target_links="P1,P2,P4",
                 description="DMA-1片区日常巡检"),
            Task(task_type=Task.TYPE_DAILY, difficulty=Task.DIFFICULTY_EASY,
                 estimated_minutes=60, area="DMA-2", scheduled_date=today,
                 target_nodes="J3,J6", target_links="P3,P7",
                 description="DMA-2片区日常巡检"),
            Task(task_type=Task.TYPE_VALVE, difficulty=Task.DIFFICULTY_MEDIUM,
                 estimated_minutes=120, area="DMA-1", scheduled_date=today,
                 target_links="P1,P2",
                 description="DMA-1阀门检修"),
            Task(task_type=Task.TYPE_LEAK, difficulty=Task.DIFFICULTY_HARD,
                 estimated_minutes=180, area="DMA-3", scheduled_date=today,
                 target_nodes="J5", target_links="P6",
                 description="DMA-3漏损排查"),
            Task(task_type=Task.TYPE_QUALITY, difficulty=Task.DIFFICULTY_EASY,
                 estimated_minutes=45, area="DMA-2", scheduled_date=today,
                 target_nodes="J4", description="水质取样"),
        ]
        db.session.add_all(seed_tasks)
    if NetworkData.query.count() == 0:
        demo_nodes = {
            "S1": {"type": "source", "x": 100, "y": 300, "elevation": 50, "head": 80},
            "J1": {"type": "junction", "x": 300, "y": 300, "elevation": 45, "demand": 20, "dma_zone": "DMA-1"},
            "J2": {"type": "junction", "x": 500, "y": 200, "elevation": 42, "demand": 15, "dma_zone": "DMA-1"},
            "J3": {"type": "junction", "x": 500, "y": 400, "elevation": 43, "demand": 25, "dma_zone": "DMA-2"},
            "J4": {"type": "junction", "x": 700, "y": 300, "elevation": 40, "demand": 30, "dma_zone": "DMA-2"},
            "J5": {"type": "junction", "x": 900, "y": 200, "elevation": 38, "demand": 10, "dma_zone": "DMA-3"},
            "J6": {"type": "junction", "x": 900, "y": 400, "elevation": 39, "demand": 18, "dma_zone": "DMA-4"},
        }
        demo_links = {
            "P1": {"type": "pipe", "start_node": "S1", "end_node": "J1", "diameter": 500, "length": 300},
            "P2": {"type": "pipe", "start_node": "J1", "end_node": "J2", "diameter": 400, "length": 250},
            "P3": {"type": "pipe", "start_node": "J1", "end_node": "J3", "diameter": 400, "length": 250},
            "P4": {"type": "pipe", "start_node": "J2", "end_node": "J4", "diameter": 300, "length": 300},
            "P5": {"type": "pipe", "start_node": "J3", "end_node": "J4", "diameter": 300, "length": 300},
            "P6": {"type": "pipe", "start_node": "J4", "end_node": "J5", "diameter": 200, "length": 250},
            "P7": {"type": "pipe", "start_node": "J4", "end_node": "J6", "diameter": 250, "length": 250},
            "P8": {"type": "pipe", "start_node": "J5", "end_node": "J6", "diameter": 150, "length": 300},
        }
        net = NetworkData(
            name="demo",
            nodes_json=json.dumps(demo_nodes, ensure_ascii=False),
            links_json=json.dumps(demo_links, ensure_ascii=False),
        )
        db.session.add(net)
    if AlertRule.query.count() == 0:
        seed_rules = [
            AlertRule(name="DMA-1片区连续异常告警",
                      condition_json=json.dumps({"type": "area_consecutive_anomaly", "area": "DMA-1", "days": 3, "threshold": 5}, ensure_ascii=False),
                      level=AlertRule.LEVEL_WARNING, notify_method="site_message", enabled=True),
            AlertRule(name="巡检员超时工作告警",
                      condition_json=json.dumps({"type": "inspector_overtime", "hours": 10}, ensure_ascii=False),
                      level=AlertRule.LEVEL_WARNING, notify_method="site_message", enabled=True),
            AlertRule(name="紧急异常未处理告警",
                      condition_json=json.dumps({"type": "urgent_unhandled", "hours": 2}, ensure_ascii=False),
                      level=AlertRule.LEVEL_CRITICAL, notify_method="site_message", enabled=True),
        ]
        db.session.add_all(seed_rules)
    if Certificate.query.count() == 0:
        seed_certs = [
            Certificate(inspector_id=1, cert_name="高级管网巡检资格证", issuer="国家水务协会", valid_until="2027-06-01"),
            Certificate(inspector_id=2, cert_name="中级管网巡检资格证", issuer="省水利厅", valid_until="2025-05-01"),
            Certificate(inspector_id=3, cert_name="初级管网巡检资格证", issuer="市水务局", valid_until="2026-12-31"),
            Certificate(inspector_id=4, cert_name="高级管网巡检资格证", issuer="国家水务协会", valid_until="2027-03-15"),
            Certificate(inspector_id=5, cert_name="中级管网巡检资格证", issuer="省水利厅", valid_until="2025-08-20"),
        ]
        db.session.add_all(seed_certs)
    if TrainingRecord.query.count() == 0:
        seed_trainings = [
            TrainingRecord(inspector_id=1, training_name="管网漏损检测技术培训", training_date="2025-01-15", duration_hours=8.0, result="pass"),
            TrainingRecord(inspector_id=2, training_name="阀门维护操作规程培训", training_date="2025-02-20", duration_hours=4.0, result="pass"),
            TrainingRecord(inspector_id=3, training_name="水质取样规范培训", training_date="2025-03-10", duration_hours=3.0, result="pass"),
            TrainingRecord(inspector_id=3, training_name="管网漏损检测技术培训", training_date="2025-04-05", duration_hours=8.0, result="fail"),
            TrainingRecord(inspector_id=4, training_name="应急抢修技术培训", training_date="2025-01-28", duration_hours=12.0, result="pass"),
            TrainingRecord(inspector_id=5, training_name="阀门维护操作规程培训", training_date="2025-03-15", duration_hours=4.0, result="pass"),
        ]
        db.session.add_all(seed_trainings)
    db.session.commit()


if __name__ == "__main__":
    with app.app_context():
        init_db_and_seed()
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
