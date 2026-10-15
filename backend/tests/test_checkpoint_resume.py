"""
LangGraph SQLite checkpoint interrupt ve aynı thread üzerinden resume testleri.
Ağ çağrısı yapmaz.
"""

import asyncio
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from agent_workflow import (
    inspect_task_checkpoint,
    delete_task_checkpoint,
    resume_agent_workflow,
    run_agent_workflow,
)
from database import get_db_path, init_db
from main import app
from schemas import ReviewerVerdict, TaskStatus


SUPPORTED_TASK = "FastAPI Items CRUD REST API"
_GITHUB_ENV = (
    "GITHUB_TOKEN",
    "GITHUB_OWNER",
    "GITHUB_REPO",
    "GITHUB_REPOSITORY",
    "GITHUB_API_BASE",
    "GITHUB_BASE_BRANCH",
)


@pytest.fixture(autouse=True)
def setup_checkpoint_env(tmp_path, monkeypatch):
    test_db_file = str(tmp_path / "checkpoint_tasks.db")
    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", test_db_file)
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("DEFAULT_PLANNER_MODE", "deterministic")
    monkeypatch.setenv("DEFAULT_CODER_MODE", "deterministic")
    monkeypatch.setenv("RUN_LIVE_LLM_TESTS", "false")
    init_db(test_db_file)
    yield test_db_file


@pytest.fixture
def client():
    return TestClient(app)


def _run(task_id: str, require_human_approval: bool):
    return asyncio.run(run_agent_workflow(
        task_id=task_id,
        description=SUPPORTED_TASK,
        planner_mode="deterministic",
        coder_mode="deterministic",
        require_human_approval=require_human_approval,
    ))


def _counts(nodes):
    return {
        "planner": nodes.count("planner"),
        "coder": nodes.count("coder"),
        "human_gate": nodes.count("human_gate"),
    }


def test_approved_task_interrupts_and_waits():
    result = _run("task_ckpt_wait", True)
    view = asyncio.run(inspect_task_checkpoint("task_ckpt_wait"))

    assert result["status"] == TaskStatus.AWAITING_APPROVAL.value
    assert result["status"] != TaskStatus.COMPLETED.value
    assert result["reviewer"]["verdict"] == ReviewerVerdict.APPROVED.value
    assert view["thread_id"] == "task_ckpt_wait"
    assert view["has_interrupt"] is True
    assert view["next"] == ["human_gate"]
    assert view["interrupts"][0]["value"]["thread_id"] == "task_ckpt_wait"
    assert view["interrupts"][0]["value"]["kind"] == "human_approval"
    assert "human_gate" not in view["executed_nodes"]
    assert _counts(view["executed_nodes"])["planner"] == 1
    assert _counts(view["executed_nodes"])["coder"] == 1


def test_approve_resumes_same_thread_without_replanning():
    _run("task_ckpt_ok", True)
    before = asyncio.run(inspect_task_checkpoint("task_ckpt_ok"))

    resumed = asyncio.run(resume_agent_workflow(
        "task_ckpt_ok",
        {"action": "approve", "approved_by": "lead", "comment": "uygun"},
    ))
    after = asyncio.run(inspect_task_checkpoint("task_ckpt_ok"))

    assert resumed["status"] == TaskStatus.COMPLETED.value
    assert any(event.get("type") == "task_approved" for event in resumed["events"])
    assert _counts(before["executed_nodes"])["planner"] == _counts(resumed["executed_nodes"])["planner"] == 1
    assert _counts(before["executed_nodes"])["coder"] == _counts(resumed["executed_nodes"])["coder"] == 1
    assert _counts(resumed["executed_nodes"])["human_gate"] == 1
    assert after["has_interrupt"] is False
    assert after["thread_id"] == "task_ckpt_ok"


def test_reject_does_not_complete_or_rerun_coder():
    _run("task_ckpt_no", True)
    before = asyncio.run(inspect_task_checkpoint("task_ckpt_no"))
    resumed = asyncio.run(resume_agent_workflow(
        "task_ckpt_no",
        {"action": "reject", "rejected_by": "qa", "reason": "daralt"},
    ))

    assert resumed["status"] == TaskStatus.CHANGES_REQUESTED.value
    assert resumed["status"] != TaskStatus.COMPLETED.value
    assert any(event.get("type") == "task_rejected" for event in resumed["events"])
    assert _counts(resumed["executed_nodes"])["coder"] == _counts(before["executed_nodes"])["coder"] == 1
    assert _counts(resumed["executed_nodes"])["planner"] == 1
    assert "retry" not in resumed["executed_nodes"]


def test_second_approve_does_not_resume_again(client):
    create_res = client.post("/tasks", json={
        "description": SUPPORTED_TASK,
        "require_human_approval": True,
    })
    task_id = create_res.json()["id"]
    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.status_code == 200
    assert run_res.json()["status"] == TaskStatus.AWAITING_APPROVAL.value

    first = client.post(f"/tasks/{task_id}/approve", json={"approved_by": "lead", "comment": "ilk"})
    assert first.status_code == 200
    assert first.json()["status"] == TaskStatus.COMPLETED.value
    approved_events = [event for event in first.json()["events"] if event["type"] == "task_approved"]
    assert len(approved_events) == 1

    second = client.post(f"/tasks/{task_id}/approve", json={"approved_by": "lead", "comment": "ikinci"})
    assert second.status_code == 200
    assert second.json()["status"] == TaskStatus.COMPLETED.value
    assert len([event for event in second.json()["events"] if event["type"] == "task_approved"]) == 1

    view = asyncio.run(inspect_task_checkpoint(task_id))
    assert view["has_interrupt"] is False
    assert _counts(view["executed_nodes"])["human_gate"] == 1
    assert _counts(view["executed_nodes"])["planner"] == 1


def test_missing_checkpoint_does_not_restart(client):
    create_res = client.post("/tasks", json={
        "description": SUPPORTED_TASK,
        "require_human_approval": True,
    })
    task_id = create_res.json()["id"]
    run_res = client.post(f"/tasks/{task_id}/run")
    assert run_res.json()["status"] == TaskStatus.AWAITING_APPROVAL.value
    planner_events = len([event for event in run_res.json()["events"] if event["type"] == "plan_created"])

    delete_task_checkpoint(task_id, get_db_path())
    approve_res = client.post(f"/tasks/{task_id}/approve", json={"approved_by": "lead", "comment": "yok"})
    assert approve_res.status_code == 409
    assert "baştan" in approve_res.json()["detail"]

    fetched = client.get(f"/tasks/{task_id}")
    assert fetched.json()["status"] == TaskStatus.AWAITING_APPROVAL.value
    assert len([event for event in fetched.json()["events"] if event["type"] == "plan_created"]) == planner_events
    assert not any(event["type"] == "task_approved" for event in fetched.json()["events"])


def test_new_process_resumes_same_checkpoint(tmp_path):
    db_path = get_db_path()
    _run("task_ckpt_restart", True)
    script = tmp_path / "resume_checkpoint.py"
    script.write_text(
        "import asyncio, os, sys\n"
        "os.environ['AI_DEV_TEAM_DB_PATH'] = sys.argv[1]\n"
        "os.environ['LLM_PROVIDER'] = 'mock'\n"
        "os.environ['DEFAULT_PLANNER_MODE'] = 'deterministic'\n"
        "os.environ['DEFAULT_CODER_MODE'] = 'deterministic'\n"
        "os.environ['EXECUTION_ENGINE'] = 'mock'\n"
        "os.environ['AI_DEV_TEAM_ALLOW_MOCK_ENGINE'] = '1'\n"
        "os.environ['RUN_LIVE_LLM_TESTS'] = 'false'\n"
        "for _name in ('GITHUB_TOKEN', 'GITHUB_OWNER', 'GITHUB_REPO', "
        "'GITHUB_REPOSITORY', 'GITHUB_API_BASE', 'GITHUB_BASE_BRANCH'):\n"
        "    os.environ[_name] = ''\n"
        "from agent_workflow import inspect_task_checkpoint, resume_agent_workflow\n"
        "async def main():\n"
        "    task_id = sys.argv[2]\n"
        "    view = await inspect_task_checkpoint(task_id)\n"
        "    assert view['thread_id'] == task_id\n"
        "    assert view['has_interrupt'] is True\n"
        "    planners = view['executed_nodes'].count('planner')\n"
        "    coders = view['executed_nodes'].count('coder')\n"
        "    result = await resume_agent_workflow(task_id, {'action': 'approve', 'approved_by': 'restart', 'comment': 'yeniden'})\n"
        "    assert result['status'] == 'completed'\n"
        "    assert result['executed_nodes'].count('planner') == planners == 1\n"
        "    assert result['executed_nodes'].count('coder') == coders == 1\n"
        "asyncio.run(main())\n",
        encoding="utf-8",
    )
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = backend_dir
    child_env["AI_DEV_TEAM_DB_PATH"] = db_path
    child_env["LLM_PROVIDER"] = "mock"
    child_env["DEFAULT_PLANNER_MODE"] = "deterministic"
    child_env["DEFAULT_CODER_MODE"] = "deterministic"
    child_env["EXECUTION_ENGINE"] = "mock"
    child_env["AI_DEV_TEAM_ALLOW_MOCK_ENGINE"] = "1"
    child_env["RUN_LIVE_LLM_TESTS"] = "false"
    for name in _GITHUB_ENV:
        child_env[name] = ""
    completed = subprocess.run(
        [sys.executable, str(script), db_path, "task_ckpt_restart"],
        cwd=backend_dir,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_without_human_approval_does_not_interrupt():
    result = _run("task_ckpt_auto", False)
    view = asyncio.run(inspect_task_checkpoint("task_ckpt_auto"))
    assert result["status"] == TaskStatus.REVIEWED.value
    assert result["reviewer"]["verdict"] == ReviewerVerdict.APPROVED.value
    assert view["has_interrupt"] is False
    assert "human_gate" not in view["executed_nodes"]


def test_run_while_waiting_does_not_restart(client):
    create_res = client.post("/tasks", json={
        "description": SUPPORTED_TASK,
        "require_human_approval": True,
    })
    task_id = create_res.json()["id"]
    assert client.post(f"/tasks/{task_id}/run").json()["status"] == TaskStatus.AWAITING_APPROVAL.value
    again = client.post(f"/tasks/{task_id}/run")
    assert again.status_code == 409
    assert client.get(f"/tasks/{task_id}").json()["status"] == TaskStatus.AWAITING_APPROVAL.value
    runs = client.get(f"/tasks/{task_id}/runs")
    assert runs.json()["total_runs"] == 1
