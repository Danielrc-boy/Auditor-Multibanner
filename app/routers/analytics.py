"""
Rutas de analítica: opciones de filtro, ranking de posiciones,
comparador head-to-head de referencias, el resumen consolidado que
alimenta el dashboard visual (/dashboard-data), y el resumen ejecutivo
de KPIs (/executive-summary).

Este router se conecta a la app principal en main.py con:
    app.include_router(analytics.router)
"""
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Query
from app.database import get_db_connection
from app.services.client_brands import CLIENT_BRANDS

router = APIRouter(tags=["analytics"])

# Retailers cuyo is_available refleja una verificación real de stock que
# SÍ se guarda en la tabla (disponibles Y agotados por igual). Confirmado
# con datos reales de producción (2026-09-14):
#   - Farmatodo: 36 de 651 filas con is_available=False -- señal real y
#     completa, es el ÚNICO retailer así.
#   - Éxito/Carulla/La Rebaja/Locatel/Colsubsidio/Pasteur/Coopidrogas
#     (VTEX): SÍ verifican AvailableQuantity real, pero vtex_scraper.py
#     DESCARTA el producto agotado antes de guardarlo (nunca se inserta) --
#     el efecto neto en la tabla es el mismo que no verificar: 0 de miles
#     de filas con is_available=False en cada uno.
#   - Cafam: in_stock queda hardcodeado en True siempre (documentado en
#     cafam_scraper.py -- el JSON de búsqueda no expone stock).
#   - Rappi: solo marca OOS cuando el JSON-LD lo indica explícitamente,
#     algo que casi nunca ocurre en la práctica -- señal parcial.
# Por eso un 100% de disponibilidad en cualquiera de estos NO distingue
# "todo en stock" de "no medimos lo agotado".
RETAILERS_WITH_RELIABLE_AVAILABILITY = {"farmatodo"}

# CLIENT_BRANDS ahora vive en app/services/client_brands.py (única fuente
# de verdad, compartida con cafam_scraper.py y el motor de insights) --
# se re-exporta aquí para no romper otros módulos que ya hacen
# `from app.routers.analytics import CLIENT_BRANDS`.

# Retailers cuyo Índice de Precio NO es confiable todavía -- distinto del
# problema de "brand" ya corregido en Cafam/Colsubsidio (ver
# client_brands.py y vtex_scraper.py). Aquí el problema es que la
# búsqueda "Toallas Higienicas" del VTEX intelligent search de
# Colsubsidio trae mezclados productos de otra categoría (copas
# menstruales, kits de toallas reutilizables) junto con toallas
# desechables reales -- confirmado con evidencia real (2026-09-15):
# "Life Cup Copa Menstrual Talla 0" ($65.322) y "TOALLAS HIGIENICAS
# REUTILIZABLES LIFEPAD" ($86.550) inflaban el precio promedio de
# competencia de ~$9.212 (comparable real, solo Siempre Libre/Stayfree/
# Kotex) a $31.454, lo que distorsionaba el Índice de Precio de ~190%
# real (cliente más caro) a un engañoso 55.8% (sugería cliente más
# barato). El problema NO lo introdujo el fix de marca -- ya existía en
# los datos crudos del sitio; antes era invisible porque client_skus=0
# siempre volvía price_index=None sin llegar a calcularlo. Ver tarea
# pendiente en CLAUDE.md sobre el filtro de relevancia de categoría que
# hace falta (podría afectar a otros retailers VTEX también). Mientras
# tanto: mismo principio que Cafam con discount_price -- preferimos
# None ("Datos insuficientes") a un número que sabemos contaminado.
RETAILERS_WITH_UNRELIABLE_PRICE_INDEX = {"colsubsidio"}


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


def _fetch_summary_metrics(cur, where_sql: str, params: list) -> dict:
    """
    Calcula Share of Shelf, Índice de Precio y Disponibilidad del cliente
    sobre el ÚLTIMO snapshot de cada SKU dentro del filtro dado.

    "SKU" se define aquí como la tupla (retailer, search_term, product_name)
    -- el mismo criterio de deduplicación que ya usa /export para la hoja
    "Resumen" (DISTINCT ON ... ORDER BY id DESC). Esto evita que un mismo
    producto capturado varias veces por corridas programadas dentro del
    período se cuente más de una vez.

    El "precio efectivo" es discount_price si existe, si no price -- el
    precio que realmente paga el cliente final, igual que en /export y
    /analytics/compare-products (avg_final_price).
    """
    sql = f"""
        WITH latest_snapshot AS (
            SELECT DISTINCT ON (retailer, search_term, product_name)
                LOWER(COALESCE(brand, 'sin marca')) AS brand_lower,
                COALESCE(discount_price, price) AS effective_price,
                is_available
            FROM scraper_results
            {where_sql}
            ORDER BY retailer, search_term, product_name, id DESC
        )
        SELECT
            COUNT(*) AS total_skus,
            COUNT(*) FILTER (WHERE brand_lower = ANY(%s)) AS client_skus,
            COUNT(*) FILTER (WHERE brand_lower = ANY(%s) AND is_available) AS client_available_skus,
            AVG(effective_price) FILTER (
                WHERE brand_lower = ANY(%s) AND effective_price > 0
            ) AS client_avg_price,
            AVG(effective_price) FILTER (
                WHERE NOT (brand_lower = ANY(%s)) AND effective_price > 0
            ) AS competition_avg_price
        FROM latest_snapshot;
    """
    cur.execute(sql, tuple(params) + (CLIENT_BRANDS, CLIENT_BRANDS, CLIENT_BRANDS, CLIENT_BRANDS))
    row = cur.fetchone() or {}

    total = row.get("total_skus") or 0
    client_total = row.get("client_skus") or 0
    client_available = row.get("client_available_skus") or 0
    client_price = float(row["client_avg_price"]) if row.get("client_avg_price") is not None else None
    competition_price = float(row["competition_avg_price"]) if row.get("competition_avg_price") is not None else None

    # Share of Shelf: None (no 0) si no hay ningún SKU monitoreado en el
    # período -- evita reportar "0% de presencia" cuando en realidad es
    # "sin datos".
    share_of_shelf_pct = round((client_total / total) * 100, 1) if total > 0 else None

    # Disponibilidad: None si el cliente no tiene ningún SKU en el período
    # (no aplica dividir 0/0).
    availability_pct = round((client_available / client_total) * 100, 1) if client_total > 0 else None

    # Índice de precio: requiere precio promedio válido de AMBOS lados.
    # Si falta precio de competencia (o de cliente), None explícito en vez
    # de 0 o de una división por cero -- el frontend debe mostrar
    # "Datos insuficientes", nunca un 0% o un error.
    if client_price is not None and competition_price is not None and competition_price > 0:
        price_index = round((client_price / competition_price) * 100, 1)
    else:
        price_index = None

    return {
        "share_of_shelf_pct": share_of_shelf_pct,
        "price_index": price_index,
        "availability_pct": availability_pct,
        "raw": {
            "total_skus": total,
            "client_skus": client_total,
            "client_available_skus": client_available,
            "client_avg_price": client_price,
            "competition_avg_price": competition_price,
        },
    }


def _distinct_retailers(cur, where_sql: str, params: list) -> set:
    """Retailers (en minúsculas) presentes en scraper_results bajo el filtro dado."""
    cur.execute(f"SELECT DISTINCT LOWER(retailer) AS r FROM scraper_results {where_sql};", tuple(params))
    return {row["r"] for row in cur.fetchall()}


def _availability_data_quality(retailers_present: set) -> str:
    """
    "complete" solo si TODOS los retailers presentes en el filtro verifican
    y guardan disponibilidad real (ver RETAILERS_WITH_RELIABLE_AVAILABILITY
    arriba). "partial" si aparece cualquier otro retailer -- para que
    availability_pct nunca se presente como 100% confiable cuando en
    realidad varios retailers no verifican OOS o lo filtran antes de guardar.
    """
    if retailers_present and retailers_present.issubset(RETAILERS_WITH_RELIABLE_AVAILABILITY):
        return "complete"
    return "partial"


def _price_index_data_quality(retailers_present: set) -> str:
    """
    "partial" si CUALQUIERA de los retailers presentes en el filtro está
    en RETAILERS_WITH_UNRELIABLE_PRICE_INDEX (ver nota arriba) -- en ese
    caso el price_index de esa ventana se fuerza a None en vez de
    mostrar un número calculado sobre un promedio de competencia
    contaminado con productos de otra categoría.
    """
    if retailers_present & RETAILERS_WITH_UNRELIABLE_PRICE_INDEX:
        return "partial"
    return "complete"


def _trend_between(current: dict, previous: dict) -> dict:
    """
    Para cada una de las 3 métricas, compara el valor actual (últimos 7
    días) contra el anterior (los 7 días antes de esos). La diferencia
    (actual - anterior) se reporta en puntos porcentuales, con la
    dirección de la flecha que debe mostrar el frontend.
    """
    trend = {}
    for key in ("share_of_shelf_pct", "price_index", "availability_pct"):
        current_value = current.get(key)
        previous_value = previous.get(key)
        if current_value is None or previous_value is None:
            trend[key] = {"change_pp": None, "direction": "flat", "previous_value": previous_value}
            continue
        change_pp = round(current_value - previous_value, 1)
        direction = "up" if change_pp > 0 else ("down" if change_pp < 0 else "flat")
        trend[key] = {"change_pp": change_pp, "direction": direction, "previous_value": previous_value}
    return trend


@router.get("/executive-summary")
@router.get("/executive-summary/")
def get_executive_summary(
    retailer: Optional[str] = Query(None),
    search_term: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    """
    Resumen Ejecutivo (Fase A del dashboard): Share of Shelf, Índice de
    Precio y Disponibilidad del cliente, más su tendencia semana a semana.

    Decisión de arquitectura: se agrega como endpoint nuevo dentro de este
    mismo router (en vez de extender /dashboard-data o crear un router
    aparte) porque comparte conexión, convenciones de filtro (retailer/
    search_term/date_from/date_to) y audiencia (la parte superior del
    mismo dashboard) con /dashboard-data -- pero tiene una forma de
    respuesta distinta (KPIs con tendencia, no series para gráficas), así
    que mezclarlo en la misma función habría complicado ambas cosas.

    - retailer/search_term/date_from/date_to: filtran las 3 métricas del
      "período seleccionado" (si no se pasan, es histórico completo).
    - La tendencia (últimos 7 días vs. los 7 días anteriores) SIEMPRE usa
      esa ventana fija de 14 días, sin importar date_from/date_to -- solo
      hereda el filtro de retailer/search_term para mantener consistencia
      con lo que el usuario esté viendo.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            common_where = " WHERE 1=1"
            common_params = []
            if retailer and retailer != "ALL":
                common_where += " AND retailer ILIKE %s"
                common_params.append(f"%{retailer}%")
            if search_term and search_term != "ALL":
                common_where += " AND search_term ILIKE %s"
                common_params.append(f"%{search_term}%")

            period_where = common_where
            period_params = list(common_params)
            if date_from:
                period_where += " AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date >= %s::date"
                period_params.append(date_from)
            if date_to:
                period_where += " AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date <= %s::date"
                period_params.append(date_to)
            period_metrics = _fetch_summary_metrics(cur, period_where, period_params)
            period_retailers = _distinct_retailers(cur, period_where, period_params)
            availability_data_quality = _availability_data_quality(period_retailers)
            price_index_data_quality = _price_index_data_quality(period_retailers)
            if price_index_data_quality == "partial":
                period_metrics["price_index"] = None

            current_where = common_where + """
                AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date
                    >= ((NOW() AT TIME ZONE 'America/Bogota')::date - INTERVAL '6 days')
            """
            current_metrics = _fetch_summary_metrics(cur, current_where, list(common_params))
            current_retailers = _distinct_retailers(cur, current_where, list(common_params))
            if _price_index_data_quality(current_retailers) == "partial":
                current_metrics["price_index"] = None

            previous_where = common_where + """
                AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date
                    >= ((NOW() AT TIME ZONE 'America/Bogota')::date - INTERVAL '13 days')
                AND (captured_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date
                    < ((NOW() AT TIME ZONE 'America/Bogota')::date - INTERVAL '6 days')
            """
            previous_metrics = _fetch_summary_metrics(cur, previous_where, list(common_params))
            previous_retailers = _distinct_retailers(cur, previous_where, list(common_params))
            if _price_index_data_quality(previous_retailers) == "partial":
                previous_metrics["price_index"] = None

        # Si la cobertura de retailers cambió entre las dos ventanas de 7
        # días (ej. se agregaron retailers nuevos a mitad de semana), la
        # diferencia actual-vs-anterior mezcla movimiento real de mercado
        # con el cambio de cobertura del sistema -- no es representativa.
        # En ese caso se devuelve trend=None con la razón explícita, en vez
        # de una flecha engañosa.
        coverage_changed = current_retailers != previous_retailers
        if coverage_changed:
            trend_result = None
            trend_unavailable_reason = (
                "La cobertura de retailers cambió entre las dos ventanas de 7 días: "
                f"hace 8-14 días eran {sorted(previous_retailers) or ['ninguno']}, "
                f"en los últimos 7 días son {sorted(current_retailers) or ['ninguno']}. "
                "Comparar el % no reflejaría movimiento real de mercado."
            )
        else:
            trend_result = _trend_between(current_metrics, previous_metrics)
            trend_unavailable_reason = None

        return {
            "period": {
                "share_of_shelf_pct": period_metrics["share_of_shelf_pct"],
                "price_index": period_metrics["price_index"],
                "availability_pct": period_metrics["availability_pct"],
                "availability_data_quality": availability_data_quality,
                "price_index_data_quality": price_index_data_quality,
            },
            "trend": trend_result,
            "coverage_changed": coverage_changed,
            "trend_unavailable_reason": trend_unavailable_reason,
            "detail": {
                "period": period_metrics["raw"],
                "current_7d": current_metrics["raw"],
                "previous_7d": previous_metrics["raw"],
                "current_7d_retailers": sorted(current_retailers),
                "previous_7d_retailers": sorted(previous_retailers),
            },
        }
    finally:
        conn.close()
