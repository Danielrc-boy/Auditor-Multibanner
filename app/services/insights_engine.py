"""
Motor de Insights: convierte el último snapshot de cada SKU en Alertas,
Oportunidades y Fortalezas accionables, calificando 4 KPIs (Share of Shelf,
Índice de Precio, Disponibilidad, Posición Dominante) por celda
(retailer, término de búsqueda) contra los umbrales estándar de digital
shelf analytics (estilo NielsenIQ).

Módulo puro: no toca la base de datos ni FastAPI, no importa nada de
app/routers/ -- así se puede probar sin esas dependencias instaladas.
build_insights() recibe filas ya consultadas (ver su docstring para el
shape esperado) y devuelve listas de dicts serializables directamente
como JSON.

client_brands y reliable_availability_retailers se reciben como
parámetro en vez de duplicarse aquí -- la fuente de verdad sigue siendo
CLIENT_BRANDS y RETAILERS_WITH_RELIABLE_AVAILABILITY en
app/routers/analytics.py. Duplicarlas aquí arriesgaría que las dos listas
se desincronicen con el tiempo (ver la lección ya documentada en
CLAUDE.md sobre get_db_connection() duplicado).

Limitación conocida (investigada y confirmada 2026-09-15) independiente
de lo anterior: en Cafam y Colsubsidio el campo "brand" NO contiene la
marca comercial real (Nosotras/Tena/etc.) sino la razón social del
fabricante/distribuidor (ej. "PRODUCTOS FAMILIA S.A."). Confirmado con
datos reales de producción y con la respuesta cruda en vivo de ambos
endpoints de búsqueda:
  - Cafam: el JSON de búsqueda no expone NINGÚN campo de marca comercial
    -- solo "manufacturer_name" (razón social) y "name" (título del
    producto, donde la marca aparece como texto libre). cafam_scraper.py
    mapea manufacturer_name -> brand asumiendo que era la marca; no hay
    un campo mejor disponible en este endpoint.
  - Colsubsidio: mismo vtex_scraper.py genérico que sí funciona bien en
    Éxito/Carulla/La Rebaja/Locatel/Pasteur/Coopidrogas -- el problema es
    que el CATÁLOGO propio de Colsubsidio llena su campo VTEX "brand" con
    la razón social, pero sí expone la marca comercial real en un campo
    de especificación separado: product["Marca Comercial"] (ej.
    ["Nosotras"]), que el scraper no está usando todavía.
Mientras no se corrija en el scraper (decisión pendiente, fuera del
alcance de este módulo), RETAILERS_WITH_UNRELIABLE_BRAND_FIELD excluye a
estos dos retailers de CUALQUIER insight que dependa de clasificar
cliente-vs-competencia: nunca se les genera una alerta de "ausencia
total" ni un Share of Shelf / Índice de Precio / Posición Dominante,
porque hoy no hay forma confiable de saber cuáles de sus filas son del
cliente. Quedan en la lista aparte "excluded_cells" del resultado, no en
silencio.
"""
from statistics import mean
from typing import Optional

RETAILERS_WITH_UNRELIABLE_BRAND_FIELD = {"cafam", "colsubsidio"}

GREEN = "verde"
YELLOW = "amarillo"
RED = "rojo"
INCONCLUSIVE = "no_concluyente"


def _effective_price(row: dict) -> Optional[float]:
    """Precio que realmente paga el cliente final: discount_price si es
    válido (positivo y menor al precio de lista), si no price."""
    price = row.get("price") or 0
    discount = row.get("discount_price")
    if discount and 0 < discount < price:
        return discount
    return price if price > 0 else None


def _is_client(row: dict, client_brands: set) -> bool:
    return (row.get("brand") or "").strip().lower() in client_brands


def rate_share_of_shelf(pct: Optional[float]) -> str:
    if pct is None:
        return INCONCLUSIVE
    if pct > 40:
        return GREEN
    if pct >= 20:
        return YELLOW
    return RED


def rate_price_index(idx: Optional[float]) -> str:
    if idx is None:
        return INCONCLUSIVE
    if 95 <= idx <= 105:
        return GREEN
    if 80 <= idx < 95 or 105 < idx <= 120:
        return YELLOW
    return RED


def rate_availability(pct: Optional[float], data_quality: str) -> str:
    """Respeta availability_data_quality: "partial" nunca puede calificar
    verde ni rojo -- siempre no_concluyente, aunque el número por sí solo
    luciera bien o mal."""
    if data_quality == "partial" or pct is None:
        return INCONCLUSIVE
    if pct >= 95:
        return GREEN
    if pct >= 85:
        return YELLOW
    return RED


def rate_position_dominance(best_position: Optional[int]) -> str:
    """
    Extensión del framework dado por el cliente: el enunciado original solo
    define "top 3" como umbral de dominancia. Aquí se agrega amarillo
    (4-10, visible pero no dominante) y rojo (>10) para poder generar
    oportunidades/fortalezas graduales en vez de un solo si/no.
    """
    if best_position is None:
        return INCONCLUSIVE
    if best_position <= 3:
        return GREEN
    if best_position <= 10:
        return YELLOW
    return RED


def _build_cell(retailer: str, search_term: str, rows: list, client_brands: set, reliable_availability_retailers: set) -> dict:
    total = len(rows)
    client_rows = [r for r in rows if _is_client(r, client_brands)]
    comp_rows = [r for r in rows if not _is_client(r, client_brands)]
    client_skus = len(client_rows)

    share_pct = round(client_skus / total * 100, 1) if total else None

    client_available = sum(1 for r in client_rows if r.get("is_available"))
    availability_pct = round(client_available / client_skus * 100, 1) if client_skus else None
    data_quality = "complete" if retailer.lower() in reliable_availability_retailers else "partial"

    client_prices = [p for p in (_effective_price(r) for r in client_rows) if p]
    comp_prices = [p for p in (_effective_price(r) for r in comp_rows) if p]
    client_avg_price = round(mean(client_prices), 0) if client_prices else None
    comp_avg_price = round(mean(comp_prices), 0) if comp_prices else None
    price_index = (
        round(client_avg_price / comp_avg_price * 100, 1)
        if client_avg_price and comp_avg_price
        else None
    )

    client_positions = [r["position"] for r in client_rows if r.get("position") is not None]
    comp_positions = [r["position"] for r in comp_rows if r.get("position") is not None]
    client_best_position = min(client_positions) if client_positions else None
    comp_best_position = min(comp_positions) if comp_positions else None

    # % de posiciones top-3 (agregado 2026-09-17 para la sección de
    # "círculos proporcionales" del reporte PDF ejecutivo): distinto de
    # client_best_position (la MEJOR posición individual) -- esto es qué
    # fracción de TODOS los SKUs del cliente en la celda están en el top
    # 3, para poder mostrar "dominancia" como una proporción y no un
    # solo sí/no. None (no 0) si el cliente no tiene ningún SKU en la
    # celda, mismo criterio que el resto de métricas de este módulo.
    client_top3_pct = (
        round(sum(1 for p in client_positions if p <= 3) / len(client_positions) * 100, 1)
        if client_positions else None
    )

    return {
        "retailer": retailer,
        "search_term": search_term,
        "total_skus": total,
        "client_skus": client_skus,
        "share_of_shelf_pct": share_pct,
        "share_of_shelf_rating": rate_share_of_shelf(share_pct),
        "availability_pct": availability_pct,
        "availability_data_quality": data_quality,
        "availability_rating": rate_availability(availability_pct, data_quality),
        "client_avg_price": client_avg_price,
        "competition_avg_price": comp_avg_price,
        "price_index": price_index,
        "price_index_rating": rate_price_index(price_index),
        "client_best_position": client_best_position,
        "competition_best_position": comp_best_position,
        "position_rating": rate_position_dominance(client_best_position),
        "client_top3_pct": client_top3_pct,
    }


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v:.1f}%" if v is not None else "N/D"


def build_retailer_summary(rows: list, client_brands: set, reliable_availability_retailers: set) -> list:
    """
    Igual que build_insights() pero agregado por retailer solamente (todos
    los search_term juntos), reusando _build_cell() sin duplicar su lógica
    -- necesario para el reporte PDF ejecutivo (gráficas "por retailer" de
    Share of Shelf, Índice de Precio y Posición Dominante), que necesita el
    dato completo de CADA retailer activo, no solo los que dispararon una
    alerta/oportunidad/fortaleza en build_insights().

    Excluye los mismos retailers que build_insights() por la misma razón
    (RETAILERS_WITH_UNRELIABLE_BRAND_FIELD) para no mostrar un Share of
    Shelf o Posición Dominante calculado sobre una clasificación de marca
    que sabemos que no es confiable.

    Devuelve una lista de dicts (ver _build_cell) ordenada por retailer,
    uno por retailer (search_term fijo como "TODOS" porque agrupa todos
    los términos).
    """
    client_brands = {b.strip().lower() for b in client_brands}
    reliable_availability_retailers = {r.strip().lower() for r in reliable_availability_retailers}

    rows_by_retailer: dict = {}
    for row in rows:
        if row["retailer"].lower() in RETAILERS_WITH_UNRELIABLE_BRAND_FIELD:
            continue
        rows_by_retailer.setdefault(row["retailer"], []).append(row)

    return [
        _build_cell(retailer, "TODOS", retailer_rows, client_brands, reliable_availability_retailers)
        for retailer, retailer_rows in sorted(rows_by_retailer.items())
    ]


def build_insights(rows: list, client_brands: set, reliable_availability_retailers: set) -> dict:
    """
    rows: lista de dicts, cada uno el último snapshot de un SKU (mismo
    criterio de deduplicación que _fetch_summary_metrics en analytics.py:
    DISTINCT ON (retailer, search_term, product_name) ORDER BY id DESC),
    con las claves: retailer, search_term, product_name, brand, price,
    discount_price, is_available, position.

    client_brands: iterable de marcas que cuentan como "cliente" -- pasar
    CLIENT_BRANDS de app/routers/analytics.py. No sensible a mayúsculas.

    reliable_availability_retailers: iterable de retailers cuyo
    is_available refleja una verificación real de stock -- pasar
    RETAILERS_WITH_RELIABLE_AVAILABILITY de app/routers/analytics.py. No
    sensible a mayúsculas.

    Devuelve {"alertas": [...], "oportunidades": [...], "fortalezas": [...],
    "excluded_cells": [...]}. Cada insight es un dict con: tipo, retailer,
    termino_o_producto, metrica, valor_actual, valor_referencia,
    mensaje_especifico -- siempre con el número real que lo sustenta.
    """
    client_brands = {b.strip().lower() for b in client_brands}
    reliable_availability_retailers = {r.strip().lower() for r in reliable_availability_retailers}

    cells_by_key: dict = {}
    for row in rows:
        key = (row["retailer"], row["search_term"])
        cells_by_key.setdefault(key, []).append(row)

    alertas, oportunidades, fortalezas, excluded = [], [], [], []

    # Por término: qué retailers (con brand confiable) tienen presencia
    # real del cliente -- necesario para no inventar "ausencia total" en
    # términos donde el cliente nunca vende en ningún lado.
    client_presence_by_term: dict = {}
    for (retailer, term), cell_rows in cells_by_key.items():
        if retailer.lower() in RETAILERS_WITH_UNRELIABLE_BRAND_FIELD:
            continue
        client_presence_by_term.setdefault(term, set())
        if any(_is_client(r, client_brands) for r in cell_rows):
            client_presence_by_term[term].add(retailer)

    for (retailer, term), cell_rows in sorted(cells_by_key.items()):
        if retailer.lower() in RETAILERS_WITH_UNRELIABLE_BRAND_FIELD:
            excluded.append({
                "retailer": retailer,
                "termino_o_producto": term,
                "motivo": (
                    "El campo brand de este retailer no distingue marca comercial de razón "
                    "social -- ver limitación documentada en insights_engine.py."
                ),
            })
            continue

        cell = _build_cell(retailer, term, cell_rows, client_brands, reliable_availability_retailers)

        # --- ALERTAS ---
        presence = client_presence_by_term.get(term, set())
        if cell["client_skus"] == 0 and presence and retailer not in presence:
            otros = ", ".join(sorted(presence))
            alertas.append({
                "tipo": "ausencia_total",
                "retailer": retailer,
                "termino_o_producto": term,
                "metrica": "share_of_shelf_pct",
                "valor_actual": 0.0,
                "valor_referencia": None,
                "mensaje_especifico": (
                    f"El cliente no aparece en absoluto en '{term}' en {retailer} "
                    f"({cell['total_skus']} productos de competencia presentes), pese a tener "
                    f"presencia confirmada en el mismo término en: {otros}."
                ),
            })

        if cell["availability_rating"] == RED:
            alertas.append({
                "tipo": "disponibilidad_critica",
                "retailer": retailer,
                "termino_o_producto": term,
                "metrica": "availability_pct",
                "valor_actual": cell["availability_pct"],
                "valor_referencia": 95.0,
                "mensaje_especifico": (
                    f"Disponibilidad del cliente en {retailer} para '{term}' es de "
                    f"{_fmt_pct(cell['availability_pct'])} ({cell['client_skus']} SKUs monitoreados), "
                    f"muy por debajo del umbral verde de 95%."
                ),
            })

        if cell["price_index_rating"] == RED and cell["price_index"] is not None:
            direccion = "más caro" if cell["price_index"] > 100 else "más barato"
            alertas.append({
                "tipo": "precio_fuera_de_mercado",
                "retailer": retailer,
                "termino_o_producto": term,
                "metrica": "price_index",
                "valor_actual": cell["price_index"],
                "valor_referencia": 100.0,
                "mensaje_especifico": (
                    f"Índice de precio del cliente en {retailer} para '{term}' es {cell['price_index']} "
                    f"(precio promedio cliente ${cell['client_avg_price']:,.0f} vs. competencia "
                    f"${cell['competition_avg_price']:,.0f}) -- {direccion} que el mercado, fuera del "
                    f"rango aceptable (80-120)."
                ),
            })

        # --- OPORTUNIDADES ---
        if cell["client_skus"] > 0 and cell["share_of_shelf_rating"] in (YELLOW, RED):
            gap = round(40 - cell["share_of_shelf_pct"], 1)
            oportunidades.append({
                "tipo": "brecha_share_of_shelf",
                "retailer": retailer,
                "termino_o_producto": term,
                "metrica": "share_of_shelf_pct",
                "valor_actual": cell["share_of_shelf_pct"],
                "valor_referencia": 40.0,
                "mensaje_especifico": (
                    f"Share of Shelf del cliente en {retailer} para '{term}' es "
                    f"{_fmt_pct(cell['share_of_shelf_pct'])} ({cell['client_skus']} de {cell['total_skus']} "
                    f"SKUs), {gap} puntos por debajo del umbral verde (40%)."
                ),
            })

        if cell["price_index_rating"] == YELLOW and cell["price_index"] is not None and cell["price_index"] > 100:
            oportunidades.append({
                "tipo": "precio_por_encima_del_mercado",
                "retailer": retailer,
                "termino_o_producto": term,
                "metrica": "price_index",
                "valor_actual": cell["price_index"],
                "valor_referencia": 105.0,
                "mensaje_especifico": (
                    f"El cliente está {round(cell['price_index'] - 100, 1)}% más caro que la competencia "
                    f"en {retailer} para '{term}' (índice {cell['price_index']}), dentro de zona amarilla -- "
                    f"margen para ajustar precio antes de perder más posición."
                ),
            })

        if (
            cell["client_skus"] > 0
            and cell["position_rating"] in (YELLOW, RED)
            and cell["competition_best_position"]
            and cell["competition_best_position"] <= 3
        ):
            oportunidades.append({
                "tipo": "posicion_no_dominante",
                "retailer": retailer,
                "termino_o_producto": term,
                "metrica": "client_best_position",
                "valor_actual": cell["client_best_position"],
                "valor_referencia": 3,
                "mensaje_especifico": (
                    f"En {retailer} para '{term}', la mejor posición del cliente es "
                    f"#{cell['client_best_position']} mientras que la competencia sí está en el top 3 "
                    f"(#{cell['competition_best_position']})."
                ),
            })

        # --- FORTALEZAS ---
        if cell["share_of_shelf_rating"] == GREEN:
            fortalezas.append({
                "tipo": "dominio_share_of_shelf",
                "retailer": retailer,
                "termino_o_producto": term,
                "metrica": "share_of_shelf_pct",
                "valor_actual": cell["share_of_shelf_pct"],
                "valor_referencia": 40.0,
                "mensaje_especifico": (
                    f"El cliente domina el anaquel en {retailer} para '{term}' con "
                    f"{_fmt_pct(cell['share_of_shelf_pct'])} de share ({cell['client_skus']} de "
                    f"{cell['total_skus']} SKUs)."
                ),
            })

        if cell["price_index_rating"] == GREEN:
            fortalezas.append({
                "tipo": "precio_alineado_al_mercado",
                "retailer": retailer,
                "termino_o_producto": term,
                "metrica": "price_index",
                "valor_actual": cell["price_index"],
                "valor_referencia": 100.0,
                "mensaje_especifico": (
                    f"El precio del cliente en {retailer} para '{term}' está alineado con el mercado "
                    f"(índice {cell['price_index']}, banda verde 95-105)."
                ),
            })

        if cell["position_rating"] == GREEN:
            fortalezas.append({
                "tipo": "posicion_dominante",
                "retailer": retailer,
                "termino_o_producto": term,
                "metrica": "client_best_position",
                "valor_actual": cell["client_best_position"],
                "valor_referencia": 3,
                "mensaje_especifico": (
                    f"El cliente domina la posición en {retailer} para '{term}': su mejor SKU está en "
                    f"#{cell['client_best_position']} (top 3)."
                ),
            })

        if cell["availability_rating"] == GREEN:
            fortalezas.append({
                "tipo": "disponibilidad_solida",
                "retailer": retailer,
                "termino_o_producto": term,
                "metrica": "availability_pct",
                "valor_actual": cell["availability_pct"],
                "valor_referencia": 95.0,
                "mensaje_especifico": (
                    f"Disponibilidad del cliente en {retailer} para '{term}' es "
                    f"{_fmt_pct(cell['availability_pct'])} ({cell['client_skus']} SKUs monitoreados), por "
                    f"encima del umbral verde (95%)."
                ),
            })

    return {
        "alertas": alertas,
        "oportunidades": oportunidades,
        "fortalezas": fortalezas,
        "excluded_cells": excluded,
    }
