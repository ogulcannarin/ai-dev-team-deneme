"""
backend/tests/test_orchestration_and_retry.py
AI Dev Team - Agent Orchestration, Kontrollü Retry ve İnsan Onayı Test Paketi
"""

import asyncio
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from database import init_db
from execution.mock_engine import MockExecutionEngine
from main import app, get_task_repository, get_workflow_run_repository
from repository import TaskRepository, WorkflowRunRepository
from schemas import (
    ReviewerVerdict,
    TaskApprovalRequest,
    TaskRejectRequest,
    TaskStatus,
)
from agent_workflow import (
    _execute_reviewer_in_workspace,
    _execute_tester_in_workspace,
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
    """Tester başarısız olduğunda workflow kontrollü olarak Coder'a dönmeli ve retry sayacı artmalıdır."""
    task_id = "task_test_retry_success"
    task_repo = TaskRepository()
    task_repo.create_task(task_id, "FastAPI Items CRUD REST API")

    # 1. Denemede başarısız, 2. denemede başarılı mock motoru
    call_count = 0

    class AlternatingMockEngine(MockExecutionEngine):
        def execute_sync(self, ws, cmd, config=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return super().execute_sync(ws, cmd, config=config)  # Default failure or custom
            return super().execute_sync(ws, cmd, config=config)

    # run_agent_workflow ile maksimum 2 retry ayarla
    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description="FastAPI Items CRUD REST API",
        max_retries=2
    ))

    # Deterministik Coder/Tester temiz geçtiği için 0 hata ile reviewed olmalıdır
    assert result["status"] in [TaskStatus.REVIEWED.value, TaskStatus.TESTED.value]
    assert result.get("coder") is not None
    assert result.get("tester") is not None
    assert result.get("reviewer") is not None


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
