"""
backend/tests/test_docker_load_and_paths.py
AI Dev Team - Docker Mount Yolları, Unicode/Boşluk Desteği, Eşzamanlı Yük ve Üretim Güvenlik Testleri
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
import pytest

from execution.base import ExecutionConfig, ExecutionResult
from execution.docker_engine import DockerExecutionEngine
from execution.mock_engine import MockExecutionEngine
from execution.subprocess_engine import SubprocessExecutionEngine
from execution import UnavailableExecutionEngine, get_execution_engine


def _check_live_docker() -> bool:
    """Canlı Docker ortamının ve runner imajının hazır olup olmadığını tespit eder."""
    if not shutil.which("docker"):
        return False
    try:
        res = subprocess.run(
            ["docker", "image", "inspect", "ai-dev-team-runner:latest"],
            capture_output=True,
            timeout=5.0
        )
        return res.returncode == 0
    except Exception:
        return False


DOCKER_SANDBOX_AVAILABLE = _check_live_docker()


# =====================================================================
# 1. BÖLÜM: Docker Mount Yolları, Boşluk ve Unicode Testleri
# =====================================================================

def test_docker_mount_path_formatting():
    """Windows ve Linux yolları Docker mount formatına doğru çevrilmelidir."""
    # Windows formatı
    win_path = r"C:\Users\Developer\Projects\AI Dev Team\workspace_1"
    formatted_win = DockerExecutionEngine.format_docker_mount_path(win_path)
    assert "\\" not in formatted_win
    assert "C:/Users/Developer/Projects/AI Dev Team/workspace_1" in formatted_win

    # Linux formatı
    linux_path = "/home/developer/projects/ai_dev_team/workspace_2"
    formatted_linux = DockerExecutionEngine.format_docker_mount_path(linux_path)
    assert formatted_linux.startswith("/") or ":" in formatted_linux
    assert "workspace_2" in formatted_linux


def test_docker_engine_rejects_non_existent_workspace():
    """Mevcut olmayan çalışma alanı dizininde Docker motoru hata dönmelidir."""
    engine = DockerExecutionEngine()
    fake_path = os.path.join(tempfile.gettempdir(), "non_existent_aidev_dir_xyz_12345")
    if os.path.exists(fake_path):
        shutil.rmtree(fake_path, ignore_errors=True)

    res = engine.execute_sync(fake_path, ["python", "--version"])
    assert res.status in ["error", "blocked"]
    assert res.exit_code == -1
    assert "mevcut değil" in (res.error or "").lower() or "mevcut değil" in (res.stderr or "").lower() or "bulunamadı" in (res.error or "").lower() or "erişilemez" in (res.error or "").lower()


@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker daemon veya sandbox runner imajı hazır değil; canlı sandbox testi atlandı.")
def test_docker_engine_handles_path_with_spaces_live():
    """Canlı Docker Sandbox: Boşluk içeren Windows/Linux çalışma alanı yolunda test çalışabilmelidir."""
    engine = DockerExecutionEngine()
    assert engine.is_available()

    with tempfile.TemporaryDirectory(prefix="aidev ws with spaces ") as space_ws:
        script_path = os.path.join(space_ws, "test_feature.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(
                "import unittest\n"
                "class SpacePathTest(unittest.TestCase):\n"
                "    def test_space_ok(self):\n"
                "        self.assertEqual(1 + 1, 2)\n"
                "if __name__ == '__main__':\n"
                "    unittest.main()\n"
            )

        res = asyncio.run(engine.execute(space_ws, ["python", "-m", "unittest", "-v", "test_feature.py"]))
        assert res.status == "success"
        assert res.exit_code == 0
        assert "ok" in res.raw_output.lower()


@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker daemon veya sandbox runner imajı hazır değil; canlı sandbox testi atlandı.")
def test_docker_engine_handles_unicode_path_live():
    """Canlı Docker Sandbox: Türkçe ve Unicode karakter içeren dizinlerde test çalışabilmelidir."""
    engine = DockerExecutionEngine()
    assert engine.is_available()

    with tempfile.TemporaryDirectory(prefix="aidev_türkçe_dizin_çalışma_") as unicode_ws:
        script_path = os.path.join(unicode_ws, "test_feature.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(
                "import unittest\n"
                "class UnicodePathTest(unittest.TestCase):\n"
                "    def test_unicode_ok(self):\n"
                "        mesaj = 'Başarılı Türkçe İletisi'\n"
                "        self.assertTrue(len(mesaj) > 0)\n"
                "if __name__ == '__main__':\n"
                "    unittest.main()\n"
            )

        res = asyncio.run(engine.execute(unicode_ws, ["python", "-m", "unittest", "-v", "test_feature.py"]))
        assert res.status == "success"
        assert res.exit_code == 0
        assert "ok" in res.raw_output.lower()


# =====================================================================
# 2. BÖLÜM: Eşzamanlı Yük ve İzolasyon Testleri (Mock ve Canlı)
# =====================================================================

def test_mock_concurrent_execution_load():
    """Mock motoruyla 10 eşzamanlı görevin paralel yürütülmesi, sonuçların birbirine karışmaması."""
    engine = MockExecutionEngine(default_config=ExecutionConfig(timeout_sec=15.0))
    task_count = 10

    async def run_single_task(idx: int):
        with tempfile.TemporaryDirectory(prefix=f"task_mock_{idx}_") as ws:
            test_file = os.path.join(ws, "test_feature.py")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(
                    f"import unittest\n"
                    f"class TaskTest{idx}(unittest.TestCase):\n"
                    f"    def test_val(self):\n"
                    f"        self.assertEqual({idx}, {idx})\n"
                )
            return await engine.execute(ws, ["python", "-m", "unittest", "-v", "test_feature.py"])

    async def run_all():
        tasks = [run_single_task(i) for i in range(task_count)]
        return await asyncio.gather(*tasks)

    results = asyncio.run(run_all())
    assert len(results) == task_count
    for r in results:
        assert r.status == "success"
        assert r.exit_code == 0
        assert r.isolation_type == "mock"


@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker daemon veya sandbox runner imajı hazır değil; canlı sandbox testi atlandı.")
def test_docker_concurrent_load_5_tasks_live():
    """
    Canlı Docker Sandbox: 5 farklı görevin aynı anda paralel çalıştırılması.
    - Görevlerden biri kasıtlı olarak timeout olur.
    - Timeout olan görev diğer 4 görevin sonucunu veya container temizliğini etkilememelidir.
    """
    engine = DockerExecutionEngine()
    assert engine.is_available()
    standard_cfg = ExecutionConfig(timeout_sec=15.0)

    async def task_quick_math(ws: str):
        script = os.path.join(ws, "test_feature.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(
                "import unittest\n"
                "class QuickMathTest(unittest.TestCase):\n"
                "    def test_calc(self):\n"
                "        self.assertEqual(sum(range(100)), 4950)\n"
                "if __name__ == '__main__':\n"
                "    unittest.main()\n"
            )
        return await engine.execute(ws, ["python", "-m", "unittest", "-v", "test_feature.py"], config=standard_cfg)

    async def task_sleep_short(ws: str):
        script = os.path.join(ws, "test_feature.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(
                "import unittest, time\n"
                "class SleepTest(unittest.TestCase):\n"
                "    def test_sleep(self):\n"
                "        time.sleep(0.5)\n"
                "        self.assertTrue(True)\n"
                "if __name__ == '__main__':\n"
                "    unittest.main()\n"
            )
        return await engine.execute(ws, ["python", "-m", "unittest", "-v", "test_feature.py"], config=standard_cfg)

    async def task_fastapi_check(ws: str):
        script = os.path.join(ws, "test_feature.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(
                "import unittest, json\n"
                "class JsonDataTest(unittest.TestCase):\n"
                "    def test_json(self):\n"
                "        data = json.loads('{\"name\": \"service\", \"active\": true}')\n"
                "        self.assertEqual(data['name'], 'service')\n"
                "        self.assertTrue(data['active'])\n"
                "if __name__ == '__main__':\n"
                "    unittest.main()\n"
            )
        return await engine.execute(ws, ["python", "-m", "unittest", "-v", "test_feature.py"], config=standard_cfg)

    async def task_intentional_timeout(ws: str):
        # 2.0 saniye timeout ile 8 saniye uyuyan script
        cfg = ExecutionConfig(timeout_sec=2.0)
        script = os.path.join(ws, "test_feature.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(
                "import time\n"
                "time.sleep(8.0)\n"
            )
        return await engine.execute(ws, ["python", "test_feature.py"], config=cfg)

    async def task_pydantic_check(ws: str):
        script = os.path.join(ws, "test_feature.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(
                "import unittest\n"
                "from dataclasses import dataclass\n"
                "@dataclass\n"
                "class User:\n"
                "    name: str\n"
                "class DataclassTest(unittest.TestCase):\n"
                "    def test_user(self):\n"
                "        u = User(name='Alice')\n"
                "        self.assertEqual(u.name, 'Alice')\n"
                "if __name__ == '__main__':\n"
                "    unittest.main()\n"
            )
        return await engine.execute(ws, ["python", "-m", "unittest", "-v", "test_feature.py"], config=standard_cfg)

    async def run_concurrent_suite():
        with tempfile.TemporaryDirectory(prefix="conc_ws_1_") as ws1, \
             tempfile.TemporaryDirectory(prefix="conc_ws_2_") as ws2, \
             tempfile.TemporaryDirectory(prefix="conc_ws_3_") as ws3, \
             tempfile.TemporaryDirectory(prefix="conc_ws_4_") as ws4, \
             tempfile.TemporaryDirectory(prefix="conc_ws_5_") as ws5:

            tasks = [
                task_quick_math(ws1),
                task_sleep_short(ws2),
                task_fastapi_check(ws3),
                task_intentional_timeout(ws4),
                task_pydantic_check(ws5)
            ]
            return await asyncio.gather(*tasks)

    results = asyncio.run(run_concurrent_suite())
    assert len(results) == 5

    res_math, res_sleep, res_fastapi, res_timeout, res_pydantic = results

    # 1, 2, 3, 5 başarılı olmalı
    assert res_math.status == "success"
    assert res_sleep.status == "success"
    assert res_fastapi.status == "success"
    assert res_pydantic.status == "success"

    # 4 zaman aşımına uğramalı fakat diğerlerini bozmamalı
    assert res_timeout.status == "timeout"
    assert "timeout" in (res_timeout.error or "").lower() or "zaman aşımı" in (res_timeout.error or "").lower()


# =====================================================================
# 3. BÖLÜM: Üretim Ortamında Güvensiz Host Yürütme Güvenlik Denetimi
# =====================================================================

def test_production_environment_strictly_rejects_unsafe_host_execution(monkeypatch):
    """Üretim ortamında (APP_ENV=production) ALLOW_UNSAFE_HOST_EXECUTION açık olsa bile reddedilmelidir."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_UNSAFE_HOST_EXECUTION", "true")

    # Subprocess motoru doğrudan reddetmeli
    sub_engine = SubprocessExecutionEngine()
    assert not sub_engine.is_available()

    # Fabrika UnavailableExecutionEngine dönmeli
    engine = get_execution_engine("subprocess_unsafe")
    assert not engine.is_available()
    assert isinstance(engine, UnavailableExecutionEngine)
    assert "üretim ortamında" in engine.reason.lower() or "güvensiz host" in engine.reason.lower()


def test_production_environment_via_environment_var_rejects_unsafe_host(monkeypatch):
    """ENVIRONMENT=prod ayarlandığında da güvensiz host yürütmesi engellenmelidir."""
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("ALLOW_UNSAFE_HOST_EXECUTION", "true")

    sub_engine = SubprocessExecutionEngine()
    assert not sub_engine.is_available()

    engine = get_execution_engine("subprocess_unsafe")
    assert not engine.is_available()
    assert isinstance(engine, UnavailableExecutionEngine)


def test_non_production_development_allows_explicit_unsafe_host(monkeypatch):
    """Geliştirme ortamında (APP_ENV=development) açıkça izin verilmişse SubprocessEngine kullanılabilir."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ALLOW_UNSAFE_HOST_EXECUTION", "true")

    sub_engine = SubprocessExecutionEngine()
    assert sub_engine.is_available()
    assert sub_engine.get_isolation_type() == "subprocess_unsafe"


def test_error_and_blocked_messages_never_leak_sensitive_environment(monkeypatch):
    """Hata veya engelleme mesajlarında hassas ortam değişkenleri (API anahtarları vb.) bulunmamalıdır."""
    secret_key = "sk-super-secret-key-that-must-never-leak-12345"
    monkeypatch.setenv("OPENAI_API_KEY", secret_key)
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret_key)

    unavailable_engine = UnavailableExecutionEngine(reason="Docker daemon kapalı.")
    res = asyncio.run(unavailable_engine.execute("/tmp/ws", ["python", "run.py"]))

    assert secret_key not in res.raw_output
    assert secret_key not in (res.error or "")
    assert secret_key not in res.stderr
    assert secret_key not in res.stdout


def test_docker_engine_check_availability_live():
    """Canlı Docker ortamında check_availability() teşhis mesajını doğrular."""
    engine = DockerExecutionEngine()
    is_ok, diag = engine.check_availability()
    if is_ok:
        assert "Docker daemon aktif" in diag
        assert "Versiyon:" in diag
        assert engine.is_available() is True


def test_docker_engine_check_availability_when_cli_missing(monkeypatch):
    """Docker CLI bulunamadığında check_availability ayrıntılı ve güvenli teşhis mesajı döndürür."""
    engine = DockerExecutionEngine()
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    monkeypatch.setattr("os.path.isfile", lambda p: False)

    is_ok, diag = engine.check_availability()
    assert is_ok is False
    assert "bulunamadı" in diag
    assert engine.is_available() is False


def test_docker_engine_check_availability_when_daemon_fails(monkeypatch):
    """Docker daemon hata döndürdüğünde check_availability hatayı yakalar ve bildirir."""
    engine = DockerExecutionEngine()
    monkeypatch.setattr("shutil.which", lambda cmd: "C:\\mock\\docker.exe")

    class MockProcess:
        returncode = 1
        stdout = ""
        stderr = "error during connect: This error may indicate that the docker daemon is not running."

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockProcess())

    is_ok, diag = engine.check_availability()
    assert is_ok is False
    assert "Docker daemon yanıt vermiyor" in diag
    assert "exit=1" in diag
    assert "docker daemon is not running" in diag


def _patch_docker_cli(monkeypatch, runner):
    """Sağlık kontrolünü gerçek daemon yerine verilen subprocess davranışına bağlar."""
    monkeypatch.setattr(shutil, "which", lambda cmd: r"C:\mock\docker.exe")
    monkeypatch.setattr(subprocess, "run", runner)
    monkeypatch.setenv("EXECUTION_ENGINE", "docker")
    monkeypatch.delenv("ALLOW_UNSAFE_HOST_EXECUTION", raising=False)


def test_factory_single_successful_probe_selects_docker(monkeypatch):
    """Başarılı sağlık kontrolü tek probda Docker motorunu seçer."""
    calls = {"n": 0}

    def fake_run(*args, **kwargs):
        calls["n"] += 1

        class Proc:
            returncode = 0
            stdout = "29.6.1\n"
            stderr = ""

        return Proc()

    _patch_docker_cli(monkeypatch, fake_run)
    engine = get_execution_engine("docker")

    assert calls["n"] == 1
    assert isinstance(engine, DockerExecutionEngine)
    assert engine.last_availability == (True, "Docker daemon aktif (Versiyon: 29.6.1)")
    assert engine.get_isolation_type() == "docker"


def test_factory_cli_error_is_recorded_once_and_blocks_host_execution(monkeypatch):
    """İlk CLI hatası kaydedilir. Sonraki prob başarılı olsa bile unavailable seçilmez."""
    calls = {"n": 0}

    def fake_run(*args, **kwargs):
        calls["n"] += 1

        class Proc:
            pass

        proc = Proc()
        if calls["n"] == 1:
            proc.returncode = 1
            proc.stdout = ""
            proc.stderr = "error during connect: This error may indicate that the docker daemon is not running."
        else:
            proc.returncode = 0
            proc.stdout = "29.6.1\n"
            proc.stderr = ""
        return proc

    _patch_docker_cli(monkeypatch, fake_run)
    engine = get_execution_engine("docker")

    assert calls["n"] == 1
    assert isinstance(engine, UnavailableExecutionEngine)
    assert engine.is_available() is False
    assert engine.get_isolation_type() == "none"
    assert "exit=1" in engine.reason
    assert "docker daemon is not running" in engine.reason
    assert "29.6.1" not in engine.reason
    assert "Docker daemon aktif" not in engine.reason

    blocked = engine.execute_sync(r"C:\unused", ["python", "-m", "unittest"])
    assert blocked.status == "blocked"
    assert blocked.isolation_type == "none"
    assert calls["n"] == 1


def test_factory_timeout_records_exception_type_without_second_probe(monkeypatch):
    """Zaman aşımı exception türüyle kaydedilir ve ikinci sağlık kontrolü yapılmaz."""
    calls = {"n": 0}

    def fake_run(*args, **kwargs):
        calls["n"] += 1
        raise subprocess.TimeoutExpired(cmd="docker", timeout=10.0)

    _patch_docker_cli(monkeypatch, fake_run)
    engine = get_execution_engine("docker")

    assert calls["n"] == 1
    assert isinstance(engine, UnavailableExecutionEngine)
    assert "10.0s zaman aşımı" in engine.reason
    assert "exception=TimeoutExpired" in engine.reason
    assert engine.get_isolation_type() == "none"


def test_availability_failure_redacts_secrets(monkeypatch, caplog):
    """Teşhis ve log, stderr içindeki token benzeri değerleri taşımaz."""
    def fake_run(*args, **kwargs):
        class Proc:
            returncode = 1
            stdout = ""
            stderr = "error during connect token=ghp_thisisnotarealtoken"

        return Proc()

    _patch_docker_cli(monkeypatch, fake_run)
    with caplog.at_level("WARNING"):
        engine = get_execution_engine("docker")

    assert isinstance(engine, UnavailableExecutionEngine)
    assert "ghp_" not in engine.reason
    assert "[redacted]" in engine.reason
    assert "exit=1" in engine.reason
    assert "ghp_" not in caplog.text


# =====================================================================
# 6. BÖLÜM: Docker Regresyon Testleri (İş Akışı ve Güvenlik Bütünlüğü)
# =====================================================================

@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker sandbox hazır değil; canlı regresyon testi atlandı.")
def test_workflow_regression_docker_available_uses_docker_engine(monkeypatch):
    """
    Regresyon Testi 1: Docker kullanılabilir olduğunda gerçek görev akışı
    Docker motorunu kullanmalı ve isolation_type='docker' olarak başarıyla tamamlanmalıdır.
    """
    from agent_workflow import run_agent_workflow
    from database import init_db
    from schemas import TaskStatus

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", db_path)
    monkeypatch.setenv("EXECUTION_ENGINE", "docker")
    init_db(db_path)

    try:
        task_id = "task_regression_docker_ok"
        desc = "Build FastAPI REST API endpoints and models for product catalog"

        result = asyncio.run(
            run_agent_workflow(
                task_id=task_id,
                description=desc,
                planner_mode="deterministic"
            )
        )

        assert result["status"] == TaskStatus.REVIEWED.value
        assert result.get("tester") is not None
        assert result["tester"]["isolation_type"] == "docker"
        assert result["tester"]["status"] == "tested"
        assert result["tester"]["passed"] > 0
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_workflow_regression_docker_unavailable_blocks_workflow(monkeypatch):
    """
    Regresyon Testi 2: Docker kullanılamadığında (daemon kapalı/CLI yok),
    görev 'blocked' kalmalı ve host üzerinde asla kod çalıştırılmamalıdır.
    """
    from agent_workflow import run_agent_workflow
    from database import init_db
    from schemas import TaskStatus

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", db_path)
    monkeypatch.setenv("EXECUTION_ENGINE", "docker")
    monkeypatch.delenv("ALLOW_UNSAFE_HOST_EXECUTION", raising=False)
    # Docker unavailable simülasyonu. Karar sağlık kontrolünün kendisinden gelir.
    monkeypatch.setattr(
        DockerExecutionEngine,
        "check_availability",
        lambda self: (False, "Docker daemon çalışmıyor"),
    )
    init_db(db_path)

    try:
        task_id = "task_regression_docker_blocked"
        desc = "Build a simple user authentication service"

        result = asyncio.run(
            run_agent_workflow(
                task_id=task_id,
                description=desc,
                planner_mode="deterministic"
            )
        )

        # Tester engellenmeli ve workflow blocked/rejected olmalı
        assert result["status"] == TaskStatus.BLOCKED.value
        assert result.get("tester") is not None
        assert result["tester"]["status"] == "blocked"
        assert result["tester"]["isolation_type"] == "none"
        assert "Docker" in (result["tester"].get("error") or "")
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker sandbox hazır değil; canlı regresyon testi atlandı.")
def test_workflow_regression_calculator_task_live_docker(monkeypatch):
    """
    Regresyon Testi 3: Kullanıcının girdiği Türkçe hesaplama modülü ve toplama fonksiyonu görevi
    Coder tarafından başarıyla kodlanmalı, Tester Docker sandbox içinde 4 testi de geçirmeli
    ve Reviewer tarafından approved edilerek reviewed durumuna ulaşmalıdır.
    """
    from agent_workflow import run_agent_workflow
    from database import init_db
    from schemas import TaskStatus

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", db_path)
    monkeypatch.setenv("EXECUTION_ENGINE", "docker")
    init_db(db_path)

    try:
        task_id = "task_calc_live_docker"
        desc = "Python ile çalışan basit bir hesaplama modülü oluştur. İki sayıyı toplayan bir fonksiyon yaz ve fonksiyonun doğru çalıştığını doğrulayan pytest testleri ekle."

        result = asyncio.run(
            run_agent_workflow(
                task_id=task_id,
                description=desc,
                planner_mode="deterministic"
            )
        )

        assert result["status"] == TaskStatus.REVIEWED.value
        assert result.get("coder") is not None
        assert result["coder"]["status"] == "coded"
        assert "calculator.py" in [os.path.basename(f) for f in result["coder"]["created_files"]]

        assert result.get("tester") is not None
        assert result["tester"]["status"] == "tested"
        assert result["tester"]["isolation_type"] == "docker"
        assert result["tester"]["passed"] >= 4
        assert result["tester"]["failed"] == 0
        
        # Test metot isimlerinin docstring ilk kelimesi ('Iki') yerine gercek isim ('test_01_...') oldugunu dogrula
        test_names = [t["name"] for t in result["tester"]["test_results"]]
        assert any(n.startswith("test_01") for n in test_names), f"Gerçek test ismi bulunamadı: {test_names}"
        assert "Iki" not in test_names, f"Hatalı docstring ismi ayrıştırıldı: {test_names}"

        assert result.get("reviewer") is not None
        assert result["reviewer"]["status"] == "reviewed"
        assert result["reviewer"]["verdict"] == "approved"
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


def test_unittest_parser_various_formats():
    """
    _parse_unittest_output fonksiyonunun:
    1. Docstring içeren çok satırlı Python 3.11/3.13 çıktılarını,
    2. Docstring içermeyen tek satırlı çıktıları,
    3. FAIL ve ERROR durumlarında traceback hata detaylarını yakalamasını,
    4. Boş veya geçersiz çıktıları doğru yönetmesini test eder.
    """
    from agent_workflow import _parse_unittest_output

    sample_output = """test_01_no_docstring (test_pkg.TestSample.test_01_no_docstring) ... ok
test_02_with_docstring (test_pkg.TestSample.test_02_with_docstring)
Iki sayinin toplami dogrulanir. ... ok
test_03_failing (test_pkg.TestSample.test_03_failing)
Basarisiz toplama senaryosu. ... FAIL
test_04_error (test_pkg.TestSample.test_04_error)
Sifira bolme hatasi beklenir. ... ERROR

======================================================================
FAIL: test_03_failing (test_pkg.TestSample.test_03_failing)
Basarisiz toplama senaryosu.
----------------------------------------------------------------------
Traceback (most recent call last):
  File "test_feature.py", line 25, in test_03_failing
    self.assertEqual(add(2, 2), 5)
AssertionError: 4 != 5

======================================================================
ERROR: test_04_error (test_pkg.TestSample.test_04_error)
Sifira bolme hatasi beklenir.
----------------------------------------------------------------------
Traceback (most recent call last):
  File "test_feature.py", line 30, in test_04_error
    raise ZeroDivisionError("division by zero")
ZeroDivisionError: division by zero

----------------------------------------------------------------------
Ran 4 tests in 0.005s

FAILED (failures=1, errors=1)
"""

    cases, passed, failed = _parse_unittest_output(sample_output, 100.0)

    assert passed == 2
    assert failed == 2
    assert len(cases) == 4

    # Test isimleri kontrolü (Docstring değil gerçek metot isimleri)
    assert cases[0].name == "test_01_no_docstring"
    assert cases[0].status == "passed"
    assert cases[0].error is None

    assert cases[1].name == "test_02_with_docstring"
    assert cases[1].status == "passed"
    assert cases[1].error is None

    assert cases[2].name == "test_03_failing"
    assert cases[2].status == "failed"
    assert "AssertionError: 4 != 5" in cases[2].error

    assert cases[3].name == "test_04_error"
    assert cases[3].status == "failed"
    assert "ZeroDivisionError: division by zero" in cases[3].error

    # Boş ve beklenmeyen çıktı testleri
    empty_cases, empty_p, empty_f = _parse_unittest_output("", 0.0)
    assert empty_cases == []
    assert empty_p == 0
    assert empty_f == 0

    garbled_cases, g_p, g_f = _parse_unittest_output("SyntaxError: invalid syntax on line 1", 10.0)
    assert garbled_cases == []
    assert g_p == 0
    assert g_f == 0


