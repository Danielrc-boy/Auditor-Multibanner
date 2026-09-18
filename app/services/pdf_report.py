"""
Generador del PDF ejecutivo -- 8 secciones fijas (portada, resumen
ejecutivo, cita editorial, distribución por retailer, índice de precio
por retailer, posición dominante por retailer, conclusiones clave,
metodología), en ese orden.

Build en dos etapas, a propósito:
  - Etapa 1 (superada): solo texto y tablas con datos reales -- sin
    gráficas de barras/círculos ni paleta de marca -- para confirmar que
    las 8 secciones traían los números correctos antes de invertir tiempo
    en el diseño visual.
  - Etapa 2, portada + resumen (hecho, aprobado 2026-09-17 contra
    staging con Preview real -- ver CLAUDE.md, no tocar sin pedirlo):
    secciones 1-2 en plantillas horizontales tipo presentación
    (BaseDocTemplate con PageTemplate por sección, ver
    generate_executive_pdf), paleta de marca Vantic real (muestreada de
    app/assets/logo_vantic.png, ver COLOR_* arriba) y logo embebido en la
    portada. La cita editorial (sección 3) se integró como blockquote en
    la misma página horizontal del resumen.
  - Etapa 2, sección 4 (hecho, 2026-09-17): tabla de rejilla verde
    reemplazada por `_RetailerShareBar`, una barra horizontal apilada
    (Flowable custom dibujado a mano con canvas.roundRect + clipping, no
    HorizontalBarChart de reportlab.graphics -- se decidió así porque el
    dato en sí es una proporción de 2 partes que suman 100%, share
    cliente vs. competencia, y una barra tipo "progress bar" con
    clipping representa eso de forma más directa y con más control de
    estilo -- sin bordes duros, esquinas redondeadas, número grande al
    lado -- que armar la gráfica genérica de reportlab.graphics para
    este caso). Sin verde institucional en esta sección.
  - Etapa 2, secciones 5/6/7/8 (hecho, 2026-09-18 -- resto del
    documento, ver CLAUDE.md): sección 5 (Índice de Precio) como
    `_PriceIndexBar`, mismo mecanismo de dibujo a mano que la sección 4
    (roundRect + clipping) -- una barra 0..scale_max con una línea de
    referencia fija en 100 (paridad) y un rombo violeta oscuro marcando
    price_index_median (agregado el mismo día como dato adicional junto
    al promedio, ver insights_engine.py). Sección 6 (Posición Dominante)
    como `_TopThreeCircle`, una dona proporcional dibujada con
    canvas.wedge (no HorizontalBarChart/Pie de reportlab.graphics, mismo
    criterio de control de estilo que la sección 4/5). A diferencia de
    la sección 4 (monocromática violeta, "sin verde institucional" a
    propósito porque ahí no hay una calificación de estado), las
    secciones 5/6 SÍ tienen una calificación por celda
    (price_index_rating/position_rating: verde/amarillo/rojo/
    no_concluyente) -- se colorean con una paleta de semáforo aparte
    (_STATUS_COLORS, tonos "-600" de Tailwind) en vez de violeta, mismo
    criterio de color que ya usa el dashboard para
    Alertas/Oportunidades/Fortalezas (que en la sección 7 reusan esos
    mismos 3 colores, ver _CATEGORIA_STATUS_KEY). Secciones 7
    (Conclusiones) y 8 (Metodología) no tenían un dato numérico natural
    para graficar -- se rediseñaron solo con tipografía/color de marca:
    7 usa `_callout_box` (caja con barra de color a la izquierda, mismo
    patrón que `_cita_blockquote` de la sección 3 pero coloreado por
    categoría) en vez de una lista de viñetas negras; 8 usa
    `_note_box` (fondo lila pálido) para el disclaimer y traduce las
    claves snake_case de metodology["metrics"] a nombres legibles
    (METRIC_DISPLAY_NAMES) -- la etapa 1 imprimía la clave cruda (ej.
    "share_of_shelf_pct") como encabezado.

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
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# Paleta de marca Vantic, extraída con muestreo real de píxeles de
# app/assets/logo_vantic.png (2026-09-17) -- no son valores inventados
# a ojo: el isotipo/wordmark usa una familia de violetas en el rango de
# tono ~270-280°, de la que se tomaron un extremo oscuro (casi carbón,
# con tinte violeta) y uno medio/claro para los acentos. "Carbón" del
# nombre de la paleta es el gris neutro para texto de cuerpo -- no
# forma parte del logo, es la convención tipográfica estándar para no
# usar negro puro sobre los fondos lila.
COLOR_CHARCOAL = colors.HexColor("#2B2B33")
COLOR_CHARCOAL_MUTED = colors.HexColor("#6B6B75")
COLOR_VIOLET_DARK = colors.HexColor("#241640")
COLOR_VIOLET = colors.HexColor("#5B3876")
COLOR_LILAC = colors.HexColor("#8A5FA8")
COLOR_LILAC_PALE = colors.HexColor("#F4EFFA")
COLOR_LILAC_LINE = colors.HexColor("#D9C9EC")

PAGE_LANDSCAPE = landscape(letter)
PAGE_PORTRAIT = letter

CARD_SIDE_PADDING = 16  # pt -- padding lateral de _kpi_stat_card, ver su docstring

DATOS_INSUFICIENTES = "Datos insuficientes"

# Colores de semáforo (secciones 5/6/7, agregado 2026-09-18): DISTINTOS
# de la paleta de marca violeta de arriba a propósito -- verde/ámbar/rojo
# comunican un estado (bien/atención/crítico), no identidad de marca, y
# es el mismo criterio de color que ya usa el dashboard (rose/amber/
# emerald) para Alertas/Oportunidades/Fortalezas. Tonos "-600" de
# Tailwind (más oscuros que los "-400" del dashboard, pensado para modo
# oscuro) para que el texto tenga suficiente contraste sobre fondo
# blanco de página impresa.
_STATUS_HEX = {
    "verde": "#059669",
    "amarillo": "#D97706",
    "rojo": "#E11D48",
}
_STATUS_COLORS = {key: colors.HexColor(value) for key, value in _STATUS_HEX.items()}
_STATUS_COLORS["no_concluyente"] = COLOR_CHARCOAL_MUTED

# Alertas/Oportunidades/Fortalezas (sección 7) no son una calificación
# verde/amarillo/rojo por celda como price_index_rating/position_rating
# -- son 3 CATEGORÍAS fijas, pero comparten exactamente los mismos 3
# colores que el dashboard ya usa para ellas (rojo=Alertas,
# amarillo=Oportunidades, verde=Fortalezas), así que reusan _STATUS_HEX/
# _STATUS_COLORS en vez de duplicar la paleta.
_CATEGORIA_STATUS_KEY = {"Alertas": "rojo", "Oportunidades": "amarillo", "Fortalezas": "verde"}

# Nombres legibles para las claves de metodology["metrics"] (snake_case,
# pensadas para consumo por API/frontend) -- la etapa 1 imprimía la
# clave cruda (ej. "share_of_shelf_pct") como encabezado en el PDF; la
# etapa 2 la traduce a un nombre presentable sin tocar el dict de
# /methodology (que otros consumidores sí esperan en snake_case).
METRIC_DISPLAY_NAMES = {
    "share_of_shelf_pct": "Share of Shelf",
    "price_index": "Índice de Precio",
    "availability_pct": "Disponibilidad",
    "dn_pct": "Distribución Numérica (% DN)",
    "dp_pct": "Distribución Ponderada (% DP)",
    "pct_promoted": "% Promocionado",
}


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v:.1f}%" if v is not None else DATOS_INSUFICIENTES


def _fmt_index(v: Optional[float]) -> str:
    return f"{v:.1f}" if v is not None else DATOS_INSUFICIENTES


def _fmt_position(v: Optional[int]) -> str:
    return f"#{v}" if v is not None else "N/D"


def _as_float(v) -> Optional[float]:
    """Convierte a float nativo de forma segura, o None si v es None.

    psycopg2 devuelve columnas numéricas (price, discount_price, y por
    lo tanto todo lo derivado de ellas: price_index, price_index_median,
    client_top3_pct si alguna vez se derivara de un numeric) como
    decimal.Decimal -- comparar un Decimal con un float (`<`, `min`,
    `max`) funciona bien, pero OPERAR uno con otro (`/`, `*`) lanza
    TypeError real (ya documentado una vez en este mismo módulo, ver
    _pick_highlight_insight._gap -- y confirmado de nuevo en staging
    2026-09-18 al agregar las barras/donas de las secciones 5/6, que sí
    dividen y multiplican estos valores, algo que las tablas de texto de
    la etapa 1 nunca hacían). Se castea en el punto donde los datos
    entran a este módulo (_retailer_price_index_rows/_retailer_top3_rows)
    en vez de en cada operación aritmética individual."""
    return float(v) if v is not None else None


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
        name="PortadaTitulo", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=34, leading=40, alignment=TA_CENTER, textColor=COLOR_CHARCOAL,
    ))
    styles.add(ParagraphStyle(
        name="PortadaSubtitulo", parent=styles["Normal"], fontName="Helvetica",
        fontSize=15, leading=19, alignment=TA_CENTER, textColor=COLOR_VIOLET, spaceBefore=10,
    ))
    styles.add(ParagraphStyle(
        name="PortadaMeta", parent=styles["Normal"], fontName="Helvetica",
        fontSize=10.5, leading=14, alignment=TA_CENTER, textColor=COLOR_CHARCOAL_MUTED, spaceBefore=4,
    ))
    styles.add(ParagraphStyle(
        name="ResumenTitulo", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=20, leading=24, textColor=COLOR_CHARCOAL, spaceAfter=10,
    ))
    styles.add(ParagraphStyle(
        name="ResumenProsa", parent=styles["Normal"], fontName="Helvetica",
        fontSize=10.5, leading=15, alignment=TA_LEFT, textColor=COLOR_CHARCOAL,
    ))
    styles.add(ParagraphStyle(
        name="CitaEditorial", parent=styles["Normal"], fontName="Helvetica-Oblique",
        fontSize=11.5, alignment=TA_LEFT, textColor=COLOR_VIOLET_DARK, leading=16,
    ))
    styles.add(ParagraphStyle(
        name="CardLabel", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10, alignment=TA_CENTER, textColor=COLOR_LILAC_LINE, spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name="CardNumero", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=50, leading=54, alignment=TA_CENTER, textColor=colors.white,
    ))
    styles.add(ParagraphStyle(
        name="CardKPIValor", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=14, alignment=TA_CENTER, textColor=colors.white,
    ))
    styles.add(ParagraphStyle(
        name="CardKPILabel", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7.5, alignment=TA_CENTER, textColor=COLOR_LILAC_LINE,
    ))
    styles.add(ParagraphStyle(
        name="SeccionTitulo", parent=styles["Heading2"], spaceBefore=18, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="SeccionTituloBrand", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=17, leading=21, textColor=COLOR_CHARCOAL, spaceBefore=6, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="LegendLabel", parent=styles["Normal"], fontName="Helvetica",
        fontSize=8.5, textColor=COLOR_CHARCOAL_MUTED,
    ))
    styles.add(ParagraphStyle(
        name="CategoriaTitulo", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=12.5, leading=16, textColor=COLOR_CHARCOAL, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="CalloutTexto", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9.5, leading=13.5, textColor=COLOR_CHARCOAL,
    ))
    styles.add(ParagraphStyle(
        name="MetodologiaSubtitulo", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=11, leading=14, textColor=COLOR_VIOLET, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="NotaTexto", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9.5, leading=14, textColor=COLOR_CHARCOAL,
    ))
    styles.add(ParagraphStyle(
        name="MetricaNombre", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10.5, leading=14, textColor=COLOR_VIOLET, spaceBefore=4,
    ))
    styles.add(ParagraphStyle(
        name="MetodologiaTexto", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9, leading=13, textColor=COLOR_CHARCOAL_MUTED,
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


def _draw_portada_background(canvas, doc):
    """Fondo de la portada (plantilla 'Portada', horizontal): lavado lila
    pálido de página completa + franja sólida violeta oscuro en el borde
    superior + un motivo decorativo de círculos en la esquina inferior
    derecha, en eco del isotipo de nodos conectados del logo -- puramente
    ornamental, no reemplaza al logo real (que se inserta como Image
    dentro del frame, no aquí)."""
    width, height = PAGE_LANDSCAPE
    canvas.saveState()
    canvas.setFillColor(COLOR_LILAC_PALE)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    band_height = 1.6 * cm
    canvas.setFillColor(COLOR_VIOLET_DARK)
    canvas.rect(0, height - band_height, width, band_height, stroke=0, fill=1)
    for x, y, r, color in (
        (width - 2.3 * cm, 2.7 * cm, 0.55 * cm, COLOR_LILAC),
        (width - 1.2 * cm, 3.8 * cm, 0.32 * cm, COLOR_VIOLET),
        (width - 3.4 * cm, 1.7 * cm, 0.28 * cm, COLOR_VIOLET_DARK),
        (width - 0.9 * cm, 1.5 * cm, 0.18 * cm, COLOR_LILAC),
    ):
        canvas.setFillColor(color)
        canvas.circle(x, y, r, stroke=0, fill=1)
    canvas.restoreState()


def _draw_resumen_background(canvas, doc):
    """Fondo de la página de Resumen Ejecutivo (plantilla 'Resumen',
    horizontal): mismo lavado lila pálido, con una franja delgada
    violeta oscuro arriba para mantener continuidad de marca con la
    portada sin repetir el mismo peso visual."""
    width, height = PAGE_LANDSCAPE
    canvas.saveState()
    canvas.setFillColor(COLOR_LILAC_PALE)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    band_height = 0.5 * cm
    canvas.setFillColor(COLOR_VIOLET_DARK)
    canvas.rect(0, height - band_height, width, band_height, stroke=0, fill=1)
    canvas.restoreState()


def _cita_blockquote(texto: str, styles) -> Table:
    """Cita editorial (sección 3, integrada en la misma página horizontal
    del resumen) como blockquote: barra violeta a la izquierda + fondo
    blanco, en vez de texto centrado suelto como en la etapa 1."""
    table = Table([[Paragraph(f"“{texto}”", styles["CitaEditorial"])]], colWidths=[None])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LINEBEFORE", (0, 0), (0, -1), 3, COLOR_VIOLET),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return table


def _callout_box(texto: str, color, styles) -> Table:
    """Caja con barra de color a la izquierda -- generaliza el patrón
    visual de `_cita_blockquote` (específica para la cita editorial en
    cursiva violeta) para la sección 7 (Conclusiones), donde el color de
    la barra es el de la categoría (Alertas/Oportunidades/Fortalezas,
    ver _STATUS_COLORS) en vez de fijo violeta."""
    table = Table([[Paragraph(texto, styles["CalloutTexto"])]], colWidths=[None])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LINEBEFORE", (0, 0), (0, -1), 3, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _note_box(texto: str, styles) -> Table:
    """Caja con fondo lila pálido de página completa -- para el
    disclaimer de la sección 8 (Metodología), a modo de 'nota'
    destacada en vez de un párrafo suelto como en la etapa 1."""
    table = Table([[Paragraph(texto, styles["NotaTexto"])]], colWidths=[None])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_LILAC_PALE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return table


def _kpi_stat_card(period: dict, styles, width: float) -> Table:
    """Tarjeta violeta con la cifra grande de Share of Shelf + 3 KPIs de
    apoyo (DN, DP, Disponibilidad) apilados debajo -- reemplaza la cifra
    suelta de la etapa 1 con el formato de 'tarjeta de presentación' de
    la columna derecha del Resumen Ejecutivo. No recalcula nada: reusa
    los mismos campos de `period` que ya consumían las demás secciones."""
    kpis = [
        ("DN", _fmt_pct(period.get("dn_pct"))),
        ("DP", _fmt_pct(period.get("dp_pct"))),
        ("Disponib.", _fmt_pct(period.get("availability_pct"))),
    ]
    # `width` es el ancho TOTAL de la tarjeta (ver colWidths=[width] más
    # abajo) -- la tabla de KPIs va anidada dentro de esa misma tarjeta,
    # así que su ancho debe descontar el padding lateral de la tarjeta
    # (CARD_SIDE_PADDING*2) o se sale del borde violeta. Confirmado con
    # evidencia real contra staging (2026-09-17): con
    # availability_pct=100.0, "100.0%" se salía físicamente del borde
    # derecho de la tarjeta -- no era un caso hipotético.
    inner_width = width - 2 * CARD_SIDE_PADDING
    kpi_table = Table(
        [[Paragraph(v, styles["CardKPIValor"]) for _, v in kpis], [Paragraph(k, styles["CardKPILabel"]) for k, _ in kpis]],
        colWidths=[inner_width / 3.0] * 3,
    )
    kpi_table.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    card = Table(
        [
            [Paragraph("SHARE OF SHELF", styles["CardLabel"])],
            [Paragraph(_fmt_pct(period["share_of_shelf_pct"]), styles["CardNumero"])],
            [Spacer(1, 0.4 * cm)],
            [kpi_table],
        ],
        colWidths=[width],
    )
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_VIOLET),
        ("TOPPADDING", (0, 0), (0, 0), 20),
        ("BOTTOMPADDING", (0, -1), (0, -1), 20),
        ("LEFTPADDING", (0, 0), (-1, -1), CARD_SIDE_PADDING),
        ("RIGHTPADDING", (0, 0), (-1, -1), CARD_SIDE_PADDING),
        ("LINEBELOW", (0, 1), (0, 1), 0.75, COLOR_LILAC),
        ("TOPPADDING", (0, 3), (0, 3), 10),
    ]))
    return card


class _RetailerShareBar(Flowable):
    """Fila de la sección 4 (Distribución): barra horizontal tipo
    'progress bar' -- violeta (cliente) sobre pista lila clara
    (competencia) -- en vez de una fila de tabla con rejilla verde.
    Reemplaza a `_tabla_distribucion` (etapa 1, eliminada). Dibujada a
    mano con canvas.roundRect + clipping en vez de HorizontalBarChart de
    reportlab.graphics: ver docstring del módulo para la razón.

    `client_share`/`comp_share` en 0-100 o None (sin datos, ej. total de
    SKUs en 0 -- no debería pasar en datos reales pero no se asume).
    Reserva `ROW_GAP` pt de espacio en blanco debajo de su propio
    contenido, así que el llamador solo necesita agregar una instancia
    por retailer al story, sin Spacers entre sí."""

    ROW_H = 46
    ROW_GAP = 16
    BAR_H = 12

    def __init__(self, retailer_label: str, client_share: Optional[float], comp_share: Optional[float],
                 total_skus: int, presente: bool, width: float):
        super().__init__()
        self.retailer_label = retailer_label
        self.client_share = client_share
        self.comp_share = comp_share
        self.total_skus = total_skus
        self.presente = presente
        self.width = width

    def wrap(self, availWidth, availHeight):
        return (self.width, self.ROW_H + self.ROW_GAP)

    def draw(self):
        c = self.canv
        w = self.width
        top = self.ROW_GAP + self.ROW_H

        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(COLOR_CHARCOAL)
        c.drawString(0, top - 12, self.retailer_label)

        c.setFont("Helvetica-Bold", 15)
        c.setFillColor(COLOR_VIOLET if self.client_share is not None else COLOR_CHARCOAL_MUTED)
        c.drawRightString(w, top - 14, _fmt_pct(self.client_share))

        c.setFont("Helvetica", 8)
        c.setFillColor(COLOR_CHARCOAL_MUTED)
        meta = f"{self.total_skus} SKUs totales -- {'presente' if self.presente else 'sin presencia'}"
        c.drawString(0, top - 24, meta)
        c.drawRightString(w, top - 24, f"Competencia {_fmt_pct(self.comp_share)}")

        bar_y = self.ROW_GAP
        radius = self.BAR_H / 2
        c.setFillColor(COLOR_LILAC_LINE)
        c.roundRect(0, bar_y, w, self.BAR_H, radius, stroke=0, fill=1)
        if self.client_share:
            client_w = w * (self.client_share / 100.0)
            c.saveState()
            p = c.beginPath()
            p.roundRect(0, bar_y, w, self.BAR_H, radius)
            c.clipPath(p, stroke=0, fill=0)
            c.setFillColor(COLOR_VIOLET)
            c.rect(0, bar_y, client_w, self.BAR_H, stroke=0, fill=1)
            c.restoreState()


class _ColorLegend(Flowable):
    """Leyenda de color (cuadro violeta = Cliente, cuadro lila =
    Competencia) para la sección 4 -- reemplaza a los encabezados de
    columna que tenía la tabla de la etapa 1, ahora que las barras no
    tienen encabezados propios."""

    def __init__(self, width: float, height: float = 14):
        super().__init__()
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        sq = 9
        y = (self.height - sq) / 2
        c.setFillColor(COLOR_VIOLET)
        c.rect(0, y, sq, sq, stroke=0, fill=1)
        c.setFont("Helvetica", 8.5)
        c.setFillColor(COLOR_CHARCOAL_MUTED)
        c.drawString(sq + 5, y + 1, "Cliente")
        x2 = sq + 5 + c.stringWidth("Cliente", "Helvetica", 8.5) + 16
        c.setFillColor(COLOR_LILAC_LINE)
        c.rect(x2, y, sq, sq, stroke=0, fill=1)
        c.setFillColor(COLOR_CHARCOAL_MUTED)
        c.drawString(x2 + sq + 5, y + 1, "Competencia")


class _Legend(Flowable):
    """Leyenda de color genérica -- generaliza `_ColorLegend` (fija a
    'Cliente'/'Competencia' de la sección 4) para las secciones 5/6, que
    necesitan leyendas de distinto contenido (semáforo verde/ámbar/rojo,
    o el marcador de mediana). `items` es una lista de (color, texto,
    marker) -- marker es "square" (por defecto) o "diamond"."""

    def __init__(self, items: list, width: float, height: float = 14):
        super().__init__()
        self.items = items
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        sq = 9
        y = (self.height - sq) / 2
        x = 0
        c.setFont("Helvetica", 8.5)
        for item in self.items:
            color, label = item[0], item[1]
            marker = item[2] if len(item) > 2 else "square"
            c.setFillColor(color)
            if marker == "diamond":
                cx, cy, r = x + sq / 2, y + sq / 2, sq / 2
                p = c.beginPath()
                p.moveTo(cx, cy + r)
                p.lineTo(cx + r, cy)
                p.lineTo(cx, cy - r)
                p.lineTo(cx - r, cy)
                p.close()
                c.drawPath(p, stroke=0, fill=1)
            else:
                c.rect(x, y, sq, sq, stroke=0, fill=1)
            c.setFillColor(COLOR_CHARCOAL_MUTED)
            c.drawString(x + sq + 5, y + 1, label)
            x += sq + 5 + c.stringWidth(label, "Helvetica", 8.5) + 16


def _retailer_share_rows(by_retailer_dn_dp: list, width: float) -> list:
    """Arma las filas de barra de la sección 4, una por retailer activo,
    ordenadas igual que la tabla de la etapa 1 (por retailer_code) --
    incluye retailers con client_skus=0 (Cafam/Colsubsidio en su momento,
    ver CLAUDE.md), mostrando 0.0% en vez de ocultar la fila."""
    rows = []
    for row in sorted(by_retailer_dn_dp, key=lambda r: r["retailer_code"]):
        total = row["total_skus"]
        client = row["client_skus"]
        share = round(client / total * 100, 1) if total else None
        comp_share = round(100 - share, 1) if share is not None else None
        rows.append(_RetailerShareBar(
            retailer_label=row["retailer_code"].capitalize(),
            client_share=share,
            comp_share=comp_share,
            total_skus=total,
            presente=client > 0,
            width=width,
        ))
    return rows


class _PriceIndexBar(Flowable):
    """Fila de la sección 5 (Índice de Precio): barra horizontal 0..
    scale_max coloreada por semáforo (price_index_rating) -- reemplaza
    la tabla verde de la etapa 1, mismo mecanismo de dibujo a mano
    (roundRect + clipping) que `_RetailerShareBar` en la sección 4, por
    consistencia visual, aunque el dato en sí no es una proporción de 2
    partes sino un único valor centrado en 100 (paridad).

    Dos marcas de referencia sobre la barra: una línea vertical fija en
    el valor 100 (paridad con el mercado), y un rombo violeta oscuro en
    price_index_median (agregado 2026-09-18 -- dato ADICIONAL junto al
    índice oficial, ver la nota completa en insights_engine.py y
    CLAUDE.md sobre por qué conviven ambas métricas en vez de reemplazar
    una a la otra)."""

    ROW_H = 46
    ROW_GAP = 16
    BAR_H = 12

    def __init__(self, retailer_label: str, price_index: Optional[float],
                 price_index_median: Optional[float], rating: str,
                 tena_label: str, scale_max: float, width: float):
        super().__init__()
        self.retailer_label = retailer_label
        self.price_index = price_index
        self.price_index_median = price_index_median
        self.rating = rating
        self.tena_label = tena_label
        self.scale_max = scale_max
        self.width = width

    def wrap(self, availWidth, availHeight):
        return (self.width, self.ROW_H + self.ROW_GAP)

    def draw(self):
        c = self.canv
        w = self.width
        top = self.ROW_GAP + self.ROW_H
        color = _STATUS_COLORS.get(self.rating, COLOR_CHARCOAL_MUTED)

        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(COLOR_CHARCOAL)
        c.drawString(0, top - 12, self.retailer_label)

        c.setFont("Helvetica-Bold", 15)
        c.setFillColor(color)
        c.drawRightString(w, top - 14, _fmt_index(self.price_index))

        c.setFont("Helvetica", 8)
        c.setFillColor(COLOR_CHARCOAL_MUTED)
        c.drawString(0, top - 24, f"Mediana: {_fmt_index(self.price_index_median)}")
        c.drawRightString(w, top - 24, self.tena_label)

        bar_y = self.ROW_GAP
        radius = self.BAR_H / 2
        c.setFillColor(COLOR_LILAC_LINE)
        c.roundRect(0, bar_y, w, self.BAR_H, radius, stroke=0, fill=1)

        if self.price_index is not None:
            value_w = max(0.0, min(w, w * (self.price_index / self.scale_max)))
            c.saveState()
            p = c.beginPath()
            p.roundRect(0, bar_y, w, self.BAR_H, radius)
            c.clipPath(p, stroke=0, fill=0)
            c.setFillColor(color)
            c.rect(0, bar_y, value_w, self.BAR_H, stroke=0, fill=1)
            c.restoreState()

        ref_x = w * (100.0 / self.scale_max)
        c.setStrokeColor(COLOR_VIOLET_DARK)
        c.setLineWidth(1.2)
        c.line(ref_x, bar_y - 2, ref_x, bar_y + self.BAR_H + 2)

        if self.price_index_median is not None:
            med_x = max(0.0, min(w, w * (self.price_index_median / self.scale_max)))
            cy, r = bar_y + self.BAR_H / 2, 4.5
            c.setFillColor(COLOR_VIOLET_DARK)
            p2 = c.beginPath()
            p2.moveTo(med_x, cy + r)
            p2.lineTo(med_x + r, cy)
            p2.lineTo(med_x, cy - r)
            p2.lineTo(med_x - r, cy)
            p2.close()
            c.drawPath(p2, stroke=0, fill=1)


def _retailer_price_index_rows(por_retailer: list, width: float) -> list:
    """Arma las filas de barra de la sección 5, una por retailer con
    price_index_rating calculado -- incluye los que vienen en None
    (Rappi por falta de precio comparable, o cualquier retailer forzado
    a None por price_index_data_quality='partial', ver analytics.py):
    se muestran con la pista vacía y 'Datos insuficientes', no se
    ocultan.

    scale_max: escala común (0..scale_max) para que todas las barras de
    la sección sean comparables entre sí -- múltiplo de 50 por encima
    del mayor valor real presente (price_index O price_index_median,
    el que sea más alto -- confirmado con datos reales que la mediana
    puede superar al promedio, ver CLAUDE.md sobre Carulla 118.0 vs.
    150.0), con un piso de 150 para que la marca de referencia en 100
    nunca quede pegada al borde derecho de una barra corta. Sin incluir
    la mediana aquí, su rombo terminaría pegado al borde derecho (o
    fuera de la pista) cada vez que la mediana superara al promedio --
    confirmado visualmente con este mismo fixture antes de este ajuste."""
    cells = sorted(por_retailer, key=lambda c: c["retailer"])
    real_values = [_as_float(c["price_index"]) for c in cells if c.get("price_index") is not None]
    real_values += [_as_float(c["price_index_median"]) for c in cells if c.get("price_index_median") is not None]
    scale_max = max(150.0, 50.0 * (int(max(real_values, default=100) // 50) + 1)) if real_values else 150.0

    rows = []
    for cell in cells:
        excluded_skus = cell.get("client_price_excluded_skus") or 0
        excluded_price = cell.get("client_price_excluded_avg_price")
        tena_label = (
            f"TENA: ${excluded_price:,.0f} ({excluded_skus} SKUs)" if excluded_skus else "TENA: sin SKUs"
        )
        rows.append(_PriceIndexBar(
            retailer_label=cell["retailer"].capitalize(),
            price_index=_as_float(cell.get("price_index")),
            price_index_median=_as_float(cell.get("price_index_median")),
            rating=cell.get("price_index_rating", "no_concluyente"),
            tena_label=tena_label,
            scale_max=scale_max,
            width=width,
        ))
    return rows


class _TopThreeCircle(Flowable):
    """Fila de la sección 6 (Posición Dominante): dona proporcional con
    el % de SKUs del cliente en el top-3 (client_top3_pct), coloreada
    por semáforo (position_rating) -- reemplaza la tabla verde de la
    etapa 1. Dibujada con canvas.wedge (pie/dona) en vez de una gráfica
    de reportlab.graphics, mismo criterio que las secciones 4/5: más
    control de estilo (grosor de anillo, colores exactos) que la
    gráfica genérica -- el 'agujero' de la dona se logra dibujando un
    círculo blanco encima del centro (la sección está en la plantilla
    portrait 'Normal', fondo de página blanco liso, ver
    generate_executive_pdf)."""

    ROW_H = 50
    ROW_GAP = 14
    DIAM = 42
    RING_W = 7

    def __init__(self, retailer_label: str, top3_pct: Optional[float],
                 client_best_position: Optional[int], competition_best_position: Optional[int],
                 rating: str, width: float):
        super().__init__()
        self.retailer_label = retailer_label
        self.top3_pct = top3_pct
        self.client_best_position = client_best_position
        self.competition_best_position = competition_best_position
        self.rating = rating
        self.width = width

    def wrap(self, availWidth, availHeight):
        return (self.width, self.ROW_H + self.ROW_GAP)

    def draw(self):
        c = self.canv
        color = _STATUS_COLORS.get(self.rating, COLOR_CHARCOAL_MUTED)
        cy = self.ROW_GAP + self.ROW_H / 2
        cx = self.DIAM / 2
        r = self.DIAM / 2

        c.setFillColor(COLOR_LILAC_LINE)
        c.wedge(cx - r, cy - r, cx + r, cy + r, 0, 360, stroke=0, fill=1)
        if self.top3_pct is not None and self.top3_pct > 0:
            extent = -(min(self.top3_pct, 100.0) / 100.0 * 360)
            c.setFillColor(color)
            c.wedge(cx - r, cy - r, cx + r, cy + r, 90, extent, stroke=0, fill=1)

        c.setFillColor(colors.white)
        c.circle(cx, cy, r - self.RING_W, stroke=0, fill=1)

        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(color if self.top3_pct is not None else COLOR_CHARCOAL_MUTED)
        label = _fmt_pct(self.top3_pct) if self.top3_pct is not None else "N/D"
        c.drawCentredString(cx, cy - 4, label)

        text_x = self.DIAM + 16
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(COLOR_CHARCOAL)
        c.drawString(text_x, cy + 6, self.retailer_label)
        c.setFont("Helvetica", 8.5)
        c.setFillColor(COLOR_CHARCOAL_MUTED)
        meta = (
            f"Mejor posición cliente: {_fmt_position(self.client_best_position)}   "
            f"Competencia: {_fmt_position(self.competition_best_position)}"
        )
        c.drawString(text_x, cy - 6, meta)


def _retailer_top3_rows(por_retailer: list, width: float) -> list:
    """Arma las filas de dona de la sección 6, una por retailer con
    position_rating calculado -- client_top3_pct puede ser None (cliente
    sin presencia en la celda) sin ocultar la fila, mismo criterio que
    el resto de las secciones."""
    rows = []
    for cell in sorted(por_retailer, key=lambda c: c["retailer"]):
        rows.append(_TopThreeCircle(
            retailer_label=cell["retailer"].capitalize(),
            top3_pct=_as_float(cell.get("client_top3_pct")),
            client_best_position=cell.get("client_best_position"),
            competition_best_position=cell.get("competition_best_position"),
            rating=cell.get("position_rating", "no_concluyente"),
            width=width,
        ))
    return rows


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

    # Secciones 1-2 (Portada, Resumen Ejecutivo) van en plantillas
    # horizontales tipo presentación, aprobadas por separado antes de
    # replicar el diseño al resto del documento (ver docstring del
    # módulo) -- las secciones 3-8 se quedan en la plantilla vertical de
    # la etapa 1 por ahora, sin tocar.
    margin_landscape = 1.5 * cm
    portada_band_h = 1.6 * cm
    resumen_band_h = 0.5 * cm
    margin_portrait = 2 * cm

    frame_portada = Frame(
        margin_landscape, margin_landscape,
        PAGE_LANDSCAPE[0] - 2 * margin_landscape,
        PAGE_LANDSCAPE[1] - 2 * margin_landscape - portada_band_h,
        id="portada", showBoundary=0,
    )
    frame_resumen = Frame(
        margin_landscape, margin_landscape,
        PAGE_LANDSCAPE[0] - 2 * margin_landscape,
        PAGE_LANDSCAPE[1] - 2 * margin_landscape - resumen_band_h,
        id="resumen", showBoundary=0,
    )
    frame_normal = Frame(
        margin_portrait, margin_portrait,
        PAGE_PORTRAIT[0] - 2 * margin_portrait,
        PAGE_PORTRAIT[1] - 2 * margin_portrait,
        id="normal", showBoundary=0,
    )

    doc = BaseDocTemplate(
        buffer, pagesize=PAGE_PORTRAIT,
        topMargin=margin_portrait, bottomMargin=margin_portrait,
        leftMargin=margin_portrait, rightMargin=margin_portrait,
    )
    doc.addPageTemplates([
        PageTemplate(id="Portada", frames=[frame_portada], pagesize=PAGE_LANDSCAPE,
                     onPage=_draw_portada_background),
        PageTemplate(id="Resumen", frames=[frame_resumen], pagesize=PAGE_LANDSCAPE,
                     onPage=_draw_resumen_background),
        PageTemplate(id="Normal", frames=[frame_normal], pagesize=PAGE_PORTRAIT),
    ])
    story = []

    period = exec_summary["period"]
    by_retailer_dn_dp = exec_summary["detail"]["distribution"]["by_retailer"]
    por_retailer = insights.get("por_retailer", [])

    # --- 1. Portada (horizontal, plantilla 'Portada') ---
    logo = _logo_flowable(logo_path, max_width_cm=7.0)
    story.append(Spacer(1, 2.6 * cm if logo else 4.2 * cm))
    if logo:
        story.append(logo)
        story.append(Spacer(1, 1.0 * cm))
    story.append(Paragraph(client_name, styles["PortadaTitulo"]))
    story.append(Paragraph("Reporte Ejecutivo de Digital Shelf", styles["PortadaSubtitulo"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(period_label, styles["PortadaMeta"]))
    story.append(Paragraph(
        f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["PortadaMeta"]
    ))
    story.append(NextPageTemplate("Resumen"))
    story.append(PageBreak())

    # --- 2. Resumen ejecutivo (horizontal, plantilla 'Resumen') ---
    # columna izquierda: título + prosa + cita editorial (sección 3,
    # integrada en la misma página); columna derecha: tarjeta violeta
    # con la cifra grande de Share of Shelf + KPIs de apoyo.
    left_col_w = 15.5 * cm
    right_col_w = 8.5 * cm

    left_col_content = [
        Paragraph("Resumen Ejecutivo", styles["ResumenTitulo"]),
        Paragraph(_resumen_prosa(client_name, period, by_retailer_dn_dp), styles["ResumenProsa"]),
    ]
    highlight = _pick_highlight_insight(insights)
    if highlight:
        left_col_content.append(Spacer(1, 0.5 * cm))
        left_col_content.append(_cita_blockquote(highlight["mensaje_especifico"], styles))

    right_col_content = [_kpi_stat_card(period, styles, width=right_col_w - 0.6 * cm)]

    resumen_table = Table([[left_col_content, right_col_content]], colWidths=[left_col_w, right_col_w])
    resumen_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 0.6 * cm),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(resumen_table)
    story.append(NextPageTemplate("Normal"))
    story.append(PageBreak())

    # --- 4. Distribución por retailer (Share of Shelf, DN, DP) ---
    content_width_normal = PAGE_PORTRAIT[0] - 2 * margin_portrait
    story.append(Paragraph("Distribución por Retailer", styles["SeccionTituloBrand"]))
    story.append(_ColorLegend(width=content_width_normal))
    story.append(Spacer(1, 0.3 * cm))
    story.extend(_retailer_share_rows(by_retailer_dn_dp, width=content_width_normal))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        f"% Distribución Numérica (DN): {_fmt_pct(period['dn_pct'])} &nbsp;|&nbsp; "
        f"% Distribución Ponderada (DP): {_fmt_pct(period['dp_pct'])}",
        styles["Normal"],
    ))
    story.append(PageBreak())

    # --- 5. Índice de Precio por retailer ---
    story.append(Paragraph("Índice de Precio por Retailer", styles["SeccionTituloBrand"]))
    story.append(_Legend([
        (_STATUS_COLORS["verde"], "Bien (95-105)"),
        (_STATUS_COLORS["amarillo"], "Atención (80-95 / 105-120)"),
        (_STATUS_COLORS["rojo"], "Crítico (<80 / >120)"),
        (COLOR_VIOLET_DARK, "Mediana (dato adicional)", "diamond"),
    ], width=content_width_normal))
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph(
        "La línea vertical marca 100 (paridad de precio con la competencia).",
        styles["LegendLabel"],
    ))
    story.append(Spacer(1, 0.25 * cm))
    story.extend(_retailer_price_index_rows(por_retailer, width=content_width_normal))
    story.append(PageBreak())

    # --- 6. Posición dominante por retailer (% top-3) ---
    story.append(Paragraph("Posición Dominante por Retailer", styles["SeccionTituloBrand"]))
    story.append(Paragraph(
        "% de SKUs del cliente en el top-3 de resultados de búsqueda, por retailer.",
        styles["LegendLabel"],
    ))
    story.append(Spacer(1, 0.25 * cm))
    story.extend(_retailer_top3_rows(por_retailer, width=content_width_normal))
    story.append(PageBreak())

    # --- 7. Conclusiones clave ---
    story.append(Paragraph("Conclusiones Clave", styles["SeccionTituloBrand"]))
    story.append(Paragraph(
        "Los hallazgos más relevantes de cada categoría en el período, con el número real que los sustenta.",
        styles["LegendLabel"],
    ))
    story.append(Spacer(1, 0.3 * cm))
    for titulo, lista in (
        ("Alertas", insights.get("alertas", [])),
        ("Oportunidades", insights.get("oportunidades", [])),
        ("Fortalezas", insights.get("fortalezas", [])),
    ):
        status_key = _CATEGORIA_STATUS_KEY[titulo]
        story.append(Paragraph(
            f'<font color="{_STATUS_HEX[status_key]}">&#9679;</font> {titulo}', styles["CategoriaTitulo"]
        ))
        if not lista:
            story.append(Paragraph("Sin elementos en esta categoría en el período.", styles["LegendLabel"]))
        else:
            for item in lista[:3]:
                story.append(_callout_box(item["mensaje_especifico"], _STATUS_COLORS[status_key], styles))
                story.append(Spacer(1, 0.15 * cm))
        story.append(Spacer(1, 0.3 * cm))
    story.append(PageBreak())

    # --- 8. Metodología ---
    story.append(Paragraph("Metodología", styles["SeccionTituloBrand"]))
    story.append(Paragraph(methodology.get("audit_type", ""), styles["MetodologiaSubtitulo"]))
    story.append(_note_box(methodology.get("disclaimer", ""), styles))
    story.append(Spacer(1, 0.35 * cm))
    for metric_key, metric_text in methodology.get("metrics", {}).items():
        story.append(Paragraph(METRIC_DISPLAY_NAMES.get(metric_key, metric_key), styles["MetricaNombre"]))
        story.append(Paragraph(metric_text, styles["MetodologiaTexto"]))
        story.append(Spacer(1, 0.18 * cm))
    caveats = methodology.get("known_data_quality_caveats", [])
    if caveats:
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph("Limitaciones de datos conocidas", styles["MetricaNombre"]))
        for caveat in caveats:
            story.append(Paragraph(f"&bull; {caveat}", styles["MetodologiaTexto"]))

    doc.build(story)
    return buffer.getvalue()
