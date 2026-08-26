from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/skus", tags=["SKUs"])

@router.get("/", response_model=List[schemas.SKUResponse])
def list_skus(db: Session = Depends(get_db)):
    return db.query(models.SKU).all()

@router.post("/", response_model=schemas.SKUResponse)
def create_sku(sku: schemas.SKUCreate, db: Session = Depends(get_db)):
    db_obj = models.SKU(**sku.model_dump())
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj