"""
İnsan onayı kapısının LangGraph durumuna bağlandığını doğrular.
Ağ çağrısı yapmaz. Reviewer approved dışındaki kararları approved yapmaz.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from agent_workflow import _route_after_reviewer, reviewer_node, run_agent_workflow
from database import init_db
from main import app
from schemas import ReviewerResult, ReviewerVerdict, TaskStatus


SUPPORTED_TASK = "FastAPI Items CRUD REST API"


@pytest.fixture(autouse=True)
def setup_hitl_env(tmp_path, monkeypatch):
    test_db_file = str(tmp_path / "test_hitl.db")
    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", test_db_file)
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("DEFAULT_PLANNER_MODE", "deterministic")
    monkeypatch.setenv("DEFAULT_CODER_MODE", "deterministic")
    monkeypatch.setenv("RUN_LIVE_LLM_TESTS", "false")
    init_db(test_db_file)
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _reviewer_result(verdict: ReviewerVerdict, status: str) -> ReviewerResult:
    return ReviewerResult(
        status=status,
        verdict=verdict,
        findings=[],
        summary=f"test verdict {verdict.value}",
        reviewed_files=["models.py"],
        error=None,
    )


def _coded_state(**overrides):
    state = {
        "task_id": "task_hitl_node",
        "description": SUPPORTED_TASK,
        "status": TaskStatus.TESTED.value,
        "coder": {"status": "coded", "created_files": ["models.py"]},
        "tester": {"status": "tested", "passed": 2, "failed": 0, "test_results": []},
        "events": [],
        "retry_count": 0,
        "max_retries": 2,
        "require_human_approval": False,
    }
    state.update(overrides)
    return state


def _run(description: str, **kwargs):
    return asyncio.run(run_agent_workflow(
        task_id=kwargs.pop("task_id", "task_hitl_flow"),
        description=description,
        planner_mode="deterministic",
        coder_mode="deterministic",
        **kwargs,
    ))


def test_reviewer_approved_with_human_approval_waits():
    result = _run(SUPPORTED_TASK, task_id="task_hitl_wait", require_human_approval=True)

    assert result["reviewer"]["verdict"] == ReviewerVerdict.APPROVED.value
    assert result["status"] == TaskStatus.AWAITING_APPROVAL.value
    assert result["status"] != TaskStatus.COMPLETED.value
    assert any(event.get("type") == "awaiting_human_approval" for event in result["events"])
    assert not any(event.get("type") == "task_approved" for event in result["events"])
    assert _route_after_reviewer(result) == "human_gate"


def test_reviewer_approved_without_human_approval_stays_reviewed():
    result = _run(SUPPORTED_TASK, task_id="task_hitl_auto", require_human_approval=False)

    assert result["reviewer"]["verdict"] == ReviewerVerdict.APPROVED.value
    assert result["status"] == TaskStatus.REVIEWED.value
    assert result["status"] != TaskStatus.AWAITING_APPROVAL.value
    assert result["status"] != TaskStatus.COMPLETED.value
    assert not any(event.get("type") == "awaiting_human_approval" for event in result["events"])


def test_changes_requested_still_retries_when_approval_required(monkeypatch):
    """Değişiklik talebi retry başlatır. Aynı deterministik şablon onay veya insan kapısına taşınmaz."""
    calls = {"n": 0}

    def fake_reviewer(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _reviewer_result(ReviewerVerdict.CHANGES_REQUESTED, "reviewed")
        return _reviewer_result(ReviewerVerdict.APPROVED, "reviewed")

    monkeypatch.setattr("agent_workflow._execute_reviewer_in_workspace", fake_reviewer)

    result = _run(
        SUPPORTED_TASK,
        task_id="task_hitl_retry",
        require_human_approval=True,
        max_retries=1,
    )

    assert calls["n"] == 1
    assert any(event.get("type") == "retry_triggered" for event in result["events"])
    assert result["status"] == TaskStatus.FAILED.value
    assert "deterministik şablon" in (result.get("error") or "")
    assert result["reviewer"]["verdict"] == ReviewerVerdict.CHANGES_REQUESTED.value
    assert result["status"] != TaskStatus.AWAITING_APPROVAL.value
    assert result["status"] != TaskStatus.COMPLETED.value


def test_changes_requested_is_not_promoted_to_approval(monkeypatch):
    monkeypatch.setattr(
        "agent_workflow._execute_reviewer_in_workspace",
        lambda *_args, **_kwargs: _reviewer_result(ReviewerVerdict.CHANGES_REQUESTED, "reviewed"),
    )

    node_result = reviewer_node(_coded_state(require_human_approval=True))
    assert node_result["status"] == TaskStatus.REVIEWED.value
    assert node_result["reviewer"]["verdict"] == ReviewerVerdict.CHANGES_REQUESTED.value
    assert _route_after_reviewer(node_result) == "retry"

    exhausted = _route_after_reviewer({**node_result, "retry_count": 2, "max_retries": 2})
    assert exhausted == "end"
    assert node_result["status"] != TaskStatus.AWAITING_APPROVAL.value
    assert node_result["status"] != TaskStatus.COMPLETED.value


def test_blocked_review_stays_blocked_when_approval_required(monkeypatch):
    monkeypatch.setattr(
        "agent_workflow._execute_reviewer_in_workspace",
        lambda *_args, **_kwargs: _reviewer_result(ReviewerVerdict.BLOCKED, "blocked"),
    )

    result = _run(
        SUPPORTED_TASK,
        task_id="task_hitl_blocked",
        require_human_approval=True,
        max_retries=2,
    )

    assert result["reviewer"]["verdict"] == ReviewerVerdict.BLOCKED.value
    assert result["status"] == TaskStatus.BLOCKED.value
    assert result.get("retry_count", 0) == 0
    assert not any(event.get("type") == "retry_triggered" for event in result["events"])
    assert result["status"] != TaskStatus.AWAITING_APPROVAL.value
    assert result["status"] != TaskStatus.COMPLETED.value
    assert _route_after_reviewer(result) == "end"


def test_api_awaiting_approval_is_not_completed_until_approve(client):
    create_res = client.post("/tasks", json={
        "description": SUPPORTED_TASK,
        "require_human_approval": True,
    })
    assert create_res.status_code == 201
    task_id = create_res.json()["id"]

    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200
    assert run_res.json()["status"] == TaskStatus.AWAITING_APPROVAL.value
    assert run_res.json()["reviewer"]["verdict"] == ReviewerVerdict.APPROVED.value

    fetched = client.get(f"/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == TaskStatus.AWAITING_APPROVAL.value
    assert fetched.json()["status"] != TaskStatus.COMPLETED.value

    approve_res = client.post(
        f"/tasks/{task_id}/approve",
        json={"comment": "İnsan onayı verildi.", "approved_by": "lead_architect"},
    )
    assert approve_res.status_code == 200
    approved = approve_res.json()
    assert approved["status"] == TaskStatus.COMPLETED.value
    assert approved["reviewer"]["verdict"] == ReviewerVerdict.APPROVED.value
    assert approved["plan"] is not None
    approval_event = next(event for event in approved["events"] if event["type"] == "task_approved")
    assert approval_event["details"]["approved_by"] == "lead_architect"
    assert approval_event["source"] == "HUMAN_REVIEWER"

    runs = client.get(f"/tasks/{task_id}/runs")
    assert runs.status_code == 200
    assert runs.json()["total_runs"] == 1


def test_api_reject_awaiting_task_does_not_rerun(client):
    create_res = client.post("/tasks", json={"description": SUPPORTED_TASK})
    task_id = create_res.json()["id"]

    run_res = client.post(f"/tasks/{task_id}/run?require_human_approval=true")
    assert run_res.status_code == 200
    assert run_res.json()["status"] == TaskStatus.AWAITING_APPROVAL.value

    reject_res = client.post(
        f"/tasks/{task_id}/reject",
        json={"reason": "Kapsam daraltılmalı.", "rejected_by": "qa_lead"},
    )
    assert reject_res.status_code == 200
    rejected = reject_res.json()
    assert rejected["status"] == TaskStatus.CHANGES_REQUESTED.value
    assert rejected["status"] != TaskStatus.COMPLETED.value
    assert rejected["reviewer"]["verdict"] == ReviewerVerdict.APPROVED.value
    assert rejected["plan"] is not None
    reject_event = next(event for event in rejected["events"] if event["type"] == "task_rejected")
    assert reject_event["details"]["rejected_by"] == "qa_lead"
    assert reject_event["details"]["reason"] == "Kapsam daraltılmalı."

    runs = client.get(f"/tasks/{task_id}/runs")
    assert runs.json()["total_runs"] == 1
    assert client.get(f"/tasks/{task_id}").json()["status"] == TaskStatus.CHANGES_REQUESTED.value


def test_api_without_flag_keeps_reviewed_completion(client):
    create_res = client.post("/tasks", json={"description": SUPPORTED_TASK})
    task_id = create_res.json()["id"]

    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200
    body = run_res.json()
    assert body["status"] == TaskStatus.REVIEWED.value
    assert body["reviewer"]["verdict"] == ReviewerVerdict.APPROVED.value
    assert body["status"] != TaskStatus.COMPLETED.value
    assert body["status"] != TaskStatus.AWAITING_APPROVAL.value
