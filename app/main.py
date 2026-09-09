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
from app.routers import retailers, configs, results, analytics, scraping
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

@app.get("/")
def read_root():
    return {"message": "API Monitoreo Activa"}

@app.get("/dashboard")
def get_dashboard_page():
    if os.path.exists("app/dashboard.html"):
        return FileResponse("app/dashboard.html")
    if os.path.exists("dashboard.html"):
        return FileResponse("dashboard.html")
    raise HTTPException(status_code=404, detail="dashboard.html no encontrado.")