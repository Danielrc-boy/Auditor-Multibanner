import os
import inspect
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

from app.services.scrapers.vtex_scraper import VTEXScraper

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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error BD: {str(e)}")

def parse_item_field(obj: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(field_name, default)
    return getattr(obj, field_name, default)

def save_scraper_results(results: List[Any]) -> int:
    if not results:
        return 0

    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        INSERT INTO scraper_results 
        (retailer, search_term, product_name, position, price, discount_price, is_available)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """
    
    try:
        data_tuples = []
        for r in results:
            # Mapeo exacto basado en el modelo ExtractedProductData de vtex_scraper
            name = (
                parse_item_field(r, "title") or 
                parse_item_field(r, "product_name") or 
                parse_item_field(r, "name")
            )
            if not name:
                continue

            retailer = parse_item_field(r, "retailer") or parse_item_field(r, "store") or "Exito"
            search_term = (
                parse_item_field(r, "search_keyword") or 
                parse_item_field(r, "search_term") or 
                parse_item_field(r, "keyword") or 
                "General"
            )
            position = parse_item_field(r, "search_position") or parse_item_field(r, "position")
            price = parse_item_field(r, "base_price") or parse_item_field(r, "price")
            discount_price = parse_item_field(r, "discount_price")
            is_available = parse_item_field(r, "in_stock", True)

            data_tuples.append((
                retailer,
                search_term,
                name,
                position,
                price,
                discount_price,
                is_available
            ))
        
        if not data_tuples:
            cursor.close()
            conn.close()
            return 0

        cursor.executemany(query, data_tuples)
        conn.commit()
        inserted_count = cursor.rowcount
        cursor.close()
        conn.close()
        return inserted_count
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Error insertando en scraper_results: {str(e)}")

async def run_vtex_scraping(terms: List[str]) -> List[Any]:
    extracted = []
    
    print(f"\n[LOG SCRAPER] 1. Términos a buscar recibidos: {terms}", flush=True)

    try:
        scraper = VTEXScraper()
    except Exception as inst_err:
        print(f"[LOG SCRAPER] ERROR al instanciar VTEXScraper: {inst_err}", flush=True)
        return []

    # PASO 3: Log con el nombre del método explícito confirmado
    METHOD_NAME = "scrape_keyword"
    print(f"[LOG SCRAPER] Ejecutando extracción explícita vía método: VTEXScraper.{METHOD_NAME}()", flush=True)

    for term in terms:
        try:
            # PASO 2: Llamada directa al método exacto de vtex_scraper
            raw_res = scraper.scrape_keyword(term)

            if inspect.isawaitable(raw_res):
                res = await raw_res
            else:
                res = raw_res

            count = len(res) if isinstance(res, list) else 0

            if count > 0:
                print(f"[LOG SCRAPER] 2. Término '{term}' vía '{METHOD_NAME}': devueltos {count} productos.", flush=True)
                extracted.extend(res)
            else:
                print(f"[LOG SCRAPER] 2. ALERTA: Término '{term}' vía '{METHOD_NAME}' devolvió 0 resultados. Tipo: {type(res)} | Raw: {res}", flush=True)

        except Exception as err:
            print(f"[LOG SCRAPER] 2. ERROR CAPTURADO buscando '{term}': {type(err).__name__} - {str(err)}", flush=True)

    if hasattr(scraper, "close") and callable(getattr(scraper, "close")):
        try:
            close_res = scraper.close()
            if inspect.isawaitable(close_res):
                await close_res
        except Exception:
            pass

    return extracted

class SearchConfigCreate(BaseModel):
    search_term: Optional[str] = None
    keyword: Optional[str] = None

@app.get("/")
def read_root():
    return {"message": "API Monitoreo Activa"}

@app.get("/retailers")
@app.get("/retailers/")
def get_retailers():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM retailers WHERE is_active = TRUE;")
    retailers = cursor.fetchall()
    cursor.close()
    conn.close()
    return retailers

@app.get("/configs")
@app.get("/configs/")
def get_configs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM search_configs ORDER BY created_at DESC;")
    configs = cursor.fetchall()
    cursor.close()
    conn.close()
    return configs

@app.post("/configs")
@app.post("/configs/")
def create_config(config: SearchConfigCreate):
    term = config.search_term or config.keyword
    if not term:
        raise HTTPException(status_code=400, detail="Debe proporcionar 'search_term' o 'keyword'.")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO search_configs (search_term) VALUES (%s) RETURNING *;",
            (term,)
        )
        new_config = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        return new_config
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Error guardando: {str(e)}")

@app.post("/trigger-now")
@app.post("/trigger-now/")
async def trigger_now():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT search_term FROM search_configs;")
    configs = cursor.fetchall()
    cursor.close()
    conn.close()

    if not configs:
        print("[LOG TRIGGER] ALERTA: No se encontraron términos en search_configs.", flush=True)
        return {"status": "warning", "message": "No hay términos configurados para buscar."}

    terms = [cfg["search_term"] for cfg in configs]
    
    extracted_products = await run_vtex_scraping(terms)

    print(f"\n[LOG TRIGGER] 3. Total elementos acumulados en extracted_products antes de save_scraper_results: {len(extracted_products)}", flush=True)

    total_saved = save_scraper_results(extracted_products)

    return {
        "status": "success",
        "message": f"Monitoreo ejecutado correctamente. {total_saved} productos guardados en la BD.",
        "total_records": total_saved
    }