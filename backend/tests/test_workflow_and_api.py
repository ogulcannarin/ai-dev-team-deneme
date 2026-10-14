import asyncio
import os
import sys
import shutil
import pytest
from fastapi.testclient import TestClient

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Optional
from main import app
from agent_workflow import (
    _deterministic_planner,
    _llm_planner,
    _deterministic_scope,
    _is_path_safe,
    _scan_workspace_files,
    _get_safe_project_root,
    _get_safe_workspaces_root,
    _validate_task_id,
    _execute_coder_in_workspace,
    _execute_tester_in_workspace,
    _execute_reviewer_in_workspace,
    _generate_test_suite_code,
    _is_supported_task,
    ALLOWED_CODER_FILENAMES,
    run_agent_workflow
)
from llm_provider import (
    LLMConfig,
    MockLLMProvider,
    BaseLLMProvider,
    LLMResponse,
    get_llm_provider,
    load_project_env,
    extract_json_from_llm_text,
    LLMProviderError,
    LLMAuthenticationError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMResponseFormatError
)
import tempfile
from database import init_db, get_db_path
from repository import TaskRepository, WorkflowRunRepository
from schemas import TaskStatus, FindingSeverity, ReviewerVerdict, WorkflowRun, AgentMetric, TaskPlan, LLMProviderInfo

# Backend test veritabanı yolu
_TEST_DB_FILE: Optional[str] = None


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Her test için geçici, izole SQLite veritabanı ve temiz workspace hazırlar."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        test_db_path = tmp.name

    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", test_db_path)
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")
    init_db(test_db_path)

    # Workspace temizliği
    ws_root = _get_safe_workspaces_root()
    if os.path.exists(ws_root):
        for item in os.listdir(ws_root):
            item_path = os.path.join(ws_root, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path, ignore_errors=True)
            elif os.path.isfile(item_path) and not item.endswith(".gitkeep"):
                os.remove(item_path)

    yield test_db_path

    # Temizlik
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass


@pytest.fixture
def client():
    """FastAPI TestClient örneği."""
    return TestClient(app)


# --- 1. Unit Tests: Planner, Scope, Coder & Security ---

def test_deterministic_planner_generates_valid_structure():
    """Planner'ın goal, subtasks, acceptance_criteria ve risks alanlarını eksiksiz ürettiğini test eder."""
    desc = "Refactor JWT auth middleware and add sliding window rate limiter"
    plan = _deterministic_planner(desc)

    assert plan.goal != ""
    assert "Refactor JWT auth middleware" in plan.goal
    assert len(plan.subtasks) >= 5
    assert len(plan.acceptance_criteria) >= 3
    assert len(plan.risks) >= 2

    subtask_text = " ".join(plan.subtasks)
    assert "Güvenlik & Doğrulama" in subtask_text or "Token" in subtask_text
    assert "Rate Limiting" in subtask_text or "limitleme" in subtask_text


def test_deterministic_scope_structure():
    """Scope Agent'ın summary, existing_files, proposed_new_files, out_of_scope ve risks alanlarını ürettiğini test eder."""
    desc = "Create rate limiter middleware in FastAPI and update React dashboard"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    assert scope.summary != ""
    assert isinstance(scope.existing_files, list)
    assert len(scope.existing_files) > 0
    assert isinstance(scope.proposed_new_files, list)
    assert isinstance(scope.out_of_scope, list)
    assert len(scope.out_of_scope) >= 3
    assert isinstance(scope.risks, list)
    assert len(scope.risks) >= 2


def test_scope_excludes_sensitive_and_ignored_files():
    """Scope tarayıcısının .env, .git, .venv, workspaces, node_modules gibi hassas ve derleme dosyalarını hariç tuttuğunu test eder."""
    root = _get_safe_project_root()
    files = _scan_workspace_files(root)

    for f in files:
        assert not f.startswith(".env"), f"Hassas dosya bulundu: {f}"
        assert not f.startswith(".git/"), f"Git iç dosyası bulundu: {f}"
        assert not f.startswith("node_modules/"), f"node_modules dosyası bulundu: {f}"
        assert not f.startswith("backend/.venv/"), f"Sanal ortam dosyası bulundu: {f}"
        assert not f.startswith("backend/workspaces/"), f"Workspace dosyası bulundu: {f}"
        assert not f.endswith(".pyc"), f"Pyc dosyası bulundu: {f}"


def test_path_traversal_protection():
    """Path traversal ve kök dizin dışı yolların engellendiğini test eder."""
    root = _get_safe_project_root()
    
    # Güvenli yollar
    assert _is_path_safe(os.path.join(root, "backend", "main.py"), root) is True
    assert _is_path_safe(os.path.join(root, "src", "App.tsx"), root) is True

    # Güvensiz / Traversal yollar
    assert _is_path_safe(os.path.join(root, "..", "..", "Windows", "System32"), root) is False
    assert _is_path_safe("C:\\Windows\\explorer.exe", root) is False


def test_task_id_validation_security():
    """Task ID'nin güvenli karakterler içerdiğini, path traversal denemelerinin engellendiğini test eder."""
    assert _validate_task_id("task_123abc") is True
    assert _validate_task_id("task-456_DEF") is True
    
    # Güvensiz Task ID denemeleri
    assert _validate_task_id("../etc/passwd") is False
    assert _validate_task_id("task/../../../secret") is False
    assert _validate_task_id("task*illegal$") is False
    assert _validate_task_id("") is False
    assert _validate_task_id("a" * 70) is False  # > 64 chars


def test_coder_supported_task_detection():
    """Desteklenen Python REST API ve Hesaplama şablonlarının tespit edildiğini, desteklenmeyenlerin reddedildiğini test eder."""
    supported_desc = "Create Python FastAPI REST API router for user management and items CRUD"
    assert _is_supported_task(supported_desc) is True

    calculator_turkish_desc = "Python ile çalışan basit bir hesaplama modülü oluştur. İki sayıyı toplayan bir fonksiyon yaz ve fonksiyonun doğru çalıştığını doğrulayan pytest testleri ekle."
    assert _is_supported_task(calculator_turkish_desc) is True

    unsupported_desc = "Train a 70B parameter model with distributed PyTorch and deploy on iOS"
    assert _is_supported_task(unsupported_desc) is False


def test_coder_calculator_template_execution():
    """Hesaplama ve matematik fonksiyonu isteklerinde calculator.py dosyasının doğru üretildiğini test eder."""
    task_id = "task_calculator_unit_test"
    desc = "Python ile çalışan basit bir hesaplama modülü oluştur. İki sayıyı toplayan bir fonksiyon yaz ve fonksiyonun doğru çalıştığını doğrulayan pytest testleri ekle."
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_result = _execute_coder_in_workspace(task_id, desc, plan, scope)

    assert coder_result.status == "coded"
    assert "calculator.py" in [os.path.basename(f) for f in coder_result.created_files]
    assert coder_result.error is None

    workspaces_root = _get_safe_workspaces_root()
    task_ws_dir = os.path.join(workspaces_root, task_id)
    calc_file = os.path.join(task_ws_dir, "calculator.py")
    assert os.path.exists(calc_file)
    with open(calc_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "def add(a: Number, b: Number)" in content
        assert "def subtract(" in content


def test_coder_executes_in_isolated_workspace():
    """Coder Agent'ın sadece backend/workspaces/{task_id}/ altına yazdığını ve ana dosyaları değiştirmediğini test eder."""
    task_id = "task_coder_unit_test"
    desc = "Build FastAPI REST API router and models for products catalog"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_result = _execute_coder_in_workspace(task_id, desc, plan, scope)

    assert coder_result.status == "coded"
    assert len(coder_result.created_files) > 0
    assert coder_result.error is None

    workspaces_root = _get_safe_workspaces_root()
    task_ws_dir = os.path.join(workspaces_root, task_id)
    assert os.path.isdir(task_ws_dir)

    for cf in coder_result.created_files:
        filename = os.path.basename(cf)
        full_path = os.path.join(task_ws_dir, filename)
        assert os.path.exists(full_path), f"Oluşturulan dosya bulunamadı: {full_path}"
        assert filename in ALLOWED_CODER_FILENAMES
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert len(content) > 0


def test_coder_unsupported_task_returns_unsupported_status():
    """Desteklenmeyen görevde Coder'ın uydurma kod yazmayıp 'unsupported' döndürdüğünü test eder."""
    task_id = "task_unsupported_unit"
    desc = "Develop an Android Kotlin camera app with 3D OpenGL filters"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_result = _execute_coder_in_workspace(task_id, desc, plan, scope)

    assert coder_result.status == "unsupported"
    assert len(coder_result.created_files) == 0
    assert "desteklenmiyor" in coder_result.summary.lower()
    assert any("Deterministik" in lim or "LLM" in lim or "Python REST API" in lim for lim in coder_result.limitations)


def test_coder_file_collision_protection():
    """Var olan bir dosya üzerine sessizce yazılmayıp çakışma durumunda failed döndüğünü test eder."""
    task_id = "task_collision_test"
    desc = "FastAPI REST API feature for order management"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    # 1. İlk çalıştırma: Başarılı oluşturur
    first_result = _execute_coder_in_workspace(task_id, desc, plan, scope)
    assert first_result.status == "coded"

    # 2. İkinci çalıştırma (aynı workspace ve dosyalar varken): Çakışmayı tespit edip failed döner
    second_result = _execute_coder_in_workspace(task_id, desc, plan, scope)
    assert second_result.status == "failed"
    assert "Dosya çakışması" in (second_result.error or "")


# --- 2. Unit Tests: Tester Agent & Isolation Security ---

def test_tester_executes_successfully_in_isolated_workspace():
    """Tester Agent'ın Coder tarafından oluşturulan izole workspace içindeki testleri çalıştırıp 'tested' döndürdüğünü test eder."""
    task_id = "task_tester_unit_success"
    desc = "Build FastAPI REST API router and models for products catalog"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_res = _execute_coder_in_workspace(task_id, desc, plan, scope)
    assert coder_res.status == "coded"

    workspaces_root = _get_safe_workspaces_root()
    tester_res = _execute_tester_in_workspace(task_id, desc, workspaces_root)

    assert tester_res.status == "tested"
    assert tester_res.passed > 0
    assert tester_res.failed == 0
    assert tester_res.error is None
    assert "0 hata" in tester_res.summary or "tamamlad" in tester_res.summary

    # Bireysel test durumlarını kontrol et
    for tr in tester_res.test_results:
        assert tr.status == "passed"
        assert tr.duration_ms >= 0


def test_tester_blocked_on_invalid_task_id_or_traversal():
    """Geçersiz Task ID veya path traversal girişiminde Tester Agent'ın 'blocked' döndüğünü test eder."""
    workspaces_root = _get_safe_workspaces_root()

    # Path traversal denemesi
    res_traversal = _execute_tester_in_workspace("../etc/passwd", "Test desc", workspaces_root)
    assert res_traversal.status == "blocked"
    assert "Geçersiz" in (res_traversal.error or "") or "engellendi" in (res_traversal.error or "")

    # Var olmayan workspace
    res_missing = _execute_tester_in_workspace("task_nonexistent_workspace", "Test desc", workspaces_root)
    assert res_missing.status == "blocked"
    assert "bulunamadı" in (res_missing.error or "")


def test_tester_handles_failed_assertions():
    """Workspace içindeki kodda hata veya başarısız test olduğunda Tester Agent'ın 'failed' döndürdüğünü test eder."""
    task_id = "task_tester_failing_case"
    desc = "Build FastAPI REST API router and models for products catalog"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_res = _execute_coder_in_workspace(task_id, desc, plan, scope)
    assert coder_res.status == "coded"

    workspaces_root = _get_safe_workspaces_root()
    task_ws = os.path.join(workspaces_root, task_id)
    test_file_path = os.path.join(task_ws, "test_feature.py")

    # test_feature.py dosyasını kasıtlı olarak başarısız olacak şekilde modifiye et
    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write("""import unittest

class TestIntentionalFailure(unittest.TestCase):
    def test_broken_assertion(self):
        self.assertEqual(1 + 1, 999, "Kasıtlı test hatası")
""")

    tester_res = _execute_tester_in_workspace(task_id, desc, workspaces_root)

    assert tester_res.status == "failed"
    assert tester_res.failed > 0
    assert len(tester_res.test_results) > 0
    assert any(tr.status == "failed" for tr in tester_res.test_results)
    assert "başarısız" in tester_res.summary.lower()


def test_tester_handles_timeout():
    """Sonsuz döngüye giren test kodunun timeout sınırına takılıp 'failed' olarak yakalandığını test eder."""
    task_id = "task_tester_timeout_case"
    desc = "Build FastAPI REST API router and models for products catalog"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_res = _execute_coder_in_workspace(task_id, desc, plan, scope)
    assert coder_res.status == "coded"

    workspaces_root = _get_safe_workspaces_root()
    task_ws = os.path.join(workspaces_root, task_id)
    test_file_path = os.path.join(task_ws, "test_feature.py")

    # test_feature.py içine 15 saniyelik sleep yerleştir (timeout 5.0 saniyedir)
    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write("""import unittest
import time

class TestInfiniteLoop(unittest.TestCase):
    def test_sleep_forever(self):
        time.sleep(15)
        self.assertTrue(True)
""")

    tester_res = _execute_tester_in_workspace(task_id, desc, workspaces_root)

    assert tester_res.status == "failed"
    assert "zaman aşımı" in (tester_res.summary or "").lower() or "timeoutexpired" in (tester_res.error or "").lower()
    assert tester_res.failed >= 1


def test_tester_blocks_network_module_imports():
    """Ağ erişimi yapmaya çalışan (socket, requests, urllib vb.) kodların AST aşamasında engellendiğini ve çalıştırılmadığını test eder."""
    task_id = "task_tester_network_blocked"
    desc = "Build FastAPI REST API router and models for products catalog"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_res = _execute_coder_in_workspace(task_id, desc, plan, scope)
    assert coder_res.status == "coded"

    workspaces_root = _get_safe_workspaces_root()
    task_ws = os.path.join(workspaces_root, task_id)
    test_file_path = os.path.join(task_ws, "test_feature.py")

    # Kasıtlı ağ modülü importu ekle
    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write("""import unittest
import socket

class TestNetworkLeak(unittest.TestCase):
    def test_connect(self):
        s = socket.socket()
        self.assertTrue(True)
""")

    tester_res = _execute_tester_in_workspace(task_id, desc, workspaces_root)

    assert tester_res.status == "blocked"
    assert tester_res.passed == 0
    assert tester_res.failed == 0
    assert "Yasaklı ağ/sistem modülü" in (tester_res.error or "")
    assert "socket" in (tester_res.error or "")


def test_tester_blocks_system_calls_and_process_escapes():
    """İşletim sistemi komutu çalıştırmaya çalışan (subprocess, os.system vb.) kodların engellendiğini test eder."""
    task_id = "task_tester_syscall_blocked"
    desc = "Build FastAPI REST API router and models for products catalog"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_res = _execute_coder_in_workspace(task_id, desc, plan, scope)
    assert coder_res.status == "coded"

    workspaces_root = _get_safe_workspaces_root()
    task_ws = os.path.join(workspaces_root, task_id)
    test_file_path = os.path.join(task_ws, "test_feature.py")

    # Kasıtlı subprocess ve os.system ekle
    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write("""import unittest
import subprocess

class TestSyscallLeak(unittest.TestCase):
    def test_exec(self):
        subprocess.run(["cmd.exe", "/c", "dir"])
""")

    tester_res = _execute_tester_in_workspace(task_id, desc, workspaces_root)

    assert tester_res.status == "blocked"
    assert tester_res.passed == 0
    assert "Yasaklı ağ/sistem modülü" in (tester_res.error or "")
    assert "subprocess" in (tester_res.error or "")


def test_tester_blocks_filesystem_escape_open():
    """Çalışma alanı dışına çıkmaya çalışan (open('../../../.env')) kodların engellendiğini test eder."""
    task_id = "task_tester_fs_escape_blocked"
    desc = "Build FastAPI REST API router and models for products catalog"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_res = _execute_coder_in_workspace(task_id, desc, plan, scope)
    assert coder_res.status == "coded"

    workspaces_root = _get_safe_workspaces_root()
    task_ws = os.path.join(workspaces_root, task_id)
    test_file_path = os.path.join(task_ws, "test_feature.py")

    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write("""import unittest

class TestFileEscape(unittest.TestCase):
    def test_read_secret(self):
        with open("../../../.env", "r") as f:
            data = f.read()
""")

    tester_res = _execute_tester_in_workspace(task_id, desc, workspaces_root)

    assert tester_res.status == "blocked"
    assert tester_res.passed == 0
    assert "Çalışma alanı dışına dosya erişim girişimi" in (tester_res.error or "")


def test_tester_blocks_eval_exec_builtins():
    """Dinamik kod çalıştırma girişimlerinin (eval, exec) AST aşamasında engellendiğini test eder."""
    task_id = "task_tester_eval_blocked"
    desc = "Build FastAPI REST API router and models for products catalog"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_res = _execute_coder_in_workspace(task_id, desc, plan, scope)
    assert coder_res.status == "coded"

    workspaces_root = _get_safe_workspaces_root()
    task_ws = os.path.join(workspaces_root, task_id)
    test_file_path = os.path.join(task_ws, "test_feature.py")

    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write("""import unittest

class TestEval(unittest.TestCase):
    def test_run_eval(self):
        eval("__import__('os').system('whoami')")
""")

    tester_res = _execute_tester_in_workspace(task_id, desc, workspaces_root)

    assert tester_res.status == "blocked"
    assert tester_res.passed == 0
    assert "Yasaklı dinamik çalıştırma çağrısı" in (tester_res.error or "")


def test_tester_blocks_unauthorized_files_in_workspace():
    """Çalışma alanında izin verilmeyen dosya veya alt dizin olduğunda test koşumunun engellendiğini test eder."""
    task_id = "task_tester_unauthorized_files"
    desc = "Build FastAPI REST API router and models for products catalog"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_res = _execute_coder_in_workspace(task_id, desc, plan, scope)
    assert coder_res.status == "coded"

    workspaces_root = _get_safe_workspaces_root()
    task_ws = os.path.join(workspaces_root, task_id)
    bad_file = os.path.join(task_ws, "unauthorized_script.sh")
    with open(bad_file, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\necho dangerous")

    tester_res = _execute_tester_in_workspace(task_id, desc, workspaces_root)

    assert tester_res.status == "blocked"
    assert "İzin verilmeyen dosya tespit edildi" in (tester_res.summary or "")


# --- 3. End-to-End Workflow Tests ---

def test_run_agent_workflow_success_with_planner_scope_coder_and_tester():
    """LangGraph iş akışının (init -> planner -> scope -> coder -> tester -> reviewer) başarıyla çalışıp 'reviewed' durumuna ulaştığını test eder."""
    task_id = "task_full_flow_test"
    desc = "Build FastAPI REST API endpoints with auth middleware and rate limiting"

    result = asyncio.run(run_agent_workflow(task_id, desc))

    assert result["task_id"] == task_id
    assert result["status"] == TaskStatus.REVIEWED.value
    assert result["plan"] is not None
    assert result["scope"] is not None
    assert result["coder"] is not None
    assert result["coder"]["status"] == "coded"
    assert len(result["coder"]["created_files"]) > 0
    assert result["tester"] is not None
    assert result["tester"]["status"] == "tested"
    assert result["tester"]["passed"] > 0
    assert result["tester"]["failed"] == 0
    assert result["reviewer"] is not None
    assert result["reviewer"]["status"] == "reviewed"
    assert result["reviewer"]["verdict"] == "approved"
    assert result["error"] is None

    # Olay kayıtları kontrolü
    events = result["events"]
    assert len(events) >= 11
    event_types = [e["type"] for e in events]
    assert "task_started" in event_types
    assert "planning_started" in event_types
    assert "plan_created" in event_types
    assert "scope_started" in event_types
    assert "scope_completed" in event_types
    assert "coder_started" in event_types
    assert "coder_completed" in event_types
    assert "tester_started" in event_types
    assert "tester_completed" in event_types
    assert "reviewer_started" in event_types
    assert "reviewer_completed" in event_types


def test_run_agent_workflow_unsupported_task():
    """Desteklenmeyen görev iş akışına girdiğinde 'unsupported' durumuna ulaştığını ve Tester'ın çağrılmadığını test eder."""
    task_id = "task_unsupported_flow"
    desc = "Write Rust kernel module for Bluetooth Low Energy drivers"

    result = asyncio.run(run_agent_workflow(task_id, desc))

    assert result["status"] == TaskStatus.UNSUPPORTED.value
    assert result["coder"] is not None
    assert result["coder"]["status"] == "unsupported"
    assert result.get("tester") is None
    event_types = [e["type"] for e in result["events"]]
    assert "coder_unsupported" in event_types
    assert "tester_started" not in event_types


def test_run_agent_workflow_empty_description_fails():
    """Boş açıklama verildiğinde workflow'un failed durumuna geçtiğini ve sonraki adımlara geçmediğini doğrular."""
    task_id = "task_empty_desc"
    desc = "   "

    result = asyncio.run(run_agent_workflow(task_id, desc))

    assert result["status"] == TaskStatus.FAILED.value
    assert result["plan"] is None
    assert result["scope"] is None
    assert result["coder"] is None
    assert result["tester"] is None
    assert result["error"] is not None
    event_types = [e["type"] for e in result["events"]]
    assert "planning_failed" in event_types
    assert "scope_started" not in event_types
    assert "coder_started" not in event_types
    assert "tester_started" not in event_types


# --- 4. Integration Tests: API Endpoints ---

def test_health_check(client):
    """GET /health endpoint'inin 200 OK döndürdüğünü test eder."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data


def test_create_task_success(client):
    """POST /tasks ile görev oluşturulduğunda 201 Created ve başlangıçta 'queued' döndüğünü test eder."""
    payload = {"description": "FastAPI REST API router for invoice processing"}
    response = client.post("/tasks", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["id"].startswith("task_")
    assert data["description"] == payload["description"]
    assert data["status"] == "queued"
    assert data["plan"] is None
    assert data["scope"] is None
    assert data["coder"] is None
    assert data["tester"] is None
    assert len(data["events"]) == 1
    assert data["events"][0]["type"] == "task_created"


def test_create_task_empty_description_validation(client):
    """POST /tasks boş veya whitespace açıklama ile çağrıldığında 422 Unprocessable Entity döndüğünü test eder."""
    res1 = client.post("/tasks", json={"description": ""})
    assert res1.status_code == 422

    res2 = client.post("/tasks", json={"description": "    "})
    assert res2.status_code == 422

    res3 = client.post("/tasks", json={})
    assert res3.status_code == 422


def test_run_task_workflow_success(client):
    """POST /tasks/{task_id}/run endpoint'inin LangGraph akışını (Planner + Scope + Coder + Tester + Reviewer) tetikleyip 'reviewed' döndürdüğünü test eder."""
    # 1. Görevi oluştur
    create_res = client.post("/tasks", json={"description": "FastAPI REST API endpoints for user authentication and rate limiting"})
    assert create_res.status_code == 201
    task_id = create_res.json()["id"]

    # 2. İş akışını çalıştır
    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200
    data = run_res.json()

    assert data["id"] == task_id
    assert data["status"] == "reviewed"
    assert data["plan"] is not None
    assert "goal" in data["plan"]
    assert data["scope"] is not None
    assert "summary" in data["scope"]
    assert data["coder"] is not None
    assert data["coder"]["status"] == "coded"
    assert len(data["coder"]["created_files"]) > 0
    assert data["tester"] is not None
    assert data["tester"]["status"] == "tested"
    assert data["tester"]["passed"] > 0
    assert data["tester"]["failed"] == 0
    assert data["reviewer"] is not None
    assert data["reviewer"]["status"] == "reviewed"
    assert data["reviewer"]["verdict"] == "approved"
    assert len(data["reviewer"]["reviewed_files"]) > 0
    assert len(data["events"]) >= 11


def test_run_task_invalid_id_returns_404(client):
    """POST /tasks/{invalid_task_id}/run çağrıldığında 404 Not Found döndüğünü test eder."""
    response = client.post("/tasks/task_nonexistent_999/run")
    assert response.status_code == 404
    data = response.json()
    assert "bulunamadı" in data["detail"]


def test_get_task_by_id(client):
    """GET /tasks/{task_id} ile plan, scope, coder, tester ve reviewer dahil tüm alanların doğru geldiğini test eder."""
    create_res = client.post("/tasks", json={"description": "FastAPI REST API service with auth and data models"})
    task_id = create_res.json()["id"]
    client.post(f"/tasks/{task_id}/run")

    get_res = client.get(f"/tasks/{task_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["id"] == task_id
    assert data["status"] == "reviewed"
    assert data["plan"] is not None
    assert data["scope"] is not None
    assert data["coder"] is not None
    assert data["tester"] is not None
    assert data["tester"]["status"] == "tested"
    assert data["reviewer"] is not None
    assert data["reviewer"]["status"] == "reviewed"
    assert data["reviewer"]["verdict"] == "approved"
    assert data["description"] == "FastAPI REST API service with auth and data models"


def test_get_task_invalid_id_returns_404(client):
    """GET /tasks/{invalid_task_id} 404 döndürdüğünü test eder."""
    response = client.get("/tasks/task_unknown_id")
    assert response.status_code == 404


def test_list_tasks(client):
    """GET /tasks tüm görevleri liste olarak döndürdüğünü test eder."""
    client.post("/tasks", json={"description": "Task 1: Setup CI/CD"})
    client.post("/tasks", json={"description": "Task 2: Setup Docker Compose"})

    response = client.get("/tasks")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert any(t["description"] == "Task 1: Setup CI/CD" for t in data)
    assert any(t["description"] == "Task 2: Setup Docker Compose" for t in data)


# --- 5. Reviewer Agent Unit & Integration Tests ---

def test_reviewer_approves_clean_workspace():
    """Temiz ve kurallara uygun bir görev için Reviewer'ın approved kararı ürettiğini test eder."""
    task_id = "task_rev_clean_1"
    ws_root = _get_safe_workspaces_root()
    ws_path = os.path.join(ws_root, task_id)
    os.makedirs(ws_path, exist_ok=True)

    # Dosya yaz (Docstring ve return type ipucu ile tertemiz kod)
    app_code = 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/test")\ndef get_test() -> dict:\n    """Test endpoint."""\n    return {"status": "ok"}\n'
    with open(os.path.join(ws_path, "main.py"), "w", encoding="utf-8") as f:
        f.write(app_code)

    coder_data = {
        "status": "coded",
        "created_files": [{"path": "main.py", "action": "created", "bytes": len(app_code), "description": "API"}]
    }
    tester_data = {
        "status": "tested",
        "passed": 3,
        "failed": 0,
        "summary": "All tests passed"
    }

    result = _execute_reviewer_in_workspace(
        task_id=task_id,
        description="FastAPI test endpoint",
        coder_data=coder_data,
        tester_data=tester_data,
        workspaces_root=ws_root
    )

    assert result.status == "reviewed"
    assert result.verdict == ReviewerVerdict.APPROVED or result.verdict == "approved"
    assert any("main.py" in rf for rf in result.reviewed_files)
    assert len(result.findings) == 0
    assert "APPROVED" in result.summary or "onay" in result.summary.lower()


def test_reviewer_catches_syntax_error():
    """Sözdizimi hatalı (AST Syntax Error) Python dosyası bulunduğunda critical bulgu üretip engellediğini test eder."""
    task_id = "task_rev_syntax_err"
    ws_root = _get_safe_workspaces_root()
    ws_path = os.path.join(ws_root, task_id)
    os.makedirs(ws_path, exist_ok=True)

    # Bozuk sözdizimli dosya
    broken_code = "def invalid_syntax_func(\n    return 42"
    with open(os.path.join(ws_path, "api_feature.py"), "w", encoding="utf-8") as f:
        f.write(broken_code)

    coder_data = {
        "status": "coded",
        "created_files": [{"path": "api_feature.py", "action": "created", "bytes": len(broken_code), "description": "Broken"}]
    }
    tester_data = {
        "status": "tested",
        "passed": 1,
        "failed": 0,
        "summary": "Tests ran"
    }

    result = _execute_reviewer_in_workspace(
        task_id=task_id,
        description="FastAPI endpoint",
        coder_data=coder_data,
        tester_data=tester_data,
        workspaces_root=ws_root
    )

    assert result.verdict == ReviewerVerdict.BLOCKED or result.verdict == "blocked"
    assert any((f.severity == FindingSeverity.CRITICAL or f.severity == "critical") and "SyntaxError" in f.title for f in result.findings)


def test_reviewer_flags_bare_except_and_changes_requested():
    """Genel / bare except ('except:') kullanımında HIGH önem dereceli bulgu ve changes_requested ürettiğini test eder."""
    task_id = "task_rev_bare_except"
    ws_root = _get_safe_workspaces_root()
    ws_path = os.path.join(ws_root, task_id)
    os.makedirs(ws_path, exist_ok=True)

    code_with_bare_except = "def run():\n    try:\n        x = 1 / 0\n    except:\n        pass\n"
    with open(os.path.join(ws_path, "api_feature.py"), "w", encoding="utf-8") as f:
        f.write(code_with_bare_except)

    coder_data = {
        "status": "coded",
        "created_files": [{"path": "api_feature.py", "action": "created", "bytes": len(code_with_bare_except), "description": "App"}]
    }
    tester_data = {
        "status": "tested",
        "passed": 2,
        "failed": 0,
        "summary": "Tests ran"
    }

    result = _execute_reviewer_in_workspace(
        task_id=task_id,
        description="Sample function",
        coder_data=coder_data,
        tester_data=tester_data,
        workspaces_root=ws_root
    )

    assert result.verdict == ReviewerVerdict.CHANGES_REQUESTED or result.verdict == "changes_requested"
    assert any((f.severity == FindingSeverity.HIGH or f.severity == "high") and ("except" in f.title.lower() or f.category == "error_handling") for f in result.findings)


def test_reviewer_rejects_when_tester_failed():
    """Tester failed olduğunda Reviewer'ın onay vermediğini (changes_requested) ve bulgu ürettiğini test eder."""
    task_id = "task_rev_tester_failed"
    ws_root = _get_safe_workspaces_root()
    ws_path = os.path.join(ws_root, task_id)
    os.makedirs(ws_path, exist_ok=True)

    valid_code = "def get_num():\n    return 42\n"
    with open(os.path.join(ws_path, "main.py"), "w", encoding="utf-8") as f:
        f.write(valid_code)

    coder_data = {
        "status": "coded",
        "created_files": [{"path": "main.py", "action": "created", "bytes": len(valid_code), "description": "Main"}]
    }
    tester_data = {
        "status": "failed",
        "passed": 1,
        "failed": 2,
        "summary": "2 test senaryosu başarısız oldu."
    }

    result = _execute_reviewer_in_workspace(
        task_id=task_id,
        description="Test endpoint",
        coder_data=coder_data,
        tester_data=tester_data,
        workspaces_root=ws_root
    )

    assert result.verdict == ReviewerVerdict.CHANGES_REQUESTED or result.verdict == "changes_requested"
    assert any("Başarısız" in f.title and (f.severity == FindingSeverity.HIGH or f.severity == "high") for f in result.findings)


def test_reviewer_blocked_when_tester_blocked():
    """Tester güvenlik kısıtı nedeniyle blocked ise Reviewer'ın da blocked olduğunu test eder."""
    task_id = "task_rev_tester_blocked"
    ws_root = _get_safe_workspaces_root()
    ws_path = os.path.join(ws_root, task_id)
    os.makedirs(ws_path, exist_ok=True)

    valid_code = "def check():\n    return True\n"
    with open(os.path.join(ws_path, "main.py"), "w", encoding="utf-8") as f:
        f.write(valid_code)

    coder_data = {
        "status": "coded",
        "created_files": [{"path": "main.py", "action": "created", "bytes": len(valid_code), "description": "Main"}]
    }
    tester_data = {
        "status": "blocked",
        "passed": 0,
        "failed": 0,
        "summary": "Test süreci güvenlik engeline takıldı"
    }

    result = _execute_reviewer_in_workspace(
        task_id=task_id,
        description="Check function",
        coder_data=coder_data,
        tester_data=tester_data,
        workspaces_root=ws_root
    )

    assert result.verdict == ReviewerVerdict.BLOCKED or result.verdict == "blocked"
    assert any("Engellendi" in f.title or f.category == "testing" for f in result.findings)


def test_reviewer_flags_missing_files():
    """Coder tarafından beyan edilen ancak diskte bulunmayan dosyaları HIGH bulgu olarak tespit ettiğini test eder."""
    task_id = "task_rev_missing_file"
    ws_root = _get_safe_workspaces_root()
    ws_path = os.path.join(ws_root, task_id)
    os.makedirs(ws_path, exist_ok=True)

    # Diske dosya yazmadık
    coder_data = {
        "status": "coded",
        "created_files": [{"path": "api_feature.py", "action": "created", "bytes": 50, "description": "Missing"}]
    }
    tester_data = {
        "status": "tested",
        "passed": 1,
        "failed": 0,
        "summary": "Ran"
    }

    result = _execute_reviewer_in_workspace(
        task_id=task_id,
        description="Missing file check",
        coder_data=coder_data,
        tester_data=tester_data,
        workspaces_root=ws_root
    )

    assert result.verdict == ReviewerVerdict.CHANGES_REQUESTED or result.verdict == "changes_requested"
    assert any("Eksik" in f.title and (f.severity == FindingSeverity.HIGH or f.severity == "high") for f in result.findings)


def test_reviewer_rejects_path_traversal():
    """Workspace dışında dosya veya geçersiz task_id verildiğinde Reviewer'ın engellediğini test eder."""
    ws_root = _get_safe_workspaces_root()
    result = _execute_reviewer_in_workspace(
        task_id="../malicious_path",
        description="Attack test",
        coder_data={"status": "coded", "created_files": []},
        tester_data=None,
        workspaces_root=ws_root
    )

    assert result.status == "blocked"
    assert result.verdict == ReviewerVerdict.BLOCKED or result.verdict == "blocked"
    assert any((f.severity == FindingSeverity.CRITICAL or f.severity == "critical") and ("Path Traversal" in f.title or "Geçersiz" in f.title) for f in result.findings)


def test_reviewer_is_strictly_read_only():
    """Reviewer'ın workspace içerisindeki hiçbir dosyayı ve içeriği değiştirmediğini (hash & timestamp) test eder."""
    import hashlib

    task_id = "task_rev_readonly_test"
    ws_root = _get_safe_workspaces_root()
    ws_path = os.path.join(ws_root, task_id)
    os.makedirs(ws_path, exist_ok=True)

    file_content = "def calculate_sum(a: int, b: int) -> int:\n    return a + b\n"
    file_path = os.path.join(ws_path, "api_feature.py")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(file_content)

    # Dosyanın hash ve timestamp değerlerini kaydet
    initial_hash = hashlib.sha256(open(file_path, "rb").read()).hexdigest()
    initial_mtime = os.path.getmtime(file_path)

    coder_data = {
        "status": "coded",
        "created_files": [{"path": "api_feature.py", "action": "created", "bytes": len(file_content), "description": "Calc"}]
    }
    tester_data = {
        "status": "tested",
        "passed": 2,
        "failed": 0,
        "summary": "Passed"
    }

    # Reviewer çalıştır
    result = _execute_reviewer_in_workspace(
        task_id=task_id,
        description="Calculation service",
        coder_data=coder_data,
        tester_data=tester_data,
        workspaces_root=ws_root
    )

    assert result.status == "reviewed"
    assert result.verdict == ReviewerVerdict.APPROVED or result.verdict == "approved"

    # İnceleme sonrası kontrol
    after_hash = hashlib.sha256(open(file_path, "rb").read()).hexdigest()
    after_mtime = os.path.getmtime(file_path)

    assert initial_hash == after_hash, "Reviewer dosya içeriğini değiştirdi!"
    assert initial_mtime == after_mtime, "Reviewer dosya değiştirilme zamanını etkiledi!"


def test_unsupported_coder_skips_reviewer(client):
    """Desteklenmeyen bir görev açıklaması verildiğinde Coder unsupported döner ve Tester/Reviewer atlanır."""
    create_res = client.post("/tasks", json={"description": "Build a React 3D WebGL renderer and game engine with Rust WASM"})
    assert create_res.status_code == 201
    task_id = create_res.json()["id"]

    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200
    data = run_res.json()

    assert data["status"] == "unsupported"
    assert data["coder"] is not None
    assert data["coder"]["status"] == "unsupported"
    assert data["tester"] is None
    assert data["reviewer"] is None


# --- 6. SQLite Persistence & Workflow Run History Tests ---

def test_task_creation_and_sqlite_persistence(client, setup_test_db):
    """Görev oluşturulduğunda SQLite 'tasks' tablosuna yazıldığını doğrular."""
    desc = "Build FastAPI microservice for invoice generation"
    res = client.post("/tasks", json={"description": desc})
    assert res.status_code == 201
    task_id = res.json()["id"]

    # Repository katmanından doğrudan sorgula
    repo = TaskRepository(setup_test_db)
    saved_task = repo.get_task(task_id)

    assert saved_task is not None
    assert saved_task.id == task_id
    assert saved_task.description == desc
    assert saved_task.status == TaskStatus.QUEUED
    assert len(saved_task.events) == 1
    assert saved_task.events[0].type == "task_created"


def test_task_listing_and_detail_query_from_sqlite(client, setup_test_db):
    """SQLite'dan görevlerin sıralı listelenmesi ve detay sorgulanmasını test eder."""
    res1 = client.post("/tasks", json={"description": "Task Alpha"})
    res2 = client.post("/tasks", json={"description": "Task Beta"})
    id1 = res1.json()["id"]
    id2 = res2.json()["id"]

    # Liste sorgusu
    list_res = client.get("/tasks")
    assert list_res.status_code == 200
    tasks = list_res.json()
    assert len(tasks) == 2
    task_ids = [t["id"] for t in tasks]
    assert id1 in task_ids
    assert id2 in task_ids

    # Tekil detay sorgusu
    detail_res = client.get(f"/tasks/{id1}")
    assert detail_res.status_code == 200
    assert detail_res.json()["description"] == "Task Alpha"


def test_persistence_survives_restart_simulation(client, setup_test_db):
    """Uygulama veya bağlantı yeniden başlatıldığında verilerin kaybolmadığını test eder."""
    # 1. Görev oluştur ve çalıştır
    res = client.post("/tasks", json={"description": "FastAPI REST API router for user permissions"})
    task_id = res.json()["id"]
    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200
    assert run_res.json()["status"] == "reviewed"

    # 2. Yeniden başlatmayı simüle et: Tamamen yeni bir TaskRepository ve WorkflowRunRepository örneği aç
    fresh_task_repo = TaskRepository(setup_test_db)
    fresh_run_repo = WorkflowRunRepository(setup_test_db)

    # Verilerin korunduğunu doğrula
    loaded_task = fresh_task_repo.get_task(task_id)
    assert loaded_task is not None
    assert loaded_task.status == TaskStatus.REVIEWED
    assert loaded_task.plan is not None
    assert loaded_task.coder is not None
    assert loaded_task.tester is not None
    assert loaded_task.reviewer is not None
    assert loaded_task.reviewer.verdict == ReviewerVerdict.APPROVED

    runs = fresh_run_repo.list_runs_for_task(task_id)
    assert len(runs) == 1
    assert runs[0].run_number == 1
    assert runs[0].status == TaskStatus.REVIEWED


def test_workflow_run_saved_to_history_table(client, setup_test_db):
    """Workflow tamamlandığında 'workflow_runs' tablosuna başlangıç, bitiş, süre ve metriklerle kaydedildiğini test eder."""
    res = client.post("/tasks", json={"description": "FastAPI REST API router for analytics"})
    task_id = res.json()["id"]

    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200

    run_repo = WorkflowRunRepository(setup_test_db)
    runs = run_repo.list_runs_for_task(task_id)
    assert len(runs) == 1
    r = runs[0]
    assert r.task_id == task_id
    assert r.run_number == 1
    assert r.status == TaskStatus.REVIEWED
    assert r.started_at is not None
    assert r.completed_at is not None
    assert r.duration_ms is not None and r.duration_ms >= 0
    assert len(r.agent_metrics) == 5  # PLANNER, SCOPE, CODER, TESTER, REVIEWER


def test_multiple_runs_for_same_task_creates_distinct_history(client, setup_test_db):
    """Aynı görevin birden fazla çalıştırılmasında her çalıştırmanın ayrı bir geçmiş kaydı (Run #1, Run #2) olduğunu test eder."""
    res = client.post("/tasks", json={"description": "FastAPI REST API router for inventory tracking"})
    task_id = res.json()["id"]

    # 1. İlk çalıştırma
    run_res1 = client.post(f"/tasks/{task_id}/run")
    assert run_res1.status_code == 200

    # 2. İkinci çalıştırma (aynı görev tekrar tetikleniyor)
    # Workspace çakışmasını simüle etmemek için task workspace temizliğini yapalım veya kod yeniden üretilsin
    ws_root = _get_safe_workspaces_root()
    task_ws = os.path.join(ws_root, task_id)
    if os.path.exists(task_ws):
        shutil.rmtree(task_ws, ignore_errors=True)

    run_res2 = client.post(f"/tasks/{task_id}/run")
    assert run_res2.status_code == 200

    # API üzerinden çalıştırma geçmişini sorgula
    runs_res = client.get(f"/tasks/{task_id}/runs")
    assert runs_res.status_code == 200
    runs_data = runs_res.json()
    assert runs_data["total_runs"] == 2
    assert len(runs_data["runs"]) == 2

    run1 = runs_data["runs"][0]
    run2 = runs_data["runs"][1]
    assert run1["run_number"] == 1
    assert run2["run_number"] == 2
    assert run1["id"] != run2["id"]


def test_failed_workflow_run_recorded_in_history(client, setup_test_db):
    """Hatalı / unsupported workflow çalıştırmalarının da geçmişe doğru status ve error ile kaydedildiğini test eder."""
    res = client.post("/tasks", json={"description": "Build Android Java App with 3D Vulkan engine"})
    task_id = res.json()["id"]

    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200
    assert run_res.json()["status"] == "unsupported"

    runs_res = client.get(f"/tasks/{task_id}/runs")
    assert runs_res.status_code == 200
    runs_data = runs_res.json()
    assert runs_data["total_runs"] == 1
    run = runs_data["runs"][0]
    assert run["status"] == "unsupported"
    assert run["coder"]["status"] == "unsupported"


def test_invalid_task_id_and_runs_404_behavior(client):
    """Olmayan task_id ile /runs ve /runs/{run_id} çağrıldığında 404 döndüğünü test eder."""
    res_runs = client.get("/tasks/task_invalid_9999/runs")
    assert res_runs.status_code == 404

    res_run_detail = client.get("/tasks/task_invalid_9999/runs/run_invalid_8888")
    assert res_run_detail.status_code == 404


def test_get_single_run_by_id(client, setup_test_db):
    """GET /tasks/{task_id}/runs/{run_id} ile tekil çalıştırma detayının eksiksiz döndüğünü test eder."""
    create_res = client.post("/tasks", json={"description": "FastAPI REST API router for notification preferences"})
    task_id = create_res.json()["id"]
    client.post(f"/tasks/{task_id}/run")

    runs_res = client.get(f"/tasks/{task_id}/runs")
    run_id = runs_res.json()["runs"][0]["id"]

    single_run_res = client.get(f"/tasks/{task_id}/runs/{run_id}")
    assert single_run_res.status_code == 200
    run_data = single_run_res.json()
    assert run_data["id"] == run_id
    assert run_data["task_id"] == task_id
    assert len(run_data["agent_metrics"]) == 5


# --- 5. LLM Provider & Planner Agent Entegrasyon Testleri ---

def test_llm_config_and_safe_metadata_never_leaks_key():
    """LLMConfig'in ortam değişkenlerini doğru parse ettiğini ve safe_metadata'da API anahtarını ASLA sızdırmadığını test eder."""
    cfg = LLMConfig(
        provider="openai",
        api_key="sk-secret-super-confidential-token-12345",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        temperature=0.3,
        max_tokens=1500,
        timeout=20.0,
        fallback_to_deterministic=True
    )
    assert cfg.is_configured() is True

    safe_meta = cfg.safe_metadata()
    assert "api_key" not in safe_meta
    assert "sk-secret-super-confidential-token-12345" not in str(safe_meta)
    assert safe_meta["provider"] == "openai"
    assert safe_meta["model"] == "gpt-4o-mini"
    assert safe_meta["base_host"] == "api.openai.com"
    assert safe_meta["temperature"] == 0.3
    assert safe_meta["fallback_to_deterministic"] is True


def test_load_project_env_loads_file_correctly(monkeypatch):
    """load_project_env fonksiyonunun .env dosyasını doğru yüklediğini test eder (Mock değerlerle)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        env_file_path = os.path.join(tmp_dir, ".env")
        with open(env_file_path, "w", encoding="utf-8") as f:
            f.write("TEST_CUSTOM_LOAD_VAR=loaded_mock_value_999\n")

        # Önce ortamda olmadığından emin ol
        monkeypatch.delenv("TEST_CUSTOM_LOAD_VAR", raising=False)
        load_project_env(base_dir=tmp_dir)

        assert os.environ.get("TEST_CUSTOM_LOAD_VAR") == "loaded_mock_value_999"


def test_load_project_env_does_not_override_existing_environ(monkeypatch):
    """load_project_env'in mevcut ortam değişkenlerini ezmediğini (override=False) test eder."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        env_file_path = os.path.join(tmp_dir, ".env")
        with open(env_file_path, "w", encoding="utf-8") as f:
            f.write("TEST_OVERRIDE_VAR=from_file_value\n")

        # Ortamda önceden bir değer ayarla
        monkeypatch.setenv("TEST_OVERRIDE_VAR", "existing_process_value")
        load_project_env(base_dir=tmp_dir)

        # Dosyadaki değer ortamdaki mevcut değeri ezmemeli
        assert os.environ.get("TEST_OVERRIDE_VAR") == "existing_process_value"


def test_extract_json_from_llm_text_variations():
    """extract_json_from_llm_text fonksiyonunun temiz JSON, markdown code fence ve karma metinleri parse edebildiğini test eder."""
    # 1. Düz JSON
    raw_json = '{"goal": "Build API", "subtasks": ["Step 1", "Step 2"], "acceptance_criteria": ["Crit 1"], "risks": ["Risk 1"]}'
    res1 = extract_json_from_llm_text(raw_json)
    assert res1["goal"] == "Build API"

    # 2. Markdown Code Block (```json ... ```)
    markdown_json = f"Burada üretilen plan bulunmaktadır:\n```json\n{raw_json}\n```\nİnceleyebilirsiniz."
    res2 = extract_json_from_llm_text(markdown_json)
    assert res2["goal"] == "Build API"
    assert len(res2["subtasks"]) == 2

    # 3. Geçersiz veya bozuk JSON fırlatması
    with pytest.raises(LLMResponseFormatError):
        extract_json_from_llm_text("Bu metin içerisinde herhangi bir JSON verisi bulunmamaktadır.")

    with pytest.raises(LLMResponseFormatError):
        extract_json_from_llm_text('{"goal": "Bozuk JSON", "subtasks": [')


@pytest.mark.asyncio
async def test_mock_llm_provider_success_and_metrics():
    """MockLLMProvider'ın deterministik olarak geçerli JSON ve token/gecikme metrikleri ürettiğini test eder."""
    provider = MockLLMProvider()
    assert provider.is_configured() is True

    response = await provider.generate("Test prompt", system_prompt="System prompt")
    assert isinstance(response, LLMResponse)
    assert response.provider == "mock"
    assert response.total_tokens > 0
    assert response.latency_ms > 0

    parsed = await provider.generate_json("Test prompt")
    assert "goal" in parsed
    assert len(parsed["subtasks"]) >= 4
    assert len(parsed["acceptance_criteria"]) >= 3
    assert len(parsed["risks"]) >= 2


@pytest.mark.asyncio
async def test_mock_llm_provider_simulated_errors():
    """MockLLMProvider ile simüle edilen zaman aşımı, yetkilendirme ve format hatalarını test eder."""
    # 1. Timeout Hatası
    timeout_provider = MockLLMProvider(simulate_error=LLMTimeoutError("İstek 15.0s zaman aşımına uğradı.", provider="mock"))
    with pytest.raises(LLMTimeoutError):
        await timeout_provider.generate("Test")

    # 2. Yetkilendirme Hatası (401)
    auth_provider = MockLLMProvider(simulate_error=LLMAuthenticationError("401 Unauthorized: Invalid API key", provider="mock", status_code=401))
    with pytest.raises(LLMAuthenticationError):
        await auth_provider.generate("Test")

    # 3. Geçersiz Format
    corrupt_provider = MockLLMProvider(custom_response="Bozuk yanıt...")
    with pytest.raises(LLMResponseFormatError):
        await corrupt_provider.generate_json("Test")


@pytest.mark.asyncio
async def test_llm_planner_schema_validation_success():
    """_llm_planner fonksiyonunun geçerli model çıktısını Pydantic TaskPlan modeline dönüştürdüğünü test eder."""
    provider = MockLLMProvider()
    plan = await _llm_planner("FastAPI JWT Authentication feature", provider)

    assert isinstance(plan, TaskPlan)
    assert plan.goal != ""
    assert len(plan.subtasks) >= 4
    assert len(plan.acceptance_criteria) >= 3
    assert len(plan.risks) >= 2


@pytest.mark.asyncio
async def test_llm_planner_schema_validation_rejects_malformed_plan():
    """_llm_planner'ın eksik zorunlu alan içeren model yanıtlarını reddettiğini ve hata fırlattığını test eder."""
    # Eksik subtasks
    invalid_json = '{"goal": "Hedef var", "subtasks": [], "acceptance_criteria": ["Kriter 1"], "risks": ["Risk 1"]}'
    corrupt_provider = MockLLMProvider(custom_response=invalid_json)

    with pytest.raises(LLMResponseFormatError):
        await _llm_planner("Test task", corrupt_provider)


@pytest.mark.asyncio
async def test_workflow_planner_deterministic_mode():
    """LangGraph iş akışının planner_mode='deterministic' ile hatasız çalıştığını test eder."""
    task_id = "test_plan_det_001"
    desc = "FastAPI REST API router for user profile management"
    result = await run_agent_workflow(task_id=task_id, description=desc, planner_mode="deterministic")

    assert result["status"] in [TaskStatus.REVIEWED.value, TaskStatus.CODED.value, TaskStatus.TESTED.value]
    assert result["plan"] is not None
    assert "user profile management" in result["plan"]["goal"].lower()

    # Olaylarda planner_mode="deterministic" kaydı aranır
    plan_events = [e for e in result["events"] if e.get("source") == "PLANNER_AGENT"]
    assert any(e.get("details", {}).get("planner_mode") == "deterministic" for e in plan_events)


@pytest.mark.asyncio
async def test_workflow_planner_llm_mode_fallback_when_unconfigured(monkeypatch):
    """API anahtarı yapılandırılmamışken planner_mode='llm' istendiğinde güvenli fallback moduna geçtiğini test eder."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_TO_DETERMINISTIC", "true")

    task_id = "test_plan_fallback_001"
    desc = "FastAPI REST API router for product catalog search"
    result = await run_agent_workflow(task_id=task_id, description=desc, planner_mode="llm")

    assert result["status"] in [TaskStatus.REVIEWED.value, TaskStatus.CODED.value, TaskStatus.TESTED.value]
    assert result["plan"] is not None

    # Fallback olayının kaydedildiğini doğrula
    fallback_events = [e for e in result["events"] if e.get("type") == "planner_fallback"]
    assert len(fallback_events) >= 1
    assert fallback_events[0]["details"]["reason"] == "missing_api_key"


@pytest.mark.asyncio
async def test_workflow_planner_llm_mode_fails_when_fallback_disabled(monkeypatch):
    """Fallback kapalıyken (LLM_FALLBACK_TO_DETERMINISTIC=false) yapılandırılmamış LLM istendiğinde görevin FAILED olduğunu test eder."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_TO_DETERMINISTIC", "false")

    task_id = "test_plan_no_fallback_001"
    desc = "FastAPI REST API router for analytics aggregation"
    result = await run_agent_workflow(task_id=task_id, description=desc, planner_mode="llm")

    assert result["status"] == TaskStatus.FAILED.value
    assert result["plan"] is None
    assert "yapılandırılmamış" in result["error"] or "unconfigured" in result["error"]


@pytest.mark.asyncio
async def test_workflow_planner_llm_mode_success_with_mock_provider(monkeypatch):
    """MockLLMProvider ile LLM modunun tam iş akışında başarıyla çalıştığını ve metriklerin kaydedildiğini test eder."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "mock-gpt-4o-planner")

    task_id = "test_plan_mock_llm_001"
    desc = "FastAPI REST API router for payment transaction webhooks"
    result = await run_agent_workflow(task_id=task_id, description=desc, planner_mode="llm")

    assert result["status"] in [TaskStatus.REVIEWED.value, TaskStatus.CODED.value, TaskStatus.TESTED.value]
    assert result["plan"] is not None

    # Olaylarda LLM mode kaydını doğrula
    plan_completed_events = [
        e for e in result["events"]
        if e.get("source") == "PLANNER_AGENT" and e.get("type") == "plan_created"
    ]
    assert len(plan_completed_events) >= 1
    assert plan_completed_events[0]["details"]["planner_mode"] == "llm"
    assert plan_completed_events[0]["details"]["provider"] == "mock"
    assert plan_completed_events[0]["details"]["model"] == "mock-gpt-4o-planner"


def test_api_get_llm_info_endpoint(client, monkeypatch):
    """GET /system/llm-info endpoint'inin sağlayıcı ve model durumunu API anahtarı olmadan döndürdüğünü test eder."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "mock-v1")

    res = client.get("/system/llm-info")
    assert res.status_code == 200
    data = res.json()

    assert data["provider"] == "mock"
    assert data["model"] == "mock-v1"
    assert data["is_configured"] is True
    assert "api_key" not in data


def test_api_create_and_run_task_with_planner_mode(client, setup_test_db, monkeypatch):
    """API üzerinden görev oluşturma ve çalıştırma sırasında planner_mode parametresinin doğru çalıştığını test eder."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "mock-planner-model")

    # 1. LLM Modu ile görev oluştur
    create_res = client.post("/tasks", json={
        "description": "FastAPI REST API router for customer loyalty points",
        "planner_mode": "llm"
    })
    assert create_res.status_code == 201
    task_id = create_res.json()["id"]

    # 2. Görevi çalıştır
    run_res = client.post(f"/tasks/{task_id}/run?planner_mode=llm")
    assert run_res.status_code == 200
    run_data = run_res.json()
    assert run_data["status"] in ["reviewed", "tested", "coded"]

    # 3. Çalıştırma geçmişi ve agent metriklerini doğrula
    runs_res = client.get(f"/tasks/{task_id}/runs")
    assert runs_res.status_code == 200
    runs_list = runs_res.json()["runs"]
    assert len(runs_list) >= 1

    run_record = runs_list[0]
    planner_metric = next((m for m in run_record["agent_metrics"] if m["agent_name"] == "PLANNER"), None)
    assert planner_metric is not None
    assert planner_metric["mode"] == "llm"
    assert planner_metric["provider"] == "mock"
    assert planner_metric["model"] == "mock-planner-model"


def test_api_key_zero_leakage_guarantee(client, setup_test_db, monkeypatch):
    """Gizli API anahtarının veritabanı kayıtlarına, olaylara, metrik loglarına veya API yanıtlarına ASLA sızmadığını test eder."""
    secret_key = "sk-super-secret-production-private-token-998877"
    monkeypatch.setenv("OPENAI_API_KEY", secret_key)
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    create_res = client.post("/tasks", json={
        "description": "FastAPI REST API router for audit log storage",
        "planner_mode": "llm"
    })
    task_id = create_res.json()["id"]

    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200

    # 1. Task JSON yanıtında kontrol
    task_detail_res = client.get(f"/tasks/{task_id}")
    assert secret_key not in task_detail_res.text

    # 2. Runs JSON yanıtında kontrol
    runs_res = client.get(f"/tasks/{task_id}/runs")
    assert secret_key not in runs_res.text

    # 3. LLM Info JSON yanıtında kontrol
    info_res = client.get("/system/llm-info")
    assert secret_key not in info_res.text

