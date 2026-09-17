"""
Pruebas del generador de PDF ejecutivo (app/services/pdf_report.py).

Usa el mismo fixture real de producción que tests/test_insights_engine.py
(tests/fixtures/production_snapshot_2026-09-15.json) para armar los tres
dicts de entrada (exec_summary, insights, methodology) con el mismo shape
que devuelven /executive-summary, /insights y /methodology -- no datos
sintéticos inventados a mano. methodology se arma reusando
app.routers.analytics._build_methodology() (función pura, sin DB) para no
duplicar ese texto en el test.

No requiere fastapi/psycopg2 para el cálculo de datos (insights_engine.py
y _build_methodology son puros), pero sí importa reportlab (dependencia
real del proyecto) para generar los bytes del PDF.

Correr con: python3 -m unittest tests.test_pdf_report -v
"""
import json
import os
import unittest
from collections import defaultdict

from app.routers.analytics import _build_methodology
from app.services.insights_engine import build_insights, build_retailer_summary
from app.services.pdf_report import generate_executive_pdf

CLIENT_BRANDS = {"nosotras", "pequeñin", "pequeñín", "tena", "zewa"}
RELIABLE_AVAILABILITY_RETAILERS = {"farmatodo"}

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "production_snapshot_2026-09-15.json"
)


def _load_fixture_rows():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def _fake_by_retailer_dn_dp(rows: list) -> list:
    """
    Reconstruye la forma de exec_summary["detail"]["distribution"]["by_retailer"]
    (ver _fetch_retailer_distribution_stats en analytics.py) directamente
    del fixture -- a propósito NO excluye Cafam/Colsubsidio (esta lista sí
    los incluye en el sistema real, ver CLAUDE.md sobre por qué DN/DP no
    excluye por brand no confiable).
    """
    by_retailer = defaultdict(lambda: {"total_skus": 0, "client_skus": 0, "client_promoted_skus": 0})
    for row in rows:
        code = row["retailer"].lower()
        bucket = by_retailer[code]
        bucket["total_skus"] += 1
        is_client = (row.get("brand") or "").strip().lower() in CLIENT_BRANDS
        if is_client:
            bucket["client_skus"] += 1
            discount = row.get("discount_price")
            price = row.get("price") or 0
            if discount and 0 < discount < price:
                bucket["client_promoted_skus"] += 1
    return [{"retailer_code": code, **stats} for code, stats in by_retailer.items()]


def _fake_period_metrics(by_retailer_dn_dp: list) -> dict:
    total_active = len(by_retailer_dn_dp)
    with_presence = [r for r in by_retailer_dn_dp if r["client_skus"] > 0]
    dn_pct = round(len(with_presence) / total_active * 100, 1) if total_active else None
    total_catalog = sum(r["total_skus"] for r in by_retailer_dn_dp)
    client_catalog = sum(r["total_skus"] for r in with_presence)
    dp_pct = round(client_catalog / total_catalog * 100, 1) if total_catalog else None
    return {
        "share_of_shelf_pct": 49.8,
        "price_index": None,
        "availability_pct": 100.0,
        "availability_data_quality": "partial",
        "price_index_data_quality": "partial",
        "dn_pct": dn_pct,
        "dp_pct": dp_pct,
        "pct_promoted": 25.3,
    }


class GenerateExecutivePdfRealDataTests(unittest.TestCase):
    """
    No parsea el contenido del PDF (reportlab no expone texto plano
    fácilmente sin una dependencia extra) -- verifica lo que sí se puede
    afirmar de forma determinística: que el pipeline completo (datos
    reales -> reportlab -> bytes) no revienta con las 8 secciones y sus
    casos límite reales (price_index None, listas de insights vacías,
    logo ausente), y que el resultado es un PDF válido.
    """

    @classmethod
    def setUpClass(cls):
        cls.rows = _load_fixture_rows()
        cls.insights = build_insights(cls.rows, CLIENT_BRANDS, RELIABLE_AVAILABILITY_RETAILERS)
        cls.insights["por_retailer"] = build_retailer_summary(
            cls.rows, CLIENT_BRANDS, RELIABLE_AVAILABILITY_RETAILERS
        )
        cls.by_retailer_dn_dp = _fake_by_retailer_dn_dp(cls.rows)
        cls.exec_summary = {
            "period": _fake_period_metrics(cls.by_retailer_dn_dp),
            "detail": {"distribution": {"by_retailer": cls.by_retailer_dn_dp}},
        }
        cls.methodology = _build_methodology()

    def test_genera_pdf_valido_sin_logo(self):
        pdf_bytes = generate_executive_pdf(
            client_name="Essity",
            period_label="Histórico completo",
            exec_summary=self.exec_summary,
            insights=self.insights,
            methodology=self.methodology,
            logo_path=None,
        )
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"), "El resultado no empieza con la firma %PDF-")
        self.assertGreater(len(pdf_bytes), 1000, "El PDF generado es sospechosamente pequeño")

    def test_no_revienta_con_ruta_de_logo_inexistente(self):
        # Mismo caso que producción hoy: app/assets/logo_vantic.png todavía
        # no existe en el repo -- la portada debe verse sin logo, no lanzar.
        pdf_bytes = generate_executive_pdf(
            client_name="Essity",
            period_label="Histórico completo",
            exec_summary=self.exec_summary,
            insights=self.insights,
            methodology=self.methodology,
            logo_path="app/assets/logo_vantic.png",
        )
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

    def test_no_revienta_con_price_index_none(self):
        # El fixture real (Carulla/Coopidrogas, ambos con price_index
        # numérico) no cubre este caso, así que se agrega una celda
        # sintética con price_index=None (ej. Rappi por falta de precio
        # comparable, o cualquier retailer forzado a None por
        # price_index_data_quality='partial') -- debe imprimir "Datos
        # insuficientes", no lanzar una excepción de formateo.
        insights_con_none = dict(self.insights)
        insights_con_none["por_retailer"] = self.insights["por_retailer"] + [{
            "retailer": "Rappi",
            "price_index": None,
            "price_index_rating": "no_concluyente",
            "client_best_position": 1,
            "client_top3_pct": 100.0,
            "position_rating": "verde",
        }]
        pdf_bytes = generate_executive_pdf(
            client_name="Essity",
            period_label="Histórico completo",
            exec_summary=self.exec_summary,
            insights=insights_con_none,
            methodology=self.methodology,
        )
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

    def test_no_revienta_con_listas_de_insights_vacias(self):
        empty_insights = {"alertas": [], "oportunidades": [], "fortalezas": [], "por_retailer": []}
        pdf_bytes = generate_executive_pdf(
            client_name="Essity",
            period_label="Histórico completo",
            exec_summary=self.exec_summary,
            insights=empty_insights,
            methodology=self.methodology,
        )
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
