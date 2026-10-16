"""
İzole Git teslimatı. Gerçek LLM çağrısı yapmaz.
Git varsa temp depoda gerçek commit davranışını da doğrular.
"""

import asyncio
import os
import pathlib
import shutil
import stat
import sys
import subprocess
import threading

import pytest
from fastapi.testclient import TestClient

from agent_workflow import (
    coder_node,
    delivery_node,
    planner_node,
    resume_agent_workflow,
    run_agent_workflow,
    _route_after_human_gate,
    _route_after_reviewer,
)
from database import init_db
from git_delivery import _find_base_git_dir, deliver_task_workspace
from main import app
from repository import TaskRepository
from schemas import ReviewerVerdict, TaskStatus


SUPPORTED_TASK = "FastAPI Items CRUD REST API"


def _git(cwd: str, *args: str, git_dir: str | None = None, work_tree: str | None = None) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    if git_dir and work_tree:
        env["GIT_DIR"] = git_dir
        env["GIT_WORK_TREE"] = work_tree
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _delivery_paths(root: str, task_id: str) -> tuple[str, str]:
    workspace = os.path.join(root, task_id)
    git_dir = os.path.join(root, ".delivery", f"{task_id}.git")
    return workspace, git_dir


@pytest.fixture
def git_available():
    if shutil.which("git") is None:
        pytest.skip("Git kurulu değil; gerçek commit senaryosu çalıştırılmadı.")


def test_invalid_task_id_does_not_create_repository(tmp_path):
    result = deliver_task_workspace("../outside", str(tmp_path), ["README.md"])
    assert result["status"] == "failed"
    assert result["commit"] is None
    assert not (tmp_path / ".git").exists()
    assert list(tmp_path.iterdir()) == []


def test_delivery_node_skips_when_review_or_tests_fail(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_workflow._get_safe_workspaces_root", lambda: str(tmp_path))
    state = {
        "task_id": "task_skip",
        "status": TaskStatus.BLOCKED.value,
        "require_human_approval": False,
        "reviewer": {"verdict": ReviewerVerdict.BLOCKED.value},
        "tester": {"status": "blocked", "passed": 0, "failed": 0},
        "coder": {"created_files": ["README.md"]},
        "events": [],
    }
    result = delivery_node(state)
    assert result["events"][-1]["type"] == "delivery_skipped"
    assert not (tmp_path / "task_skip" / ".git").exists()
    assert _route_after_reviewer(state) == "end"


def test_human_rejection_does_not_route_to_delivery():
    route = _route_after_human_gate({
        "status": TaskStatus.CHANGES_REQUESTED.value,
        "events": [{"type": "task_rejected"}],
    })
    assert route == "end"


def test_missing_git_reports_failure_without_commit(tmp_path, monkeypatch, git_available):
    workspace = tmp_path / "task_nogit"
    workspace.mkdir()
    (workspace / "README.md").write_text("icerik", encoding="utf-8")
    monkeypatch.setattr("git_delivery.shutil.which", lambda _name: None)
    result = deliver_task_workspace("task_nogit", str(tmp_path), ["README.md"])
    assert result["status"] == "failed"
    assert result["commit"] is None
    assert "Git bulunamadı" in str(result["reason"])
    assert not (workspace / ".git").exists()


def test_isolated_branch_commit_is_idempotent_and_leaves_parent_untouched(tmp_path, git_available):
    parent = tmp_path / "parent-repo"
    parent.mkdir()
    (parent / "user.txt").write_text("kullanici", encoding="utf-8")
    _git(str(parent), "init", "-b", "main")
    _git(str(parent), "-c", "user.name=User", "-c", "user.email=user@example.com", "add", "--", "user.txt")
    _git(str(parent), "-c", "user.name=User", "-c", "user.email=user@example.com", "commit", "-m", "user change")
    parent_head = _git(str(parent), "rev-parse", "HEAD")

    root = parent / "workspaces"
    task_id = "task_delivery"
    workspace = root / task_id
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text("teslim", encoding="utf-8")
    (workspace / "api_feature.py").write_text("VALUE = 1\n", encoding="utf-8")

    first = deliver_task_workspace(task_id, str(root), [f"workspaces/{task_id}/README.md", "api_feature.py"])
    assert first["status"] == "committed"
    assert first["branch"] == "task/task_delivery"
    assert first["commit"]

    workspace_path, git_dir = _delivery_paths(str(root), task_id)
    assert not os.path.lexists(os.path.join(workspace_path, ".git"))
    branch = _git(workspace_path, "rev-parse", "--abbrev-ref", "HEAD", git_dir=git_dir, work_tree=workspace_path)
    assert branch == "task/task_delivery"
    assert _git(workspace_path, "rev-parse", "HEAD^", git_dir=git_dir, work_tree=workspace_path) == parent_head
    assert _git(
        workspace_path,
        "rev-parse",
        "refs/delivery-base/main",
        git_dir=git_dir,
        work_tree=workspace_path,
    ) == parent_head
    tree = _git(workspace_path, "ls-tree", "-r", "--name-only", "HEAD", git_dir=git_dir, work_tree=workspace_path)
    assert "user.txt" in tree
    assert "README.md" in tree
    assert _git(workspace_path, "rev-list", "--count", "HEAD", git_dir=git_dir, work_tree=workspace_path) == "2"
    toplevel = os.path.normcase(os.path.abspath(
        _git(workspace_path, "rev-parse", "--show-toplevel", git_dir=git_dir, work_tree=workspace_path)
    ))
    assert toplevel == os.path.normcase(os.path.abspath(workspace_path))

    second = deliver_task_workspace(task_id, str(root), ["README.md", "api_feature.py"])
    assert second["status"] == "reused"
    assert second["commit"] == first["commit"]
    assert _git(workspace_path, "rev-list", "--count", "HEAD", git_dir=git_dir, work_tree=workspace_path) == "2"

    assert _git(str(parent), "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _git(str(parent), "rev-parse", "HEAD") == parent_head
    assert "task/task_delivery" not in _git(str(parent), "branch", "--list")


def test_commit_failure_resets_index_and_keeps_files(tmp_path, monkeypatch, git_available):
    workspace = tmp_path / "task_fail"
    workspace.mkdir()
    (workspace / "README.md").write_text("kalir", encoding="utf-8")
    real_run = subprocess.run

    def fail_commit(*args, **kwargs):
        command = args[0]
        if isinstance(command, list) and any(arg in {"commit", "commit-tree"} for arg in command):
            return subprocess.CompletedProcess(command, 1, "", "commit reddedildi")
        return real_run(*args, **kwargs)

    monkeypatch.setattr("git_delivery.subprocess.run", fail_commit)
    result = deliver_task_workspace("task_fail", str(tmp_path), ["README.md"])
    assert result["status"] == "failed"
    assert result["commit"] is None
    assert (workspace / "README.md").read_text(encoding="utf-8") == "kalir"
    probe_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    probe_env["GIT_DIR"] = str(tmp_path / ".delivery" / "task_fail.git")
    probe_env["GIT_WORK_TREE"] = str(workspace)
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=str(workspace),
        env=probe_env,
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0


@pytest.fixture
def workflow_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "delivery.db")
    monkeypatch.setenv("AI_DEV_TEAM_DB_PATH", db_path)
    monkeypatch.setenv("EXECUTION_ENGINE", "mock")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("DEFAULT_PLANNER_MODE", "deterministic")
    monkeypatch.setenv("DEFAULT_CODER_MODE", "deterministic")
    monkeypatch.setenv("RUN_LIVE_LLM_TESTS", "false")
    init_db(db_path)


def _workspace(task_id: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "workspaces", task_id))


def _remove_tree(path: str) -> None:
    def _onerror(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if not os.path.lexists(path):
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_onerror)
    else:
        shutil.rmtree(path, onerror=_onerror)


def _remove_task_delivery(task_id: str) -> None:
    workspace = _workspace(task_id)
    git_dir = os.path.join(os.path.dirname(workspace), ".delivery", f"{task_id}.git")
    _remove_tree(workspace)
    _remove_tree(git_dir)


def test_approval_waits_without_commit_then_approve_commits_once(workflow_env, git_available):
    task_id = "task_git_wait"
    workspace = _workspace(task_id)
    _remove_task_delivery(task_id)
    try:
        waiting = asyncio.run(run_agent_workflow(
            task_id=task_id,
            description=SUPPORTED_TASK,
            planner_mode="deterministic",
            coder_mode="deterministic",
            require_human_approval=True,
        ))
        assert waiting["status"] == TaskStatus.AWAITING_APPROVAL.value
        assert not any(event.get("type") in {"delivery_committed", "delivery_reused"} for event in waiting["events"])
        assert not os.path.isdir(os.path.join(workspace, ".git"))

        approved = asyncio.run(resume_agent_workflow(
            task_id,
            {"action": "approve", "approved_by": "lead", "comment": "teslim"},
        ))
        assert approved["status"] == TaskStatus.COMPLETED.value
        committed = [event for event in approved["events"] if event.get("type") == "delivery_committed"]
        assert len(committed) == 1
        assert committed[0]["details"]["branch"] == f"task/{task_id}"
        _, git_dir = _delivery_paths(os.path.dirname(workspace), task_id)
        assert not os.path.lexists(os.path.join(workspace, ".git"))
        assert _git(workspace, "rev-list", "--count", "refs/delivery-base/main..HEAD", git_dir=git_dir, work_tree=workspace) == "1"

        again = deliver_task_workspace(
            task_id,
            os.path.dirname(workspace),
            committed[0]["details"]["files"],
        )
        assert again["status"] == "reused"
        assert again["commit"] == committed[0]["details"]["commit"]
    finally:
        _remove_task_delivery(task_id)


def test_reject_does_not_create_delivery_commit(workflow_env, git_available):
    task_id = "task_git_reject"
    workspace = _workspace(task_id)
    _remove_task_delivery(task_id)
    try:
        asyncio.run(run_agent_workflow(
            task_id=task_id,
            description=SUPPORTED_TASK,
            planner_mode="deterministic",
            coder_mode="deterministic",
            require_human_approval=True,
        ))
        rejected = asyncio.run(resume_agent_workflow(
            task_id,
            {"action": "reject", "rejected_by": "qa", "reason": "daralt"},
        ))
        assert rejected["status"] == TaskStatus.CHANGES_REQUESTED.value
        assert not any(event.get("type") == "delivery_committed" for event in rejected["events"])
        assert not os.path.lexists(os.path.join(workspace, ".git"))
    finally:
        _remove_task_delivery(task_id)


def test_reviewed_task_commits_on_isolated_branch(workflow_env, git_available):
    task_id = "task_git_auto"
    workspace = _workspace(task_id)
    _remove_task_delivery(task_id)
    try:
        result = asyncio.run(run_agent_workflow(
            task_id=task_id,
            description=SUPPORTED_TASK,
            planner_mode="deterministic",
            coder_mode="deterministic",
            require_human_approval=False,
        ))
        assert result["status"] == TaskStatus.REVIEWED.value
        assert any(event.get("type") == "delivery_committed" for event in result["events"])
        _, git_dir = _delivery_paths(os.path.dirname(workspace), task_id)
        assert not os.path.lexists(os.path.join(workspace, ".git"))
        assert _git(workspace, "rev-parse", "--abbrev-ref", "HEAD", git_dir=git_dir, work_tree=workspace) == f"task/{task_id}"
        assert "delivery" in result["executed_nodes"]
    finally:
        _remove_task_delivery(task_id)


def _eligible_state(task_id: str, **overrides):
    state = {
        "task_id": task_id,
        "status": TaskStatus.REVIEWED.value,
        "require_human_approval": False,
        "reviewer": {"verdict": ReviewerVerdict.APPROVED.value},
        "tester": {"status": "tested", "passed": 4, "failed": 0},
        "coder": {"created_files": ["README.md"]},
        "events": [],
        "error": None,
    }
    state.update(overrides)
    return state


def test_reviewer_rejection_and_failed_tests_do_not_commit(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_workflow._get_safe_workspaces_root", lambda: str(tmp_path))
    rejected = _eligible_state(
        "task_reject_skip",
        status=TaskStatus.REVIEWED.value,
        reviewer={"verdict": ReviewerVerdict.CHANGES_REQUESTED.value},
    )
    assert _route_after_reviewer(rejected) in {"retry", "end"}
    rejected_delivery = delivery_node(rejected)
    assert rejected_delivery["events"][-1]["type"] == "delivery_skipped"
    assert rejected_delivery["status"] != TaskStatus.COMPLETED.value
    assert not (tmp_path / ".delivery").exists()

    failed_tests = _eligible_state(
        "task_tests_fail",
        tester={"status": "failed", "passed": 1, "failed": 2},
    )
    assert _route_after_reviewer(failed_tests) in {"retry", "end"}
    failed_delivery = delivery_node(failed_tests)
    assert failed_delivery["events"][-1]["type"] == "delivery_skipped"

    zero_passed = _eligible_state(
        "task_zero",
        tester={"status": "tested", "passed": 0, "failed": 0},
    )
    assert _route_after_reviewer(zero_passed) == "end"
    zero_delivery = delivery_node(zero_passed)
    assert zero_delivery["events"][-1]["type"] == "delivery_skipped"
    assert not (tmp_path / "task_zero" / ".git").exists()


def test_changed_content_gets_a_new_commit(tmp_path, git_available):
    task_id = "task_content"
    workspace = tmp_path / task_id
    workspace.mkdir()
    readme = workspace / "README.md"
    readme.write_text("eski\n", encoding="utf-8")
    first = deliver_task_workspace(task_id, str(tmp_path), ["README.md"])
    second = deliver_task_workspace(task_id, str(tmp_path), ["README.md"])
    assert first["status"] == "committed"
    assert second["status"] == "reused"
    assert second["commit"] == first["commit"]

    readme.write_text("yeni\n", encoding="utf-8")
    third = deliver_task_workspace(task_id, str(tmp_path), ["README.md"])
    assert third["status"] == "committed"
    assert third["commit"] != first["commit"]
    assert third["previous_commit"] == first["commit"]
    workspace_path, git_dir = _delivery_paths(str(tmp_path), task_id)
    assert _git(workspace_path, "rev-parse", f"{third['commit']}^", git_dir=git_dir, work_tree=workspace_path) == first["commit"]
    assert _git(workspace_path, "rev-list", "--count", "refs/delivery-base/main..HEAD", git_dir=git_dir, work_tree=workspace_path) == "2"
    assert _git(workspace_path, "show", f"{third['commit']}:README.md", git_dir=git_dir, work_tree=workspace_path) == "yeni"
    assert _git(workspace_path, "show", f"{first['commit']}:README.md", git_dir=git_dir, work_tree=workspace_path) == "eski"
    assert not os.path.lexists(os.path.join(workspace_path, ".git"))


def test_commit_failure_sets_delivery_failed_without_deleting_files(tmp_path, monkeypatch, git_available):
    task_id = "task_status_fail"
    workspace = tmp_path / task_id
    workspace.mkdir()
    (workspace / "README.md").write_text("kalir\n", encoding="utf-8")
    monkeypatch.setattr("agent_workflow._get_safe_workspaces_root", lambda: str(tmp_path))
    real_run = subprocess.run

    def fail_commit(*args, **kwargs):
        command = args[0]
        if isinstance(command, list) and any(arg in {"commit", "commit-tree"} for arg in command):
            return subprocess.CompletedProcess(command, 1, "", "commit reddedildi")
        return real_run(*args, **kwargs)

    monkeypatch.setattr("git_delivery.subprocess.run", fail_commit)
    state = _eligible_state(task_id, events=[{"type": "task_approved", "details": {}}])
    result = delivery_node(state)
    assert result["status"] == TaskStatus.DELIVERY_FAILED.value
    assert result["status"] != TaskStatus.COMPLETED.value
    assert result["error"]
    assert result["events"][-1]["type"] == "delivery_failed"
    assert (workspace / "README.md").read_text(encoding="utf-8") == "kalir\n"


def test_retry_after_delivery_failure_does_not_rerun_agents(tmp_path, monkeypatch, git_available):
    task_id = "task_retry_delivery"
    workspace = tmp_path / task_id
    workspace.mkdir()
    (workspace / "README.md").write_text("yeniden\n", encoding="utf-8")
    monkeypatch.setattr("agent_workflow._get_safe_workspaces_root", lambda: str(tmp_path))

    def fail_agents(*_args, **_kwargs):
        raise AssertionError("Planner veya Coder teslimat retry sırasında çalıştı")

    monkeypatch.setattr("agent_workflow.planner_node", fail_agents)
    monkeypatch.setattr("agent_workflow.coder_node", fail_agents)
    failed = {
        "status": "failed",
        "branch": f"task/{task_id}",
        "commit": None,
        "previous_commit": None,
        "reason": "Commit tamamlanamadı",
        "files": ["README.md"],
    }
    monkeypatch.setattr("agent_workflow.deliver_task_workspace", lambda *_args, **_kwargs: failed)
    state = _eligible_state(task_id, events=[{"type": "task_approved", "details": {}}])
    first = delivery_node(state)
    assert first["status"] == TaskStatus.DELIVERY_FAILED.value
    assert "planner" not in first.get("executed_nodes", [])
    assert "coder" not in first.get("executed_nodes", [])

    monkeypatch.setattr("agent_workflow.deliver_task_workspace", deliver_task_workspace)
    retried = delivery_node(first)
    assert retried["status"] == TaskStatus.COMPLETED.value
    assert retried["error"] is None
    committed = [event for event in retried["events"] if event["type"] == "delivery_committed"]
    assert len(committed) == 1
    workspace_path, git_dir = _delivery_paths(str(tmp_path), task_id)
    head = _git(workspace_path, "rev-parse", "HEAD", git_dir=git_dir, work_tree=workspace_path)
    assert committed[0]["details"]["commit"] == head
    assert planner_node is not None and coder_node is not None


def test_concurrent_delivery_keeps_a_single_sha(tmp_path, git_available):
    task_id = "task_parallel"
    workspace = tmp_path / task_id
    workspace.mkdir()
    (workspace / "README.md").write_text("ortak\n", encoding="utf-8")
    barrier = threading.Barrier(2)
    results = []

    def _worker():
        barrier.wait(timeout=10)
        results.append(deliver_task_workspace(task_id, str(tmp_path), ["README.md"]))

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(results) == 2
    assert all(item["status"] in {"committed", "reused"} for item in results)
    assert len({item["commit"] for item in results}) == 1
    workspace_path, git_dir = _delivery_paths(str(tmp_path), task_id)
    assert _git(workspace_path, "rev-list", "--count", "refs/delivery-base/main..HEAD", git_dir=git_dir, work_tree=workspace_path) == "1"
    assert _git(workspace_path, "rev-parse", "--abbrev-ref", "HEAD", git_dir=git_dir, work_tree=workspace_path) == f"task/{task_id}"


def test_restart_reads_failed_delivery_then_successful_retry(workflow_env, git_available):
    client = TestClient(app)
    created = client.post(
        "/tasks",
        json={
            "description": SUPPORTED_TASK,
            "planner_mode": "deterministic",
            "coder_mode": "deterministic",
            "require_human_approval": True,
        },
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    try:
        ran = client.post(f"/tasks/{task_id}/run")
        assert ran.status_code == 200
        assert ran.json()["status"] == TaskStatus.AWAITING_APPROVAL.value
        planner_events = sum(1 for event in ran.json()["events"] if event["source"] == "PLANNER_AGENT")
        coder_events = sum(1 for event in ran.json()["events"] if event["source"] == "CODER_AGENT")

        failed = {
            "status": "failed",
            "branch": f"task/{task_id}",
            "commit": None,
            "previous_commit": None,
            "reason": "Commit tamamlanamadı",
            "files": [],
        }
        original = deliver_task_workspace

        def fail_delivery(*_args, **_kwargs):
            return failed

        import agent_workflow
        agent_workflow.deliver_task_workspace = fail_delivery
        try:
            approved = client.post(
                f"/tasks/{task_id}/approve",
                json={"approved_by": "lead", "comment": "teslim"},
            )
        finally:
            agent_workflow.deliver_task_workspace = original

        assert approved.status_code == 200
        body = approved.json()
        assert body["status"] == TaskStatus.DELIVERY_FAILED.value
        assert body["status"] != TaskStatus.COMPLETED.value
        assert body["error"]
        assert any(event["type"] == "task_approved" for event in body["events"])
        assert any(event["type"] == "delivery_failed" for event in body["events"])

        reloaded = TaskRepository().get_task(task_id)
        assert reloaded is not None
        assert reloaded.status == TaskStatus.DELIVERY_FAILED
        assert reloaded.error == body["error"]

        blocked = client.post(f"/tasks/{task_id}/run")
        assert blocked.status_code == 409

        retried = client.post(f"/tasks/{task_id}/deliver")
        assert retried.status_code == 200
        delivered = retried.json()
        assert delivered["status"] == TaskStatus.COMPLETED.value
        assert sum(1 for event in delivered["events"] if event["source"] == "PLANNER_AGENT") == planner_events
        assert sum(1 for event in delivered["events"] if event["source"] == "CODER_AGENT") == coder_events
        commit_events = [event for event in delivered["events"] if event["type"] == "delivery_committed"]
        assert len(commit_events) == 1
        workspace, git_dir = _delivery_paths(os.path.dirname(_workspace(task_id)), task_id)
        head = _git(workspace, "rev-parse", "HEAD", git_dir=git_dir, work_tree=workspace)
        assert commit_events[0]["details"]["commit"] == head

        reread = TaskRepository().get_task(task_id)
        assert reread is not None
        assert reread.status == TaskStatus.COMPLETED
        assert reread.events[-1].type == "delivery_committed"
        assert reread.events[-1].details["commit"] == head
    finally:
        _remove_task_delivery(task_id)


def _commit_file(repo: str, name: str, content: str, message: str) -> str:
    with open(os.path.join(repo, name), "w", encoding="utf-8") as handle:
        handle.write(content)
    _git(repo, "-c", "user.name=User", "-c", "user.email=user@example.com", "add", "--", name)
    _git(repo, "-c", "user.name=User", "-c", "user.email=user@example.com", "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _shallow_clone(source: str, destination: str) -> None:
    _git(source, "clone", "--depth", "1", "--branch", "main", pathlib.Path(source).resolve().as_uri(), destination)


def _noop_fetch(real_run):
    def _run(args, **kwargs):
        command = args[0] if isinstance(args, tuple) else args
        if isinstance(command, list) and "fetch" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        return real_run(args, **kwargs)

    return _run


def test_shallow_source_imports_exact_base_without_rewriting_source(tmp_path, git_available):
    source = tmp_path / "full-source"
    source.mkdir()
    _git(str(source), "init", "-b", "main")
    _commit_file(str(source), "user.txt", "bir\n", "ilk")
    tip = _commit_file(str(source), "user.txt", "iki\n", "ikinci")
    shallow_file = source / ".git" / "shallow"
    checkout = tmp_path / "shallow-checkout"
    _shallow_clone(str(source), str(checkout))
    shallow_head = _git(str(checkout), "rev-parse", "HEAD")
    shallow_marker = (checkout / ".git" / "shallow").read_text(encoding="ascii")
    assert _git(str(checkout), "rev-parse", "--is-shallow-repository") == "true"
    assert shallow_head == tip
    assert not shallow_file.exists()

    root = checkout / "workspaces"
    task_id = "task_shallow"
    workspace = root / task_id
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text("sig teslim\n", encoding="utf-8")
    first = deliver_task_workspace(task_id, str(root), ["README.md"])
    assert first["status"] == "committed"
    assert first["commit"]
    workspace_path, git_dir = _delivery_paths(str(root), task_id)
    base = _git(workspace_path, "rev-parse", "refs/delivery-base/main", git_dir=git_dir, work_tree=workspace_path)
    assert base == shallow_head
    assert _git(workspace_path, "rev-parse", "HEAD^", git_dir=git_dir, work_tree=workspace_path) == shallow_head
    assert _git(
        workspace_path,
        "merge-base",
        "--is-ancestor",
        base,
        "HEAD",
        git_dir=git_dir,
        work_tree=workspace_path,
    ) == ""
    assert _git(
        workspace_path,
        "rev-list",
        "--count",
        "refs/delivery-base/main..HEAD",
        git_dir=git_dir,
        work_tree=workspace_path,
    ) == "1"
    tree = _git(workspace_path, "ls-tree", "-r", "--name-only", "HEAD", git_dir=git_dir, work_tree=workspace_path)
    assert "user.txt" in tree
    assert "README.md" in tree
    assert _git(str(checkout), "rev-parse", "HEAD") == shallow_head
    assert (checkout / ".git" / "shallow").read_text(encoding="ascii") == shallow_marker
    assert _git(str(source), "rev-parse", "HEAD") == tip
    assert "task/task_shallow" not in _git(str(source), "branch", "--list")

    second = deliver_task_workspace(task_id, str(root), ["README.md"])
    assert second["status"] == "reused"
    assert second["commit"] == first["commit"]
    assert _git(workspace_path, "rev-parse", "refs/delivery-base/main", git_dir=git_dir, work_tree=workspace_path) == base


def test_shallow_fetch_without_ref_still_imports_expected_commit(tmp_path, monkeypatch, git_available):
    source = tmp_path / "full-source"
    source.mkdir()
    _git(str(source), "init", "-b", "main")
    tip = _commit_file(str(source), "user.txt", "sig\n", "tek")
    checkout = tmp_path / "shallow-checkout"
    _shallow_clone(str(source), str(checkout))
    root = checkout / "workspaces"
    task_id = "task_shallow_fetch"
    workspace = root / task_id
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text("kopya\n", encoding="utf-8")
    monkeypatch.setattr("git_delivery.subprocess.run", _noop_fetch(subprocess.run))
    result = deliver_task_workspace(task_id, str(root), ["README.md"])
    assert result["status"] == "committed"
    workspace_path, git_dir = _delivery_paths(str(root), task_id)
    assert _git(workspace_path, "rev-parse", "refs/delivery-base/main", git_dir=git_dir, work_tree=workspace_path) == tip
    assert _git(workspace_path, "rev-parse", "HEAD^", git_dir=git_dir, work_tree=workspace_path) == tip
    assert _git(str(checkout), "rev-parse", "HEAD") == tip


def test_fetch_exit_zero_without_ref_fails_for_full_repository(tmp_path, monkeypatch, git_available):
    parent = tmp_path / "parent-repo"
    parent.mkdir()
    _git(str(parent), "init", "-b", "main")
    _commit_file(str(parent), "user.txt", "tam\n", "tam depo")
    root = parent / "workspaces"
    task_id = "task_fetch_ignored"
    workspace = root / task_id
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text("yok\n", encoding="utf-8")
    monkeypatch.setattr("git_delivery.subprocess.run", _noop_fetch(subprocess.run))
    result = deliver_task_workspace(task_id, str(root), ["README.md"])
    assert result["status"] == "failed"
    assert result["commit"] is None
    assert "Ana dal geçmişi teslimat deposuna alınamadı" in str(result["reason"])
    git_dir = root / ".delivery" / f"{task_id}.git"
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "refs/delivery-base/main"],
        cwd=str(workspace),
        env={
            **{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
            "GIT_DIR": str(git_dir),
            "GIT_WORK_TREE": str(workspace),
        },
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0


def test_unrelated_base_ref_is_not_rewritten(tmp_path, git_available):
    parent = tmp_path / "parent-repo"
    parent.mkdir()
    _git(str(parent), "init", "-b", "main")
    source_head = _commit_file(str(parent), "user.txt", "kaynak\n", "kaynak")
    root = parent / "workspaces"
    task_id = "task_unrelated"
    workspace = root / task_id
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text("gorev\n", encoding="utf-8")
    git_dir = root / ".delivery" / f"{task_id}.git"
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    _git(str(unrelated), "init", "-b", "main")
    unrelated_head = _commit_file(str(unrelated), "other.txt", "baska\n", "baska")
    os.makedirs(git_dir, exist_ok=True)
    _git(str(workspace), "init", "--separate-git-dir", str(git_dir), "-b", "task/task_unrelated")
    _git(str(workspace), "fetch", "--no-tags", "--", str(unrelated / ".git"), f"{unrelated_head}:refs/delivery-base/main")
    assert _git(str(workspace), "rev-parse", "refs/delivery-base/main") == unrelated_head

    result = deliver_task_workspace(task_id, str(root), ["README.md"])
    assert result["status"] == "failed"
    assert result["commit"] is None
    assert _git(
        str(workspace),
        "rev-parse",
        "refs/delivery-base/main",
        git_dir=str(git_dir),
        work_tree=str(workspace),
    ) == unrelated_head
    assert _git(str(parent), "rev-parse", "HEAD") == source_head


def test_shallow_repeated_and_concurrent_delivery_keep_one_history(tmp_path, git_available):
    source = tmp_path / "full-source"
    source.mkdir()
    _git(str(source), "init", "-b", "main")
    tip = _commit_file(str(source), "user.txt", "ortak\n", "taban")
    checkout = tmp_path / "shallow-checkout"
    _shallow_clone(str(source), str(checkout))
    root = checkout / "workspaces"
    task_id = "task_shallow_parallel"
    workspace = root / task_id
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text("paralel\n", encoding="utf-8")
    barrier = threading.Barrier(2)
    results = []

    def _worker():
        barrier.wait(timeout=10)
        results.append(deliver_task_workspace(task_id, str(root), ["README.md"]))

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(results) == 2
    assert all(item["status"] in {"committed", "reused"} for item in results)
    assert len({item["commit"] for item in results}) == 1
    workspace_path, git_dir = _delivery_paths(str(root), task_id)
    assert _git(workspace_path, "rev-parse", "refs/delivery-base/main", git_dir=git_dir, work_tree=workspace_path) == tip
    assert _git(
        workspace_path,
        "rev-list",
        "--count",
        "refs/delivery-base/main..HEAD",
        git_dir=git_dir,
        work_tree=workspace_path,
    ) == "1"
    repeated = deliver_task_workspace(task_id, str(root), ["README.md"])
    assert repeated["status"] == "reused"
    assert repeated["commit"] == results[0]["commit"]


def _git_result(cwd: str, *args: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_detached_shallow_checkout_without_local_main_uses_verified_origin_ref(tmp_path, git_available):
    source = tmp_path / "full-source"
    source.mkdir()
    _git(str(source), "init", "-b", "main")
    _commit_file(str(source), "user.txt", "bir\n", "ilk")
    tip = _commit_file(str(source), "user.txt", "iki\n", "ikinci")
    checkout = tmp_path / "shallow-checkout"
    _shallow_clone(str(source), str(checkout))
    _git(str(checkout), "checkout", "--detach", "HEAD")
    _git(str(checkout), "update-ref", "-d", "refs/heads/main")

    missing_main = _git_result(str(checkout), "rev-parse", "--verify", "--end-of-options", "refs/heads/main")
    detached = _git_result(str(checkout), "symbolic-ref", "--quiet", "HEAD")
    assert missing_main.returncode != 0
    assert detached.returncode != 0
    assert _git(str(checkout), "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert _git(str(checkout), "rev-parse", "--is-shallow-repository") == "true"
    assert _git(str(checkout), "rev-list", "--count", "HEAD") == "1"
    origin_main = _git(str(checkout), "rev-parse", "--verify", "refs/remotes/origin/main")
    assert origin_main == tip
    assert _git(str(checkout), "cat-file", "-t", origin_main) == "commit"

    root = checkout / "workspaces"
    task_id = "task_detached"
    workspace = root / task_id
    workspace.mkdir(parents=True)
    found = _find_base_git_dir(str(workspace))
    project_git = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".git"))
    assert os.path.normcase(found or "") == os.path.normcase(str(checkout / ".git"))
    assert os.path.normcase(found or "") != os.path.normcase(project_git)

    readme = workspace / "README.md"
    readme.write_text("eski\n", encoding="utf-8")
    first = deliver_task_workspace(task_id, str(root), ["README.md"])
    second = deliver_task_workspace(task_id, str(root), ["README.md"])
    assert first["status"] == "committed"
    assert first["commit"]
    assert second["status"] == "reused"
    assert second["commit"] == first["commit"]

    readme.write_text("yeni\n", encoding="utf-8")
    third = deliver_task_workspace(task_id, str(root), ["README.md"])
    assert third["status"] == "committed"
    assert third["commit"] != first["commit"]
    assert third["previous_commit"] == first["commit"]
    workspace_path, git_dir = _delivery_paths(str(root), task_id)
    assert _git(workspace_path, "rev-parse", "refs/delivery-base/main", git_dir=git_dir, work_tree=workspace_path) == tip
    assert _git(workspace_path, "rev-parse", f"{third['commit']}^", git_dir=git_dir, work_tree=workspace_path) == first["commit"]

    parallel_id = "task_detached_parallel"
    parallel = root / parallel_id
    parallel.mkdir()
    (parallel / "README.md").write_text("ortak\n", encoding="utf-8")
    barrier = threading.Barrier(2)
    results = []

    def _worker():
        barrier.wait(timeout=10)
        results.append(deliver_task_workspace(parallel_id, str(root), ["README.md"]))

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(results) == 2
    assert all(item["status"] in {"committed", "reused"} for item in results)
    assert len({item["commit"] for item in results}) == 1
    parallel_workspace, parallel_git = _delivery_paths(str(root), parallel_id)
    assert _git(
        parallel_workspace,
        "rev-parse",
        "refs/delivery-base/main",
        git_dir=parallel_git,
        work_tree=parallel_workspace,
    ) == tip

    _git(str(checkout), "update-ref", "-d", "refs/remotes/origin/main")
    still_missing = _git_result(str(checkout), "rev-parse", "--verify", "--end-of-options", "refs/heads/main")
    remote_missing = _git_result(str(checkout), "rev-parse", "--verify", "--end-of-options", "refs/remotes/origin/main")
    assert still_missing.returncode != 0
    assert remote_missing.returncode != 0
    assert _git(str(checkout), "rev-parse", "HEAD") == tip
    ambiguous = root / "task_ambiguous"
    ambiguous.mkdir()
    (ambiguous / "README.md").write_text("belirsiz\n", encoding="utf-8")
    refused = deliver_task_workspace("task_ambiguous", str(root), ["README.md"])
    assert refused["status"] == "failed"
    assert refused["commit"] is None
    assert "Detached HEAD taban kabul edilmedi" in str(refused["reason"])
    assert "refs/heads/main" in str(refused["reason"])
    assert "refs/remotes/origin/main" in str(refused["reason"])
    assert _git_result(str(checkout), "rev-parse", "--verify", "--end-of-options", "refs/heads/main").returncode != 0
