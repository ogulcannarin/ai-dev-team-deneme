"""
Izole Calisma Alani - Veri Modelleri ve Semalar
Bu dosya Coder Agent tarafindan gorev kapsaminda otomatik uretilmistir.
"""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100, description="Oge basligi")
    description: Optional[str] = Field(None, max_length=500, description="Detayli aciklama")
    is_completed: bool = Field(default=False, description="Tamamlanma durumu")


class ItemResponse(ItemCreate):
    id: str = Field(..., description="Benzersiz oge kimligi")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
