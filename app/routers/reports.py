"""
Generación de reportes descargables (PDF ejecutivo). Reusa las funciones
de app/routers/analytics.py directamente (llamadas en Python, no HTTP
interno) para no duplicar ninguna consulta SQL ni lógica de filtros --
este router solo arma el dict de entrada que espera
generate_executive_pdf() y responde con los bytes del PDF.

Este router se conecta a la app principal en main.py con:
    app.include_router(reports.router)
"""
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Response

from app.routers.analytics import get_executive_summary, get_insights, get_methodology
from app.services.client_brands import ACTIVE_CLIENT_NAME
from app.services.pdf_report import generate_executive_pdf

router = APIRouter(tags=["reports"])

# Ruta relativa al directorio de trabajo del proceso (mismo patrón que
# `os.path.exists("app/dashboard.html")` en main.py -- Railway corre la
# app desde la raíz del repo). El archivo aún no existe en el repo
# (pendiente de que se agregue "app/assets/logo_vantic.png" -- versión
# corregida con el nombre "VantiC"); generate_executive_pdf() ya maneja
# su ausencia sin reventar, mostrando la portada solo con texto mientras
# tanto.
LOGO_PATH = "app/assets/logo_vantic.png"


def _period_label(date_from: Optional[datetime], date_to: Optional[datetime]) -> str:
    if not date_from and not date_to:
        return "Histórico completo"
    desde = date_from.strftime("%Y-%m-%d") if date_from else "inicio"
    hasta = date_to.strftime("%Y-%m-%d") if date_to else "hoy"
    return f"Período: {desde} a {hasta}"


@router.get("/reports/executive-pdf")
def get_executive_pdf(
    retailer: Optional[str] = Query(None),
    search_term: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    exec_summary = get_executive_summary(retailer, search_term, date_from, date_to)
    insights = get_insights(retailer, search_term, date_from, date_to)
    methodology = get_methodology()

    pdf_bytes = generate_executive_pdf(
        client_name=ACTIVE_CLIENT_NAME,
        period_label=_period_label(date_from, date_to),
        exec_summary=exec_summary,
        insights=insights,
        methodology=methodology,
        logo_path=LOGO_PATH if os.path.exists(LOGO_PATH) else None,
    )
    filename = f"reporte-ejecutivo-{datetime.now().strftime('%Y-%m-%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
