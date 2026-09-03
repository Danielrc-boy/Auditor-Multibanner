import os
import io
import json
from uuid import UUID
from typing import Optional, List
from datetime import datetime
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="Digital Shelf & Retail Intelligence API")

# --- CONFIGURACIÓN DE CORS ---
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
            price, discount_price, is_available
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
    """
    saved_count = 0
    formatted_retailer = retailer.capitalize() if retailer else "Unknown"
    with conn.cursor() as cur:
        for item in results:
            try:
                term = getattr(item, "search_keyword", None) or item.get("search_keyword")
                pos = getattr(item, "search_position", None) or item.get("search_position")
                title = getattr(item, "title", None) or item.get("title") or ""
                brand = getattr(item, "brand", None) or item.get("brand") or "Sin Marca"
                base_price = getattr(item, "base_price", 0.0) if hasattr(item, "base_price") else item.get("base_price", 0.0)
                disc_price = getattr(item, "discount_price", None) if hasattr(item, "discount_price") else item.get("discount_price")
                stock = getattr(item, "in_stock", True) if hasattr(item, "in_stock") else item.get("in_stock", True)

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
        return 0
    total_saved = 0
    try:
        from app.services.scrapers.farmatodo_scraper import FarmatodoScraper
        scraper = FarmatodoScraper()
        for term in search_configs:
            results = await scraper.search_keyword(term, limit=50)
            if results:
                count = save_scraper_results(conn, results, retailer="farmatodo")
                total_saved += count
    except Exception as e:
        print(f"[SCRAPING ERROR] FARMATODO: {e}", flush=True)
    return total_saved

async def run_rappi_scraping(conn):
    return 0 

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

@app.get("/dashboard-data")
def get_dashboard_data(
    retailer: Optional[str] = Query("ALL"),
    search_term: Optional[str] = Query("ALL")
):
    conn = get_db_connection()
    cursor = conn.cursor()
    where_clause = "WHERE 1=1"
    params = []
    if retailer and retailer != "ALL":
        where_clause += " AND retailer ILIKE %s"
        params.append(f"%{retailer}%")
    if search_term and search_term != "ALL":
        where_clause += " AND search_term ILIKE %s"
        params.append(f"%{search_term}%")

    query_kpis = f"""
        SELECT 
            COUNT(*) as total_monitored,
            COALESCE(ROUND(AVG(CASE WHEN is_available THEN 1 ELSE 0 END) * 100, 1), 0) as availability_rate,
            SUM(CASE WHEN NOT is_available THEN 1 ELSE 0 END) as out_of_stock_alerts,
            COALESCE(ROUND(AVG(CASE WHEN price > 0 AND discount_price IS NOT NULL THEN ((price - discount_price) / price) * 100 ELSE 0 END), 1), 0) as avg_discount_pct
        FROM scraper_results {where_clause};
    """
    cursor.execute(query_kpis, tuple(params))
    kpis = cursor.fetchone()

    cursor.execute("SELECT DISTINCT retailer FROM scraper_results WHERE retailer IS NOT NULL;")
    retailers = [r["retailer"] for r in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT search_term FROM scraper_results WHERE search_term IS NOT NULL;")
    terms = [t["search_term"] for t in cursor.fetchall()]

    cursor.close()
    conn.close()

    return {
        "summary": kpis or {"total_monitored": 0, "availability_rate": 0, "out_of_stock_alerts": 0, "avg_discount_pct": 0},
        "filters": {"retailers": retailers, "search_terms": terms}
    }

@app.get("/analytics/options")
def get_analytics_options():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT COALESCE(brand, 'Sin Marca') as brand FROM scraper_results ORDER BY brand ASC;")
    brands = [b["brand"] for b in cursor.fetchall()]
    cursor.execute("SELECT DISTINCT product_name FROM scraper_results WHERE product_name IS NOT NULL ORDER BY product_name ASC;")
    products = [p["product_name"] for p in cursor.fetchall()]
    cursor.close()
    conn.close()
    return {"brands": brands, "products": products}

@app.get("/analytics/positions")
@app.get("/results")
def get_positions(
    retailer: Optional[str] = Query("ALL"),
    search_term: Optional[str] = Query("ALL"),
    brand: Optional[str] = Query("ALL"),
    product_name: Optional[str] = Query("ALL"),
    query: Optional[str] = Query(None),
    limit: int = Query(100)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    sql = "SELECT * FROM scraper_results WHERE 1=1"
    params = []

    if retailer and retailer != "ALL":
        sql += " AND retailer ILIKE %s"
        params.append(f"%{retailer}%")
    if search_term and search_term != "ALL":
        sql += " AND search_term ILIKE %s"
        params.append(f"%{search_term}%")
    if brand and brand != "ALL":
        sql += " AND brand ILIKE %s"
        params.append(f"%{brand}%")
    if product_name and product_name != "ALL":
        sql += " AND product_name ILIKE %s"
        params.append(f"%{product_name}%")
    if query:
        sql += " AND product_name ILIKE %s"
        params.append(f"%{query}%")

    sql += " ORDER BY id DESC LIMIT %s;"
    params.append(limit)

    cursor.execute(sql, tuple(params))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

@app.post("/trigger-now")
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
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()