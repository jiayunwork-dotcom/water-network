import numpy as np
from datetime import datetime
from models import db, Inspector, Task, Certificate


SKILL_HIERARCHY = {
    Inspector.SKILL_JUNIOR: 1,
    Inspector.SKILL_INTERMEDIATE: 2,
    Inspector.SKILL_SENIOR: 3,
}

DIFFICULTY_HIERARCHY = {
    Task.DIFFICULTY_EASY: 1,
    Task.DIFFICULTY_MEDIUM: 2,
    Task.DIFFICULTY_HARD: 3,
}

TASK_TYPE_SKILL_REQUIREMENT = {
    Task.TYPE_DAILY: Inspector.SKILL_JUNIOR,
    Task.TYPE_VALVE: Inspector.SKILL_INTERMEDIATE,
    Task.TYPE_LEAK: Inspector.SKILL_SENIOR,
    Task.TYPE_QUALITY: Inspector.SKILL_JUNIOR,
}

TASK_TYPE_DIFFICULTY = {
    Task.TYPE_DAILY: Task.DIFFICULTY_EASY,
    Task.TYPE_VALVE: Task.DIFFICULTY_MEDIUM,
    Task.TYPE_LEAK: Task.DIFFICULTY_HARD,
    Task.TYPE_QUALITY: Task.DIFFICULTY_EASY,
}

MAX_WORK_MINUTES = 8 * 60


def _inspector_can_handle(inspector, task):
    required_skill = TASK_TYPE_SKILL_REQUIREMENT.get(task.task_type, Inspector.SKILL_SENIOR)
    if SKILL_HIERARCHY.get(inspector.skill_level, 0) < SKILL_HIERARCHY.get(required_skill, 0):
        return False
    if task.area:
        inspector_areas = inspector.areas.split(",") if inspector.areas else []
        if task.area not in inspector_areas:
            return False
    certs = Certificate.query.filter_by(inspector_id=inspector.id).all()
    today_str = datetime.now().strftime("%Y-%m-%d")
    has_expired = any(c.valid_until < today_str for c in certs)
    if has_expired:
        if SKILL_HIERARCHY.get(inspector.skill_level, 0) < SKILL_HIERARCHY.get(required_skill, 0) + 1:
            return False
    return True


def _compute_workload_std(assignments, inspectors):
    workloads = []
    for insp in inspectors:
        total = sum(t.estimated_minutes for t in assignments.get(insp.id, []))
        workloads.append(total)
    if not workloads:
        return 0.0
    return float(np.std(workloads))


def daily_schedule(inspector_ids, task_ids):
    inspectors = Inspector.query.filter(
        Inspector.id.in_(inspector_ids),
        Inspector.status == Inspector.STATUS_ON_DUTY
    ).all()
    tasks = Task.query.filter(
        Task.id.in_(task_ids),
        Task.status == Task.STATUS_PENDING
    ).all()

    if not inspectors or not tasks:
        return {
            "assignments": {},
            "unassigned": [
                {"task_id": t.id, "reason": "无在岗巡检员"} for t in tasks
            ] if not inspectors else [],
        }

    tasks_sorted = sorted(
        tasks,
        key=lambda t: DIFFICULTY_HIERARCHY.get(t.difficulty, 0),
        reverse=True
    )
    inspectors_sorted = sorted(
        inspectors,
        key=lambda i: SKILL_HIERARCHY.get(i.skill_level, 0)
    )

    assignments = {insp.id: [] for insp in inspectors_sorted}
    workloads = {insp.id: 0 for insp in inspectors_sorted}
    unassigned = []

    for task in tasks_sorted:
        eligible = []
        for insp in inspectors_sorted:
            if not _inspector_can_handle(insp, task):
                continue
            if workloads[insp.id] + task.estimated_minutes > MAX_WORK_MINUTES:
                continue
            eligible.append(insp)

        if not eligible:
            reason = _get_unassign_reason(task, inspectors_sorted, workloads)
            unassigned.append({"task_id": task.id, "reason": reason})
            continue

        eligible.sort(key=lambda i: workloads[i.id])
        chosen = eligible[0]
        assignments[chosen.id].append(task)
        workloads[chosen.id] += task.estimated_minutes

    improved = _local_search(assignments, inspectors_sorted, workloads)
    if improved:
        assignments = improved

    result_assignments = {}
    for insp_id, task_list in assignments.items():
        result_assignments[insp_id] = [t.id for t in task_list]

    return {
        "assignments": result_assignments,
        "unassigned": unassigned,
    }


def _get_unassign_reason(task, inspectors, workloads):
    required_skill = TASK_TYPE_SKILL_REQUIREMENT.get(task.task_type, Inspector.SKILL_SENIOR)
    required_level = SKILL_HIERARCHY.get(required_skill, 3)

    skilled_available = any(
        SKILL_HIERARCHY.get(i.skill_level, 0) >= required_level
        for i in inspectors
    )

    if not skilled_available:
        return f"无符合技能要求({required_skill})的在岗人员"

    if task.area:
        area_available = any(task.area in (i.areas.split(",") if i.areas else []) for i in inspectors)
        if not area_available:
            return f"无负责片区({task.area})的在岗人员"

    return "巡检员当日工作量已达上限(8小时)"


def _local_search(assignments, inspectors, workloads, max_iterations=100):
    best_assignments = {k: list(v) for k, v in assignments.items()}
    best_std = _compute_workload_std(assignments, inspectors)

    for _ in range(max_iterations):
        improved = False
        insp_ids = [i.id for i in inspectors]
        if len(insp_ids) < 2:
            break

        for i in range(len(insp_ids)):
            for j in range(i + 1, len(insp_ids)):
                id_a, id_b = insp_ids[i], insp_ids[j]
                tasks_a = best_assignments.get(id_a, [])
                tasks_b = best_assignments.get(id_b, [])

                if not tasks_a or not tasks_b:
                    continue

                for ta in tasks_a:
                    insp_a = next(ins for ins in inspectors if ins.id == id_a)
                    insp_b = next(ins for ins in inspectors if ins.id == id_b)
                    if not _inspector_can_handle(insp_b, ta):
                        continue

                    for tb in tasks_b:
                        if not _inspector_can_handle(insp_a, tb):
                            continue

                        new_wl_a = workloads[id_a] - ta.estimated_minutes + tb.estimated_minutes
                        new_wl_b = workloads[id_b] - tb.estimated_minutes + ta.estimated_minutes

                        if new_wl_a > MAX_WORK_MINUTES or new_wl_b > MAX_WORK_MINUTES:
                            continue

                        temp_assignments = {k: list(v) for k, v in best_assignments.items()}
                        temp_assignments[id_a].remove(ta)
                        temp_assignments[id_a].append(tb)
                        temp_assignments[id_b].remove(tb)
                        temp_assignments[id_b].append(ta)

                        temp_workloads = dict(workloads)
                        temp_workloads[id_a] = new_wl_a
                        temp_workloads[id_b] = new_wl_b

                        new_std = _compute_workload_std(temp_assignments, inspectors)
                        if new_std < best_std:
                            best_assignments = temp_assignments
                            workloads[id_a] = new_wl_a
                            workloads[id_b] = new_wl_b
                            best_std = new_std
                            improved = True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break

        if not improved:
            break

    return best_assignments
