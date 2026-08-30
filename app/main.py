import os
import io
from typing import Optional
from datetime import datetime
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

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


def save_scraper_results(conn, results: list, retailer: str) -> int:
    if not results:
        return 0
    insert_query = """
        INSERT INTO scraper_results (
            retailer, search_term, product_name, position,
            price, discount_price, is_available
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """
    saved_count = 0
    formatted_retailer = retailer.capitalize() if retailer else "Unknown"
    with conn.cursor() as cur:
        for item in results:
            try:
                term = getattr(item, "search_keyword", None)
                pos = getattr(item, "search_position", None)
                title = getattr(item, "title", None)
                base_price = getattr(item, "base_price", 0.0)
                disc_price = getattr(item, "discount_price", None)
                stock = getattr(item, "in_stock", True)
                cur.execute(insert_query, (
                    formatted_retailer, term, title, pos,
                    base_price, disc_price, stock
                ))
                saved_count += 1
            except Exception as e:
                print(f"[DB ERROR] {formatted_retailer}: {e}", flush=True)
                conn.rollback()
                continue
    conn.commit()
    return saved_count


async def run_vtex_scraping(conn):
    search_configs = []
    with conn.cursor() as cur:
        cur.execute("SELECT search_term FROM search_configs;")
        rows = cur.fetchall()
        search_configs = [r["search_term"] for r in rows] if rows else []

    if not search_configs:
        print("[VTEX SCRAPING] No hay términos en search_configs.", flush=True)
        return 0

    retailers = ["exito", "carulla"]
    total_saved = 0

    from app.services.scrapers.vtex_scraper import VTEXScraper

    for retailer in retailers:
        print(f"\n[SCRAPING] Iniciando extracción para: {retailer.upper()}", flush=True)
        scraper = VTEXScraper(retailer=retailer)
        for term in search_configs:
            try:
                results = await scraper.search_keyword(term, limit=50)
                if results:
                    count = save_scraper_results(conn, results, retailer=retailer)
                    total_saved += count
                    print(f"[{retailer.upper()}] Guardados {count} para '{term}'.", flush=True)
                else:
                    print(f"[{retailer.upper()}] Sin resultados para '{term}'.", flush=True)
            except Exception as e:
                print(f"[SCRAPING ERROR] {retailer} '{term}': {e}", flush=True)

    return total_saved


async def run_farmatodo_scraping(conn):
    search_configs = []
    with conn.cursor() as cur:
        cur.execute("SELECT search_term FROM search_configs;")
        rows = cur.fetchall()
        search_configs = [r["search_term"] for r in rows] if rows else []

    if not search_configs:
        print("[FARMATODO SCRAPING] No hay términos en search_configs.", flush=True)
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


async def run_all_scraping(conn):
    vtex_total = await run_vtex_scraping(conn)
    farmatodo_total = await run_farmatodo_scraping(conn)
    return vtex_total + farmatodo_total


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


@app.delete("/configs/{config_id}")
def delete_config(config_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM search_configs WHERE id = %s RETURNING id;", (config_id,))
        deleted = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        if not deleted:
            raise HTTPException(status_code=404, detail="Configuración no encontrada.")
        return {"status": "success", "deleted_id": config_id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Error eliminando: {str(e)}")


@app.get("/results")
@app.get("/results/")
def get_results(
    retailer: Optional[str] = Query(None),
    search_term: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM scraper_results WHERE 1=1"
    params = []
    if retailer:
        query += " AND retailer ILIKE %s"
        params.append(f"%{retailer}%")
    if search_term:
        query += " AND search_term ILIKE %s"
        params.append(f"%{search_term}%")
    if date_from:
        query += " AND captured_at >= %s"
        params.append(date_from)
    if date_to:
        query += " AND captured_at <= %s"
        params.append(date_to)
    query += " ORDER BY captured_at DESC LIMIT %s;"
    params.append(limit)
    cursor.execute(query, tuple(params))
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results


@app.post("/trigger-now")
@app.post("/trigger-now/")
async def trigger_now():
    conn = get_db_connection()
    try:
        total_records = await run_all_scraping(conn)
        return {
            "status": "success",
            "message": f"Monitoreo ejecutado correctamente en Éxito, Carulla y Farmatodo. {total_records} productos guardados.",
            "total_records": total_records
        }
    except Exception as e:
        print(f"[TRIGGER ERROR] {e}", flush=True)
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


@app.get("/export")
@app.get("/export/")
def export_results(
    retailer: Optional[str] = Query(None),
    search_term: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Consulta del histórico completo (Hoja "Tendencia")
    query_tendencia = "SELECT * FROM scraper_results WHERE 1=1"
    params = []
    if retailer:
        query_tendencia += " AND retailer ILIKE %s"
        params.append(f"%{retailer}%")
    if search_term:
        query_tendencia += " AND search_term ILIKE %s"
        params.append(f"%{search_term}%")
    if date_from:
        query_tendencia += " AND captured_at >= %s"
        params.append(date_from)
    if date_to:
        query_tendencia += " AND captured_at <= %s"
        params.append(date_to)

    query_tendencia += " ORDER BY captured_at DESC;"
    cursor.execute(query_tendencia, tuple(params))
    rows_tendencia = cursor.fetchall()

    if not rows_tendencia:
        cursor.close()
        conn.close()
        raise HTTPException(
            status_code=404,
            detail="No se encontraron datos para exportar con los filtros seleccionados."
        )

    # 2. Consulta de última captura por producto/retailer/search_term (Hoja "Resumen")
    query_resumen = """
        SELECT DISTINCT ON (retailer, search_term, product_name) *
        FROM scraper_results
        WHERE 1=1
    """
    params_resumen = []
    if retailer:
        query_resumen += " AND retailer ILIKE %s"
        params_resumen.append(f"%{retailer}%")
    if search_term:
        query_resumen += " AND search_term ILIKE %s"
        params_resumen.append(f"%{search_term}%")
    if date_from:
        query_resumen += " AND captured_at >= %s"
        params_resumen.append(date_from)
    if date_to:
        query_resumen += " AND captured_at <= %s"
        params_resumen.append(date_to)

    query_resumen += " ORDER BY retailer, search_term, product_name, captured_at DESC;"
    cursor.execute(query_resumen, tuple(params_resumen))
    rows_resumen = cursor.fetchall()

    cursor.close()
    conn.close()

    # 3. Construcción del archivo Excel (.xlsx) usando Pandas y OpenPyXL
    df_tendencia = pd.DataFrame(rows_tendencia)
    df_resumen = pd.DataFrame(rows_resumen)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_resumen.to_excel(writer, sheet_name="Resumen", index=False)
        df_tendencia.to_excel(writer, sheet_name="Tendencia", index=False)

    output.seek(0)

    filename = f"digital_shelf_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )