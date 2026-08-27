import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Importaciones directas (sin 'app.' ni '.')
from db import get_session, engine
from services.orchestrator import run_monitoring_pipeline 
from models import ScraperResult  

scheduler = AsyncIOScheduler()

async def scheduled_monitoring_job():
    print(f"[CRON JOB] Ejecutando monitoreo automático: {datetime.now()}", flush=True)
    try:
        with Session(engine) as session:
            await run_monitoring_pipeline(session)
        print("[CRON JOB] Monitoreo automático completado exitosamente.", flush=True)
    except Exception as e:
        print(f"[CRON JOB ERROR] Falló la ejecución: {str(e)}", flush=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicia el Scheduler al arrancar
    scheduler.add_job(
        scheduled_monitoring_job, 
        'interval', 
        hours=6, 
        id="monitoring_cron_6h",
        replace_existing=True
    )
    scheduler.start()
    print("[SCHEDULER] APScheduler iniciado correctamente (cada 6 horas).", flush=True)
    yield
    # Apaga el Scheduler al detener la app
    scheduler.shutdown()
    print("[SCHEDULER] APScheduler detenido.", flush=True)

app = FastAPI(title="Auditor Multibanner API", lifespan=lifespan)

# --- ENDPOINTS ---

@app.post("/trigger-now")
async def trigger_now(session: Session = Depends(get_session)):
    results = await run_monitoring_pipeline(session)
    return {
        "status": "success",
        "message": f"Monitoreo ejecutado correctamente. {len(results)} productos guardados en la BD.",
        "total_records": len(results)
    }

@app.get("/results")
def get_results(
    retailer: Optional[str] = Query(None, description="Filtrar por tienda"),
    search_term: Optional[str] = Query(None, description="Filtrar por término"),
    date_from: Optional[datetime] = Query(None, description="Fecha inicial ISO"),
    date_to: Optional[datetime] = Query(None, description="Fecha final ISO"),
    limit: int = Query(100, ge=1, le=1000, description="Límite de registros"),
    session: Session = Depends(get_session)
):
    statement = select(ScraperResult)

    if retailer:
        statement = statement.where(ScraperResult.retailer.ilike(f"%{retailer}%"))
    if search_term:
        statement = statement.where(ScraperResult.search_term.ilike(f"%{search_term}%"))
    if date_from:
        statement = statement.where(ScraperResult.captured_at >= date_from)
    if date_to:
        statement = statement.where(ScraperResult.captured_at <= date_to)

    statement = statement.order_by(ScraperResult.captured_at.desc()).limit(limit)

    results = session.scalars(statement).all()
    return results