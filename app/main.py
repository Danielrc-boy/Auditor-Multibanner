import os
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, Depends, Query, HTTPException
from sqlmodel import Session, select, SQLModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db import get_session
# Importa tu función ejecutora del pipeline existente
from app.services.orchestrator import run_monitoring_pipeline 
# Importa el modelo ORM correspondiente a la tabla scraper_results
from app.models import ScraperResult  

app = FastAPI(title="Auditor Multibanner API")

# Inicialización del planificador en segundo plano
scheduler = AsyncIOScheduler()

async def scheduled_monitoring_job():
    """Tarea programada que ejecuta el pipeline cada 6 horas."""
    print(f"[CRON JOB] Iniciando ejecución automática: {datetime.now()}", flush=True)
    try:
        # Se asume una sesión dedicada para el job en segundo plano
        from app.db import engine
        with Session(engine) as session:
            await run_monitoring_pipeline(session)
        print(f"[CRON JOB] Ejecución automática completada exitosamente.", flush=True)
    except Exception as e:
        print(f"[CRON JOB ERROR] Falló la ejecución automática: {str(e)}", flush=True)

@app.on_event("startup")
def start_scheduler():
    """Inicia el scheduler al arrancar Uvicorn/FastAPI."""
    # Programa la ejecución cada 6 horas
    scheduler.add_job(
        scheduled_monitoring_job, 
        'interval', 
        hours=6, 
        id="monitoring_cron_6h",
        replace_existing=True
    )
    scheduler.start()
    print("[SCHEDULER] APScheduler iniciado correctamente (frecuencia: cada 6 horas).", flush=True)

@app.on_event("shutdown")
def stop_scheduler():
    """Detiene el scheduler al apagar el servidor."""
    scheduler.shutdown()
    print("[SCHEDULER] APScheduler detenido.", flush=True)

# --- ENDPOINTS ---

@app.post("/trigger-now")
async def trigger_now(session: Session = Depends(get_session)):
    """Ejecución manual bajo demanda desde el botón de la Web o curl."""
    results = await run_monitoring_pipeline(session)
    return {
        "status": "success",
        "message": f"Monitoreo ejecutado correctamente. {len(results)} productos guardados en la BD.",
        "total_records": len(results)
    }

@app.get("/results")
def get_results(
    retailer: Optional[str] = Query(None, description="Filtrar por tienda (ej: Exito, Carulla)"),
    search_term: Optional[str] = Query(None, description="Filtrar por término (ej: ducales)"),
    date_from: Optional[datetime] = Query(None, description="Fecha inicial en formato ISO (YYYY-MM-DDTHH:MM:SS)"),
    date_to: Optional[datetime] = Query(None, description="Fecha final en formato ISO (YYYY-MM-DDTHH:MM:SS)"),
    limit: int = Query(100, ge=1, le=1000, description="Límite de registros a retornar"),
    session: Session = Depends(get_session)
):
    """Consulta histórica de datos extraídos con filtros opcionales."""
    statement = select(ScraperResult)

    if retailer:
        statement = statement.where(ScraperResult.retailer.ilike(f"%{retailer}%"))
    if search_term:
        statement = statement.where(ScraperResult.search_term.ilike(f"%{search_term}%"))
    if date_from:
        statement = statement.where(ScraperResult.captured_at >= date_from)
    if date_to:
        statement = statement.where(ScraperResult.captured_at <= date_to)

    # Ordenamiento por fecha descendente usando el campo confirmado
    statement = statement.order_by(ScraperResult.captured_at.desc()).limit(limit)

    results = session.exec(statement).all()
    return results