"""
Gemini entegrasyon yapılandırma doğrulama betiği (ağ çağrısı yapmaz).
"""
import sys
import os
import json
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_provider import load_project_env, LLMConfig, GeminiProvider, get_llm_provider
from scripts.run_llm_smoke_test import execute_smoke_test

load_project_env(force_reload=True)

# --- Yapilandirma ---
cfg = LLMConfig.from_env()
print("=== YAPILANDIRMA ===")
print(f"provider       : {cfg.provider}")
print(f"model          : {cfg.model}")
print(f"base_url       : {cfg.base_url}")
key_info = "MEVCUT (uzunluk=" + str(len(cfg.api_key)) + ")" if cfg.api_key else "EKSIK"
print(f"GEMINI_API_KEY : {key_info}")
print(f"is_configured  : {cfg.is_configured()}")
print(f"timeout        : {cfg.timeout}s")
print(f"fallback       : {cfg.fallback_to_deterministic}")

# --- Provider factory ---
p = get_llm_provider(cfg)
print()
print("=== PROVIDER FACTORY ===")
print(f"Sinif          : {p.__class__.__name__}")
print(f"GeminiProvider : {isinstance(p, GeminiProvider)}")

# --- safe_metadata sizinti kontrolu ---
meta = cfg.safe_metadata()
meta_str = json.dumps(meta)
api_key_leaked = bool(cfg.api_key) and cfg.api_key in meta_str
print()
print("=== GUVENLIK ===")
print(f"safe_metadata API key siziyor mu : {api_key_leaked}")
print(f"safe_metadata icerigi            : {meta_str}")

# --- Gemini 3.x parametre mantigi ---
is_gemini_3 = "gemini-3" in cfg.model.lower()
gen_cfg = {"maxOutputTokens": cfg.max_tokens, "candidateCount": 1}
if is_gemini_3:
    gen_cfg["thinkingConfig"] = {"thinkingLevel": "low"}
    temperature_sent = False
else:
    gen_cfg["temperature"] = cfg.temperature
    temperature_sent = True

print()
print("=== GEMINI PARAMETRE UYUMLULUGU ===")
print(f"Gemini 3.x model mi    : {is_gemini_3}")
print(f"thinkingConfig eklendi : {'thinkingConfig' in gen_cfg}")
print(f"temperature gonderildi : {temperature_sent}")
print(f"generationConfig       : {json.dumps(gen_cfg)}")

# --- Smoke test retry / dongu kontrolu ---
src = inspect.getsource(execute_smoke_test)
retry_mentions = src.lower().count("retry")
retry_after_mentions = src.lower().count("retry-after") + src.lower().count("retry_after")
retry_loops = max(0, retry_mentions - retry_after_mentions)
loop_count = src.count("for ") + src.count("while ")
generate_calls = src.count("await provider.generate")

print()
print("=== SMOKE TEST GUVENLIK ===")
print(f"retry dongusu           : {retry_loops} (0 olmali)")
print(f"for/while dongu sayisi  : {loop_count} (0 olmali)")
print(f"provider.generate() cagri sayisi : {generate_calls} (1 olmali)")

# --- live_mode guard ---
live_guard_present = "if not live_mode:" in src and "real_network_call_made" in src
print(f"live_mode guard mevcut  : {live_guard_present}")
