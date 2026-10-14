"""
backend/execution/base.py
AI Dev Team - Güvenli Kod Yürütme Motoru Temel Arayüzü ve Modelleri

En az ayrıcalık ilkesi (Principle of Least Privilege) ile izole kod çalıştırma modelleri.
"""

import abc
import asyncio
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ExecutionConfig(BaseModel):
    """Kod yürütme kısıtları ve güvenlik yapılandırması."""
    timeout_sec: float = Field(default=15.0, ge=0.5, le=60.0, description="Zaman aşımı süresi (saniye)")
    max_memory_mb: int = Field(default=256, ge=32, le=2048, description="Maksimum bellek sınırı (MB)")
    max_cpus: float = Field(default=1.0, ge=0.1, le=4.0, description="Maksimum CPU çekirdek sınırı")
    max_pids: int = Field(default=64, ge=8, le=256, description="Maksimum süreç sayısı (Fork-bomb koruması)")
    max_output_chars: int = Field(default=10000, ge=100, le=50000, description="Maksimum stdout/stderr çıktı boyutu")
    network_disabled: bool = Field(default=True, description="Ağ erişiminin kernel seviyesinde engellenmesi")
    read_only_root: bool = Field(default=True, description="Kök dosya sisteminin salt okunur yapılması")
    image_name: str = Field(default="ai-dev-team-runner:latest", description="Sandbox Docker imaj adı")


class ExecutionResult(BaseModel):
    """Kod yürütme motorundan dönen standart sonuç."""
    status: str = Field(..., description="Yürütme durumu ('success', 'failed', 'blocked', 'timeout', 'error')")
    exit_code: Optional[int] = Field(None, description="Süreç çıkış kodu")
    stdout: str = Field(default="", description="Standart çıktı metni")
    stderr: str = Field(default="", description="Standart hata metni")
    duration_ms: float = Field(default=0.0, description="Toplam çalışma süresi (milisaniye)")
    isolation_type: str = Field(..., description="Kullanılan izolasyon türü ('docker', 'mock', 'none', 'subprocess_unsafe')")
    error: Optional[str] = Field(None, description="Varsa hata veya bloklama açıklaması")
    raw_output: str = Field(default="", description="Ham birleşik çıktı")


class BaseExecutionEngine(abc.ABC):
    """Tüm kod yürütme motorlarının türediği soyut temel sınıf."""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Motorun mevcut ortamda çalıştırılabilir (Docker daemon aktif vb.) olup olmadığını bildirir."""
        pass

    @abc.abstractmethod
    def get_isolation_type(self) -> str:
        """İzolasyon türünü döndürür ('docker', 'mock', 'none', 'subprocess_unsafe')."""
        pass

    @abc.abstractmethod
    def execute_sync(
        self,
        workspace_path: str,
        command: List[str],
        config: Optional[ExecutionConfig] = None
    ) -> ExecutionResult:
        """Belirtilen komutu izole ortamda senkron olarak çalıştırır."""
        pass

    async def execute(
        self,
        workspace_path: str,
        command: List[str],
        config: Optional[ExecutionConfig] = None
    ) -> ExecutionResult:
        """Belirtilen komutu izole ortamda asenkron olarak çalıştırır."""
        return await asyncio.to_thread(self.execute_sync, workspace_path, command, config)
