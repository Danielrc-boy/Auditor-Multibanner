from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/retailers", tags=["Retailers"])

@router.get("/", response_model=List[schemas.RetailerResponse])
def list_retailers(db: Session = Depends(get_db)):
    return db.query(models.Retailer).all()

@router.post("/", response_model=schemas.RetailerResponse)
def create_retailer(retailer: schemas.RetailerCreate, db: Session = Depends(get_db)):
    db_obj = models.Retailer(**retailer.model_dump())
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj