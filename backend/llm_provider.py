"""
backend/llm_provider.py
AI Dev Team - LLM Provider Layer & Model Orchestration

Provides extensible, secure, and robust integration with LLM providers (OpenAI, OpenAI-compatible APIs, local servers).
Ensures zero secret leakage, strict timeout handling, rate limit resilience, and Pydantic schema validation.
"""

import abc
import json
import os
import re
import time
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field, model_validator


# --- Custom LLM Exceptions ---

class LLMProviderError(Exception):
    """Genel LLM sağlayıcı hatası."""
    def __init__(
        self,
        message: str,
        provider: str = "unknown",
        status_code: Optional[int] = None,
        error_code: Optional[str] = None,
        error_type: Optional[str] = None,
        retry_after: Optional[str] = None,
        is_quota_error: bool = False,
        request_id: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.error_code = error_code
        self.error_type = error_type
        self.retry_after = retry_after
        self.is_quota_error = is_quota_error
        self.request_id = request_id


class LLMAuthenticationError(LLMProviderError):
    """API anahtarı eksik, geçersiz veya yetkilendirme reddedildi (401/403)."""
    pass


class LLMRateLimitError(LLMProviderError):
    """Sağlayıcı istek limiti veya bakiye/kota aşımı hatası (429 Rate Limit / Quota Exceeded)."""
    def __init__(
        self,
        message: str,
        provider: str = "unknown",
        status_code: Optional[int] = 429,
        error_code: Optional[str] = None,
        error_type: Optional[str] = None,
        retry_after: Optional[str] = None,
        is_quota_error: bool = False,
        request_id: Optional[str] = None
    ):
        super().__init__(
            message=message,
            provider=provider,
            status_code=status_code,
            error_code=error_code,
            error_type=error_type,
            retry_after=retry_after,
            is_quota_error=is_quota_error,
            request_id=request_id
        )


class LLMTimeoutError(LLMProviderError):
    """Model çağrısı belirtilen zaman aşımı süresini aştı."""
    pass


class LLMResponseFormatError(LLMProviderError):
    """Model yanıtı beklenen JSON veya şema formatında değil."""
    pass


_ENV_LOADED = False


def load_project_env(base_dir: Optional[str] = None, force_reload: bool = False) -> None:
    """
    backend/.env ve proje kök .env dosyalarını çalışma dizininden bağımsız olarak güvenle yükler.
    Mevcut os.environ değişkenlerini ezmez (override=False).
    """
    global _ENV_LOADED
    if _ENV_LOADED and not force_reload and base_dir is None:
        return

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    current_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
    backend_env = os.path.join(current_dir, ".env")
    parent_env = os.path.join(os.path.dirname(current_dir), ".env")

    # 1. backend/.env dosyasını yükle (override=False - mevcut işlem değişkenlerini korur)
    if os.path.isfile(backend_env):
        load_dotenv(dotenv_path=backend_env, override=False)

    # 2. Üst dizindeki .env dosyasını yükle (override=False)
    if os.path.isfile(parent_env):
        load_dotenv(dotenv_path=parent_env, override=False)

    if base_dir is None:
        _ENV_LOADED = True


# Modül import edildiğinde güvenli .env yüklemesini başlat
load_project_env()


# --- LLM Config & Response Models ---

class LLMConfig(BaseModel):
    """LLM Sağlayıcı Yapılandırma Modeli (Ortam Değişkenleri)."""
    provider: str = Field(default="openai", description="Sağlayıcı türü ('openai', 'openai_compatible', 'gemini', 'mock')")
    api_key: Optional[str] = Field(default=None, description="API anahtarı (Gizli tutulur)")
    base_url: str = Field(default="https://api.openai.com/v1", description="API kök adresi")
    model: str = Field(default="gpt-4o-mini", description="Kullanılacak model adı")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="Örnekleme sıcaklığı")
    max_tokens: int = Field(default=2048, ge=1, le=16384, description="Maksimum çıktı token sayısı")
    timeout: float = Field(default=15.0, ge=1.0, le=120.0, description="Zaman aşımı süresi (saniye)")
    max_retries: int = Field(default=2, ge=0, le=5, description="Maksimum deneme sayısı")
    fallback_to_deterministic: bool = Field(default=True, description="Hata durumunda deterministik motora düşme")

    @model_validator(mode="after")
    def _normalize_provider_defaults(self) -> "LLMConfig":
        if self.provider == "gemini":
            if self.base_url == "https://api.openai.com/v1":
                self.base_url = "https://generativelanguage.googleapis.com/v1beta"
            if self.model in ["gpt-4o-mini", "gemini-2.5-flash", ""]:
                self.model = "gemini-3.8-flash"
        return self

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Ortam değişkenlerinden yapılandırmayı yükler."""
        provider = os.environ.get("LLM_PROVIDER", "openai").lower().strip()

        # Sağlayıcı bazlı varsayılanlar ve API anahtarı çözümlemesi
        if provider == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")
            default_base_url = "https://generativelanguage.googleapis.com/v1beta"
            default_model = "gemini-3.8-flash"
            base_url = os.environ.get("GEMINI_BASE_URL") or os.environ.get("LLM_BASE_URL") or default_base_url
        else:
            api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
            default_base_url = "https://api.openai.com/v1"
            default_model = "gpt-4o-mini"
            base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_BASE_URL") or default_base_url

        # Boşluklu veya placeholder olan anahtarları None say
        if api_key:
            api_key = api_key.strip()
            placeholder_values = {
                "",
                "your-openai-api-key-here",
                "your-gemini-api-key-here",
                "sk-placeholder",
                "gemini-placeholder",
                "none",
                "null"
            }
            if api_key in placeholder_values:
                api_key = None

        return cls(
            provider=provider,
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model=os.environ.get("LLM_MODEL", default_model),
            temperature=float(os.environ.get("LLM_TEMPERATURE", "0.2")),
            max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "2048")),
            timeout=float(os.environ.get("LLM_TIMEOUT", "15.0")),
            max_retries=int(os.environ.get("LLM_MAX_RETRIES", "2")),
            fallback_to_deterministic=os.environ.get("LLM_FALLBACK_TO_DETERMINISTIC", "true").lower() in ["true", "1", "yes"]
        )

    def is_configured(self) -> bool:
        """Sağlayıcının geçerli bir API anahtarına veya mock moduna sahip olup olmadığını bildirir."""
        if self.provider == "mock":
            return True
        return bool(self.api_key and len(self.api_key) > 5)

    def safe_metadata(self) -> Dict[str, Any]:
        """API anahtarı ve hassas verileri içermeyen güvenli metaveri sözlüğü döndürür."""
        # Base URL host bilgisini güvenli ayıkla
        base_host = self.base_url.split("//")[-1].split("/")[0] if "//" in self.base_url else self.base_url
        return {
            "provider": self.provider,
            "model": self.model,
            "base_host": base_host,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout_sec": self.timeout,
            "is_configured": self.is_configured(),
            "fallback_enabled": self.fallback_to_deterministic,
            "fallback_to_deterministic": self.fallback_to_deterministic
        }


class LLMResponse(BaseModel):
    """Standartlaştırılmış LLM Yanıt Modeli."""
    content: str = Field(..., description="Modelin ürettiği metin yanıt")
    provider: str = Field(..., description="Kullanılan sağlayıcı")
    model: str = Field(..., description="Kullanılan model")
    prompt_tokens: Optional[int] = Field(None, description="Girdi token sayısı")
    completion_tokens: Optional[int] = Field(None, description="Çıktı token sayısı")
    total_tokens: Optional[int] = Field(None, description="Toplam token sayısı")
    latency_ms: float = Field(default=0.0, description="Yanıt süresi (ms)")
    raw_json: Optional[Dict[str, Any]] = Field(None, description="Ayrıştırılmış JSON nesnesi (varsa)")
    request_id: Optional[str] = Field(None, description="Sağlayıcı x-request-id başlığı")


# --- Helper JSON Extraction ---

def extract_json_from_llm_text(text: str) -> Dict[str, Any]:
    """
    LLM çıktısından JSON nesnesini güvenle ayıklar:
    1. Doğrudan json.loads dener.
    2. Markdown ```json ... ``` kod bloklarını arar.
    3. Metin içindeki en dış {...} parantezlerini arar.
    """
    if not text or not text.strip():
        raise LLMResponseFormatError("Model çıktısı boş.")

    trimmed = text.strip()

    # 1. Doğrudan parse
    try:
        data = json.loads(trimmed)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. Markdown json bloğu arama (```json ... ``` veya ``` ...)
    md_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", trimmed, re.IGNORECASE)
    if md_match:
        try:
            data = json.loads(md_match.group(1))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 3. En geniş {...} bloğunu yakala
    first_brace = trimmed.find("{")
    last_brace = trimmed.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        json_candidate = trimmed[first_brace:last_brace + 1]
        try:
            data = json.loads(json_candidate)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            raise LLMResponseFormatError(f"Model çıktısındaki JSON ayrıştırılamadı: {str(exc)}")

    raise LLMResponseFormatError("Model yanıtında geçerli bir JSON nesnesi tespit edilemedi.")


def _parse_error_details(response: httpx.Response, api_key_to_mask: Optional[str] = None) -> Dict[str, Any]:
    """
    HTTP hata yanıtından hassas verileri filtreleyerek güvenli hata detaylarını ayıklar.
    Asla tam gövdeyi, API anahtarını veya gizli başlıkları döndürmez.
    """
    error_code: Optional[str] = None
    error_type: Optional[str] = None
    raw_message: Optional[str] = None
    retry_after: Optional[str] = response.headers.get("retry-after") or response.headers.get("Retry-After")
    
    # Request ID tespiti (x-request-id veya x-goog-request-id başlığı - sahte ID üretilmez)
    request_id_raw = (
        response.headers.get("x-goog-request-id")
        or response.headers.get("x-request-id")
        or response.headers.get("X-Request-Id")
        or response.headers.get("x-request_id")
    )
    request_id: Optional[str] = None
    if request_id_raw:
        cleaned_id = str(request_id_raw).strip()
        if cleaned_id and len(cleaned_id) <= 120:
            request_id = cleaned_id

    try:
        data = response.json()
        if isinstance(data, dict) and "error" in data and isinstance(data["error"], dict):
            err = data["error"]
            error_code = str(err.get("code") or err.get("status")) if (err.get("code") is not None or err.get("status") is not None) else None
            error_type = str(err.get("status") or err.get("type")) if (err.get("status") or err.get("type") is not None) else None
            raw_message = str(err.get("message")) if err.get("message") is not None else None
        elif isinstance(data, dict):
            error_code = str(data.get("code") or data.get("status")) if (data.get("code") is not None or data.get("status") is not None) else None
            error_type = str(data.get("status") or data.get("type")) if (data.get("status") or data.get("type") is not None) else None
            raw_message = str(data.get("message")) if data.get("message") is not None else None
    except Exception:
        raw_message = response.text[:200] if response.text else None

    # Güvenli sanitize: API anahtarını ve hassas kalıpları temizle
    safe_msg = ""
    if raw_message:
        safe_msg = str(raw_message)
        if api_key_to_mask and len(api_key_to_mask) > 5:
            safe_msg = safe_msg.replace(api_key_to_mask, "[MASKED_KEY]")
        safe_msg = re.sub(r"sk-[a-zA-Z0-9_\-]{15,}", "[MASKED_KEY]", safe_msg)
        safe_msg = re.sub(r"AQ\.[a-zA-Z0-9_\-]{20,}", "[MASKED_KEY]", safe_msg)
        safe_msg = re.sub(r"AIza[a-zA-Z0-9_\-]{30,}", "[MASKED_KEY]", safe_msg)
        safe_msg = re.sub(r"Bearer\s+[a-zA-Z0-9_\.\-]+", "Bearer [MASKED]", safe_msg)
        safe_msg = safe_msg[:300].strip()

    # Kota / bakiye / harcama limiti tespiti
    is_quota = False
    combined_check = f"{error_code or ''} {error_type or ''} {safe_msg}".lower()
    quota_keywords = [
        "insufficient_quota",
        "quota",
        "credit",
        "billing",
        "spend_limit",
        "usage_limit",
        "project_spend_limit_exceeded",
        "credit_balance_exhausted",
        "resource_exhausted",
        "resource has been exhausted"
    ]
    if any(kw in combined_check for kw in quota_keywords):
        is_quota = True

    return {
        "error_code": error_code,
        "error_type": error_type,
        "safe_message": safe_msg,
        "retry_after": retry_after,
        "is_quota_error": is_quota,
        "request_id": request_id
    }


# --- Abstract Base Provider ---

class BaseLLMProvider(abc.ABC):
    """Tüm LLM sağlayıcılarının türediği soyut temel sınıf."""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abc.abstractmethod
    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> LLMResponse:
        """Modelden metin yanıtı üretir."""
        pass

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Modelden JSON formatında yapısal veri üretir ve doğrular."""
        res = await self.generate(prompt=prompt, system_prompt=system_prompt)
        parsed = extract_json_from_llm_text(res.content)
        res.raw_json = parsed
        return parsed

    def is_configured(self) -> bool:
        return self.config.is_configured()

    def get_metadata(self) -> Dict[str, Any]:
        return self.config.safe_metadata()


# --- OpenAI & OpenAI-Compatible Provider ---

class OpenAICompatibleProvider(BaseLLMProvider):
    """
    OpenAI ve OpenAI uyumlu REST API servisleri (OpenAI, Azure, Ollama, LocalAI, vLLM, Groq vb.) için
    asenkron HTTP istemcisi.
    """

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> LLMResponse:
        if not self.config.api_key:
            raise LLMAuthenticationError(
                "OpenAI / LLM API anahtarı bulunamadı. Lütfen 'OPENAI_API_KEY' ortam değişkenini ayarlayın.",
                provider=self.config.provider
            )

        endpoint = f"{self.config.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "AIDevTeam-LLMProvider/1.0"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        # JSON çıktısını teşvik etmek için response_format (destekleyen modeller için)
        if "gpt" in self.config.model.lower() or "mini" in self.config.model.lower():
            payload["response_format"] = {"type": "json_object"}

        start_time = time.perf_counter()

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            try:
                response = await client.post(endpoint, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError(
                    f"LLM sağlayıcısına istek zaman aşımına uğradı ({self.config.timeout}s).",
                    provider=self.config.provider
                ) from exc
            except httpx.NetworkError as exc:
                raise LLMProviderError(
                    f"LLM sağlayıcısına ağ bağlantısı kurulamadı ({self.config.base_url}): {str(exc)}",
                    provider=self.config.provider
                ) from exc
            except Exception as exc:
                raise LLMProviderError(
                    f"LLM sağlayıcısına istek gönderilirken beklenmeyen bir hata oluştu: {str(exc)}",
                    provider=self.config.provider
                ) from exc

        duration_ms = (time.perf_counter() - start_time) * 1000

        # HTTP Durum Kodu Kontrolleri
        if response.status_code == 401 or response.status_code == 403:
            err_details = _parse_error_details(response, api_key_to_mask=self.config.api_key)
            msg_suffix = f" Detay: {err_details['safe_message']}" if err_details["safe_message"] else ""
            raise LLMAuthenticationError(
                f"LLM API anahtarı geçersiz veya yetkilendirme reddedildi ({response.status_code}).{msg_suffix}",
                provider=self.config.provider,
                status_code=response.status_code,
                error_code=err_details["error_code"],
                error_type=err_details["error_type"],
                retry_after=err_details["retry_after"],
                is_quota_error=err_details["is_quota_error"],
                request_id=err_details["request_id"]
            )
        elif response.status_code == 429:
            err_details = _parse_error_details(response, api_key_to_mask=self.config.api_key)
            code = err_details["error_code"]
            etype = err_details["error_type"]
            msg = err_details["safe_message"]
            retry_after = err_details["retry_after"]
            is_quota = err_details["is_quota_error"]
            req_id = err_details["request_id"]

            if is_quota:
                base_desc = "OpenAI bakiye veya harcama kotası yetersiz (insufficient_quota / spend_limit)."
            else:
                base_desc = "LLM API istek sıklığı limiti aşıldı (rate_limit_exceeded)."

            parts = [f"{base_desc} (HTTP 429)"]
            if req_id:
                parts.append(f"request_id='{req_id}'")
            if code:
                parts.append(f"code='{code}'")
            if etype:
                parts.append(f"type='{etype}'")
            if retry_after:
                parts.append(f"retry_after={retry_after}s")
            if msg:
                parts.append(f"detay: {msg}")

            final_msg = " | ".join(parts)

            raise LLMRateLimitError(
                final_msg,
                provider=self.config.provider,
                status_code=429,
                error_code=code,
                error_type=etype,
                retry_after=retry_after,
                is_quota_error=is_quota,
                request_id=req_id
            )
        elif response.status_code >= 500:
            err_details = _parse_error_details(response, api_key_to_mask=self.config.api_key)
            raise LLMProviderError(
                f"LLM sağlayıcısı sunucu hatası döndürdü ({response.status_code}): {err_details['safe_message'] or response.text[:200]}",
                provider=self.config.provider,
                status_code=response.status_code,
                error_code=err_details["error_code"],
                error_type=err_details["error_type"],
                retry_after=err_details["retry_after"],
                request_id=err_details["request_id"]
            )
        elif response.status_code != 200:
            err_details = _parse_error_details(response, api_key_to_mask=self.config.api_key)
            raise LLMProviderError(
                f"LLM çağrısı başarısız oldu ({response.status_code}): {err_details['safe_message'] or response.text[:200]}",
                provider=self.config.provider,
                status_code=response.status_code,
                error_code=err_details["error_code"],
                error_type=err_details["error_type"],
                retry_after=err_details["retry_after"],
                request_id=err_details["request_id"]
            )

        try:
            resp_json = response.json()
            choice = resp_json["choices"][0]
            content = choice["message"]["content"]
            usage = resp_json.get("usage", {})
        except (KeyError, IndexError, ValueError) as exc:
            req_id_raw = response.headers.get("x-request-id") or response.headers.get("X-Request-Id")
            raise LLMResponseFormatError(
                f"Sağlayıcıdan dönen yanıt formatı ayrıştırılamadı: {str(exc)}",
                provider=self.config.provider,
                request_id=str(req_id_raw).strip() if req_id_raw else None
            ) from exc

        req_id_success = response.headers.get("x-request-id") or response.headers.get("X-Request-Id")
        return LLMResponse(
            content=content,
            provider=self.config.provider,
            model=resp_json.get("model", self.config.model),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=round(duration_ms, 2),
            request_id=str(req_id_success).strip() if req_id_success else None
        )


# --- Google Gemini Provider ---

class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini (v1beta) REST API servisi için asenkron HTTP istemcisi.
    Desteklenen resmi modeller: gemini-2.5-flash (varsayılan), gemini-1.5-flash, gemini-2.0-flash vb.
    """

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> LLMResponse:
        if not self.config.api_key:
            raise LLMAuthenticationError(
                "Google Gemini API anahtarı bulunamadı. Lütfen 'GEMINI_API_KEY' ortam değişkenini ayarlayın.",
                provider="gemini"
            )

        # Model adı normalizasyonu (models/ önekini gerekirse temizle)
        model_name = self.config.model.strip()
        if model_name.startswith("models/"):
            model_name = model_name[len("models/"):]

        endpoint = f"{self.config.base_url}/models/{model_name}:generateContent"
        headers = {
            "x-goog-api-key": self.config.api_key,
            "Content-Type": "application/json",
            "User-Agent": "AIDevTeam-GeminiProvider/1.0"
        }

        # Gemini REST içerik formatı
        contents: List[Dict[str, Any]] = [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ]

        # Gemini 3.x modelleri (gemini-3.8-flash vb.) ile eski modeller arasındaki parametre uyumluluğu:
        # Gemini 3.x serisinde geleneksel token örnekleme parametreleri (temperature, top_p, top_k) kaldırılmıştır/desteklenmez.
        # Bunun yerine reasoning derinliği thinkingConfig (low/medium/high) ile belirlenir.
        is_gemini_3 = "gemini-3" in model_name.lower()

        generation_config: Dict[str, Any] = {
            "maxOutputTokens": self.config.max_tokens,
            "candidateCount": 1,
        }

        if is_gemini_3:
            generation_config["thinkingConfig"] = {
                "thinkingLevel": "low"
            }
        else:
            generation_config["temperature"] = self.config.temperature

        # JSON çıktısını teşvik etmek için responseMimeType (destekleyen Gemini modelleri için)
        combined_text = f"{system_prompt or ''} {prompt}".lower()
        if "json" in combined_text:
            generation_config["responseMimeType"] = "application/json"

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config
        }

        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        start_time = time.perf_counter()

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            try:
                response = await client.post(endpoint, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError(
                    f"Gemini sağlayıcısına istek zaman aşımına uğradı ({self.config.timeout}s).",
                    provider="gemini"
                ) from exc
            except httpx.NetworkError as exc:
                raise LLMProviderError(
                    f"Gemini sağlayıcısına ağ bağlantısı kurulamadı ({self.config.base_url}): {str(exc)}",
                    provider="gemini"
                ) from exc
            except Exception as exc:
                raise LLMProviderError(
                    f"Gemini sağlayıcısına istek gönderilirken beklenmeyen bir hata oluştu: {str(exc)}",
                    provider="gemini"
                ) from exc

        duration_ms = (time.perf_counter() - start_time) * 1000

        # HTTP Hata Durum Kodu Kontrolleri
        if response.status_code in (401, 403):
            err_details = _parse_error_details(response, api_key_to_mask=self.config.api_key)
            msg_suffix = f" Detay: {err_details['safe_message']}" if err_details["safe_message"] else ""
            raise LLMAuthenticationError(
                f"Gemini API anahtarı geçersiz veya yetkilendirme reddedildi ({response.status_code}).{msg_suffix}",
                provider="gemini",
                status_code=response.status_code,
                error_code=err_details["error_code"],
                error_type=err_details["error_type"],
                retry_after=err_details["retry_after"],
                is_quota_error=err_details["is_quota_error"],
                request_id=err_details["request_id"]
            )
        elif response.status_code == 429:
            err_details = _parse_error_details(response, api_key_to_mask=self.config.api_key)
            code = err_details["error_code"]
            etype = err_details["error_type"]
            msg = err_details["safe_message"]
            retry_after = err_details["retry_after"]
            is_quota = err_details["is_quota_error"]
            req_id = err_details["request_id"]

            if is_quota:
                base_desc = "Google Gemini bakiye veya harcama kotası yetersiz (RESOURCE_EXHAUSTED / quota_exceeded)."
            else:
                base_desc = "Google Gemini API istek sıklığı limiti aşıldı (rate_limit_exceeded)."

            parts = [f"{base_desc} (HTTP 429)"]
            if req_id:
                parts.append(f"request_id='{req_id}'")
            if code:
                parts.append(f"code='{code}'")
            if etype:
                parts.append(f"type='{etype}'")
            if retry_after:
                parts.append(f"retry_after={retry_after}s")
            if msg:
                parts.append(f"detay: {msg}")

            final_msg = " | ".join(parts)
            raise LLMRateLimitError(
                final_msg,
                provider="gemini",
                status_code=429,
                error_code=code,
                error_type=etype,
                retry_after=retry_after,
                is_quota_error=is_quota,
                request_id=req_id
            )
        elif response.status_code == 400:
            err_details = _parse_error_details(response, api_key_to_mask=self.config.api_key)
            msg_lower = (err_details["safe_message"] or "").lower()
            if "api_key" in msg_lower or "api key" in msg_lower or "key not valid" in msg_lower:
                raise LLMAuthenticationError(
                    f"Gemini API anahtarı geçersiz ({response.status_code}): {err_details['safe_message']}",
                    provider="gemini",
                    status_code=400,
                    error_code=err_details["error_code"],
                    error_type=err_details["error_type"],
                    request_id=err_details["request_id"]
                )
            if err_details["is_quota_error"]:
                raise LLMRateLimitError(
                    f"Google Gemini bakiye veya kota hatası ({response.status_code}): {err_details['safe_message']}",
                    provider="gemini",
                    status_code=400,
                    error_code=err_details["error_code"],
                    error_type=err_details["error_type"],
                    is_quota_error=True,
                    request_id=err_details["request_id"]
                )
            raise LLMProviderError(
                f"Gemini isteği geçersiz parametre içeriyor (HTTP 400): {err_details['safe_message'] or response.text[:200]}",
                provider="gemini",
                status_code=400,
                error_code=err_details["error_code"],
                error_type=err_details["error_type"],
                request_id=err_details["request_id"]
            )
        elif response.status_code >= 500:
            err_details = _parse_error_details(response, api_key_to_mask=self.config.api_key)
            raise LLMProviderError(
                f"Gemini sağlayıcısı sunucu hatası döndürdü ({response.status_code}): {err_details['safe_message'] or response.text[:200]}",
                provider="gemini",
                status_code=response.status_code,
                error_code=err_details["error_code"],
                error_type=err_details["error_type"],
                retry_after=err_details["retry_after"],
                request_id=err_details["request_id"]
            )
        elif response.status_code != 200:
            err_details = _parse_error_details(response, api_key_to_mask=self.config.api_key)
            raise LLMProviderError(
                f"Gemini çağrısı başarısız oldu ({response.status_code}): {err_details['safe_message'] or response.text[:200]}",
                provider="gemini",
                status_code=response.status_code,
                error_code=err_details["error_code"],
                error_type=err_details["error_type"],
                retry_after=err_details["retry_after"],
                request_id=err_details["request_id"]
            )

        # Başarılı Yanıt Ayrıştırma
        req_id_raw = (
            response.headers.get("x-goog-request-id")
            or response.headers.get("x-request-id")
            or response.headers.get("X-Request-Id")
        )
        req_id = str(req_id_raw).strip() if req_id_raw else None

        try:
            resp_json = response.json()
            candidates = resp_json.get("candidates", [])
            if not candidates:
                # Güvenlik filtresi (promptFeedback) kontrolü
                prompt_feedback = resp_json.get("promptFeedback", {})
                block_reason = prompt_feedback.get("blockReason")
                if block_reason:
                    raise LLMProviderError(
                        f"Gemini isteği güvenlik filtresi tarafından engellendi: {block_reason}",
                        provider="gemini",
                        error_type=block_reason,
                        request_id=req_id
                    )
                raise LLMResponseFormatError(
                    "Gemini yanıtında geçerli bir aday (candidate) bulunamadı.",
                    provider="gemini",
                    request_id=req_id
                )

            cand = candidates[0]
            finish_reason = cand.get("finishReason")
            if finish_reason in ["SAFETY", "RECITATION", "BLOCKLIST"]:
                raise LLMProviderError(
                    f"Gemini yanıtı güvenlik politikası nedeniyle durduruldu ({finish_reason}).",
                    provider="gemini",
                    error_type=finish_reason,
                    request_id=req_id
                )

            parts = cand.get("content", {}).get("parts", [])
            if not parts:
                raise LLMResponseFormatError(
                    "Gemini adayı içerisinde metin parçası (parts) bulunamadı.",
                    provider="gemini",
                    request_id=req_id
                )

            # Gemini 3.x modellerinde düşünce (thought) parçaları ile nihai yanıt parçaları ayrı dönebilir.
            # thought=True olan parçalar filtrelenir, sadece nihai metin birleştirilir.
            answer_parts = [
                p.get("text", "")
                for p in parts
                if not p.get("thought", False) and p.get("text")
            ]
            if answer_parts:
                content = "".join(answer_parts)
            else:
                content = "".join(p.get("text", "") for p in parts if p.get("text"))

            usage = resp_json.get("usageMetadata", {})
        except LLMProviderError:
            raise
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMResponseFormatError(
                f"Gemini sağlayıcısından dönen yanıt formatı ayrıştırılamadı: {str(exc)}",
                provider="gemini",
                request_id=req_id
            ) from exc

        return LLMResponse(
            content=content,
            provider="gemini",
            model=resp_json.get("modelVersion", self.config.model),
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
            total_tokens=usage.get("totalTokenCount"),
            latency_ms=round(duration_ms, 2),
            request_id=req_id
        )


# --- Mock LLM Provider (Testler ve Çevrimdışı Çalışma İçin) ---

class MockLLMProvider(BaseLLMProvider):
    """
    Birim testler ve çevrimdışı doğrulama için deterministik Mock sağlayıcı.
    Gerçek API çağrısı veya anahtar gerektirmez.
    """

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        custom_response: Optional[str] = None,
        simulate_error: Optional[Exception] = None
    ):
        cfg = config or LLMConfig(provider="mock", model="mock-model-v1", api_key="mock-key-12345")
        super().__init__(cfg)
        self.custom_response = custom_response
        self.simulate_error = simulate_error

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> LLMResponse:
        if self.simulate_error:
            raise self.simulate_error

        if self.custom_response:
            return LLMResponse(
                content=self.custom_response,
                provider="mock",
                model=self.config.model,
                prompt_tokens=50,
                completion_tokens=150,
                total_tokens=200,
                latency_ms=12.5
            )

        # Coder Agent isteği tespiti
        combined = f"{system_prompt or ''} {prompt}".lower()
        if "coder" in combined or "allowed_coder_filenames" in combined or "target files" in combined:
            filename = "calculator.py"
            code_body = '''"""
Mock LLM Coder - Calculator Module
"""

class Calculator:
    """Tip guvenli temel aritmetik islemleri."""
    def add(self, a: float, b: float) -> float:
        return float(a + b)

    def subtract(self, a: float, b: float) -> float:
        return float(a - b)

    def multiply(self, a: float, b: float) -> float:
        return float(a * b)

    def divide(self, a: float, b: float) -> float:
        if b == 0:
            raise ValueError("Sıfıra bölme hatası.")
        return float(a / b)


def add(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Geçersiz tip.")
    return a + b


def subtract(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Geçersiz tip.")
    return a - b


def multiply(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Geçersiz tip.")
    return a * b


def divide(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Geçersiz tip.")
    if b == 0:
        raise ValueError("Sıfıra bölme hatası.")
    return float(a) / float(b)
'''
            if "email" in combined or "filter" in combined:
                filename = "email_filter.py"
                code_body = r'''"""
Mock LLM Coder - Email Filter Module
"""
import re
from typing import List


def filter_emails(emails: List[str]) -> List[str]:
    """
    E-posta adreslerini temizler, gecersizleri eler ve tekillestirir.
    """
    valid: List[str] = []
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    for item in emails:
        if not isinstance(item, str):
            continue
        cleaned = item.strip().lower()
        if re.match(pattern, cleaned) and cleaned not in valid:
            valid.append(cleaned)
    return valid
'''
            elif "rate" in combined or "limiter" in combined:
                filename = "rate_limiter.py"
                code_body = '''"""
Mock LLM Coder - Rate Limiter Middleware
"""
from typing import Dict, List
from datetime import datetime, timezone
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException, status


class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.history: Dict[str, List[float]] = {}

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = datetime.now(timezone.utc).timestamp()
        reqs = self.history.get(client_ip, [])
        reqs = [t for t in reqs if now - t < self.window_seconds]
        if len(reqs) >= self.max_requests:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
        reqs.append(now)
        self.history[client_ip] = reqs
        return await call_next(request)
'''

            default_coder_json = {
                "summary": f"Mock LLM Coder: '{filename}' modülü ve README dokümantasyonu başarıyla üretildi.",
                "files": [
                    {
                        "filename": filename,
                        "content": code_body.strip() + "\n"
                    },
                    {
                        "filename": "README.md",
                        "content": f"# AI Dev Team - Mock LLM Code Output\n\nGenerated for: {prompt[:80]}\nStatus: Mock Verified\n"
                    }
                ]
            }

            return LLMResponse(
                content=json.dumps(default_coder_json, ensure_ascii=False),
                provider="mock",
                model=self.config.model,
                prompt_tokens=60,
                completion_tokens=220,
                total_tokens=280,
                latency_ms=10.0,
                raw_json=default_coder_json
            )

        # Varsayılan geçerli JSON plan yanıtı (Planner Agent)
        default_json = {
            "goal": f"Mock LLM Tabanlı Plan: {prompt[:100]}",
            "subtasks": [
                "1. [Mock Planner] Gereksinim Analizi ve Kapsam Ayrıştırması",
                "2. [Mock Planner] Veri Modelleri ve Arayüz Tanımları",
                "3. [Mock Planner] Çekirdek İş Mantığı Geliştirme",
                "4. [Mock Planner] Otomatik Testlerin ve Doğrulama Senaryolarının Yazılması",
                "5. [Mock Planner] Güvenlik ve Performans İncelemesi"
            ],
            "acceptance_criteria": [
                "Görev gereksinimlerinin eksiksiz ve tip güvenli karşılanması",
                "Tüm birim testlerinin başarıyla geçmesi",
                "Geriye dönük uyumluluğun korunması"
            ],
            "risks": [
                "API sözleşmelerinde uyumsuzluk riski",
                "Büyük veri setlerinde bellek ve sorgu optimizasyonu gereksinimi"
            ]
        }

        return LLMResponse(
            content=json.dumps(default_json, ensure_ascii=False),
            provider="mock",
            model=self.config.model,
            prompt_tokens=45,
            completion_tokens=160,
            total_tokens=205,
            latency_ms=15.0,
            raw_json=default_json
        )


# --- Factory Function ---

def get_llm_provider(config: Optional[LLMConfig] = None) -> BaseLLMProvider:
    """
    Yapılandırmaya uygun LLM sağlayıcı örneğini döndürür.
    """
    cfg = config or LLMConfig.from_env()

    if cfg.provider == "mock":
        return MockLLMProvider(cfg)
    elif cfg.provider == "gemini":
        return GeminiProvider(cfg)
    elif cfg.provider in ["openai", "openai_compatible", "azure", "groq", "ollama", "localai"]:
        return OpenAICompatibleProvider(cfg)
    else:
        # Varsayılan olarak OpenAI uyumlu sağlayıcıyı kullan
        return OpenAICompatibleProvider(cfg)
