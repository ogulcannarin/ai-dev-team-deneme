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

import os
import shutil
import subprocess
import time
import uuid
from typing import List, Optional

from .base import BaseExecutionEngine, ExecutionConfig, ExecutionResult


class DockerExecutionEngine(BaseExecutionEngine):
    """
    Docker container içinde güvenli kod yürüten motor.
    """

    def __init__(self, default_config: Optional[ExecutionConfig] = None):
        self.default_config = default_config or ExecutionConfig()

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
        """
        docker_cmd = self._get_docker_cmd()
        if not shutil.which(docker_cmd) and not os.path.isfile(docker_cmd):
            return False, f"Docker CLI yürütülebilir dosyası sistem PATH üzerinde bulunamadı (aranan: {docker_cmd})."

        try:
            res = subprocess.run(
                [docker_cmd, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=10.0,
                stdin=subprocess.DEVNULL
            )
            if res.returncode == 0 and len(res.stdout.strip()) > 0:
                return True, f"Docker daemon aktif (Versiyon: {res.stdout.strip()})"
            err_msg = (res.stderr or "").strip() or f"Dönüş kodu: {res.returncode}"
            # Hassas bilgi sızıntısını önlemek için çıktıyı temizle
            err_msg = err_msg.splitlines()[0] if err_msg else f"Dönüş kodu: {res.returncode}"
            return False, f"Docker daemon yanıt vermiyor ({err_msg}). Docker Desktop'ın çalıştığından emin olun."
        except subprocess.TimeoutExpired:
            return False, "Docker daemon yanıt vermedi (10.0s zaman aşımı)."
        except Exception as exc:
            return False, f"Docker bağlantı kontrolü sırasında hata: {str(exc)}"

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

        if not self.is_available():
            _, diag_msg = (
                self.check_availability()
                if hasattr(self, "check_availability")
                else (False, "Docker daemon erişilemez.")
            )
            return ExecutionResult(
                status="blocked",
                exit_code=-1,
                stdout="",
                stderr=diag_msg,
                duration_ms=0.0,
                isolation_type=self.get_isolation_type(),
                error=f"Docker daemon erişilemez veya çalışmıyor ({diag_msg}). Kod host üzerinde çalıştırılmadı."
            )

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
                error=None if completed.returncode == 0 else f"Process exited with code {completed.returncode}"
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
