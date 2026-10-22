"""
Izole Calisma Alani - FastAPI REST API Router
Bu dosya Coder Agent tarafindan gorev kapsaminda otomatik uretilmistir.
"""

import uuid
from typing import Dict, List
from fastapi import APIRouter, HTTPException, status
from models import ItemCreate, ItemResponse

router = APIRouter(prefix="/items", tags=["Items Feature"])

# Izole bellek ici veri deposu
_items_db: Dict[str, dict] = {}


@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(payload: ItemCreate) -> ItemResponse:
    item_id = f"item_{uuid.uuid4().hex[:8]}"
    item_data = payload.model_dump()
    item_data["id"] = item_id
    _items_db[item_id] = item_data
    return ItemResponse(**item_data)


@router.get("/", response_model=List[ItemResponse])
async def list_items() -> List[ItemResponse]:
    return [ItemResponse(**item) for item in _items_db.values()]


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(item_id: str) -> ItemResponse:
    item = _items_db.get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oge bulunamadi.")
    return ItemResponse(**item)
