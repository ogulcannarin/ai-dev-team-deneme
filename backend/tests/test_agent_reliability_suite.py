"""
backend/tests/test_agent_reliability_suite.py
AI Dev Team — Agent Reliability Test Suite

8 Kritik Güvenilirlik Senaryosu:
1. Başarılı Python görevi — Canlı Docker Sandbox.
2. Bilerek hatalı sonuç üreten fonksiyon (Logic Bug) — Canlı Docker Sandbox & AssertionError.
3. Tester başarısızlığı — Görevin asla sahte onay almaması.
4. Eksik çalışma alanı dosyası — Reviewer'ın eksik dosyayı tespit etmesi.
5. SyntaxError / runner çökmesi — Canlı Docker Sandbox çıkış kodu ve hata ayrıştırması.
6. Docker kullanılamadığında güvenli engelleme (No Host Fallback).
7. Reviewer için parametrik sıfır hatalı onay (Zero False Positive) matrisi.
8. Retry sınırına ulaşılması — 'retry_exhausted' olayı ve temiz sonlanma.
"""

import asyncio
import os
import shutil
import tempfile
import uuid
import pytest

from database import init_db
from execution.docker_engine import DockerExecutionEngine
from execution.mock_engine import MockExecutionEngine
from repository import TaskRepository
from schemas import (
    FindingSeverity,
    ReviewerResult,
    ReviewerVerdict,
    TaskStatus,
    TesterResult,
)
from agent_workflow import (
    _execute_reviewer_in_workspace,
    _execute_tester_in_workspace,
    _generate_test_suite_code,
    _parse_unittest_output,
    run_agent_workflow,
)


def _is_docker_available() -> bool:
    """Sistemde Docker CLI ve daemon'ın çalışıp çalışmadığını güvenle kontrol eder."""
    try:
        engine = DockerExecutionEngine()
        return engine.is_available()
    except Exception:
        return False


DOCKER_SANDBOX_AVAILABLE = _is_docker_available()


@pytest.fixture
def isolated_db(monkeypatch):
    """Her test için izole geçici SQLite veritabanı sağlar."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", db_path)
    init_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


# =====================================================================
# SENARYO 1: Başarılı Python Görevi (Canlı Docker Sandbox)
# =====================================================================

@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker sandbox hazır değil; canlı test atlandı.")
def test_reliability_01_happy_path_live_docker(isolated_db, monkeypatch):
    """
    Senaryo 1: Geçerli hesaplama modülü ve doğru testler içeren görev.
    - Testler Docker sandbox içinde koşturulmalıdır.
    - 4 birim testinin tamamı başarıyla geçmelidir.
    - Reviewer hiçbir engelleyici bulgu bulmayıp APPROVED vermelidir.
    """
    monkeypatch.setenv("EXECUTION_ENGINE", "docker")

    task_id = f"task_rel_happy_{uuid.uuid4().hex[:6]}"
    desc = "Python ile çalışan basit bir hesaplama modülü oluştur. İki sayıyı toplayan bir fonksiyon yaz ve fonksiyonun doğru çalıştığını doğrulayan pytest testleri ekle."

    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description=desc,
        planner_mode="deterministic"
    ))

    # Durum ve Ajan Çıktıları Doğrulaması
    assert result["status"] == TaskStatus.REVIEWED.value
    assert result.get("coder") is not None
    assert result["coder"]["status"] == "coded"

    # Tester Sonuçları
    tester = result.get("tester")
    assert tester is not None
    assert tester["status"] == "tested"
    assert tester["isolation_type"] == "docker"
    assert tester["passed"] >= 4
    assert tester["failed"] == 0
    assert tester["error"] is None

    # Test isimlerinin gerçek metot adları olduğunu doğrula
    test_names = [t["name"] for t in tester["test_results"]]
    assert any(n.startswith("test_01") for n in test_names)

    # Reviewer Onayı
    reviewer = result.get("reviewer")
    assert reviewer is not None
    assert reviewer["status"] == "reviewed"
    assert reviewer["verdict"] == "approved"
    assert len(reviewer["findings"]) == 0


# =====================================================================
# SENARYO 2: Bilerek Hatalı Mantık (Logic Bug) Enjeksiyonu (Canlı Docker)
# =====================================================================

@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker sandbox hazır değil; canlı test atlandı.")
def test_reliability_02_intentional_logic_bug_live_docker():
    """
    Senaryo 2: Bilerek yanlış sonuç üreten toplama fonksiyonu:
    add(2, 3) -> 6 (2 + 3 + 1)
    - Kod gerçek Docker container içinde çalıştırılmalıdır.
    - Docker container içindeki unittest AssertionError üretmelidir.
    - Tester en az 1 testin başarısız olduğunu ve AssertionError detayını yakalamalıdır.
    - Reviewer bunu tespit edip CHANGES_REQUESTED vermeli, ASLA APPROVED vermemelidir.
    """
    task_id = f"task_rel_bug_{uuid.uuid4().hex[:6]}"

    with tempfile.TemporaryDirectory(prefix="rel_logic_bug_") as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        # Kasıtlı olarak hatalı çalışan calculator.py
        buggy_code = (
            "def add(a, b):\n"
            "    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):\n"
            "        raise TypeError('Sayilar numeric olmalidir')\n"
            "    return a + b + 1  # KASITLI MANTIK HATASI\n\n"
            "def subtract(a, b):\n"
            "    return a - b\n\n"
            "def multiply(a, b):\n"
            "    return a * b\n\n"
            "def divide(a, b):\n"
            "    if b == 0:\n"
            "        raise ValueError('Sifira bolunemez')\n"
            "    return a / b\n"
        )
        with open(os.path.join(task_ws, "calculator.py"), "w", encoding="utf-8") as f:
            f.write(buggy_code)

        # Otomatik test süitini üret
        test_code = _generate_test_suite_code(task_id, "Hesaplama modulu", ["calculator.py"])
        with open(os.path.join(task_ws, "test_feature.py"), "w", encoding="utf-8") as f:
            f.write(test_code)

        # Gerçek Docker Motoru ile Yürüt
        docker_engine = DockerExecutionEngine()
        tester_res = _execute_tester_in_workspace(
            task_id=task_id,
            description="Hesaplama modulu",
            workspaces_root=temp_root,
            engine=docker_engine
        )

        # 1. Tester Sonuçları Doğrulaması
        assert tester_res.status == "failed"
        assert tester_res.isolation_type == "docker"
        assert tester_res.failed >= 1
        assert any(t.status == "failed" for t in tester_res.test_results)

        # AssertionError yakalandı mı?
        failed_tests = [t for t in tester_res.test_results if t.status == "failed"]
        assert any("AssertionError" in (t.error or "") for t in failed_tests)

        # 2. Reviewer Değerlendirmesi
        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/calculator.py", f"workspaces/{task_id}/test_feature.py"]
        }
        reviewer_res = _execute_reviewer_in_workspace(
            task_id=task_id,
            description="Hesaplama modulu",
            coder_data=coder_data,
            tester_data=tester_res.model_dump(),
            workspaces_root=temp_root
        )

        assert reviewer_res.verdict == ReviewerVerdict.CHANGES_REQUESTED
        assert reviewer_res.verdict != ReviewerVerdict.APPROVED
        assert any(f.category == "testing" for f in reviewer_res.findings)


# =====================================================================
# SENARYO 3: Tester Başarısızlığı Durumunda Görevin Onaylanmaması
# =====================================================================

def test_reliability_03_tester_failure_blocks_approval():
    """
    Senaryo 3: Tester test başarısızlığı raporladığında Reviewer asla APPROVED veremez.
    """
    task_id = "task_rel_tester_fail"

    with tempfile.TemporaryDirectory(prefix="rel_test_fail_") as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        with open(os.path.join(task_ws, "calculator.py"), "w", encoding="utf-8") as f:
            f.write("def add(a: int, b: int) -> int:\n    '''Toplama fonksiyonu.'''\n    return a + b\n")

        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/calculator.py"]
        }

        # 2 test geçti, 1 test başarısız olan Tester çıktısı
        failed_tester_data = {
            "status": "failed",
            "passed": 2,
            "failed": 1,
            "isolation_type": "docker",
            "summary": "1 test başarısız oldu.",
            "test_results": [
                {"name": "test_01", "status": "passed", "duration_ms": 10.0, "error": None},
                {"name": "test_02", "status": "failed", "duration_ms": 15.0, "error": "AssertionError: 2 != 3"}
            ],
            "error": "1 test başarısız oldu."
        }

        reviewer_res = _execute_reviewer_in_workspace(
            task_id=task_id,
            description="Test fail check",
            coder_data=coder_data,
            tester_data=failed_tester_data,
            workspaces_root=temp_root
        )

        assert reviewer_res.verdict == ReviewerVerdict.CHANGES_REQUESTED
        assert reviewer_res.verdict != ReviewerVerdict.APPROVED
        assert any("Birim Testleri Başarısız Oldu" in f.title for f in reviewer_res.findings)


# =====================================================================
# SENARYO 4: Eksik Çalışma Alanı Dosyası Tespiti
# =====================================================================

def test_reliability_04_missing_workspace_file_detected():
    """
    Senaryo 4: Coder Agent'ın oluşturduğunu beyan ettiği bir dosya diskte mevcut değilse
    Reviewer bunu HIGH seviye bulgu olarak tespit etmeli ve CHANGES_REQUESTED vermelidir.
    """
    task_id = "task_rel_missing_file"

    with tempfile.TemporaryDirectory(prefix="rel_missing_") as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        # Sadece calculator.py oluşturulmuş olsun, README.md diskte OLMASIN
        with open(os.path.join(task_ws, "calculator.py"), "w", encoding="utf-8") as f:
            f.write("def add(a: int, b: int) -> int:\n    '''Toplama.'''\n    return a + b\n")

        coder_data = {
            "status": "coded",
            "created_files": [
                f"workspaces/{task_id}/calculator.py",
                f"workspaces/{task_id}/README.md"  # Disk üzerinde YOK
            ]
        }

        tester_data = {
            "status": "tested",
            "passed": 1,
            "failed": 0,
            "isolation_type": "docker",
            "test_results": [{"name": "test_01", "status": "passed", "duration_ms": 5.0, "error": None}],
            "summary": "1 test geçti.",
            "error": None
        }

        reviewer_res = _execute_reviewer_in_workspace(
            task_id=task_id,
            description="Missing file test",
            coder_data=coder_data,
            tester_data=tester_data,
            workspaces_root=temp_root
        )

        assert reviewer_res.verdict == ReviewerVerdict.CHANGES_REQUESTED
        assert reviewer_res.verdict != ReviewerVerdict.APPROVED
        assert any("Beklenen Dosya Eksik: README.md" in f.title for f in reviewer_res.findings)


# =====================================================================
# SENARYO 5: SyntaxError / Runner Çökmesi (Canlı Docker Sandbox)
# =====================================================================

@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker sandbox hazır değil; canlı test atlandı.")
def test_reliability_05_syntax_error_runner_live_docker():
    """
    Senaryo 5: Kaynak kodda sözdizimi hatası (SyntaxError) olduğunda:
    - Docker içindeki 'python -m unittest' exit_code != 0 ile çöker.
    - Tester bunu 'Execution Error' olarak yakalar.
    - Reviewer bunu sözdizimi / execution hatası olarak işaretler ve BLOCKED/CHANGES_REQUESTED verir.
    """
    task_id = f"task_rel_syntax_{uuid.uuid4().hex[:6]}"

    with tempfile.TemporaryDirectory(prefix="rel_syntax_") as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        # Bozuk sözdizimli Python dosyası
        bad_syntax_code = "def broken_func(:\n    return 42\n"
        with open(os.path.join(task_ws, "calculator.py"), "w", encoding="utf-8") as f:
            f.write(bad_syntax_code)

        with open(os.path.join(task_ws, "test_feature.py"), "w", encoding="utf-8") as f:
            f.write("import unittest\nfrom calculator import broken_func\nclass T(unittest.TestCase):\n    def test_1(self): pass\n")

        docker_engine = DockerExecutionEngine()
        tester_res = _execute_tester_in_workspace(
            task_id=task_id,
            description="Syntax error check",
            workspaces_root=temp_root,
            engine=docker_engine
        )

        # AST kontrolü veya runner çökmesi yakalanmalı
        assert tester_res.status in ["failed", "blocked"]
        assert tester_res.passed == 0

        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/calculator.py"]
        }
        reviewer_res = _execute_reviewer_in_workspace(
            task_id=task_id,
            description="Syntax error check",
            coder_data=coder_data,
            tester_data=tester_res.model_dump(),
            workspaces_root=temp_root
        )

        assert reviewer_res.verdict in [ReviewerVerdict.BLOCKED, ReviewerVerdict.CHANGES_REQUESTED]
        assert reviewer_res.verdict != ReviewerVerdict.APPROVED


# =====================================================================
# SENARYO 6: Docker Kullanılamadığında Güvenli Engelleme (No Host Fallback)
# =====================================================================

def test_reliability_06_docker_unavailable_strict_block(isolated_db, monkeypatch):
    """
    Senaryo 6: Docker daemon erişilemez veya kapalı olduğunda:
    - Motor asla host üzerinde güvensiz kod yürütmez.
    - Görev derhal 'blocked' statüsüne geçer.
    """
    from execution.docker_engine import DockerExecutionEngine

    # Docker'ın kapalı olduğu durumu simüle et
    monkeypatch.setattr(DockerExecutionEngine, "is_available", lambda self: False)
    monkeypatch.setattr(DockerExecutionEngine, "check_availability", lambda self: (False, "Docker daemon çalışmıyor"))
    monkeypatch.setenv("EXECUTION_ENGINE", "docker")

    task_id = f"task_rel_no_docker_{uuid.uuid4().hex[:6]}"
    desc = "Python toplama fonksiyonu"

    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description=desc,
        planner_mode="deterministic"
    ))

    assert result["status"] == TaskStatus.BLOCKED.value
    tester = result.get("tester")
    assert tester is not None
    assert tester["status"] == "blocked"
    assert "Docker" in (tester.get("summary") or "")

    reviewer = result.get("reviewer")
    assert reviewer is not None
    assert reviewer["verdict"] == ReviewerVerdict.BLOCKED.value


# =====================================================================
# SENARYO 7: Reviewer Sıfır Hatalı Onay (Zero False Positive) Matrisi
# =====================================================================

@pytest.mark.parametrize("scenario_name, tester_data, extra_setup, expected_verdict", [
    (
        "1_test_failed",
        {"status": "failed", "passed": 3, "failed": 1, "isolation_type": "docker", "test_results": []},
        lambda ws: None,
        ReviewerVerdict.CHANGES_REQUESTED
    ),
    (
        "zero_tests_passed",
        {"status": "tested", "passed": 0, "failed": 0, "isolation_type": "docker", "test_results": []},
        lambda ws: None,
        ReviewerVerdict.CHANGES_REQUESTED
    ),
    (
        "tester_blocked_security",
        {"status": "blocked", "passed": 0, "failed": 0, "isolation_type": "none", "error": "Security block", "summary": "Docker yok"},
        lambda ws: None,
        ReviewerVerdict.BLOCKED
    ),
    (
        "syntax_error_in_code",
        {"status": "tested", "passed": 1, "failed": 0, "isolation_type": "docker", "test_results": []},
        lambda ws: open(os.path.join(ws, "calculator.py"), "w").write("def bad(:\n"),
        ReviewerVerdict.BLOCKED
    ),
    (
        "unauthorized_symlink",
        {"status": "tested", "passed": 1, "failed": 0, "isolation_type": "docker", "test_results": []},
        lambda ws: os.symlink(os.path.join(ws, "calculator.py"), os.path.join(ws, "link.py")),
        ReviewerVerdict.BLOCKED
    ),
    (
        "non_whitelisted_file",
        {"status": "tested", "passed": 1, "failed": 0, "isolation_type": "docker", "test_results": []},
        lambda ws: open(os.path.join(ws, "hacker_payload.sh"), "w").write("echo hacked"),
        ReviewerVerdict.BLOCKED
    ),
])
def test_reliability_07_reviewer_zero_false_positive_approval_matrix(scenario_name, tester_data, extra_setup, expected_verdict):
    """
    Senaryo 7: Reviewer Gatekeeping Güvencesi:
    Hiçbir hata, güvenlik ihlali, test başarısızlığı veya kural ihlali durumunda
    Reviewer ASLA APPROVED veremez.
    """
    task_id = f"task_matrix_{scenario_name}"

    with tempfile.TemporaryDirectory(prefix="rel_matrix_") as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        # Temel geçerli dosya
        with open(os.path.join(task_ws, "calculator.py"), "w", encoding="utf-8") as f:
            f.write("def add(a: int, b: int) -> int:\n    '''Toplama.'''\n    return a + b\n")

        # Senaryoya özel setup (syntax hatası, symlink vb.)
        try:
            extra_setup(task_ws)
        except OSError:
            # Windows'ta symlink izin gerektirebilir, atla
            if "symlink" in scenario_name:
                pytest.skip("Windows'ta symlink oluşturma yetkisi yok.")

        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/calculator.py"]
        }

        reviewer_res = _execute_reviewer_in_workspace(
            task_id=task_id,
            description="Approval matrix test",
            coder_data=coder_data,
            tester_data=tester_data,
            workspaces_root=temp_root
        )

        assert reviewer_res.verdict == expected_verdict
        assert reviewer_res.verdict != ReviewerVerdict.APPROVED, f"HATA: {scenario_name} senaryosunda Reviewer yanlışlıkla APPROVED verdi!"


# =====================================================================
# SENARYO 8: Retry Sınır Aşımı ve Temiz Sonlanma (Orchestration)
# =====================================================================

def test_reliability_08_retry_exhaustion_terminates_gracefully(isolated_db, monkeypatch):
    """
    Senaryo 8: Sürekli başarısız olan bir görevde:
    - Akış sonsuz döngüye girmeden max_retries sınırında durmalıdır.
    - 'retry_exhausted' olayı kaydedilmelidir.
    - Son durum kontrollü şekilde FAILED veya BLOCKED olmalıdır.
    """
    task_id = f"task_rel_retry_exhaust_{uuid.uuid4().hex[:6]}"

    # Motorun her zaman test hatası vermesini sağla
    class AlwaysFailMockEngine(MockExecutionEngine):
        def execute_sync(self, ws, cmd, config=None):
            raw = (
                "test_01 (__main__.Test.test_01) ... FAIL\n\n"
                "======================================================================\n"
                "FAIL: test_01 (__main__.Test.test_01)\n"
                "----------------------------------------------------------------------\n"
                "Traceback (most recent call last):\n"
                "  File 'test_feature.py', line 5, in test_01\n"
                "AssertionError: 1 != 2\n\n"
                "----------------------------------------------------------------------\n"
                "Ran 1 test in 0.001s\n\nFAILED (failures=1)\n"
            )
            from execution.base import ExecutionResult
            return ExecutionResult(
                status="failed",
                exit_code=1,
                stdout="",
                stderr="FAIL: test_01",
                duration_ms=10.0,
                isolation_type="mock",
                raw_output=raw,
                error="1 test başarısız oldu."
            )

    import execution
    import agent_workflow
    monkeypatch.setattr(execution, "get_execution_engine", lambda preferred=None: AlwaysFailMockEngine())
    monkeypatch.setattr(agent_workflow, "get_execution_engine", lambda preferred=None: AlwaysFailMockEngine())

    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description="FastAPI continuous fail test",
        max_retries=2,
        planner_mode="deterministic"
    ))

    # Sonsuz döngü engellenmeli ve görev tamamlanmalıdır
    assert result is not None
    assert result.get("retry_count", 0) == 2

    # Retry sınırının aşıldığına dair event kaydedilmeli veya akış sonlanmalı
    events = result.get("events", [])
    event_types = [ev.get("type") or ev.get("event_type") for ev in events]
    assert "retry_exhausted" in event_types
    assert result.get("status") in [TaskStatus.REVIEWED.value, TaskStatus.FAILED.value, TaskStatus.BLOCKED.value]
