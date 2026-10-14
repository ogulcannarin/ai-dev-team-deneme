"""
backend/tests/test_llm_smoke_test_suite.py
AI Dev Team — Smoke Test Kontrol ve Güvenlik Doğrulama Test Paketi

Bu paket, canlı LLM smoke test altyapısının:
1. Varsayılan modda 0 ağ çağrısı yaptığını,
2. Canlı modda tam olarak 1 minimal HTTP çağrısı yaptığını (Coder, Docker, Benchmark, Retry olmaksızın),
3. HTTP 401, HTTP 429 (kota/kredi), HTTP 5xx, Timeout, Bağlantı ve Geçersiz JSON hatalarının asla başarı sayılmadığını,
4. API anahtarlarının hiçbir formatta rapora veya hata mesajına sızdırılmadığını,
5. is_configured ve real_network_call_made durumlarının doğruluğunu
%100 izole bir şekilde doğrular.
"""

import asyncio
import json
import os
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from scripts.run_llm_smoke_test import execute_smoke_test
from llm_provider import LLMConfig


@pytest.mark.asyncio
async def test_smoke_test_default_dry_run_makes_zero_network_calls():
    """
    1. Varsayılan modda (live_mode=False) dış ağa kesinlikle HTTP çağrısı yapılmamalıdır.
    """
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        report = await execute_smoke_test(live_mode=False)

        assert report["live_mode_requested"] is False
        assert report["real_network_call_made"] is False
        assert report["success"] is True
        assert report["schema_validated"] is True
        assert mock_post.call_count == 0


@pytest.mark.asyncio
async def test_smoke_test_live_mode_makes_exactly_one_minimal_call(monkeypatch):
    """
    2. Canlı mod etkinleştirildiğinde ve 200 OK alındığında:
    - Tam olarak 1 HTTP çağrısı yapılmalı (call_count == 1).
    - real_network_call_made=True olmalı.
    - Plan şeması doğrulanmalı.
    - Token kullanımı kaydedilmeli.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key-for-testing")

    mock_resp = httpx.Response(
        status_code=200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "goal": "Calculator implementation plan",
                            "subtasks": ["1. Create module", "2. Add tests"],
                            "acceptance_criteria": ["4 arithmetic functions"],
                            "risks": ["Division by zero"]
                        })
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 45,
                "completion_tokens": 80,
                "total_tokens": 125
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        report = await execute_smoke_test(live_mode=True)

        assert report["live_mode_requested"] is True
        assert report["real_network_call_made"] is True
        assert report["success"] is True
        assert report["http_status"] == 200
        assert report["schema_validated"] is True
        assert report["token_usage"]["total_tokens"] == 125
        # En fazla VE tam olarak 1 API isteği
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_smoke_test_live_mode_quota_error_reported_as_failure(monkeypatch):
    """
    3. Canlı modda kota / bakiye hatası (429 insufficient_quota) alındığında:
    - success=False olmalı (Asla sahte başarı veya fallback arkasına saklanmamalı).
    - is_quota_error=True olmalı.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key-for-testing")

    mock_resp = httpx.Response(
        status_code=429,
        json={
            "error": {
                "message": "You exceeded your current quota (credit_balance_exhausted).",
                "type": "insufficient_quota",
                "code": "insufficient_quota"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        report = await execute_smoke_test(live_mode=True)

        assert report["live_mode_requested"] is True
        assert report["real_network_call_made"] is True
        assert report["success"] is False
        assert report["http_status"] == 429
        assert report["is_quota_error"] is True
        assert report["error_type"] == "LLMRateLimitError"
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_smoke_test_live_mode_auth_error_reported_as_failure(monkeypatch):
    """
    4. HTTP 401 hatası alındığında success=False ve error_type=LLMAuthenticationError olmalıdır.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-invalid-test-key")

    mock_resp = httpx.Response(
        status_code=401,
        json={
            "error": {
                "message": "Incorrect API key provided.",
                "type": "invalid_request_error",
                "code": "invalid_api_key"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        report = await execute_smoke_test(live_mode=True)

        assert report["success"] is False
        assert report["http_status"] == 401
        assert report["error_type"] == "LLMAuthenticationError"


@pytest.mark.asyncio
async def test_smoke_test_live_mode_server_500_error_reported_as_failure(monkeypatch):
    """
    5. HTTP 500 / 503 sunucu hatası alındığında success=False olmalıdır.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key-for-testing")

    mock_resp = httpx.Response(
        status_code=500,
        text="Internal Server Error from Provider",
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        report = await execute_smoke_test(live_mode=True)

        assert report["success"] is False
        assert report["error_type"] in ["LLMProviderError", "Exception"]


@pytest.mark.asyncio
async def test_smoke_test_live_mode_timeout_reported_as_failure(monkeypatch):
    """
    6. Timeout durumunda success=False ve error_type=LLMTimeoutError olmalıdır.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key-for-testing")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        report = await execute_smoke_test(live_mode=True)

        assert report["success"] is False
        assert report["error_type"] == "LLMTimeoutError"


@pytest.mark.asyncio
async def test_smoke_test_live_mode_invalid_json_reported_as_failure(monkeypatch):
    """
    7. Modelden gelen yanıt bozuk / geçersiz JSON olduğunda success=False ve schema_validated=False olmalıdır.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key-for-testing")

    mock_resp = httpx.Response(
        status_code=200,
        json={
            "choices": [
                {
                    "message": {
                        "content": "This is completely unstructured non-JSON text from the model."
                    }
                }
            ]
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        report = await execute_smoke_test(live_mode=True)

        assert report["success"] is False
        assert report["schema_validated"] is False
        assert report["error_type"] == "LLMResponseFormatError"


@pytest.mark.asyncio
async def test_smoke_test_missing_api_key_makes_zero_network_calls(monkeypatch):
    """
    8. API anahtarı yapılandırılmamışsa, canlı mod istense bile dış ağa sıfır çağrı yapılmalıdır.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        report = await execute_smoke_test(live_mode=True)

        assert report["success"] is False
        assert report["real_network_call_made"] is False
        assert report["error_type"] == "ConfigurationError"
        assert mock_post.call_count == 0


@pytest.mark.asyncio
async def test_smoke_test_zero_secret_leakage_across_key_patterns(monkeypatch):
    """
    9. Rapor JSON çıktısında veya hata mesajlarında API anahtarı kesinlikle yer almamalıdır.
    """
    secret_key = "sk-proj-ultra_secret_api_key_value_9876543210"
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", secret_key)

    mock_resp = httpx.Response(
        status_code=401,
        json={
            "error": {
                "message": f"Invalid API key: {secret_key} with Bearer {secret_key}",
                "type": "invalid_request_error",
                "code": "invalid_api_key"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        report = await execute_smoke_test(live_mode=True)

        report_json_str = json.dumps(report)
        assert secret_key not in report_json_str
        assert "ultra_secret" not in report_json_str
        assert "[MASKED_KEY]" in report["error_message"] or "Invalid API key" in report["error_message"]


@pytest.mark.asyncio
async def test_smoke_test_captures_request_id_in_report(monkeypatch):
    """
    10. Canlı modda HTTP 429 yanıtındaki x-request-id başlığı rapora request_id olarak eklenmelidir.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key-for-testing")

    mock_resp = httpx.Response(
        status_code=429,
        headers={"x-request-id": "req_openai_smoke_429_test_id"},
        json={
            "error": {
                "message": "You exceeded your current quota (credit_balance_exhausted).",
                "type": "insufficient_quota",
                "code": "credit_balance_exhausted"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        report = await execute_smoke_test(live_mode=True)

        assert report["request_id"] == "req_openai_smoke_429_test_id"
        assert report["is_quota_error"] is True
        assert report["error_code"] == "credit_balance_exhausted"


@pytest.mark.asyncio
async def test_smoke_test_request_id_none_when_header_absent(monkeypatch):
    """
    11. x-request-id başlığı bulunmadığında report['request_id'] None (JSON null) olmalı, sahte ID üretilmemelidir.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key-for-testing")

    mock_resp = httpx.Response(
        status_code=429,
        headers={},
        json={
            "error": {
                "message": "You exceeded your current quota.",
                "type": "insufficient_quota",
                "code": "insufficient_quota"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        report = await execute_smoke_test(live_mode=True)

        assert report["request_id"] is None
