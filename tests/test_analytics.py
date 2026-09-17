"""
Pruebas de las funciones puras de app/routers/analytics.py
(_price_index_data_quality, _compute_distribution_metrics,
_build_methodology). Ninguna requiere base de datos.

Contexto _price_index_data_quality: el Índice de Precio de Colsubsidio
(2026-09-15) y de Locatel (2026-09-17) se descubrió contaminado por
productos de otra categoría (copa menstrual, kit reutilizable) mezclados
en el buscador VTEX -- confirmado con evidencia real para ambos (ver
nota junto a RETAILERS_WITH_UNRELIABLE_PRICE_INDEX). Los otros 6
retailers investigados con el mismo método el 2026-09-17 (Éxito,
Carulla, Farmatodo, La Rebaja, Pasteur, Coopidrogas) NO mostraron el
problema. Estas pruebas verifican que exactamente esos 2 retailers
fuerzan price_index a "partial" (y por lo tanto None en el endpoint),
sin afectar a los demás retailers ni al Share of Shelf/Disponibilidad.

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
    _drop_unreliable_price_insights,
    _price_index_data_quality,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


class PriceIndexDataQualityTests(unittest.TestCase):
    def test_colsubsidio_alone_is_partial(self):
        self.assertEqual(_price_index_data_quality({"colsubsidio"}), "partial")

    def test_locatel_alone_is_partial(self):
        self.assertEqual(_price_index_data_quality({"locatel"}), "partial")

    def test_colsubsidio_mixed_with_others_is_still_partial(self):
        self.assertEqual(
            _price_index_data_quality({"colsubsidio", "exito", "cafam"}), "partial"
        )

    def test_other_retailers_alone_are_complete(self):
        self.assertEqual(_price_index_data_quality({"exito", "cafam", "carulla"}), "complete")

    def test_empty_set_is_complete(self):
        self.assertEqual(_price_index_data_quality(set()), "complete")

    def test_exactly_colsubsidio_and_locatel_are_flagged(self):
        # Confirmado con evidencia real 2026-09-17: Éxito, Carulla,
        # Farmatodo, La Rebaja, Pasteur y Coopidrogas se investigaron
        # con el mismo método (productos de competencia más caros +
        # búsqueda por palabra clave "copa"/"menstrual"/"reutilizable")
        # y NINGUNO mostró contaminación de categoría -- si este test
        # falla porque se agregó un retailer nuevo al set, confirmar
        # primero con evidencia real (ver metodología documentada junto
        # a RETAILERS_WITH_UNRELIABLE_PRICE_INDEX) antes de aceptarlo.
        self.assertEqual(RETAILERS_WITH_UNRELIABLE_PRICE_INDEX, {"colsubsidio", "locatel"})


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


class DropUnreliablePriceInsightsTests(unittest.TestCase):
    """
    Reproduce el bug real confirmado 2026-09-17 en producción: el PDF
    ejecutivo destacaba como "cita editorial" una alerta de Locatel con
    price_index=46.0 (contaminado, ver RETAILERS_WITH_UNRELIABLE_PRICE_INDEX)
    aunque la tabla por_retailer sí lo forzaba a "Datos insuficientes"
    correctamente. No hay fixture real con filas de Locatel a mano, así
    que el `result` de entrada aquí es sintético -- pero reproduce
    exactamente el shape real que build_insights() devuelve (mismas
    claves: tipo/retailer/metrica/valor_actual/mensaje_especifico) y el
    síntoma real observado.
    """

    def _make_result(self):
        return {
            "alertas": [
                {"tipo": "precio_fuera_de_mercado", "retailer": "Locatel", "metrica": "price_index", "valor_actual": 46.0},
                {"tipo": "precio_fuera_de_mercado", "retailer": "Coopidrogas", "metrica": "price_index", "valor_actual": 133.9},
                {"tipo": "disponibilidad_critica", "retailer": "Locatel", "metrica": "availability_pct", "valor_actual": 50.0},
            ],
            "oportunidades": [
                {"tipo": "precio_por_encima_del_mercado", "retailer": "Locatel", "metrica": "price_index", "valor_actual": 110.0},
            ],
            "fortalezas": [
                {"tipo": "dominio_share_of_shelf", "retailer": "Locatel", "metrica": "share_of_shelf_pct", "valor_actual": 57.8},
            ],
        }

    def test_descarta_insights_de_price_index_para_retailers_no_confiables(self):
        result = _drop_unreliable_price_insights(self._make_result(), {"colsubsidio", "locatel"})
        alertas_precio_locatel = [
            i for i in result["alertas"] if i["retailer"] == "Locatel" and i["metrica"] == "price_index"
        ]
        self.assertEqual(alertas_precio_locatel, [])  # la de price_index se descarta
        self.assertEqual(result["oportunidades"], [])  # la única era de Locatel/price_index

    def test_conserva_insights_de_price_index_para_otros_retailers(self):
        result = _drop_unreliable_price_insights(self._make_result(), {"colsubsidio", "locatel"})
        retailers_con_alerta_precio = {
            i["retailer"] for i in result["alertas"] if i["metrica"] == "price_index"
        }
        self.assertEqual(retailers_con_alerta_precio, {"Coopidrogas"})

    def test_conserva_insights_no_relacionados_a_precio_para_retailers_no_confiables(self):
        # Locatel SÍ debe seguir apareciendo en Disponibilidad/Share of
        # Shelf -- el problema es solo de price_index, no de todo el
        # retailer (a diferencia de RETAILERS_WITH_UNRELIABLE_BRAND_FIELD,
        # que sí excluye todo-o-nada).
        result = _drop_unreliable_price_insights(self._make_result(), {"colsubsidio", "locatel"})
        retailers_alertas_restantes = {i["retailer"] for i in result["alertas"]}
        self.assertIn("Locatel", retailers_alertas_restantes)
        self.assertEqual(len(result["fortalezas"]), 1)
        self.assertEqual(result["fortalezas"][0]["retailer"], "Locatel")


if __name__ == "__main__":
    unittest.main()
