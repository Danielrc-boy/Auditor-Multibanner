"""
Rutas de analítica: opciones de filtro, ranking de posiciones,
comparador head-to-head de referencias, y el resumen consolidado
que alimenta el dashboard visual (/dashboard-data).

Este router se conecta a la app principal en main.py con:
    app.include_router(analytics.router)
"""
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Query
from app.database import get_db_connection

router = APIRouter(tags=["analytics"])


@router.get("/analytics/options")
def get_filter_options():
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
@router.get("/analytics/positions")
def get_positions(
    retailer: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    product_name: Optional[str] = Query(None),
    search_term: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500)
):
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
                COALESCE(seller_name, retailer) as seller_name,
                COUNT(*) as run_count,
                MIN(captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota') as first_seen,
                MAX(captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota') as last_seen
            FROM scraper_results
            {where_clause}
            GROUP BY retailer, search_term, product_name, brand, position, price, discount_price, is_available, seller_name
            ORDER BY last_seen DESC, position ASC
            LIMIT %s;
        """
        params.append(limit)
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()
    finally:
        conn.close()
@router.get("/analytics/compare-products")
def compare_products(
    product_a: str = Query(..., description="Nombre exacto de la referencia A (Base)"),
    product_b: str = Query(..., description="Nombre exacto de la referencia B (Comparación)"),
    retailer: Optional[str] = Query(None)
):
    conn = get_db_connection()
    try:
        where_clause = " WHERE product_name ILIKE %s"
        params_a = [f"%{product_a}%"]
        params_b = [f"%{product_b}%"]
        if retailer and retailer != "ALL":
            where_clause += " AND retailer ILIKE %s"
            params_a.append(f"%{retailer}%")
            params_b.append(f"%{retailer}%")
        query_sql = f"""
            SELECT 
                product_name,
                COALESCE(brand, 'Sin Marca') as brand,
                COUNT(*) as total_skus,
                ROUND(AVG(position)::numeric, 1) as avg_position,
                ROUND(AVG(price)::numeric, 0) as avg_price,
                ROUND(AVG(CASE WHEN discount_price > 0 AND discount_price < price THEN discount_price ELSE price END)::numeric, 0) as avg_final_price,
                COUNT(CASE WHEN is_available = FALSE THEN 1 END) as oos_skus
            FROM scraper_results
            {where_clause}
            GROUP BY product_name, COALESCE(brand, 'Sin Marca');
        """
        with conn.cursor() as cur:
            cur.execute(query_sql, tuple(params_a))
            res_a = cur.fetchone() or {}
            cur.execute(query_sql, tuple(params_b))
            res_b = cur.fetchone() or {}
        price_a = float(res_a.get("avg_final_price") or 0)
        price_b = float(res_b.get("avg_final_price") or 0)
        price_diff = price_b - price_a
        price_pct = ((price_b - price_a) / price_a * 100) if price_a > 0 else 0
        pos_a = float(res_a.get("avg_position") or 0)
        pos_b = float(res_b.get("avg_position") or 0)
        pos_diff = pos_b - pos_a
        return {
            "product_a": res_a,
            "product_b": res_b,
            "differentials": {
                "price_diff": price_diff,
                "price_pct": round(price_pct, 1),
                "is_b_cheaper": price_diff < 0,
                "pos_diff": round(pos_diff, 1),
                "is_b_better_positioned": pos_diff < 0
            }
        }
    finally:
        conn.close()
@router.get("/dashboard-data")
@router.get("/dashboard-data/")
def get_dashboard_data(
    retailer: Optional[str] = Query(None),
    search_term: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
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
            cur.execute("SELECT DISTINCT retailer FROM scraper_results WHERE retailer IS NOT NULL ORDER BY retailer;")
            available_retailers = [r["retailer"].capitalize() for r in cur.fetchall()]
            cur.execute("SELECT DISTINCT search_term FROM scraper_results WHERE search_term IS NOT NULL ORDER BY search_term;")
            available_terms = [r["search_term"] for r in cur.fetchall()]
            cur.execute(f"""
                SELECT 
                    COUNT(*) as total_monitored,
                    COUNT(CASE WHEN is_available = FALSE THEN 1 END) as out_of_stock_count,
                    COUNT(DISTINCT retailer) as active_retailers,
                    COUNT(CASE WHEN discount_price > 0 AND discount_price < price THEN 1 END) as discounted_count,
                    ROUND(AVG(CASE WHEN discount_price > 0 AND discount_price < price THEN ((price - discount_price) / price) * 100 END)::numeric, 1) as avg_discount_pct
                FROM scraper_results
                {base_where};
            """, tuple(params))
            summary_row = cur.fetchone()
            total = summary_row["total_monitored"] if summary_row and summary_row["total_monitored"] else 0
            stock_out = summary_row["out_of_stock_count"] if summary_row and summary_row["out_of_stock_count"] else 0
            availability = round(((total - stock_out) / total) * 100, 1) if total > 0 else 100.0
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
