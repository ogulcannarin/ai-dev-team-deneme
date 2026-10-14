"""
backend/tests/test_gemini_provider.py
AI Dev Team — Google Gemini LLM Sağlayıcısı Kapsamlı Test Paketi

Bu test paketi, harici API çağrısı yapmaksızın (mock HTTP yanıtları ile):
1. LLM_PROVIDER=gemini seçildiğinde GeminiProvider'ın doğru şekilde oluşturulması ve varsayılan modelin gemini-3.8-flash olması
2. Ortam değişkenlerinin (GEMINI_API_KEY vs OPENAI_API_KEY) bağımsızlığı ve birbirini zorunlu tutmaması
3. API anahtarı eksik olduğunda anlaşılır LLMAuthenticationError üretilmesi
4. Gemini 3.8 Flash için generationConfig uyumluluğu (thinkingConfig kullanımı, temperature parametresinin gönderilmemesi)
5. Gemini 3.x modellerinde thought (düşünce) parçalarının filtrelenip sadece nihai cevabın alınması
6. Başarılı Gemini REST API yanıtının LLMResponse şemasına dönüştürülmesi (token, latency, request_id)
7. Gemini JSON yanıtının Pydantic TaskPlan şeması ile doğrulanması
8. 401 / 403 Yetkilendirme hatalarının güvenle ele alınması ve API anahtarının asla sızdırılmaması
9. 429 RESOURCE_EXHAUSTED (Kota / Bakiye Yetersizliği) durumunun is_quota_error=True olarak yakalanması
10. 429 Geçici İstek Sıklığı (Rate Limit) ve Retry-After başlığı tespiti
11. 5xx Sağlayıcı sunucu hatalarının ele alınması
12. Zaman aşımı (Timeout) durumunda LLMTimeoutError fırlatılması
13. Güvenlik politikası (SAFETY) ve bozuk JSON durumlarının yönetimi
14. run_llm_smoke_test.py betiğinin Gemini ile dry-run, mock ve --model override uyumluluğu
15. OpenAI sağlayıcısının geriye dönük tam uyumluluğunun korunması
durumlarını doğrular.
"""

import asyncio
import json
import os
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from llm_provider import (
    BaseLLMProvider,
    LLMConfig,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMProviderError,
    LLMResponseFormatError,
    GeminiProvider,
    OpenAICompatibleProvider,
    MockLLMProvider,
    get_llm_provider,
    extract_json_from_llm_text,
)
from schemas import TaskPlan
from scripts.run_llm_smoke_test import execute_smoke_test


# =====================================================================
# 1. Sağlayıcı Seçimi ve Yapılandırma Doğrulamaları
# =====================================================================

def test_gemini_provider_selection_from_factory(monkeypatch):
    """LLM_PROVIDER=gemini seçildiğinde GeminiProvider örneği döndürüldüğünü ve varsayılanın gemini-3.8-flash olduğunu doğrular."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.test_mock_gemini_key_12345")
    monkeypatch.delenv("LLM_MODEL", raising=False)

    provider = get_llm_provider()
    assert isinstance(provider, GeminiProvider)
    assert provider.config.provider == "gemini"
    assert provider.config.model == "gemini-3.8-flash"
    assert "generativelanguage.googleapis.com" in provider.config.base_url
    assert provider.is_configured() is True


def test_gemini_custom_model_configuration(monkeypatch):
    """LLM_MODEL ortam değişkeni ile Gemini modelinin özelleştirilebildiğini doğrular."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.test_mock_gemini_key_12345")
    monkeypatch.setenv("LLM_MODEL", "gemini-1.5-flash")

    provider = get_llm_provider()
    assert isinstance(provider, GeminiProvider)
    assert provider.config.model == "gemini-1.5-flash"


def test_gemini_env_independence(monkeypatch):
    """
    Ortam değişkenlerinin yanlış sağlayıcı tarafından zorunlu tutulmadığını doğrular:
    - Gemini seçildiğinde OPENAI_API_KEY gerekmez.
    - OpenAI seçildiğinde GEMINI_API_KEY gerekmez.
    """
    # 1. Gemini modu: OPENAI_API_KEY yokken is_configured True olmalı
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.test_gemini_key_abcde")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    cfg_gemini = LLMConfig.from_env()
    assert cfg_gemini.provider == "gemini"
    assert cfg_gemini.is_configured() is True

    # 2. OpenAI modu: GEMINI_API_KEY yokken is_configured True olmalı
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test-openai-key-12345")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    cfg_openai = LLMConfig.from_env()
    assert cfg_openai.provider == "openai"
    assert cfg_openai.is_configured() is True


def test_gemini_missing_api_key_raises_auth_error():
    """Gemini API anahtarı eksik olduğunda açık ve anlaşılır LLMAuthenticationError verildiğini test eder."""
    cfg = LLMConfig(provider="gemini", api_key=None)
    provider = GeminiProvider(cfg)
    assert provider.is_configured() is False

    with pytest.raises(LLMAuthenticationError) as exc_info:
        asyncio.run(provider.generate("Merhaba dünya"))

    err = exc_info.value
    assert err.provider == "gemini"
    assert "GEMINI_API_KEY" in err.message


def test_gemini_safe_metadata_zero_secret_leak():
    """safe_metadata() sözlüğünün API anahtarı içermediğini ve güvenli ana sunucu adını verdiğini doğrular."""
    secret = "AQ.SuperSecretGeminiKey123456789"
    cfg = LLMConfig(
        provider="gemini",
        api_key=secret,
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-3.8-flash"
    )
    meta = cfg.safe_metadata()

    assert meta["provider"] == "gemini"
    assert meta["model"] == "gemini-3.8-flash"
    assert meta["base_host"] == "generativelanguage.googleapis.com"
    assert meta["is_configured"] is True
    assert secret not in json.dumps(meta)


# =====================================================================
# 2. Gemini 3.8 Flash Parametre Uyumluluğu (thinkingConfig & thought parts)
# =====================================================================

@pytest.mark.asyncio
async def test_gemini_3_8_flash_thinking_config_and_parameters():
    """
    Gemini 3.8 Flash için:
    - Geleneksel temperature parametresi gönderilmemeli (Google 3.x API gereksinimi).
    - thinkingConfig: {"thinkingLevel": "low"} eklenmeli.
    - maxOutputTokens ve candidateCount parametreleri taşınmalı.
    """
    cfg = LLMConfig(
        provider="gemini",
        api_key="AQ.mock_valid_key_12345",
        model="gemini-3.8-flash",
        max_tokens=4096
    )
    provider = GeminiProvider(cfg)

    mock_resp = httpx.Response(
        status_code=200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Gemini 3.8 Flash yanıtı"}],
                        "role": "model"
                    },
                    "finishReason": "STOP"
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 20,
                "totalTokenCount": 30
            },
            "modelVersion": "gemini-3.8-flash"
        },
        headers={"x-goog-request-id": "req_3_8_abc"},
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        res = await provider.generate("Test prompt")

        assert res.content == "Gemini 3.8 Flash yanıtı"
        assert res.model == "gemini-3.8-flash"

        call_payload = mock_post.call_args.kwargs["json"]
        gen_cfg = call_payload["generationConfig"]

        # Gemini 3.x kuralları:
        assert "temperature" not in gen_cfg
        assert "thinkingConfig" in gen_cfg
        assert gen_cfg["thinkingConfig"]["thinkingLevel"] == "low"
        assert gen_cfg["maxOutputTokens"] == 4096
        assert gen_cfg["candidateCount"] == 1


@pytest.mark.asyncio
async def test_gemini_3_thought_parts_filtering():
    """
    Gemini 3.x modellerinde thought=True olan düşünce adımlarının filtrelenip
    yalnızca asıl metin/JSON çıktısının LLMResponse'a aktarıldığını doğrular.
    """
    cfg = LLMConfig(provider="gemini", api_key="AQ.mock_valid_key_12345", model="gemini-3.8-flash")
    provider = GeminiProvider(cfg)

    mock_resp = httpx.Response(
        status_code=200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "Bu bir iç akıl yürütme adımıdır ve nihai yanıta dahil edilmemelidir."},
                            {"thought": False, "text": '{"result": "success", "data": 42}'}
                        ],
                        "role": "model"
                    },
                    "finishReason": "STOP"
                }
            ],
            "usageMetadata": {"totalTokenCount": 45}
        },
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        res = await provider.generate("JSON üret")

        # Sadece thought=False olan asıl çıktı alınmalı
        assert res.content == '{"result": "success", "data": 42}'
        assert "iç akıl yürütme" not in res.content


# =====================================================================
# 3. Başarılı Yanıt Dönüştürme ve Şema Uyumu
# =====================================================================

@pytest.mark.asyncio
async def test_gemini_successful_response_mapping():
    """
    Başarılı Google Gemini v1beta REST yanıtının standart LLMResponse modeline dönüştüğünü test eder.
    """
    cfg = LLMConfig(
        provider="gemini",
        api_key="AQ.mock_valid_key_12345",
        model="gemini-3.8-flash"
    )
    provider = GeminiProvider(cfg)

    mock_gemini_body = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Python ile hesap makinesi modülü başarıyla üretildi."}],
                    "role": "model"
                },
                "finishReason": "STOP",
                "index": 0
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 25,
            "candidatesTokenCount": 60,
            "totalTokenCount": 85
        },
        "modelVersion": "gemini-3.8-flash"
    }

    mock_resp = httpx.Response(
        status_code=200,
        json=mock_gemini_body,
        headers={"x-goog-request-id": "req_goog_gemini_998877"},
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        res = await provider.generate(prompt="Hesap makinesi yaz", system_prompt="Sen bir yazılım mimarısın.")

        assert res.content == "Python ile hesap makinesi modülü başarıyla üretildi."
        assert res.provider == "gemini"
        assert res.model == "gemini-3.8-flash"
        assert res.prompt_tokens == 25
        assert res.completion_tokens == 60
        assert res.total_tokens == 85
        assert res.request_id == "req_goog_gemini_998877"
        assert res.latency_ms > 0

        # İsteğin doğru başlıklar ve JSON şemasıyla gönderildiğini doğrula
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["headers"]["x-goog-api-key"] == "AQ.mock_valid_key_12345"
        payload = call_kwargs["json"]
        assert "contents" in payload
        assert payload["contents"][0]["parts"][0]["text"] == "Hesap makinesi yaz"
        assert payload["systemInstruction"]["parts"][0]["text"] == "Sen bir yazılım mimarısın."


@pytest.mark.asyncio
async def test_gemini_json_mode_and_task_plan_validation():
    """
    Gemini JSON plan çıktısının Pydantic TaskPlan şeması ile eksiksiz doğrulandığını test eder.
    """
    cfg = LLMConfig(provider="gemini", api_key="AQ.mock_valid_key_12345", model="gemini-3.8-flash")
    provider = GeminiProvider(cfg)

    plan_json = {
        "goal": "FastAPI tabanlı güvenli kimlik doğrulama servisi",
        "subtasks": [
            "1. JWT token üretim ve doğrulama modülü",
            "2. Şifre hashleme ve kullanıcı doğrulama servisi",
            "3. Otomatik birim testlerinin yazılması"
        ],
        "acceptance_criteria": [
            "Geçersiz token 401 döndürmelidir",
            "Tüm testler geçmelidir"
        ],
        "risks": [
            "Token süresi aşımı durumunda refresh mekanizması gereksinimi"
        ]
    }

    mock_gemini_body = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": json.dumps(plan_json)}],
                    "role": "model"
                },
                "finishReason": "STOP"
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 40,
            "candidatesTokenCount": 110,
            "totalTokenCount": 150
        }
    }

    mock_resp = httpx.Response(
        status_code=200,
        json=mock_gemini_body,
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        parsed_dict = await provider.generate_json(
            prompt="JSON formatında plan üret.",
            system_prompt="You are an Autonomous Software Architect."
        )

        plan = TaskPlan(**parsed_dict)
        assert plan.goal == "FastAPI tabanlı güvenli kimlik doğrulama servisi"
        assert len(plan.subtasks) == 3
        assert len(plan.acceptance_criteria) == 2

        # İstek JSON modunun devrede olduğunu doğrula
        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["generationConfig"]["responseMimeType"] == "application/json"


# =====================================================================
# 4. Güvenli Hata Yönetimi ve Sıfır Sızıntı Testleri
# =====================================================================

@pytest.mark.asyncio
async def test_gemini_401_403_authentication_failure_masks_key():
    """
    403 PERMISSION_DENIED / 401 yanıtında:
    - LLMAuthenticationError fırlatılmalı
    - Gerçek API anahtarı maskelenmeli, asla hata metninde sızmamalı.
    """
    secret_key = "AQ.RealSecretProductionKey_9876543210"
    cfg = LLMConfig(provider="gemini", api_key=secret_key, model="gemini-3.8-flash")
    provider = GeminiProvider(cfg)

    mock_resp = httpx.Response(
        status_code=403,
        json={
            "error": {
                "code": 403,
                "message": f"API key not valid. Please pass a valid API key: {secret_key}",
                "status": "PERMISSION_DENIED"
            }
        },
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(LLMAuthenticationError) as exc_info:
            await provider.generate("Test prompt")

        err = exc_info.value
        assert err.status_code == 403
        assert err.provider == "gemini"
        # Gizli anahtarın asla hata mesajında yer almadığını doğrula
        assert secret_key not in str(err)
        assert secret_key not in err.message
        assert "[MASKED_KEY]" in str(err)


@pytest.mark.asyncio
async def test_gemini_429_resource_exhausted_quota_error():
    """
    Google Gemini 429 RESOURCE_EXHAUSTED yanıtında:
    - LLMRateLimitError fırlatılmalı
    - is_quota_error=True olarak işaretlenmeli.
    """
    cfg = LLMConfig(provider="gemini", api_key="AQ.mock_quota_test_key", model="gemini-3.8-flash")
    provider = GeminiProvider(cfg)

    mock_resp = httpx.Response(
        status_code=429,
        json={
            "error": {
                "code": 429,
                "message": "Resource has been exhausted (e.g. check quota).",
                "status": "RESOURCE_EXHAUSTED"
            }
        },
        headers={"x-goog-request-id": "req_gemini_quota_123"},
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(LLMRateLimitError) as exc_info:
            await provider.generate("Test prompt")

        err = exc_info.value
        assert err.status_code == 429
        assert err.is_quota_error is True
        assert err.request_id == "req_gemini_quota_123"
        assert "RESOURCE_EXHAUSTED" in err.message or "bakiye veya harcama kotası yetersiz" in err.message.lower()


@pytest.mark.asyncio
async def test_gemini_429_transient_rate_limit_with_retry_after():
    """
    429 Geçici istek sınırı aşıldığında Retry-After başlığının okunduğunu test eder.
    """
    cfg = LLMConfig(provider="gemini", api_key="AQ.mock_transient_test_key", model="gemini-3.8-flash")
    provider = GeminiProvider(cfg)

    mock_resp = httpx.Response(
        status_code=429,
        json={
            "error": {
                "code": 429,
                "message": "Rate limit exceeded for requests per minute.",
                "status": "RESOURCE_EXHAUSTED"
            }
        },
        headers={"retry-after": "20"},
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(LLMRateLimitError) as exc_info:
            await provider.generate("Test prompt")

        err = exc_info.value
        assert err.status_code == 429
        assert err.retry_after == "20"


@pytest.mark.asyncio
async def test_gemini_5xx_server_error():
    """Gemini 500 / 503 yanıtlarında LLMProviderError fırlatıldığını test eder."""
    cfg = LLMConfig(provider="gemini", api_key="AQ.mock_server_test_key", model="gemini-3.8-flash")
    provider = GeminiProvider(cfg)

    mock_resp = httpx.Response(
        status_code=503,
        json={
            "error": {
                "code": 503,
                "message": "The service is temporarily unavailable.",
                "status": "UNAVAILABLE"
            }
        },
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(LLMProviderError) as exc_info:
            await provider.generate("Test prompt")

        err = exc_info.value
        assert err.status_code == 503
        assert "503" in str(err)


@pytest.mark.asyncio
async def test_gemini_timeout_handling():
    """İstek zaman aşımına uğradığında LLMTimeoutError fırlatıldığını test eder."""
    cfg = LLMConfig(provider="gemini", api_key="AQ.mock_timeout_key", model="gemini-3.8-flash", timeout=3.0)
    provider = GeminiProvider(cfg)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Read timeout")

        with pytest.raises(LLMTimeoutError) as exc_info:
            await provider.generate("Test prompt")

        assert "zaman aşımına uğradı" in str(exc_info.value).lower() or "timeout" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_gemini_safety_block_handling():
    """Güvenlik filtresi (finishReason=SAFETY) yanıtında anlaşılır LLMProviderError verildiğini test eder."""
    cfg = LLMConfig(provider="gemini", api_key="AQ.mock_safety_key", model="gemini-3.8-flash")
    provider = GeminiProvider(cfg)

    mock_resp = httpx.Response(
        status_code=200,
        json={
            "candidates": [
                {
                    "content": {"parts": []},
                    "finishReason": "SAFETY"
                }
            ]
        },
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(LLMProviderError) as exc_info:
            await provider.generate("Tehlikeli içerik testi")

        assert "SAFETY" in str(exc_info.value) or "güvenlik politikası" in str(exc_info.value).lower()


# =====================================================================
# 5. Smoke Test Betiği Entegrasyonu (run_llm_smoke_test.py)
# =====================================================================

@pytest.mark.asyncio
async def test_smoke_test_dry_run_with_gemini_configured(monkeypatch):
    """
    run_llm_smoke_test.py varsayılan modda çalıştırıldığında:
    - 0 ağ çağrısı yapılır
    - Mock plan şeması başarıyla doğrulanır
    - Varsayılan modelin gemini-3.8-flash olduğu doğrulanır.
    """
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.mock_smoke_test_key")
    monkeypatch.delenv("LLM_MODEL", raising=False)

    report = await execute_smoke_test(live_mode=False, provider_override="gemini")

    assert report["success"] is True
    assert report["real_network_call_made"] is False
    assert report["schema_validated"] is True
    assert report["provider"] == "gemini"
    assert report["model"] == "gemini-3.8-flash"


@pytest.mark.asyncio
async def test_smoke_test_model_override_parameter(monkeypatch):
    """
    run_llm_smoke_test.py betiğinde --model parametresinin varsayılan modeli
    doğru şekilde geçersiz kıldığını doğrular.
    """
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.mock_smoke_test_key")

    report = await execute_smoke_test(
        live_mode=False,
        provider_override="gemini",
        model_override="custom-gemini-experimental"
    )

    assert report["provider"] == "gemini"
    assert report["model"] == "custom-gemini-experimental"


@pytest.mark.asyncio
async def test_smoke_test_live_fails_cleanly_when_unconfigured(monkeypatch):
    """
    Canlı mod istendiğinde ve API anahtarı yoksa:
    - Ağ çağrısı yapılmaz
    - Net biçimde GEMINI_API_KEY eksikliği bildirilir.
    """
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    report = await execute_smoke_test(live_mode=True, provider_override="gemini")

    assert report["success"] is False
    assert report["real_network_call_made"] is False
    assert report["error_type"] == "ConfigurationError"
    assert "GEMINI_API_KEY" in report["error_message"]


# =====================================================================
# 6. OpenAI Sağlayıcısının Bozulmadığının Doğrulanması
# =====================================================================

def test_openai_provider_remains_intact(monkeypatch):
    """LLM_PROVIDER=openai seçildiğinde OpenAICompatibleProvider'ın sorunsuz çalıştığını doğrular."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test-openai-key-still-valid")
    monkeypatch.delenv("LLM_MODEL", raising=False)

    provider = get_llm_provider()
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.config.provider == "openai"
    assert provider.config.model == "gpt-4o-mini"
    assert provider.is_configured() is True
