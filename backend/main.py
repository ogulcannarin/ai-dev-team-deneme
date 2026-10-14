import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from agent_workflow import (
    WorkflowCheckpointError,
    delivery_node,
    has_completion_evidence,
    recover_unpersisted_decisions,
    resume_agent_workflow,
    run_agent_workflow,
)
from database import init_db
from llm_provider import get_llm_provider, load_project_env
from repository import TaskRepository, WorkflowRunRepository
from schemas import (
    HealthResponse,
    LLMProviderInfo,
    TaskApprovalRequest,
    TaskCreateRequest,
    TaskEvent,
    TaskRejectRequest,
    TaskResponse,
    TaskStatus,
    WorkflowRun,
    WorkflowRunListResponse,
)

# Ortam değişkenlerini güvenle yükle
load_project_env()

# Eşzamanlı çalıştırmaları önlemek için görev kilitleri (Task-level concurrency locks)
_task_locks: Dict[str, asyncio.Lock] = {}
_lock_access: Optional[asyncio.Lock] = None
_sandbox_semaphore: Optional[asyncio.Semaphore] = None

MAX_CONCURRENT_SANDBOXES = int(os.environ.get("MAX_CONCURRENT_SANDBOXES", "3"))


def get_sandbox_semaphore() -> asyncio.Semaphore:
    global _sandbox_semaphore
    if _sandbox_semaphore is None:
        _sandbox_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)
    return _sandbox_semaphore


def get_lock_access() -> asyncio.Lock:
    global _lock_access
    if _lock_access is None:
        _lock_access = asyncio.Lock()
    return _lock_access


async def get_task_lock(task_id: str) -> asyncio.Lock:
    async with get_lock_access():
        if task_id not in _task_locks:
            _task_locks[task_id] = asyncio.Lock()
        return _task_locks[task_id]


# İnsan kararı yalnızca incelemesi bitmiş görevlerde geçerlidir.
# completed onayı ve changes_requested reddi olay yazmadan mevcut kaydı döndürür.
_APPROVABLE_STATUSES = {TaskStatus.REVIEWED, TaskStatus.AWAITING_APPROVAL}
_REJECTABLE_STATUSES = {TaskStatus.REVIEWED, TaskStatus.AWAITING_APPROVAL}


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    """Sorgu veya olay detayındaki değeri bool'a çevirir. Tanınmayan değer None kalır."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
        return None
    return bool(value)


def _detail_from_events(events: Optional[List[Any]], key: str) -> Any:
    if not events:
        return None
    for ev in events:
        details = getattr(ev, "details", None)
        if isinstance(details, dict) and key in details:
            return details.get(key)
    return None


def _stamp_human_approval_flag(events: List[Any], required: bool) -> None:
    """Sonraki /run çağrılarının aynı onay tercihini okuyabilmesi için olaya yazar."""
    for ev in events:
        if getattr(ev, "type", None) == "task_created":
            details = dict(getattr(ev, "details", None) or {})
            details["require_human_approval"] = required
            ev.details = details
            return


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ortam değişkenlerini ve veritabanı tablolarını başlat
    load_project_env()
    init_db()
    try:
        await recover_unpersisted_decisions()
    except Exception:
        logging.getLogger(__name__).exception(
            "Checkpoint recovery başlatılamadı. Bekleyen görevler completed yapılmadı."
        )
    yield


app = FastAPI(
    title="AI Dev Team - Backend API",
    description="AI Dev Team orkestrasyon sistemi, SQLite kalıcı veri katmanı ve LangGraph tabanlı agent iş akışı REST API servisi.",
    version="0.4.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS yapılandırması - React frontend için erişim izni
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_task_repository() -> TaskRepository:
    return TaskRepository()


def get_workflow_run_repository() -> WorkflowRunRepository:
    return WorkflowRunRepository()


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Sağlık kontrolü",
    description="Servisin ayakta ve erişilebilir olduğunu bildiren durum bilgisini döndürür.",
)
async def health_check() -> HealthResponse:
    return HealthResponse()


@app.get(
    "/system/llm-info",
    response_model=LLMProviderInfo,
    tags=["System"],
    summary="LLM Sağlayıcı Bilgisi",
    description="Backend ortamında yapılandırılmış olan LLM sağlayıcısı ve model bilgilerini döndürür (Gizli anahtarlar asla yer almaz).",
)
async def get_llm_info() -> LLMProviderInfo:
    provider = get_llm_provider()
    meta = provider.get_metadata()
    return LLMProviderInfo(
        provider=meta["provider"],
        model=meta["model"],
        base_host=meta["base_host"],
        is_configured=meta["is_configured"],
        fallback_enabled=meta["fallback_enabled"],
        default_planner_mode=os.environ.get("DEFAULT_PLANNER_MODE", "deterministic"),
        default_coder_mode=os.environ.get("DEFAULT_CODER_MODE", "deterministic")
    )


@app.post(
    "/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Tasks"],
    summary="Yeni görev oluştur",
    description="Yeni bir görev kaydı oluşturur, SQLite veritabanına kalıcı olarak kaydeder ve başlangıçta 'queued' durumuna alır.",
)
async def create_task(payload: TaskCreateRequest) -> TaskResponse:
    task_id = f"task_{uuid.uuid4().hex[:10]}"
    task_repo = get_task_repository()
    
    try:
        task = task_repo.create_task(
            task_id=task_id,
            description=payload.description,
            status=TaskStatus.QUEUED
        )
        mode_details = {}
        if payload.planner_mode:
            mode_details["planner_mode"] = payload.planner_mode
        if payload.coder_mode:
            mode_details["coder_mode"] = payload.coder_mode
        if payload.require_human_approval is not None:
            mode_details["require_human_approval"] = bool(payload.require_human_approval)

        if mode_details:
            # Mode tercihlerini ilk event detayına ekle
            for e in task.events:
                if e.type == "task_created":
                    e.details = mode_details
            task_repo.update_task_workflow_result(
                task_id=task.id,
                status=task.status,
                events=task.events
            )
            updated = task_repo.get_task(task_id)
            if updated:
                return updated
        return task
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Görev oluşturulurken veritabanı hatası meydana geldi: {str(e)}"
        )


@app.post(
    "/tasks/{task_id}/run",
    response_model=TaskResponse,
    status_code=status.HTTP_200_OK,
    tags=["Tasks", "Workflow"],
    summary="Görevin agent iş akışını başlat (Planner + Scope + Coder + Tester + Reviewer Agent)",
    description="Belirtilen görevi LangGraph StateGraph iş akışına sokar. Yeni bir workflow_run kaydı oluşturur, ajanları çalıştırır, sonuçları ve çalıştırma geçmişini SQLite veritabanında kalıcı olarak günceller.",
)
async def run_task(
    task_id: str,
    planner_mode: Optional[str] = None,
    coder_mode: Optional[str] = None,
    require_human_approval: Optional[bool] = None
) -> TaskResponse:
    task_repo = get_task_repository()
    run_repo = get_workflow_run_repository()

    task = task_repo.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{task_id}' kimlikli görev bulunamadı."
        )

    task_lock = await get_task_lock(task_id)
    if task_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{task_id}' kimlikli görev için bir iş akışı şu anda zaten çalışıyor. Lütfen tamamlanmasını bekleyin."
        )

    # İstenen planner ve coder modunu belirle
    effective_planner_mode = planner_mode
    effective_coder_mode = coder_mode
    if (not effective_planner_mode or not effective_coder_mode) and task.events:
        for ev in task.events:
            if ev.details and isinstance(ev.details, dict):
                if not effective_planner_mode and "planner_mode" in ev.details:
                    effective_planner_mode = ev.details.get("planner_mode")
                if not effective_coder_mode and "coder_mode" in ev.details:
                    effective_coder_mode = ev.details.get("coder_mode")

    # Sorgu parametresi yoksa görev oluşturulurken kaydedilen tercihi kullan. Varsayılan kapalıdır.
    stored_approval = _coerce_optional_bool(
        _detail_from_events(task.events, "require_human_approval")
    )
    effective_require_human_approval = (
        require_human_approval if require_human_approval is not None else bool(stored_approval)
    )
    initial_events = list(task.events or [])
    _stamp_human_approval_flag(initial_events, effective_require_human_approval)

    async with task_lock:
        current = task_repo.get_task(task_id)
        if current and current.status == TaskStatus.AWAITING_APPROVAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Görev insan onayı bekliyor. Checkpoint duraklaması sürüyor; akış baştan başlatılmadı."
            )
        if current and current.status == TaskStatus.DELIVERY_FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Git teslimatı başarısız. Planner ve Coder yeniden çalıştırılmadı. Teslimat yeniden denenebilir."
            )
        async with get_sandbox_semaphore():
            start_time = datetime.now(timezone.utc)
            
            # 1. Yeni çalıştırma kaydı oluştur (WorkflowRun)
            run_record = run_repo.create_run(
                task_id=task_id,
                started_at=start_time
            )

            try:
                # 2. LangGraph iş akışını çalıştır
                result_state = await run_agent_workflow(
                    task_id=task.id,
                    description=task.description,
                    initial_events=initial_events,
                    planner_mode=effective_planner_mode,
                    coder_mode=effective_coder_mode,
                    require_human_approval=effective_require_human_approval
                )

                end_time = datetime.now(timezone.utc)
                duration_ms = (end_time - start_time).total_seconds() * 1000

                final_status = TaskStatus(result_state.get("status", TaskStatus.FAILED.value))
                plan = result_state.get("plan")
                scope = result_state.get("scope")
                coder = result_state.get("coder")
                tester = result_state.get("tester")
                reviewer = result_state.get("reviewer")
                events = result_state.get("events", [])
                error = result_state.get("error")

                # 3. Çalıştırma geçmişini tamamla
                run_repo.complete_run(
                    run_id=run_record.id,
                    status=final_status,
                    plan=plan,
                    scope=scope,
                    coder=coder,
                    tester=tester,
                    reviewer=reviewer,
                    events=events,
                    error=error,
                    completed_at=end_time,
                    duration_ms=duration_ms
                )

                # 4. Görev tablosundaki son durumu güncelle
                updated_task = task_repo.update_task_workflow_result(
                    task_id=task_id,
                    status=final_status,
                    plan=plan,
                    scope=scope,
                    coder=coder,
                    tester=tester,
                    reviewer=reviewer,
                    events=events,
                    error=error,
                    updated_at=end_time
                )

                if not updated_task:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Görev durumu güncellenirken bir hata oluştu."
                    )

                return updated_task

            except Exception as e:
                end_time = datetime.now(timezone.utc)
                duration_ms = (end_time - start_time).total_seconds() * 1000
                err_msg = str(e)

                # Hata durumunu çalıştırma geçmişine yaz
                run_repo.complete_run(
                    run_id=run_record.id,
                    status=TaskStatus.FAILED,
                    error=err_msg,
                    completed_at=end_time,
                    duration_ms=duration_ms
                )

                task_repo.update_task_workflow_result(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=err_msg,
                    updated_at=end_time
                )

                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"İş akışı yürütülürken beklenmeyen hata oluştu: {err_msg}"
                )


@app.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    tags=["Tasks"],
    summary="Görev detayını getir",
    description="Belirtilen ID'ye sahip görevin durumunu, planını, dosya kapsamını, agent sonuçlarını ve olay günlüğünü döndürür. Bulunamazsa 404 döner.",
)
async def get_task(task_id: str) -> TaskResponse:
    task_repo = get_task_repository()
    task = task_repo.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{task_id}' kimlikli görev bulunamadı."
        )
    return task


@app.get(
    "/tasks",
    response_model=List[TaskResponse],
    tags=["Tasks"],
    summary="Tüm görevleri listele",
    description="SQLite veritabanında kayıtlı tüm görevleri oluşturulma tarihine göre azalan sırada döndürür.",
)
async def list_tasks() -> List[TaskResponse]:
    task_repo = get_task_repository()
    return task_repo.list_tasks()


@app.get(
    "/tasks/{task_id}/runs",
    response_model=WorkflowRunListResponse,
    tags=["Workflow", "History"],
    summary="Görevin iş akışı çalıştırma geçmişini listele",
    description="Belirtilen göreve ait tüm geçmiş iş akışı çalıştırmalarını kronolojik sırayla listeler.",
)
async def list_task_runs(task_id: str) -> WorkflowRunListResponse:
    task_repo = get_task_repository()
    run_repo = get_workflow_run_repository()

    task = task_repo.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{task_id}' kimlikli görev bulunamadı."
        )

    runs = run_repo.list_runs_for_task(task_id)
    return WorkflowRunListResponse(
        task_id=task_id,
        total_runs=len(runs),
        runs=runs
    )


@app.get(
    "/tasks/{task_id}/runs/{run_id}",
    response_model=WorkflowRun,
    tags=["Workflow", "History"],
    summary="Tekil çalıştırma detayını getir",
    description="Belirtilen çalıştırma ID'sine ait ayrıntılı sonuçları ve agent metriklerini döndürür.",
)
async def get_task_run(task_id: str, run_id: str) -> WorkflowRun:
    task_repo = get_task_repository()
    run_repo = get_workflow_run_repository()

    task = task_repo.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{task_id}' kimlikli görev bulunamadı."
        )

    run = run_repo.get_run(run_id)
    if not run or run.task_id != task_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{task_id}' görevine ait '{run_id}' kimlikli çalıştırma kaydı bulunamadı."
        )

    return run


def _persist_workflow_state(task_id: str, result_state: dict, updated_at: datetime):
    task_repo = get_task_repository()
    run_repo = get_workflow_run_repository()
    final_status = TaskStatus(result_state.get("status", TaskStatus.FAILED.value))
    updated = task_repo.update_task_workflow_result(
        task_id=task_id,
        status=final_status,
        plan=result_state.get("plan"),
        scope=result_state.get("scope"),
        coder=result_state.get("coder"),
        tester=result_state.get("tester"),
        reviewer=result_state.get("reviewer"),
        events=result_state.get("events") or [],
        error=result_state.get("error"),
        updated_at=updated_at,
    )
    runs = run_repo.list_runs_for_task(task_id)
    if runs:
        run_repo.complete_run(
            run_id=runs[-1].id,
            status=final_status,
            plan=result_state.get("plan"),
            scope=result_state.get("scope"),
            coder=result_state.get("coder"),
            tester=result_state.get("tester"),
            reviewer=result_state.get("reviewer"),
            events=result_state.get("events") or [],
            error=result_state.get("error"),
            completed_at=updated_at,
        )
    return updated


def _record_resume_failure(task, message: str):
    """Resume başarısızsa durumu completed yapmadan hatayı kaydeder."""
    task_repo = get_task_repository()
    now_dt = datetime.now(timezone.utc)
    events = list(task.events or [])
    events.append(TaskEvent(
        id=f"evt_{uuid.uuid4().hex[:8]}",
        timestamp=now_dt,
        source="ORCHESTRATOR",
        type="resume_failed",
        message=message,
        details={"status_preserved": task.status.value},
    ))
    return task_repo.update_task_workflow_result(
        task_id=task.id,
        status=task.status,
        plan=task.plan,
        scope=task.scope,
        coder=task.coder,
        tester=task.tester,
        reviewer=task.reviewer,
        events=events,
        error=message,
        updated_at=now_dt,
    )


@app.post(
    "/tasks/{task_id}/approve",
    response_model=TaskResponse,
    tags=["Tasks", "Approval"],
    summary="Görevi onayla ve teslim et (Human-in-the-Loop)",
    description="İncelemesi bitmiş görevi onaylar. completed yalnızca güncel içeriğin Git teslimatı da başarılıysa yazılır. Teslimat başarısızsa delivery_failed döner.",
)
async def approve_task(task_id: str, payload: Optional[TaskApprovalRequest] = None) -> TaskResponse:
    task_repo = get_task_repository()
    task = task_repo.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{task_id}' kimlikli görev bulunamadı."
        )

    task_lock = await get_task_lock(task_id)
    if task_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{task_id}' kimlikli görev için bir işlem şu anda çalışıyor."
        )

    async with task_lock:
        task = task_repo.get_task(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"'{task_id}' kimlikli görev bulunamadı."
            )
        if task.status == TaskStatus.COMPLETED:
            return task
        if task.reviewer and task.reviewer.verdict.value == "blocked":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reviewer güvenlik veya bütünlük engeli (BLOCKED) bildirdiği için görev onaylanamaz."
            )
        if task.status not in _APPROVABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"'{task.status.value}' durumundaki bir görev onaylanamaz. "
                    "Onay yalnızca reviewed veya awaiting_approval durumundaki görevler için geçerlidir."
                ),
            )
        if task.status == TaskStatus.AWAITING_APPROVAL:
            approver = payload.approved_by if payload and payload.approved_by else "reviewer_human"
            comment = payload.comment if payload and payload.comment else "İnsan onayı verildi."
            try:
                result_state = await resume_agent_workflow(
                    task_id,
                    {"action": "approve", "approved_by": approver, "comment": comment},
                )
            except WorkflowCheckpointError as exc:
                _record_resume_failure(task, str(exc))
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
            except Exception as exc:
                message = f"Onay resume başarısız oldu ({type(exc).__name__}). Görev completed yapılmadı."
                _record_resume_failure(task, message)
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message)

            if result_state.get("status") == TaskStatus.DELIVERY_FAILED.value:
                updated = _persist_workflow_state(task_id, result_state, datetime.now(timezone.utc))
                if not updated:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Görev durumu güncellenirken veritabanı hatası oluştu."
                    )
                return updated

            if result_state.get("status") != TaskStatus.COMPLETED.value:
                message = "Resume tamamlandı fakat görev completed olmadı. Durum completed yapılmadı."
                preserved = _record_resume_failure(task, message)
                if preserved:
                    task_repo.update_task_workflow_result(
                        task_id=task_id,
                        status=TaskStatus(result_state.get("status", TaskStatus.AWAITING_APPROVAL.value)),
                        plan=result_state.get("plan"),
                        scope=result_state.get("scope"),
                        coder=result_state.get("coder"),
                        tester=result_state.get("tester"),
                        reviewer=result_state.get("reviewer"),
                        events=result_state.get("events") or [],
                        error=message,
                        updated_at=datetime.now(timezone.utc),
                    )
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message)

            updated = _persist_workflow_state(task_id, result_state, datetime.now(timezone.utc))
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Görev durumu güncellenirken veritabanı hatası oluştu."
                )
            return updated

        approver = payload.approved_by if payload and payload.approved_by else "reviewer_human"
        comment = payload.comment if payload and payload.comment else "İnsan onayı verildi."

        now_dt = datetime.now(timezone.utc)
        approval_event = TaskEvent(
            id=f"evt_{uuid.uuid4().hex[:8]}",
            timestamp=now_dt,
            source="HUMAN_REVIEWER",
            type="task_approved",
            message=f"Görev insan onayı ile onaylandı ({approver}): {comment}",
            details={"approved_by": approver, "comment": comment}
        )

        reviewer_payload = task.reviewer.model_dump(mode="json") if task.reviewer else {}
        tester_payload = task.tester.model_dump(mode="json") if task.tester else {}
        if not has_completion_evidence(reviewer_payload, tester_payload):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Görev tamamlanamaz. Reviewer sonucu approved olmalı ve "
                    "başarısız olmayan en az bir test kanıtı bulunmalıdır."
                ),
            )

        delivery_state = _delivery_state_from_task(task)
        delivery_state["events"] = list(delivery_state["events"]) + [approval_event.model_dump(mode="json")]
        delivered = delivery_node(delivery_state)
        final_status = TaskStatus(str(delivered.get("status") or TaskStatus.DELIVERY_FAILED.value))
        stored_events = delivered.get("events") or []
        stored_error = delivered.get("error")

        updated = task_repo.update_task_workflow_result(
            task_id=task_id,
            status=final_status,
            plan=task.plan,
            scope=task.scope,
            coder=task.coder,
            tester=task.tester,
            reviewer=task.reviewer,
            events=stored_events,
            error=stored_error,
            updated_at=now_dt
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Görev durumu güncellenirken veritabanı hatası oluştu."
            )
        return updated


def _delivery_state_from_task(task: TaskResponse) -> Dict[str, Any]:
    """Kayıtlı görevden yalnızca teslimat düğümünün okuduğu durumu kurar."""
    events: List[Dict[str, Any]] = []
    require_human_approval = False
    for event in task.events or []:
        payload = event.model_dump(mode="json")
        details = payload.get("details") or {}
        if details.get("require_human_approval") is True:
            require_human_approval = True
        events.append(payload)

    def _dump(value: Any) -> Any:
        if value is None:
            return {}
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value

    return {
        "task_id": task.id,
        "status": task.status.value,
        "require_human_approval": require_human_approval,
        "reviewer": _dump(task.reviewer),
        "tester": _dump(task.tester),
        "coder": _dump(task.coder),
        "events": events,
        "error": task.error,
    }


@app.post(
    "/tasks/{task_id}/deliver",
    response_model=TaskResponse,
    tags=["Tasks", "Delivery"],
    summary="Git teslimatını yeniden dene",
    description="Planner ve Coder çalıştırmadan izole branch teslimatını yeniden dener. Aynı içerik duplicate commit açmaz.",
)
async def deliver_task_endpoint(task_id: str) -> TaskResponse:
    task_repo = get_task_repository()
    task = task_repo.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{task_id}' kimlikli görev bulunamadı."
        )

    task_lock = await get_task_lock(task_id)
    if task_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{task_id}' kimlikli görev için bir işlem şu anda çalışıyor."
        )

    async with task_lock:
        task = task_repo.get_task(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"'{task_id}' kimlikli görev bulunamadı."
            )
        allowed = {TaskStatus.DELIVERY_FAILED, TaskStatus.REVIEWED, TaskStatus.COMPLETED}
        if task.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"'{task.status.value}' durumundaki bir görevin teslimatı yeniden denenemez. "
                    "Teslimat reviewed, completed veya delivery_failed durumundaki görevler için geçerlidir."
                ),
            )
        result_state = delivery_node(_delivery_state_from_task(task))
        updated = task_repo.update_task_workflow_result(
            task_id=task_id,
            status=TaskStatus(result_state.get("status", task.status.value)),
            plan=task.plan,
            scope=task.scope,
            coder=task.coder,
            tester=task.tester,
            reviewer=task.reviewer,
            events=result_state.get("events") or [],
            error=result_state.get("error"),
            updated_at=datetime.now(timezone.utc),
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Teslimat sonucu kaydedilirken veritabanı hatası oluştu."
            )
        return updated


@app.post(
    "/tasks/{task_id}/reject",
    response_model=TaskResponse,
    tags=["Tasks", "Approval"],
    summary="Görevi reddet / değişiklik talep et (Human-in-the-Loop)",
    description="İnceleme sonucunda görevi reddederek 'changes_requested' durumuna alır.",
)
async def reject_task(task_id: str, payload: TaskRejectRequest) -> TaskResponse:
    task_repo = get_task_repository()
    task = task_repo.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{task_id}' kimlikli görev bulunamadı."
        )

    task_lock = await get_task_lock(task_id)
    if task_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{task_id}' kimlikli görev için bir işlem şu anda çalışıyor."
        )

    async with task_lock:
        task = task_repo.get_task(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"'{task_id}' kimlikli görev bulunamadı."
            )
        if task.status == TaskStatus.CHANGES_REQUESTED:
            return task
        if task.status not in _REJECTABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"'{task.status.value}' durumundaki bir görev reddedilemez. "
                    "Ret yalnızca reviewed veya awaiting_approval durumundaki görevler için geçerlidir."
                ),
            )
        if task.status == TaskStatus.AWAITING_APPROVAL:
            rejecter = payload.rejected_by or "reviewer_human"
            try:
                result_state = await resume_agent_workflow(
                    task_id,
                    {
                        "action": "reject",
                        "rejected_by": rejecter,
                        "reason": payload.reason,
                    },
                )
            except WorkflowCheckpointError as exc:
                _record_resume_failure(task, str(exc))
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
            except Exception as exc:
                message = f"Ret resume başarısız oldu ({type(exc).__name__}). Görev completed yapılmadı."
                _record_resume_failure(task, message)
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message)

            if result_state.get("status") == TaskStatus.COMPLETED.value:
                message = "Ret resume görevi completed yaptı. Bu sonuç kaydedilmedi."
                _record_resume_failure(task, message)
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=message)

            updated = _persist_workflow_state(task_id, result_state, datetime.now(timezone.utc))
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Görev durumu güncellenirken veritabanı hatası oluştu."
                )
            return updated

        rejecter = payload.rejected_by or "reviewer_human"
        now_dt = datetime.now(timezone.utc)
        reject_event = TaskEvent(
            id=f"evt_{uuid.uuid4().hex[:8]}",
            timestamp=now_dt,
            source="HUMAN_REVIEWER",
            type="task_rejected",
            message=f"Görev insan incelemesinde reddedildi ({rejecter}): {payload.reason}",
            details={"rejected_by": rejecter, "reason": payload.reason}
        )

        events = list(task.events or [])
        events.append(reject_event)

        updated = task_repo.update_task_workflow_result(
            task_id=task_id,
            status=TaskStatus.CHANGES_REQUESTED,
            plan=task.plan,
            scope=task.scope,
            coder=task.coder,
            tester=task.tester,
            reviewer=task.reviewer,
            error=f"İnsan incelemesi reddi: {payload.reason}",
            events=events,
            updated_at=now_dt
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Görev durumu güncellenirken veritabanı hatası oluştu."
            )
        return updated


@app.post(
    "/tasks/{task_id}/cancel",
    response_model=TaskResponse,
    tags=["Tasks", "Workflow"],
    summary="Görevi iptal et",
    description="Kuyruktaki veya bekleyen bir görevi 'cancelled' durumuna alır.",
)
async def cancel_task(task_id: str) -> TaskResponse:
    task_repo = get_task_repository()
    task = task_repo.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{task_id}' kimlikli görev bulunamadı."
        )

    if task.status == TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tamamlanmış bir görev iptal edilemez."
        )

    now_dt = datetime.now(timezone.utc)
    cancel_event = TaskEvent(
        id=f"evt_{uuid.uuid4().hex[:8]}",
        timestamp=now_dt,
        source="ORCHESTRATOR",
        type="task_cancelled",
        message="Görev kullanıcı/orkestratör tarafından iptal edildi.",
        details={}
    )

    events = list(task.events or [])
    events.append(cancel_event)

    updated = task_repo.update_task_workflow_result(
        task_id=task_id,
        status=TaskStatus.CANCELLED,
        events=events,
        updated_at=now_dt
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Görev iptal edilirken veritabanı hatası oluştu."
        )
    return updated


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_excludes=["workspaces/*", "*.db", "*.db-journal", ".pytest_cache/*", "__pycache__/*"]
    )

