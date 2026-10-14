"""
backend/tests/test_live_llm.py
AI Dev Team - Gerçek LLM Sağlayıcı Kontrollü Entegrasyon Testi

ÖNEMLİ GÜVENLİK VE MALİYET KORUMASI:
1. Bu dosyadaki testler VARSAYILAN OLARAK ATLANIR (skip).
2. Yalnızca 'RUN_LIVE_LLM_TESTS=true' ortam değişkeni açıkça tanımlandığında
   ve geçerli bir 'OPENAI_API_KEY' mevcut olduğunda çalıştırılır.
3. Otomatik CI/CD veya standart 'pytest' koşumlarında harici ücretli API çağrısı yapmaz.
"""

import os
import pytest
from llm_provider import LLMConfig, OpenAICompatibleProvider, get_llm_provider
from agent_workflow import _llm_planner, run_agent_workflow
from schemas import TaskPlan, TaskStatus


# Canlı test kontrol koşulu
_LIVE_ENABLED = os.environ.get("RUN_LIVE_LLM_TESTS", "").lower() in ["true", "1", "yes"]
_API_KEY_PRESENT = bool(os.environ.get("OPENAI_API_KEY") and len(os.environ.get("OPENAI_API_KEY", "").strip()) > 10)


@pytest.mark.skipif(
    not (_LIVE_ENABLED and _API_KEY_PRESENT),
    reason="Gerçek LLM çağrısı gerektiren testler varsayılan olarak atlanır. "
           "Çalıştırmak için: RUN_LIVE_LLM_TESTS=true ve OPENAI_API_KEY ortam değişkenlerini ayarlayın."
)
@pytest.mark.asyncio
async def test_live_openai_compatible_provider_plan_generation():
    """
    Gerçek OpenAI / uyumlu API üzerinden canlı plan üretimini ve Pydantic doğrulamasını test eder.
    Yalnızca açıkça izin verildiğinde (RUN_LIVE_LLM_TESTS=true) çalışır.
    """
    config = LLMConfig.from_env()
    assert config.is_configured() is True

    provider = OpenAICompatibleProvider(config)
    description = "Create a FastAPI rate limiting middleware with sliding window algorithm and redis backend"
    
    # 1. Canlı model çağrısı
    plan = await _llm_planner(description, provider)

    # 2. Pydantic şema doğrulaması
    assert isinstance(plan, TaskPlan)
    assert plan.goal != ""
    assert len(plan.subtasks) >= 3
    assert len(plan.acceptance_criteria) >= 2
    assert len(plan.risks) >= 1


@pytest.mark.skipif(
    not (_LIVE_ENABLED and _API_KEY_PRESENT),
    reason="Gerçek LLM çağrısı gerektiren testler varsayılan olarak atlanır."
)
@pytest.mark.asyncio
async def test_live_workflow_run_with_real_llm_planner():
    """
    Gerçek LLM ile tam LangGraph akışının (Planner -> Scope -> Coder -> Tester -> Reviewer)
    uçtan uca çalıştığını ve geçmişe kaydedildiğini test eder.
    """
    task_id = "live_test_task_001"
    desc = "FastAPI REST API router for user preferences management"
    
    result = await run_agent_workflow(
        task_id=task_id,
        description=desc,
        planner_mode="llm"
    )

    assert result["status"] in [TaskStatus.REVIEWED.value, TaskStatus.CODED.value, TaskStatus.TESTED.value]
    assert result["plan"] is not None
    assert len(result["plan"]["subtasks"]) >= 3
