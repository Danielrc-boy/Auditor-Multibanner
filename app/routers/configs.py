from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/configs", tags=["Monitoring Configs"])

@router.get("/", response_model=List[schemas.MonitoringConfigResponse])
def list_configs(db: Session = Depends(get_db)):
    return db.query(models.MonitoringConfig).all()

@router.post("/", response_model=schemas.MonitoringConfigResponse)
def create_config(config: schemas.MonitoringConfigCreate, db: Session = Depends(get_db)):
    if not config.sku_id and not config.search_keyword:
        raise HTTPException(status_code=400, detail="Debe proporcionar sku_id o search_keyword.")
    db_obj = models.MonitoringConfig(**config.model_dump())
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

@router.delete("/{config_id}")
def delete_config(config_id: UUID, db: Session = Depends(get_db)):
    config = db.query(models.MonitoringConfig).filter(models.MonitoringConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    db.delete(config)
    db.commit()
    return {"message": "Configuración eliminada correctamente"}