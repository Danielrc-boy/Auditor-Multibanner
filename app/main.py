import os
import importlib
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI()

# Configuración de dominios permitidos para CORS
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

def save_scraper_results(results: List[Dict[str, Any]]) -> int:
    """Inserta de forma masiva la lista de productos extraídos en PostgreSQL."""
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
        data_tuples = [
            (
                r.get("retailer") or r.get("store") or "Desconocido",
                r.get("search_term") or r.get("keyword") or "General",
                r.get("product_name") or r.get("title") or r.get("name"),
                r.get("position") or r.get("index"),
                r.get("price"),
                r.get("discount_price") or r.get("special_price"),
                r.get("is_available", True)
            )
            for r in results
            if r.get("product_name") or r.get("title") or r.get("name")
        ]
        
        if not data_tuples:
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

def execute_scrapers_for_term(term: str) -> List[Dict[str, Any]]:
    """Ejecuta los módulos ubicados en app.services.scrapers."""
    extracted = []
    
    # 1. Intentar importar la función orquestadora principal si existe en el paquete
    try:
        pkg = importlib.import_module("app.services.scrapers")
        if hasattr(pkg, "run_all_scrapers"):
            res = pkg.run_all_scrapers(term)
            return res if isinstance(res, list) else []
    except ImportError:
        pass

    # 2. Si no hay un orquestador expuesto en __init__.py, intenta ejecutar los scrapers individuales conocidos
    scraper_modules = ["exito", "jumbo", "olimpica", "base_scraper", "runner"]
    
    for mod_name in scraper_modules:
        try:
            mod = importlib.import_module(f"app.services.scrapers.{mod_name}")
            for fn_name in ["run", "scrape", "search", "run_scraper", "execute"]:
                fn = getattr(mod, fn_name, None)
                if fn and callable(fn):
                    res = fn(term)
                    if isinstance(res, list):
                        extracted.extend(res)
                    break
        except ImportError:
            continue
            
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
def trigger_now():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT search_term FROM search_configs;")
    configs = cursor.fetchall()
    cursor.close()
    conn.close()

    if not configs:
        return {"status": "warning", "message": "No hay términos configurados para buscar."}

    all_extracted_products = []
    for cfg in configs:
        term = cfg["search_term"]
        results = execute_scrapers_for_term(term)
        if results:
            all_extracted_products.extend(results)

    total_saved = save_scraper_results(all_extracted_products)

    return {
        "status": "success",
        "message": f"Monitoreo ejecutado. {total_saved} registros insertados.",
        "total_records": total_saved
    }