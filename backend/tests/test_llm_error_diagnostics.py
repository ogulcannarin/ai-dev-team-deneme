"""
backend/tests/test_llm_error_diagnostics.py
AI Dev Team — LLM HTTP 429 & Error Diagnostics Unit Test Suite

Verifies:
1. Safe extraction of error.code, error.type, and sanitized error messages from HTTP 429 responses.
2. Differentiation between transient rate limits and permanent quota/spend limits.
3. Handling of Retry-After headers (present vs absent).
4. Non-JSON / malformed error payload resilience.
5. Zero leakage of API keys / Authorization headers in error messages and exception payloads.
6. Structured error detail propagation into workflow events (planner_fallback, coder_fallback).
"""

import json
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from llm_provider import (
    LLMConfig,
    LLMProviderError,
    LLMRateLimitError,
    LLMAuthenticationError,
    OpenAICompatibleProvider,
    _parse_error_details,
)
from agent_workflow import run_agent_workflow


def test_parse_error_details_rate_limit_exceeded():
    """T1: rate_limit_exceeded durumu ve Retry-After başlığı doğru ayrıştırılmalı."""
    mock_response = httpx.Response(
        status_code=429,
        headers={"retry-after": "15"},
        json={
            "error": {
                "message": "Rate limit reached for requests",
                "type": "requests",
                "code": "rate_limit_exceeded"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    details = _parse_error_details(mock_response)
    assert details["error_code"] == "rate_limit_exceeded"
    assert details["error_type"] == "requests"
    assert details["retry_after"] == "15"
    assert details["is_quota_error"] is False
    assert "Rate limit reached" in details["safe_message"]


def test_parse_error_details_insufficient_quota():
    """T2: insufficient_quota hatası is_quota_error=True olarak işaretlenmeli."""
    mock_response = httpx.Response(
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

    details = _parse_error_details(mock_response)
    assert details["error_code"] == "insufficient_quota"
    assert details["error_type"] == "insufficient_quota"
    assert details["retry_after"] is None
    assert details["is_quota_error"] is True


def test_parse_error_details_project_spend_limit():
    """T3: Proje harcama limiti (project_spend_limit_exceeded) doğru tespit edilmeli."""
    mock_response = httpx.Response(
        status_code=429,
        json={
            "error": {
                "message": "The project spend limit has been exceeded.",
                "type": "spend_limit",
                "code": "project_spend_limit_exceeded"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    details = _parse_error_details(mock_response)
    assert details["error_code"] == "project_spend_limit_exceeded"
    assert details["is_quota_error"] is True


def test_parse_error_details_non_json_body():
    """T4: JSON olmayan HTML veya ham metin hata gövdesi güvenle ele alınmalı."""
    mock_response = httpx.Response(
        status_code=429,
        text="<html><body>429 Too Many Requests - Cloudflare</body></html>",
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    details = _parse_error_details(mock_response)
    assert details["error_code"] is None
    assert details["error_type"] is None
    assert details["retry_after"] is None
    assert "429 Too Many Requests" in details["safe_message"]


def test_parse_error_details_retry_after_header_case_insensitive():
    """T5: Retry-After başlığı büyük/küçük harf duyarsız okunmalı."""
    mock_response = httpx.Response(
        status_code=429,
        headers={"Retry-After": "45"},
        json={"error": {"message": "Rate limit exceeded"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    details = _parse_error_details(mock_response)
    assert details["retry_after"] == "45"


def test_parse_error_details_masks_secret_keys():
    """T6: Hata mesajı içinde API anahtarı geçse bile güvenle maskelenmeli."""
    secret_key = "sk-proj-supersecretkey1234567890abcdef"
    mock_response = httpx.Response(
        status_code=429,
        json={
            "error": {
                "message": f"Rate limit for key {secret_key} exceeded. Bearer mock_token_secret_value",
                "type": "requests",
                "code": "rate_limit_exceeded"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    details = _parse_error_details(mock_response, api_key_to_mask=secret_key)
    assert secret_key not in details["safe_message"]
    assert "mock_token_secret_value" not in details["safe_message"]
    assert "[MASKED" in details["safe_message"]


@pytest.mark.asyncio
async def test_openai_provider_raises_structured_ratelimit_error():
    """T7: OpenAICompatibleProvider.generate 429 yanıtında tüm detayları istisnaya aktarmalı."""
    cfg = LLMConfig(
        provider="openai",
        api_key="sk-mock-key-for-unit-testing",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini"
    )
    provider = OpenAICompatibleProvider(cfg)

    mock_resp = httpx.Response(
        status_code=429,
        headers={"retry-after": "10"},
        json={
            "error": {
                "message": "Monthly usage limit reached",
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
        assert err.error_code == "insufficient_quota"
        assert err.error_type == "insufficient_quota"
        assert err.retry_after == "10"
        assert err.is_quota_error is True
        assert "insufficient_quota" in err.message


@pytest.mark.asyncio
async def test_workflow_records_structured_error_in_fallback_events(tmp_path, monkeypatch):
    """T8: LangGraph workflow LLM 429 aldığında olay günlüğüne yapılandırılmış hata detaylarını kaydetmeli."""
    mock_resp = httpx.Response(
        status_code=429,
        headers={"retry-after": "30"},
        json={
            "error": {
                "message": "Quota limit reached",
                "type": "insufficient_quota",
                "code": "insufficient_quota"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-testing-key-12345")
    monkeypatch.setenv("LLM_FALLBACK_TO_DETERMINISTIC", "true")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result = await run_agent_workflow(
            task_id="test_diag_fallback_1",
            description="Basit hesap makinesi",
            planner_mode="llm",
            coder_mode="deterministic"
        )

        events = result.get("events", [])
        fallback_ev = next((e for e in events if e.get("type") == "planner_fallback"), None)
        assert fallback_ev is not None
        details = fallback_ev.get("details", {})
        assert details.get("error_code") == "insufficient_quota"
        assert details.get("error_type") == "insufficient_quota"
        assert details.get("retry_after") == "30"
        assert details.get("is_quota_error") is True


def test_parse_error_details_extracts_x_request_id():
    """T9: x-request-id başlığı güvenle ayıklanmalı ve request_id alanına atanmalıdır."""
    mock_response = httpx.Response(
        status_code=429,
        headers={"x-request-id": "req_openai_test_12345abcdef"},
        json={
            "error": {
                "message": "You have no credits remaining.",
                "type": "insufficient_quota",
                "code": "credit_balance_exhausted"
            }
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    details = _parse_error_details(mock_response)
    assert details["request_id"] == "req_openai_test_12345abcdef"
    assert details["is_quota_error"] is True
    assert details["error_code"] == "credit_balance_exhausted"


def test_parse_error_details_request_id_is_none_when_missing():
    """T10: x-request-id başlığı yoksa request_id None olmalı, sahte ID üretilmemelidir."""
    mock_response = httpx.Response(
        status_code=429,
        headers={},
        json={"error": {"message": "Rate limit exceeded"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )

    details = _parse_error_details(mock_response)
    assert details["request_id"] is None
