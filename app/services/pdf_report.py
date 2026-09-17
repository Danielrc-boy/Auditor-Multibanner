"""
Generador del PDF ejecutivo. v1: solo texto y datos reales (sin diseño
visual elaborado -- tablas simples en vez de las gráficas de barras/
círculos que se agregarán en la v2), para probar que el pipeline
completo (fetch de datos -> reportlab -> bytes de PDF válidos) funciona
con datos reales antes de invertir tiempo en el diseño final.

Decisión de librería (2026-09-17): reportlab, no fpdf2 ni WeasyPrint.
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
    formas Circle/Drawing) para las gráficas nativas de la v2 sin
    necesitar matplotlib ni generar imágenes intermedias.

Módulo puro (no toca la base de datos ni FastAPI): recibe los mismos
dicts que ya devuelven /executive-summary, /insights y /methodology
como parámetros, para poder probarlo con datos capturados reales sin
levantar el servidor. El router (app/routers/reports.py) solo arma esos
tres dicts y llama a generate_executive_pdf().
"""
import io
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
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


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v:.1f}%" if v is not None else "Datos insuficientes"


def _fmt_index(v: Optional[float]) -> str:
    return f"{v:.1f}" if v is not None else "Datos insuficientes"


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
    else:
        frases.append(
            "El Índice de Precio consolidado no se pudo calcular de forma confiable en este período "
            "(ver metodología para el detalle de qué retailers quedan excluidos y por qué)."
        )
    frases.append(f"La disponibilidad reportada del cliente es de {disponibilidad}.")
    return " ".join(frases)


def generate_executive_pdf(
    client_name: str,
    period_label: str,
    exec_summary: dict,
    insights: dict,
    methodology: dict,
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
    story.append(Spacer(1, 4 * cm))
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

    # --- 4/5/6. Tablas por retailer (v1 texto -- se reemplazan por
    # gráficas de barras/círculos en la v2) ---
    story.append(Paragraph("Desempeño por Retailer", styles["SeccionTitulo"]))
    dn_dp_by_code = {r["retailer_code"]: r for r in by_retailer_dn_dp}
    table_data = [[
        "Retailer", "Share of Shelf", "Índice de Precio", "Mejor posición cliente",
        "Presente (DN)", "SKUs promocionados",
    ]]
    for cell in por_retailer:
        dn_row = dn_dp_by_code.get(cell["retailer"].lower(), {})
        table_data.append([
            cell["retailer"].capitalize(),
            _fmt_pct(cell["share_of_shelf_pct"]),
            _fmt_index(cell["price_index"]),
            _fmt_position(cell["client_best_position"]),
            "Sí" if dn_row.get("client_skus", 0) > 0 else "No",
            str(dn_row.get("client_promoted_skus", "N/D")),
        ])
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a6b3c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        f"% Distribución Numérica (DN): {_fmt_pct(period['dn_pct'])} &nbsp;|&nbsp; "
        f"% Distribución Ponderada (DP): {_fmt_pct(period['dp_pct'])} &nbsp;|&nbsp; "
        f"% Promocionado: {_fmt_pct(period['pct_promoted'])}",
        styles["Normal"],
    ))
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
