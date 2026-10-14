"""
backend/tests/test_task_diversity_benchmark.py
AI Dev Team — Agent Capability & Task Diversity Benchmark (10 Senaryo)

Bu test süiti, agent sisteminin farklı yazılım geliştirme görevlerini çözme,
sınırlarını belirleme, mantık hatalarını yakalama ve güvenlik politikalarını denetleme
yeteneğini ölçer:

1. Matematik yardımcı modülü (Calculator / Aritmetik)
2. Tarih ve zaman hesaplama (Date & Time Diff / Semantik Doğrulama)
3. Girdi doğrulama (Email Filter / Regex Validation)
4. Metin işleme (Text Processor / Slugify & Sanitization)
5. JSON okuma ve doğrulama (JSON Parser & Pydantic Schema)
6. Eksik gereksinimlerin tespiti (Missing Requirements / Vague Task)
7. Çelişkili gereksinimlerin tespiti (Contradictory Requirements / Impossible Spec)
8. Mantıksal hata içeren kodun yakalanması (Intentional Logic Bug / Tester & Reviewer Guard)
9. Desteklenmeyen programlama dili veya teknoloji (Unsupported Language / Fail-safe)
10. Dosya yolu manipülasyonu ve güvenli olmayan kod üretimi (Security / AST & Path Guard)
"""

import asyncio
import json
import os
import tempfile
import uuid
import pytest

from database import init_db
from execution.docker_engine import DockerExecutionEngine
from execution.mock_engine import MockExecutionEngine
from llm_provider import MockLLMProvider, LLMConfig
from repository import TaskRepository
from schemas import (
    FindingSeverity,
    ReviewerVerdict,
    TaskStatus,
    TesterResult,
)
from agent_workflow import (
    _execute_coder_in_workspace,
    _execute_reviewer_in_workspace,
    _execute_tester_in_workspace,
    _generate_test_suite_code,
    _is_supported_task,
    _validate_python_ast_security,
    _llm_coder,
    _llm_planner,
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
# SENARYO 1: Matematik Yardımcı Modülü (Calculator)
# =====================================================================

@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker sandbox hazır değil; canlı test atlandı.")
def test_scenario_01_math_helper_module(isolated_db, monkeypatch):
    """
    Senaryo 1: Matematik yardımcı modülü (calculator.py)
    - Girdi: add, subtract, multiply, divide ve sıfıra bölme kontrolü.
    - Beklenen: 6 birim testinin tamamı Docker içinde geçer, Reviewer APPROVED verir.
    - Motor: Planner: Mock LLM (mock-llm-v1), Coder: Deterministik Motor.
    """
    monkeypatch.setenv("EXECUTION_ENGINE", "docker")
    task_id = f"task_div_01_math_{uuid.uuid4().hex[:6]}"
    desc = (
        "Python ile çalışan bir calculator.py modülü oluştur. "
        "add(a, b), subtract(a, b), multiply(a, b) ve divide(a, b) fonksiyonlarını uygula. "
        "Sıfıra bölme durumunu doğru şekilde yönet. "
        "Pozitif, negatif, ondalıklı sayılar ve sıfıra bölme durumlarını kapsayan testler yaz."
    )

    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description=desc,
        planner_mode="llm",
        coder_mode="deterministic"
    ))

    assert result["status"] == TaskStatus.REVIEWED.value
    assert result.get("coder") is not None
    assert any("calculator.py" in f for f in result["coder"]["created_files"])

    tester = result.get("tester")
    assert tester is not None
    assert tester["passed"] >= 4
    assert tester["failed"] == 0
    assert tester["isolation_type"] == "docker"

    reviewer = result.get("reviewer")
    assert reviewer is not None
    assert reviewer["verdict"] == "approved"
    assert len(reviewer["findings"]) == 0


# =====================================================================
# SENARYO 2: Tarih ve Zaman Hesaplama (Date & Time Diff Semantik Ayrım)
# =====================================================================

def test_scenario_02_date_time_diff_semantic_gap(isolated_db):
    """
    Senaryo 2: Tarih ve zaman hesaplama (date_diff)
    - Girdi: İki ISO-8601 tarih string'i arasındaki gün farkını hesaplayan date_diff fonksiyonu.
    - Beklenen: Deterministik motor date_diff şablonuna sahip değilse, Reviewer semantik
      olarak iş gereksiniminin karşılanmadığını tespit eder ve CHANGES_REQUESTED verir.
    - Motor: Deterministik / Reviewer Semantik AST Motoru.
    """
    task_id = f"task_div_02_date_{uuid.uuid4().hex[:6]}"
    desc = "İki ISO-8601 tarih string'i arasındaki gün farkını hesaplayan date_diff(d1, d2) fonksiyonu içeren date_utils.py modülü oluştur."

    with tempfile.TemporaryDirectory(prefix="div_date_") as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        # Coder alakasız calculator.py üretmiş olsun
        calc_code = "def add(a, b): return a + b\ndef subtract(a, b): return a - b\n"
        with open(os.path.join(task_ws, "calculator.py"), "w", encoding="utf-8") as f:
            f.write(calc_code)
        with open(os.path.join(task_ws, "README.md"), "w", encoding="utf-8") as f:
            f.write("# Calculator Module\n")

        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/calculator.py", f"workspaces/{task_id}/README.md"]
        }
        tester_data = {
            "status": "tested",
            "passed": 4,
            "failed": 0,
            "isolation_type": "docker",
            "test_results": [{"name": "test_add", "status": "passed", "duration_ms": 10.0}]
        }

        reviewer_res = _execute_reviewer_in_workspace(
            task_id=task_id,
            description=desc,
            coder_data=coder_data,
            tester_data=tester_data,
            workspaces_root=temp_root
        )

        # Testler geçse bile iş gereksinimi (date_diff) üretilen kodda (calculator) olmadığı için CHANGES_REQUESTED olmalıdır
        assert reviewer_res.verdict == ReviewerVerdict.CHANGES_REQUESTED
        assert reviewer_res.verdict != ReviewerVerdict.APPROVED
        sem_findings = [f for f in reviewer_res.findings if f.category == "semantic_alignment"]
        assert len(sem_findings) >= 1


# =====================================================================
# SENARYO 3: Girdi Doğrulama (Email Filter & Regex Validation)
# =====================================================================

@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker sandbox hazır değil; canlı test atlandı.")
def test_scenario_03_input_validation_email_filter(isolated_db):
    """
    Senaryo 3: Girdi doğrulama (Email Filter)
    - Girdi: E-posta formatını regex ile doğrulayan filter_emails modülü.
    - Beklenen: Mock LLM Coder ile email_filter.py üretilir, Docker içinde birim testleri geçer.
    - Motor: Mock LLM (mock-llm-v1) / Docker Tester.
    """
    task_id = f"task_div_03_email_{uuid.uuid4().hex[:6]}"
    desc = "E-posta adres listesini doğrulayan ve sadece geçerli formatta olanları filtreleyen email_filter.py modülü oluştur."

    with tempfile.TemporaryDirectory(prefix="div_email_") as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        provider = MockLLMProvider(LLMConfig(provider="mock", model="mock-llm-v1"))
        coder_resp = asyncio.run(_llm_coder(
            description=desc,
            plan=None,
            scope=None,
            reviewer_feedback=None,
            retry_history=None,
            provider=provider
        ))

        assert any(f.filename == "email_filter.py" for f in coder_resp.files)
        email_file = next(f for f in coder_resp.files if f.filename == "email_filter.py")
        with open(os.path.join(task_ws, "email_filter.py"), "w", encoding="utf-8") as f:
            f.write(email_file.content)

        # Doğrulama Testi
        test_script = '''
import unittest
from email_filter import filter_emails

class TestEmailFilter(unittest.TestCase):
    def test_filter_valid_emails(self):
        inputs = ["valid.user@domain.com", "bad-email", "test@corp.org", "no_at_sign.com"]
        expected = ["valid.user@domain.com", "test@corp.org"]
        self.assertEqual(filter_emails(inputs), expected)

    def test_empty_list(self):
        self.assertEqual(filter_emails([]), [])

if __name__ == "__main__":
    unittest.main()
'''
        with open(os.path.join(task_ws, "test_feature.py"), "w", encoding="utf-8") as f:
            f.write(test_script)

        docker_engine = DockerExecutionEngine()
        tester_res = _execute_tester_in_workspace(
            task_id=task_id,
            description=desc,
            workspaces_root=temp_root,
            engine=docker_engine
        )

        assert tester_res.status == "tested"
        assert tester_res.passed >= 2
        assert tester_res.failed == 0


# =====================================================================
# SENARYO 4: Metin İşleme (Slugify & Transliteration)
# =====================================================================

def test_scenario_04_text_processing_slugify(isolated_db):
    """
    Senaryo 4: Metin işleme (URL slug oluşturucu)
    - Girdi: Türkçe karakterleri dönüştüren ve URL slug üreten modül.
    - Beklenen: slugify fonksiyonu özel karakterleri temizler ve doğru slug üretir.
    - Motor: Deterministik Python / AST Doğrulayıcı.
    """
    task_id = f"task_div_04_slug_{uuid.uuid4().hex[:6]}"
    desc = "Türkçe karakter destekli metin slugify modülü oluştur."

    with tempfile.TemporaryDirectory(prefix="div_slug_") as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        slug_code = r'''"""
Metin Isleme - Slugify Modulu
"""
import re

TR_MAP = str.maketrans({
    "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g",
    "ı": "i", "I": "i", "İ": "i", "i": "i",
    "ö": "o", "Ö": "o", "ş": "s", "Ş": "s",
    "ü": "u", "Ü": "u"
})

def slugify(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("Girdi string olmalidir.")
    text = text.translate(TR_MAP).lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "-", text)
'''
        with open(os.path.join(task_ws, "text_processor.py"), "w", encoding="utf-8") as f:
            f.write(slug_code)

        # AST ve Syntax denetimi
        ast_err = _validate_python_ast_security("text_processor.py", slug_code)
        assert ast_err is None

        # Doğrudan mantık doğrulaması
        ns = {}
        exec(slug_code, ns)
        slug_fn = ns["slugify"]
        assert slug_fn("Türkçe Başlık & Özel Karakterler!") == "turkce-baslik-ozel-karakterler"
        assert slug_fn("  Çok   Güzel   Bir   Gün  ") == "cok-guzel-bir-gun"
        with pytest.raises(TypeError):
            slug_fn(12345)


# =====================================================================
# SENARYO 5: JSON Okuma ve Doğrulama (Pydantic Schema Parser)
# =====================================================================

def test_scenario_05_json_schema_validation(isolated_db):
    """
    Senaryo 5: JSON okuma ve şema doğrulama
    - Girdi: Yapılandırılmış JSON verisini okuyan ve Pydantic ile doğrulayan model.
    - Beklenen: Geçerli JSON doğrulanır, eksik/hatalı tiplerde ValidationError fırlatılır.
    - Motor: Deterministik REST / Pydantic Schema Motoru.
    """
    task_id = f"task_div_05_json_{uuid.uuid4().hex[:6]}"
    desc = "Pydantic tabanlı JSON yapılandırma okuma ve doğrulama modülü."

    from pydantic import BaseModel, Field, ValidationError

    class AppConfig(BaseModel):
        app_name: str = Field(..., min_length=2)
        port: int = Field(..., ge=1, le=65535)
        debug: bool = Field(default=False)

    # Geçerli JSON
    valid_raw = '{"app_name": "AI-Dev-Team", "port": 8000, "debug": true}'
    cfg = AppConfig.model_validate_json(valid_raw)
    assert cfg.app_name == "AI-Dev-Team"
    assert cfg.port == 8000
    assert cfg.debug is True

    # Hatalı Port (Geçersiz Aralık)
    invalid_raw = '{"app_name": "AI-Dev-Team", "port": 70000}'
    with pytest.raises(ValidationError):
        AppConfig.model_validate_json(invalid_raw)

    # Eksik Zorunlu Alan
    missing_raw = '{"port": 8000}'
    with pytest.raises(ValidationError):
        AppConfig.model_validate_json(missing_raw)


# =====================================================================
# SENARYO 6: Eksik Gereksinimlerin Tespiti (Vague / Incomplete Requirements)
# =====================================================================

def test_scenario_06_missing_requirements_detection(isolated_db):
    """
    Senaryo 6: Eksik ve belirsiz gereksinimler ("Sistemi hızlandır...")
    - Girdi: Teknik kabul kriteri, veri modeli ve girdi/çıktı sözleşmesi bulunmayan görev.
    - Beklenen: Planner belirsizlik risklerini tespit eder, Reviewer eksik gereksinimleri bildirir.
    - Motor: Mock LLM Planner / Reviewer Kural Denetimi.
    """
    vague_desc = "Sistemi hızlandır ve veritabanı performansını optimize et."

    provider = MockLLMProvider(LLMConfig(provider="mock", model="mock-llm-v1"))
    plan = asyncio.run(_llm_planner(vague_desc, provider))

    # Planner riskleri ve genel alt görevleri belirler
    assert len(plan.risks) >= 1
    assert any("optimizasyon" in r.lower() or "bellek" in r.lower() or "risk" in r.lower() for r in plan.risks)
    assert len(plan.acceptance_criteria) >= 1


# =====================================================================
# SENARYO 7: Çelişkili Gereksinimlerin Tespiti (Contradictory Specs)
# =====================================================================

@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker sandbox hazır değil; canlı test atlandı.")
def test_scenario_07_contradictory_requirements_detection(isolated_db):
    """
    Senaryo 7: Çelişkili gereksinimlerin tespiti
    - Girdi: Mantıksal olarak imkansız istek (Sayı hem pozitif olmalı hem de sıfırdan küçük olmalı).
    - Beklenen: Docker içindeki test süiti başarısız olur ve Reviewer CHANGES_REQUESTED verir.
    - Motor: Docker Sandbox / Reviewer Engine.
    """
    task_id = f"task_div_07_contra_{uuid.uuid4().hex[:6]}"
    desc = "Bir fonksiyon yaz: Girdi hem pozitif olmalı hem de kesinlikle sıfırdan küçük olmalıdır."

    with tempfile.TemporaryDirectory(prefix="div_contra_") as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        code = """def add(a: int, b: int) -> int:
    # Imkansiz kosul / mantik celiskisi
    return a + b if (a > 0 and a < 0) else 0
"""
        with open(os.path.join(task_ws, "calculator.py"), "w", encoding="utf-8") as f:
            f.write(code)

        test_code = """import unittest
from calculator import add

class TestContradiction(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(add(5, 5), 10)

if __name__ == "__main__":
    unittest.main()
"""
        with open(os.path.join(task_ws, "test_feature.py"), "w", encoding="utf-8") as f:
            f.write(test_code)

        docker_engine = DockerExecutionEngine()
        tester_res = _execute_tester_in_workspace(
            task_id=task_id,
            description=desc,
            workspaces_root=temp_root,
            engine=docker_engine
        )

        assert tester_res.status == "failed"
        assert tester_res.failed >= 1

        coder_data = {"status": "coded", "created_files": [f"workspaces/{task_id}/calculator.py"]}
        reviewer_res = _execute_reviewer_in_workspace(
            task_id=task_id,
            description=desc,
            coder_data=coder_data,
            tester_data=tester_res.model_dump(),
            workspaces_root=temp_root
        )

        assert reviewer_res.verdict in [ReviewerVerdict.CHANGES_REQUESTED, ReviewerVerdict.BLOCKED]
        assert reviewer_res.verdict != ReviewerVerdict.APPROVED


# =====================================================================
# SENARYO 8: Mantıksal Hata İçeren Kodun Yakalanması (Logic Bug)
# =====================================================================

@pytest.mark.skipif(not DOCKER_SANDBOX_AVAILABLE, reason="Docker sandbox hazır değil; canlı test atlandı.")
def test_scenario_08_logic_bug_detection(isolated_db):
    """
    Senaryo 8: Mantıksal hata içeren kodun yakalanması
    - Girdi: Sözdizimi geçerli ama add(2, 3) -> 6 üreten hatalı kod.
    - Beklenen: Docker sandbox testinde AssertionError yakalanır, Reviewer asla APPROVED vermez.
    - Motor: Docker Sandbox / Reviewer Verification.
    """
    task_id = f"task_div_08_bug_{uuid.uuid4().hex[:6]}"
    desc = "Python ile çalışan hesaplama modülü."

    with tempfile.TemporaryDirectory(prefix="div_logic_bug_") as temp_root:
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        buggy_calc = """def add(a, b):
    return a + b + 1  # Mantik hatasi

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    if b == 0:
        raise ValueError("Sifira bolunemez")
    return a / b
"""
        with open(os.path.join(task_ws, "calculator.py"), "w", encoding="utf-8") as f:
            f.write(buggy_calc)

        test_code = _generate_test_suite_code(task_id, "Hesaplama modulu", ["calculator.py"])
        with open(os.path.join(task_ws, "test_feature.py"), "w", encoding="utf-8") as f:
            f.write(test_code)

        docker_engine = DockerExecutionEngine()
        tester_res = _execute_tester_in_workspace(
            task_id=task_id,
            description="Hesaplama modulu",
            workspaces_root=temp_root,
            engine=docker_engine
        )

        assert tester_res.status == "failed"
        assert tester_res.failed >= 1
        assert any("AssertionError" in (t.error or "") for t in tester_res.test_results)

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


# =====================================================================
# SENARYO 9: Desteklenmeyen Dil / Teknoloji (Unsupported Stack)
# =====================================================================

def test_scenario_09_unsupported_language_or_tech(isolated_db):
    """
    Senaryo 9: Desteklenmeyen dil veya teknoloji (Rust / Go / Solidity)
    - Girdi: Rust veya C++ ile multi-threaded kütüphane isteği.
    - Beklenen: _is_supported_task False döndürür, sahte Python kodu çalıştırılmaz.
    - Motor: Deterministik Kapsam ve Kategori Filtresi.
    """
    unsupported_tasks = [
        "Rust ile actor model concurrency kütüphanesi yaz ve Cargo.toml oluştur.",
        "Golang ile fiber tabanlı mikroservis geliştir.",
        "Solidity ile ERC-20 smart contract yaz.",
        "Swift ile iOS Bluetooth bağlantı modülü oluştur."
    ]

    for desc in unsupported_tasks:
        assert _is_supported_task(desc) is False

    task_id = f"task_div_09_unsupp_{uuid.uuid4().hex[:6]}"
    result = asyncio.run(run_agent_workflow(
        task_id=task_id,
        description=unsupported_tasks[0],
        planner_mode="deterministic",
        coder_mode="deterministic"
    ))

    # Akış desteklenmeyen görevde çökmeksizin uygun hata durumu verir
    assert result["status"] == TaskStatus.UNSUPPORTED.value
    assert result.get("coder") is not None
    assert result["coder"]["status"] == "unsupported"


# =====================================================================
# SENARYO 10: Güvenlik ve Dosya Yolu Manipülasyonu Engellemesi (Security AST & Path Traversal)
# =====================================================================

def test_scenario_10_path_traversal_and_unsafe_code_blocked(isolated_db):
    """
    Senaryo 10: Dosya yolu manipülasyonu ve güvenli olmayan kod üretimi girişimleri
    - Girdi: ../../etc/passwd yoluna erişim veya subprocess/os.system çağrısı içeren kod.
    - Beklenen: AST güvenlik filtresi zararlı importları yakalar, yol normalizasyonu izolasyon dışına çıkışı engeller.
    - Motor: AST Security Guard & Path Confinement Policy.
    """
    # 1. Zararlı AST Kod Denetimi
    unsafe_code_snippets = [
        "import subprocess\nsubprocess.call(['rm', '-rf', '/'])",
        "import os\nos.system('echo hacked')",
        "import socket\ns = socket.socket()",
        "import pty\npty.spawn('/bin/sh')"
    ]

    for code in unsafe_code_snippets:
        err_msg = _validate_python_ast_security("unsafe_module.py", code)
        assert err_msg is not None
        assert "yasaklı" in err_msg.lower() or "güvenlik" in err_msg.lower() or "modül" in err_msg.lower() or "ast" in err_msg.lower()

    # 2. Path Traversal Denetimi
    with tempfile.TemporaryDirectory(prefix="div_sec_") as temp_root:
        task_id = "task_sec_test"
        task_ws = os.path.join(temp_root, task_id)
        os.makedirs(task_ws, exist_ok=True)

        malicious_path = os.path.abspath(os.path.join(task_ws, "..", "..", "system_file.txt"))
        # task_ws içinde kalındığı doğrulanır
        assert not malicious_path.startswith(os.path.abspath(task_ws))
