"""
backend/tests/test_llm_provider_readiness.py
AI Dev Team — Gerçek LLM Entegrasyonu Öncesi Hazırlık ve Hata Yönetimi Test Paketi

Bu test paketi, gerçek harici API çağrısı yapmaksızın HTTP yanıtlarını mock ederek:
1. 401 Authentication Hatası (Geçersiz API Anahtarı)
2. 429 Rate Limit (Geçici İstek Sıklığı Aşımı & Retry-After)
3. 429 Insufficient Quota (Kalıcı Bakiye / Harcama Kotası Aşımı)
4. 5xx Sağlayıcı Sunucu Hatası (500 / 503 Service Unavailable)
5. Timeout ve Ağ Bağlantı Hataları (httpx.TimeoutException & ConnectError)
6. Bozuk JSON veya Şemaya Uymayan Model Yanıtları (LLMResponseFormatError)
7. Planner ve Coder Modlarının Bağımsızlığı ve Sözleşme Uyumu
8. Başarısız LLM Çağrılarında Asla Sahte APPROVED Verilmemesi
durumlarını doğrular.
"""

import asyncio
import json
import os
import tempfile
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from database import init_db
from llm_provider import (
    BaseLLMProvider,
    LLMConfig,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMProviderError,
    LLMResponseFormatError,
    OpenAICompatibleProvider,
    MockLLMProvider,
    get_llm_provider,
    extract_json_from_llm_text,
)
from schemas import (
    TaskPlan,
    LLMCoderResponse,
    TaskStatus,
    ReviewerVerdict,
)
from agent_workflow import (
    _llm_planner,
    _llm_coder,
    run_agent_workflow,
)


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
# 1. 401 Authentication Hatası (Geçersiz / Eksik API Anahtarı)
# =====================================================================

@pytest.mark.asyncio
async def test_error_401_authentication_failure():
    """
    401 Yanıtında:
    - LLMAuthenticationError fırlatılmalı.
    - Status code 401 olarak kaydedilmeli.
    - Hata mesajı API anahtarını sızdırmamalı.
    """
    cfg = LLMConfig(
        provider="openai",
        api_key="sk-proj-supersecretkey1234567890",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini"
    )
    provider = OpenAICompatibleProvider(cfg)

    mock_resp = httpx.Response(
        status_code=401,
        json={
            "error": {
                "message": "Incorrect API key provided: sk-proj-supersecretkey1234567890.",
                "type": "invalid_request_error",
                "code": "invalid_api_key"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(LLMAuthenticationError) as exc_info:
            await provider.generate("Test prompt")

        err = exc_info.value
        assert err.status_code == 401
        assert err.error_code == "invalid_api_key"
        # API anahtarının maskelendiğini doğrula
        assert "supersecretkey1234567890" not in str(err)
        assert "[MASKED_KEY]" in str(err) or "[MASKED" in str(err)


# =====================================================================
# 2. 429 Rate Limit (Geçici İstek Sıklığı Aşımı)
# =====================================================================

@pytest.mark.asyncio
async def test_error_429_transient_rate_limit():
    """
    429 Rate Limit Yanıtında:
    - LLMRateLimitError fırlatılmalı.
    - is_quota_error=False olarak işaretlenmeli.
    - retry_after süresi doğru okunmalı.
    """
    cfg = LLMConfig(provider="openai", api_key="sk-test-key-12345")
    provider = OpenAICompatibleProvider(cfg)

    mock_resp = httpx.Response(
        status_code=429,
        headers={"retry-after": "12"},
        json={
            "error": {
                "message": "Rate limit reached for requests per min (RPM).",
                "type": "requests",
                "code": "rate_limit_exceeded"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(LLMRateLimitError) as exc_info:
            await provider.generate("Test prompt")

        err = exc_info.value
        assert err.status_code == 429
        assert err.error_code == "rate_limit_exceeded"
        assert err.retry_after == "12"
        assert err.is_quota_error is False


# =====================================================================
# 3. 429 Insufficient Quota (Kalıcı Bakiye / Kota Aşımı)
# =====================================================================

@pytest.mark.asyncio
async def test_error_429_insufficient_quota_non_retryable():
    """
    429 Kota / Bakiye Yetersizliği Yanıtında:
    - is_quota_error=True olarak işaretlenmeli.
    - Açık ve bilgilendirici hata mesajı üretilmeli.
    """
    cfg = LLMConfig(provider="openai", api_key="sk-test-key-12345")
    provider = OpenAICompatibleProvider(cfg)

    mock_resp = httpx.Response(
        status_code=429,
        json={
            "error": {
                "message": "You exceeded your current quota, please check your plan and billing details.",
                "type": "insufficient_quota",
                "code": "insufficient_quota"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(LLMRateLimitError) as exc_info:
            await provider.generate("Test prompt")

        err = exc_info.value
        assert err.status_code == 429
        assert err.is_quota_error is True
        assert "bakiye veya harcama kotası yetersiz" in err.message.lower() or "insufficient_quota" in err.message


# =====================================================================
# 4. 5xx Sağlayıcı Sunucu Hatası (500 / 503 Service Unavailable)
# =====================================================================

@pytest.mark.asyncio
async def test_error_5xx_provider_server_error():
    """
    500 / 503 Sunucu Hatalarında:
    - LLMProviderError fırlatılmalı.
    - Status code doğru taşınmalı.
    """
    cfg = LLMConfig(provider="openai", api_key="sk-test-key-12345")
    provider = OpenAICompatibleProvider(cfg)

    mock_resp = httpx.Response(
        status_code=503,
        json={
            "error": {
                "message": "The engine is currently overloaded, please try again later.",
                "type": "server_error",
                "code": "service_unavailable"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(LLMProviderError) as exc_info:
            await provider.generate("Test prompt")

        err = exc_info.value
        assert err.status_code == 503
        assert "503" in str(err)


# =====================================================================
# 5. Timeout ve Ağ Bağlantı Hataları
# =====================================================================

@pytest.mark.asyncio
async def test_error_timeout_and_network_disconnect():
    """
    Timeout ve Ağ Hatalarında:
    - Timeout durumunda LLMTimeoutError fırlatılmalı.
    - Bağlantı kopmasında LLMProviderError fırlatılmalı.
    """
    cfg = LLMConfig(provider="openai", api_key="sk-test-key-12345", timeout=5.0)
    provider = OpenAICompatibleProvider(cfg)

    # 1. Timeout Testi
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        with pytest.raises(LLMTimeoutError) as exc_info:
            await provider.generate("Test prompt")

        assert "zaman aşımına uğradı" in str(exc_info.value).lower() or "timeout" in str(exc_info.value).lower()

    # 2. Ağ Bağlantı Kopması Testi
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(LLMProviderError) as exc_info:
            await provider.generate("Test prompt")

        assert "bağlantı" in str(exc_info.value).lower() or "connection" in str(exc_info.value).lower()


# =====================================================================
# 6. Bozuk JSON veya Şemaya Uymayan Model Yanıtları
# =====================================================================

@pytest.mark.asyncio
async def test_error_malformed_json_and_schema_validation():
    """
    Bozuk veya Eksik JSON Yanıtlarında:
    - extract_json_from_llm_text LLMResponseFormatError fırlatmalı.
    - Pydantic şema doğrulaması eksik zorunlu alanları yakalamalı.
    """
    # 1. Tamamen Bozuk JSON
    with pytest.raises(LLMResponseFormatError):
        extract_json_from_llm_text("I cannot provide JSON right now.")

    # 2. Eksik Kapanış Parantezi
    with pytest.raises(LLMResponseFormatError):
        extract_json_from_llm_text('{"goal": "Incomplete json')

    # 3. Şemaya Uymayan Plan (Eksik subtasks ve acceptance_criteria)
    corrupt_provider = MockLLMProvider(LLMConfig(provider="mock"))
    with patch.object(corrupt_provider, "generate_json", new_callable=AsyncMock) as mock_json:
        mock_json.return_value = {"goal": "Only goal present"}

        with pytest.raises(Exception):
            await _llm_planner("Test task", corrupt_provider)


# =====================================================================
# 7. Planner ve Coder Model Seçimi Bağımsızlığı & Sözleşme Uyumu
# =====================================================================

@pytest.mark.asyncio
async def test_planner_and_coder_model_selection_independence(isolated_db):
    """
    Planner ve Coder modlarının birbirinden bağımsız seçilebildiği doğrulanır:
    - Planner: LLM (Mock), Coder: Deterministik
    - Her iki motor da kendi güvenli metaverisini taşır.
    """
    task_id = "test_independence_01"
    desc = "Python ile basit hesaplama modülü oluştur."

    result = await run_agent_workflow(
        task_id=task_id,
        description=desc,
        planner_mode="llm",
        coder_mode="deterministic"
    )

    assert result["status"] == TaskStatus.REVIEWED.value
    events = result.get("events", [])

    plan_ev = next((e for e in events if e.get("type") == "planning_started"), None)
    coder_ev = next((e for e in events if e.get("type") == "coder_started"), None)

    assert plan_ev is not None
    assert plan_ev["details"].get("planner_mode") == "llm"

    assert coder_ev is not None
    assert coder_ev["details"].get("coder_mode") == "deterministic"


# =====================================================================
# 8. Başarısız LLM Çağrılarında Asla Sahte APPROVED Verilmemesi
# =====================================================================

@pytest.mark.asyncio
async def test_failed_llm_call_never_produces_fake_approval(isolated_db, monkeypatch):
    """
    LLM çağrısı başarısız olduğunda ve fallback devre dışı bırakıldığında:
    - Görev FAILED durumunda sonlanmalı.
    - Coder / Tester / Reviewer çalıştırılmamalı.
    - Kesinlikle APPROVED sonucu üretilmemeli.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-invalid-key")
    monkeypatch.setenv("LLM_FALLBACK_TO_DETERMINISTIC", "false")

    mock_resp = httpx.Response(
        status_code=401,
        json={"error": {"message": "Invalid API key"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result = await run_agent_workflow(
            task_id="test_failed_no_fake_approval",
            description="Önemli güvenlik modülü",
            planner_mode="llm",
            coder_mode="llm"
        )

        assert result["status"] == TaskStatus.FAILED.value
        assert result.get("coder") is None
        assert result.get("reviewer") is None
        assert "başarısız" in (result.get("error") or "").lower() or "401" in (result.get("error") or "")
