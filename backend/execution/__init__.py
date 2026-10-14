"""
backend/execution/__init__.py
AI Dev Team - Güvenli Kod Yürütme Katmanı ve Motor Fabrikası

Varsayılan politika:
Docker bulunamadığında veya daemon çalışmadığında güvenilmeyen kodu host üzerinde çalıştırmayı REDDEDER.
"""

import logging
import os
from typing import List, Optional

from .base import BaseExecutionEngine, ExecutionConfig, ExecutionResult
from .docker_engine import DockerExecutionEngine
from .mock_engine import MockExecutionEngine
from .subprocess_engine import SubprocessExecutionEngine

logger = logging.getLogger("ai_dev_team.execution")


class UnavailableExecutionEngine(BaseExecutionEngine):
    """
    Güvenli yürütme motorunun (Docker) bulunamadığı durumlarda
    kodu çalıştırmayı reddeden ve 'blocked' dönen güvenlik motoru.
    """

    def __init__(self, reason: str = "Güvenli Docker motoru bulunamadı. Host üzerinde kod yürütme engellendi."):
        self.reason = reason

    def is_available(self) -> bool:
        return False

    def get_isolation_type(self) -> str:
        return "none"

    def execute_sync(
        self,
        workspace_path: str,
        command: List[str],
        config: Optional[ExecutionConfig] = None
    ) -> ExecutionResult:
        return ExecutionResult(
            status="blocked",
            exit_code=-1,
            stdout="",
            stderr=self.reason,
            duration_ms=0.0,
            isolation_type=self.get_isolation_type(),
            raw_output=self.reason,
            error=self.reason
        )


def get_execution_engine(preferred: Optional[str] = None) -> BaseExecutionEngine:
    """
    Ortam yapılandırmasına ve güvenlik politikasına uygun yürütme motorunu döndürür.
    """
    is_prod = (
        os.environ.get("APP_ENV", "").lower() in ["production", "prod"] or
        os.environ.get("ENVIRONMENT", "").lower() in ["production", "prod"]
    )
    engine_type = (preferred or os.environ.get("EXECUTION_ENGINE", "docker")).lower()

    if engine_type == "mock":
        logger.info("[ENGINE_FACTORY] Returning MockExecutionEngine (EXECUTION_ENGINE=mock)")
        return MockExecutionEngine()

    if engine_type == "subprocess_unsafe":
        if is_prod:
            return UnavailableExecutionEngine(
                reason="GÜVENLİK İHLALİ: Üretim ortamında (APP_ENV=production) güvensiz host yürütmesi kesinlikle yasaklanmıştır."
            )
        sub_engine = SubprocessExecutionEngine()
        if sub_engine.is_available():
            logger.warning("[ENGINE_FACTORY] Using SubprocessExecutionEngine in development mode")
            return sub_engine
        return UnavailableExecutionEngine(
            reason="Host üzerinde güvensiz kod çalıştırma izni verilmedi (ALLOW_UNSAFE_HOST_EXECUTION kapalı)."
        )

    # Varsayılan: Docker motoru
    docker_engine = DockerExecutionEngine()
    if docker_engine.is_available():
        _, docker_diag = (
            docker_engine.check_availability()
            if hasattr(docker_engine, "check_availability")
            else (True, "Docker daemon aktif")
        )
        logger.info(f"[ENGINE_FACTORY] Selected DockerExecutionEngine: {docker_diag}")
        return docker_engine

    _, docker_diag = (
        docker_engine.check_availability()
        if hasattr(docker_engine, "check_availability")
        else (False, "Docker daemon kontrol edilemedi.")
    )
    logger.warning(f"[ENGINE_FACTORY] Docker unavailable: {docker_diag}")

    # Docker yoksa ve güvensiz çalıştırma izni yoksa: BLOCKED
    if not is_prod and os.environ.get("ALLOW_UNSAFE_HOST_EXECUTION", "false").lower() in ["true", "1", "yes"]:
        return SubprocessExecutionEngine()

    return UnavailableExecutionEngine(
        reason=f"Güvenli Docker motoru kullanılamıyor ({docker_diag}). Güvenlik politikası gereği kod host üzerinde çalıştırılmadı."
    )


__all__ = [
    "BaseExecutionEngine",
    "ExecutionConfig",
    "ExecutionResult",
    "DockerExecutionEngine",
    "MockExecutionEngine",
    "SubprocessExecutionEngine",
    "UnavailableExecutionEngine",
    "get_execution_engine",
]
