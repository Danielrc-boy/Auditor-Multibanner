import os
import io
from uuid import UUID
from typing import Optional, List
from datetime import datetime
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
from app.database import get_db_connection
from app.routers import retailers, configs, results, analytics, scraping, internal
app = FastAPI()
origins = [
    "https://auditor-multibanner.vercel.app",
    "https://auditor-multibanner-i2djrxig5-daniel-restrepo.vercel.app",
    "http://localhost:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://auditor-multibanner-.*-daniel-restrepo\.vercel\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(retailers.router)
app.include_router(configs.router)
app.include_router(results.router)
app.include_router(analytics.router)
app.include_router(scraping.router)
app.include_router(internal.router)

@app.get("/")
def read_root():
    return {"message": "API Monitoreo Activa"}

@app.get("/version")
def get_version():
    """
    Confirma qué commit está corriendo realmente en este ambiente (staging
    o producción) sin tener que adivinar si un deploy ya terminó de
    propagarse -- Railway inyecta estas variables automáticamente en cada
    deploy, sin configuración adicional.
    """
    commit_sha = os.getenv("RAILWAY_GIT_COMMIT_SHA", "unknown")
    return {
        "commit": commit_sha[:7] if commit_sha != "unknown" else commit_sha,
        "commit_full": commit_sha,
        "branch": os.getenv("RAILWAY_GIT_BRANCH", "unknown"),
        "environment": os.getenv("RAILWAY_ENVIRONMENT_NAME", "unknown"),
    }

@app.get("/dashboard")
def get_dashboard_page():
    if os.path.exists("app/dashboard.html"):
        return FileResponse("app/dashboard.html")
    if os.path.exists("dashboard.html"):
        return FileResponse("dashboard.html")
    raise HTTPException(status_code=404, detail="dashboard.html no encontrado.")

@app.get("/internal/tools")
def get_internal_tools_page():
    # Página interna, sin link desde dashboard.html -- protegida por
    # INTERNAL_ADMIN_KEY en el endpoint que realmente borra datos
    # (ver app/routers/internal.py), no por ocultar esta URL.
    if os.path.exists("app/internal_tools.html"):
        return FileResponse("app/internal_tools.html")
    raise HTTPException(status_code=404, detail="internal_tools.html no encontrado.")


# --- ENDPOINT TEMPORAL DE PRUEBA: solo para validar Cruz Verde antes de ---
# --- integrarlo al flujo completo de guardado. Se retira despues de confirmar. ---
@app.get("/admin/test-cruzverde")
async def test_cruzverde(q: str = "toallas"):
    from app.services.scrapers.cruzverde_scraper import CruzVerdeScraper
    scraper = CruzVerdeScraper()
    results_list = await scraper.search_keyword(q, limit=10)
    return {"total": len(results_list), "productos": [r.dict() for r in results_list]}