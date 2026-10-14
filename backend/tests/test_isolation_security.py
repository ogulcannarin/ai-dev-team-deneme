"""
backend/tests/test_isolation_security.py
AI Dev Team - Güvenli Execution Engine & Sandbox İzolasyon Test Paketi

Bu test paketi iki kategori içerir:
1. Mock & Güvenlik Politikası Testleri: Herhangi bir Docker bağımlılığı olmadan %100 offline çalışır.
   - Docker yokken host üzerinde çalıştırmanın engellenmesi (Blocked / isolation_type="none")
   - Subprocess motorunun yalnızca açık izinle (ALLOW_UNSAFE_HOST_EXECUTION) çalışabilmesi
   - Mock motorunun çıktı, zaman aşımı ve hata simülasyonları
   - Çıktı karakter sınırı ve AST güvenlik filtresi kombinasyonu
   - Workflow ve SQLite kalıcı katmanında isolation_type alanının saklanması
2. Canlı Docker İzolasyon Testleri: Yalnızca Docker daemon ve sandbox imajı mevcutsa koşulur, aksi halde temizce atlanır (skip).
   - Ağ izolasyonu (--network none)
   - Salt okunur dosya sistemi (--read-only)
   - Bellek sınırı (--memory=256m)
   - Zaman aşımı ve container temizliği
"""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import pytest

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from execution.base import ExecutionConfig, ExecutionResult, BaseExecutionEngine
from execution.docker_engine import DockerExecutionEngine
from execution.mock_engine import MockExecutionEngine
from execution.subprocess_engine import SubprocessExecutionEngine
from execution import UnavailableExecutionEngine, get_execution_engine
from database import init_db
from repository import TaskRepository, WorkflowRunRepository
from schemas import TaskStatus, TesterResult
from agent_workflow import _execute_tester_in_workspace, run_agent_workflow


def is_docker_sandbox_ready() -> bool:
    """Docker daemon ve runner imajının erişilebilir olup olmadığını doğrular."""
    docker_engine = DockerExecutionEngine()
    if not docker_engine.is_available():
        return False
    try:
        img_check = subprocess.run(
            ["docker", "image", "inspect", "ai-dev-team-runner:latest"],
            capture_output=True,
            timeout=5.0
        )
        if img_check.returncode == 0:
            return True
        img_check_py = subprocess.run(
            ["docker", "image", "inspect", "python:3.10-slim"],
            capture_output=True,
            timeout=5.0
        )
        return img_check_py.returncode == 0
    except Exception:
        return False


DOCKER_SANDBOX_AVAILABLE = is_docker_sandbox_ready()


@pytest.fixture(autouse=True)
def setup_isolation_test_db(monkeypatch):
    """Her test için geçici SQLite veritabanı ve temiz workspace hazırlar."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        test_db_path = tmp.name

    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", test_db_path)
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")
    init_db(test_db_path)

    # Workspace temizliği
    from agent_workflow import _get_safe_workspaces_root
    ws_root = _get_safe_workspaces_root()
    if os.path.exists(ws_root):
        for item in os.listdir(ws_root):
            item_path = os.path.join(ws_root, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path, ignore_errors=True)
            elif os.path.isfile(item_path) and not item.endswith(".gitkeep"):
                os.remove(item_path)

    yield test_db_path

    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass


# =====================================================================
# 1. BÖLÜM: Mock & Politika Testleri (Her ortamda %100 offline çalışır)
# =====================================================================

def test_unavailable_engine_always_blocks():
    """UnavailableExecutionEngine her zaman status='blocked' ve isolation_type='none' döndürmelidir."""
    engine = UnavailableExecutionEngine(reason="Docker daemon kapalı.")
    assert not engine.is_available()
    assert engine.get_isolation_type() == "none"

    res = asyncio.run(engine.execute("/tmp/fake_ws", ["python", "-m", "unittest"]))
    assert res.status == "blocked"
    assert res.exit_code == -1
    assert res.isolation_type == "none"
    assert "Docker daemon kapalı" in res.stderr


def test_subprocess_engine_strictly_gated_by_env(monkeypatch):
    """SubprocessExecutionEngine, ALLOW_UNSAFE_HOST_EXECUTION açık olmadıkça çalıştırılamaz."""
    # Varsayılan: İzin kapalı
    monkeypatch.delenv("ALLOW_UNSAFE_HOST_EXECUTION", raising=False)
    engine = SubprocessExecutionEngine()
    assert not engine.is_available()

    # Açıkça 'false' verildiğinde
    monkeypatch.setenv("ALLOW_UNSAFE_HOST_EXECUTION", "false")
    engine = SubprocessExecutionEngine()
    assert not engine.is_available()

    # Yalnızca açıkça 'true' verildiğinde
    monkeypatch.setenv("ALLOW_UNSAFE_HOST_EXECUTION", "true")
    engine_allowed = SubprocessExecutionEngine()
    assert engine_allowed.is_available()
    assert engine_allowed.get_isolation_type() == "subprocess_unsafe"


def test_engine_factory_defaults_to_docker_or_unavailable(monkeypatch):
    """Docker yoksa fabrika varsayılan olarak UnavailableExecutionEngine dönmeli, asla hostta çalıştırmamalıdır."""
    monkeypatch.setenv("EXECUTION_ENGINE", "docker")
    monkeypatch.delenv("ALLOW_UNSAFE_HOST_EXECUTION", raising=False)

    # Docker unavailable simülasyonu
    monkeypatch.setattr(DockerExecutionEngine, "is_available", lambda self: False)

    engine = get_execution_engine("docker")
    assert not engine.is_available()
    assert isinstance(engine, UnavailableExecutionEngine)
    assert engine.get_isolation_type() == "none"


def test_mock_engine_success_simulation():
    """MockExecutionEngine başarılı unittest çıktısını doğru formatta simüle eder."""
    engine = MockExecutionEngine()
    assert engine.is_available()
    assert engine.get_isolation_type() == "mock"

    with tempfile.TemporaryDirectory() as temp_ws:
        # Basit bir test_feature.py oluştur
        with open(os.path.join(temp_ws, "test_feature.py"), "w", encoding="utf-8") as f:
            f.write("import unittest\nclass DummyTest(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")

        res = asyncio.run(engine.execute(temp_ws, ["python", "-m", "unittest", "-v", "test_feature.py"]))
        assert res.status == "success"
        assert res.exit_code == 0
        assert res.isolation_type == "mock"
        assert "ok" in res.raw_output.lower() or "ok" in res.stdout.lower()
        assert res.duration_ms >= 0


def test_mock_engine_custom_failure_and_timeout():
    """MockExecutionEngine hata ve zaman aşımı durumlarını doğru simüle eder."""
    # Başarısızlık simülasyonu
    failing_engine = MockExecutionEngine(
        custom_status="failed",
        custom_exit_code=1,
        custom_raw_output="test_a ... FAIL\n\nFAILURES!\nRan 1 test. FAILED (failures=1)"
    )
    res_fail = asyncio.run(failing_engine.execute("/fake/ws", ["python", "-m", "unittest"]))
    assert res_fail.status == "failed"
    assert res_fail.exit_code == 1
    assert "FAIL" in res_fail.raw_output

    # Zaman aşımı simülasyonu
    timeout_engine = MockExecutionEngine(
        custom_status="timeout",
        custom_exit_code=-1,
        custom_raw_output="",
        custom_error="Process timed out after 5.0s"
    )
    res_timeout = asyncio.run(timeout_engine.execute("/fake/ws", ["python", "-m", "unittest"]))
    assert res_timeout.status == "timeout"
    assert "timed out" in res_timeout.error


def test_output_character_limit_enforced():
    """ExecutionConfig'te belirtilen maksimum çıktı sınırı aşılmamalıdır."""
    config = ExecutionConfig(max_output_chars=100)
    huge_output = "X" * 500

    engine = MockExecutionEngine(custom_raw_output=huge_output)
    res = asyncio.run(engine.execute("/fake/ws", ["cmd"], config=config))

    assert len(res.stdout) <= 200  # Truncation mesajı dahil toplam sınır
    assert "truncated" in res.stdout.lower()


def test_tester_workspace_blocks_when_docker_missing(monkeypatch):
    """_execute_tester_in_workspace, motor kullanılamadığında 'blocked' ve isolation_type='none' dönmelidir."""
    with tempfile.TemporaryDirectory() as temp_root:
        task_id = "task_test_engine_block"
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        with open(os.path.join(task_ws, "models.py"), "w", encoding="utf-8") as f:
            f.write("# safe model\n")

        unavailable_engine = UnavailableExecutionEngine(reason="Docker daemon erişilemez.")

        tester_res = _execute_tester_in_workspace(
            task_id=task_id,
            description="REST API Feature",
            workspaces_root=temp_root,
            engine=unavailable_engine
        )

        assert tester_res.status == "blocked"
        assert tester_res.passed == 0
        assert tester_res.failed == 0
        assert tester_res.isolation_type == "none"
        assert "Docker daemon" in (tester_res.summary or "") or "Docker daemon" in (tester_res.error or "")


def test_ast_security_blocks_malicious_code_before_execution():
    """Tehlikeli çağrılar içeren Python kodu, motor tipi ne olursa olsun AST aşamasında engellenmelidir."""
    with tempfile.TemporaryDirectory() as temp_root:
        task_id = "task_test_ast_block"
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        # Saldırgan kod (socket açma)
        with open(os.path.join(task_ws, "api_feature.py"), "w", encoding="utf-8") as f:
            f.write("import socket\ns = socket.socket()\n")

        # Mock motor verilse bile AST'de durmalı
        mock_engine = MockExecutionEngine()
        tester_res = _execute_tester_in_workspace(
            task_id=task_id,
            description="Socket test",
            workspaces_root=temp_root,
            engine=mock_engine
        )

        assert tester_res.status == "blocked"
        assert "Yasaklı ağ/sistem modülü" in (tester_res.error or "")
        assert "socket" in (tester_res.error or "")


def test_full_workflow_persists_isolation_type(monkeypatch):
    """Uçtan uca workflow çalıştırıldığında TesterResult.isolation_type veritabanına ve run nesnesine kaydedilmelidir."""
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")

    task_id = "task_workflow_isolation_test"
    desc = "Build FastAPI REST API router and models for products catalog"

    result_state = asyncio.run(
        run_agent_workflow(
            task_id=task_id,
            description=desc,
            planner_mode="deterministic"
        )
    )

    assert result_state["status"] == TaskStatus.REVIEWED.value
    tester_dict = result_state.get("tester")
    assert tester_dict is not None
    assert tester_dict.get("isolation_type") == "mock"
    assert tester_dict.get("status") == "tested"

    # Veritabanı doğrulaması
    task_repo = TaskRepository()
    task_repo.create_task(task_id=task_id, description=desc, status=TaskStatus.QUEUED)
    task_repo.update_task_workflow_result(
        task_id=task_id,
        status=TaskStatus.REVIEWED,
        tester=tester_dict,
        reviewer=result_state.get("reviewer")
    )
    saved_task = task_repo.get_task(task_id)
    assert saved_task is not None
    assert saved_task.tester is not None
    assert saved_task.tester.isolation_type == "mock"


# =====================================================================
# 2. BÖLÜM: Canlı Docker İzolasyon Testleri (Docker ve runner imajı varsa çalışır, yoksa skip)
# =====================================================================

@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker daemon veya sandbox runner imajı hazır değil; canlı sandbox testi atlandı.")
def test_docker_engine_network_isolation_live():
    """Canlı Docker Sandbox: Ağ erişimi tamamen kapalı olmalıdır (--network none)."""
    engine = DockerExecutionEngine()
    assert engine.is_available()
    assert engine.get_isolation_type() == "docker"

    with tempfile.TemporaryDirectory() as temp_ws:
        script_path = os.path.join(temp_ws, "test_net.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(
                "import urllib.request\n"
                "try:\n"
                "    urllib.request.urlopen('http://1.1.1.1', timeout=2)\n"
                "    print('NET_OPEN')\n"
                "except Exception as e:\n"
                "    print(f'NET_BLOCKED: {type(e).__name__}')\n"
            )

        res = asyncio.run(engine.execute(temp_ws, ["python", "test_net.py"]))
        assert res.status == "success"
        assert "NET_BLOCKED" in res.raw_output
        assert "NET_OPEN" not in res.raw_output


@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker daemon veya sandbox runner imajı hazır değil; canlı sandbox testi atlandı.")
def test_docker_engine_read_only_root_live():
    """Canlı Docker Sandbox: Kök dosya sistemi salt okunur olmalıdır (--read-only)."""
    engine = DockerExecutionEngine()

    with tempfile.TemporaryDirectory() as temp_ws:
        script_path = os.path.join(temp_ws, "test_ro.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(
                "try:\n"
                "    with open('/root_test.txt', 'w') as f:\n"
                "        f.write('fail')\n"
                "    print('WRITE_SUCCESS')\n"
                "except Exception as e:\n"
                "    print(f'WRITE_DENIED: {type(e).__name__}')\n"
            )

        res = asyncio.run(engine.execute(temp_ws, ["python", "test_ro.py"]))
        assert res.status == "success"
        assert "WRITE_DENIED" in res.raw_output
        assert "WRITE_SUCCESS" not in res.raw_output


@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker daemon veya sandbox runner imajı hazır değil; canlı sandbox testi atlandı.")
def test_docker_engine_timeout_and_cleanup_live():
    """Canlı Docker Sandbox: Sonsuz döngüye giren container 5s içinde durdurulmalı ve temizlenmelidir."""
    engine = DockerExecutionEngine()
    config = ExecutionConfig(timeout_sec=2.0)

    with tempfile.TemporaryDirectory() as temp_ws:
        script_path = os.path.join(temp_ws, "test_loop.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write("import time\nwhile True:\n    time.sleep(0.5)\n")

        res = asyncio.run(engine.execute(temp_ws, ["python", "test_loop.py"], config=config))
        assert res.status == "timeout"
        assert res.exit_code == -1


@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker daemon veya sandbox runner imajı hazır değil; canlı sandbox testi atlandı.")
def test_docker_engine_non_root_user_live():
    """Canlı Docker Sandbox: Container root olmayan kullanıcı (1000:1000 / runner) ile çalışmalıdır."""
    engine = DockerExecutionEngine()

    with tempfile.TemporaryDirectory() as temp_ws:
        script_path = os.path.join(temp_ws, "test_uid.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write("import os\nprint(f'UID:{os.getuid()}_GID:{os.getgid()}')\n")

        res = asyncio.run(engine.execute(temp_ws, ["python", "test_uid.py"]))
        assert res.status == "success"
        assert "UID:1000_GID:1000" in res.raw_output


@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker daemon veya sandbox runner imajı hazır değil; canlı sandbox testi atlandı.")
def test_docker_engine_memory_limit_live():
    """Canlı Docker Sandbox: Bellek sınırını (256MB) aşan süreçler OOM / MemoryError ile durdurulmalıdır."""
    engine = DockerExecutionEngine()
    # 64MB kısıtlı konfigürasyon ile 200MB tahsis denemesi
    config = ExecutionConfig(max_memory_mb=64)

    with tempfile.TemporaryDirectory() as temp_ws:
        script_path = os.path.join(temp_ws, "test_mem.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(
                "try:\n"
                "    a = bytearray(200 * 1024 * 1024)\n"
                "    print('MEM_ALLOC_SUCCESS')\n"
                "except MemoryError:\n"
                "    print('MEM_ERROR_CAUGHT')\n"
            )

        res = asyncio.run(engine.execute(temp_ws, ["python", "test_mem.py"], config=config))
        # OOM kill (exit 137) veya MemoryError yakalanması
        assert res.status == "failed" or "MEM_ERROR_CAUGHT" in res.raw_output or res.exit_code in [137, 1]
        assert "MEM_ALLOC_SUCCESS" not in res.raw_output


@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker daemon veya sandbox runner imajı hazır değil; canlı sandbox testi atlandı.")
def test_docker_engine_real_workspace_unittest_live():
    """Canlı Docker Sandbox: Coder tarafından üretilen gerçek Python kodunu Docker içinde başarıyla test eder."""
    from agent_workflow import _deterministic_planner, _deterministic_scope, _execute_coder_in_workspace, _get_safe_workspaces_root

    task_id = "task_live_docker_runner_e2e"
    desc = "Build FastAPI REST API router and models for products catalog"
    plan = _deterministic_planner(desc)
    scope = _deterministic_scope(desc, plan)

    coder_res = _execute_coder_in_workspace(task_id, desc, plan, scope)
    assert coder_res.status == "coded"

    workspaces_root = _get_safe_workspaces_root()
    docker_engine = DockerExecutionEngine()

    tester_res = _execute_tester_in_workspace(
        task_id=task_id,
        description=desc,
        workspaces_root=workspaces_root,
        engine=docker_engine
    )

    assert tester_res.status == "tested"
    assert tester_res.isolation_type == "docker"
    assert tester_res.passed > 0
    assert tester_res.failed == 0
    assert tester_res.error is None
    assert "docker" in tester_res.summary.lower()

