"""
Checkpoint kararı SQLite'a yazılmadan süreç kapanırsa recovery uzlaştırır.
Gerçek LLM çağrısı yapmaz.
"""

import asyncio
import os
import shutil
import stat
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from agent_workflow import recover_unpersisted_decisions, resume_agent_workflow
from database import get_db_connection, init_db
from main import app
from repository import TaskRepository
from schemas import ReviewerResult, ReviewerVerdict, TaskStatus
from schemas import TesterResult as SchemaTesterResult


SUPPORTED_TASK = "FastAPI Items CRUD REST API"


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "recovery.db")
    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", db_path)
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("DEFAULT_PLANNER_MODE", "deterministic")
    monkeypatch.setenv("DEFAULT_CODER_MODE", "deterministic")
    monkeypatch.setenv("RUN_LIVE_LLM_TESTS", "false")
    init_db(db_path)
    return TestClient(app)


def _workspace(task_id: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "workspaces", task_id))


def _remove_tree(path: str) -> None:
    def _onerror(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if os.path.lexists(path):
        shutil.rmtree(path, onexc=_onerror)


def _remove_task_delivery(task_id: str) -> None:
    workspace = _workspace(task_id)
    git_dir = os.path.join(os.path.dirname(workspace), ".delivery", f"{task_id}.git")
    lock_path = os.path.join(os.path.dirname(workspace), ".delivery", f"{task_id}.lock")
    _remove_tree(workspace)
    _remove_tree(git_dir)
    if os.path.lexists(lock_path):
        os.chmod(lock_path, stat.S_IWRITE)
        os.remove(lock_path)


def _event_count(events, event_type: str) -> int:
    return sum(1 for event in events if getattr(event, "type", None) == event_type or (isinstance(event, dict) and event.get("type") == event_type))


def _awaiting_gap(client: TestClient) -> str:
    created = client.post("/tasks", json={
        "description": SUPPORTED_TASK,
        "planner_mode": "deterministic",
        "coder_mode": "deterministic",
        "require_human_approval": True,
    })
    assert created.status_code == 201
    task_id = created.json()["id"]
    ran = client.post(f"/tasks/{task_id}/run")
    assert ran.status_code == 200
    assert ran.json()["status"] == TaskStatus.AWAITING_APPROVAL.value
    return task_id


def test_crash_recovery_is_idempotent_and_skips_agents(client, monkeypatch):
    task_id = _awaiting_gap(client)
    try:
        stored = TaskRepository().get_task(task_id)
        assert stored is not None
        planner_before = _event_count(stored.events, "plan_created")
        coder_before = _event_count(stored.events, "coder_completed")

        resumed = asyncio.run(resume_agent_workflow(
            task_id,
            {"action": "approve", "approved_by": "lead", "comment": "kayda gecmedi"},
        ))
        assert resumed["status"] == TaskStatus.COMPLETED.value
        still = TaskRepository().get_task(task_id)
        assert still is not None
        assert still.status == TaskStatus.AWAITING_APPROVAL.value
        assert _event_count(still.events, "task_approved") == 0

        def _forbidden(*_args, **_kwargs):
            raise AssertionError("Planner veya Coder recovery sırasında çalıştı")

        monkeypatch.setattr("agent_workflow.planner_node", _forbidden)
        monkeypatch.setattr("agent_workflow.coder_node", _forbidden)
        first = asyncio.run(recover_unpersisted_decisions())
        second = asyncio.run(recover_unpersisted_decisions())
        assert task_id in first
        assert second == []

        recovered = TaskRepository().get_task(task_id)
        assert recovered is not None
        assert recovered.status == TaskStatus.COMPLETED.value
        assert _event_count(recovered.events, "task_approved") == 1
        assert _event_count(recovered.events, "plan_created") == planner_before
        assert _event_count(recovered.events, "coder_completed") == coder_before
        assert recovered.reviewer is not None
        assert recovered.reviewer.verdict == ReviewerVerdict.APPROVED
        assert recovered.tester is not None
        assert recovered.tester.passed > 0
    finally:
        _remove_task_delivery(task_id)


def test_new_process_recovers_without_rerunning_agents(client, tmp_path):
    task_id = _awaiting_gap(client)
    try:
        asyncio.run(resume_agent_workflow(
            task_id,
            {"action": "approve", "approved_by": "restart", "comment": "yeni surec"},
        ))
        assert TaskRepository().get_task(task_id).status == TaskStatus.AWAITING_APPROVAL.value
        script = tmp_path / "recover_checkpoint.py"
        script.write_text(
            "import asyncio, os, sys\n"
            "os.environ['AI_DEV_TEAM_DB_PATH'] = sys.argv[1]\n"
            "os.environ['LLM_PROVIDER'] = 'mock'\n"
            "os.environ['EXECUTION_ENGINE'] = 'mock'\n"
            "import agent_workflow\n"
            "from repository import TaskRepository\n"
            "def boom(*_args, **_kwargs):\n"
            "    raise SystemExit('agent calisti')\n"
            "agent_workflow.planner_node = boom\n"
            "agent_workflow.coder_node = boom\n"
            "async def main():\n"
            "    task_id = sys.argv[2]\n"
            "    recovered = await agent_workflow.recover_unpersisted_decisions()\n"
            "    task = TaskRepository().get_task(task_id)\n"
            "    assert task_id in recovered\n"
            "    assert task.status.value == 'completed'\n"
            "    assert sum(1 for event in task.events if event.type == 'task_approved') == 1\n"
            "    again = await agent_workflow.recover_unpersisted_decisions()\n"
            "    assert again == []\n"
            "    reread = TaskRepository().get_task(task_id)\n"
            "    assert sum(1 for event in reread.events if event.type == 'task_approved') == 1\n"
            "asyncio.run(main())\n",
            encoding="utf-8",
        )
        backend_dir = os.path.dirname(os.path.dirname(__file__))
        child_env = os.environ.copy()
        child_env["PYTHONPATH"] = backend_dir
        child_env["AI_DEV_TEAM_DB_PATH"] = os.environ["AI_DEV_TEAM_DB_PATH"]
        completed = subprocess.run(
            [sys.executable, str(script), os.environ["AI_DEV_TEAM_DB_PATH"], task_id],
            cwd=backend_dir,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        reread = TaskRepository().get_task(task_id)
        assert reread.status == TaskStatus.COMPLETED
        assert _event_count(reread.events, "task_approved") == 1
    finally:
        _remove_task_delivery(task_id)


def test_missing_or_unverified_checkpoint_is_not_completed(client):
    pending_id = _awaiting_gap(client)
    missing_id = _awaiting_gap(client)
    try:
        pending = asyncio.run(recover_unpersisted_decisions())
        assert pending_id not in pending
        pending_task = TaskRepository().get_task(pending_id)
        assert pending_task.status == TaskStatus.AWAITING_APPROVAL
        assert _event_count(pending_task.events, "task_approved") == 0

        from agent_workflow import delete_task_checkpoint
        from database import get_db_path
        delete_task_checkpoint(missing_id, get_db_path())
        missing = asyncio.run(recover_unpersisted_decisions())
        assert missing_id not in missing
        missing_task = TaskRepository().get_task(missing_id)
        assert missing_task.status == TaskStatus.AWAITING_APPROVAL
        assert missing_task.status != TaskStatus.COMPLETED
        assert _event_count(missing_task.events, "task_approved") == 0
    finally:
        _remove_task_delivery(pending_id)
        _remove_task_delivery(missing_id)


def _reviewed_shell(client: TestClient) -> str:
    created = client.post("/tasks", json={"description": SUPPORTED_TASK})
    assert created.status_code == 201
    task_id = created.json()["id"]
    task = TaskRepository().get_task(task_id)
    TaskRepository().update_task_workflow_result(
        task_id=task_id,
        status=TaskStatus.REVIEWED,
        events=task.events,
        error=None,
    )
    return task_id


def test_reviewed_without_approved_evidence_is_not_completed(client):
    missing = _reviewed_shell(client)
    response = client.post(f"/tasks/{missing}/approve", json={"approved_by": "lead", "comment": "eksik"})
    assert response.status_code == 400
    assert "tamamlanamaz" in response.json()["detail"]
    assert TaskRepository().get_task(missing).status == TaskStatus.REVIEWED
    assert _event_count(TaskRepository().get_task(missing).events, "task_approved") == 0

    changes = _reviewed_shell(client)
    TaskRepository().update_task_workflow_result(
        task_id=changes,
        status=TaskStatus.REVIEWED,
        reviewer=ReviewerResult(
            status="reviewed",
            verdict=ReviewerVerdict.CHANGES_REQUESTED,
            summary="eski kayit",
        ),
        tester=SchemaTesterResult(status="tested", passed=2, failed=0, summary="test var"),
        events=TaskRepository().get_task(changes).events,
    )
    denied = client.post(f"/tasks/{changes}/approve", json={"approved_by": "lead", "comment": "ret"})
    assert denied.status_code == 400
    assert TaskRepository().get_task(changes).status == TaskStatus.REVIEWED


def test_failed_or_zero_tests_are_not_completed(client):
    failed = _reviewed_shell(client)
    TaskRepository().update_task_workflow_result(
        task_id=failed,
        status=TaskStatus.REVIEWED,
        reviewer=ReviewerResult(status="reviewed", verdict=ReviewerVerdict.APPROVED, summary="onay"),
        tester=SchemaTesterResult(status="failed", passed=1, failed=1, summary="hata"),
        events=TaskRepository().get_task(failed).events,
    )
    failed_res = client.post(f"/tasks/{failed}/approve", json={"approved_by": "lead", "comment": "test"})
    assert failed_res.status_code == 400
    assert TaskRepository().get_task(failed).status == TaskStatus.REVIEWED

    zero = _reviewed_shell(client)
    TaskRepository().update_task_workflow_result(
        task_id=zero,
        status=TaskStatus.REVIEWED,
        reviewer=ReviewerResult(status="reviewed", verdict=ReviewerVerdict.APPROVED, summary="onay"),
        tester=SchemaTesterResult(status="tested", passed=0, failed=0, summary="bos"),
        events=TaskRepository().get_task(zero).events,
    )
    zero_res = client.post(f"/tasks/{zero}/approve", json={"approved_by": "lead", "comment": "sifir"})
    assert zero_res.status_code == 400
    assert "test" in zero_res.json()["detail"]
    assert TaskRepository().get_task(zero).status == TaskStatus.REVIEWED
    assert _event_count(TaskRepository().get_task(zero).events, "task_approved") == 0


def test_corrupt_legacy_row_stays_uncompleted(client):
    task_id = _reviewed_shell(client)
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE tasks SET reviewer_json = ?, tester_json = ? WHERE id = ?",
            ('{"verdict": "approved"}', "not-json", task_id),
        )
    loaded = TaskRepository().get_task(task_id)
    assert loaded is not None
    assert loaded.reviewer is None
    assert loaded.tester is None
    response = client.post(f"/tasks/{task_id}/approve", json={"approved_by": "lead", "comment": "bozuk"})
    assert response.status_code == 400
    assert TaskRepository().get_task(task_id).status == TaskStatus.REVIEWED


def test_delivery_retry_does_not_run_planner_or_coder(client, monkeypatch):
    task_id = _awaiting_gap(client)
    try:
        failed = {
            "status": "failed",
            "branch": f"task/{task_id}",
            "commit": None,
            "previous_commit": None,
            "reason": "Commit tamamlanamadı",
            "files": [],
        }
        import agent_workflow
        original = agent_workflow.deliver_task_workspace
        agent_workflow.deliver_task_workspace = lambda *_args, **_kwargs: failed
        try:
            approved = client.post(f"/tasks/{task_id}/approve", json={"approved_by": "lead", "comment": "dene"})
        finally:
            agent_workflow.deliver_task_workspace = original
        assert approved.status_code == 200
        assert approved.json()["status"] == TaskStatus.DELIVERY_FAILED.value
        planner_before = _event_count(approved.json()["events"], "plan_created")
        coder_before = _event_count(approved.json()["events"], "coder_completed")

        def _forbidden(*_args, **_kwargs):
            raise AssertionError("Planner veya Coder teslimat retry sırasında çalıştı")

        monkeypatch.setattr("agent_workflow.planner_node", _forbidden)
        monkeypatch.setattr("agent_workflow.coder_node", _forbidden)
        retried = client.post(f"/tasks/{task_id}/deliver")
        assert retried.status_code == 200
        body = retried.json()
        assert body["status"] in {TaskStatus.COMPLETED.value, TaskStatus.DELIVERY_FAILED.value}
        assert _event_count(body["events"], "plan_created") == planner_before
        assert _event_count(body["events"], "coder_completed") == coder_before
        assert not any(event["source"] == "PLANNER_AGENT" and event["type"] == "planning_started" and event not in approved.json()["events"] for event in body["events"])
    finally:
        _remove_task_delivery(task_id)
