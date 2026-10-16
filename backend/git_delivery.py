"""
Görev çalışma alanı için izole Git teslimatı.

Git deposu görev klasörünün içinde değil, backend/workspaces/.delivery/{task_id}.git
altında tutulur. GIT_DIR ve GIT_WORK_TREE açıkça ayarlanır. Ana branch'e geçilmez ve merge yapılmaz.
"""

import os
import shutil
import stat
import subprocess
import threading
import time
from typing import Dict, List, Optional

_TASK_ID_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"
_ALLOWED_FILENAMES = {
    "main.py",
    "api_feature.py",
    "models.py",
    "middleware.py",
    "rate_limiter.py",
    "auth.py",
    "schemas.py",
    "calculator.py",
    "math_utils.py",
    "email_filter.py",
    "date_utils.py",
    "utils.py",
    "service.py",
    "helpers.py",
    "test_feature.py",
    "README.md",
}


def _valid_task_id(task_id: str) -> bool:
    import re
    return bool(task_id and isinstance(task_id, str) and re.match(_TASK_ID_PATTERN, task_id))


def branch_name_for(task_id: str) -> str:
    if not _valid_task_id(task_id):
        raise ValueError("Geçersiz görev kimliği. Branch oluşturulmadı.")
    return f"task/{task_id}"


def _result(status: str, branch: Optional[str] = None, commit: Optional[str] = None,
            reason: Optional[str] = None, files: Optional[List[str]] = None,
            previous_commit: Optional[str] = None) -> Dict[str, object]:
    return {
        "status": status,
        "branch": branch,
        "commit": commit,
        "previous_commit": previous_commit,
        "reason": reason,
        "files": files or [],
    }


_LOCK_GUARD = threading.Lock()
_TASK_LOCKS: Dict[str, threading.Lock] = {}


class _DeliveryLock:
    """Aynı görev deposunu süreç içi ve süreçler arası teslimatların bozmasını engeller."""

    def __init__(self, task_id: str, lock_path: str):
        self.lock_path = lock_path
        self._thread_lock: Optional[threading.Lock] = None
        self._file = None
        with _LOCK_GUARD:
            self._thread_lock = _TASK_LOCKS.setdefault(task_id, threading.Lock())

    def __enter__(self) -> "_DeliveryLock":
        assert self._thread_lock is not None
        if not self._thread_lock.acquire(timeout=30):
            raise TimeoutError("Teslimat kilidi alınamadı. Commit oluşturulmadı.")
        try:
            os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
            self._file = open(self.lock_path, "a+b")
            self._file.seek(0, os.SEEK_END)
            if self._file.tell() == 0:
                self._file.write(b"\0")
                self._file.flush()
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt
                deadline = time.monotonic() + 30
                while True:
                    try:
                        msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Teslimat dosya kilidi alınamadı. Commit oluşturulmadı.")
                        time.sleep(0.05)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
        except Exception:
            if self._file is not None:
                self._file.close()
                self._file = None
            self._thread_lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._file is not None:
                if os.name == "nt":
                    import msvcrt
                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                self._file.close()
        finally:
            if self._thread_lock is not None and self._thread_lock.locked():
                self._thread_lock.release()


def _safe_names(task_id: str, filenames: List[str]) -> List[str]:
    prefix = f"workspaces/{task_id}/"
    names: List[str] = []
    for raw in filenames:
        if not isinstance(raw, str):
            continue
        normalized = raw.replace("\\", "/").strip()
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            continue
        if normalized.startswith(prefix):
            name = normalized[len(prefix):]
        else:
            name = normalized
        if "/" in name or name not in _ALLOWED_FILENAMES:
            continue
        if name not in names:
            names.append(name)
    return names


def _workspace_path(task_id: str, workspaces_root: str) -> str:
    root = os.path.abspath(workspaces_root)
    workspace = os.path.abspath(os.path.join(root, task_id))
    if os.path.basename(workspace) != task_id:
        raise ValueError("Çalışma alanı yolu görev kimliğiyle eşleşmiyor.")
    if os.path.commonpath([root, workspace]) != root or workspace == root:
        raise ValueError("Çalışma alanı izin verilen kökün dışına çıkıyor.")
    if os.path.islink(workspace):
        raise ValueError("Çalışma alanı sembolik bağlantı. Teslimat yapılmadı.")
    return workspace


def _git_dir_for(task_id: str, workspaces_root: str) -> str:
    root = os.path.abspath(workspaces_root)
    delivery_root = os.path.abspath(os.path.join(root, ".delivery"))
    git_dir = os.path.abspath(os.path.join(delivery_root, f"{task_id}.git"))
    if os.path.basename(git_dir) != f"{task_id}.git":
        raise ValueError("Git dizini görev kimliğiyle eşleşmiyor.")
    if os.path.commonpath([delivery_root, git_dir]) != delivery_root:
        raise ValueError("Git dizini teslimat kökünün dışına çıkıyor.")
    return git_dir


def _git_env(workspace: str, git_dir: str) -> Dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_DIR"] = git_dir
    env["GIT_WORK_TREE"] = workspace
    return env


def _remove_worktree_gitlink(workspace: str) -> None:
    """git init çalışma alanına .git bırakırsa tester bir sonraki turda bunu alt dizin sayar."""
    link = os.path.join(workspace, ".git")
    if not os.path.lexists(link):
        return

    def _onerror(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if os.path.isdir(link) and not os.path.islink(link):
        shutil.rmtree(link, onerror=_onerror)
    else:
        os.chmod(link, stat.S_IWRITE)
        os.remove(link)


def _reject_unsafe_git_args(args: List[str]) -> None:
    if any(not isinstance(arg, str) or arg.startswith("-C") for arg in args):
        raise ValueError("Güvensiz Git argümanı reddedildi.")


def _run_git(args: List[str], workspace: str, env: Dict[str, str]) -> subprocess.CompletedProcess:
    _reject_unsafe_git_args(args)
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
        check=False,
    )


def _run_git_bytes(
    args: List[str],
    cwd: str,
    env: Dict[str, str],
    data: Optional[bytes] = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    _reject_unsafe_git_args(args)
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        input=data,
        capture_output=True,
        timeout=timeout,
        shell=False,
        check=False,
    )


def _sha_ok(value: str) -> bool:
    return len(value) >= 7 and all(char in "0123456789abcdef" for char in value)


def _existing_commit(workspace: str, branch: str, env: Dict[str, str]) -> Optional[str]:
    probe = _run_git(["rev-parse", "--verify", "--end-of-options", f"refs/heads/{branch}"], workspace, env)
    if probe.returncode != 0:
        return None
    sha = probe.stdout.strip()
    if not _sha_ok(sha):
        return None
    return sha


def _point_head(workspace: str, env: Dict[str, str], branch: str) -> subprocess.CompletedProcess:
    """HEAD'i görev branch'ine alır. Çalışma ağacındaki dosyalara dokunmaz."""
    return _run_git(["symbolic-ref", "HEAD", f"refs/heads/{branch}"], workspace, env)


def _restore_index(workspace: str, env: Dict[str, str], branch: str) -> None:
    """İndeksi HEAD'e geri alır. Görev dosyalarını silmez."""
    if _existing_commit(workspace, branch, env):
        _point_head(workspace, env, branch)
        _run_git(["reset", "--quiet"], workspace, env)
    else:
        _run_git(["read-tree", "--empty"], workspace, env)


def _stage_tree(workspace: str, env: Dict[str, str], names: List[str], parent_sha: str) -> subprocess.CompletedProcess:
    """Ana dal ağacını indekse alır ve yalnızca görev dosyalarını bunun üzerine yazar."""
    loaded = _run_git(["read-tree", "--", parent_sha], workspace, env)
    if loaded.returncode != 0:
        return loaded
    return _run_git(["add", "--", *names], workspace, env)


def _find_base_git_dir(start: str) -> Optional[str]:
    """Görev çalışma alanının üzerindeki salt okunur proje deposunu bulur."""
    current = os.path.abspath(start)
    for _ in range(12):
        candidate = os.path.join(current, ".git")
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "HEAD")):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    return None


def _base_branch_name() -> str:
    name = os.environ.get("GITHUB_BASE_BRANCH", "main").strip() or "main"
    if name.startswith("-") or "/" in name or ".." in name or name in {"HEAD"}:
        return "main"
    return name


def _base_ref(branch: str) -> str:
    return f"refs/delivery-base/{branch}"


def _source_env(source_git: str) -> Dict[str, str]:
    """Kaynak depoyu salt okur. Teslimat deposunun GIT_DIR değerini taşımaz."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_DIR"] = source_git
    return env


def _verified_commit(workspace: str, env: Dict[str, str], ref: str) -> Optional[str]:
    """Ref varsa ve bir commit nesnesine işaret ediyorsa tam SHA döner."""
    probe = _run_git(["rev-parse", "--verify", "--end-of-options", ref], workspace, env)
    sha = probe.stdout.strip()
    if probe.returncode != 0 or len(sha) != 40 or not _sha_ok(sha):
        return None
    kind = _run_git(["cat-file", "-t", sha], workspace, env)
    if kind.returncode != 0 or kind.stdout.strip() != "commit":
        return None
    return sha


def _base_ref_candidates(branch: str) -> tuple[str, ...]:
    """Taban dalın adını taşıyan ref'ler. Detached HEAD bu listeye girmez."""
    return (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}")


def _resolve_source_commit(source_git: str, branch: str) -> Optional[tuple[str, str]]:
    """Aday ref commit nesnesine çözülürse (ref, sha) döner. HEAD tek başına kabul edilmez."""
    env = _source_env(source_git)
    for ref in _base_ref_candidates(branch):
        sha = _verified_commit(source_git, env, ref)
        if sha:
            return ref, sha
    return None


def _unverified_base_reason(branch: str) -> str:
    refs = ", ".join(_base_ref_candidates(branch))
    return (
        f"Ana dal ref'i doğrulanamadı ({refs}). "
        "Detached HEAD taban kabul edilmedi. Commit oluşturulmadı."
    )


def _source_is_shallow(source_git: str) -> bool:
    env = _source_env(source_git)
    probe = _run_git(["rev-parse", "--is-shallow-repository"], source_git, env)
    return probe.returncode == 0 and probe.stdout.strip() == "true"


def _reachable_object_ids(source_git: str, sha: str) -> Optional[bytes]:
    """Sığ sınırda duran geçmişin commit, ağaç ve blob kimliklerini döner."""
    listed = _run_git_bytes(["rev-list", "--objects", sha], source_git, _source_env(source_git))
    if listed.returncode != 0:
        return None
    identifiers = []
    for raw in listed.stdout.splitlines():
        token = raw.split(b" ", 1)[0].strip()
        if len(token) != 40:
            return None
        try:
            text = token.decode("ascii")
        except UnicodeError:
            return None
        if not _sha_ok(text):
            return None
        identifiers.append(token)
    if sha.encode("ascii") not in identifiers:
        return None
    return b"\n".join(identifiers) + b"\n"


def _copy_shallow_objects(source_git: str, workspace: str, env: Dict[str, str], sha: str) -> bool:
    """Sığ kaynaktaki erişilebilir nesneleri teslimat deposuna kopyalar. Kaynak ref'leri değiştirmez."""
    identifiers = _reachable_object_ids(source_git, sha)
    if not identifiers:
        return False
    packed = _run_git_bytes(
        ["pack-objects", "--stdout", "--no-reuse-delta"],
        source_git,
        _source_env(source_git),
        data=identifiers,
    )
    if packed.returncode != 0 or not packed.stdout:
        return False
    unpacked = _run_git_bytes(["unpack-objects"], workspace, env, data=packed.stdout)
    return unpacked.returncode == 0


def _record_shallow_boundaries(source_git: str, git_dir: str, workspace: str, env: Dict[str, str]) -> None:
    """Kaynakta sığ sınır olan ve teslimat deposunda bulunan commit'leri sığ kök olarak işaretler."""
    source_shallow = os.path.join(source_git, "shallow")
    if not os.path.isfile(source_shallow):
        return
    with open(source_shallow, "r", encoding="ascii") as handle:
        recorded = [line.strip() for line in handle if line.strip()]
    additions = []
    for sha in recorded:
        if len(sha) != 40 or not _sha_ok(sha):
            continue
        kind = _run_git(["cat-file", "-t", sha], workspace, env)
        if kind.returncode == 0 and kind.stdout.strip() == "commit":
            additions.append(sha)
    if not additions:
        return
    destination = os.path.join(git_dir, "shallow")
    lines = []
    if os.path.isfile(destination):
        with open(destination, "r", encoding="ascii") as handle:
            lines = [line.strip() for line in handle if line.strip()]
    for sha in additions:
        if sha not in lines:
            lines.append(sha)
    with open(destination, "w", encoding="ascii", newline="\n") as handle:
        for sha in lines:
            handle.write(sha + "\n")


def _import_base_commit(
    workspace: str, env: Dict[str, str], source_git: str, git_dir: str
) -> tuple[Optional[str], Optional[str]]:
    """Ana dal nesnelerini teslimat deposuna kopyalar. Kaynak depoyu ve ana dalı değiştirmez."""
    source = os.path.abspath(source_git)
    if (
        not os.path.isdir(source)
        or os.path.normcase(source) == os.path.normcase(os.path.abspath(git_dir))
        or source.startswith(("http://", "https://"))
        or "@" in source
    ):
        return None, None
    branch = _base_branch_name()
    destination = _base_ref(branch)
    resolved = _resolve_source_commit(source, branch)
    if resolved is None:
        return None, _unverified_base_reason(branch)
    source_ref, expected = resolved
    _run_git(
        ["fetch", "--no-tags", "--", source, f"{source_ref}:{destination}"],
        workspace,
        env,
    )
    # Çıkış kodu 0 olsa bile ref beklenen commit'e işaret etmiyorsa fetch başarılı sayılmaz.
    imported = _verified_commit(workspace, env, destination)
    if imported == expected:
        return expected, None
    if not _source_is_shallow(source):
        return None, None
    if not _copy_shallow_objects(source, workspace, env, expected):
        return None, None
    _record_shallow_boundaries(source, git_dir, workspace, env)
    if imported is not None and not _is_ancestor(workspace, env, imported, expected):
        return None, None
    previous = imported if imported is not None else "0" * 40
    _run_git(["update-ref", destination, expected, previous], workspace, env)
    verified = _verified_commit(workspace, env, destination)
    if verified != expected:
        return None, None
    return expected, None


def _is_ancestor(workspace: str, env: Dict[str, str], base_sha: str, commit_sha: str) -> bool:
    if not _sha_ok(base_sha) or not _sha_ok(commit_sha):
        return False
    result = _run_git(["merge-base", "--is-ancestor", base_sha, commit_sha], workspace, env)
    return result.returncode == 0


def shares_base_history(workspace: str, git_dir: str, sha: str, base_branch: str = "main") -> bool:
    """Görev commit'i teslimat deposundaki ana dal tabanının soyundan mı bakar."""
    if not os.path.isdir(git_dir) or not _sha_ok(sha):
        return False
    env = _git_env(workspace, git_dir)
    probe = _run_git(
        ["rev-parse", "--verify", "--end-of-options", _base_ref(base_branch)],
        workspace,
        env,
    )
    base_sha = probe.stdout.strip()
    if probe.returncode != 0:
        return False
    return _is_ancestor(workspace, env, base_sha, sha)


def deliver_task_workspace(task_id: str, workspaces_root: str, filenames: List[str]) -> Dict[str, object]:
    """
    İzinli dosyaları task/{task_id} branch'ine teslim eder.
    Aynı ağaç varsa yeni commit açmaz. İçerik değiştiyse aynı branch'e yeni commit yazar.
    Ana branch'e geçmez, merge ve push yapmaz.
    """
    if not _valid_task_id(task_id):
        return _result("failed", reason="Geçersiz görev kimliği. Teslimat yapılmadı.")
    try:
        workspace = _workspace_path(task_id, workspaces_root)
        git_dir = _git_dir_for(task_id, workspaces_root)
    except ValueError as exc:
        return _result("failed", reason=str(exc))

    branch = branch_name_for(task_id)
    names = _safe_names(task_id, filenames)
    if not names:
        return _result("failed", branch=branch, reason="Teslim edilecek izinli dosya yok.")
    if not os.path.isdir(workspace):
        return _result("failed", branch=branch, reason="Çalışma alanı bulunamadı.")
    for name in names:
        file_path = os.path.join(workspace, name)
        if os.path.islink(file_path) or not os.path.isfile(file_path):
            return _result("failed", branch=branch, files=names, reason=f"Teslimat dosyası güvenli değil: {name}")

    git_binary = shutil.which("git")
    if not git_binary:
        return _result("failed", branch=branch, files=names, reason="Git bulunamadı. Commit oluşturulmadı.")

    lock_path = os.path.join(os.path.dirname(git_dir), f"{task_id}.lock")
    try:
        with _DeliveryLock(task_id, lock_path):
            return _deliver_locked(task_id, workspace, git_dir, branch, names)
    except TimeoutError as exc:
        return _result("failed", branch=branch, files=names, reason=str(exc))
    except subprocess.TimeoutExpired:
        return _result("failed", branch=branch, files=names, reason="Git komutu zaman aşımına uğradı. Commit oluşturulmadı.")
    except ValueError as exc:
        return _result("failed", branch=branch, files=names, reason=str(exc))


def _git_dir_initialized(git_dir: str) -> bool:
    """Yarım kalan init, yalnızca objects klasörü bırakmış bir dizini depo saymaz."""
    return os.path.isfile(os.path.join(git_dir, "HEAD")) and os.path.isdir(os.path.join(git_dir, "refs"))


def _deliver_locked(task_id: str, workspace: str, git_dir: str, branch: str, names: List[str]) -> Dict[str, object]:
    os.makedirs(os.path.dirname(git_dir), exist_ok=True)
    env = _git_env(workspace, git_dir)
    source_git = _find_base_git_dir(workspace) or _find_base_git_dir(os.path.dirname(os.path.abspath(__file__)))
    if not source_git:
        return _result("failed", branch=branch, files=names, reason="Ana dal geçmişi bulunamadı. Commit oluşturulmadı.")
    if not _git_dir_initialized(git_dir):
        created = _run_git(["init", "-b", branch], workspace, env)
        if created.returncode != 0:
            created = _run_git(["init"], workspace, env)
            if created.returncode != 0:
                return _result("failed", branch=branch, files=names, reason="Git deposu oluşturulamadı.")
        _remove_worktree_gitlink(workspace)
    env["GIT_AUTHOR_NAME"] = "AI Dev Team"
    env["GIT_AUTHOR_EMAIL"] = "ai-dev-team@localhost"
    env["GIT_COMMITTER_NAME"] = "AI Dev Team"
    env["GIT_COMMITTER_EMAIL"] = "ai-dev-team@localhost"
    if not _git_dir_initialized(git_dir):
        return _result("failed", branch=branch, files=names, reason="Git deposu oluşturulamadı.")

    if not os.path.isdir(git_dir):
        return _result("failed", branch=branch, files=names, reason="Git deposu çalışma alanının yanında oluşmadı.")
    _remove_worktree_gitlink(workspace)
    if os.path.lexists(os.path.join(workspace, ".git")):
        return _result("failed", branch=branch, files=names, reason="Çalışma alanında .git bırakılmadı. Teslimat durduruldu.")
    toplevel = _run_git(["rev-parse", "--show-toplevel"], workspace, env)
    actual_root = os.path.normcase(os.path.abspath(toplevel.stdout.strip()))
    if toplevel.returncode != 0 or actual_root != os.path.normcase(workspace):
        return _result("failed", branch=branch, files=names, reason="Git kökü çalışma alanıyla eşleşmiyor. Teslimat durduruldu.")

    base_sha, base_reason = _import_base_commit(workspace, env, source_git, git_dir)
    if not base_sha:
        return _result(
            "failed",
            branch=branch,
            files=names,
            reason=base_reason or "Ana dal geçmişi teslimat deposuna alınamadı. Commit oluşturulmadı.",
        )

    existing = _existing_commit(workspace, branch, env)
    if existing and not _is_ancestor(workspace, env, base_sha, existing):
        return _result(
            "failed",
            branch=branch,
            commit=existing,
            files=names,
            reason="Mevcut görev dalı ana dalla ortak geçmişe sahip değil. Commit değiştirilmedi.",
        )
    git_parent = existing or base_sha

    pointed = _point_head(workspace, env, branch)
    if pointed.returncode != 0:
        return _result("failed", branch=branch, files=names, reason="Görev branch'i oluşturulamadı. Ana branch değiştirilmedi.")

    staged = _stage_tree(workspace, env, names, git_parent)
    if staged.returncode != 0:
        _restore_index(workspace, env, branch)
        return _result("failed", branch=branch, files=names, reason="Dosyalar stage edilemedi. Commit oluşturulmadı.")
    written = _run_git(["write-tree"], workspace, env)
    tree = written.stdout.strip()
    if written.returncode != 0 or not _sha_ok(tree):
        _restore_index(workspace, env, branch)
        return _result("failed", branch=branch, files=names, reason="Teslimat ağacı yazılamadı. Commit oluşturulmadı.")

    parent = git_parent
    parent_tree = ""
    if parent:
        parsed = _run_git(["rev-parse", "--verify", "--end-of-options", f"{parent}^{{tree}}"], workspace, env)
        parent_tree = parsed.stdout.strip()
        if parsed.returncode != 0 or not _sha_ok(parent_tree):
            _restore_index(workspace, env, branch)
            return _result("failed", branch=branch, files=names, reason="Mevcut teslimat ağacı okunamadı. Yeni commit oluşturulmadı.")
    if parent and parent_tree == tree:
        _restore_index(workspace, env, branch)
        _remove_worktree_gitlink(workspace)
        return _result(
            "reused",
            branch=branch,
            commit=parent,
            files=names,
            reason="Aynı içerik için mevcut teslimat commit'i yeniden kullanıldı.",
        )

    hooks = os.path.join(git_dir, "no-hooks")
    os.makedirs(hooks, exist_ok=True)
    command = [
        "-c", "user.name=AI Dev Team",
        "-c", "user.email=ai-dev-team@localhost",
        "-c", f"core.hooksPath={hooks}",
        "commit-tree",
        tree,
    ]
    if parent:
        command.extend(["-p", parent])
    command.extend(["-m", f"Deliver task {task_id}"])
    committed = _run_git(command, workspace, env)
    sha = committed.stdout.strip()
    if committed.returncode != 0 or not _sha_ok(sha):
        _restore_index(workspace, env, branch)
        detail = (committed.stderr or committed.stdout or "commit başarısız").strip().splitlines()
        return _result(
            "failed",
            branch=branch,
            files=names,
            reason=f"Commit tamamlanamadı: {detail[0][:180] if detail else 'bilinmeyen hata'}",
        )
    if not _is_ancestor(workspace, env, base_sha, sha):
        _restore_index(workspace, env, branch)
        return _result(
            "failed",
            branch=branch,
            files=names,
            reason="Görev commit'i ana dalla ortak geçmişe sahip değil. Branch güncellenmedi.",
        )

    updated = _run_git(["update-ref", f"refs/heads/{branch}", sha], workspace, env)
    if updated.returncode != 0:
        _restore_index(workspace, env, branch)
        return _result("failed", branch=branch, files=names, reason="Branch güncellenemedi. Ana branch değiştirilmedi.")
    head_ref = _point_head(workspace, env, branch)
    head_sha = _existing_commit(workspace, branch, env)
    head_name = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], workspace, env)
    _remove_worktree_gitlink(workspace)
    if os.path.lexists(os.path.join(workspace, ".git")):
        return _result("failed", branch=branch, commit=sha, previous_commit=parent, files=names, reason="Commit sonrası çalışma alanında .git kaldı.")
    if head_ref.returncode != 0 or head_sha != sha or head_name.stdout.strip() != branch:
        return _result("failed", branch=branch, commit=sha, previous_commit=parent, files=names, reason="Commit sonrası branch doğrulanamadı.")
    return _result("committed", branch=branch, commit=sha, previous_commit=existing, files=names)
