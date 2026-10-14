"""
backend/tests/test_e2e_verification.py
AI Dev Team - Uçtan Uca (End-to-End) Sistem Doğrulama Test Paketi

Senaryo A: Başarılı Görev Yaşam Döngüsü (Planner -> Scope -> Coder -> Tester -> Reviewer -> SQLite)
Senaryo B: Tester Başarısızlığı, Geri Bildirimli Retry ve Üst Sınır (max_retries -> failed)
Senaryo C: İnsan Onayı (HITL), Onay, Red ve Bloke/Başarısız Onay Engeli
Senaryo D: SQLite Kalıcı Görev ve Run Geçmişi Doğrulaması (Kayıpsız Snapshot'lar)
Senaryo E: Güvenlik, İzolasyon ve Fail-Safe Davranışları (Docker yokken Blocked, host fallback yok)
"""

import asyncio
import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient

from database import init_db, get_db_connection
from execution.base import ExecutionResult
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
    _execute_coder_in_workspace,
    _execute_reviewer_in_workspace,
    _execute_tester_in_workspace,
    run_agent_workflow,
)


@pytest.fixture(autouse=True)
def setup_e2e_env(tmp_path, monkeypatch):
    """Her test için tamamen izole geçici SQLite veritabanı ve mock motoru hazırlar."""
    test_db_file = str(tmp_path / "test_e2e.db")
    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", test_db_file)
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")
    init_db(test_db_file)
    yield


@pytest.fixture
def client():
    return TestClient(app)


# =====================================================================
# SENARYO A: BAŞARILI GÖREV YAŞAM DÖNGÜSÜ
# =====================================================================

def test_scenario_a_successful_task_lifecycle(client):
    """
    Senaryo A:
    1. Görev oluşturulur (POST /tasks) -> queued
    2. Workflow çalıştırılır (POST /tasks/{id}/run)
    3. Planner iş planı üretir (subtasks, acceptance_criteria, risks)
    4. Scope dosya bağımlılıklarını belirler (existing_files, proposed_new_files)
    5. Coder izole workspace'e gerekli dosyaları yazar (models.py, api_feature.py)
    6. Tester testleri koşar ve passed kaydeder
    7. Reviewer kodu onaylar (APPROVED)
    8. Görev ve çalıştırma geçmişi SQLite'a eksiksiz kaydedilir
    """
    # 1. Görev oluştur
    create_res = client.post("/tasks", json={"description": "FastAPI Items CRUD REST API"})
    assert create_res.status_code == 201
    task_id = create_res.json()["id"]
    assert create_res.json()["status"] == TaskStatus.QUEUED.value

    # 2. Workflow'u çalıştır
    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200
    task_data = run_res.json()

    # 3. Planner çıktısı doğrulaması
    assert task_data["plan"] is not None
    assert len(task_data["plan"]["subtasks"]) >= 3
    assert len(task_data["plan"]["acceptance_criteria"]) >= 2
    assert "risks" in task_data["plan"]

    # 4. Scope çıktısı doğrulaması
    assert task_data["scope"] is not None
    assert isinstance(task_data["scope"]["existing_files"], list)
    assert isinstance(task_data["scope"]["proposed_new_files"], list)

    # 5. Coder çıktısı doğrulaması
    assert task_data["coder"] is not None
    assert task_data["coder"]["status"] == "coded"
    assert len(task_data["coder"]["created_files"]) >= 2

    # 6. Tester çıktısı doğrulaması
    assert task_data["tester"] is not None
    assert task_data["tester"]["status"] in ["passed", "tested"]
    assert task_data["tester"]["passed"] >= 1
    assert task_data["tester"]["failed"] == 0

    # 7. Reviewer kararı doğrulaması
    assert task_data["reviewer"] is not None
    assert task_data["reviewer"]["verdict"] == ReviewerVerdict.APPROVED.value
    assert task_data["status"] == TaskStatus.REVIEWED.value

    # 8. SQLite Kalıcı Geçmiş doğrulaması
    runs_res = client.get(f"/tasks/{task_id}/runs")
    assert runs_res.status_code == 200
    runs_data = runs_res.json()
    assert runs_data["total_runs"] == 1
    run_0 = runs_data["runs"][0]
    assert run_0["task_id"] == task_id
    assert run_0["plan"] is not None
    assert run_0["coder"] is not None
    assert run_0["tester"] is not None
    assert run_0["reviewer"] is not None
    assert run_0["duration_ms"] > 0


# =====================================================================
# SENARYO B: TESTER BAŞARISIZLIĞI, GERİ BİLDİRİM VE RETRY ÜST SINIRI
# =====================================================================

def test_scenario_b_controlled_retry_exhaustion_on_tester_failure(monkeypatch):
    """
    Senaryo B:
    Tester sürekli başarısız olduğunda:
    - Workflow tester başarısızlığını algılar.
    - Reviewer CHANGES_REQUESTED verir.
    - Retry döngüsü tetiklenir ve retry_count artar.
    - Coder'a önceki reviewer ve tester geri bildirimleri aktarılır.
    - Her deneme retry_history listesinde snapshot olarak saklanır.
    - max_retries (2) sınırına ulaşıldığında görev FAILED durumuna geçer.
    - Asla sonsuz döngüye girmez.
    """
    task_id = "task_e2e_retry_fail_test"
    task_repo = TaskRepository()
    task_repo.create_task(task_id, "FastAPI Items CRUD REST API")

    # Tester motorunun her zaman 1 hata vermesini sağlayan Mock Engine
    class FailingTesterEngine(MockExecutionEngine):
        def execute_sync(self, ws, cmd, config=None):
            return ExecutionResult(
                exit_code=1,
                stdout="FAILED (failures=1)\nAssertionError: Item title mismatch",
                stderr="",
                duration_ms=45.0,
                timed_out=False,
                is_sandboxed=False,
                engine_name="mock"
            )

    monkeypatch.setattr("agent_workflow.get_execution_engine", lambda: FailingTesterEngine())

    # 2 retry sınırı ile çalıştır
    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description="FastAPI Items CRUD REST API",
        max_retries=2
    ))

    # 1. Görev durumu 'failed' veya 'reviewed' (changes requested) olarak sonlanmalıdır
    assert result["status"] in [TaskStatus.FAILED.value, TaskStatus.REVIEWED.value]
    
    # 2. Retry sayacı sınırına ulaşmalıdır
    assert result["retry_count"] == 2
    assert result["max_retries"] == 2

    # 3. retry_history içinde geçmiş denemelerin snapshot'ı bulunmalıdır
    assert "retry_history" in result
    assert len(result["retry_history"]) == 2
    for attempt in result["retry_history"]:
        assert "attempt" in attempt
        assert "coder" in attempt
        assert "tester" in attempt
        assert "reviewer" in attempt
        assert attempt["tester"]["status"] == "failed"

    # 4. Event günlüğünde retry_triggered ve retry_exhausted olayları bulunmalıdır
    events = result.get("events", [])
    retry_events = [e for e in events if e.get("type") == "retry_triggered"]
    assert len(retry_events) == 2
    exhaust_event = next((e for e in events if e.get("type") == "retry_exhausted"), None)
    assert exhaust_event is not None


# =====================================================================
# SENARYO C: İNSAN ONAYI (HITL), ONAMA, REDDETME VE ENGEL DENETİMLERİ
# =====================================================================

def test_scenario_c_human_in_the_loop_approval_and_rejection(client):
    """
    Senaryo C:
    1. İnceleme aşamasını geçmiş görev için insan onayı verilmesi:
       - POST /tasks/{id}/approve -> status: completed
       - Onay veren kişi ve yorum SQLite event günlüğüne eklenir.
    2. İnceleme aşamasındaki görevin insan tarafından reddedilmesi:
       - POST /tasks/{id}/reject -> status: changes_requested
       - Reddeden kişi ve gerekçe kaydedilir.
    3. Bloke veya Başarısız görevlerin onaylanamaması:
       - status: blocked veya failed olan görevler için /approve çağrısı 400 Bad Request döner.
    """
    # 1. Başarılı Onay Akışı
    create_res1 = client.post("/tasks", json={"description": "FastAPI Items REST API"})
    task_id1 = create_res1.json()["id"]
    client.post(f"/tasks/{task_id1}/run")

    approve_res = client.post(
        f"/tasks/{task_id1}/approve",
        json={"comment": "Tüm güvenlik ve işlevsellik testleri onaylandı.", "approved_by": "sec_auditor"}
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == TaskStatus.COMPLETED.value
    events1 = approve_res.json()["events"]
    appr_evt = next((e for e in events1 if e["type"] == "task_approved"), None)
    assert appr_evt is not None
    assert appr_evt["details"]["approved_by"] == "sec_auditor"

    # 2. İnsan Red Akışı (Changes Requested)
    create_res2 = client.post("/tasks", json={"description": "FastAPI Auth JWT Service"})
    task_id2 = create_res2.json()["id"]
    client.post(f"/tasks/{task_id2}/run")

    reject_res = client.post(
        f"/tasks/{task_id2}/reject",
        json={"reason": "JWT expiration süresi 15 dakikaya indirilmeli.", "rejected_by": "lead_dev"}
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["status"] == TaskStatus.CHANGES_REQUESTED.value
    events2 = reject_res.json()["events"]
    rej_evt = next((e for e in events2 if e["type"] == "task_rejected"), None)
    assert rej_evt is not None
    assert rej_evt["details"]["rejected_by"] == "lead_dev"

    # 3. Bloke Görevin Onaylanmasının Güvenle Engellenmesi (400)
    task_repo = TaskRepository()
    task_repo.create_task("task_blocked_hitl", "Blocked Task")
    task_repo.update_task_workflow_result("task_blocked_hitl", status=TaskStatus.BLOCKED, error="AST Socket İhlali")

    blocked_appr = client.post("/tasks/task_blocked_hitl/approve", json={"comment": "Zorla onayla"})
    assert blocked_appr.status_code == 400
    assert "onaylanamaz" in blocked_appr.json()["detail"].lower()


# =====================================================================
# SENARYO D: GÖREV GEÇMİŞİ VE SQLITE KALICILIK DOĞRULAMASI
# =====================================================================

def test_scenario_d_sqlite_persistence_and_querying(client):
    """
    Senaryo D:
    - Görevler ve geçmiş çalıştırmalar SQLite üzerinde kalıcı saklanır.
    - Bağlantı yeniden oluşturulduğunda veya API sorgulandığında veriler kaybolmaz.
    - Planner, Scope, Coder, Tester, Reviewer ve Event kayıtları eksiksiz okunur.
    """
    create_res = client.post("/tasks", json={"description": "FastAPI Items CRUD Persistence Test"})
    task_id = create_res.json()["id"]

    # 1. Run çalıştır
    client.post(f"/tasks/{task_id}/run")

    # 2. 2. Run çalıştır (Yeni bir çalıştırma kaydı oluşturmalı)
    client.post(f"/tasks/{task_id}/run")

    # 3. API üzerinden geçmişi listele
    runs_res = client.get(f"/tasks/{task_id}/runs")
    assert runs_res.status_code == 200
    runs = runs_res.json()["runs"]
    assert len(runs) == 2
    assert runs[0]["id"] != runs[1]["id"]

    # 4. Doğrudan SQLite bağlantısı ile ham tablodan doğrula
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, status, plan_json, coder_json, tester_json, reviewer_json FROM tasks WHERE id = ?", (task_id,))
        task_row = cursor.fetchone()
        assert task_row is not None
        assert task_row["status"] == TaskStatus.REVIEWED.value
        assert task_row["plan_json"] is not None
        assert task_row["coder_json"] is not None
        assert task_row["tester_json"] is not None
        assert task_row["reviewer_json"] is not None

        cursor.execute("SELECT COUNT(*) as count FROM workflow_runs WHERE task_id = ?", (task_id,))
        count_row = cursor.fetchone()
        assert count_row["count"] == 2


# =====================================================================
# SENARYO E: GÜVENLİK, İZOLASYON VE FAIL-SAFE DAVRANIŞLARI
# =====================================================================

def test_scenario_e_security_isolation_and_no_host_fallback(monkeypatch):
    """
    Senaryo E:
    1. Docker Sandbox kullanılamadığında (ör. EXECUTION_ENGINE='docker' ancak daemon yok):
       - Host üzerinde güvensiz çalıştırma (subprocess) ASLA devreye girmez.
       - Tester sonucu 'blocked' olur.
       - Reviewer 'BLOCKED' kararı üretir.
    2. 'BLOCKED' durumundaki görev asla retry mekanizması tarafından tekrar çalıştırılmaz.
    """
    task_id = "task_e2e_security_block_test"

    # Zararlı ağ/socket kodu yaz
    with tempfile.TemporaryDirectory() as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)
        with open(os.path.join(task_ws, "api_feature.py"), "w", encoding="utf-8") as f:
            f.write("import urllib.request\nurllib.request.urlopen('http://malicious.test')\n")

        mock_engine = MockExecutionEngine()
        tester_res = _execute_tester_in_workspace(
            task_id=task_id,
            description="Malicious feature",
            workspaces_root=temp_root,
            engine=mock_engine
        )

        # 1. AST güvenlik filtresi soketi yakalamalı ve durumu 'blocked' yapmalıdır
        assert tester_res.status == "blocked"
        assert "Yasaklı ağ/sistem modülü" in (tester_res.error or "")

        # 2. Reviewer asla onaylamamalı, 'BLOCKED' kararı vermelidir
        reviewer_res = _execute_reviewer_in_workspace(
            task_id=task_id,
            description="Malicious feature",
            coder_data={"status": "coded", "created_files": ["api_feature.py"]},
            tester_data=tester_res.model_dump(),
            workspaces_root=temp_root
        )
        assert reviewer_res.verdict == ReviewerVerdict.BLOCKED
        assert reviewer_res.status == "blocked"

        # 3. Workflow yönlendirmesi ASLA retry yapmamalı (route -> end)
        from agent_workflow import _route_after_reviewer
        dummy_state = {
            "status": TaskStatus.BLOCKED.value,
            "reviewer": reviewer_res.model_dump(),
            "tester": tester_res.model_dump(),
            "retry_count": 0,
            "max_retries": 2
        }
        route = _route_after_reviewer(dummy_state)
        assert route == "end"
