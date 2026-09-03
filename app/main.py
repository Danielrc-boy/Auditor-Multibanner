import os
import io
import asyncio
from uuid import UUID
from typing import Optional, List
from datetime import datetime
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="Digital Shelf & Retail Intelligence API")

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
                term = item.get("search_keyword")
                pos = item.get("search_position")
                title = item.get("title", "") or ""
                brand = item.get("brand") or "Sin Marca"
                base_price = item.get("base_price", 0.0)
                disc_price = item.get("discount_price")
                stock = item.get("in_stock", True)
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

# --- SCRAPER ROBUSTO PARA ÉXITO Y CARULLA (INTELLIGENT SEARCH & VTEX API) ---
async def fetch_vtex_products(domain: str, retailer_name: str, search_term: str, limit: int = 50):
    # Intentamos primero con la API de Intelligent Search (Usada por las versiones modernas de Éxito y Carulla)
    encoded_term = requests.utils.quote(search_term)
    url_intelligent = f"https://www.{domain}/api/io/_v/api/intelligent-search/product_search/{encoded_term}?workspace=master&maxItems={limit}&page=1"
    url_legacy = f"https://www.{domain}/api/catalog_system/pub/products/search/{encoded_term}?O=OrderByTopSaleDESC&_from=0&_to={limit-1}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-ES,es;q=0.9",
        "Cache-Control": "no-cache"
    }
    
    results = []
    
    try:
        # Intento 1: Intelligent Search
        response = requests.get(url_intelligent, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            products = data.get("products", [])
            for idx, prod in enumerate(products, start=1):
                items = prod.get("items", [])
                sellers = items[0].get("sellers", []) if items else []
                comm_offer = sellers[0].get("commertialOffer", {}) if sellers else {}
                
                list_price = comm_offer.get("ListPrice", 0.0)
                price = comm_offer.get("Price", 0.0)
                available = comm_offer.get("AvailableQuantity", 0) > 0

                results.append({
                    "search_keyword": search_term,
                    "search_position": idx,
                    "title": prod.get("productName", ""),
                    "brand": prod.get("brand", "Sin Marca"),
                    "base_price": list_price if list_price > 0 else price,
                    "discount_price": price if price < list_price else None,
                    "in_stock": available
                })
        
        # Intento 2: Fallback a API Legacy si Intelligent Search no devuelve nada
        if not results:
            response_legacy = requests.get(url_legacy, headers=headers, timeout=10)
            if response_legacy.status_code == 200:
                data_legacy = response_legacy.json()
                for idx, prod in enumerate(data_legacy, start=1):
                    items = prod.get("items", [])
                    sellers = items[0].get("sellers", []) if items else []
                    comm_offer = sellers[0].get("commertialOffer", {}) if sellers else {}
                    
                    list_price = comm_offer.get("ListPrice", 0.0)
                    price = comm_offer.get("Price", 0.0)
                    available = comm_offer.get("AvailableQuantity", 0) > 0

                    results.append({
                        "search_keyword": search_term,
                        "search_position": idx,
                        "title": prod.get("productName", ""),
                        "brand": prod.get("brand", "Sin Marca"),
                        "base_price": list_price if list_price > 0 else price,
                        "discount_price": price if price < list_price else None,
                        "in_stock": available
                    })
    except Exception as e:
        print(f"[{retailer_name.upper()} ERROR] Excepción consultando '{search_term}': {e}", flush=True)
        
    return results

async def run_vtex_scraping(conn):
    search_configs = []
    with conn.cursor() as cur:
        cur.execute("SELECT search_term FROM search_configs WHERE is_active = TRUE;")
        rows = cur.fetchall()
        search_configs = [r["search_term"] for r in rows] if rows else []
    
    if not search_configs:
        return 0

    total_saved = 0
    vtex_targets = [
        {"domain": "exito.com", "name": "Éxito"},
        {"domain": "carulla.com", "name": "Carulla"}
    ]

    for target in vtex_targets:
        print(f"\n[SCRAPING] Iniciando extracción para: {target['name']}", flush=True)
        for term in search_configs:
            results = await fetch_vtex_products(target["domain"], target["name"], term)
            if results:
                count = save_scraper_results(conn, results, retailer=target["name"])
                total_saved += count
                print(f"[{target['name']}] Guardados {count} para '{term}'.", flush=True)
            else:
                print(f"[{target['name']}] Sin resultados para '{term}'.", flush=True)
    return total_saved

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
        print("\n[SCRAPING] Iniciando extracción para: FARMATODO", flush=True)
        for term in search_configs:
            results = await scraper.search_keyword(term, limit=50)
            if results:
                count = save_scraper_results(conn, results, retailer="farmatodo")
                total_saved += count
                print(f"[FARMATODO] Guardados {count} para '{term}'.", flush=True)
            else:
                print(f"[FARMATODO] Sin resultados para '{term}'.", flush=True)
    except Exception as e:
        print(f"[SCRAPING ERROR] FARMATODO: {e}", flush=True)
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
    try:
        from app.services.scrapers.rappi_scraper import RappiScraper
        scraper = RappiScraper()
        print("\n[SCRAPING] Iniciando extracción para: RAPPI", flush=True)
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
                print(f"[ERROR RAPPI] Error al scrapear '{term}': {e}", flush=True)
    except Exception as e:
        print(f"[SCRAPING ERROR] RAPPI: {e}", flush=True)
    return total_saved

async def run_all_scraping(conn):
    total_records = 0
    total_records += await run_vtex_scraping(conn)
    total_records += await run_farmatodo_scraping(conn)
    total_records += await run_rappi_scraping(conn)
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
        "summary": kpis,
        "filters": {
            "retailers": retailers,
            "search_terms": terms
        }
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
def get_analytics_positions(
    retailer: Optional[str] = Query("ALL"),
    search_term: Optional[str] = Query("ALL"),
    brand: Optional[str] = Query("ALL"),
    product_name: Optional[str] = Query("ALL"),
    query: Optional[str] = Query(None),
    limit: int = Query(50)
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