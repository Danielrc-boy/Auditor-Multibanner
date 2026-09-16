"""
Pruebas de las funciones puras de app/routers/analytics.py
(_price_index_data_quality, _compute_distribution_metrics,
_build_methodology). Ninguna requiere base de datos.

Contexto _price_index_data_quality: el Índice de Precio de Colsubsidio
se descubrió contaminado por productos de otra categoría (copa
menstrual, kit reutilizable) mezclados en el buscador VTEX -- confirmado
con evidencia real (2026-09-15, ver nota junto a
RETAILERS_WITH_UNRELIABLE_PRICE_INDEX). Estas pruebas verifican que ese
retailer específico fuerza price_index a "partial" (y por lo tanto None
en el endpoint), sin afectar a los demás retailers ni al Share of
Shelf/Disponibilidad.

Contexto _compute_distribution_metrics: tests/fixtures/
distribution_stats_production_2026-09-15.json es evidencia REAL --
total_skus/client_skus/client_promoted_skus por cada uno de los 10
retailers activos de producción, calculados a partir de
/analytics/positions (endpoint público) el 2026-09-15. En ese momento
Cafam y Colsubsidio todavía mostraban client_skus=0 porque el fix de
marca (ver commits anteriores) corrige el SCRAPER hacia adelante, no
reescribe retroactivamente las filas ya guardadas -- eso es exactamente
lo que se está probando aquí (el cálculo, no si el negocio "se ve bien"
hoy).
"""
import json
import os
import unittest

from app.routers.analytics import (
    RETAILERS_WITH_RELIABLE_AVAILABILITY,
    RETAILERS_WITH_UNRELIABLE_PRICE_INDEX,
    RETAILERS_WITHOUT_RELIABLE_DISCOUNT,
    _build_methodology,
    _compute_distribution_metrics,
    _price_index_data_quality,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


class PriceIndexDataQualityTests(unittest.TestCase):
    def test_colsubsidio_alone_is_partial(self):
        self.assertEqual(_price_index_data_quality({"colsubsidio"}), "partial")

    def test_colsubsidio_mixed_with_others_is_still_partial(self):
        self.assertEqual(
            _price_index_data_quality({"colsubsidio", "exito", "cafam"}), "partial"
        )

    def test_other_retailers_alone_are_complete(self):
        self.assertEqual(_price_index_data_quality({"exito", "cafam", "carulla"}), "complete")

    def test_empty_set_is_complete(self):
        self.assertEqual(_price_index_data_quality(set()), "complete")

    def test_colsubsidio_is_the_only_retailer_flagged(self):
        self.assertEqual(RETAILERS_WITH_UNRELIABLE_PRICE_INDEX, {"colsubsidio"})


class DistributionMetricsRealDataTests(unittest.TestCase):
    """
    A mano, sobre el fixture real (8 de 10 retailers activos con
    client_skus > 0 -- todos menos cafam y colsubsidio):
      DN = 8/10 * 100 = 80.0
      DP = (suma total_skus de esos 8) / (suma total_skus de los 10) * 100
         = 588 / 658 * 100 = 89.4
      pct_promoted (excluye cafam y rappi) =
         (suma client_promoted_skus de los 8 restantes)
         / (suma client_skus de esos mismos 8) * 100
         = 82 / 319 * 100 = 25.7
    """

    @classmethod
    def setUpClass(cls):
        cls.rows = _load_fixture("distribution_stats_production_2026-09-15.json")
        cls.result = _compute_distribution_metrics(cls.rows)

    def test_dn_pct(self):
        self.assertEqual(self.result["dn_pct"], 80.0)
        self.assertEqual(self.result["raw"]["active_retailers"], 10)
        self.assertEqual(self.result["raw"]["retailers_with_client_presence"], 8)

    def test_dp_pct(self):
        self.assertEqual(self.result["dp_pct"], 89.4)
        self.assertEqual(self.result["raw"]["total_catalog_size"], 658)
        self.assertEqual(self.result["raw"]["client_catalog_size"], 588)

    def test_pct_promoted_excludes_cafam_and_rappi(self):
        self.assertEqual(self.result["pct_promoted"], 25.7)
        self.assertEqual(self.result["raw"]["client_skus_promotable"], 319)
        self.assertEqual(self.result["raw"]["client_promoted_skus"], 82)

    def test_excluded_from_promoted_matches_constant(self):
        self.assertEqual(
            set(self.result["raw"]["excluded_from_promoted"]), RETAILERS_WITHOUT_RELIABLE_DISCOUNT
        )


class DistributionMetricsEdgeCaseTests(unittest.TestCase):
    def test_empty_retailer_list_returns_none_not_zero(self):
        result = _compute_distribution_metrics([])
        self.assertIsNone(result["dn_pct"])
        self.assertIsNone(result["dp_pct"])
        self.assertIsNone(result["pct_promoted"])

    def test_cafam_promotions_never_count_even_if_present(self):
        # Cafam con client_skus=10 y client_promoted_skus=10 seria 100%
        # promocionado si se contara -- debe quedar excluido igual que
        # en el fixture real, aunque aqui SI tenga datos de promocion.
        rows = [
            {"retailer_code": "cafam", "total_skus": 10, "client_skus": 10, "client_promoted_skus": 10},
            {"retailer_code": "exito", "total_skus": 10, "client_skus": 10, "client_promoted_skus": 2},
        ]
        result = _compute_distribution_metrics(rows)
        self.assertEqual(result["raw"]["client_skus_promotable"], 10)  # solo exito
        self.assertEqual(result["raw"]["client_promoted_skus"], 2)  # solo exito
        self.assertEqual(result["pct_promoted"], 20.0)

    def test_retailer_with_zero_captures_counts_against_dn_dp(self):
        # Un retailer activo sin NINGUNA fila capturada en el periodo
        # (total_skus=0) debe seguir contando en el denominador de DN,
        # penalizando el %.
        rows = [
            {"retailer_code": "exito", "total_skus": 100, "client_skus": 50, "client_promoted_skus": 0},
            {"retailer_code": "nuevo_retailer", "total_skus": 0, "client_skus": 0, "client_promoted_skus": 0},
        ]
        result = _compute_distribution_metrics(rows)
        self.assertEqual(result["dn_pct"], 50.0)  # 1 de 2 retailers activos
        self.assertEqual(result["dp_pct"], 100.0)  # todo el catalogo capturado es del retailer con presencia


class MethodologyTests(unittest.TestCase):
    def test_explicitly_not_a_retail_audit(self):
        m = _build_methodology()
        self.assertEqual(m["audit_type"], "Digital Shelf Audit")
        self.assertFalse(m["is_retail_audit"])
        self.assertIn("no mide unidades", m["disclaimer"])

    def test_documents_all_seven_metrics(self):
        m = _build_methodology()
        expected = {
            "share_of_shelf_pct", "price_index", "availability_pct",
            "dn_pct", "dp_pct", "pct_promoted",
        }
        self.assertEqual(set(m["metrics"].keys()), expected)

    def test_caveats_reference_current_retailer_sets(self):
        m = _build_methodology()
        caveats_text = " ".join(m["known_data_quality_caveats"]).lower()
        for retailer in RETAILERS_WITH_UNRELIABLE_PRICE_INDEX | RETAILERS_WITHOUT_RELIABLE_DISCOUNT:
            self.assertIn(retailer, caveats_text)
        for retailer in RETAILERS_WITH_RELIABLE_AVAILABILITY:
            self.assertIn(retailer.capitalize(), " ".join(m["known_data_quality_caveats"]))


if __name__ == "__main__":
    unittest.main()
