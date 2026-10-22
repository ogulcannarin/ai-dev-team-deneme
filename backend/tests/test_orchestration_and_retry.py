"""
backend/tests/test_orchestration_and_retry.py
AI Dev Team - Agent Orchestration, Kontrollü Retry ve İnsan Onayı Test Paketi
"""

import asyncio
import os
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import agent_workflow
from database import init_db
from execution import ExecutionResult
from execution.mock_engine import MockExecutionEngine
from main import app, _persist_workflow_state, get_task_repository, get_workflow_run_repository
from repository import TaskRepository, WorkflowRunRepository
from schemas import (
    ReviewerVerdict,
    TaskApprovalRequest,
    TaskRejectRequest,
    TaskScope,
    TaskStatus,
)
from agent_workflow import (
    _execute_coder_in_workspace,
    _execute_reviewer_in_workspace,
    _execute_tester_in_workspace,
    _route_after_tester,
    fix_exhausted_node,
    run_agent_workflow,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Her test için izole geçici SQLite veritabanı oluşturur."""
    test_db_file = str(tmp_path / "test_orchestration.db")
    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", test_db_file)
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")
    init_db(test_db_file)
    yield


@pytest.fixture
def client():
    return TestClient(app)


# =====================================================================
# 1. BÖLÜM: Kontrollü Retry ve Döngü Sınırı Testleri
# =====================================================================

def test_workflow_retry_on_tester_failure(monkeypatch):
    """İlk test başarısızlığı Coder'ı farklı içerik üretmeye iter; ikinci başarı Reviewer'a ulaşır."""
    task_id = "task_test_retry_success"
    description = "FastAPI Items CRUD REST API"
    task_repo = TaskRepository()
    task_repo.create_task(task_id, description)

    generated_models = []

    def scripted_code_files(generated_task_id, generated_description):
        del generated_task_id, generated_description
        if not generated_models:
            models = "BUG_MARKER = True\n"
        else:
            models = "RETRY_FIX_APPLIED = True\n"
        generated_models.append(models)
        return {
            "models.py": models,
            "api_feature.py": "def list_items():\n    return []\n",
            "README.md": "Items API usage example.\n",
        }

    class ContentAwareMockEngine(MockExecutionEngine):
        def __init__(self):
            super().__init__()
            self.observed_models = []

        def is_available(self):
            return True

        def get_isolation_type(self):
            return "mock"

        def execute_sync(self, workspace_path, command, config=None):
            del command, config
            models_path = os.path.join(workspace_path, "models.py")
            try:
                with open(models_path, "r", encoding="utf-8") as handle:
                    content = handle.read()
            except OSError:
                content = ""
            self.observed_models.append(content)
            if "RETRY_FIX_APPLIED" in content:
                raw_output = "test_items (test_feature.TestItems) ... ok\n\nRan 1 test in 0.001s\n\nOK\n"
                return ExecutionResult(
                    status="success",
                    exit_code=0,
                    stdout=raw_output,
                    stderr="",
                    duration_ms=10.0,
                    isolation_type="mock",
                    raw_output=raw_output,
                    error=None,
                )
            raw_output = (
                "test_items (test_feature.TestItems) ... FAIL\n\n"
                "======================================================================\n"
                "FAIL: test_items\n"
                "AssertionError: BUG_MARKER\n\n"
                "Ran 1 test in 0.001s\n\nFAILED (failures=1)\n"
            )
            return ExecutionResult(
                status="failed",
                exit_code=1,
                stdout=raw_output,
                stderr="",
                duration_ms=10.0,
                isolation_type="mock",
                raw_output=raw_output,
                error="1 test başarısız oldu.",
            )

    engine = ContentAwareMockEngine()
    monkeypatch.setattr(agent_workflow, "_generate_deterministic_code_files", scripted_code_files)
    monkeypatch.setattr(agent_workflow, "get_execution_engine", lambda preferred=None: engine)

    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description=description,
        planner_mode="deterministic",
        coder_mode="deterministic",
        max_retries=1,
        require_human_approval=True,
    ))

    assert len(generated_models) == 2
    assert generated_models[0] != generated_models[1]
    assert len(engine.observed_models) == 2
    assert "BUG_MARKER" in engine.observed_models[0]
    assert "RETRY_FIX_APPLIED" in engine.observed_models[1]

    models_path = os.path.join(os.path.dirname(__file__), "..", "workspaces", task_id, "models.py")
    with open(models_path, "r", encoding="utf-8") as handle:
        assert "RETRY_FIX_APPLIED" in handle.read()

    assert result["retry_count"] == 1
    assert len(result["retry_history"]) == 1
    assert result["retry_history"][0]["attempt"] == 1
    assert result["retry_history"][0]["tester"]["status"] == "failed"

    tester = result["tester"]
    assert tester["status"] in {"tested", "passed"}
    assert tester["failed"] == 0
    assert tester["passed"] > 0
    assert tester["isolation_type"] == "mock"
    assert result["reviewer"] is not None

    event_types = [event.get("type") for event in result.get("events") or []]
    assert "retry_triggered" in event_types
    assert "coder_retry_started" in event_types
    assert "reviewer_started" in event_types or "reviewer_completed" in event_types
    assert "tester_blocked" not in event_types
    assert "test_retries_exhausted" not in event_types
    assert all(
        (event.get("details") or {}).get("reason") != "test_retries_exhausted"
        for event in result.get("events") or []
    )
    limitations = (result.get("coder") or {}).get("limitations") or []
    assert all("içerik değişmedi" not in item for item in limitations)


def test_deterministic_retry_stops_when_content_unchanged(monkeypatch):
    """Yamalanmamış deterministik şablon aynı baytı üretince retry dürüstçe durur."""
    task_id = "task_deterministic_unchanged_retry"
    description = "FastAPI Items CRUD REST API"
    task_repo = TaskRepository()
    task_repo.create_task(task_id, description)

    class AlwaysFailingTester(MockExecutionEngine):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def is_available(self):
            return True

        def get_isolation_type(self):
            return "mock"

        def execute_sync(self, workspace_path, command, config=None):
            del workspace_path, command, config
            self.calls += 1
            raw_output = (
                "test_items (test_feature.TestItems) ... FAIL\n\n"
                "======================================================================\n"
                "FAIL: test_items\n"
                "AssertionError: template unchanged\n\n"
                "Ran 1 test in 0.001s\n\nFAILED (failures=1)\n"
            )
            return ExecutionResult(
                status="failed",
                exit_code=1,
                stdout=raw_output,
                stderr="",
                duration_ms=10.0,
                isolation_type="mock",
                raw_output=raw_output,
                error="1 test başarısız oldu.",
            )

    engine = AlwaysFailingTester()
    monkeypatch.setattr(agent_workflow, "get_execution_engine", lambda preferred=None: engine)

    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description=description,
        planner_mode="deterministic",
        coder_mode="deterministic",
        max_retries=2,
        require_human_approval=True,
    ))

    assert engine.calls == 1
    assert result["status"] == TaskStatus.FAILED.value
    assert result["retry_count"] == 1
    assert len(result["retry_history"]) == 1
    assert result["retry_history"][0]["attempt"] == 1
    assert result["retry_history"][0]["tester"]["status"] == "failed"
    assert result["coder"]["status"] == "failed"
    assert "deterministik şablon aynı içeriği üretiyor" in (result.get("error") or "")

    event_types = [event.get("type") for event in result.get("events") or []]
    assert event_types.count("tester_started") == 1
    assert event_types.count("retry_triggered") == 1
    assert "coder_retry_no_change" in event_types
    assert "coder_failed" in event_types
    assert "reviewer_completed" not in event_types
    assert "retry_exhausted" not in event_types
    assert "test_retries_exhausted" not in event_types
    assert all(
        (event.get("details") or {}).get("reason") != "test_retries_exhausted"
        for event in result.get("events") or []
    )


def test_workflow_never_retries_on_security_block(monkeypatch):
    """Güvenlik ihlali veya BLOCKED durumunda asla retry yapılmamalı, akış derhal durmalıdır."""
    task_id = "task_test_no_retry_on_block"

    with tempfile.TemporaryDirectory() as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        # Zararlı socket import içeren dosya
        with open(os.path.join(task_ws, "api_feature.py"), "w", encoding="utf-8") as f:
            f.write("import socket\ns = socket.socket()\n")

        mock_engine = MockExecutionEngine()
        tester_res = _execute_tester_in_workspace(
            task_id=task_id,
            description="Socket feature",
            workspaces_root=temp_root,
            engine=mock_engine
        )
        assert tester_res.status == "blocked"

        reviewer_res = _execute_reviewer_in_workspace(
            task_id=task_id,
            description="Socket feature",
            coder_data={"status": "coded", "created_files": ["api_feature.py"]},
            tester_data=tester_res.model_dump(),
            workspaces_root=temp_root
        )

        assert reviewer_res.verdict == ReviewerVerdict.BLOCKED
        assert reviewer_res.status == "blocked"


def test_retry_history_and_snapshots_preserved():
    """Retry yapıldığında önceki denemelerin snapshot'ı retry_history içinde saklanmalıdır."""
    task_id = "task_test_retry_snapshots"
    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description="FastAPI REST API CRUD",
        max_retries=1
    ))

    assert "retry_history" in result
    assert isinstance(result["retry_history"], list)
    assert result.get("retry_count", 0) <= 1


# =====================================================================
# 2. BÖLÜM: İnsan Onayı (Human-in-the-Loop), Red ve İptal API Testleri
# =====================================================================

def test_human_approval_flow_success(client):
    """İnceleme aşamasından geçmiş geçerli bir görev insan onayı ile COMPLETED yapılabilir."""
    # 1. Görev oluştur ve çalıştır
    create_res = client.post("/tasks", json={"description": "FastAPI Items REST API"})
    assert create_res.status_code == 201
    task_id = create_res.json()["id"]

    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200
    assert run_res.json()["status"] == TaskStatus.REVIEWED.value

    # 2. İnsan onayı ver
    approve_res = client.post(
        f"/tasks/{task_id}/approve",
        json={"comment": "Kod incelendi ve üretime uygun bulundu.", "approved_by": "lead_architect"}
    )
    assert approve_res.status_code == 200
    approved_data = approve_res.json()
    assert approved_data["status"] == TaskStatus.COMPLETED.value

    # Event kaydını doğrula
    events = approved_data["events"]
    approval_evt = next((e for e in events if e["type"] == "task_approved"), None)
    assert approval_evt is not None
    assert approval_evt["details"]["approved_by"] == "lead_architect"
    assert "uygun bulundu" in approval_evt["details"]["comment"]


def test_human_approval_rejected_on_blocked_or_failed_task(client):
    """Bloke edilmiş veya başarısız bir görev onaylanamaz (400 Bad Request)."""
    task_repo = TaskRepository()
    task = task_repo.create_task("task_blocked_test", "Blocked task")
    task_repo.update_task_workflow_result("task_blocked_test", status=TaskStatus.BLOCKED, error="Güvenlik ihlali")

    approve_res = client.post("/tasks/task_blocked_test/approve", json={"comment": "Onaylamaya çalış"})
    assert approve_res.status_code == 400
    assert "onaylanamaz" in approve_res.json()["detail"].lower()


def test_human_rejection_flow(client):
    """İnsan incelemesinde görev reddedildiğinde durumu CHANGES_REQUESTED olmalıdır."""
    create_res = client.post("/tasks", json={"description": "FastAPI Auth JWT Service"})
    task_id = create_res.json()["id"]

    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200

    reject_res = client.post(
        f"/tasks/{task_id}/reject",
        json={"reason": "Test kapsamı yetersiz, ek edge-case testleri gerekli.", "rejected_by": "qa_lead"}
    )
    assert reject_res.status_code == 200
    rejected_data = reject_res.json()
    assert rejected_data["status"] == TaskStatus.CHANGES_REQUESTED.value
    assert "qa_lead" in rejected_data["error"] or "qa_lead" in str(rejected_data["events"])


def test_task_cancellation_flow(client):
    """Kuyruktaki veya çalışan görev iptal edilebilir, tamamlanmış görev iptal edilemez."""
    create_res = client.post("/tasks", json={"description": "Task to cancel"})
    task_id = create_res.json()["id"]

    # İptal et
    cancel_res = client.post(f"/tasks/{task_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == TaskStatus.CANCELLED.value

    # Tamamlanmış görevin iptali 400 dönmeli
    completed_task = TaskRepository().create_task("task_already_done", "Done task", status=TaskStatus.COMPLETED)
    cancel_completed = client.post(f"/tasks/{completed_task.id}/cancel")
    assert cancel_completed.status_code == 400


# =====================================================================
# 3. BÖLÜM: Eşzamanlılık ve Çakışma Koruması Testleri
# =====================================================================

def test_tester_routes_keep_retry_count_and_split_block_reasons():
    """İlk başarı sayacı artırmaz. İzolasyon engeli retry başlatmaz. Tükenme ayrı gerekçe yazar."""
    success = {
        "tester": {"status": "tested", "passed": 4, "failed": 0},
        "retry_count": 0,
        "max_retries": 2,
        "retry_history": [],
    }
    assert _route_after_tester(success) == "reviewer"
    assert success["retry_count"] == 0
    assert success["retry_history"] == []

    blocked = {"tester": {"status": "blocked", "error": "Docker daemon unavailable"}, "retry_count": 0, "max_retries": 2}
    assert _route_after_tester(blocked) == "reviewer"
    assert blocked["retry_count"] == 0

    first_failure = {"tester": {"status": "failed", "passed": 1, "failed": 1}, "retry_count": 0, "max_retries": 2}
    assert _route_after_tester(first_failure) == "retry"
    assert first_failure["retry_count"] == 0

    exhausted_route = {"tester": {"status": "failed", "passed": 0, "failed": 1}, "retry_count": 2, "max_retries": 2, "events": []}
    assert _route_after_tester(exhausted_route) == "fix_exhausted"
    result = fix_exhausted_node(exhausted_route)
    assert result["status"] == TaskStatus.BLOCKED.value
    assert result["retry_count"] == 2
    assert "test_retries_exhausted" in result["error"]
    assert result["events"][-1]["details"]["reason"] == "test_retries_exhausted"
    assert "reviewer_completed" not in [event["type"] for event in result["events"]]


def test_scope_allowlist_rejects_overwrite_outside_scope(tmp_path):
    """allow_overwrite=True Scope dışındaki dosyayı yazamaz."""
    scope = TaskScope(
        summary="hesap",
        existing_files=[],
        proposed_new_files=["backend/calculator.py"],
        out_of_scope=[".env"],
        risks=[],
    )
    rejected = _execute_coder_in_workspace(
        task_id="task_scope_guard",
        description="Create calculator.py",
        scope=scope,
        workspaces_root=str(tmp_path),
        allow_overwrite=True,
        code_files={"middleware.py": "print('no')\n"},
    )
    assert rejected.status == "failed"
    assert "Scope dışı dosya" in (rejected.error or "")
    assert not (tmp_path / "task_scope_guard" / "middleware.py").exists()

    workspace = tmp_path / "task_same_content"
    workspace.mkdir()
    (workspace / "calculator.py").write_text("same\n", encoding="utf-8")
    unchanged = _execute_coder_in_workspace(
        task_id="task_same_content",
        description="Create calculator.py",
        scope=scope,
        workspaces_root=str(tmp_path),
        allow_overwrite=True,
        code_files={"calculator.py": "same\n"},
        tester_feedback={
            "status": "failed",
            "error": "AssertionError: expected 5",
            "test_results": [{"name": "test_01_addition_operations", "status": "failed", "error": "expected 5"}],
        },
        prior_created_files=["workspaces/task_same_content/calculator.py"],
    )
    assert unchanged.status == "failed"
    assert "deterministik şablon aynı içeriği üretiyor" in (unchanged.error or "")
    assert any("içerik değişmedi" in item for item in unchanged.limitations)
    assert (workspace / "calculator.py").read_text(encoding="utf-8") == "same\n"


def test_empty_scope_proposal_rejects_unapproved_file(tmp_path):
    """Scope önerisi boşken beyaz listedeki bir dosya da yazılamaz."""
    scope = TaskScope(
        summary="bos",
        existing_files=[],
        proposed_new_files=[],
        out_of_scope=[".env"],
        risks=[],
    )
    rejected = _execute_coder_in_workspace(
        task_id="task_empty_scope",
        description="FastAPI Items CRUD REST API",
        scope=scope,
        workspaces_root=str(tmp_path),
        allow_overwrite=True,
        code_files={"models.py": "class Item: pass\n"},
    )
    assert rejected.status == "failed"
    assert "Scope dışı dosya" in (rejected.error or "")
    assert not (tmp_path / "task_empty_scope" / "models.py").exists()


def test_reviewer_change_request_does_not_pretend_template_changed(tmp_path):
    """Aynı şablon Reviewer talebiyle başarılı düzeltme sayılmaz. Farklı içerik yazılabilir."""
    scope = TaskScope(
        summary="hesap",
        existing_files=[],
        proposed_new_files=["calculator.py"],
        out_of_scope=[],
        risks=[],
    )
    workspace = tmp_path / "task_reviewer_same"
    workspace.mkdir()
    (workspace / "calculator.py").write_text("same\n", encoding="utf-8")
    stuck = _execute_coder_in_workspace(
        task_id="task_reviewer_same",
        description="Create calculator.py",
        scope=scope,
        workspaces_root=str(tmp_path),
        allow_overwrite=True,
        coder_mode="deterministic",
        code_files={"calculator.py": "same\n"},
        reviewer_feedback={
            "verdict": "changes_requested",
            "summary": "Eksik docstring giderilmeli.",
            "findings": [{"severity": "low", "title": "Docstring", "description": "add fonksiyonu belgelenmeli", "recommendation": "Docstring ekle"}],
        },
        tester_feedback={"status": "tested", "passed": 4, "failed": 0, "error": None},
    )
    assert stuck.status == "failed"
    assert "deterministik şablon" in (stuck.error or "")
    assert stuck.status != "coded"
    assert (workspace / "calculator.py").read_text(encoding="utf-8") == "same\n"

    changed = _execute_coder_in_workspace(
        task_id="task_reviewer_same",
        description="Create calculator.py",
        scope=scope,
        workspaces_root=str(tmp_path),
        allow_overwrite=True,
        coder_mode="deterministic",
        code_files={"calculator.py": "def add(a, b):\n    return a + b\n"},
        reviewer_feedback={"verdict": "changes_requested", "summary": "Docstring", "findings": []},
        tester_feedback={"status": "tested", "passed": 4, "failed": 0},
    )
    assert changed.status == "coded"
    assert "return a + b" in (workspace / "calculator.py").read_text(encoding="utf-8")


def test_resume_persist_keeps_retry_on_task_and_run(tmp_path, monkeypatch):
    """Onay veya ret sonrası kalıcılık görev ve workflow-run retry kayıtlarını birlikte yazar."""
    db_path = str(tmp_path / "resume_retry.db")
    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", db_path)
    init_db(db_path)
    tasks = TaskRepository(db_path)
    runs = WorkflowRunRepository(db_path)
    tasks.create_task("task_resume_retry", "Calculator")
    runs.create_run("task_resume_retry")
    history = [{"attempt": 1, "tester": {"status": "failed", "error": "AssertionError"}}]
    updated = _persist_workflow_state(
        "task_resume_retry",
        {
            "status": TaskStatus.CHANGES_REQUESTED.value,
            "retry_count": 1,
            "retry_history": history,
            "events": [],
            "error": "İnsan incelemesi reddi: ek test gerekli.",
        },
        datetime.now(timezone.utc),
    )
    assert updated is not None
    assert updated.retry_count == 1
    assert updated.retry_history[0]["attempt"] == 1
    stored_runs = runs.list_runs_for_task("task_resume_retry")
    assert stored_runs[-1].retry_count == updated.retry_count
    assert stored_runs[-1].retry_history[0]["tester"]["status"] == "failed"
    fetched = tasks.get_task("task_resume_retry")
    assert fetched is not None
    assert fetched.retry_count == stored_runs[-1].retry_count
    assert fetched.retry_history == stored_runs[-1].retry_history


def test_retry_fields_persist_on_task_and_workflow_run(tmp_path):
    """retry_count ve retry_history görev ve çalıştırma kayıtlarında kalır."""
    db_path = str(tmp_path / "retry_persist.db")
    init_db(db_path)
    tasks = TaskRepository(db_path)
    runs = WorkflowRunRepository(db_path)
    tasks.create_task("task_retry_persist", "Calculator")
    history = [{"attempt": 1, "tester": {"status": "failed", "error": "AssertionError"}}]
    updated = tasks.update_task_workflow_result(
        "task_retry_persist",
        status=TaskStatus.BLOCKED,
        error="Test düzeltme denemeleri tükendi (reason=test_retries_exhausted).",
        retry_count=2,
        retry_history=history,
    )
    assert updated is not None
    assert updated.retry_count == 2
    assert updated.retry_history[0]["attempt"] == 1
    fetched = tasks.get_task("task_retry_persist")
    assert fetched is not None
    assert fetched.retry_count == 2
    assert "test_retries_exhausted" in (fetched.error or "")

    created = runs.create_run("task_retry_persist")
    completed = runs.complete_run(
        created.id,
        status=TaskStatus.BLOCKED,
        error=fetched.error,
        retry_count=2,
        retry_history=history,
    )
    assert completed is not None
    assert completed.retry_count == 2
    assert completed.retry_history[0]["tester"]["status"] == "failed"
    stored = runs.get_run(created.id)
    assert stored is not None
    assert stored.retry_count == 2


def test_duplicate_concurrent_run_conflict(client):
    """Aynı görev için aynı anda iki kez run çağrıldığında kilit mekanizması 409 Conflict veya güvenli sıra sağlamalıdır."""
    create_res = client.post("/tasks", json={"description": "FastAPI Concurrent Lock Test"})
    task_id = create_res.json()["id"]

    # Sıralı iki run başarıyla tamamlanmalı ve geçmişe iki ayrı kayıt düşmelidir
    run1 = client.post(f"/tasks/{task_id}/run")
    assert run1.status_code == 200

    run2 = client.post(f"/tasks/{task_id}/run")
    assert run2.status_code == 200

    runs_res = client.get(f"/tasks/{task_id}/runs")
    assert runs_res.status_code == 200
    assert runs_res.json()["total_runs"] == 2
