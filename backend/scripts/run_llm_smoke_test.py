"""
backend/scripts/run_llm_smoke_test.py
AI Dev Team — Kontrollü Canlı LLM Smoke Test Çalıştırıcısı

KULLANIM:
1. Varsayılan Güvenli Mod / Ön Kontrol (Dry-Run - 0 Ağ Çağrısı):
   python scripts/run_llm_smoke_test.py

2. Kontrollü Canlı Test (Tekil Minimal Planner İsteği - Dış API Çağrısı):
   python scripts/run_llm_smoke_test.py --live

GÜVENLİK VE MALİYET KURALLARI:
- Varsayılan modda dış ağa ASLA HTTP isteği gönderilmez.
- Canlı mod için açık '--live' parametresi zorunludur.
- Canlı modda yalnızca tek bir minimal Planner isteği (~50 token) yapılır.
- Coder çağrısı, Docker testi veya otomatik döngüler başlatılmaz.
- Kota ve kimlik doğrulama hatalarında fallback arkasına gizlenme yapılmaz.
- API anahtarları asla ekrana veya rapora yazdırılmaz.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Ensure backend root in sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from llm_provider import (
    BaseLLMProvider,
    LLMConfig,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMProviderError,
    LLMResponseFormatError,
    MockLLMProvider,
    OpenAICompatibleProvider,
    GeminiProvider,
    extract_json_from_llm_text,
    get_llm_provider,
    load_project_env,
)
from schemas import TaskPlan


async def execute_smoke_test(
    live_mode: bool = False,
    model_override: Optional[str] = None,
    provider_override: Optional[str] = None
) -> Dict[str, Any]:
    """
    Smoke test mantığını çalıştırır ve yapısal sonuç raporu üretir.
    """
    # .env dosyasını güvenle yükle
    load_project_env()

    cfg = LLMConfig.from_env()

    active_provider = (provider_override or cfg.provider).lower().strip()
    if model_override:
        active_model = model_override
    elif active_provider == "gemini":
        active_model = cfg.model if (cfg.provider == "gemini" and cfg.model and cfg.model != "gemini-2.5-flash") else "gemini-3.8-flash"
    else:
        active_model = cfg.model or "gpt-4o-mini"

    if live_mode:
        if active_provider == "mock":
            active_provider = "gemini" if os.environ.get("GEMINI_API_KEY") else "openai"
        if not model_override:
            if active_model in ["mock-llm-v1", "mock", "deterministic", "", "gemini-2.5-flash"]:
                active_model = "gemini-3.8-flash" if active_provider == "gemini" else "gpt-4o-mini"

    # Canlı mod yapılandırmasını kur
    live_cfg = LLMConfig.from_env()
    live_cfg.fallback_to_deterministic = False
    live_cfg.provider = active_provider
    live_cfg.model = active_model
    if active_provider == "gemini":
        live_cfg.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")
        if live_cfg.base_url == "https://api.openai.com/v1":
            live_cfg.base_url = "https://generativelanguage.googleapis.com/v1beta"

    safe_meta = live_cfg.safe_metadata()

    report: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "live_mode_requested": live_mode,
        "real_network_call_made": False,
        "provider": active_provider,
        "model": active_model,
        "base_host": safe_meta["base_host"],
        "is_configured": safe_meta["is_configured"],
        "timeout_seconds": safe_meta["timeout_sec"],
        "success": False,
        "http_status": None,
        "request_id": None,
        "error_type": None,
        "error_code": None,
        "is_quota_error": False,
        "error_message": None,
        "schema_validated": False,
        "plan_summary": None,
        "token_usage": None,
        "latency_ms": 0.0,
        "cost_warning_displayed": live_mode
    }

    print("=" * 70)
    print("AI DEV TEAM — LLM ENTEGRASYON SMOKE TESTİ")
    print(f"Mod: {'CANLI ÇAĞRI (LIVE)' if live_mode else 'GÜVENLİ ÖN KONTROL (DRY-RUN / MOCK)'}")
    print(f"Sağlayıcı: {report['provider']} | Model: {report['model']}")
    print(f"Uç Nokta Sunucusu: {safe_meta['base_host']}")
    print(f"Yapılandırma Durumu: {'Geçerli' if safe_meta['is_configured'] else 'Eksik / Yapılandırılmamış'}")
    print("=" * 70)

    # 1. Varsayılan Mod: Dry-run / Mock Doğrulaması
    if not live_mode:
        print("\n[BİLGİ] Varsayılan güvenli mod devrede. Dış ağa hiçbir HTTP isteği gönderilmedi.")
        print("[BİLGİ] Mock LLM sağlayıcısı ile Pydantic şema ve plan ayrıştırma doğrulaması yapılıyor...")

        mock_provider = MockLLMProvider(LLMConfig(provider="mock", model="mock-llm-v1"))
        t0 = time.perf_counter()
        try:
            plan_dict = await mock_provider.generate_json(
                prompt="Basit bir Python hesap makinesi modülü planı hazırla.",
                system_prompt="You are an expert Autonomous Software Architect. Output valid JSON."
            )
            plan = TaskPlan(**plan_dict)
            latency = (time.perf_counter() - t0) * 1000

            report["success"] = True
            report["schema_validated"] = True
            report["plan_summary"] = plan.goal[:120] if plan.goal else "Plan oluşturuldu"
            report["latency_ms"] = round(latency, 2)
            report["real_network_call_made"] = False

            print(f"[BAŞARILI] Mock Plan Şeması Doğrulandı ({report['latency_ms']} ms).")
            print(f"[BAŞARILI] Hedef: {report['plan_summary']}")
            print("\n[İPUCU] Canlı API sağlayıcısını (Gemini / OpenAI vb.) test etmek için: python scripts/run_llm_smoke_test.py --live")
        except Exception as exc:
            report["success"] = False
            report["error_type"] = exc.__class__.__name__
            report["error_message"] = str(exc)
            print(f"[HATA] Mock şema doğrulama başarısız: {str(exc)}")

        return report

    # 2. Canlı Mod: Tekil Minimal Planner İsteği
    print("\n[UYARI] Canlı mod etkinleştirildi! Dış LLM sağlayıcısına tekil minimal bir istek gönderilecek.")
    print(f"[UYARI] Bu işlem {active_provider.capitalize()} hesabınızda token maliyeti oluşturabilir.")

    if not live_cfg.is_configured():
        report["success"] = False
        report["error_type"] = "ConfigurationError"
        key_name = "GEMINI_API_KEY" if active_provider == "gemini" else "OPENAI_API_KEY"
        report["error_message"] = f"LLM API anahtarı ayarlanmamış ({key_name} eksik veya geçersiz)."
        print(f"\n[HATA] {report['error_message']}")
        return report

    # Canlı sağlayıcıyı yapılandır (fallback=False ile, böylece hata gerçek haliyle görünür)
    provider = get_llm_provider(live_cfg)

    minimal_prompt = "Basit bir Python calculator.py modülü için tek cümlelik hedef ve 2 alt görev içeren JSON plan üret."
    system_prompt = (
        "You are an Autonomous Software Architect. Respond with strictly valid JSON according to this schema:\n"
        '{"goal": "string", "subtasks": ["string"], "acceptance_criteria": ["string"], "risks": ["string"]}'
    )

    t0 = time.perf_counter()
    report["real_network_call_made"] = True

    try:
        # Tekil ve doğrudan API isteği (Coder, Docker, Benchmark, Retry ÇALIŞTIRILMAZ)
        raw_resp = await provider.generate(prompt=minimal_prompt, system_prompt=system_prompt)
        latency = (time.perf_counter() - t0) * 1000
        report["latency_ms"] = round(latency, 2)
        report["http_status"] = 200
        report["request_id"] = raw_resp.request_id

        # Token kullanımı (yalnızca API'den dönen gerçek değerler)
        if raw_resp.prompt_tokens or raw_resp.completion_tokens or raw_resp.total_tokens:
            report["token_usage"] = {
                "prompt_tokens": raw_resp.prompt_tokens,
                "completion_tokens": raw_resp.completion_tokens,
                "total_tokens": raw_resp.total_tokens
            }

        # Tekil yanıttan JSON ayıklama ve Pydantic TaskPlan şeması doğrulaması
        plan_dict = extract_json_from_llm_text(raw_resp.content)
        plan = TaskPlan(**plan_dict)
        report["schema_validated"] = True
        report["plan_summary"] = plan.goal[:120] if plan.goal else "Plan oluşturuldu"
        report["success"] = True

        print(f"\n[BAŞARILI] Canlı LLM Yanıtı Alındı ({report['latency_ms']} ms, HTTP 200).")
        if report["request_id"]:
            print(f"[BİLGİ] Request ID: {report['request_id']}")
        print(f"[BAŞARILI] Plan Şeması Doğrulandı: {report['plan_summary']}")
        if report["token_usage"]:
            print(f"[BAŞARILI] Token Kullanımı: {report['token_usage']}")

    except LLMAuthenticationError as auth_err:
        report["success"] = False
        report["http_status"] = auth_err.status_code or 401
        report["request_id"] = auth_err.request_id
        report["error_type"] = "LLMAuthenticationError"
        report["error_code"] = auth_err.error_code
        report["error_message"] = auth_err.message
        print(f"\n[HATA] 401 Authentication Hatası: {auth_err.message}")

    except LLMRateLimitError as rate_err:
        report["success"] = False
        report["http_status"] = 429
        report["request_id"] = rate_err.request_id
        report["error_type"] = "LLMRateLimitError"
        report["error_code"] = rate_err.error_code
        report["is_quota_error"] = rate_err.is_quota_error
        report["error_message"] = rate_err.message
        if rate_err.is_quota_error:
            print(f"\n[HATA] 429 Bakiye / Kota Yetersizliği: {rate_err.message}")
        else:
            print(f"\n[HATA] 429 İstek Sıklığı Sınırı (Rate Limit): {rate_err.message}")

    except LLMTimeoutError as timeout_err:
        report["success"] = False
        report["request_id"] = timeout_err.request_id
        report["error_type"] = "LLMTimeoutError"
        report["error_message"] = str(timeout_err)
        print(f"\n[HATA] Zaman Aşımı (Timeout): {str(timeout_err)}")

    except LLMResponseFormatError as fmt_err:
        report["success"] = False
        report["request_id"] = fmt_err.request_id
        report["error_type"] = "LLMResponseFormatError"
        report["error_message"] = str(fmt_err)
        print(f"\n[HATA] Yanıt Formatı / JSON Ayrıştırma Hatası: {str(fmt_err)}")

    except LLMProviderError as prov_err:
        report["success"] = False
        report["request_id"] = prov_err.request_id
        report["error_type"] = "LLMProviderError"
        report["error_message"] = str(prov_err)
        print(f"\n[HATA] Sağlayıcı / Ağ Hatası: {str(prov_err)}")

    except Exception as exc:
        report["success"] = False
        report["error_type"] = exc.__class__.__name__
        report["error_message"] = str(exc)
        print(f"\n[HATA] Beklenmeyen Hata: {str(exc)}")

    return report


def main():
    parser = argparse.ArgumentParser(description="AI Dev Team — Kontrollü Canlı LLM Smoke Testi")
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Dış LLM sağlayıcısına (Gemini, OpenAI vb.) tekil minimal bir canlı istek gönderir. (Maliyet oluşturabilir)"
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Canlı test için kullanılacak sağlayıcı ('gemini', 'openai', 'mock'). Varsayılan: .env içindeki LLM_PROVIDER"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Canlı test için kullanılacak model adı (Varsayılan: gemini-2.5-flash veya gpt-4o-mini)"
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default=os.path.join(backend_dir, "tests", "llm_smoke_test_report.json"),
        help="Raporun kaydedileceği JSON dosya yolu"
    )

    args = parser.parse_args()

    report = asyncio.run(
        execute_smoke_test(
            live_mode=args.live,
            model_override=args.model,
            provider_override=args.provider
        )
    )

    # Raporu diske kaydet
    try:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n[RAPOR] Rapor dosyası oluşturuldu: {os.path.abspath(args.output_json)}")
    except Exception as exc:
        print(f"[UYARI] Rapor diske yazılamadı: {exc}")

    sys.exit(0 if report["success"] else 1)


if __name__ == "__main__":
    main()
