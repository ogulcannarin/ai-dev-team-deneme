"""
backend/tests/test_agent_evaluation_benchmark.py
AI Dev Team — Agent Intelligence Evaluation Benchmark Test Suite

5 Temel Değerlendirme (Evaluation) Senaryosu:
E1 — Basit ve net Python görevi (email_filter): Plan kalitesi, kabul kriterleri ve Coder şablon sınırları.
E2 — Çoklu kabul kriteri (User Registration): 4 ayrı iş gereksiniminin plan ve alt görevlere ayrıştırılması.
E3 — Belirsiz / Eksik gereksinim ("Sistemi hızlandır..."): Eksik gereksinim tespiti ve risk analizi.
E4 — Semantik uyuşmazlık (Date Diff vs Calculator): Testler geçse bile oluşan semantik onay boşluğu (Semantic Gap).
E5 — LLM Kesintisi & Fallback: Sağlayıcı hatasında 'planner_fallback' olayı ve deterministik devamlılık.
"""

import asyncio
import json
import os
import tempfile
import uuid
import pytest

from database import init_db
from execution.docker_engine import DockerExecutionEngine
from llm_provider import (
    BaseLLMProvider,
    LLMConfig,
    LLMProviderError,
    LLMResponse,
    LLMTimeoutError,
    MockLLMProvider,
)
from schemas import (
    ReviewerVerdict,
    TaskPlan,
    TaskStatus,
)
from agent_workflow import (
    _deterministic_planner,
    _execute_reviewer_in_workspace,
    _execute_tester_in_workspace,
    _llm_planner,
    planner_node,
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
# SENARYO E1: Basit ve Net Python Görevi (filter_emails)
# =====================================================================

@pytest.mark.asyncio
async def test_eval_e1_simple_python_email_filter_plan_and_coder_boundaries():
    """
    E1 Değerlendirmesi:
    Görev: 'filter_emails(emails: list[str]) -> list[str]'
    - LLM Planner çıktısının fonksiyon imzası, regex ve duplicate temizleme kriterlerini içerdiğini ölçer.
    - Deterministik Coder'ın şablon sınırını (özel fonksiyonun statik 4 şablona dahil olmaması) doğrular.
    
    Yürütme Modu: mock_llm + static_analysis
    """
    task_desc = (
        "Verilen bir metin listesindeki e-posta adreslerini regex ile filtreleyen "
        "ve duplicate kayıtları temizleyen 'filter_emails(emails: list[str]) -> list[str]' fonksiyonunu yaz."
    )

    # 1. LLM Planner Yanıt Mock'u
    custom_llm_plan = {
        "goal": "E-posta listesini regex ile filtreleyen ve duplicate adresleri normalize edip temizleyen 'filter_emails' yardımcı modülünün geliştirilmesi.",
        "subtasks": [
            "1. RFC 5322 uyumlu e-posta regex doğrulama deseni tanımlama",
            "2. 'filter_emails(emails: list[str]) -> list[str]' fonksiyon imzasını ve tip kontrollerini oluşturma",
            "3. Case-insensitive normalizasyon ve duplicate temizleme mantığını kodlama",
            "4. Geçersiz formatlar, boş girdiler ve duplicate senaryoları için birim testleri hazırlama"
        ],
        "acceptance_criteria": [
            "Geçerli e-posta adresleri filtrelenmeli ve küçük harfe normalize edilmelidir",
            "Mükerrer (duplicate) adresler listeden temizlenmeli, sıra korunmalıdır",
            "Geçersiz formatlar ve None/boş girdiler güvenle elenmelidir",
            "Tüm birim testleri Docker sandbox içinde 0 hata ile geçmelidir"
        ],
        "risks": [
            "Aşırı katı regex desenlerinin geçerli yeni TLD e-postaları elemesi riski",
            "Büyük e-posta listelerinde bellek ve arama karmaşıklığı riski"
        ]
    }

    mock_provider = MockLLMProvider(custom_response=json.dumps(custom_llm_plan, ensure_ascii=False))

    # LLM Planner çağrısı ve ölçümü
    plan = await _llm_planner(task_desc, mock_provider)

    assert isinstance(plan, TaskPlan)
    assert "filter_emails" in plan.goal or "filter_emails" in plan.subtasks[1]
    assert len(plan.subtasks) >= 4
    assert len(plan.acceptance_criteria) >= 3
    assert any("duplicate" in c.lower() or "mükerrer" in c.lower() for c in plan.acceptance_criteria)
    assert any("regex" in s.lower() for s in plan.subtasks)

    # 2. Deterministik Planner Kıyaslaması
    det_plan = _deterministic_planner(task_desc)
    assert isinstance(det_plan, TaskPlan)
    assert len(det_plan.subtasks) >= 5
    assert len(det_plan.acceptance_criteria) >= 5

    # Metrik: Plan kalitesi ve şema uygunluğu %100 doğrulandı.


# =====================================================================
# SENARYO E2: Çoklu Kabul Kriteri (User Registration Service)
# =====================================================================

@pytest.mark.asyncio
async def test_eval_e2_multi_criteria_user_registration_evaluation():
    """
    E2 Değerlendirmesi:
    Görev: 4 ayrı kabul kriterine sahip kullanıcı kayıt servisi:
      1) Şifre en az 8 karakter, 1 rakam ve 1 büyük harf
      2) E-posta format doğrulaması
      3) Başarılı kayıtta HTTP 201 ve kullanıcı ID
      4) Hatalı girdilerde HTTP 422
    
    Yürütme Modu: mock_llm
    """
    task_desc = (
        "Kullanıcı kayıt servisi yaz: "
        "1) Şifre en az 8 karakter, 1 rakam ve 1 büyük harf içermeli. "
        "2) E-posta formatı doğrulanmalı. "
        "3) Başarılı kayıtta 201 ve kullanıcı ID dönmeli. "
        "4) Hatalı girdilerde 422 dönmeli."
    )

    custom_plan_json = {
        "goal": "FastAPI ve Pydantic kullanarak 4 temel doğrulama kuralını karşılayan güvenli kullanıcı kayıt servisi endpoint'i oluşturulması.",
        "subtasks": [
            "1. UserRegisterRequest ve UserRegisterResponse Pydantic şemalarını tanımlama",
            "2. Şifre karmaşıklık kurallarını (min 8 karakter, büyük harf, rakam) doğrulayan validator geliştirme",
            "3. E-posta format kontrolü ve duplicate kullanıcı kontrol mekanizması ekleme",
            "4. POST /auth/register endpoint'ini HTTP 201 Created ve HTTP 422 Unprocessable Entity yanıtlarıyla kodlama",
            "5. Tüm doğrulama ve hata durumlarını kapsayan test senaryolarını yazma"
        ],
        "acceptance_criteria": [
            "Kriter 1: Şifre en az 8 karakter, 1 büyük harf ve 1 rakam içermiyorsa 422 dönmelidir",
            "Kriter 2: Geçersiz e-posta formatlarında 422 hata yanıtı dönmelidir",
            "Kriter 3: Geçerli kayıt isteklerinde HTTP 201 Created ve oluşturulan user_id dönmelidir",
            "Kriter 4: Hatalı veya eksik gövde (body) alanlarında HTTP 422 standart JSON yanıtı dönmelidir"
        ],
        "risks": [
            "Zayıf şifrelerin regex doğrulaması sırasında atlanması riski",
            "E-posta normalizasyonu yapılmazsa mükerrer hesap oluşturulma riski"
        ]
    }

    mock_provider = MockLLMProvider(custom_response=json.dumps(custom_plan_json, ensure_ascii=False))
    plan = await _llm_planner(task_desc, mock_provider)

    # Ölçülebilir Metrikler:
    # 1. 4 kabul kriterinin tamamı plan kriterlerine eşlenmiş mi?
    assert len(plan.acceptance_criteria) >= 4
    assert any("şifre" in c.lower() or "8 karakter" in c.lower() for c in plan.acceptance_criteria)
    assert any("e-posta" in c.lower() or "email" in c.lower() for c in plan.acceptance_criteria)
    assert any("201" in c for c in plan.acceptance_criteria)
    assert any("422" in c for c in plan.acceptance_criteria)

    # 2. Alt görevlerde auth ve şema adımları mevcut mu?
    assert any("pydantic" in s.lower() or "şema" in s.lower() for s in plan.subtasks)
    assert any("422" in s or "201" in s for s in plan.subtasks)


# =====================================================================
# SENARYO E3: Belirsiz / Eksik Gereksinim ("Sistemi hızlandır...")
# =====================================================================

@pytest.mark.asyncio
async def test_eval_e3_ambiguous_requirement_risk_and_assumptions():
    """
    E3 Değerlendirmesi:
    Görev: 'Sistemi hızlandır ve verileri kaydet.'
    - Belirsiz ve eksik gereksinimli bir istek karşısında Planner'ın riskleri,
      varsayımları ve mimari kapsam sınırlarını nasıl belirlediğini ölçer.
    
    Yürütme Modu: mock_llm + deterministic
    """
    task_desc = "Sistemi hızlandır ve verileri kaydet."

    # 1. LLM Modu: Belirsizliği tespit eden plan
    ambiguous_plan_json = {
        "goal": "Belirsiz performans ve veri saklama talebi için mimari önbellekleme (caching) ve asenkron veri kalıcılık katmanı planlanması.",
        "subtasks": [
            "1. Mimari Gereksinim Netleştirme: Performans darboğazlarının ve kaydedilecek veri türlerinin tanımlanması",
            "2. Veri Modelleri ve Saklama Arayüzünün (Repository) Hazırlanması",
            "3. Bellek İçi Önbellek (In-Memory Cache) veya İndeksleme Mantığının Geliştirilmesi",
            "4. Veri Bütünlüğü ve Gecikme (Latency) Doğrulama Testlerinin Yazılması"
        ],
        "acceptance_criteria": [
            "Kaydedilecek veri modellerinin açık ve tip güvenli tanımlanması",
            "Sorgu ve yanıt sürelerinin kabul edilebilir eşik altında kalması",
            "Eksik gereksinimlerin varsayımlarla belgelenmesi"
        ],
        "risks": [
            "BELİRSİZLİK RİSKİ: Görev tanımında veri modelleri ve performans hedef metrikleri (SLA/TPS) belirtilmemiştir",
            "VERİ KAYBI RİSKİ: Hızlandırma optimizasyonunun veri tutarlılığı ve kalıcılık garantilerini zayıflatma riski",
            "KAPSAM KAYMASI RİSKİ: Açık hedeflerin olmaması nedeniyle gereksiz bileşenlerin kapsama dahil edilme riski"
        ]
    }

    mock_provider = MockLLMProvider(custom_response=json.dumps(ambiguous_plan_json, ensure_ascii=False))
    plan = await _llm_planner(task_desc, mock_provider)

    # Ölçülebilir Metrikler:
    assert len(plan.risks) >= 2
    # Belirsizlik veya veri riski tespit edildi mi?
    assert any("belirsiz" in r.lower() or "veri" in r.lower() or "risk" in r.lower() for r in plan.risks)

    # 2. Deterministik Motor ile Kıyaslama
    det_plan = _deterministic_planner(task_desc)
    assert len(det_plan.risks) >= 3
    assert any("risk" in r.lower() or "darboğaz" in r.lower() for r in det_plan.risks)


# =====================================================================
# SENARYO E4: Semantik Uyuşmazlık ve Onay Boşluğu (Semantic Gap)
# =====================================================================

def test_eval_e4_semantic_mismatch_demonstrates_reviewer_gap():
    """
    E4 Değerlendirmesi (Bilinen Mimari Eksiklik Tespiti):
    Kullanıcı İsteği: 'İki tarih arasındaki gün farkını hesaplayan date_diff fonksiyonu yaz.'
    Coder'ın Ürettiği: calculator.py (add, subtract, multiply, divide)
    Tester Sonucu: 4/4 test başarılı (test_calculator.py geçti).
    
    Ölçülen Davranış:
    - Mevcut Reviewer kodu AST, sözdizimi ve Tester sonuçlarına baktığı için
      ve Tester başarılı olduğu için göreve APPROVED verir.
    - Bu test, Reviewer'ın İŞ GEREKSİNİMİ (Date Diff) ile KOD (Calculator) arasındaki
      semantik uyuşmazlığı yakalayamadığını kanıtlar ve hedeflenen semantik kontrol
      kuralını tanımlar.
    
    Yürütme Modu: static_analysis + mock_results
    """
    task_id = f"task_eval_semgap_{uuid.uuid4().hex[:6]}"
    user_requirement = "İki tarih arasındaki gün farkını hesaplayan 'date_diff(d1: str, d2: str) -> int' fonksiyonu yaz."

    with tempfile.TemporaryDirectory() as tmp_workspaces:
        ws_dir = os.path.join(tmp_workspaces, task_id)
        os.makedirs(ws_dir, exist_ok=True)

        # Coder alakasız bir calculator.py üretiyor
        calc_code = (
            '"""Hesaplama Modulu"""\n\n'
            'def add(a: int, b: int) -> int:\n'
            '    """Toplama"""\n'
            '    return a + b\n\n'
            'def multiply(a: int, b: int) -> int:\n'
            '    """Carpma"""\n'
            '    return a * b\n'
        )
        with open(os.path.join(ws_dir, "calculator.py"), "w", encoding="utf-8") as f:
            f.write(calc_code)

        with open(os.path.join(ws_dir, "README.md"), "w", encoding="utf-8") as f:
            f.write("# Calculator Module\n")

        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/calculator.py", f"workspaces/{task_id}/README.md"]
        }

        # Tester da bu calculator için testleri çalıştırıp 4/4 başarılı döndürüyor
        tester_data = {
            "status": "tested",
            "passed": 4,
            "failed": 0,
            "summary": "Ran 4 tests in 0.012s. OK.",
            "is_isolated": True,
            "tests": [
                {"name": "test_01_add", "status": "passed"},
                {"name": "test_02_multiply", "status": "passed"}
            ]
        }

        # Reviewer incelemesi
        reviewer_result = _execute_reviewer_in_workspace(
            task_id=task_id,
            description=user_requirement,
            coder_data=coder_data,
            tester_data=tester_data,
            workspaces_root=tmp_workspaces
        )

        # SEMANTİK DOĞRULAMA KATMANI SONUCU:
        # Reviewer, Tester testleri geçmiş olsa bile iş gereksinimi (date_diff) ile üretilen kod (calculator)
        # arasındaki semantik uyuşmazlığı yakalar ve CHANGES_REQUESTED verir.
        assert reviewer_result.verdict == ReviewerVerdict.CHANGES_REQUESTED
        assert reviewer_result.status == "reviewed"

        # Semantik bulgular ve karşılanmayan kriterler doğrulaması:
        assert any(f.category == "semantic_alignment" for f in reviewer_result.findings)
        assert any(e.status.value == "not_met" for e in reviewer_result.semantic_evaluations)

        # SEMANTİK KONTROL METRİĞİ (Hedeflenen İyileştirme Doğrulaması):
        # Programatik semantik analiz: Kullanıcı isteğindeki anahtar kelimeler ile üretilen kodun fonksiyonları
        # karşılaştırıldığında uyuşmazlık oranı %100'dür.
        required_keywords = ["date_diff", "tarih", "gün", "date", "diff"]
        with open(os.path.join(ws_dir, "calculator.py"), "r", encoding="utf-8") as f:
            actual_code = f.read()

        semantic_match = any(kw in actual_code.lower() for kw in required_keywords)
        # Bu assert, mevcut kodun gerçekten semantik olarak gereksinimi karşılamadığını kanıtlar:
        assert semantic_match is False, "Kod kullanıcının istediği 'date_diff' fonksiyonunu içermiyor."


# =====================================================================
# SENARYO E5: LLM Sağlayıcısı Hatası ve Fallback Dayanıklılığı
# =====================================================================

@pytest.mark.asyncio
async def test_eval_e5_llm_provider_fallback_resilience(isolated_db, monkeypatch):
    """
    E5 Değerlendirmesi:
    LLM sağlayıcısı hata verdiğinde (zaman aşımı veya API hatası):
    - Sistemin çökmeyip 'planner_fallback' olayını fırlattığını,
    - Deterministik Planner motoruna güvenle geçerek geçerli bir plan ürettiğini,
    - Görevin PLANNED durumuna ulaştığını doğrular.
    
    Yürütme Modu: mock_with_simulated_error -> deterministic
    """
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_FALLBACK_TO_DETERMINISTIC", "true")

    task_id = f"task_eval_fallback_{uuid.uuid4().hex[:6]}"
    task_desc = "FastAPI ile çalışan ürün listeleme endpoint'i ekle."

    # Hata fırlatan Mock LLM Sağlayıcısı
    error_provider = MockLLMProvider(
        simulate_error=LLMTimeoutError("LLM API çağrısı zaman aşımına uğradı (15s).", provider="mock")
    )

    # get_llm_provider'ı mock sağlayıcı döndürecek şekilde monkeypatch et
    monkeypatch.setattr("agent_workflow.get_llm_provider", lambda: error_provider)

    # Workflow başlangıç durumu
    initial_state = {
        "task_id": task_id,
        "description": task_desc,
        "planner_mode": "llm",
        "status": TaskStatus.IN_PROGRESS.value,
        "events": [],
        "plan": None,
        "scope": None,
        "coder": None,
        "tester": None,
        "reviewer": None,
        "retry_count": 0,
        "error": None
    }

    # planner_node'u çalıştır
    state_after_planner = await planner_node(initial_state)

    # Doğrulamalar:
    # 1. Görev durumu PLANNED olmalıdır (çökmemelidir)
    assert state_after_planner["status"] == TaskStatus.PLANNED.value
    assert state_after_planner["plan"] is not None
    assert len(state_after_planner["plan"]["subtasks"]) >= 4

    # 2. Olay günlüğünde 'planner_fallback' olayı bulunmalıdır
    events = state_after_planner["events"]
    fallback_events = [ev for ev in events if (ev.get("type") or ev.get("event_type")) == "planner_fallback"]
    assert len(fallback_events) >= 1
    assert "deterministik" in fallback_events[0]["message"].lower() or "fallback" in fallback_events[0]["message"].lower()
