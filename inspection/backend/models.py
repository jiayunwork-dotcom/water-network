from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Inspector(db.Model):
    __tablename__ = "inspectors"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    employee_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False, default="")
    skill_level = db.Column(db.String(20), nullable=False, default="junior")
    areas = db.Column(db.String(500), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="on_duty")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    SKILL_JUNIOR = "junior"
    SKILL_INTERMEDIATE = "intermediate"
    SKILL_SENIOR = "senior"

    STATUS_ON_DUTY = "on_duty"
    STATUS_OFF = "off"
    STATUS_OUT = "out"

    def to_dict(self):
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "name": self.name,
            "phone": self.phone,
            "skill_level": self.skill_level,
            "areas": self.areas.split(",") if self.areas else [],
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_type = db.Column(db.String(50), nullable=False)
    difficulty = db.Column(db.String(20), nullable=False, default="easy")
    estimated_minutes = db.Column(db.Integer, nullable=False, default=30)
    status = db.Column(db.String(20), nullable=False, default="pending")
    inspector_id = db.Column(db.Integer, db.ForeignKey("inspectors.id"), nullable=True)
    area = db.Column(db.String(100), nullable=False, default="")
    target_nodes = db.Column(db.String(500), nullable=False, default="")
    target_links = db.Column(db.String(500), nullable=False, default="")
    description = db.Column(db.Text, nullable=True)
    scheduled_date = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    TYPE_DAILY = "daily_inspection"
    TYPE_VALVE = "valve_maintenance"
    TYPE_LEAK = "leak_investigation"
    TYPE_QUALITY = "quality_sampling"

    DIFFICULTY_EASY = "easy"
    DIFFICULTY_MEDIUM = "medium"
    DIFFICULTY_HARD = "hard"

    STATUS_PENDING = "pending"
    STATUS_ASSIGNED = "assigned"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_ANOMALY = "anomaly"

    STATUS_ORDER = ["pending", "assigned", "in_progress", "completed", "anomaly"]

    VALID_TRANSITIONS = {
        "pending": ["assigned"],
        "assigned": ["in_progress", "pending"],
        "in_progress": ["completed", "anomaly"],
        "completed": [],
        "anomaly": ["in_progress"],
    }

    inspector = db.relationship("Inspector", backref="tasks")

    def to_dict(self):
        return {
            "id": self.id,
            "task_type": self.task_type,
            "difficulty": self.difficulty,
            "estimated_minutes": self.estimated_minutes,
            "status": self.status,
            "inspector_id": self.inspector_id,
            "area": self.area,
            "target_nodes": self.target_nodes.split(",") if self.target_nodes else [],
            "target_links": self.target_links.split(",") if self.target_links else [],
            "description": self.description,
            "scheduled_date": self.scheduled_date,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Anomaly(db.Model):
    __tablename__ = "anomalies"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("inspectors.id"), nullable=True)
    report_time = db.Column(db.DateTime, default=datetime.utcnow)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=True)
    anomaly_type = db.Column(db.String(50), nullable=False)
    severity = db.Column(db.String(20), nullable=False, default="minor")
    description = db.Column(db.Text, nullable=True)
    gps_lat = db.Column(db.Float, nullable=True)
    gps_lon = db.Column(db.Float, nullable=True)
    related_node = db.Column(db.String(50), nullable=True)
    related_link = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="unhandled")
    auto_task_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    TYPE_PIPE_BREAK = "pipe_break"
    TYPE_VALVE_STUCK = "valve_stuck"
    TYPE_METER_ABNORMAL = "meter_abnormal"
    TYPE_QUALITY_EXCEED = "quality_exceed"
    TYPE_OTHER = "other"

    SEVERITY_MINOR = "minor"
    SEVERITY_NORMAL = "normal"
    SEVERITY_SERIOUS = "serious"
    SEVERITY_URGENT = "urgent"

    STATUS_UNHANDLED = "unhandled"
    STATUS_PROCESSING = "processing"
    STATUS_RESOLVED = "resolved"
    STATUS_ACCEPTED = "accepted"

    ANOMALY_STATUS_ORDER = ["unhandled", "processing", "resolved", "accepted"]

    ANOMALY_VALID_TRANSITIONS = {
        "unhandled": ["processing"],
        "processing": ["resolved"],
        "resolved": ["accepted"],
        "accepted": [],
    }

    reporter = db.relationship("Inspector", backref="reported_anomalies")
    task = db.relationship("Task", backref="anomalies")

    def to_dict(self):
        return {
            "id": self.id,
            "reporter_id": self.reporter_id,
            "reporter_name": self.reporter.name if self.reporter else None,
            "report_time": self.report_time.isoformat() if self.report_time else None,
            "task_id": self.task_id,
            "anomaly_type": self.anomaly_type,
            "severity": self.severity,
            "description": self.description,
            "gps_lat": self.gps_lat,
            "gps_lon": self.gps_lon,
            "related_node": self.related_node,
            "related_link": self.related_link,
            "status": self.status,
            "auto_task_id": self.auto_task_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class NetworkData(db.Model):
    __tablename__ = "network_data"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, default="default")
    nodes_json = db.Column(db.Text, nullable=False, default="{}")
    links_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "name": self.name,
            "nodes": json.loads(self.nodes_json) if self.nodes_json else {},
            "links": json.loads(self.links_json) if self.links_json else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
