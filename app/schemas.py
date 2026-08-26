from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID

class RetailerCreate(BaseModel):
    code: str
    name: str
    base_url: str

class RetailerResponse(RetailerCreate):
    id: UUID
    is_active: bool
    model_config = ConfigDict(from_attributes=True)

class SKUCreate(BaseModel):
    title: str
    brand: str
    ean_gtin: Optional[str] = None
    internal_code: Optional[str] = None

class SKUResponse(SKUCreate):
    id: UUID
    model_config = ConfigDict(from_attributes=True)

class MonitoringConfigCreate(BaseModel):
    name: str
    retailer_id: UUID
    sku_id: Optional[UUID] = None
    search_keyword: Optional[str] = None
    frequency_hours: int = 6
    end_date: Optional[datetime] = None

class MonitoringConfigResponse(MonitoringConfigCreate):
    id: UUID
    is_active: bool
    start_date: datetime
    model_config = ConfigDict(from_attributes=True)