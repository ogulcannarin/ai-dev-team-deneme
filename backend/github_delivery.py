"""
GitHub pull request teslimatı.

Yerel commit bu modülde oluşturulmaz. Nesneler git push --no-force ile
task/{task_id} dalına aynen aktarılır. Branch sorgusu ve pull request
GitHub REST API ile yapılır. Ana dala push, merge ve force push yapılmaz.
Token URL'de, Git argümanlarında, olayda ve hata metninde yer almaz.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Callable, Dict, Optional
from urllib.parse import urlsplit

import httpx

from git_delivery import (
    _DeliveryLock,
    _git_dir_for,
    _git_env,
    _run_git,
    _sha_ok,
    _workspace_path,
    branch_name_for,
)


class GitHubDeliveryError(Exception):
    """GitHub teslimat hatası. İleti gizli bilgi içermez."""


class GitHubAuthError(GitHubDeliveryError):
    """Kimlik doğrulama veya yetki hatası."""


class GitHubNetworkError(GitHubDeliveryError):
    """Ağ kesintisi veya zaman aşımı."""


class GitHubAPIError(GitHubDeliveryError):
    """GitHub API'nin reddettiği veya doğrulanamayan işlem."""


_PLACEHOLDER_TOKENS = {
    "",
    "your-github-token-here",
    "your-token",
    "changeme",
}
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")


@dataclass(frozen=True)
class GitHubConfig:
    token: str
    owner: str
    repo: str
    api_base: str
    base_branch: str


@dataclass(frozen=True)
class GitHubResponse:
    status: int
    body: object


def mask_secrets(text: str, token: Optional[str] = None) -> str:
    """Hata gövdesindeki token ve bearer değerlerini maskeler."""
    if not text:
        return ""
    masked = text
    if token:
        masked = masked.replace(token, "[MASKED_KEY]")
    masked = re.sub(r"github_pat_[A-Za-z0-9_]+", "[MASKED_KEY]", masked)
    masked = re.sub(r"gh[pousr]_[A-Za-z0-9]+", "[MASKED_KEY]", masked)
    masked = re.sub(r"(?i)bearer\s+\S+", "Bearer [MASKED_KEY]", masked)
    return masked


def load_github_config() -> Optional[GitHubConfig]:
    """
    Tam yapılandırma yoksa None döner. Bu durumda yerel teslimat yalnız devam eder.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token in _PLACEHOLDER_TOKENS:
        return None
    owner, repo = _repository_names()
    if not owner or not repo:
        return None
    if not _NAME_PATTERN.match(owner) or not _NAME_PATTERN.match(repo):
        return None
    api_base = os.environ.get("GITHUB_API_BASE", "https://api.github.com").strip().rstrip("/")
    if not api_base:
        api_base = "https://api.github.com"
    base_branch = os.environ.get("GITHUB_BASE_BRANCH", "main").strip() or "main"
    if not _safe_api_base(api_base, token) or not _safe_branch(base_branch):
        return None
    return GitHubConfig(
        token=token,
        owner=owner,
        repo=repo,
        api_base=api_base,
        base_branch=base_branch,
    )


def _repository_names() -> tuple:
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repository.count("/") == 1:
        owner, repo = repository.split("/", 1)
        owner = owner.strip()
        repo = repo.strip()
        if owner and repo:
            return owner, repo
    owner = os.environ.get("GITHUB_OWNER", "").strip()
    repo = os.environ.get("GITHUB_REPO", "").strip()
    if owner and repo:
        return owner, repo
    return "", ""


def _safe_api_base(api_base: str, token: str) -> bool:
    parsed = urlsplit(api_base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return False
    if token and token in api_base:
        return False
    return True


def _safe_branch(branch: str) -> bool:
    return bool(_BRANCH_PATTERN.match(branch) and ".." not in branch and not branch.startswith(("-", "/")))


class HttpxTransport:
    """Token'ı yalnızca Authorization başlığına koyar. URL'ye yazmaz."""

    def __init__(self, config: GitHubConfig):
        self._token = config.token
        self._base = config.api_base
        self._timeout = 20.0

    def request(
        self,
        method: str,
        path: str,
        json_body: Optional[dict] = None,
        query: Optional[dict] = None,
    ) -> GitHubResponse:
        url = f"{self._base}{path}"
        if self._token and self._token in url:
            raise GitHubAPIError("GitHub isteği oluşturulmadı.")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-dev-team",
        }
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=False, trust_env=False) as client:
                response = client.request(method, url, headers=headers, json=json_body, params=query)
        except httpx.TimeoutException:
            raise GitHubNetworkError("GitHub isteği zaman aşımına uğradı.") from None
        except httpx.HTTPError:
            raise GitHubNetworkError("GitHub ağına bağlanılamadı.") from None
        body: object
        try:
            body = response.json()
        except ValueError:
            body = {"message": mask_secrets(response.text or "", self._token)[:180]}
        return GitHubResponse(status=response.status_code, body=body)


class GitHubClient:
    def __init__(
        self,
        config: GitHubConfig,
        transport=None,
        ancestor_check: Optional[Callable[[str, str], bool]] = None,
        pusher: Optional[Callable[..., None]] = None,
    ):
        self.config = config
        self.transport = transport or HttpxTransport(config)
        self._ancestor_check = ancestor_check
        self._pusher = pusher

    def publish(
        self,
        *,
        task_id: str,
        sha: str,
        title: str,
        body: str,
        workspace: str,
        git_dir: str,
    ) -> Dict[str, object]:
        branch = branch_name_for(task_id)
        self._assert_task_branch(branch)
        if not _sha_ok(sha) or len(sha) != 40:
            raise GitHubAPIError("Geçersiz commit. Push yapılmadı.")
        remote_sha = self._remote_sha(branch)
        if remote_sha != sha:
            if remote_sha is not None and not self._can_fast_forward(remote_sha, sha, workspace, git_dir):
                raise GitHubAPIError(
                    "Uzak görev dalı yerel commit ile hızlı ileri alınamıyor. Force push yapılmadı."
                )
            self._push_branch(branch, sha, workspace, git_dir)
            confirmed = self._remote_sha(branch)
            if confirmed != sha:
                raise GitHubAPIError("Uzak dal yerel SHA ile eşleşmedi. Force push yapılmadı.")
        pull = self._ensure_pull_request(branch, title, body)
        return {
            "status": pull["status"],
            "branch": branch,
            "commit": sha,
            "base": self.config.base_branch,
            "pr_number": pull["number"],
            "pr_url": pull["url"],
        }

    def _push_branch(self, branch: str, sha: str, workspace: str, git_dir: str) -> None:
        remote_url = git_remote_url(self.config)
        refspec = f"refs/heads/{branch}:refs/heads/{branch}"
        _assert_push_contract(remote_url, refspec, self.config.token, branch, self.config.base_branch)
        if self._pusher is not None:
            self._pusher(
                remote_url=remote_url,
                refspec=refspec,
                sha=sha,
                workspace=workspace,
                git_dir=git_dir,
            )
            return
        git_push_ref(
            workspace=workspace,
            git_dir=git_dir,
            remote_url=remote_url,
            refspec=refspec,
            token=self.config.token,
        )

    def _assert_task_branch(self, branch: str) -> None:
        base = self.config.base_branch
        if (
            branch == base
            or branch in {"main", "master"}
            or branch.startswith("+")
            or not branch.startswith("task/")
        ):
            raise GitHubAPIError("Ana dala push yapılmadı.")

    def _request(
        self,
        method: str,
        path: str,
        json_body: Optional[dict] = None,
        query: Optional[dict] = None,
    ) -> GitHubResponse:
        token = self.config.token
        if token and token in path:
            raise GitHubAPIError("GitHub isteği oluşturulmadı.")
        if query and any(token and token in str(value) for value in query.values()):
            raise GitHubAPIError("GitHub isteği oluşturulmadı.")
        try:
            return self.transport.request(method, path, json_body=json_body, query=query)
        except GitHubNetworkError:
            raise
        except httpx.TimeoutException:
            raise GitHubNetworkError("GitHub isteği zaman aşımına uğradı.") from None
        except httpx.HTTPError:
            raise GitHubNetworkError("GitHub ağına bağlanılamadı.") from None

    def _remote_sha(self, branch: str) -> Optional[str]:
        response = self._request("GET", self._ref_path(branch))
        if response.status == 404:
            return None
        self._raise_for_status(response)
        if not isinstance(response.body, dict):
            raise GitHubAPIError("GitHub branch yanıtı okunamadı.")
        sha = str((response.body.get("object") or {}).get("sha") or "")
        if not _sha_ok(sha):
            raise GitHubAPIError("GitHub branch commit'i okunamadı.")
        return sha

    def _ref_path(self, branch: str) -> str:
        return f"/repos/{self.config.owner}/{self.config.repo}/git/refs/heads/{branch}"

    def _can_fast_forward(self, remote_sha: str, sha: str, workspace: str, git_dir: str) -> bool:
        if self._ancestor_check is not None:
            return bool(self._ancestor_check(remote_sha, sha))
        if not os.path.isdir(git_dir):
            return False
        env = _git_env(workspace, git_dir)
        result = _run_git(
            ["merge-base", "--is-ancestor", remote_sha, sha],
            workspace,
            env,
        )
        return result.returncode == 0

    def _ensure_pull_request(self, branch: str, title: str, body: str) -> Dict[str, object]:
        existing = self._find_open_pull_request(branch)
        if existing is not None:
            return {"status": "reused", **existing}
        response = self._request(
            "POST",
            f"/repos/{self.config.owner}/{self.config.repo}/pulls",
            {
                "title": mask_secrets(title, self.config.token)[:120],
                "head": branch,
                "base": self.config.base_branch,
                "body": mask_secrets(body, self.config.token)[:4000],
            },
        )
        if response.status == 422 and _mentions_existing_pull_request(response.body):
            existing = self._find_open_pull_request(branch)
            if existing is not None:
                return {"status": "reused", **existing}
        self._raise_for_status(response)
        parsed = _pull_request_fields(response.body, self.config.token)
        return {"status": "opened", **parsed}

    def _find_open_pull_request(self, branch: str) -> Optional[Dict[str, object]]:
        response = self._request(
            "GET",
            f"/repos/{self.config.owner}/{self.config.repo}/pulls",
            query={
                "head": f"{self.config.owner}:{branch}",
                "base": self.config.base_branch,
                "state": "open",
                "per_page": "1",
            },
        )
        self._raise_for_status(response)
        if not isinstance(response.body, list) or not response.body:
            return None
        return _pull_request_fields(response.body[0], self.config.token)

    def _raise_for_status(self, response: GitHubResponse) -> None:
        if 200 <= response.status < 300:
            return
        if 300 <= response.status < 400:
            raise GitHubAPIError("GitHub yönlendirmesi izlenmedi.")
        message = _safe_api_message(response.status, response.body, self.config.token)
        if response.status in {401, 403}:
            raise GitHubAuthError(message)
        raise GitHubAPIError(message)


def git_remote_url(config: GitHubConfig) -> str:
    """Token içermeyen HTTPS remote adresi."""
    if config.api_base.rstrip("/") == "https://api.github.com":
        base = "https://github.com"
    else:
        parsed = urlsplit(config.api_base)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise GitHubAPIError("Git push oluşturulmadı.")
        port = f":{parsed.port}" if parsed.port else ""
        base = f"https://{parsed.hostname}{port}"
    url = f"{base}/{config.owner}/{config.repo}.git"
    if config.token and config.token in url:
        raise GitHubAPIError("Git push oluşturulmadı.")
    return url


_GIT_PASSWORD_ENV = "AI_DEV_TEAM_GIT_PASSWORD"
_CREDENTIAL_HELPER = """import os
import sys

action = sys.argv[1] if len(sys.argv) > 1 else "get"
sys.stdin.read()
if action != "get":
    raise SystemExit(0)
password = os.environ.get("AI_DEV_TEAM_GIT_PASSWORD", "")
if not password:
    raise SystemExit(1)
sys.stdout.write("username=x-access-token\\n")
sys.stdout.write("password=" + password + "\\n")
"""


def _credential_helper_command(script_path: str) -> str:
    """Token içermeyen, yalnızca bu push sürecinde çalışan kimlik yardımcısı."""
    python = os.path.abspath(sys.executable).replace("\\", "/")
    script = os.path.abspath(script_path).replace("\\", "/")
    if any(char in value for value in (python, script) for char in "\"'$`\n\r"):
        raise GitHubAPIError("Git kimlik yardımcısı oluşturulamadı.")
    return f'!f() {{ "{python}" "{script}" "$1"; }}; f'


def git_push_ref(
    *,
    workspace: str,
    git_dir: str,
    remote_url: str,
    refspec: str,
    token: str,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> None:
    """
    Yerel nesneleri aynı SHA ile gönderir.
    Token URL'de ve git argümanlarında durmaz. Bu sürecin Git yapılandırması
    Authorization başlığı eklemez; Git, Basic kimliği tek kullanımlık
    yardımcının süreç ortamındaki parolasıyla üretir.
    """
    branch = refspec.split(":", 1)[0].removeprefix("refs/heads/")
    _assert_push_contract(remote_url, refspec, token, branch, "")
    env = _git_env(workspace, git_dir)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    args = ["push", "--no-force", "--", remote_url, refspec]
    if token and any(token in arg for arg in args):
        raise GitHubAPIError("Git push oluşturulmadı.")
    helper_dir = tempfile.mkdtemp(prefix="aidev-git-auth-")
    try:
        script_path = os.path.join(helper_dir, "credential_helper.py")
        with open(script_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_CREDENTIAL_HELPER)
        helper = _credential_helper_command(script_path)
        if token and token in helper:
            raise GitHubAPIError("Git push oluşturulmadı.")
        env["GIT_CONFIG_COUNT"] = "2"
        env["GIT_CONFIG_KEY_0"] = "credential.helper"
        env["GIT_CONFIG_VALUE_0"] = ""
        env["GIT_CONFIG_KEY_1"] = "credential.helper"
        env["GIT_CONFIG_VALUE_1"] = helper
        env[_GIT_PASSWORD_ENV] = token
        try:
            completed = (runner or _run_git)(args, workspace, env)
        except subprocess.TimeoutExpired:
            raise GitHubNetworkError("Git push zaman aşımına uğradı.") from None
    finally:
        shutil.rmtree(helper_dir, ignore_errors=True)
    if completed.returncode == 0:
        return
    detail = mask_secrets((completed.stderr or completed.stdout or "").strip(), token)
    lowered = detail.lower()
    if any(marker in lowered for marker in ("authentication", "authorization", "401", "403", "terminal prompts disabled")):
        raise GitHubAuthError("GitHub kimlik doğrulaması başarısız. Push yapılmadı.")
    if any(marker in lowered for marker in ("could not resolve", "unable to access", "timed out", "connection", "network")):
        raise GitHubNetworkError("GitHub ağına bağlanılamadı. Push yapılmadı.")
    if any(marker in lowered for marker in ("non-fast-forward", "failed to push", "rejected")):
        raise GitHubAPIError("Uzak görev dalı hızlı ileri alınamıyor. Force push yapılmadı.")
    suffix = detail.splitlines()[0][:160] if detail else "bilinmeyen hata"
    raise GitHubAPIError(f"Git push tamamlanamadı. {suffix}")


def _assert_push_contract(remote_url: str, refspec: str, token: str, branch: str, base_branch: str) -> None:
    parsed = urlsplit(remote_url)
    destination = refspec.split(":", 1)[-1]
    protected = {"refs/heads/main", "refs/heads/master"}
    if base_branch:
        protected.add(f"refs/heads/{base_branch}")
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or not parsed.netloc
        or (token and (token in remote_url or token in refspec))
        or refspec != f"refs/heads/{branch}:refs/heads/{branch}"
        or refspec.startswith("+")
        or "+" in refspec
        or destination in protected
        or not destination.startswith("refs/heads/task/")
    ):
        raise GitHubAPIError("Ana dala push yapılmadı.")


def publish_github_delivery(
    task_id: str,
    workspaces_root: str,
    sha: str,
    title: str,
    body: str,
    client: Optional[GitHubClient] = None,
) -> Dict[str, object]:
    """Görev kilidi içinde uzak dalı ve pull request'i uzlaştırır."""
    config = client.config if client is not None else load_github_config()
    if config is None:
        raise GitHubAPIError("GitHub yapılandırması yok. Pull request açılmadı.")
    if client is None:
        client = GitHubClient(config)
    try:
        workspace = _workspace_path(task_id, workspaces_root)
        git_dir = _git_dir_for(task_id, workspaces_root)
    except ValueError as exc:
        raise GitHubAPIError("Görev yolu doğrulanamadı. Pull request açılmadı.") from None
    lock_path = os.path.join(os.path.dirname(git_dir), f"{task_id}.lock")
    try:
        with _DeliveryLock(task_id, lock_path):
            return client.publish(
                task_id=task_id,
                sha=sha,
                title=title,
                body=body,
                workspace=workspace,
                git_dir=git_dir,
            )
    except TimeoutError:
        raise GitHubAPIError("Teslimat kilidi alınamadı. Pull request açılmadı.") from None


def _safe_api_message(status: int, body: object, token: str) -> str:
    if status in {401, 403}:
        return "GitHub kimlik doğrulaması başarısız. Pull request açılmadı."
    detail = mask_secrets(_body_message(body), token)[:160] or "istek reddedildi"
    if status >= 500:
        return f"GitHub API hatası ({status}). {detail}"
    return f"GitHub API hatası ({status}). {detail}"


def _body_message(body: object) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or "")
    if isinstance(body, str):
        return body
    return ""


def _mentions_existing_pull_request(body: object) -> bool:
    text = _body_message(body).lower()
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list):
            text = f"{text} {errors}".lower()
    return "already exists" in text


def _pull_request_fields(body: object, token: str) -> Dict[str, object]:
    if not isinstance(body, dict) or not isinstance(body.get("number"), int):
        raise GitHubAPIError("GitHub pull request yanıtı okunamadı.")
    url = str(body.get("html_url") or "")
    if token and token in url:
        url = ""
    url = mask_secrets(url, token)
    return {"number": body["number"], "url": url}
