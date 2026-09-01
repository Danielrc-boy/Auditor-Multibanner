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
                term = getattr(item, "search_keyword", None)
                pos = getattr(item, "search_position", None)
                title = getattr(item, "title", "") or ""
                brand = getattr(item, "brand", None) or "Sin Marca"
                base_price = getattr(item, "base_price", 0.0)
                disc_price = getattr(item, "discount_price", None)
                stock = getattr(item, "in_stock", True)
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


class SearchConfigCreate(BaseModel):
    search_term: Optional[str] = None
    keyword: Optional[str] = None


@app.get("/")
def read_root():
    return {"message": "API Monitoreo Activa"}


# --- ENDPOINT ADMIN: LIMPIEZA DE BASE DE DATOS ---
@app.delete("/admin/clean-db")
def clean_database(confirm: bool = Query(False)):
    """Elimina todos los registros de scraper_results para reiniciar la captura."""
    if not confirm:
        raise HTTPException(
            status_code=400, 
            detail="Se requiere el parámetro ?confirm=true para ejecutar la limpieza."
        )
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE scraper_results RESTART IDENTITY;")
            conn.commit()
            return {
                "status": "success",
                "message": "Base de datos truncada correctamente."
            }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al limpiar BD: {str(e)}")
    finally:
        conn.close()


# --- ENDPOINT PARA OBTENER OPCIONES DE FILTROS (MARCAS Y PRODUCTOS) ---
@app.get("/analytics/options")
def get_filter_options():
    """Retorna las listas distintas de marcas y productos para los selectores frontend."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT COALESCE(brand, 'Sin Marca') as brand FROM scraper_results WHERE brand IS NOT NULL ORDER BY brand ASC;")
            brands = [r["brand"] for r in cur.fetchall()]

            cur.execute("SELECT DISTINCT product_name FROM scraper_results WHERE product_name IS NOT NULL ORDER BY product_name ASC;")
            products = [r["product_name"] for r in cur.fetchall()]

            return {"brands": brands, "products": products}
    finally:
        conn.close()


# --- ENDPOINT ANALYTICS: TABLA DE POSICIONES DEDUPLICADA ---
@app.get("/analytics/positions")
def get_positions(
    retailer: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    product_name: Optional[str] = Query(None),
    search_term: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500)
):
    """Obtiene el ranking de posicionamiento deduplicado indicando número de permanencias."""
    conn = get_db_connection()
    try:
        where_clause = " WHERE 1=1"
        params = []
        if retailer and retailer != "ALL":
            where_clause += " AND retailer ILIKE %s"
            params.append(f"%{retailer}%")
        if brand and brand != "ALL":
            where_clause += " AND brand ILIKE %s"
            params.append(f"%{brand}%")
        if product_name and product_name != "ALL":
            where_clause += " AND product_name ILIKE %s"
            params.append(f"%{product_name}%")
        if search_term and search_term != "ALL":
            where_clause += " AND search_term ILIKE %s"
            params.append(f"%{search_term}%")
        if query:
            where_clause += " AND product_name ILIKE %s"
            params.append(f"%{query}%")

        sql = f"""
            SELECT 
                retailer,
                search_term,
                product_name,
                COALESCE(brand, 'Sin Marca') as brand,
                position,
                price,
                discount_price,
                is_available,
                COUNT(*) as run_count,
                MIN(captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota') as first_seen,
                MAX(captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota') as last_seen
            FROM scraper_results
            {where_clause}
            GROUP BY retailer, search_term, product_name, brand, position, price, discount_price, is_available
            ORDER BY last_seen DESC, position ASC
            LIMIT %s;
        """
        params.append(limit)
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()
    finally:
        conn.close()


# --- ENDPOINT ANALYTICS: COMPARADOR HEAD-TO-HEAD DE MARCAS ---
@app.get("/analytics/compare")
def compare_brands(
    brand_a: str = Query(..., description="Primera marca a comparar (ej. Nosotras)"),
    brand_b: str = Query(..., description="Segunda marca a comparar (ej. Kotex)"),
    retailer: Optional[str] = Query(None),
    search_term: Optional[str] = Query(None)
):
    """Compara métricas clave (Precios, Promociones, Visibilidad y Stock) entre dos marcas."""
    conn = get_db_connection()
    try:
        where_clause = " WHERE brand ILIKE %s"
        params_a = [f"%{brand_a}%"]
        params_b = [f"%{brand_b}%"]

        if retailer and retailer != "ALL":
            where_clause += " AND retailer ILIKE %s"
            params_a.append(f"%{retailer}%")
            params_b.append(f"%{retailer}%")
        if search_term and search_term != "ALL":
            where_clause += " AND search_term ILIKE %s"
            params_a.append(f"%{search_term}%")
            params_b.append(f"%{search_term}%")

        query_sql = f"""
            SELECT 
                COUNT(*) as total_skus,
                ROUND(AVG(position)::numeric, 1) as avg_position,
                COUNT(CASE WHEN position <= 10 THEN 1 END) as top10_count,
                ROUND(AVG(price)::numeric, 0) as avg_price,
                ROUND(AVG(CASE WHEN discount_price > 0 AND discount_price < price THEN discount_price ELSE price END)::numeric, 0) as avg_final_price,
                COUNT(CASE WHEN discount_price > 0 AND discount_price < price THEN 1 END) as promo_skus,
                COUNT(CASE WHEN is_available = FALSE THEN 1 END) as oos_skus
            FROM scraper_results
            {where_clause};
        """
        with conn.cursor() as cur:
            cur.execute(query_sql, tuple(params_a))
            res_a = cur.fetchone()
            cur.execute(query_sql, tuple(params_b))
            res_b = cur.fetchone()

        return {
            "brand_a": {"name": brand_a, "metrics": res_a},
            "brand_b": {"name": brand_b, "metrics": res_b}
        }
    finally:
        conn.close()


# --- ENDPOINT DE DATOS DEL DASHBOARD POTENCIADO Y FILTRABLE ---
@app.get("/dashboard-data")
@app.get("/dashboard-data/")
def get_dashboard_data(
    retailer: Optional[str] = Query(None),
    search_term: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    """Consolida métricas y cruces comerciales avanzados con soporte para filtros dinámicos."""
    conn = get_db_connection()
    try:
        base_where = " WHERE 1=1"
        params = []

        if retailer and retailer != "ALL":
            base_where += " AND retailer ILIKE %s"
            params.append(f"%{retailer}%")
        if search_term and search_term != "ALL":
            base_where += " AND search_term ILIKE %s"
            params.append(f"%{search_term}%")
        if date_from:
            base_where += " AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date >= %s::date"
            params.append(date_from)
        if date_to:
            base_where += " AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date <= %s::date"
            params.append(date_to)

        with conn.cursor() as cur:
            # 1. Filtros disponibles para desplegables en Frontend
            cur.execute("SELECT DISTINCT retailer FROM scraper_results WHERE retailer IS NOT NULL ORDER BY retailer;")
            available_retailers = [r["retailer"].capitalize() for r in cur.fetchall()]

            cur.execute("SELECT DISTINCT search_term FROM scraper_results WHERE search_term IS NOT NULL ORDER BY search_term;")
            available_terms = [r["search_term"] for r in cur.fetchall()]

            # 2. Resumen General y Métricas Clave
            cur.execute(f"""
                SELECT 
                    COUNT(*) as total_monitored,
                    COUNT(CASE WHEN is_available = FALSE THEN 1 END) as out_of_stock_count,
                    COUNT(DISTINCT retailer) as active_retailers,
                    COUNT(CASE WHEN discount_price > 0 AND discount_price < price THEN 1 END) as discounted_count,
                    ROUND(AVG(CASE WHEN discount_price > 0 AND discount_price < price THEN ((price - discount_price) / price) * 100 ELSE 0 END)::numeric, 1) as avg_discount_pct
                FROM scraper_results
                {base_where};
            """, tuple(params))
            summary_row = cur.fetchone()

            total = summary_row["total_monitored"] if summary_row and summary_row["total_monitored"] else 0
            stock_out = summary_row["out_of_stock_count"] if summary_row and summary_row["out_of_stock_count"] else 0
            availability = round(((total - stock_out) / total) * 100, 1) if total > 0 else 100.0

            # 3. Share of Shelf Global & Top 10 (Visibilidad)
            cur.execute(f"""
                SELECT 
                    retailer,
                    COUNT(CASE WHEN LOWER(brand) IN ('nosotras', 'pequeñin', 'pequeñín', 'tena', 'zewa') THEN 1 END) as essity_total,
                    COUNT(CASE WHEN LOWER(brand) NOT IN ('nosotras', 'pequeñin', 'pequeñín', 'tena', 'zewa') OR brand IS NULL THEN 1 END) as comp_total,
                    COUNT(CASE WHEN LOWER(brand) IN ('nosotras', 'pequeñin', 'pequeñín', 'tena', 'zewa') AND position <= 10 THEN 1 END) as essity_top10,
                    COUNT(CASE WHEN (LOWER(brand) NOT IN ('nosotras', 'pequeñin', 'pequeñín', 'tena', 'zewa') OR brand IS NULL) AND position <= 10 THEN 1 END) as comp_top10
                FROM scraper_results
                {base_where}
                GROUP BY retailer;
            """, tuple(params))
            sos_rows = cur.fetchall()

            # 4. Evolución de Precio Promedio por Marca (Essity vs Competencia)
            cur.execute(f"""
                SELECT 
                    TO_CHAR((captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota'), 'YYYY-MM-DD') as date_label,
                    ROUND(AVG(CASE WHEN LOWER(brand) IN ('nosotras', 'pequeñin', 'pequeñín', 'tena', 'zewa') THEN price END)::numeric, 0) as essity_price,
                    ROUND(AVG(CASE WHEN LOWER(brand) NOT IN ('nosotras', 'pequeñin', 'pequeñín', 'tena', 'zewa') OR brand IS NULL THEN price END)::numeric, 0) as comp_price
                FROM scraper_results
                {base_where} AND price > 0
                GROUP BY TO_CHAR((captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota'), 'YYYY-MM-DD')
                ORDER BY date_label ASC;
            """, tuple(params))
            price_rows = cur.fetchall()

            # 5. Top Marcas por Presencia (Desglose Comercial)
            cur.execute(f"""
                SELECT 
                    COALESCE(brand, 'Sin Marca') as brand_name,
                    COUNT(*) as total_skus,
                    COUNT(CASE WHEN is_available = FALSE THEN 1 END) as oos_skus,
                    ROUND(AVG(price)::numeric, 0) as avg_price
                FROM scraper_results
                {base_where}
                GROUP BY COALESCE(brand, 'Sin Marca')
                ORDER BY total_skus DESC
                LIMIT 7;
            """, tuple(params))
            brand_rows = cur.fetchall()

        return {
            "filters": {
                "retailers": available_retailers,
                "search_terms": available_terms
            },
            "summary": {
                "total_monitored": total,
                "availability_rate": availability,
                "out_of_stock_alerts": stock_out,
                "active_retailers": summary_row["active_retailers"] if summary_row else 0,
                "discounted_count": summary_row["discounted_count"] if summary_row else 0,
                "avg_discount_pct": float(summary_row["avg_discount_pct"]) if summary_row and summary_row["avg_discount_pct"] else 0.0
            },
            "share_of_shelf": {
                "retailers": [r["retailer"].capitalize() for r in sos_rows],
                "essity": [r["essity_total"] for r in sos_rows],
                "competencia": [r["comp_total"] for r in sos_rows],
                "essity_top10": [r["essity_top10"] for r in sos_rows],
                "competencia_top10": [r["comp_top10"] for r in sos_rows]
            },
            "price_evolution": {
                "labels": [p["date_label"] for p in price_rows],
                "essity_prices": [float(p["essity_price"]) if p["essity_price"] else 0 for p in price_rows],
                "comp_prices": [float(p["comp_price"]) if p["comp_price"] else 0 for p in price_rows]
            },
            "brand_breakdown": [
                {
                    "brand": b["brand_name"],
                    "skus": b["total_skus"],
                    "oos": b["oos_skus"],
                    "avg_price": float(b["avg_price"]) if b["avg_price"] else 0
                } for b in brand_rows
            ]
        }
    finally:
        conn.close()


@app.get("/dashboard")
def get_dashboard_page():
    """Servir la página del dashboard directamente"""
    if os.path.exists("app/dashboard.html"):
        return FileResponse("app/dashboard.html")
    if os.path.exists("dashboard.html"):
        return FileResponse("dashboard.html")
    raise HTTPException(status_code=404, detail="dashboard.html no encontrado.")


@app.post("/admin/add-is-active-column")
def add_is_active_column():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "ALTER TABLE search_configs ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;"
        )
        conn.commit()
        return {
            "status": "success",
            "message": "Columna is_active agregada correctamente.",
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


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
        raise HTTPException(
            status_code=400, detail="Debe proporcionar 'search_term' o 'keyword'."
        )
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO search_configs (search_term, is_active) VALUES (%s, TRUE) RETURNING *;",
            (term,),
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


@app.patch("/configs/{config_id}/toggle")
def toggle_config(config_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE search_configs SET is_active = NOT is_active WHERE id = %s RETURNING id, search_term, is_active;",
            (config_id,),
        )
        updated = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        if not updated:
            raise HTTPException(
                status_code=404, detail="Configuración no encontrada."
            )
        return {"status": "success", "config": updated}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        raise HTTPException(
            status_code=400, detail=f"Error actualizando estado: {str(e)}"
        )


@app.delete("/configs/{config_id}")
def delete_config(config_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM search_configs WHERE id = %s RETURNING id;", (config_id,)
        )
        deleted = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        if not deleted:
            raise HTTPException(
                status_code=404, detail="Configuración no encontrada."
            )
        return {"status": "success", "deleted_id": config_id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        raise HTTPException(
            status_code=400, detail=f"Error eliminando: {str(e)}"
        )


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
    query = """
        SELECT 
            id, retailer, search_term, product_name, 
            COALESCE(brand, 'Sin Marca') AS brand, 
            position, price, discount_price, is_available,
            (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota') AS captured_at
        FROM scraper_results 
        WHERE 1=1
    """
    params = []
    if retailer:
        query += " AND retailer ILIKE %s"
        params.append(f"%{retailer}%")
    if search_term:
        query += " AND search_term ILIKE %s"
        params.append(f"%{search_term}%")
    if date_from:
        query += " AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date >= %s::date"
        params.append(date_from)
    if date_to:
        query += " AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date <= %s::date"
        params.append(date_to)
    query += " ORDER BY id DESC LIMIT %s;"
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
            "message": f"Monitoreo ejecutado correctamente. {total_records} productos guardados.",
            "total_records": total_records,
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

    query_tendencia = """
        SELECT 
            id, retailer, search_term, product_name, 
            COALESCE(brand, 'Sin Marca') AS brand, 
            position, price, discount_price, is_available,
            (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota') AS captured_at
        FROM scraper_results WHERE 1=1
    """
    params = []
    if retailer:
        query_tendencia += " AND retailer ILIKE %s"
        params.append(f"%{retailer}%")
    if search_term:
        query_tendencia += " AND search_term ILIKE %s"
        params.append(f"%{search_term}%")
    if date_from:
        query_tendencia += " AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date >= %s::date"
        params.append(date_from)
    if date_to:
        query_tendencia += " AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date <= %s::date"
        params.append(date_to)
    query_tendencia += " ORDER BY id DESC;"
    cursor.execute(query_tendencia, tuple(params))
    rows_tendencia = cursor.fetchall()

    if not rows_tendencia:
        cursor.close()
        conn.close()
        raise HTTPException(
            status_code=404, detail="No se encontraron datos para exportar."
        )

    query_resumen = """
        SELECT DISTINCT ON (retailer, search_term, product_name)
            id, retailer, search_term, product_name, 
            COALESCE(brand, 'Sin Marca') AS brand, 
            position, price, discount_price, is_available,
            (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota') AS captured_at
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
        query_resumen += " AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date >= %s::date"
        params_resumen.append(date_from)
    if date_to:
        query_resumen += " AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date <= %s::date"
        params_resumen.append(date_to)
    query_resumen += " ORDER BY retailer, search_term, product_name, id DESC;"
    cursor.execute(query_resumen, tuple(params_resumen))
    rows_resumen = cursor.fetchall()

    cursor.close()
    conn.close()

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
        headers=headers,
    )


@app.get("/exec-sql")
def execute_sql_query(sql: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            if cur.description:
                results = cur.fetchall()
                conn.commit()
                return {"status": "ok", "data": results}
            else:
                conn.commit()
                return {"status": "ok", "message": f"Filas afectadas: {cur.rowcount}"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"Error SQL: {str(e)}")
    finally:
        conn.close()