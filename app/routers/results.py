"""
Rutas de consulta y exportación de los datos capturados por los scrapers.

- GET /results  -> consulta filtrable (retailer, término, fechas) en JSON
- GET /export   -> el mismo filtro, entregado como archivo Excel
                   (hoja "Resumen": última captura por producto;
                    hoja "Tendencia": histórico completo)

Este router se conecta a la app principal en main.py con:
    app.include_router(results.router)
"""
import io
from typing import Optional
from datetime import datetime
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from app.database import get_db_connection

router = APIRouter(tags=["results"])


@router.get("/results")
@router.get("/results/")
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
            COALESCE(seller_name, retailer) AS seller_name,
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


@router.get("/export")
@router.get("/export/")
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
            COALESCE(seller_name, retailer) AS seller_name,
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
        raise HTTPException(status_code=404, detail="No se encontraron datos para exportar.")

    query_resumen = """
        SELECT DISTINCT ON (retailer, search_term, product_name)
            id, retailer, search_term, product_name, 
            COALESCE(brand, 'Sin Marca') AS brand, 
            position, price, discount_price, is_available,
            COALESCE(seller_name, retailer) AS seller_name,
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
