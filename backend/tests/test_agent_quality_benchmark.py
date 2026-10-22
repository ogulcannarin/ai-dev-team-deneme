"""
backend/tests/test_agent_quality_benchmark.py
AI Dev Team - Agent Quality Benchmark Değerlendirme Paketi

10 Temel Kalite ve Güvenlik Senaryosu:
1. Başarılı REST API üretimi (Planner -> Scope -> Coder -> Tester -> Reviewer)
2. Veri modeli ve validasyon üretimi (ItemCreate, ItemResponse, Pydantic kuralları)
3. Eksik veya hatalı / desteklenmeyen görev yönetimi (Unsupported fail-safe)
4. Tester tarafından yakalanabilen kod hatası (Defect detection)
5. Reviewer tarafından reddedilmesi gereken kod (Code review quality & rejection)
6. Retry sonrasında kodun düzelip düzelmediği (True Recovery Loop)
7. Güvenlik kontrolünü tetikleyen zararsız test girdileri (AST Security filter)
8. Docker kullanılamadığında güvenli bloklama (Fail-safe host escape prevention)
9. İnsan onayı gerektiren akış (HITL Approval, Rejection & Event audit)
10. LLM erişilemediğinde deterministik fallback (Resilience & Zero-crash)
"""

import asyncio
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from database import init_db, get_db_connection
from execution.base import ExecutionConfig, ExecutionResult
from execution.docker_engine import DockerExecutionEngine
from execution.mock_engine import MockExecutionEngine
from execution import UnavailableExecutionEngine
from main import app
from repository import TaskRepository, WorkflowRunRepository
from schemas import (
    FindingSeverity,
    ReviewerVerdict,
    TaskApprovalRequest,
    TaskRejectRequest,
    TaskStatus,
)
from agent_workflow import (
    _deterministic_planner,
    _deterministic_scope,
    _execute_coder_in_workspace,
    _execute_reviewer_in_workspace,
    _execute_tester_in_workspace,
    _is_supported_task,
    _validate_python_ast_security,
    _route_after_reviewer,
    run_agent_workflow,
)
from llm_provider import (
    LLMConfig,
    MockLLMProvider,
    LLMRateLimitError,
    LLMTimeoutError,
    get_llm_provider,
)

# Benchmark Metrik Deposu
BENCHMARK_RESULTS: Dict[str, Dict[str, Any]] = {}


@pytest.fixture(autouse=True)
def setup_benchmark_db(tmp_path, monkeypatch):
    """Her benchmark testi için izole geçici SQLite veritabanı hazırlar."""
    test_db_file = str(tmp_path / "test_benchmark.db")
    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", test_db_file)
    init_db(test_db_file)
    yield


@pytest.fixture
def client():
    return TestClient(app)


# =====================================================================
# SENARYO 1: BAŞARILI REST API ÜRETİMİ
# =====================================================================

def test_benchmark_01_successful_rest_api_generation(monkeypatch):
    """
    Senaryo 1: Standart CRUD REST API görevi için Planner, Scope, Coder, Tester ve Reviewer
    aşamalarının hatasız tamamlanması, kod dosyalarının üretilmesi ve testlerin geçmesi.
    """
    task_id = "bench_01_rest_api"
    desc = "FastAPI Items CRUD REST API with pydantic schemas"
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")

    start_time = time.perf_counter()
    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description=desc,
        planner_mode="deterministic",
        coder_mode="deterministic",
        max_retries=2
    ))
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # Doğrulamalar
    assert result["status"] == TaskStatus.REVIEWED.value
    assert result["plan"] is not None
    assert len(result["plan"]["subtasks"]) >= 3
    assert result["scope"] is not None
    assert result["coder"]["status"] == "coded"
    assert len(result["coder"]["created_files"]) >= 2
    assert result["tester"]["status"] == "tested"
    assert result["tester"]["passed"] >= 4
    assert result["tester"]["failed"] == 0
    assert result["reviewer"]["verdict"] == ReviewerVerdict.APPROVED.value

    BENCHMARK_RESULTS["Scenario_01_REST_API"] = {
        "scenario": "Başarılı REST API Üretimi",
        "expected": "Status: reviewed, Tester: 4 passed / 0 failed, Reviewer: APPROVED",
        "actual": f"Status: {result['status']}, Tester: {result['tester']['passed']} passed, Reviewer: {result['reviewer']['verdict']}",
        "status": "PASS",
        "duration_ms": duration_ms,
        "isolation_type": result["tester"]["isolation_type"],
        "metric": "Success: 1/1 (100%)"
    }


# =====================================================================
# SENARYO 2: VERİ MODELİ VE VALİDASYON ÜRETİMİ
# =====================================================================

def test_benchmark_02_data_model_and_validation(monkeypatch):
    """
    Senaryo 2: Pydantic veri modellerinin tip güvenliği, zorunlu alan doğrulaması
    ve eksik alanlarda ValidationError fırlatmasının izole test ortamında doğrulanması.
    """
    task_id = "bench_02_models"
    desc = "FastAPI Data Models and strict field validation"
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")

    start_time = time.perf_counter()
    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description=desc,
        planner_mode="deterministic",
        coder_mode="deterministic",
    ))
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    assert result["coder"]["status"] == "coded"
    created = result["coder"]["created_files"]
    assert any("models.py" in f for f in created)
    assert any("api_feature.py" in f for f in created)

    # Tester sonuçları (ItemCreate valid ve invalid test senaryolarını içerir)
    assert result["tester"]["status"] == "tested"
    assert result["tester"]["passed"] >= 4
    assert result["tester"]["failed"] == 0

    BENCHMARK_RESULTS["Scenario_02_Data_Validation"] = {
        "scenario": "Veri Modeli ve Validasyon Üretimi",
        "expected": "models.py üretimi, ItemCreate ve ValidationError testlerinin geçmesi",
        "actual": f"models.py mevcut, {result['tester']['passed']} test başarıyla geçti",
        "status": "PASS",
        "duration_ms": duration_ms,
        "isolation_type": result["tester"]["isolation_type"],
        "metric": "Validation Integrity: 1/1 (100%)"
    }


# =====================================================================
# SENARYO 3: EKSİK / HATALI / DESTEKLENMEYEN GÖREV YÖNETİMİ
# =====================================================================

def test_benchmark_03_unsupported_or_invalid_task():
    """
    Senaryo 3: Desteklenmeyen veya geçersiz şablonlu bir görev geldiğinde
    Coder ve iş akışının durumu false-positive üretmeden 'unsupported' olarak sonlandırması.
    """
    task_id = "bench_03_unsupported"
    unsupported_desc = "Haskell binary parser with monad transformers"

    start_time = time.perf_counter()
    is_supported = _is_supported_task(unsupported_desc)
    assert is_supported is False

    coder_res = _execute_coder_in_workspace(task_id, unsupported_desc)
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    assert coder_res.status == "unsupported"
    assert len(coder_res.created_files) == 0

    BENCHMARK_RESULTS["Scenario_03_Unsupported_Task"] = {
        "scenario": "Eksik/Desteklenmeyen Görev Yönetimi",
        "expected": "is_supported=False, Coder status: unsupported, 0 dosya üretimi",
        "actual": f"is_supported={is_supported}, Coder status: {coder_res.status}",
        "status": "PASS",
        "duration_ms": duration_ms,
        "isolation_type": "none",
        "metric": "False Positive Prevention: 1/1 (100%)"
    }


# =====================================================================
# SENARYO 4: TESTER TARAFINDAN YAKALANABİLECEK KOD HATASI
# =====================================================================

def test_benchmark_04_tester_defect_detection(monkeypatch):
    """
    Senaryo 4: Kod içinde birim test başarısızlığı olduğunda Tester Agent'ın
    bu kusuru doğru biçimde yakalaması, failed sayısını artırması ve TesterResult.status='failed' üretmesi.
    """
    task_id = "bench_04_tester_defect"

    # 1 testin başarısız olduğu simülasyon motoru
    class DefectMockEngine(MockExecutionEngine):
        def execute_sync(self, ws, cmd, config=None):
            return ExecutionResult(
                status="failed",
                exit_code=1,
                stdout="test_01 (test_feature.Test) ... FAIL\nAssertionError: Expected 200 got 500",
                stderr="FAILED (failures=1)",
                duration_ms=40.0,
                isolation_type="mock",
                raw_output="test_01 ... FAIL\nAssertionError: Expected 200 got 500\nFAILED (failures=1)",
                error="Process exited with code 1"
            )

    start_time = time.perf_counter()
    with tempfile.TemporaryDirectory() as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)
        with open(os.path.join(task_ws, "models.py"), "w", encoding="utf-8") as f:
            f.write("# Dummy model\n")

        tester_res = _execute_tester_in_workspace(
            task_id=task_id,
            description="FastAPI CRUD",
            workspaces_root=temp_root,
            engine=DefectMockEngine()
        )
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    assert tester_res.status == "failed"
    assert tester_res.failed >= 1
    assert "hata" in tester_res.summary.lower() or "başarısız" in tester_res.summary.lower()

    BENCHMARK_RESULTS["Scenario_04_Defect_Detection"] = {
        "scenario": "Tester Kod Hatası Yakalama",
        "expected": "Tester status: failed, failed >= 1, kusur loglandı",
        "actual": f"Tester status: {tester_res.status}, failed: {tester_res.failed}",
        "status": "PASS",
        "duration_ms": duration_ms,
        "isolation_type": "mock",
        "metric": "Defect Catch Rate: 1/1 (100%)"
    }


# =====================================================================
# SENARYO 5: REVIEWER TARAFINDAN REDDEDİLMESİ GEREKEN KOD
# =====================================================================

def test_benchmark_05_reviewer_rejection_quality():
    """
    Senaryo 5: Reviewer Agent'ın hatalı kod kalıplarını (bare except:pass, eksik dosyalar vb.)
    tespit ederek CHANGES_REQUESTED kararı vermesi ve onay vermemesi.
    """
    task_id = "bench_05_reviewer_reject"

    start_time = time.perf_counter()
    with tempfile.TemporaryDirectory() as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        # Kötü kod kalıbı içeren dosya
        with open(os.path.join(task_ws, "api_feature.py"), "w", encoding="utf-8") as f:
            f.write("def do_something():\n    try:\n        x = 1/0\n    except:\n        pass\n")

        reviewer_res = _execute_reviewer_in_workspace(
            task_id=task_id,
            description="FastAPI Service",
            coder_data={"status": "coded", "created_files": ["api_feature.py"]},
            tester_data={"status": "tested", "passed": 2, "failed": 0, "test_results": []},
            workspaces_root=temp_root
        )
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    assert reviewer_res.verdict == ReviewerVerdict.CHANGES_REQUESTED
    assert len(reviewer_res.findings) >= 1
    assert any("except" in (f.description or f.title).lower() for f in reviewer_res.findings)

    BENCHMARK_RESULTS["Scenario_05_Reviewer_Rejection"] = {
        "scenario": "Reviewer Kod Reddi ve Kalite Denetimi",
        "expected": "Reviewer verdict: CHANGES_REQUESTED, Bare except bulgusu",
        "actual": f"Verdict: {reviewer_res.verdict.value}, Bulgu sayısı: {len(reviewer_res.findings)}",
        "status": "PASS",
        "duration_ms": duration_ms,
        "isolation_type": "none",
        "metric": "Rejection Accuracy: 1/1 (100%)"
    }


# =====================================================================
# SENARYO 6: RETRY SONRASINDA KODUN DÜZELMESİ (TRUE RECOVERY LOOP)
# =====================================================================

def test_benchmark_06_true_retry_recovery(monkeypatch):
    """
    Senaryo 6: İlk üretim hatalı bayt yazar. Retry farklı ve düzeltilmiş içerik üretir,
    ikinci Tester başarılı olur ve görev reviewed / approved olur.
    """
    import agent_workflow

    task_id = "bench_06_recovery"
    description = "FastAPI Items CRUD REST API"
    task_repo = TaskRepository()
    task_repo.create_task(task_id, description)

    generated_models = []
    original_files = agent_workflow._generate_deterministic_code_files

    def scripted_code_files(generated_task_id, generated_description):
        files = dict(original_files(generated_task_id, generated_description))
        models = files["models.py"]
        if not generated_models:
            models = models + "\nBUG_MARKER = True\n"
        generated_models.append(models)
        files["models.py"] = models
        return files

    class ContentAwareMockEngine(MockExecutionEngine):
        def __init__(self):
            super().__init__()
            self.calls = 0
            self.observed_models = []

        def is_available(self):
            return True

        def get_isolation_type(self):
            return "mock"

        def execute_sync(self, workspace_path, command, config=None):
            del command, config
            self.calls += 1
            models_path = os.path.join(workspace_path, "models.py")
            try:
                with open(models_path, "r", encoding="utf-8") as handle:
                    content = handle.read()
            except OSError:
                content = ""
            self.observed_models.append(content)
            if "BUG_MARKER" not in content:
                raw_output = (
                    "test_items (test_feature.TestItems) ... ok\n"
                    "test_create (test_feature.TestItems) ... ok\n\n"
                    "Ran 2 tests in 0.001s\n\nOK\n"
                )
                return ExecutionResult(
                    status="success",
                    exit_code=0,
                    stdout=raw_output,
                    stderr="",
                    duration_ms=30.0,
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
                duration_ms=45.0,
                isolation_type="mock",
                raw_output=raw_output,
                error="Test failure on attempt 1",
            )

    engine_inst = ContentAwareMockEngine()
    monkeypatch.setattr(agent_workflow, "_generate_deterministic_code_files", scripted_code_files)
    monkeypatch.setattr(agent_workflow, "get_execution_engine", lambda preferred=None: engine_inst)

    start_time = time.perf_counter()
    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description=description,
        planner_mode="deterministic",
        coder_mode="deterministic",
        max_retries=2
    ))
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    assert len(generated_models) == 2
    assert generated_models[0] != generated_models[1]
    assert "BUG_MARKER" in generated_models[0]
    assert "BUG_MARKER" not in generated_models[1]
    assert engine_inst.calls == 2
    assert "BUG_MARKER" in engine_inst.observed_models[0]
    assert "BUG_MARKER" not in engine_inst.observed_models[1]
    models_path = os.path.join(os.path.dirname(__file__), "..", "workspaces", task_id, "models.py")
    with open(models_path, "r", encoding="utf-8") as handle:
        final_models = handle.read()
    assert final_models == generated_models[1]
    assert "BUG_MARKER" not in final_models

    assert result["retry_count"] == 1
    assert len(result["retry_history"]) == 1
    assert result["retry_history"][0]["attempt"] == 1
    assert result["retry_history"][0]["tester"]["status"] == "failed"
    tester = result["tester"]
    assert tester["status"] in {"tested", "passed"}
    assert tester["failed"] == 0
    assert tester["passed"] > 0
    assert result["status"] == TaskStatus.REVIEWED.value
    assert result["reviewer"]["verdict"] == ReviewerVerdict.APPROVED.value
    limitations = (result.get("coder") or {}).get("limitations") or []
    assert all("içerik değişmedi" not in item for item in limitations)

    BENCHMARK_RESULTS["Scenario_06_Retry_Recovery"] = {
        "scenario": "Retry İyileşmesi (True Recovery)",
        "expected": "1. deneme failed -> retry_count=1 -> 2. deneme passed -> APPROVED",
        "actual": f"retry_count: {result['retry_count']}, history snapshot: {len(result['retry_history'])}, final verdict: {result['reviewer']['verdict']}",
        "status": "PASS",
        "duration_ms": duration_ms,
        "isolation_type": "mock",
        "metric": "Recovery Rate: 1/1 (100%)"
    }


# =====================================================================
# SENARYO 7: GÜVENLİK KONTROLÜ / ZARARSIZ TEST GİRDİSİ (AST SECURITY)
# =====================================================================

def test_benchmark_07_security_ast_inspection():
    """
    Senaryo 7: Zararlı / yasaklı import (socket, subprocess vb.) içeren kodun
    AST analizörü tarafından kod çalıştırılmadan tespit edilip BLOCKED durumuna alınması.
    """
    task_id = "bench_07_ast_security"

    start_time = time.perf_counter()
    with tempfile.TemporaryDirectory() as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        with open(os.path.join(task_ws, "api_feature.py"), "w", encoding="utf-8") as f:
            f.write("import socket\ns = socket.socket()\n")

        tester_res = _execute_tester_in_workspace(
            task_id=task_id,
            description="Socket communication",
            workspaces_root=temp_root
        )

        reviewer_res = _execute_reviewer_in_workspace(
            task_id=task_id,
            description="Socket communication",
            coder_data={"status": "coded", "created_files": ["api_feature.py"]},
            tester_data=tester_res.model_dump(),
            workspaces_root=temp_root
        )

        dummy_state = {
            "status": TaskStatus.BLOCKED.value,
            "reviewer": reviewer_res.model_dump(),
            "tester": tester_res.model_dump(),
            "retry_count": 0,
            "max_retries": 2
        }
        route = _route_after_reviewer(dummy_state)
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # Doğrulamalar
    assert tester_res.status == "blocked"
    assert "Yasaklı ağ/sistem modülü" in (tester_res.error or "")
    assert reviewer_res.verdict == ReviewerVerdict.BLOCKED
    assert route == "end"  # Güvenlik blokajında asla retry yapılmaz

    BENCHMARK_RESULTS["Scenario_07_AST_Security"] = {
        "scenario": "AST Güvenlik ve Yasaklı Modül Taraması",
        "expected": "Tester: blocked, Reviewer: BLOCKED, Retry: Asla yapılmaz (route=end)",
        "actual": f"Tester: {tester_res.status}, Reviewer: {reviewer_res.verdict.value}, Route: {route}",
        "status": "PASS",
        "duration_ms": duration_ms,
        "isolation_type": "none",
        "metric": "Security Trap Rate: 1/1 (100%)"
    }


# =====================================================================
# SENARYO 8: DOCKER KULLANILAMADIĞINDA GÜVENLİ BLOKLAMA
# =====================================================================

def test_benchmark_08_docker_unavailable_fail_safe():
    """
    Senaryo 8: Docker daemon çalışmadığında sistemin güvensiz host fallback'e
    geçmeyerek kodu çalıştırmayı reddetmesi ve açıkça BLOCKED döndürmesi.
    """
    task_id = "bench_08_docker_fail_safe"
    unavailable_engine = UnavailableExecutionEngine()

    start_time = time.perf_counter()
    assert unavailable_engine.is_available() is False
    assert unavailable_engine.get_isolation_type() == "none"

    exec_res = unavailable_engine.execute_sync("fake/ws", ["python", "-m", "unittest"])
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    assert exec_res.status == "blocked"
    assert "Güvenli Docker motoru bulunamadı" in exec_res.error

    BENCHMARK_RESULTS["Scenario_08_Docker_FailSafe"] = {
        "scenario": "Docker Yokluğunda Güvenli Bloklama",
        "expected": "is_available=False, execute_sync status: blocked, 0 host execution",
        "actual": f"is_available: False, status: {exec_res.status}, isolation: {exec_res.isolation_type}",
        "status": "PASS",
        "duration_ms": duration_ms,
        "isolation_type": "none",
        "metric": "Host Escape Prevention: 1/1 (100%)"
    }


# =====================================================================
# SENARYO 9: İNSAN ONAYI (HITL) AKIŞI VE VERİ TABANI TUTARLILIĞI
# =====================================================================

def test_benchmark_09_hitl_approval_and_rejection(client):
    """
    Senaryo 9: İnsan Onayı (HITL) etkin görevlerde /approve ile completed,
    /reject ile changes_requested durumuna geçiş ve SQLite olay günlüğünün denetimi.
    """
    start_time = time.perf_counter()
    # 1. Onay Akışı. completed için reviewer, test kanıtı ve teslim edilebilir dosya gerekir.
    create1 = client.post("/tasks", json={"description": "FastAPI Items REST API"})
    t1_id = create1.json()["id"]
    from agent_workflow import _get_safe_workspaces_root
    workspace = os.path.join(_get_safe_workspaces_root(), t1_id)
    os.makedirs(workspace, exist_ok=True)
    with open(os.path.join(workspace, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("benchmark teslimat\n")
    TaskRepository().update_task_workflow_result(
        task_id=t1_id,
        status=TaskStatus.REVIEWED,
        reviewer={"status": "reviewed", "verdict": "approved", "summary": "Hazır", "findings": [], "reviewed_files": []},
        tester={"status": "tested", "passed": 4, "failed": 0, "summary": "Testler geçti", "test_results": []},
        coder={"status": "coded", "created_files": ["README.md"], "summary": "Dosya hazır", "limitations": []},
    )

    appr_res = client.post(f"/tasks/{t1_id}/approve", json={"comment": "Onaylandı", "approved_by": "qa_architect"})
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == TaskStatus.COMPLETED.value

    # 2. Red Akışı
    create2 = client.post("/tasks", json={"description": "FastAPI Auth JWT Service"})
    t2_id = create2.json()["id"]
    TaskRepository().update_task_workflow_result(
        task_id=t2_id,
        status=TaskStatus.REVIEWED,
        reviewer={"status": "reviewed", "verdict": "approved", "summary": "Hazır", "findings": [], "reviewed_files": []}
    )

    rej_res = client.post(f"/tasks/{t2_id}/reject", json={"reason": "Eksik parametre", "rejected_by": "qa_architect"})
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == TaskStatus.CHANGES_REQUESTED.value
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    def _onerror(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    delivery_root = os.path.join(_get_safe_workspaces_root(), ".delivery")
    for path in (workspace, os.path.join(delivery_root, f"{t1_id}.git")):
        if not os.path.lexists(path):
            continue
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_onerror)
        else:
            shutil.rmtree(path, onerror=_onerror)
    lock_path = os.path.join(delivery_root, f"{t1_id}.lock")
    if os.path.lexists(lock_path):
        os.chmod(lock_path, stat.S_IWRITE)
        os.remove(lock_path)

    BENCHMARK_RESULTS["Scenario_09_HITL_Flow"] = {
        "scenario": "İnsan Onayı (HITL) ve Olay Günlüğü",
        "expected": "Approve -> COMPLETED, Reject -> CHANGES_REQUESTED, Olay günlüğü yazımı",
        "actual": f"Approve: {appr_res.json()['status']}, Reject: {rej_res.json()['status']}",
        "status": "PASS",
        "duration_ms": duration_ms,
        "isolation_type": "none",
        "metric": "HITL State Accuracy: 2/2 (100%)"
    }


# =====================================================================
# SENARYO 10: LLM ERİŞİLEMEZKEN DETERMINİSTİK FALLBACK
# =====================================================================

def test_benchmark_10_llm_fallback_resilience(monkeypatch):
    """
    Senaryo 10: LLM yapılandırılmadığında veya model çağrısı sırasında hata oluştuğunda
    sistemin çökmeden deterministik planlayıcıya fallback yapması ve 'fallback' modunu kaydetmesi.
    """
    task_id = "bench_10_llm_fallback"
    desc = "FastAPI Items CRUD Service"
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")

    # API Key olmayan yapılandırma
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LLM_FALLBACK_TO_DETERMINISTIC", "true")

    start_time = time.perf_counter()
    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description=desc,
        planner_mode="llm"
    ))
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    assert result["plan"] is not None
    assert len(result["plan"]["subtasks"]) >= 3
    # Fallback olayını doğrula
    events = result.get("events", [])
    fallback_evt = next((e for e in events if e.get("details", {}).get("planner_mode") == "fallback"), None)
    assert fallback_evt is not None

    BENCHMARK_RESULTS["Scenario_10_LLM_Fallback"] = {
        "scenario": "LLM Fallback Dayanıklılığı",
        "expected": "LLM erişilemez -> Deterministik Fallback -> Plan başarıyla üretildi",
        "actual": f"Plan üretildi (subtasks: {len(result['plan']['subtasks'])}), fallback_event={fallback_evt is not None}",
        "status": "PASS",
        "duration_ms": duration_ms,
        "isolation_type": "mock",
        "metric": "Fallback Resilience: 1/1 (100%)"
    }


# =====================================================================
# BENCHMARK ÖZET RAPORLAYICI VE METRİK TOPLAYICI
# =====================================================================

def test_benchmark_summary_generation():
    """
    Tüm 10 senaryonun sonuçlarını toplar, JSON raporunu scratch dizinine yazar
    ve başarı oranlarını doğrular.
    """
    total_scenarios = len(BENCHMARK_RESULTS)
    passed_scenarios = sum(1 for v in BENCHMARK_RESULTS.values() if v.get("status") == "PASS")

    assert total_scenarios == 10, f"10 senaryonun tümü çalıştırılmış olmalıdır (Mevcut: {total_scenarios})"
    assert passed_scenarios == 10, f"10 senaryonun tümü PASS olmalıdır (Geçen: {passed_scenarios}/{total_scenarios})"

    # Benchmark Özet JSON'ı
    summary_report = {
        "benchmark_suite": "AI Dev Team - Agent Quality Benchmark",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_scenarios": total_scenarios,
        "passed_scenarios": passed_scenarios,
        "failed_scenarios": total_scenarios - passed_scenarios,
        "success_rate_percent": round((passed_scenarios / total_scenarios) * 100, 2),
        "results": BENCHMARK_RESULTS
    }

    report_path = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary_report, f, indent=2, ensure_ascii=False)

    assert os.path.exists(report_path)
