"""
Repository layer for Task and WorkflowRun persistent operations in SQLite.
Provides strong type safety, JSON serialization/deserialization, and transaction management.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import get_db_connection
from schemas import (
    AgentMetric,
    CoderResult,
    FindingSeverity,
    ReviewerResult,
    ReviewerVerdict,
    ReviewFinding,
    TaskEvent,
    TaskPlan,
    TaskResponse,
    TaskScope,
    TaskStatus,
    TestCaseResult,
    TesterResult,
    WorkflowRun,
)


def _to_json_compatible(item: Any) -> Any:
    """Nesneyi JSON serileştirilebilir Python ilkel tiplerine dönüştürür."""
    if item is None:
        return None
    if isinstance(item, (int, float, bool, str)):
        return item
    if isinstance(item, datetime):
        return item.isoformat()
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if hasattr(item, "dict"):
        return item.dict()
    if isinstance(item, list):
        return [_to_json_compatible(x) for x in item]
    if isinstance(item, tuple):
        return [_to_json_compatible(x) for x in item]
    if isinstance(item, dict):
        return {k: _to_json_compatible(v) for k, v in item.items()}
    return str(item)


def _serialize_json(data: Any) -> Optional[str]:
    """Pydantic modelini, listesini veya Python sözlüğünü güvenle JSON dizesine dönüştürür."""
    if data is None:
        return None
    compatible_data = _to_json_compatible(data)
    return json.dumps(compatible_data, ensure_ascii=False)


def _deserialize_json(json_str: Optional[str]) -> Optional[Any]:
    """JSON dizesini Python nesnesine dönüştürür."""
    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except Exception:
        return None


def _model_or_none(model: Any, raw: Any) -> Any:
    """Eksik veya bozuk eski JSON alanını görevi çökertmeden boş kabul eder."""
    if not isinstance(raw, dict):
        return None
    try:
        return model(**raw)
    except Exception:
        return None


def _parse_datetime(val: Any) -> datetime:
    """Metin veya datetime değerini UTC datetime nesnesine dönüştürür."""
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.now(timezone.utc)


def extract_agent_metrics_from_events(
    events: List[TaskEvent],
    plan_data: Optional[Any] = None,
    scope_data: Optional[Any] = None,
    coder_data: Optional[Any] = None,
    tester_data: Optional[Any] = None,
    reviewer_data: Optional[Any] = None,
) -> List[AgentMetric]:
    """
    Olay günlüğünden (TaskEvent) ve agent sonuçlarından ajan bazlı metrikleri türetir.
    """
    metrics: List[AgentMetric] = []
    
    # 1. Planner Agent
    p_start_evt = next((e for e in events if e.type == "planning_started"), None)
    p_end_evt = next((e for e in events if e.type in ["plan_created", "planning_failed"]), None)
    p_start = p_start_evt.timestamp if p_start_evt else None
    p_end = p_end_evt.timestamp if p_end_evt else None
    p_status = "completed" if plan_data else ("failed" if any(e.type == "planning_failed" for e in events) else "skipped")
    p_dur = (p_end - p_start).total_seconds() * 1000 if (p_start and p_end) else None
    
    details = (p_end_evt.details if p_end_evt and p_end_evt.details else None) or (p_start_evt.details if p_start_evt and p_start_evt.details else {})
    p_mode = details.get("planner_mode") or ("fallback" if any(e.type == "planner_fallback" for e in events) else "deterministic")
    p_prov = details.get("provider")
    p_model = details.get("model")

    metrics.append(AgentMetric(
        agent_name="PLANNER",
        status=p_status,
        started_at=p_start,
        completed_at=p_end,
        duration_ms=p_dur,
        error=None if plan_data else "Plan üretilemedi.",
        mode=p_mode,
        provider=p_prov,
        model=p_model
    ))

    # 2. Scope Agent
    s_start = next((e.timestamp for e in events if e.type == "scope_started"), None)
    s_end = next((e.timestamp for e in events if e.type == "scope_completed"), None)
    s_status = "completed" if scope_data else ("skipped" if not p_start else "failed")
    s_dur = (s_end - s_start).total_seconds() * 1000 if (s_start and s_end) else None
    metrics.append(AgentMetric(
        agent_name="SCOPE",
        status=s_status,
        started_at=s_start,
        completed_at=s_end,
        duration_ms=s_dur,
        error=None if scope_data else ("Kapsam analizi atlandı." if s_status == "skipped" else "Kapsam analizi başarısız.")
    ))

    # 3. Coder Agent
    c_start = next((e.timestamp for e in events if e.type == "coder_started"), None)
    c_end = next((e.timestamp for e in events if e.type in ["coder_completed", "coder_unsupported", "coder_failed"]), None)
    c_res_status = coder_data.get("status") if isinstance(coder_data, dict) else getattr(coder_data, "status", None)
    c_status = c_res_status if c_res_status in ["coded", "unsupported", "failed"] else ("completed" if coder_data else "skipped")
    c_dur = (c_end - c_start).total_seconds() * 1000 if (c_start and c_end) else None
    metrics.append(AgentMetric(
        agent_name="CODER",
        status=c_status,
        started_at=c_start,
        completed_at=c_end,
        duration_ms=c_dur,
        error=coder_data.get("error") if isinstance(coder_data, dict) else getattr(coder_data, "error", None)
    ))

    # 4. Tester Agent
    t_start = next((e.timestamp for e in events if e.type == "tester_started"), None)
    t_end = next((e.timestamp for e in events if e.type in ["tester_completed", "tester_failed", "tester_blocked"]), None)
    t_res_status = tester_data.get("status") if isinstance(tester_data, dict) else getattr(tester_data, "status", None)
    t_status = t_res_status if t_res_status in ["tested", "failed", "blocked"] else ("completed" if tester_data else "skipped")
    t_dur = (t_end - t_start).total_seconds() * 1000 if (t_start and t_end) else None
    metrics.append(AgentMetric(
        agent_name="TESTER",
        status=t_status,
        started_at=t_start,
        completed_at=t_end,
        duration_ms=t_dur,
        error=tester_data.get("error") if isinstance(tester_data, dict) else getattr(tester_data, "error", None)
    ))

    # 5. Reviewer Agent
    r_start = next((e.timestamp for e in events if e.type == "reviewer_started"), None)
    r_end = next((e.timestamp for e in events if e.type in ["reviewer_completed", "reviewer_failed", "reviewer_blocked"]), None)
    r_res_status = reviewer_data.get("status") if isinstance(reviewer_data, dict) else getattr(reviewer_data, "status", None)
    r_status = r_res_status if r_res_status in ["reviewed", "failed", "blocked"] else ("completed" if reviewer_data else "skipped")
    r_dur = (r_end - r_start).total_seconds() * 1000 if (r_start and r_end) else None
    metrics.append(AgentMetric(
        agent_name="REVIEWER",
        status=r_status,
        started_at=r_start,
        completed_at=r_end,
        duration_ms=r_dur,
        error=reviewer_data.get("error") if isinstance(reviewer_data, dict) else getattr(reviewer_data, "error", None)
    ))

    return metrics


class TaskRepository:
    """Görev (Task) veritabanı CRUD işlemleri."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def create_task(
        self,
        task_id: str,
        description: str,
        status: TaskStatus = TaskStatus.QUEUED,
        created_at: Optional[datetime] = None
    ) -> TaskResponse:
        """Yeni bir görevi veritabanına kaydeder."""
        now_dt = created_at or datetime.now(timezone.utc)
        now_str = now_dt.isoformat()

        init_event = TaskEvent(
            id=f"evt_{uuid.uuid4().hex[:8]}",
            timestamp=now_dt,
            source="ORCHESTRATOR",
            type="task_created",
            message=f"Görev başarıyla oluşturuldu: {task_id}"
        )
        events_json = _serialize_json([init_event])

        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, description, status, created_at, updated_at,
                    plan_json, scope_json, coder_json, tester_json, reviewer_json,
                    events_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    task_id,
                    description,
                    status.value if isinstance(status, TaskStatus) else str(status),
                    now_str,
                    now_str,
                    None, None, None, None, None,
                    events_json,
                    None
                )
            )

        return TaskResponse(
            id=task_id,
            description=description,
            status=status,
            created_at=now_dt,
            updated_at=now_dt,
            events=[init_event]
        )

    def get_task(self, task_id: str) -> Optional[TaskResponse]:
        """Görev ID'sine göre tekil görevi getirir."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?;", (task_id,)).fetchone()
            if not row:
                return None
            return self._row_to_task_response(row)

    def list_tasks(self) -> List[TaskResponse]:
        """Tüm görevleri oluşturulma sırasına göre (en yeniden en eskiye) listeler."""
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC;").fetchall()
            return [self._row_to_task_response(r) for r in rows]

    def update_task_workflow_result(
        self,
        task_id: str,
        status: TaskStatus,
        plan: Optional[Any] = None,
        scope: Optional[Any] = None,
        coder: Optional[Any] = None,
        tester: Optional[Any] = None,
        reviewer: Optional[Any] = None,
        events: Optional[List[Any]] = None,
        error: Optional[str] = None,
        updated_at: Optional[datetime] = None
    ) -> Optional[TaskResponse]:
        """İş akışı sonrasında görevin durum ve agent sonuçlarını günceller."""
        now_dt = updated_at or datetime.now(timezone.utc)
        now_str = now_dt.isoformat()

        plan_json = _serialize_json(plan)
        scope_json = _serialize_json(scope)
        coder_json = _serialize_json(coder)
        tester_json = _serialize_json(tester)
        reviewer_json = _serialize_json(reviewer)
        events_json = _serialize_json(events)

        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = ?,
                    updated_at = ?,
                    plan_json = ?,
                    scope_json = ?,
                    coder_json = ?,
                    tester_json = ?,
                    reviewer_json = ?,
                    events_json = ?,
                    error = ?
                WHERE id = ?;
                """,
                (
                    status.value if isinstance(status, TaskStatus) else str(status),
                    now_str,
                    plan_json,
                    scope_json,
                    coder_json,
                    tester_json,
                    reviewer_json,
                    events_json,
                    error,
                    task_id
                )
            )
            if cursor.rowcount == 0:
                return None

        return self.get_task(task_id)

    def _row_to_task_response(self, row: Any) -> TaskResponse:
        """Veritabanı satırını TaskResponse Pydantic nesnesine dönüştürür."""
        plan_raw = _deserialize_json(row["plan_json"])
        scope_raw = _deserialize_json(row["scope_json"])
        coder_raw = _deserialize_json(row["coder_json"])
        tester_raw = _deserialize_json(row["tester_json"])
        reviewer_raw = _deserialize_json(row["reviewer_json"])
        events_raw = _deserialize_json(row["events_json"]) or []

        parsed_events: List[TaskEvent] = []
        if isinstance(events_raw, list):
            for e in events_raw:
                if isinstance(e, TaskEvent):
                    parsed_events.append(e)
                elif isinstance(e, dict):
                    try:
                        parsed_events.append(TaskEvent(**e))
                    except Exception:
                        continue

        return TaskResponse(
            id=row["id"],
            description=row["description"],
            status=TaskStatus(row["status"]) if row["status"] in TaskStatus._value2member_map_ else TaskStatus.QUEUED,
            plan=_model_or_none(TaskPlan, plan_raw),
            scope=_model_or_none(TaskScope, scope_raw),
            coder=_model_or_none(CoderResult, coder_raw),
            tester=_model_or_none(TesterResult, tester_raw),
            reviewer=_model_or_none(ReviewerResult, reviewer_raw),
            events=parsed_events,
            error=row["error"],
            created_at=_parse_datetime(row["created_at"]),
            updated_at=_parse_datetime(row["updated_at"]) if row["updated_at"] else None
        )


class WorkflowRunRepository:
    """İş akışı çalıştırma geçmişi (WorkflowRun) CRUD işlemleri."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def create_run(
        self,
        task_id: str,
        run_id: Optional[str] = None,
        started_at: Optional[datetime] = None
    ) -> WorkflowRun:
        """Yeni bir iş akışı çalıştırma kaydı oluşturur."""
        rid = run_id or f"run_{uuid.uuid4().hex[:8]}"
        start_dt = started_at or datetime.now(timezone.utc)
        start_str = start_dt.isoformat()

        with get_db_connection(self.db_path) as conn:
            # Kaçıncı çalıştırma olduğunu belirle
            count_row = conn.execute(
                "SELECT COUNT(*) AS total FROM workflow_runs WHERE task_id = ?;",
                (task_id,)
            ).fetchone()
            run_number = (count_row["total"] if count_row else 0) + 1

            conn.execute(
                """
                INSERT INTO workflow_runs (
                    id, task_id, run_number, status, started_at, completed_at,
                    duration_ms, error, plan_json, scope_json, coder_json,
                    tester_json, reviewer_json, events_json, agent_metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    rid,
                    task_id,
                    run_number,
                    TaskStatus.IN_PROGRESS.value,
                    start_str,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None
                )
            )

        return WorkflowRun(
            id=rid,
            task_id=task_id,
            run_number=run_number,
            status=TaskStatus.IN_PROGRESS,
            started_at=start_dt
        )

    def complete_run(
        self,
        run_id: str,
        status: TaskStatus,
        plan: Optional[Any] = None,
        scope: Optional[Any] = None,
        coder: Optional[Any] = None,
        tester: Optional[Any] = None,
        reviewer: Optional[Any] = None,
        events: Optional[List[Any]] = None,
        error: Optional[str] = None,
        completed_at: Optional[datetime] = None,
        duration_ms: Optional[float] = None
    ) -> Optional[WorkflowRun]:
        """Çalıştırma tamamlandığında sonuçları ve metrikleri kaydeder."""
        end_dt = completed_at or datetime.now(timezone.utc)
        end_str = end_dt.isoformat()

        # Event nesnelerini parse et
        parsed_events: List[TaskEvent] = []
        if events:
            for e in events:
                if isinstance(e, TaskEvent):
                    parsed_events.append(e)
                elif isinstance(e, dict):
                    parsed_events.append(TaskEvent(**e))

        metrics = extract_agent_metrics_from_events(
            events=parsed_events,
            plan_data=plan,
            scope_data=scope,
            coder_data=coder,
            tester_data=tester,
            reviewer_data=reviewer
        )

        plan_json = _serialize_json(plan)
        scope_json = _serialize_json(scope)
        coder_json = _serialize_json(coder)
        tester_json = _serialize_json(tester)
        reviewer_json = _serialize_json(reviewer)
        events_json = _serialize_json(parsed_events)
        metrics_json = _serialize_json(metrics)

        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?,
                    completed_at = ?,
                    duration_ms = ?,
                    error = ?,
                    plan_json = ?,
                    scope_json = ?,
                    coder_json = ?,
                    tester_json = ?,
                    reviewer_json = ?,
                    events_json = ?,
                    agent_metrics_json = ?
                WHERE id = ?;
                """,
                (
                    status.value if isinstance(status, TaskStatus) else str(status),
                    end_str,
                    duration_ms,
                    error,
                    plan_json,
                    scope_json,
                    coder_json,
                    tester_json,
                    reviewer_json,
                    events_json,
                    metrics_json,
                    run_id
                )
            )
            if cursor.rowcount == 0:
                return None

        return self.get_run(run_id)

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        """ID'sine göre tekil bir çalıştırma kaydını getirir."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?;", (run_id,)).fetchone()
            if not row:
                return None
            return self._row_to_workflow_run(row)

    def list_runs_for_task(self, task_id: str) -> List[WorkflowRun]:
        """Bir göreve ait tüm geçmiş çalıştırmaları kronolojik sırada listeler."""
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_runs WHERE task_id = ? ORDER BY run_number ASC;",
                (task_id,)
            ).fetchall()
            return [self._row_to_workflow_run(r) for r in rows]

    def _row_to_workflow_run(self, row: Any) -> WorkflowRun:
        """Veritabanı satırını WorkflowRun Pydantic nesnesine dönüştürür."""
        plan_raw = _deserialize_json(row["plan_json"])
        scope_raw = _deserialize_json(row["scope_json"])
        coder_raw = _deserialize_json(row["coder_json"])
        tester_raw = _deserialize_json(row["tester_json"])
        reviewer_raw = _deserialize_json(row["reviewer_json"])
        events_raw = _deserialize_json(row["events_json"]) or []
        metrics_raw = _deserialize_json(row["agent_metrics_json"]) or []

        parsed_events: List[TaskEvent] = []
        if isinstance(events_raw, list):
            for e in events_raw:
                if isinstance(e, TaskEvent):
                    parsed_events.append(e)
                elif isinstance(e, dict):
                    parsed_events.append(TaskEvent(**e))

        parsed_metrics: List[AgentMetric] = []
        if isinstance(metrics_raw, list):
            for m in metrics_raw:
                if isinstance(m, AgentMetric):
                    parsed_metrics.append(m)
                elif isinstance(m, dict):
                    parsed_metrics.append(AgentMetric(**m))

        return WorkflowRun(
            id=row["id"],
            task_id=row["task_id"],
            run_number=row["run_number"],
            status=TaskStatus(row["status"]) if row["status"] in TaskStatus._value2member_map_ else TaskStatus.FAILED,
            started_at=_parse_datetime(row["started_at"]),
            completed_at=_parse_datetime(row["completed_at"]) if row["completed_at"] else None,
            duration_ms=row["duration_ms"],
            error=row["error"],
            plan=TaskPlan(**plan_raw) if plan_raw else None,
            scope=TaskScope(**scope_raw) if scope_raw else None,
            coder=CoderResult(**coder_raw) if coder_raw else None,
            tester=TesterResult(**tester_raw) if tester_raw else None,
            reviewer=ReviewerResult(**reviewer_raw) if reviewer_raw else None,
            events=parsed_events,
            agent_metrics=parsed_metrics
        )
