import uuid
from sqlalchemy import Column, String, Boolean, Integer, Numeric, DateTime, ForeignKey, Text, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base

class Retailer(Base):
    __tablename__ = "retailers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    base_url = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SKU(Base):
    __tablename__ = "skus"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ean_gtin = Column(String(14), unique=True)
    internal_code = Column(String(50))
    brand = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class MonitoringConfig(Base):
    __tablename__ = "monitoring_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(150), nullable=False)
    retailer_id = Column(UUID(as_uuid=True), ForeignKey("retailers.id"), nullable=False)
    sku_id = Column(UUID(as_uuid=True), ForeignKey("skus.id"), nullable=True)
    search_keyword = Column(String(255), nullable=True)
    frequency_hours = Column(Integer, nullable=False, default=6)
    start_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())