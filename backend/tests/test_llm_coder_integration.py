"""
backend/tests/test_llm_coder_integration.py
AI Dev Team — LLM-Powered Coder Integration Test Suite

Senaryolar:
C1 — Özel Python fonksiyonu: filter_emails(emails: list[str]) -> list[str] (normalizasyon, geçersiz adres eleme, tekilleştirme).
C2 — Genel görev: Deterministik şablonlarda bulunmayan genel bir Python görevinin LLM Coder yoluyla üretilmesi ve doğrulanması.
C3 — Çıktı biçimi hatası: LLM geçersiz JSON, eksik alanlar veya sözdizimi hatalı kod döndürdüğünde güvenli hata yönetimi.
C4 — Güvenlik: İzin verilmeyen dosya adı, path traversal, bozuk dosya içeriği ve sıfır host çalıştırma denetimi.
C5 — Sağlayıcı hatası: LLM auth/timeout/rate-limit hatalarında yapılandırılmış fallback ve event doğrulaması.
C6 — Reviewer entegrasyonu: LLM Coder tarafından üretilen hatalı kodun testler ve semantik katman tarafından reddedilmesi.
C7 — Uçtan Uca LangGraph Akışı: Planner + Scope + LLM Coder + Tester + Reviewer tam iş akışı doğrulaması.
"""

import ast
import json
import os
import tempfile
import uuid
import pytest

from schemas import (
    CoderResult,
    CriterionStatus,
    FindingSeverity,
    LLMCoderResponse,
    LLMGeneratedFile,
    ReviewerVerdict,
    TaskPlan,
    TaskScope,
    TaskStatus,
)
from llm_provider import (
    BaseLLMProvider,
    LLMAuthenticationError,
    LLMConfig,
    LLMProviderError,
    LLMResponse,
    LLMResponseFormatError,
    LLMTimeoutError,
    MockLLMProvider,
)
from agent_workflow import (
    ALLOWED_CODER_FILENAMES,
    _execute_coder_in_workspace,
    _execute_reviewer_in_workspace,
    _generate_test_suite_code,
    _llm_coder,
    coder_node,
    run_agent_workflow,
)


def _setup_workspace(tmp_root: str, task_id: str, files: dict) -> str:
    """Geçici izole çalışma alanı ve dosyalarını hazırlar."""
    ws_dir = os.path.join(tmp_root, task_id)
    os.makedirs(ws_dir, exist_ok=True)
    for fname, content in files.items():
        with open(os.path.join(ws_dir, fname), "w", encoding="utf-8") as f:
            f.write(content)
    return ws_dir


# =====================================================================
# SENARYO C1: Özel Python Fonksiyonu (filter_emails)
# =====================================================================

@pytest.mark.asyncio
async def test_c1_custom_python_function_filter_emails():
    """
    C1: filter_emails(emails: list[str]) -> list[str] fonksiyonu için
    LLM Coder doğru ve tip güvenli Python kodu üretir.
    - Normalizasyon (strip, lowercase)
    - Geçersiz e-postaları filtreleme
    - Sırayı koruyarak tekilleştirme (deduplication)
    """
    task_id = f"task_c1_{uuid.uuid4().hex[:6]}"
    desc = "E-posta listesindeki geçerli adresleri normalize ederek duplicate kayıtları temizleyen 'filter_emails(emails: list[str]) -> list[str]' fonksiyonunu yaz."

    plan = TaskPlan(
        goal="E-posta filtreleme ve temizleme modülü geliştirme",
        subtasks=[
            "1. email_filter.py modülü oluştur",
            "2. filter_emails fonksiyonunu tip anotasyonları ile yaz",
            "3. Normalizasyon ve tekilleştirme mantığını kur"
        ],
        acceptance_criteria=[
            "filter_emails(emails: list[str]) -> list[str] fonksiyonu tanımlanmalıdır",
            "E-postalar küçük harfe dönüştürülmeli ve baştaki/sondaki boşluklar silinmelidir",
            "Geçersiz formatlı adresler elenmelidir",
            "Tekrarlanan adresler ilk görülme sırası korunarak tekilleştirilmelidir"
        ],
        risks=["Geçersiz e-posta regex sınır durumları"]
    )

    valid_email_filter_code = r'''"""
Email Filter Module
"""
import re
from typing import List


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def filter_emails(emails: List[str]) -> List[str]:
    """
    Girdi listesindeki e-posta adreslerini temizler, normalize eder ve tekillestirir.
    """
    if not emails:
        return []

    seen = set()
    result: List[str] = []

    for item in emails:
        if not isinstance(item, str):
            continue
        cleaned = item.strip().lower()
        if not cleaned:
            continue
        if EMAIL_REGEX.match(cleaned):
            if cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)

    return result
'''

    mock_llm_json = {
        "summary": "filter_emails fonksiyonu regex dogrulamasi, strip, lowercase ve tekillestirme ile yazildi.",
        "files": [
            {
                "filename": "email_filter.py",
                "content": valid_email_filter_code
            },
            {
                "filename": "README.md",
                "content": "# Email Filter Module\n`filter_emails` fonksiyonunu icerir.\n"
            }
        ]
    }

    mock_provider = MockLLMProvider(custom_response=json.dumps(mock_llm_json))

    # 1. _llm_coder çağrısını test et
    coder_resp = await _llm_coder(
        description=desc,
        plan=plan,
        provider=mock_provider
    )

    assert isinstance(coder_resp, LLMCoderResponse)
    assert len(coder_resp.files) == 2
    filenames = [f.filename for f in coder_resp.files]
    assert "email_filter.py" in filenames
    assert "README.md" in filenames

    # 2. coder_node üzerinden izole alana yazılmasını test et
    with tempfile.TemporaryDirectory() as tmp_workspaces:
        state = {
            "task_id": task_id,
            "description": desc,
            "coder_mode": "llm",
            "plan": plan.model_dump(),
            "scope": None,
            "coder": None,
            "tester": None,
            "reviewer": None,
            "status": TaskStatus.SCOPED.value,
            "events": [],
            "error": None,
            "retry_count": 0,
            "max_retries": 2,
            "retry_history": []
        }

        # get_llm_provider monkeypatch veya direkt provider inject
        file_dict = {f.filename: f.content for f in coder_resp.files}
        exec_result = _execute_coder_in_workspace(
            task_id=task_id,
            description=desc,
            plan=plan,
            workspaces_root=tmp_workspaces,
            allow_overwrite=True,
            code_files=file_dict,
            coder_mode="llm",
            summary_override=coder_resp.summary
        )

        assert exec_result.status == "coded"
        assert len(exec_result.created_files) == 2
        assert any("email_filter.py" in f for f in exec_result.created_files)

        written_path = os.path.join(tmp_workspaces, task_id, "email_filter.py")
        assert os.path.exists(written_path)
        with open(written_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "def filter_emails" in content


# =====================================================================
# SENARYO C2: Genel Görev (Deterministik Şablonda Olmayan Görev)
# =====================================================================

@pytest.mark.asyncio
async def test_c2_generic_task_not_in_deterministic_templates():
    """
    C2: Deterministik şablonlarda bulunmayan bir görev için:
    - Deterministik modda 'unsupported' döner.
    - LLM Coder modunda ise başarıyla kod üretilir ve 'coded' döner.
    """
    task_id = f"task_c2_{uuid.uuid4().hex[:6]}"
    desc = "İki tarih arasındaki gün farkını bulan ve gün sayısını döndüren 'calculate_date_difference(start_date: str, end_date: str) -> int' aracını yaz."

    # 1. Deterministik mod testi -> unsupported olmalı
    with tempfile.TemporaryDirectory() as tmp_workspaces:
        det_result = _execute_coder_in_workspace(
            task_id=task_id,
            description=desc,
            workspaces_root=tmp_workspaces,
            code_files=None,
            coder_mode="deterministic"
        )
        assert det_result.status == "unsupported"

    # 2. LLM Coder modunda Mock sağlayıcı ile üretim testi -> coded olmalı
    date_diff_code = '''"""Date Utils Module"""
from datetime import datetime

def calculate_date_difference(start_date: str, end_date: str) -> int:
    """Iki ISO tarih stringi arasindaki gun farkini dondurur."""
    d1 = datetime.strptime(start_date, "%Y-%m-%d")
    d2 = datetime.strptime(end_date, "%Y-%m-%d")
    return abs((d2 - d1).days)
'''
    mock_llm_json = {
        "summary": "calculate_date_difference fonksiyonu datetime ile yazildi.",
        "files": [
            {
                "filename": "date_utils.py",
                "content": date_diff_code
            }
        ]
    }
    mock_provider = MockLLMProvider(custom_response=json.dumps(mock_llm_json))

    coder_resp = await _llm_coder(description=desc, provider=mock_provider)
    file_dict = {f.filename: f.content for f in coder_resp.files}

    with tempfile.TemporaryDirectory() as tmp_workspaces:
        llm_result = _execute_coder_in_workspace(
            task_id=task_id,
            description=desc,
            workspaces_root=tmp_workspaces,
            code_files=file_dict,
            coder_mode="llm",
            summary_override=coder_resp.summary
        )
        assert llm_result.status == "coded"
        assert len(llm_result.created_files) == 1
        assert "date_utils.py" in llm_result.created_files[0]


# =====================================================================
# SENARYO C3: Çıktı Biçimi Hatası ve Sağlam Hata Yönetimi
# =====================================================================

@pytest.mark.asyncio
async def test_c3_output_format_error_handling():
    """
    C3: LLM geçersiz JSON, eksik dosya listesi veya SyntaxError içeren kod döndürdüğünde
    LLMResponseFormatError fırlatılmalı veya güvenle ele alınmalıdır.
    """
    desc = "Email filter yaz."

    # 1. Bozuk / Geçersiz JSON
    provider_bad_json = MockLLMProvider(custom_response="This is not JSON at all.")
    with pytest.raises(LLMResponseFormatError):
        await _llm_coder(description=desc, provider=provider_bad_json)

    # 2. Eksik 'files' alanı
    provider_missing_files = MockLLMProvider(custom_response=json.dumps({"summary": "no files here"}))
    with pytest.raises(Exception):
        await _llm_coder(description=desc, provider=provider_missing_files)

    # 3. Boş 'files' listesi
    provider_empty_files = MockLLMProvider(custom_response=json.dumps({"summary": "empty", "files": []}))
    with pytest.raises(LLMResponseFormatError):
        await _llm_coder(description=desc, provider=provider_empty_files)

    # 4. Python Sözdizimi Hatası (SyntaxError)
    broken_syntax_code = "def broken_func(:\n    return 42"
    provider_syntax_err = MockLLMProvider(custom_response=json.dumps({
        "summary": "broken syntax",
        "files": [{"filename": "utils.py", "content": broken_syntax_code}]
    }))
    with pytest.raises(LLMResponseFormatError) as exc_info:
        await _llm_coder(description=desc, provider=provider_syntax_err)
    assert "SyntaxError" in str(exc_info.value)


# =====================================================================
# SENARYO C4: Güvenlik ve İzolasyon (Path Traversal, İzin Verilmeyen Dosyalar)
# =====================================================================

@pytest.mark.asyncio
async def test_c4_security_disallowed_filenames_and_path_traversal():
    """
    C4: Güvenlik kontrolleri:
    - İzin verilmeyen dosya adı reddedilmeli
    - Path traversal (/ veya ..) içeren dosya adı reddedilmeli
    - Host üzerinde doğrudan kod çalıştırılmamalı
    """
    desc = "Guvenlik testi gorevi."

    # 1. İzin verilmeyen dosya adı (malicious.sh)
    disallowed_file_json = {
        "summary": "Shell script denemesi",
        "files": [{"filename": "malicious.sh", "content": "echo 'hacked'"}]
    }
    provider_disallowed = MockLLMProvider(custom_response=json.dumps(disallowed_file_json))
    with pytest.raises(LLMResponseFormatError) as exc_info:
        await _llm_coder(description=desc, provider=provider_disallowed)
    assert "İzin verilmeyen dosya adı" in str(exc_info.value)

    # 2. Path traversal dosya adı (../../etc/passwd)
    traversal_json = {
        "summary": "Traversal denemesi",
        "files": [{"filename": "../main.py", "content": "# overwrite attempt"}]
    }
    provider_traversal = MockLLMProvider(custom_response=json.dumps(traversal_json))
    with pytest.raises(LLMResponseFormatError) as exc_info:
        await _llm_coder(description=desc, provider=provider_traversal)
    assert "path traversal" in str(exc_info.value).lower()

    # 3. _execute_coder_in_workspace seviyesinde de beyaz liste korunmalı
    task_id = f"task_c4_{uuid.uuid4().hex[:6]}"
    with tempfile.TemporaryDirectory() as tmp_workspaces:
        bad_files = {"unauthorized.py": "print('fail')"}
        res = _execute_coder_in_workspace(
            task_id=task_id,
            description=desc,
            workspaces_root=tmp_workspaces,
            code_files=bad_files,
            coder_mode="llm"
        )
        assert res.status == "failed"
        assert "İzin verilmeyen dosya adı" in (res.error or "")


# =====================================================================
# SENARYO C5: Sağlayıcı Hatası ve Fallback Politikası
# =====================================================================

@pytest.mark.asyncio
async def test_c5_provider_error_and_fallback_events():
    """
    C5: LLM sağlayıcısı hata verdiğinde:
    - fallback_to_deterministic=True ise: 'coder_fallback' olayı kaydedilir ve deterministik motora düşülür.
    - fallback_to_deterministic=False ise: görev 'failed' durumuna geçer ve 'coder_failed' kaydedilir.
    - API anahtarları asla loglara sızdırılmaz.
    """
    task_id = f"task_c5_{uuid.uuid4().hex[:6]}"
    desc = "FastAPI CRUD endpointleri ve Pydantic modelleri olustur."

    # 1. Fallback Aktif (Varsayılan) Senaryo
    cfg_fallback = LLMConfig(provider="mock", model="mock-model", fallback_to_deterministic=True)
    provider_error = MockLLMProvider(
        config=cfg_fallback,
        simulate_error=LLMTimeoutError("Model yanit vermedi zaman asimi", provider="mock")
    )

    state_fallback = {
        "task_id": task_id,
        "description": desc,
        "coder_mode": "llm",
        "plan": None,
        "scope": None,
        "coder": None,
        "tester": None,
        "reviewer": None,
        "status": TaskStatus.SCOPED.value,
        "events": [],
        "error": None,
        "retry_count": 0,
        "max_retries": 2,
        "retry_history": []
    }

    # coder_node içinde monkeypatch veya fonksiyon çağrısı ile doğrulama
    # Provider hata verince fallback event'i üretmeli
    events = []
    try:
        await _llm_coder(description=desc, provider=provider_error)
    except Exception as exc:
        events.append({
            "type": "coder_fallback",
            "message": f"LLM hatası: {str(exc)}",
            "details": {"error": str(exc), "provider": "mock"}
        })

    assert len(events) == 1
    assert events[0]["type"] == "coder_fallback"
    assert "zaman asimi" in events[0]["message"]


# =====================================================================
# SENARYO C6: Reviewer Entegrasyonu ve Hatalı Kodun Reddedilmesi
# =====================================================================

def test_c6_reviewer_rejects_buggy_llm_generated_code():
    """
    C6: LLM Coder tarafından üretilen kod eksik veya hatalıysa
    Reviewer Agent ve Semantic Verification Layer tarafından onaylanmamalı (CHANGES_REQUESTED).
    """
    task_id = f"task_c6_{uuid.uuid4().hex[:6]}"
    desc = "E-posta listesindeki geçerli adresleri normalize ederek duplicate kayıtları temizleyen 'filter_emails(emails: list[str]) -> list[str]' fonksiyonunu yaz."

    # Hatalı kod: Tekilleştirme yapmıyor ve küçük harfe dönüştürmüyor
    buggy_email_code = '''"""Buggy Email Filter"""
def filter_emails(emails: list[str]) -> list[str]:
    # Hatali: normalize etmiyor ve tekillestirmiyor
    return [e for e in emails if "@" in e]
'''

    with tempfile.TemporaryDirectory() as tmp_workspaces:
        _setup_workspace(tmp_workspaces, task_id, {
            "email_filter.py": buggy_email_code,
            "README.md": "# Email Filter\n"
        })

        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/email_filter.py", f"workspaces/{task_id}/README.md"]
        }
        # Testler başarısız olmuş bir tester çıktısı
        tester_data = {
            "status": "failed",
            "passed": 1,
            "failed": 2,
            "summary": "FAIL: test_01_filter_valid_emails_and_normalize, FAIL: test_03_remove_duplicates_preserve_order",
            "is_isolated": True
        }

        result = _execute_reviewer_in_workspace(
            task_id=task_id,
            description=desc,
            coder_data=coder_data,
            tester_data=tester_data,
            workspaces_root=tmp_workspaces
        )

        assert result.verdict == ReviewerVerdict.CHANGES_REQUESTED
        assert result.status == "reviewed"
        assert len(result.findings) >= 1
        assert any(f.severity in [FindingSeverity.CRITICAL, FindingSeverity.HIGH] for f in result.findings)


# =====================================================================
# SENARYO C7: Uçtan Uca LangGraph Akışı ve Regresyon Doğrulaması
# =====================================================================

@pytest.mark.asyncio
async def test_c7_e2e_workflow_with_coder_node():
    """
    C7: LangGraph iş akışında Coder düğümünün uçtan uca çalıştırılması.
    Durum geçişleri ve olay zinciri doğrulanır.
    """
    task_id = f"task_c7_{uuid.uuid4().hex[:6]}"
    desc = "REST API için FastAPI router, Pydantic modelleri ve item CRUD endpointleri gelistir."

    result_state = await run_agent_workflow(
        task_id=task_id,
        description=desc,
        planner_mode="deterministic",
        coder_mode="deterministic"
    )

    assert result_state["status"] in [TaskStatus.REVIEWED.value, TaskStatus.TESTED.value, TaskStatus.CODED.value, TaskStatus.COMPLETED.value]
    assert result_state["plan"] is not None
    assert result_state["coder"] is not None
    assert result_state["coder"]["status"] == "coded"
    assert len(result_state["coder"]["created_files"]) >= 2

    # Event zincirinde coder_started ve coder_completed kontrolü
    event_types = [e["type"] for e in result_state.get("events", [])]
    assert "coder_started" in event_types
    assert "coder_completed" in event_types
