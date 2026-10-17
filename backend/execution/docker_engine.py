"""
backend/execution/docker_engine.py
AI Dev Team - Docker Tabanlı İzole Kod Yürütme Motoru

Güvenlik Politikası:
1. --network none: Kernel seviyesinde sıfır ağ çıkışı.
2. --read-only: Salt okunur kök dosya sistemi.
3. --cpus, --memory, --pids-limit: Katı kaynak sınırları (DoS / Fork-bomb engelleme).
4. --cap-drop=ALL, --security-opt=no-new-privileges: Linux yetki yükseltme engelleri.
5. Sadece salt okunur workspace mount; Docker socket veya host dosyaları ASLA mount edilmez.
6. 5s katı timeout ve 'docker kill' / 'docker rm -f' ile temizlik garantisi.
"""

import logging
import os
import re
import shutil
import stat
import subprocess
import time
import uuid
from typing import List, Optional, Tuple

from .base import BaseExecutionEngine, ExecutionConfig, ExecutionResult

logger = logging.getLogger("ai_dev_team.execution")

_DOCKER_INFO_TIMEOUT_SECONDS = 10.0
_INTERRUPTED_DOCKER_INFO_EXIT = 130

_SECRET_TEXT = re.compile(
    r"(?i)(bearer\s+\S+|ghp_[A-Za-z0-9]+|github_pat_\S+|sk-[A-Za-z0-9_\-]+|"
    r"(?:token|api[_-]?key|password|secret|authorization)\s*[=:]\s*\S+)"
)


def _public_diagnostic(text: str, limit: int = 240) -> str:
    """Tek satırlık teşhis. Anahtar, token ve benzeri gizli değerleri yazmaz."""
    raw = (text or "").strip()
    if not raw:
        return ""
    line = _SECRET_TEXT.sub("[redacted]", raw.splitlines()[0])
    return line[:limit]


def _run_docker_info_probe(docker_cmd: str) -> tuple[bool, str, Optional[int]]:
    """docker info sağlık kontrolünü bir kez çalıştırır.

    Dönüş: (başarılı mı, teşhis, çıkış kodu). Zaman aşımı ve diğer
    istisnalarda çıkış kodu None olur; bu çağrılar yeniden denenmez.
    """
    try:
        res = subprocess.run(
            [docker_cmd, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=_DOCKER_INFO_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return (
            False,
            "Docker daemon yanıt vermedi "
            f"({_DOCKER_INFO_TIMEOUT_SECONDS:.1f}s zaman aşımı; exception=TimeoutExpired).",
            None,
        )
    except Exception as exc:
        detail = _public_diagnostic(str(exc))
        suffix = f": {detail}" if detail else ""
        return (
            False,
            "Docker bağlantı kontrolü sırasında hata: "
            f"exception={type(exc).__name__}{suffix}",
            None,
        )

    if res.returncode == 0 and len(res.stdout.strip()) > 0:
        version = _public_diagnostic(res.stdout.strip(), limit=80)
        return True, f"Docker daemon aktif (Versiyon: {version})", res.returncode

    err_msg = _public_diagnostic(res.stderr) or f"Dönüş kodu: {res.returncode}"
    return (
        False,
        "Docker daemon yanıt vermiyor "
        f"(exit={res.returncode}; {err_msg}). "
        "Docker Desktop'ın çalıştığından emin olun.",
        res.returncode,
    )


def _log_docker_info_attempt(attempt: int, ok: bool, message: str, code: Optional[int]) -> None:
    """Sağlık denemesinin teşhisini loglar. Mesaj zaten gizli değerlerden arındırılmıştır."""
    exit_label = "yok" if code is None else str(code)
    outcome = "başarılı" if ok else "başarısız"
    log = logger.info if ok else logger.warning
    if attempt == 1:
        log(
            "[DOCKER_HEALTH] deneme=1 sonuç=%s exit=%s tanı=%s. "
            "Aynı kontrol bir kez daha denenecek.",
            outcome,
            exit_label,
            message,
        )
        return
    log(
        "[DOCKER_HEALTH] deneme=%s sonuç=%s exit=%s tanı=%s",
        attempt,
        outcome,
        exit_label,
        message,
    )


class DockerExecutionEngine(BaseExecutionEngine):
    """
    Docker container içinde güvenli kod yürüten motor.
    """

    def __init__(self, default_config: Optional[ExecutionConfig] = None):
        self.default_config = default_config or ExecutionConfig()
        self.last_availability: Optional[Tuple[bool, str]] = None

    def get_isolation_type(self) -> str:
        return "docker"

    def _get_docker_cmd(self) -> str:
        """Sistemde kurulu Docker CLI yürütülebilir dosyasının yolunu bulur."""
        cli = shutil.which("docker")
        if cli:
            return cli
        # Windows varsayılan kurulum yolları
        common_windows_paths = [
            r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
            r"C:\Program Files\Docker\Docker\resources\bin\docker.EXE",
        ]
        for p in common_windows_paths:
            if os.path.isfile(p):
                return p
        return "docker"

    def check_availability(self) -> tuple[bool, str]:
        """
        Docker CLI ve Docker daemon'ın erişilebilir olup olmadığını doğrular
        ve ayrıntılı teşhis mesajı döndürür.

        Yalnızca docker info çıkış kodu 130 olduğunda aynı kontrol bir kez
        daha çalışır. Zaman aşımı ve diğer çıkış kodları yeniden denenmez.
        """
        docker_cmd = self._get_docker_cmd()
        if not shutil.which(docker_cmd) and not os.path.isfile(docker_cmd):
            result = (
                False,
                "Docker CLI yürütülebilir dosyası sistem PATH üzerinde bulunamadı "
                f"(aranan: {docker_cmd})."
            )
            self.last_availability = result
            return result

        ok, message, code = _run_docker_info_probe(docker_cmd)
        if code == _INTERRUPTED_DOCKER_INFO_EXIT:
            _log_docker_info_attempt(1, ok, message, code)
            ok, message, code = _run_docker_info_probe(docker_cmd)
            _log_docker_info_attempt(2, ok, message, code)
        result = (ok, message)
        self.last_availability = result
        return result

    def is_available(self) -> bool:
        """Docker CLI ve Docker daemon'ın erişilebilir olup olmadığını doğrular."""
        ok, _ = self.check_availability()
        return ok

    @staticmethod
    def format_docker_mount_path(workspace_path: str) -> str:
        """
        Windows ve Linux dosya yollarını Docker Desktop / WSL2 mount formatına dönüştürür.
        Boşluk ve Unicode karakter içeren yolları korur.
        """
        abs_workspace = os.path.abspath(os.path.expanduser(workspace_path))
        # Windows sürücü yolunu (C:\...) Linux formatına (C:/...) çevirir
        return abs_workspace.replace("\\", "/")

    def execute_sync(
        self,
        workspace_path: str,
        command: List[str],
        config: Optional[ExecutionConfig] = None
    ) -> ExecutionResult:
        cfg = config or self.default_config

        if not os.path.exists(workspace_path) or not os.path.isdir(workspace_path):
            return ExecutionResult(
                status="error",
                exit_code=-1,
                stdout="",
                stderr=f"Çalışma alanı dizini mevcut değil veya geçersiz: {workspace_path}",
                duration_ms=0.0,
                isolation_type=self.get_isolation_type(),
                raw_output=f"Çalışma alanı dizini bulunamadı: {workspace_path}",
                error=f"Çalışma alanı dizini mevcut değil: {workspace_path}"
            )

        if self.last_availability is not None:
            available, diag_msg = self.last_availability
        else:
            available, diag_msg = self.check_availability()
        if not available:
            return ExecutionResult(
                status="blocked",
                exit_code=-1,
                stdout="",
                stderr=diag_msg,
                duration_ms=0.0,
                isolation_type=self.get_isolation_type(),
                error=f"Docker daemon erişilemez veya çalışmıyor ({diag_msg}). Kod host üzerinde çalıştırılmadı."
            )

        _grant_sandbox_read(workspace_path)
        start_time = time.perf_counter()
        docker_cmd = self._get_docker_cmd()
        docker_mount_path = self.format_docker_mount_path(workspace_path)
        container_name = f"aidev-test-{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"

        docker_args = [
            docker_cmd, "run",
            "--name", container_name,
            "--rm",
            "--network", "none",
            "--read-only",
            "--cpus", str(cfg.max_cpus),
            "--memory", f"{cfg.max_memory_mb}m",
            "--memory-swap", f"{cfg.max_memory_mb}m",
            "--pids-limit", str(cfg.max_pids),
            "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
            "-v", f"{docker_mount_path}:/workspace:ro",
            "-w", "/workspace",
            "--user", "1000:1000",
            cfg.image_name
        ] + command

        try:
            completed = subprocess.run(
                docker_args,
                capture_output=True,
                text=True,
                timeout=cfg.timeout_sec,
                stdin=subprocess.DEVNULL
            )
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""

            if len(stdout) > cfg.max_output_chars:
                stdout = stdout[:cfg.max_output_chars] + "\n[Output truncated due to length limit]"
            if len(stderr) > cfg.max_output_chars:
                stderr = stderr[:cfg.max_output_chars] + "\n[Output truncated due to length limit]"

            raw_output = (stderr or "") + "\n" + (stdout or "")
            status = "success" if completed.returncode == 0 else "failed"

            return ExecutionResult(
                status=status,
                exit_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                isolation_type=self.get_isolation_type(),
                raw_output=raw_output,
                error=None if completed.returncode == 0 else _failure_detail(completed.returncode, stderr, stdout)
            )
        except subprocess.TimeoutExpired:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            try:
                subprocess.run([docker_cmd, "kill", container_name], capture_output=True, timeout=2.0, stdin=subprocess.DEVNULL)
                subprocess.run([docker_cmd, "rm", "-f", container_name], capture_output=True, timeout=2.0, stdin=subprocess.DEVNULL)
            except Exception:
                pass

            return ExecutionResult(
                status="timeout",
                exit_code=-1,
                stdout="",
                stderr=f"Execution timeout ({cfg.timeout_sec}s exceeded)",
                duration_ms=duration_ms,
                isolation_type=self.get_isolation_type(),
                raw_output=f"TimeoutExpired: Test execution exceeded {cfg.timeout_sec}s limit",
                error=f"Zaman aşımı: Test yürütmesi {cfg.timeout_sec}s sınırını aştı."
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            try:
                subprocess.run([docker_cmd, "rm", "-f", container_name], capture_output=True, timeout=2.0, stdin=subprocess.DEVNULL)
            except Exception:
                pass

            return ExecutionResult(
                status="error",
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_ms=duration_ms,
                isolation_type=self.get_isolation_type(),
                raw_output=str(exc),
                error=f"Docker yürütme hatası: {str(exc)}"
            )
        finally:
            try:
                subprocess.run([docker_cmd, "rm", "-f", container_name], capture_output=True, timeout=1.0, stdin=subprocess.DEVNULL)
            except Exception:
                pass


def _grant_sandbox_read(workspace_path: str) -> None:
    """
    Linux geçici dizinleri 0700 olur ve sahibi runner uid 1001 olabilir.
    Sandbox --user 1000:1000 bu dosyayı okuyamaz. Mount salt okunur kalır.
    """
    if os.name == "nt":
        return
    for root, _dirs, files in os.walk(workspace_path, followlinks=False):
        _add_other_mode(root, 0o005)
        for name in files:
            path = os.path.join(root, name)
            if os.path.islink(path):
                continue
            _add_other_mode(path, 0o004)


def _add_other_mode(path: str, extra: int) -> None:
    try:
        mode = os.lstat(path).st_mode
        if stat.S_ISLNK(mode):
            return
        os.chmod(path, stat.S_IMODE(mode) | extra)
    except OSError:
        return


def _failure_detail(exit_code: int, stderr: str, stdout: str) -> str:
    text = (stderr or stdout or "").strip()
    line = text.splitlines()[-1][:300] if text else ""
    if line:
        return f"Process exited with code {exit_code}: {line}"
    return f"Process exited with code {exit_code}"
