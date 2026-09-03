import os
import io
import json
import urllib.parse
from uuid import UUID
from typing import Optional, List
from datetime import datetime
import pandas as pd
import httpx
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
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")

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

# --- FUNCIÓN DE GUARDADO COMPATIBLE (SOPORTA DICCIONARIOS Y OBJETOS) ---
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
                # Extrae los datos sin importar si el item es un Dict o una Clase Pydantic
                term = item.get("search_keyword") if isinstance(item, dict) else getattr(item, "search_keyword", None)
                pos = item.get("search_position") if isinstance(item, dict) else getattr(item, "search_position", None)
                title = (item.get("title") if isinstance(item, dict) else getattr(item, "title", "")) or ""
                brand = (item.get("brand") if isinstance(item, dict) else getattr(item, "brand", None)) or "Sin Marca"
                base_price = item.get("base_price") if isinstance(item, dict) else getattr(item, "base_price", 0.0)
                disc_price = item.get("discount_price") if isinstance(item, dict) else getattr(item, "discount_price", None)
                stock = item.get("in_stock") if isinstance(item, dict) else getattr(item, "in_stock", True)

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

# --- SCRAPER DEDICADO Y ROBUSTO PARA VTEX (ÉXITO & CARULLA) ---
class VTEXScraper:
    def __init__(self, retailer: str = "exito"):
        self.retailer = retailer.lower()
        self.base_url = "https://www.carulla.com" if self.retailer == "carulla" else "https://www.exito.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "es-CO,es;q=0.9",
        }

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[dict]:
        variables_payload = {
            "first": limit,
            "after": "0",
            "sort": "score_desc",
            "term": keyword,
            "selectedFacets": [
                {"key": "channel", "value": json.dumps({"salesChannel": "1", "regionId": ""})},
                {"key": "locale", "value": "es-CO"}
            ]
        }
        encoded_variables = urllib.parse.quote(json.dumps(variables_payload))
        gql_url = f"{self.base_url}/api/graphql?operationName=SearchQuery&variables={encoded_variables}"
        
        request_url, params = self._build_request(gql_url, None)

        async with httpx.AsyncClient(timeout=25.0, verify=False, follow_redirects=True) as client:
            # Estrategia 1: GraphQL Directo
            try:
                response = await client.get(request_url, headers=self.headers, params=params)
                if response.status_code == 200:
                    products = self._parse_graphql_response(response.json(), keyword)
                    if products:
                        return products
            except Exception as e:
                print(f"[WARN {self.retailer.upper()}] GraphQL falló para '{keyword}': {e}", flush=True)

            # Estrategia 2: Fallback REST Intelligent Search
            is_url = f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/{urllib.parse.quote(keyword)}"
            is_params = {"page": 1, "count": limit, "sort": "score_desc", "locale": "es-CO"}
            req_is_url, req_is_params = self._build_request(is_url, is_params)
            
            try:
                response = await client.get(req_is_url, headers=self.headers, params=req_is_params)
                if response.status_code in (200, 206):
                    data = response.json()
                    products_raw = data.get("products", []) if isinstance(data, dict) else []
                    if products_raw:
                        return self._parse_intelligent_search(products_raw, keyword, limit)
            except Exception as e:
                print(f"[ERROR {self.retailer.upper()}] REST Search falló para '{keyword}': {e}", flush=True)

        return []

    def _build_request(self, target_url: str, params_dict: dict = None):
        if SCRAPERAPI_KEY:
            if params_dict:
                query_string = "&".join([f"{k}={v}" for k, v in params_dict.items()])
                full_target = f"{target_url}?{query_string}"
            else:
                full_target = target_url
            return "http://api.scraperapi.com/", {"api_key": SCRAPERAPI_KEY, "url": full_target}
        return target_url, params_dict

    def _parse_graphql_response(self, data: dict, search_term: str) -> List[dict]:
        parsed = []
        try:
            edges = data.get("data", {}).get("search", {}).get("products", {}).get("edges", [])
            for idx, edge in enumerate(edges, start=1):
                node = edge.get("node", {})
                offers = node.get("offers", {}).get("offers", [{}])
                offer = offers[0] if offers else {}

                price = float(offer.get("price", 0.0) or 0.0)
                list_price = float(offer.get("listPrice", 0.0) or price)
                discount_price = price if (0 < price < list_price) else None

                parsed.append({
                    "search_keyword": search_term,
                    "search_position": idx,
                    "title": node.get("name", "Sin título"),
                    "brand": node.get("brand", {}).get("name", "Sin Marca"),
                    "base_price": list_price,
                    "discount_price": discount_price,
                    "in_stock": "InStock" in str(offer.get("availability", ""))
                })
        except Exception as e:
            print(f"[PARSER GQL ERROR] {self.retailer.upper()}: {e}", flush=True)
        return parsed

    def _parse_intelligent_search(self, products: list, search_term: str, limit: int) -> List[dict]:
        parsed = []
        for idx, prod in enumerate(products[:limit], start=1):
            try:
                items = prod.get("items", [])
                item = items[0] if items else {}
                sellers = item.get("sellers", [{}])
                comm = sellers[0].get("commertialOffer", {}) if sellers else {}

                price = float(prod.get("price", 0.0) or comm.get("Price", 0.0) or 0.0)
                base_price = float(prod.get("listPrice", 0.0) or comm.get("ListPrice", 0.0) or price)
                discount_price = price if (0 < price < base_price) else None
                in_stock = prod.get("isAvailable", True) if "isAvailable" in prod else (comm.get("AvailableQuantity", 0) > 0)

                parsed.append({
                    "search_keyword": search_term,
                    "search_position": idx,
                    "title": prod.get("productName") or prod.get("name") or "Sin título",
                    "brand": prod.get("brand") or prod.get("brandName") or "Sin Marca",
                    "base_price": base_price,
                    "discount_price": discount_price,
                    "in_stock": in_stock
                })
            except Exception as e:
                continue
        return parsed

async def run_vtex_scraping(conn) -> int:
    search_configs = []
    with conn.cursor() as cur:
        cur.execute("SELECT search_term FROM search_configs WHERE is_active = TRUE;")
        rows = cur.fetchall()
        search_configs = [r["search_term"] for r in rows] if rows else []
    if not search_configs:
        return 0

    total_saved = 0
    for retailer_name in ["exito", "carulla"]:
        print(f"\n[SCRAPING] Iniciando extracción para: {retailer_name.upper()}", flush=True)
        scraper = VTEXScraper(retailer=retailer_name)
        for term in search_configs:
            try:
                results = await scraper.search_keyword(term, limit=50)
                if results:
                    count = save_scraper_results(conn, results, retailer=retailer_name)
                    total_saved += count
                    print(f"[{retailer_name.upper()}] Guardados {count} para '{term}'.", flush=True)
                else:
                    print(f"[{retailer_name.upper()}] Sin resultados para '{term}'.", flush=True)
            except Exception as e:
                print(f"[SCRAPING ERROR] {retailer_name.upper()} '{term}': {e}", flush=True)
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
        for term in search_configs:
            results = await scraper.search_keyword(term, limit=50)
            if results:
                count = save_scraper_results(conn, results, retailer="farmatodo")
                total_saved += count
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
        for term in search_configs:
            results = await scraper.search_keyword(term, limit=50)
            if results:
                count = save_scraper_results(conn, results, retailer="rappi")
                total_saved += count
    except Exception as e:
        print(f"[SCRAPING ERROR] RAPPI: {e}", flush=True)
    return total_saved

async def run_all_scraping(conn):
    total_records = 0
    total_records += await run_vtex_scraping(conn)
    total_records += await run_farmatodo_scraping(conn)
    total_records += await run_rappi_scraping(conn)
    return total_records

class SearchConfigCreate(BaseModel):
    search_term: Optional[str] = None
    keyword: Optional[str] = None

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

@app.delete("/admin/clean-db")
def clean_db(confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=400, detail="Debe confirmar la acción.")
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("TRUNCATE TABLE scraper_results RESTART IDENTITY;")
        conn.commit()
        return {"status": "success", "message": "Base de datos limpiada correctamente."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()