"""
İnsan kararı yalnızca geçerli durumlarda uygulanır.
Ağ çağrısı yapmaz. LLM_PROVIDER=mock ve EXECUTION_ENGINE=mock kullanır.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from database import init_db
from main import app
from repository import TaskRepository
from schemas import TaskStatus


SUPPORTED_TASK = "FastAPI Items CRUD REST API"


@pytest.fixture(autouse=True)
def setup_status_safety_env(tmp_path, monkeypatch):
    test_db_file = str(tmp_path / "approval_status.db")
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


def _event_count(task: dict, event_type: str) -> int:
    return sum(1 for event in task.get("events") or [] if event.get("type") == event_type)


def _create(client: TestClient, **extra) -> dict:
    payload = {"description": SUPPORTED_TASK, "planner_mode": "deterministic", "coder_mode": "deterministic"}
    payload.update(extra)
    response = client.post("/tasks", json=payload)
    assert response.status_code == 201
    return response.json()


def _set_status(task_id: str, status: TaskStatus, error: str | None = None) -> None:
    TaskRepository().update_task_workflow_result(task_id=task_id, status=status, error=error)


def test_create_request_stores_human_approval_flag_and_run_waits(client):
    created = _create(client, require_human_approval=True)
    created_flag = next(event for event in created["events"] if event["type"] == "task_created")
    assert created_flag["details"]["require_human_approval"] is True

    ran = client.post(f"/tasks/{created['id']}/run")
    assert ran.status_code == 200
    body = ran.json()
    assert body["status"] == TaskStatus.AWAITING_APPROVAL.value
    assert body["status"] != TaskStatus.COMPLETED.value
    assert body["reviewer"]["verdict"] == "approved"


def test_omitted_flag_keeps_reviewed_finish(client):
    created = _create(client)
    created_flag = next(event for event in created["events"] if event["type"] == "task_created")
    assert "require_human_approval" not in (created_flag.get("details") or {})

    ran = client.post(f"/tasks/{created['id']}/run")
    assert ran.status_code == 200
    assert ran.json()["status"] == TaskStatus.REVIEWED.value


def test_explicit_false_flag_keeps_reviewed_finish(client):
    created = _create(client, require_human_approval=False)
    ran = client.post(f"/tasks/{created['id']}/run")
    assert ran.status_code == 200
    assert ran.json()["status"] == TaskStatus.REVIEWED.value


def test_reviewed_approve_and_reject_contract_unchanged(client):
    approved_task = _create(client)
    client.post(f"/tasks/{approved_task['id']}/run")
    approved = client.post(
        f"/tasks/{approved_task['id']}/approve",
        json={"approved_by": "lead", "comment": "uygun"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == TaskStatus.COMPLETED.value
    assert _event_count(approved.json(), "task_approved") == 1

    rejected_task = _create(client)
    client.post(f"/tasks/{rejected_task['id']}/run")
    rejected = client.post(
        f"/tasks/{rejected_task['id']}/reject",
        json={"rejected_by": "qa", "reason": "daralt"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == TaskStatus.CHANGES_REQUESTED.value
    assert _event_count(rejected.json(), "task_rejected") == 1


def test_queued_task_cannot_be_approved_or_rejected(client):
    created = _create(client)

    approved = client.post(
        f"/tasks/{created['id']}/approve",
        json={"approved_by": "lead", "comment": "erken"},
    )
    assert approved.status_code == 400
    assert "onaylanamaz" in approved.json()["detail"].lower()

    rejected = client.post(
        f"/tasks/{created['id']}/reject",
        json={"rejected_by": "qa", "reason": "erken"},
    )
    assert rejected.status_code == 400

    fetched = client.get(f"/tasks/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == TaskStatus.QUEUED.value
    assert _event_count(fetched.json(), "task_approved") == 0
    assert _event_count(fetched.json(), "task_rejected") == 0


@pytest.mark.parametrize("invalid_status", [TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.CANCELLED])
def test_invalid_statuses_reject_both_decisions(client, invalid_status):
    created = _create(client)
    _set_status(created["id"], invalid_status, error="engel")

    approved = client.post(
        f"/tasks/{created['id']}/approve",
        json={"approved_by": "lead", "comment": "hayir"},
    )
    rejected = client.post(
        f"/tasks/{created['id']}/reject",
        json={"rejected_by": "qa", "reason": "hayir"},
    )
    assert approved.status_code == 400
    assert rejected.status_code == 400

    fetched = client.get(f"/tasks/{created['id']}")
    assert fetched.json()["status"] == invalid_status.value
    assert _event_count(fetched.json(), "task_approved") == 0
    assert _event_count(fetched.json(), "task_rejected") == 0


def test_completed_approve_is_idempotent_and_reject_is_rejected(client):
    created = _create(client)
    client.post(f"/tasks/{created['id']}/run")
    first = client.post(
        f"/tasks/{created['id']}/approve",
        json={"approved_by": "lead", "comment": "ilk"},
    )
    assert first.status_code == 200
    second = client.post(
        f"/tasks/{created['id']}/approve",
        json={"approved_by": "lead", "comment": "ikinci"},
    )
    assert second.status_code == 200
    assert second.json()["status"] == TaskStatus.COMPLETED.value
    assert _event_count(second.json(), "task_approved") == 1

    rejected = client.post(
        f"/tasks/{created['id']}/reject",
        json={"rejected_by": "qa", "reason": "gec"},
    )
    assert rejected.status_code == 400
    fetched = client.get(f"/tasks/{created['id']}")
    assert fetched.json()["status"] == TaskStatus.COMPLETED.value
    assert _event_count(fetched.json(), "task_rejected") == 0


def test_repeated_reject_does_not_append_another_event(client):
    created = _create(client, require_human_approval=True)
    ran = client.post(f"/tasks/{created['id']}/run?require_human_approval=true")
    assert ran.json()["status"] == TaskStatus.AWAITING_APPROVAL.value

    first = client.post(
        f"/tasks/{created['id']}/reject",
        json={"rejected_by": "qa", "reason": "daralt"},
    )
    assert first.status_code == 200
    assert first.json()["status"] == TaskStatus.CHANGES_REQUESTED.value
    first_ids = [event["id"] for event in first.json()["events"] if event["type"] == "task_rejected"]
    assert len(first_ids) == 1

    second = client.post(
        f"/tasks/{created['id']}/reject",
        json={"rejected_by": "qa", "reason": "yeniden"},
    )
    assert second.status_code == 200
    assert second.json()["status"] == TaskStatus.CHANGES_REQUESTED.value
    second_ids = [event["id"] for event in second.json()["events"] if event["type"] == "task_rejected"]
    assert second_ids == first_ids
    assert _event_count(second.json(), "task_approved") == 0


def test_repeated_reject_on_reviewed_task_is_idempotent(client):
    created = _create(client)
    client.post(f"/tasks/{created['id']}/run")
    first = client.post(
        f"/tasks/{created['id']}/reject",
        json={"rejected_by": "qa", "reason": "daralt"},
    )
    second = client.post(
        f"/tasks/{created['id']}/reject",
        json={"rejected_by": "qa", "reason": "yeniden"},
    )
    assert second.status_code == 200
    assert second.json()["status"] == TaskStatus.CHANGES_REQUESTED.value
    assert _event_count(second.json(), "task_rejected") == 1
    assert [event["id"] for event in second.json()["events"] if event["type"] == "task_rejected"] == [
        event["id"] for event in first.json()["events"] if event["type"] == "task_rejected"
    ]


def test_approve_after_reject_does_not_complete(client):
    created = _create(client, require_human_approval=True)
    client.post(f"/tasks/{created['id']}/run?require_human_approval=true")
    client.post(
        f"/tasks/{created['id']}/reject",
        json={"rejected_by": "qa", "reason": "daralt"},
    )
    approved = client.post(
        f"/tasks/{created['id']}/approve",
        json={"approved_by": "lead", "comment": "geri al"},
    )
    assert approved.status_code == 400
    fetched = client.get(f"/tasks/{created['id']}")
    assert fetched.json()["status"] == TaskStatus.CHANGES_REQUESTED.value
    assert _event_count(fetched.json(), "task_approved") == 0
    assert _event_count(fetched.json(), "task_rejected") == 1


@pytest.mark.asyncio
async def test_concurrent_approve_and_reject_apply_one_decision():
    created_response = await _async_post("/tasks", {
        "description": SUPPORTED_TASK,
        "planner_mode": "deterministic",
        "coder_mode": "deterministic",
        "require_human_approval": True,
    })
    assert created_response.status_code == 201
    task_id = created_response.json()["id"]
    ran = await _async_post(f"/tasks/{task_id}/run?require_human_approval=true", None)
    assert ran.status_code == 200
    assert ran.json()["status"] == TaskStatus.AWAITING_APPROVAL.value
    coder_before = _event_count(ran.json(), "coder_started") + _event_count(ran.json(), "coder_retry_started")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        approve_call = http.post(
            f"/tasks/{task_id}/approve",
            json={"approved_by": "lead", "comment": "yaris"},
        )
        reject_call = http.post(
            f"/tasks/{task_id}/reject",
            json={"rejected_by": "qa", "reason": "yaris"},
        )
        approve_res, reject_res = await asyncio.gather(approve_call, reject_call)
        fetched = await http.get(f"/tasks/{task_id}")

    assert approve_res.status_code in (200, 400, 409)
    assert reject_res.status_code in (200, 400, 409)
    assert [approve_res.status_code, reject_res.status_code].count(200) == 1

    body = fetched.json()
    approved = _event_count(body, "task_approved")
    rejected = _event_count(body, "task_rejected")
    assert approved + rejected == 1
    if approved == 1:
        assert body["status"] == TaskStatus.COMPLETED.value
        assert reject_res.status_code in (400, 409)
    else:
        assert body["status"] == TaskStatus.CHANGES_REQUESTED.value
        assert approve_res.status_code in (400, 409)
    assert _event_count(body, "coder_started") + _event_count(body, "coder_retry_started") == coder_before


async def _async_post(path: str, payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        if payload is None:
            return await http.post(path)
        return await http.post(path, json=payload)
