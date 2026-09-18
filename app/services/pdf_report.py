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
  - Etapa 2, secciones 5/6 (pendiente, requiere aprobación de la sección
    4 primero, mismo proceso por partes que portada+resumen): sección 5
    (Índice de Precio) como el mismo tipo de barra; sección 6 (Posición
    Dominante) como círculos proporcionales. Siguen en tabla verde de la
    etapa 1 por ahora, a propósito.

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


def _tabla_indice_precio(por_retailer: list) -> Table:
    """Sección 5: Índice de Precio por retailer -- marca explícitamente
    'Datos insuficientes' en vez de inventar un valor donde price_index
    es None (Rappi por falta de datos comparables, o cualquier retailer
    forzado a None por price_index_data_quality='partial', ver
    /methodology). price_index ya excluye CLIENT_BRANDS_PRICE_EXCLUDED
    (TENA, ver client_brands.py) -- la última columna es informativa: el
    precio promedio de esas marcas excluidas, sin índice porque no
    tienen competencia comparable capturada."""
    table_data = [["Retailer", "Índice de Precio", "Calificación", "TENA (informativo)"]]
    for cell in sorted(por_retailer, key=lambda c: c["retailer"]):
        excluded_skus = cell.get("client_price_excluded_skus") or 0
        excluded_price = cell.get("client_price_excluded_avg_price")
        tena_cell = f"${excluded_price:,.0f} ({excluded_skus} SKUs)" if excluded_skus else "Sin SKUs"
        table_data.append([
            cell["retailer"].capitalize(),
            _fmt_index(cell["price_index"]),
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
