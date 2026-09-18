"""
Generador del PDF ejecutivo -- 8 secciones fijas (portada, resumen
ejecutivo, cita editorial, distribución por retailer, índice de precio
por retailer, posición dominante por retailer, conclusiones clave,
metodología), en ese orden.

Build en dos etapas, a propósito:
  - Etapa 1 (esta versión): solo texto y tablas con datos reales -- sin
    gráficas de barras/círculos ni paleta de marca -- para confirmar que
    las 8 secciones traen los números correctos antes de invertir tiempo
    en el diseño visual.
  - Etapa 2 (pendiente, requiere aprobación de la etapa 1 primero): las
    secciones 4/5/6 se reemplazan por HorizontalBarChart/formas Circle de
    reportlab.graphics con la paleta de marca; portada+resumen llevan el
    layout horizontal tipo presentación aprobado primero por separado.

Decisión de librería (2026-09-17, documentada también en CLAUDE.md):
reportlab, no fpdf2 ni WeasyPrint.
  - WeasyPrint (HTML/CSS -> PDF) da el mejor resultado visual y hubiera
    dejado reusar estilos del dashboard, pero depende de librerías de
    sistema (Pango, Cairo, GDK-Pixbuf, libffi) que no vienen con
    `pip install` -- en Railway eso significa depender de que el
    buildpack de Nixpacks las resuelva correctamente, un punto de fallo
    de despliegue extra que no existe hoy en ningún otro componente del
    backend. Se descarta por riesgo de despliegue, no por calidad.
  - fpdf2 es puro Python (sin ese riesgo) pero de más bajo nivel: no
    tiene un sistema de flujo de documento (páginas, saltos de página,
    tablas con salto automático) comparable a Platypus de reportlab --
    hubiera significado posicionar manualmente cada elemento en X/Y para
    un documento de 8 secciones.
  - reportlab es puro Python (`pip install reportlab`, sin dependencias
    de sistema -- mismo perfil de riesgo que el resto de requirements.txt),
    con Platypus (Paragraph/Table/Spacer/PageBreak con flujo y paginación
    automática) para el texto/tablas, y reportlab.graphics (HorizontalBarChart,
    formas Circle/Drawing) para las gráficas nativas de la etapa 2 sin
    necesitar matplotlib ni generar imágenes intermedias.

Módulo puro (no toca la base de datos ni FastAPI): recibe los mismos
dicts que ya devuelven /executive-summary, /insights y /methodology
como parámetros, para poder probarlo con datos capturados reales sin
levantar el servidor. El router (app/routers/reports.py) solo arma esos
tres dicts (+ la ruta del logo) y llama a generate_executive_pdf().
"""
import io
import os
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

RATING_LABELS = {
    "verde": "Bien",
    "amarillo": "Atención",
    "rojo": "Crítico",
    "no_concluyente": "Datos insuficientes",
}

DATOS_INSUFICIENTES = "Datos insuficientes"


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v:.1f}%" if v is not None else DATOS_INSUFICIENTES


def _fmt_index(v: Optional[float]) -> str:
    return f"{v:.1f}" if v is not None else DATOS_INSUFICIENTES


def _fmt_position(v: Optional[int]) -> str:
    return f"#{v}" if v is not None else "N/D"


def _pick_highlight_insight(insights: dict) -> Optional[dict]:
    """
    Elige el insight de mayor impacto para la 'cita editorial' (sección
    3): prioriza alertas (lo más urgente) sobre fortalezas, y dentro de
    cada lista ordena por la distancia absoluta entre valor_actual y
    valor_referencia cuando ambos son numéricos -- si no se puede
    comparar (ausencia_total no tiene valor_referencia), cae al primero
    de la lista.
    """
    def _gap(insight: dict) -> float:
        actual = insight.get("valor_actual")
        referencia = insight.get("valor_referencia")
        if actual is None or referencia is None:
            return 0.0
        # psycopg2 devuelve columnas numéricas como decimal.Decimal, que no
        # se puede restar directamente con un float (valor_referencia es un
        # literal float en insights_engine.py) -- confirmado en staging
        # (2026-09-17): TypeError real, no teórico.
        return abs(float(actual) - float(referencia))

    for bucket in (insights.get("alertas") or [], insights.get("fortalezas") or []):
        if bucket:
            return max(bucket, key=_gap)
    return None


def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="PortadaTitulo", parent=styles["Title"], fontSize=28, leading=34, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name="PortadaSubtitulo", parent=styles["Normal"], fontSize=14, leading=18, alignment=TA_CENTER,
        textColor=colors.HexColor("#555555"), spaceBefore=12,
    ))
    styles.add(ParagraphStyle(
        name="CifraGrande", parent=styles["Title"], fontSize=48, leading=56, alignment=TA_CENTER,
        textColor=colors.HexColor("#1a6b3c"),
    ))
    styles.add(ParagraphStyle(
        name="CifraGrandeLabel", parent=styles["Normal"], fontSize=12, alignment=TA_CENTER,
        textColor=colors.HexColor("#555555"),
    ))
    styles.add(ParagraphStyle(
        name="CitaEditorial", parent=styles["Normal"], fontSize=13, alignment=TA_CENTER,
        textColor=colors.HexColor("#1a1a1a"), leading=18, spaceBefore=6, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="SeccionTitulo", parent=styles["Heading2"], spaceBefore=18, spaceAfter=8,
    ))
    return styles


def _resumen_prosa(client_name: str, period: dict, distribution_by_retailer: list) -> str:
    sos = _fmt_pct(period["share_of_shelf_pct"])
    price_idx = period["price_index"]
    disponibilidad = _fmt_pct(period["availability_pct"])
    retailers_con_presencia = sum(1 for r in distribution_by_retailer if r["client_skus"] > 0)
    total_retailers = len(distribution_by_retailer)

    frases = [
        f"{client_name} tiene un Share of Shelf de {sos} en el período analizado, "
        f"con presencia confirmada en {retailers_con_presencia} de {total_retailers} retailers activos."
    ]
    if price_idx is not None:
        direccion = "más caro" if price_idx > 100 else ("más barato" if price_idx < 100 else "alineado")
        frases.append(
            f"El Índice de Precio consolidado es {price_idx:.1f} -- {direccion} que la competencia."
        )
        price_idx_median = period.get("price_index_median")
        if price_idx_median is not None:
            frases.append(
                f"Calculado con la mediana (menos sensible a paquetes grandes/atípicos que el "
                f"promedio) es {price_idx_median:.1f} -- dato adicional, no reemplaza al índice "
                f"oficial (ver metodología)."
            )
    else:
        frases.append(
            "El Índice de Precio consolidado no se pudo calcular de forma confiable en este período "
            "(ver metodología para el detalle de qué retailers quedan excluidos y por qué)."
        )
    frases.append(f"La disponibilidad reportada del cliente es de {disponibilidad}.")

    excluded_skus = period.get("client_price_excluded_skus") or 0
    excluded_price = period.get("client_price_excluded_avg_price")
    if excluded_skus and excluded_price is not None:
        frases.append(
            f"Precio promedio de TENA (línea de incontinencia, sin competencia comparable "
            f"en este período): ${excluded_price:,.0f} ({excluded_skus} SKUs) -- excluido del "
            f"Índice de Precio, ver metodología."
        )
    return " ".join(frases)


def _logo_flowable(logo_path: Optional[str], max_width_cm: float = 6.0) -> Optional[Image]:
    """
    Sección 1 (portada): usa app/assets/logo_vantic.png tal cual si el
    archivo existe -- este módulo no lo genera ni lo modifica. Si no
    existe (ej. todavía no se agregó al repo), la portada se ve sin logo
    en vez de reventar -- el pipeline de datos reales no debe depender
    de un asset gráfico pendiente. Ver nota en CLAUDE.md.
    """
    if not logo_path or not os.path.exists(logo_path):
        return None
    try:
        reader = ImageReader(logo_path)
        width_px, height_px = reader.getSize()
    except Exception:
        return None
    width = max_width_cm * cm
    height = width * (height_px / width_px)
    return Image(logo_path, width=width, height=height, hAlign="CENTER")


def _tabla_distribucion(by_retailer_dn_dp: list) -> Table:
    """Sección 4: Share of Shelf cliente vs. competencia, y los dos
    componentes de los que salen % DN / % DP (presencia binaria y tamaño
    de catálogo) -- por retailer ACTIVO, incluyendo los que hoy tienen
    client_skus=0 (Cafam/Colsubsidio, ver CLAUDE.md: depresión temporal
    de dn_pct/dp_pct, no es un bug de este reporte)."""
    table_data = [[
        "Retailer", "Share Cliente", "Share Competencia", "Presente (DN)", "SKUs totales (peso DP)",
    ]]
    for row in sorted(by_retailer_dn_dp, key=lambda r: r["retailer_code"]):
        total = row["total_skus"]
        client = row["client_skus"]
        share = round(client / total * 100, 1) if total else None
        comp_share = round(100 - share, 1) if share is not None else None
        table_data.append([
            row["retailer_code"].capitalize(),
            _fmt_pct(share),
            _fmt_pct(comp_share),
            "Sí" if client > 0 else "No",
            str(total),
        ])
    table = Table(table_data, repeatRows=1)
    table.setStyle(_default_table_style())
    return table


def _tabla_indice_precio(por_retailer: list) -> Table:
    """Sección 5: Índice de Precio por retailer -- marca explícitamente
    'Datos insuficientes' en vez de inventar un valor donde price_index
    es None (Rappi por falta de datos comparables, o cualquier retailer
    forzado a None por price_index_data_quality='partial', ver
    /methodology). price_index ya excluye CLIENT_BRANDS_PRICE_EXCLUDED
    (TENA, ver client_brands.py) -- la penúltima columna es informativa:
    el precio promedio de esas marcas excluidas, sin índice porque no
    tienen competencia comparable capturada.

    Columna "Mediana" (agregada 2026-09-18, ver price_index_median en
    insights_engine.py): mismo índice pero calculado con la mediana en
    vez del promedio -- dato ADICIONAL junto al índice oficial (columna
    "Índice de Precio"), no lo reemplaza. Investigado con datos reales
    de producción: coinciden casi exactamente cuando la dispersión de
    precios de competencia es pareja, pero difieren bastante cuando hay
    alta dispersión por tamaños de empaque (ver CLAUDE.md para el
    detalle completo de la investigación, incluyendo por qué se
    descartó la moda)."""
    table_data = [["Retailer", "Índice de Precio", "Mediana", "Calificación", "TENA (informativo)"]]
    for cell in sorted(por_retailer, key=lambda c: c["retailer"]):
        excluded_skus = cell.get("client_price_excluded_skus") or 0
        excluded_price = cell.get("client_price_excluded_avg_price")
        tena_cell = f"${excluded_price:,.0f} ({excluded_skus} SKUs)" if excluded_skus else "Sin SKUs"
        table_data.append([
            cell["retailer"].capitalize(),
            _fmt_index(cell["price_index"]),
            _fmt_index(cell.get("price_index_median")),
            RATING_LABELS.get(cell["price_index_rating"], cell["price_index_rating"]),
            tena_cell,
        ])
    table = Table(table_data, repeatRows=1)
    table.setStyle(_default_table_style())
    return table


def _tabla_posicion_dominante(por_retailer: list) -> Table:
    """Sección 6: % de SKUs del cliente en posición top-3 por retailer
    (client_top3_pct, agregado en insights_engine.py 2026-09-17) -- en
    la etapa 2 esto se dibuja como círculos proporcionales; en esta
    versión de texto es la misma cifra en tabla, junto a la mejor
    posición individual para dar contexto."""
    table_data = [["Retailer", "% SKUs en Top-3", "Mejor posición", "Calificación"]]
    for cell in sorted(por_retailer, key=lambda c: c["retailer"]):
        table_data.append([
            cell["retailer"].capitalize(),
            _fmt_pct(cell.get("client_top3_pct")),
            _fmt_position(cell["client_best_position"]),
            RATING_LABELS.get(cell["position_rating"], cell["position_rating"]),
        ])
    table = Table(table_data, repeatRows=1)
    table.setStyle(_default_table_style())
    return table


def _default_table_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a6b3c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])


def generate_executive_pdf(
    client_name: str,
    period_label: str,
    exec_summary: dict,
    insights: dict,
    methodology: dict,
    logo_path: Optional[str] = None,
) -> bytes:
    styles = _build_styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )
    story = []

    period = exec_summary["period"]
    by_retailer_dn_dp = exec_summary["detail"]["distribution"]["by_retailer"]
    por_retailer = insights.get("por_retailer", [])

    # --- 1. Portada ---
    logo = _logo_flowable(logo_path)
    story.append(Spacer(1, 3 * cm if logo else 4 * cm))
    if logo:
        story.append(logo)
        story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph(client_name, styles["PortadaTitulo"]))
    story.append(Paragraph("Reporte Ejecutivo de Digital Shelf", styles["PortadaSubtitulo"]))
    story.append(Paragraph(period_label, styles["PortadaSubtitulo"]))
    story.append(Paragraph(
        f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["PortadaSubtitulo"]
    ))
    story.append(PageBreak())

    # --- 2. Resumen ejecutivo + cifra grande ---
    story.append(Paragraph("Resumen Ejecutivo", styles["SeccionTitulo"]))
    story.append(Paragraph(
        _resumen_prosa(client_name, period, by_retailer_dn_dp), styles["Normal"]
    ))
    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph(_fmt_pct(period["share_of_shelf_pct"]), styles["CifraGrande"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Share of Shelf consolidado", styles["CifraGrandeLabel"]))
    story.append(Spacer(1, 0.6 * cm))

    # --- 3. Cita editorial ---
    highlight = _pick_highlight_insight(insights)
    if highlight:
        story.append(Paragraph(
            f'"{highlight["mensaje_especifico"]}"', styles["CitaEditorial"]
        ))
    story.append(PageBreak())

    # --- 4. Distribución por retailer (Share of Shelf, DN, DP) ---
    story.append(Paragraph("Distribución por Retailer", styles["SeccionTitulo"]))
    story.append(_tabla_distribucion(by_retailer_dn_dp))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        f"% Distribución Numérica (DN): {_fmt_pct(period['dn_pct'])} &nbsp;|&nbsp; "
        f"% Distribución Ponderada (DP): {_fmt_pct(period['dp_pct'])}",
        styles["Normal"],
    ))
    story.append(PageBreak())

    # --- 5. Índice de Precio por retailer ---
    story.append(Paragraph("Índice de Precio por Retailer", styles["SeccionTitulo"]))
    story.append(_tabla_indice_precio(por_retailer))
    story.append(PageBreak())

    # --- 6. Posición dominante por retailer (% top-3) ---
    story.append(Paragraph("Posición Dominante por Retailer", styles["SeccionTitulo"]))
    story.append(_tabla_posicion_dominante(por_retailer))
    story.append(PageBreak())

    # --- 7. Conclusiones clave ---
    story.append(Paragraph("Conclusiones Clave", styles["SeccionTitulo"]))
    for titulo, lista in (
        ("Alertas", insights.get("alertas", [])),
        ("Oportunidades", insights.get("oportunidades", [])),
        ("Fortalezas", insights.get("fortalezas", [])),
    ):
        story.append(Paragraph(titulo, styles["Heading3"]))
        if not lista:
            story.append(Paragraph("Sin elementos en esta categoría en el período.", styles["Normal"]))
        for item in lista[:3]:
            story.append(Paragraph(f"&bull; {item['mensaje_especifico']}", styles["Normal"]))
        story.append(Spacer(1, 0.3 * cm))
    story.append(PageBreak())

    # --- 8. Metodología ---
    story.append(Paragraph("Metodología", styles["SeccionTitulo"]))
    story.append(Paragraph(methodology.get("audit_type", ""), styles["Heading3"]))
    story.append(Paragraph(methodology.get("disclaimer", ""), styles["Normal"]))
    story.append(Spacer(1, 0.3 * cm))
    for metric_key, metric_text in methodology.get("metrics", {}).items():
        story.append(Paragraph(metric_key, styles["Heading3"]))
        story.append(Paragraph(metric_text, styles["Normal"]))
        story.append(Spacer(1, 0.2 * cm))
    caveats = methodology.get("known_data_quality_caveats", [])
    if caveats:
        story.append(Paragraph("Limitaciones de datos conocidas", styles["Heading3"]))
        for caveat in caveats:
            story.append(Paragraph(f"&bull; {caveat}", styles["Normal"]))

    doc.build(story)
    return buffer.getvalue()
