"""
backend/execution/subprocess_engine.py
AI Dev Team - Kısıtlı Subprocess Geliştirme Adaptörü (GÜVENSİZ)

DİKKAT / GÜVENLİK UYARISI:
Bu adaptör kernel seviyesinde ağ ve tam dosya sistemi izolasyonu SAĞLAMAZ.
Yalnızca Docker bulunmayan ve güvenilmeyen kod çalıştırmayan yerel geliştirme
ortamlarında 'ALLOW_UNSAFE_HOST_EXECUTION=true' açıkça ayarlandığında kullanılabilir.
Varsayılan workflow bu motoru ASLA otomatik seçmez.
"""

import os
import subprocess
import sys
import time
from typing import List, Optional

from .base import BaseExecutionEngine, ExecutionConfig, ExecutionResult


class SubprocessExecutionEngine(BaseExecutionEngine):
    """
    Yerel kısıtlı subprocess motoru. Güvenilmeyen kod çalıştırmak için varsayılan olamaz.
    """

    def __init__(self, default_config: Optional[ExecutionConfig] = None):
        self.default_config = default_config or ExecutionConfig()

    def get_isolation_type(self) -> str:
        return "subprocess_unsafe"

    def is_available(self) -> bool:
        is_prod = (
            os.environ.get("APP_ENV", "").lower() in ["production", "prod"] or
            os.environ.get("ENVIRONMENT", "").lower() in ["production", "prod"]
        )
        if is_prod:
            return False
        return os.environ.get("ALLOW_UNSAFE_HOST_EXECUTION", "false").lower() in ["true", "1", "yes"]

    def execute_sync(
        self,
        workspace_path: str,
        command: List[str],
        config: Optional[ExecutionConfig] = None
    ) -> ExecutionResult:
        cfg = config or self.default_config

        if not self.is_available():
            return ExecutionResult(
                status="blocked",
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=0.0,
                isolation_type=self.get_isolation_type(),
                error="Host üzerinde güvensiz kod yürütme engellendi (ALLOW_UNSAFE_HOST_EXECUTION kapalı)."
            )

        start_time = time.perf_counter()
        abs_workspace = os.path.abspath(workspace_path)

        isolated_env = os.environ.copy()
        existing_pythonpath = isolated_env.get("PYTHONPATH", "")
        isolated_env["PYTHONPATH"] = (
            f"{abs_workspace}{os.pathsep}{existing_pythonpath}"
            if existing_pythonpath
            else abs_workspace
        )
        isolated_env["PYTHONDONTWRITEBYTECODE"] = "1"
        isolated_env["PYTHONUNBUFFERED"] = "1"

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

        cmd = command if command else [sys.executable, "-m", "unittest", "-v", "test_feature.py"]
        if cmd and cmd[0] in ["python", "python3"]:
            cmd = [sys.executable] + cmd[1:]

        try:
            completed = subprocess.run(
                cmd,
                cwd=abs_workspace,
                env=isolated_env,
                capture_output=True,
                text=True,
                timeout=cfg.timeout_sec,
                creationflags=creation_flags
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
            return ExecutionResult(
                status="timeout",
                exit_code=-1,
                stdout="",
                stderr="Timeout",
                duration_ms=duration_ms,
                isolation_type=self.get_isolation_type(),
                raw_output=f"TimeoutExpired: Test execution exceeded {cfg.timeout_sec}s limit",
                error=f"Zaman aşımı: Test süreci güvenlik sınırını aştı ({cfg.timeout_sec}s)."
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return ExecutionResult(
                status="error",
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_ms=duration_ms,
                isolation_type=self.get_isolation_type(),
                raw_output=str(exc),
                error=f"Subprocess yürütme hatası: {str(exc)}"
            )
