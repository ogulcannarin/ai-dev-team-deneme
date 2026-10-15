"""GitHub pull request teslimatı. Canlı API ve uzak depo kullanmaz."""

import base64
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from agent_workflow import delivery_node
from github_delivery import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubClient,
    GitHubConfig,
    GitHubNetworkError,
    GitHubResponse,
    git_push_ref,
    load_github_config,
    mask_secrets,
    publish_github_delivery,
)
from schemas import TaskStatus


TOKEN = "ghp_testtokenvalue123"
SHA = "a" * 40
SHA_NEXT = "b" * 40
TASK_ID = "task_pr"


class FakeGitHub:
    def __init__(self):
        self.remote = None
        self.pulls = []
        self.calls = []
        self.pushes = []
        self.mode = "ok"
        self.create_status = 201

    def request(self, method, path, json_body=None, query=None):
        self.calls.append({
            "method": method,
            "path": path,
            "json": json_body,
            "query": query,
        })
        if self.mode == "timeout":
            raise httpx.TimeoutException("timed out")
        if self.mode == "auth":
            return GitHubResponse(401, {"message": f"bad {TOKEN}"})
        if self.mode == "forbidden":
            return GitHubResponse(403, {"message": f"denied {TOKEN}"})
        if self.mode == "server":
            return GitHubResponse(502, {"message": f"down {TOKEN}"})
        if method == "GET" and "/git/refs/heads/" in path:
            if self.remote is None:
                return GitHubResponse(404, {"message": "not found"})
            return GitHubResponse(200, {"object": {"sha": self.remote}})
        if "/git/commits" in path or "/git/trees" in path or "/git/blobs" in path or path.endswith("/git/refs"):
            raise AssertionError("Git nesneleri REST ile yeniden oluşturulmamalı")
        if method == "GET" and path.endswith("/pulls"):
            return GitHubResponse(200, list(self.pulls))
        if method == "POST" and path.endswith("/pulls"):
            if self.create_status == 422:
                return GitHubResponse(422, getattr(self, "create_body", None) or {"message": "A pull request already exists"})
            pull = {
                "number": 9,
                "html_url": "https://github.com/acme/widgets/pull/9",
            }
            self.pulls.append(pull)
            return GitHubResponse(self.create_status, pull)
        raise AssertionError(f"beklenmeyen istek: {method} {path}")


def _config(**overrides) -> GitHubConfig:
    values = {
        "token": TOKEN,
        "owner": "acme",
        "repo": "widgets",
        "api_base": "https://api.github.com",
        "base_branch": "main",
    }
    values.update(overrides)
    return GitHubConfig(**values)


def _client(fake: FakeGitHub, ancestor=True, pusher=None, history=True) -> GitHubClient:
    def _push(**kwargs):
        fake.pushes.append(kwargs)
        fake.remote = kwargs["sha"]

    return GitHubClient(
        _config(),
        transport=fake,
        ancestor_check=lambda _remote, _local: ancestor,
        pusher=pusher or _push,
        history_check=lambda *_args: history,
    )


def _publish(fake: FakeGitHub, sha: str = SHA, ancestor: bool = True, pusher=None, history=True):
    return _client(fake, ancestor=ancestor, pusher=pusher, history=history).publish(
        task_id=TASK_ID,
        sha=sha,
        title="Deliver task",
        body="notlar",
        workspace="unused",
        git_dir="unused",
    )


def _assert_task_branch_only(fake: FakeGitHub):
    assert TOKEN not in json.dumps(fake.calls)
    assert TOKEN not in json.dumps(fake.pushes)
    expected = f"refs/heads/task/{TASK_ID}:refs/heads/task/{TASK_ID}"
    for push in fake.pushes:
        assert push["refspec"] == expected
        assert not push["refspec"].startswith("+")
        assert TOKEN not in push["remote_url"]
        assert push["remote_url"] == "https://github.com/acme/widgets.git"
        assert push["sha"]
    for call in fake.calls:
        path = call["path"]
        assert TOKEN not in path
        if call["query"]:
            assert TOKEN not in json.dumps(call["query"])
        assert not path.endswith("/git/refs")
        assert "/git/commits" not in path


def _configure(monkeypatch, repository=False):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    if repository:
        monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widgets")
        return
    monkeypatch.setenv("GITHUB_OWNER", "acme")
    monkeypatch.setenv("GITHUB_REPO", "widgets")


def _eligible(events=None):
    return {
        "task_id": TASK_ID,
        "status": TaskStatus.REVIEWED.value,
        "require_human_approval": True,
        "reviewer": {"verdict": "approved"},
        "tester": {"status": "tested", "passed": 2, "failed": 0},
        "coder": {"created_files": ["README.md"]},
        "events": list(events or [{"type": "task_approved", "details": {}}]),
        "error": None,
    }


def _local(sha=SHA, status="committed", previous=None):
    return {
        "status": status,
        "branch": f"task/{TASK_ID}",
        "commit": sha,
        "previous_commit": previous,
        "reason": None,
        "files": ["README.md"],
    }


def test_missing_or_placeholder_config_stays_disabled(monkeypatch):
    assert load_github_config() is None
    monkeypatch.setenv("GITHUB_OWNER", "acme")
    monkeypatch.setenv("GITHUB_REPO", "widgets")
    assert load_github_config() is None
    monkeypatch.setenv("GITHUB_TOKEN", "your-github-token-here")
    assert load_github_config() is None
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GITHUB_API_BASE", f"https://{TOKEN}@github.example")
    assert load_github_config() is None


def test_repository_env_and_defaults(monkeypatch):
    _configure(monkeypatch, repository=True)
    config = load_github_config()
    assert config is not None
    assert (config.owner, config.repo) == ("acme", "widgets")
    assert config.api_base == "https://api.github.com"
    assert config.base_branch == "main"
    monkeypatch.setenv("GITHUB_BASE_BRANCH", "develop")
    assert load_github_config().base_branch == "develop"


def test_push_is_blocked_without_shared_history():
    fake = FakeGitHub()
    with pytest.raises(GitHubAPIError, match="ortak geçmiş"):
        _publish(fake, history=False)
    assert fake.pushes == []
    assert not any(call["method"] == "POST" for call in fake.calls)


def test_pull_request_validation_error_keeps_safe_detail():
    fake = FakeGitHub()
    fake.create_status = 422
    fake.create_body = {
        "message": "Validation Failed",
        "errors": [{
            "resource": "PullRequest",
            "field": "head",
            "code": "invalid",
            "message": f"no history in common {TOKEN}",
        }],
    }
    with pytest.raises(GitHubAPIError) as caught:
        _publish(fake)
    message = str(caught.value)
    assert "Validation Failed" in message
    assert "head: no history in common" in message
    assert TOKEN not in message
    assert "[MASKED_KEY]" in message


def test_push_opens_one_pull_request():
    fake = FakeGitHub()
    result = _publish(fake)
    assert result["status"] == "opened"
    assert result["commit"] == SHA
    assert result["pr_number"] == 9
    assert result["branch"] == f"task/{TASK_ID}"
    assert result["base"] == "main"
    assert len(fake.pushes) == 1
    assert fake.pushes[0]["sha"] == SHA
    assert fake.pushes[0]["refspec"] == f"refs/heads/task/{TASK_ID}:refs/heads/task/{TASK_ID}"
    pulls = [call for call in fake.calls if call["method"] == "POST" and call["path"].endswith("/pulls")]
    assert len(pulls) == 1
    assert pulls[0]["json"]["head"] == f"task/{TASK_ID}"
    assert pulls[0]["json"]["base"] == "main"
    _assert_task_branch_only(fake)


def test_existing_pull_request_is_reused():
    fake = FakeGitHub()
    fake.remote = SHA
    fake.pulls.append({"number": 4, "html_url": "https://github.com/acme/widgets/pull/4"})
    result = _publish(fake)
    assert result["status"] == "reused"
    assert result["pr_number"] == 4
    assert not any(call["method"] == "POST" for call in fake.calls)
    _assert_task_branch_only(fake)


def test_same_sha_retries_do_not_open_another_pull_request():
    fake = FakeGitHub()
    first = _publish(fake)
    second = _publish(fake)
    assert first["status"] == "opened"
    assert second["status"] == "reused"
    assert second["pr_number"] == 9
    assert sum(1 for call in fake.calls if call["method"] == "POST" and call["path"].endswith("/pulls")) == 1
    assert len(fake.pushes) == 1
    assert fake.pushes[0]["sha"] == SHA
    _assert_task_branch_only(fake)


def test_push_without_saved_pr_is_completed_on_retry():
    fake = FakeGitHub()
    fake.remote = SHA
    result = _publish(fake)
    assert result["status"] == "opened"
    assert fake.pushes == []
    assert sum(1 for call in fake.calls if call["method"] == "POST" and call["path"].endswith("/pulls")) == 1


def test_existing_pull_request_race_is_reused():
    fake = FakeGitHub()
    fake.remote = SHA
    fake.create_status = 422

    def request(method, path, json_body=None, query=None):
        if method == "POST" and path.endswith("/pulls"):
            fake.pulls.append({"number": 5, "html_url": "https://github.com/acme/widgets/pull/5"})
        return FakeGitHub.request(fake, method, path, json_body, query)

    fake.request = request
    result = _publish(fake)
    assert result["status"] == "reused"
    assert result["pr_number"] == 5
    assert sum(1 for call in fake.calls if call["method"] == "POST" and call["path"].endswith("/pulls")) == 1


def test_changed_content_updates_branch_and_reuses_pull_request():
    fake = FakeGitHub()
    _publish(fake, SHA)
    updated = _publish(fake, SHA_NEXT)
    assert updated["status"] == "reused"
    assert updated["commit"] == SHA_NEXT
    assert updated["pr_number"] == 9
    assert [item["sha"] for item in fake.pushes] == [SHA, SHA_NEXT]
    assert all(not item["refspec"].startswith("+") for item in fake.pushes)
    assert sum(1 for call in fake.calls if call["method"] == "POST" and call["path"].endswith("/pulls")) == 1
    _assert_task_branch_only(fake)


def test_non_fast_forward_does_not_force_push():
    fake = FakeGitHub()
    fake.remote = SHA
    with pytest.raises(GitHubAPIError, match="Force push yapılmadı"):
        _publish(fake, SHA_NEXT, ancestor=False)
    assert fake.remote == SHA
    assert fake.pushes == []


@pytest.mark.parametrize(
    ("mode", "error_type", "text"),
    [
        ("auth", GitHubAuthError, "kimlik doğrulaması"),
        ("forbidden", GitHubAuthError, "kimlik doğrulaması"),
        ("timeout", GitHubNetworkError, "zaman aşımı"),
        ("server", GitHubAPIError, "502"),
    ],
)
def test_github_errors_are_distinct_and_mask_token(mode, error_type, text):
    fake = FakeGitHub()
    fake.mode = mode
    with pytest.raises(error_type) as caught:
        _publish(fake)
    message = str(caught.value)
    assert text in message
    assert TOKEN not in message
    if mode == "server":
        assert "[MASKED_KEY]" in message
    assert fake.pushes == []
    assert not any(call["method"] == "POST" for call in fake.calls)


def _helper_script(command: str):
    marker = "credential_helper.py"
    if '"' not in command or marker not in command:
        return None
    parts = [part for part in command.split('"') if marker in part]
    if not parts:
        return None
    return parts[0].replace("/", os.sep)


def test_git_push_keeps_sha_refspec_and_token_out_of_argv():
    seen = {}

    def runner(args, workspace, env):
        seen["args"] = list(args)
        seen["env"] = dict(env)
        script = _helper_script(env["GIT_CONFIG_VALUE_1"])
        seen["script"] = script
        seen["script_text"] = open(script, encoding="utf-8").read()
        return subprocess.CompletedProcess(args, 0, "", "")

    git_push_ref(
        workspace="unused",
        git_dir="unused-git",
        remote_url="https://github.com/acme/widgets.git",
        refspec=f"refs/heads/task/{TASK_ID}:refs/heads/task/{TASK_ID}",
        token=TOKEN,
        runner=runner,
    )
    assert seen["args"] == [
        "push",
        "--no-force",
        "--",
        "https://github.com/acme/widgets.git",
        f"refs/heads/task/{TASK_ID}:refs/heads/task/{TASK_ID}",
    ]
    rendered = " ".join(seen["args"])
    assert TOKEN not in rendered
    assert "main" not in rendered
    assert "+" not in seen["args"][-1]
    assert seen["env"]["GIT_CONFIG_COUNT"] == "2"
    assert seen["env"]["GIT_CONFIG_KEY_0"] == "credential.helper"
    assert seen["env"]["GIT_CONFIG_VALUE_0"] == ""
    assert seen["env"]["GIT_CONFIG_KEY_1"] == "credential.helper"
    config_text = " ".join(
        f"{key}={value}"
        for key, value in seen["env"].items()
        if key.startswith("GIT_CONFIG_")
    )
    assert "extraheader" not in config_text.lower()
    assert "authorization" not in config_text.lower()
    assert "bearer" not in config_text.lower()
    assert TOKEN not in config_text
    helper = seen["env"]["GIT_CONFIG_VALUE_1"]
    assert TOKEN not in helper
    assert helper.startswith("!f()")
    assert "credential_helper.py" in helper
    assert seen["env"]["AI_DEV_TEAM_GIT_PASSWORD"] == TOKEN
    assert seen["env"]["GCM_INTERACTIVE"] == "Never"
    assert TOKEN not in seen["script_text"]
    assert "x-access-token" in seen["script_text"]
    assert "extraheader" not in rendered.lower()
    assert seen["script"] is not None and not os.path.exists(seen["script"])
    assert not os.path.exists(os.path.dirname(seen["script"]))


def test_git_credential_helper_answers_username_without_a_prompt():
    seen = {}

    def runner(args, workspace, env):
        probe = dict(env)
        probe.pop("GIT_DIR", None)
        probe.pop("GIT_WORK_TREE", None)
        seen["result"] = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=example.invalid\n\n",
            capture_output=True,
            text=True,
            env=probe,
            timeout=20,
            check=False,
        )
        seen["script"] = _helper_script(env["GIT_CONFIG_VALUE_1"])
        return subprocess.CompletedProcess(args, 0, "", "")

    git_push_ref(
        workspace="unused",
        git_dir="unused-git",
        remote_url="https://github.com/acme/widgets.git",
        refspec=f"refs/heads/task/{TASK_ID}:refs/heads/task/{TASK_ID}",
        token=TOKEN,
        runner=runner,
    )
    result = seen["result"]
    assert result.returncode == 0
    assert TOKEN not in result.stderr
    assert "terminal prompts disabled" not in result.stderr.lower()
    assert "username=x-access-token" in result.stdout
    assert f"password={TOKEN}" in result.stdout
    assert seen["script"] is not None and not os.path.exists(seen["script"])


def test_git_push_env_sends_basic_without_bearer():
    records = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            auths = self.headers.get_all("Authorization") or []
            schemes = []
            basic_ok = False
            for value in auths:
                scheme, _, rest = value.partition(" ")
                schemes.append(scheme)
                if scheme.lower() != "basic" or not rest:
                    continue
                decoded = base64.b64decode(rest).decode("utf-8", errors="replace")
                user, _, password = decoded.partition(":")
                basic_ok = user == "x-access-token" and password == TOKEN
            records.append({"schemes": schemes, "basic_ok": basic_ok})
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="GitHub"')
            self.end_headers()

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        def runner(args, workspace, env):
            probe = dict(env)
            probe.pop("GIT_DIR", None)
            probe.pop("GIT_WORK_TREE", None)
            completed = subprocess.run(
                ["git", "ls-remote", f"http://127.0.0.1:{port}/acme/widgets.git"],
                cwd=os.environ.get("TEMP") or os.environ.get("TMP"),
                env=probe,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            assert TOKEN not in completed.stderr
            assert TOKEN not in completed.stdout
            return subprocess.CompletedProcess(args, 0, "", "")

        git_push_ref(
            workspace="unused",
            git_dir="unused-git",
            remote_url="https://github.com/acme/widgets.git",
            refspec=f"refs/heads/task/{TASK_ID}:refs/heads/task/{TASK_ID}",
            token=TOKEN,
            runner=runner,
        )
    finally:
        server.shutdown()

    assert records
    assert all("Bearer" not in record["schemes"] for record in records)
    assert any(record["basic_ok"] for record in records)


def test_git_push_error_masks_token_and_rejects_main():
    def runner(args, workspace, env):
        return subprocess.CompletedProcess(
            args,
            128,
            "",
            f"fatal: could not read Username for 'https://github.com': terminal prompts disabled {TOKEN}",
        )

    with pytest.raises(GitHubAuthError) as caught:
        git_push_ref(
            workspace="unused",
            git_dir="unused-git",
            remote_url="https://github.com/acme/widgets.git",
            refspec=f"refs/heads/task/{TASK_ID}:refs/heads/task/{TASK_ID}",
            token=TOKEN,
            runner=runner,
        )
    assert TOKEN not in str(caught.value)
    with pytest.raises(GitHubAPIError, match="Ana dala push yapılmadı"):
        git_push_ref(
            workspace="unused",
            git_dir="unused-git",
            remote_url="https://github.com/acme/widgets.git",
            refspec="refs/heads/main:refs/heads/main",
            token=TOKEN,
            runner=runner,
        )


def test_remote_sha_mismatch_after_push_does_not_open_pull_request():
    fake = FakeGitHub()

    def _diverge(**kwargs):
        fake.pushes.append(kwargs)
        fake.remote = "c" * 40

    with pytest.raises(GitHubAPIError, match="yerel SHA ile eşleşmedi"):
        _publish(fake, pusher=_diverge)
    assert fake.pushes[0]["sha"] == SHA
    assert not any(call["method"] == "POST" and call["path"].endswith("/pulls") for call in fake.calls)
    assert mask_secrets(TOKEN, TOKEN) == "[MASKED_KEY]"


def test_unconfigured_delivery_keeps_local_success(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("GitHub yapılandırması yokken çağrıldı")

    monkeypatch.setattr("agent_workflow.publish_github_delivery", _forbidden)
    monkeypatch.setattr("agent_workflow.deliver_task_workspace", lambda *_args, **_kwargs: _local())
    result = delivery_node(_eligible())
    assert result["status"] == TaskStatus.COMPLETED.value
    assert [event["type"] for event in result["events"]].count("delivery_committed") == 1
    assert not any(event["type"].startswith("github_") for event in result["events"])


def test_configured_delivery_records_opened_pull_request(monkeypatch):
    _configure(monkeypatch)
    calls = []

    def _publish(*_args, **_kwargs):
        calls.append(_args)
        return {
            "status": "opened",
            "branch": f"task/{TASK_ID}",
            "commit": SHA,
            "base": "main",
            "pr_number": 9,
            "pr_url": f"https://github.com/acme/widgets/pull/9?token={TOKEN}",
        }

    monkeypatch.setattr("agent_workflow.publish_github_delivery", _publish)
    monkeypatch.setattr("agent_workflow.deliver_task_workspace", lambda *_args, **_kwargs: _local())
    result = delivery_node(_eligible())
    assert result["status"] == TaskStatus.COMPLETED.value
    assert result["error"] is None
    opened = [event for event in result["events"] if event["type"] == "github_pr_opened"]
    assert len(opened) == 1
    assert opened[0]["details"]["commit"] == SHA
    assert opened[0]["details"]["pr_number"] == 9
    assert TOKEN not in json.dumps(result["events"])
    assert TOKEN not in str(result["error"])

    again = delivery_node(result)
    assert again["status"] == TaskStatus.COMPLETED.value
    assert len(calls) == 1
    assert sum(1 for event in again["events"] if event["type"] == "github_pr_opened") == 1
    assert sum(1 for event in again["events"] if event["type"] == "delivery_committed") == 1


def test_recorded_sha_without_pull_request_is_finished_without_a_new_commit(monkeypatch):
    _configure(monkeypatch)
    calls = []

    def _publish(*_args, **_kwargs):
        calls.append(1)
        return {
            "status": "reused",
            "branch": f"task/{TASK_ID}",
            "commit": SHA,
            "base": "main",
            "pr_number": 4,
            "pr_url": "https://github.com/acme/widgets/pull/4",
        }

    monkeypatch.setattr("agent_workflow.publish_github_delivery", _publish)
    monkeypatch.setattr(
        "agent_workflow.deliver_task_workspace",
        lambda *_args, **_kwargs: _local(status="reused"),
    )
    state = _eligible([{
        "type": "task_approved",
        "details": {},
    }, {
        "type": "delivery_committed",
        "details": {"commit": SHA, "branch": f"task/{TASK_ID}"},
    }])
    result = delivery_node(state)
    assert calls == [1]
    assert result["status"] == TaskStatus.COMPLETED.value
    assert sum(1 for event in result["events"] if event["type"] == "delivery_committed") == 1
    reused = [event for event in result["events"] if event["type"] == "github_pr_reused"]
    assert len(reused) == 1
    assert reused[0]["details"]["commit"] == SHA


def test_local_failure_does_not_call_github(monkeypatch):
    _configure(monkeypatch)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Yerel teslimat başarısızken GitHub çağrıldı")

    monkeypatch.setattr("agent_workflow.publish_github_delivery", _forbidden)
    monkeypatch.setattr(
        "agent_workflow.deliver_task_workspace",
        lambda *_args, **_kwargs: {
            "status": "failed",
            "branch": f"task/{TASK_ID}",
            "commit": None,
            "previous_commit": None,
            "reason": "Commit tamamlanamadı",
            "files": ["README.md"],
        },
    )
    result = delivery_node(_eligible())
    assert result["status"] == TaskStatus.DELIVERY_FAILED.value
    assert result["events"][-1]["type"] == "delivery_failed"
    assert result["events"][-1]["details"]["commit"] is None


@pytest.mark.parametrize(
    ("error", "event_type"),
    [
        (GitHubAuthError("GitHub kimlik doğrulaması başarısız. Pull request açılmadı."), "github_auth_failed"),
        (GitHubNetworkError("GitHub isteği zaman aşımına uğradı."), "github_network_failed"),
        (GitHubAPIError(f"GitHub API hatası (502). down [MASKED_KEY]"), "github_failed"),
    ],
)
def test_github_failure_keeps_local_sha_and_is_idempotent(monkeypatch, error, event_type):
    _configure(monkeypatch)

    def _publish(*_args, **_kwargs):
        raise error

    monkeypatch.setattr("agent_workflow.publish_github_delivery", _publish)
    monkeypatch.setattr("agent_workflow.deliver_task_workspace", lambda *_args, **_kwargs: _local())
    first = delivery_node(_eligible())
    assert first["status"] == TaskStatus.DELIVERY_FAILED.value
    assert TOKEN not in json.dumps(first["events"])
    assert TOKEN not in str(first["error"])
    committed = [event for event in first["events"] if event["type"] == "delivery_committed"]
    assert len(committed) == 1
    assert committed[0]["details"]["commit"] == SHA
    assert sum(1 for event in first["events"] if event["type"] == event_type) == 1

    second = delivery_node(first)
    assert second["status"] == TaskStatus.DELIVERY_FAILED.value
    assert sum(1 for event in second["events"] if event["type"] == "delivery_committed") == 1
    assert sum(1 for event in second["events"] if event["type"] == event_type) == 1


def test_publish_entrypoint_uses_injected_client(tmp_path):
    fake = FakeGitHub()
    (tmp_path / TASK_ID).mkdir()
    result = publish_github_delivery(
        TASK_ID,
        str(tmp_path),
        SHA,
        "Deliver task",
        f"not {TOKEN}",
        client=_client(fake),
    )
    assert result["status"] == "opened"
    body = [call for call in fake.calls if call["method"] == "POST" and call["path"].endswith("/pulls")][0]
    assert TOKEN not in body["json"]["body"]
    assert "[MASKED_KEY]" in body["json"]["body"]
    _assert_task_branch_only(fake)
