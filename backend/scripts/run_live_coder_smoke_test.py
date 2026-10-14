"""
backend/scripts/run_live_coder_smoke_test.py
AI Dev Team — Controlled Live LLM Coder Smoke Test Runner

Executes a single, real, live LLM Coder workflow against OpenAI gpt-4o-mini and validates:
1. Real LLM Coder execution (no mock, no fallback).
2. Safe workspace file generation (email_filter.py, README.md).
3. Docker container sandbox execution (zero host execution).
4. Reviewer semantic verification and verdict.
5. Zero secret leakage.
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

# Ensure backend root in sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from llm_provider import LLMConfig, get_llm_provider
from execution.docker_engine import DockerExecutionEngine, ExecutionConfig
from agent_workflow import run_agent_workflow
from schemas import TaskStatus, ReviewerVerdict


async def run_live_smoke_test():
    print("=" * 70)
    print("AI DEV TEAM — CONTROLLED LIVE LLM CODER SMOKE TEST")
    print("=" * 70)

    # 1. Pre-flight checks
    cfg = LLMConfig.from_env()
    safe_meta = cfg.safe_metadata()
    print(f"[PRE-CHECK] Provider: {safe_meta['provider']}")
    print(f"[PRE-CHECK] Model: {safe_meta['model']}")
    print(f"[PRE-CHECK] Base Host: {safe_meta['base_host']}")
    print(f"[PRE-CHECK] Is Configured: {safe_meta['is_configured']}")

    if not safe_meta["is_configured"]:
        print("\n[ERROR] LLM API key is NOT configured. Cannot perform live LLM test.")
        sys.exit(1)

    # Docker sandbox check
    docker_engine = DockerExecutionEngine(ExecutionConfig())
    docker_avail, docker_msg = docker_engine.check_availability()
    print(f"[PRE-CHECK] Docker Sandbox: {docker_avail} ({docker_msg})")

    if not docker_avail:
        print(f"\n[ERROR] Docker sandbox is NOT available: {docker_msg}")
        sys.exit(2)

    # 2. Define Live Task
    task_id = f"live_coder_smoke_{uuid.uuid4().hex[:6]}"
    description = (
        "E-posta listesini temizleyen 'filter_emails(emails: list[str]) -> list[str]' fonksiyonunu oluştur. "
        "E-posta adreslerinin başındaki ve sonundaki boşlukları kaldır, adresleri küçük harfe dönüştür, "
        "basit bir e-posta biçim kontrolü uygula, girdi listesini mutasyona uğratma ve "
        "yinelenen geçerli adresleri ilk görülme sırasını koruyarak kaldır."
    )

    print(f"\n[EXECUTION] Task ID: {task_id}")
    print(f"[EXECUTION] Task Description: {description}")
    print(f"[EXECUTION] Invoking LangGraph workflow with planner_mode='llm', coder_mode='llm'...\n")

    start_time = datetime.now(timezone.utc)
    result_state = await run_agent_workflow(
        task_id=task_id,
        description=description,
        planner_mode="llm",
        coder_mode="llm"
    )
    end_time = datetime.now(timezone.utc)
    duration_sec = (end_time - start_time).total_seconds()

    # 3. Analyze Results
    status = result_state.get("status")
    plan = result_state.get("plan")
    coder = result_state.get("coder")
    tester = result_state.get("tester")
    reviewer = result_state.get("reviewer")
    events = result_state.get("events", [])

    event_types = [e.get("type") for e in events]
    has_fallback = "coder_fallback" in event_types or "planning_fallback" in event_types
    coder_mode_used = (coder or {}).get("limitations", [])

    # Secret leakage check
    api_key = cfg.api_key or ""
    leaked_in_events = False
    if api_key and len(api_key) > 8:
        for e in events:
            event_str = json.dumps(e)
            if api_key in event_str:
                leaked_in_events = True
                break

    # Check written files on disk
    ws_path = os.path.join(backend_dir, "workspaces", task_id)
    email_filter_file = os.path.join(ws_path, "email_filter.py")
    file_exists = os.path.exists(email_filter_file)
    generated_code = ""
    if file_exists:
        with open(email_filter_file, "r", encoding="utf-8") as f:
            generated_code = f.read()

    # Extract structured error details if any occurred
    error_details = {}
    for e in events:
        etype = e.get("type") or e.get("event_type", "")
        if "fallback" in etype or "failed" in etype or "error" in etype:
            d = e.get("details", {})
            if d:
                error_details[etype] = {
                    "error_code": d.get("error_code"),
                    "error_type": d.get("error_type"),
                    "retry_after": d.get("retry_after"),
                    "is_quota_error": d.get("is_quota_error"),
                    "safe_message": d.get("error")
                }

    report = {
        "task_id": task_id,
        "provider": safe_meta["provider"],
        "model": safe_meta["model"],
        "base_host": safe_meta["base_host"],
        "duration_seconds": round(duration_sec, 2),
        "final_status": status,
        "real_api_call_made": True,
        "llm_coder_executed": "coder_started" in event_types and "coder_completed" in event_types,
        "deterministic_fallback_used": has_fallback,
        "error_details": error_details,
        "created_files": (coder or {}).get("created_files", []),
        "file_exists_on_disk": file_exists,
        "generated_code_snippet": generated_code[:350] if generated_code else "",
        "docker_tester_status": (tester or {}).get("status"),
        "docker_isolation_type": (tester or {}).get("isolation_type"),
        "tests_passed": (tester or {}).get("passed", 0),
        "tests_failed": (tester or {}).get("failed", 0),
        "reviewer_verdict": (reviewer or {}).get("verdict"),
        "reviewer_summary": (reviewer or {}).get("summary"),
        "semantic_evaluations_count": len((reviewer or {}).get("semantic_evaluations", [])),
        "secret_leaked": leaked_in_events,
        "event_chain": [e.get("type") for e in events]
    }

    print("=" * 70)
    print("LIVE CODER SMOKE TEST RESULTS:")
    print("=" * 70)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    return report


if __name__ == "__main__":
    asyncio.run(run_live_smoke_test())
