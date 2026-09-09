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
from app.routers import retailers, configs, results, analytics
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

DATABASE_URL = os.getenv("DATABASE_URL")
def get_db_connection():
    if not DATABASE_URL:
        raise HTTPException(
            status_code=500, detail="Error BD: La variable DATABASE_URL no está configurada."
        )
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error BD: {str(e)}")
def save_scraper_results(conn, results: list, retailer: str) -> int:
    if not results:
        return 0
    insert_query = """
        INSERT INTO scraper_results (
            retailer, search_term, product_name, brand, position,
            price, discount_price, is_available, seller_name
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
    """
    saved_count = 0
    formatted_retailer = retailer.capitalize() if retailer else "Unknown"
    with conn.cursor() as cur:
        for item in results:
            try:
                term = getattr(item, "search_keyword", None)
                pos = getattr(item, "search_position", None)
                title = getattr(item, "title", "") or ""
                brand = getattr(item, "brand", None) or "Sin Marca"
                base_price = getattr(item, "base_price", 0.0)
                disc_price = getattr(item, "discount_price", None)
                stock = getattr(item, "in_stock", True)
                seller_name = getattr(item, "seller_name", None) or getattr(item, "seller", None) or formatted_retailer
                cur.execute(
                    insert_query,
                    (
                        formatted_retailer,
                        term,
                        title,
                        str(brand).strip(),
                        pos,
                        base_price,
                        disc_price,
                        stock,
                        seller_name,
                    ),
                )
                saved_count += 1
            except Exception as e:
                print(f"[DB ERROR] {formatted_retailer}: {e}", flush=True)
    conn.commit()
    return saved_count

async def run_farmatodo_scraping(conn):
    search_configs = []
    with conn.cursor() as cur:
        cur.execute("SELECT search_term FROM search_configs WHERE is_active = TRUE;")
        rows = cur.fetchall()
        search_configs = [r["search_term"] for r in rows] if rows else []
    if not search_configs:
        print("[FARMATODO SCRAPING] No hay términos activos.", flush=True)
        return 0
    total_saved = 0
    from app.services.scrapers.farmatodo_scraper import FarmatodoScraper
    print("\n[SCRAPING] Iniciando extracción para: FARMATODO", flush=True)
    scraper = FarmatodoScraper()
    for term in search_configs:
        try:
            results = await scraper.search_keyword(term, limit=50)
            if results:
                count = save_scraper_results(conn, results, retailer="farmatodo")
                total_saved += count
                print(f"[FARMATODO] Guardados {count} para '{term}'.", flush=True)
            else:
                print(f"[FARMATODO] Sin resultados para '{term}'.", flush=True)
        except Exception as e:
            print(f"[SCRAPING ERROR] FARMATODO '{term}': {e}", flush=True)
    return total_saved
async def run_rappi_scraping(conn):
    search_configs = []
    with conn.cursor() as cur:
        cur.execute("SELECT search_term FROM search_configs WHERE is_active = TRUE;")
        rows = cur.fetchall()
        search_configs = [r["search_term"] for r in rows] if rows else []
    if not search_configs:
        return 0
    total_saved = 0
    from app.services.scrapers.rappi_scraper import RappiScraper
    print("\n[SCRAPING] Iniciando extracción para: RAPPI", flush=True)
    scraper = RappiScraper()
    for term in search_configs:
        try:
            results = await scraper.search_keyword(term, limit=50)
            if results:
                count = save_scraper_results(conn, results, retailer="rappi")
                total_saved += count
                print(f"[RAPPI] Guardados {count} para '{term}'.", flush=True)
            else:
                print(f"[RAPPI] Sin resultados para '{term}'.", flush=True)
        except Exception as e:
            print(f"[SCRAPING ERROR] RAPPI '{term}': {e}", flush=True)
    return total_saved
async def run_all_scraping(conn):
    total_records = 0
    try:
        from app.services.scrapers.vtex_scraper import run_vtex_scraping
        total_records += await run_vtex_scraping(conn)
    except Exception as e:
        print(f"[MAIN ERROR] VTEX Scraper: {e}", flush=True)
    try:
        total_records += await run_farmatodo_scraping(conn)
    except Exception as e:
        print(f"[MAIN ERROR] Farmatodo Scraper: {e}", flush=True)
    try:
        total_records += await run_rappi_scraping(conn)
    except Exception as e:
        print(f"[MAIN ERROR] Rappi Scraper: {e}", flush=True)
    return total_records
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
@app.post("/trigger-now")
@app.post("/trigger-now/")
async def trigger_now():
    conn = get_db_connection()
    try:
        total_records = await run_all_scraping(conn)
        return {
            "status": "success",
            "message": f"Monitoreo ejecutado correctamente. {total_records} productos guardados.",
            "total_records": total_records,
        }
    except Exception as e:
        print(f"[TRIGGER ERROR] {e}", flush=True)
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()
