"""
backend/execution/mock_engine.py
AI Dev Team - Test ve Çevrimdışı Doğrulama İçin Mock Yürütme Motoru

Birim testler ve çevrimdışı doğrulamalar için kullanılır.
Gerçek Docker izolasyonu sağlamaz; açıkça 'mock' izolasyon türü ile raporlar.
"""

import os
import subprocess
import sys
import time
from typing import List, Optional

from .base import BaseExecutionEngine, ExecutionConfig, ExecutionResult


class MockExecutionEngine(BaseExecutionEngine):
    """
    Birim testler ve çevrimdışı geliştirme için Mock yürütme motoru.
    """

    def __init__(
        self,
        default_config: Optional[ExecutionConfig] = None,
        simulate_timeout: bool = False,
        simulate_error: Optional[str] = None,
        custom_raw_output: Optional[str] = None,
        custom_exit_code: int = 0,
        custom_status: Optional[str] = None,
        custom_error: Optional[str] = None,
    ):
        self.default_config = default_config or ExecutionConfig()
        self.simulate_timeout = simulate_timeout
        self.simulate_error = simulate_error
        self.custom_raw_output = custom_raw_output
        self.custom_exit_code = custom_exit_code
        self.custom_status = custom_status
        self.custom_error = custom_error

    def get_isolation_type(self) -> str:
        return "mock"

    def is_available(self) -> bool:
        return True

    def execute_sync(
        self,
        workspace_path: str,
        command: List[str],
        config: Optional[ExecutionConfig] = None
    ) -> ExecutionResult:
        cfg = config or self.default_config

        if self.simulate_timeout or self.custom_status == "timeout":
            return ExecutionResult(
                status="timeout",
                exit_code=-1,
                stdout="",
                stderr=self.custom_error or "Mock execution timeout simulated",
                duration_ms=cfg.timeout_sec * 1000,
                isolation_type=self.get_isolation_type(),
                raw_output=f"TimeoutExpired: Test execution exceeded {cfg.timeout_sec}s limit",
                error=self.custom_error or f"Zaman aşımı: Test süreci güvenlik sınırını aştı ({cfg.timeout_sec}s)."
            )

        if self.simulate_error or self.custom_status == "error":
            err_msg = self.custom_error or self.simulate_error or "Mock error"
            return ExecutionResult(
                status="error",
                exit_code=-1,
                stdout="",
                stderr=err_msg,
                duration_ms=10.0,
                isolation_type=self.get_isolation_type(),
                raw_output=err_msg,
                error=err_msg
            )

        if self.custom_raw_output is not None:
            status = self.custom_status or ("success" if self.custom_exit_code == 0 else "failed")
            out = self.custom_raw_output
            if len(out) > cfg.max_output_chars:
                out = out[:cfg.max_output_chars] + "\n[Output truncated due to length limit]"
            return ExecutionResult(
                status=status,
                exit_code=self.custom_exit_code,
                stdout=out,
                stderr="",
                duration_ms=15.0,
                isolation_type=self.get_isolation_type(),
                raw_output=out,
                error=self.custom_error or (None if self.custom_exit_code == 0 else f"Process exited with code {self.custom_exit_code}")
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
                error=f"Mock yürütme hatası: {str(exc)}"
            )
