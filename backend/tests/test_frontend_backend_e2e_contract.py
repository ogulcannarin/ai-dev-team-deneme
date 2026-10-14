"""
backend/tests/test_frontend_backend_e2e_contract.py
Frontend ve Backend Arasındaki HTTP & Şema Sözleşmesini Uçtan Uca Doğrulayan Test Paketi
"""

import pytest
from fastapi.testclient import TestClient
from main import app
from database import init_db
from schemas import TaskStatus


@pytest.fixture(autouse=True)
def setup_contract_env(tmp_path, monkeypatch):
    """İzole SQLite veritabanı hazırlar."""
    test_db_file = str(tmp_path / "test_contract.db")
    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", test_db_file)
    init_db(test_db_file)
    yield


@pytest.fixture
def client():
    return TestClient(app)


def test_cors_headers_for_vite_frontend(client):
    """
    Vite React frontend (http://localhost:5173 ve http://127.0.0.1:5173) adreslerinden
    gelen isteklere uygun CORS başlıklarının döndürüldüğünü doğrular.
    """
    for origin in ["http://localhost:5173", "http://127.0.0.1:5173"]:
        # 1. Preflight OPTIONS isteği
        options_res = client.options(
            "/tasks",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            }
        )
        assert options_res.status_code == 200
        assert options_res.headers.get("access-control-allow-origin") == origin

        # 2. Gerçek GET isteği
        get_res = client.get("/health", headers={"Origin": origin})
        assert get_res.status_code == 200
        assert get_res.headers.get("access-control-allow-origin") == origin


def test_health_endpoint_contract(client):
    """
    GET /health endpoint'inin frontend'in beklediği alanları döndürdüğünü doğrular.
    Frontend tipi: { status: string, message: string, timestamp: string }
    """
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "message" in data
    assert "timestamp" in data


def test_create_task_and_schema_compatibility(client):
    """
    Frontend'in POST /tasks gönderdiği { description: string } JSON gövdesinin
    başarıyla kabul edildiğini ve döndürülen alanların (id, description, status, created_at)
    Frontend BackendTask modeliyle birebir örtüştüğünü doğrular.
    """
    payload = {"description": "Kullanıcı profil yönetimi ve JWT kimlik doğrulama"}
    res = client.post("/tasks", json=payload)
    assert res.status_code == 201
    task = res.json()

    # Frontend BackendTask modeli alanları
    assert "id" in task and task["id"].startswith("task_")
    assert task["description"] == payload["description"]
    assert task["status"] == TaskStatus.QUEUED.value
    assert "created_at" in task
    assert isinstance(task["created_at"], str)


def test_empty_and_whitespace_description_rejection(client):
    """
    Boş veya sadece boşluklardan oluşan açıklamaların backend tarafından reddedildiğini (422) doğrular.
    """
    # 1. Tamamen boş string
    res_empty = client.post("/tasks", json={"description": ""})
    assert res_empty.status_code == 422

    # 2. Sadece boşluklar
    res_whitespace = client.post("/tasks", json={"description": "    \t\n   "})
    assert res_whitespace.status_code == 422
    err_body = res_whitespace.json()
    assert "detail" in err_body


def test_get_task_by_id_success_and_not_found(client):
    """
    GET /tasks/{task_id} için başarılı sorgu ve 404 durumlarını doğrular.
    """
    # Önce görev oluştur
    create_res = client.post("/tasks", json={"description": "Örnek Test Görevi"})
    task_id = create_res.json()["id"]

    # Başarılı get
    get_res = client.get(f"/tasks/{task_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["id"] == task_id
    assert data["description"] == "Örnek Test Görevi"

    # Bulunamayan görev 404
    not_found_res = client.get("/tasks/task_bilinmeyen_999")
    assert not_found_res.status_code == 404
    assert "detail" in not_found_res.json()


def test_list_tasks_persistence_and_order(client):
    """
    GET /tasks listeleme endpoint'inin oluşturulan görevleri döndürdüğünü ve
    sayfa yenilendiğinde verilerin SQLite kalıcılığında korunduğunu doğrular.
    """
    tasks_to_create = [
        "Görev 1: Auth Modülü",
        "Görev 2: Rate Limiting",
        "Görev 3: Veritabanı Migrasyonu",
    ]

    for desc in tasks_to_create:
        res = client.post("/tasks", json={"description": desc})
        assert res.status_code == 201

    list_res = client.get("/tasks")
    assert list_res.status_code == 200
    tasks = list_res.json()
    assert len(tasks) == 3
    descs = [t["description"] for t in tasks]
    for d in tasks_to_create:
        assert d in descs


def test_full_workflow_execution_contract(client, monkeypatch):
    """
    Kullanıcının arayüzden başlattığı görevin (POST /tasks + POST /tasks/{id}/run):
    1. Yalnızca SQLite'a kaydedilmekle kalmayıp,
    2. LangGraph StateGraph agent iş akışından gerçekten geçtiğini,
    3. Planner -> Scope -> Coder -> Tester -> Reviewer aşamalarının çıktı ürettiğini,
    4. SQLite veritabanına ve olay günlüğüne eksiksiz yazıldığını doğrular.
    """
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")

    # 1. Görev oluştur
    create_res = client.post("/tasks", json={"description": "FastAPI Items CRUD REST API"})
    assert create_res.status_code == 201
    task_id = create_res.json()["id"]

    # 2. Workflow'u tetikle
    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200
    task_data = run_res.json()

    # 3. Tüm aşamaların doğrulanması
    # Planner
    assert task_data["plan"] is not None
    assert len(task_data["plan"]["subtasks"]) >= 3
    assert len(task_data["plan"]["acceptance_criteria"]) >= 2

    # Scope
    assert task_data["scope"] is not None
    assert isinstance(task_data["scope"]["existing_files"], list)

    # Coder
    assert task_data["coder"] is not None
    assert task_data["coder"]["status"] == "coded"
    assert len(task_data["coder"]["created_files"]) >= 2

    # Tester
    assert task_data["tester"] is not None
    assert task_data["tester"]["status"] in ["tested", "passed"]
    assert task_data["tester"]["passed"] >= 1

    # Reviewer
    assert task_data["reviewer"] is not None
    assert task_data["reviewer"]["verdict"] == "approved"

    # Events
    assert len(task_data["events"]) >= 5
    sources = [e["source"] for e in task_data["events"]]
    assert "PLANNER_AGENT" in sources
    assert "SCOPE_AGENT" in sources
    assert "CODER_AGENT" in sources
    assert "TESTER_AGENT" in sources
    assert "REVIEWER_AGENT" in sources


def test_hitl_approval_and_rejection_contract(client, monkeypatch):
    """
    İnsan onayı (HITL) endpoint'lerinin frontend beklentileriyle uyumunu doğrular:
    - POST /tasks/{id}/approve -> status: completed
    - POST /tasks/{id}/reject -> status: changes_requested
    """
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")

    # 1. Görev oluştur ve koştur
    create_res = client.post("/tasks", json={"description": "FastAPI Items REST API"})
    task_id = create_res.json()["id"]
    client.post(f"/tasks/{task_id}/run")

    # 2. Onaylama (Approve)
    appr_res = client.post(
        f"/tasks/{task_id}/approve",
        json={"comment": "Tüm testler ve güvenlik kuralları onaylandı.", "approved_by": "qa_lead"}
    )
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == TaskStatus.COMPLETED.value

    # 3. İkinci görev için Reddetme (Reject)
    create_res2 = client.post("/tasks", json={"description": "FastAPI Auth JWT Service"})
    task_id2 = create_res2.json()["id"]
    client.post(f"/tasks/{task_id2}/run")

    rej_res = client.post(
        f"/tasks/{task_id2}/reject",
        json={"reason": "JWT süresi 15 dakikaya indirilmeli.", "rejected_by": "security_officer"}
    )
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == TaskStatus.CHANGES_REQUESTED.value


def test_docker_unavailable_failsafe_blocks_execution(client, monkeypatch):
    """
    Docker Desktop kapalı veya kullanılamaz olduğunda:
    - Sistemin fail-safe olarak 'blocked' durumuna geçtiğini,
    - Host üzerinde ASLA güvensiz kod çalıştırmadığını,
    - Reviewer'ın 'BLOCKED' kararı ürettiğini doğrular.
    """
    monkeypatch.setenv("EXECUTION_ENGINE", "docker")
    # Docker daemon'u bilerek erişilemez yap (veya UnavailableEngine taklidi)
    from execution import UnavailableExecutionEngine
    monkeypatch.setattr("agent_workflow.get_execution_engine", lambda: UnavailableExecutionEngine("Docker daemon is unreachable"))


    create_res = client.post("/tasks", json={"description": "FastAPI Items REST API"})
    task_id = create_res.json()["id"]

    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200
    task_data = run_res.json()

    # Tester 'blocked' olmalı
    assert task_data["tester"] is not None
    assert task_data["tester"]["status"] == "blocked"

    # Reviewer 'blocked' vermeli
    assert task_data["reviewer"] is not None
    assert task_data["reviewer"]["verdict"] == "blocked"

    # Görev durumu 'blocked' olmalı
    assert task_data["status"] == TaskStatus.BLOCKED.value

