"""
Pruebas del motor de insights (app/services/insights_engine.py).

Los datos en tests/fixtures/production_snapshot_2026-09-15.json son el
último snapshot REAL de Carulla, Coopidrogas y Cafam capturado de
producción el 2026-09-15 (mismo criterio de deduplicación que
_fetch_summary_metrics en analytics.py) -- no son datos inventados. Se
eligieron esos tres retailers porque, con ese snapshot, cubren los tres
tipos de insight pedidos (alerta, oportunidad, fortaleza) más el caso de
exclusión por marca no confiable (Cafam).

No requiere fastapi/psycopg2 -- insights_engine.py es un módulo puro.
Correr con: python3 -m unittest tests.test_insights_engine -v
"""
import json
import os
import unittest

from app.services.insights_engine import (
    build_insights,
    build_retailer_summary,
    rate_availability,
    rate_position_dominance,
    rate_price_index,
    rate_share_of_shelf,
)

CLIENT_BRANDS = {"nosotras", "pequeñin", "pequeñín", "tena", "zewa"}
RELIABLE_AVAILABILITY_RETAILERS = {"farmatodo"}

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "production_snapshot_2026-09-15.json"
)


def _load_fixture_rows():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


class RatingFunctionsTests(unittest.TestCase):
    """Cada función de calificación probada por regla, con sus fronteras."""

    def test_share_of_shelf_bands(self):
        self.assertEqual(rate_share_of_shelf(None), "no_concluyente")
        self.assertEqual(rate_share_of_shelf(40.0), "amarillo")   # límite: 40 NO es > 40
        self.assertEqual(rate_share_of_shelf(40.1), "verde")
        self.assertEqual(rate_share_of_shelf(20.0), "amarillo")
        self.assertEqual(rate_share_of_shelf(19.9), "rojo")

    def test_price_index_bands(self):
        self.assertEqual(rate_price_index(None), "no_concluyente")
        self.assertEqual(rate_price_index(100.0), "verde")
        self.assertEqual(rate_price_index(95.0), "verde")
        self.assertEqual(rate_price_index(105.0), "verde")
        self.assertEqual(rate_price_index(94.9), "amarillo")
        self.assertEqual(rate_price_index(105.1), "amarillo")
        self.assertEqual(rate_price_index(120.0), "amarillo")
        self.assertEqual(rate_price_index(79.9), "rojo")
        self.assertEqual(rate_price_index(120.1), "rojo")

    def test_availability_respects_partial_data_quality(self):
        # Un 100% de disponibilidad con calidad "partial" NUNCA es verde --
        # es exactamente el caso que preocupaba al cliente (verde falso).
        self.assertEqual(rate_availability(100.0, "partial"), "no_concluyente")
        self.assertEqual(rate_availability(50.0, "partial"), "no_concluyente")
        self.assertEqual(rate_availability(95.0, "complete"), "verde")
        self.assertEqual(rate_availability(94.9, "complete"), "amarillo")
        self.assertEqual(rate_availability(85.0, "complete"), "amarillo")
        self.assertEqual(rate_availability(84.9, "complete"), "rojo")
        self.assertEqual(rate_availability(None, "complete"), "no_concluyente")

    def test_position_dominance_bands(self):
        self.assertEqual(rate_position_dominance(None), "no_concluyente")
        self.assertEqual(rate_position_dominance(1), "verde")
        self.assertEqual(rate_position_dominance(3), "verde")
        self.assertEqual(rate_position_dominance(4), "amarillo")
        self.assertEqual(rate_position_dominance(10), "amarillo")
        self.assertEqual(rate_position_dominance(11), "rojo")


class BuildInsightsRealDataTests(unittest.TestCase):
    """
    Un caso de cada tipo (alerta / oportunidad / fortaleza), verificado
    contra el snapshot real de producción -- no contra datos sintéticos.
    """

    @classmethod
    def setUpClass(cls):
        rows = _load_fixture_rows()
        cls.result = build_insights(rows, CLIENT_BRANDS, RELIABLE_AVAILABILITY_RETAILERS)

    def _find(self, bucket, tipo, retailer):
        return [
            item for item in self.result[bucket]
            if item["tipo"] == tipo and item["retailer"] == retailer
        ]

    def test_alerta_precio_fuera_de_mercado_en_coopidrogas(self):
        # Coopidrogas sigue en zona roja (133.9) incluso después de
        # excluir TENA del promedio "cliente" (2026-09-17, ver
        # CLIENT_BRANDS_PRICE_EXCLUDED en client_brands.py) -- a
        # diferencia de Carulla, que bajó de rojo a amarillo con el
        # mismo fix (ver test_oportunidad_precio_por_encima_en_carulla).
        matches = self._find("alertas", "precio_fuera_de_mercado", "Coopidrogas")
        self.assertEqual(len(matches), 1, "Se esperaba exactamente una alerta de precio para Coopidrogas")
        insight = matches[0]
        self.assertAlmostEqual(insight["valor_actual"], 133.9, delta=0.5)
        self.assertIn("133", insight["mensaje_especifico"])
        self.assertIn("Coopidrogas", insight["mensaje_especifico"])
        # El mensaje debe traer el número real, no una frase genérica.
        self.assertIn("$", insight["mensaje_especifico"])

    def test_oportunidad_precio_por_encima_en_carulla(self):
        # Confirmado 2026-09-17: antes de excluir TENA del promedio
        # "cliente" (ver CLIENT_BRANDS_PRICE_EXCLUDED en
        # client_brands.py), Carulla mostraba price_index=188.5 (zona
        # roja, "precio_fuera_de_mercado"). TENA es la línea de
        # incontinencia de Essity, sin competencia comparable capturada
        # bajo este término -- excluirla del promedio baja el índice a
        # 118.0 (zona amarilla, "precio_por_encima_del_mercado"), un
        # número real y ya no inflado por una comparación de categorías
        # distintas.
        matches = self._find("oportunidades", "precio_por_encima_del_mercado", "Carulla")
        self.assertEqual(len(matches), 1)
        insight = matches[0]
        self.assertAlmostEqual(insight["valor_actual"], 118.0, delta=0.5)
        self.assertIn("Carulla", insight["mensaje_especifico"])

    def test_oportunidad_brecha_share_of_shelf_en_carulla(self):
        matches = self._find("oportunidades", "brecha_share_of_shelf", "Carulla")
        self.assertEqual(len(matches), 1)
        insight = matches[0]
        # 21 de 53 SKUs = 39.6%, justo debajo del umbral verde de 40%.
        self.assertAlmostEqual(insight["valor_actual"], 39.6, delta=0.1)
        self.assertEqual(insight["valor_referencia"], 40.0)
        self.assertIn("21 de 53", insight["mensaje_especifico"])

    def test_fortaleza_dominio_share_of_shelf_en_coopidrogas(self):
        matches = self._find("fortalezas", "dominio_share_of_shelf", "Coopidrogas")
        self.assertEqual(len(matches), 1)
        insight = matches[0]
        # 26 de 35 SKUs = 74.3% de share.
        self.assertAlmostEqual(insight["valor_actual"], 74.3, delta=0.1)
        self.assertIn("26 de 35", insight["mensaje_especifico"])

    def test_cafam_excluido_por_brand_no_confiable(self):
        excluded_retailers = {item["retailer"] for item in self.result["excluded_cells"]}
        self.assertIn("Cafam", excluded_retailers)

        # Cafam no debe generar NINGÚN insight de las 3 categorías -- ni
        # siquiera una alerta de "ausencia total" (sabemos por los datos
        # reales que el cliente sí tiene 24 SKUs ahí, solo que el campo
        # brand no los identifica -- generar esa alerta sería un falso
        # positivo, exactamente lo que la exclusión evita).
        for bucket in ("alertas", "oportunidades", "fortalezas"):
            retailers_in_bucket = {item["retailer"] for item in self.result[bucket]}
            self.assertNotIn("Cafam", retailers_in_bucket, f"Cafam no debería aparecer en {bucket}")

    def test_todo_insight_trae_numero_real_no_frase_generica(self):
        for bucket in ("alertas", "oportunidades", "fortalezas"):
            for item in self.result[bucket]:
                self.assertIsNotNone(item["valor_actual"], f"{bucket}/{item['tipo']} sin valor_actual")
                self.assertTrue(item["mensaje_especifico"].strip())
                self.assertIn(item["retailer"], item["mensaje_especifico"])


class BuildRetailerSummaryRealDataTests(unittest.TestCase):
    """
    build_retailer_summary() agregado 2026-09-17 para el reporte PDF
    ejecutivo -- mismo fixture real que BuildInsightsRealDataTests, pero
    verificando la agregación por retailer (todos los search_term
    juntos) en vez de por celda (retailer, search_term). El fixture solo
    tiene un search_term, así que los números deben coincidir con los ya
    verificados en build_insights (Carulla 39.6% share / 118.0 índice
    tras excluir TENA, Coopidrogas 74.3% share, Cafam excluido).
    """

    @classmethod
    def setUpClass(cls):
        rows = _load_fixture_rows()
        cls.result = build_retailer_summary(rows, CLIENT_BRANDS, RELIABLE_AVAILABILITY_RETAILERS)

    def _find(self, retailer):
        matches = [c for c in self.result if c["retailer"] == retailer]
        self.assertEqual(len(matches), 1, f"Se esperaba exactamente un retailer '{retailer}'")
        return matches[0]

    def test_cafam_excluido_por_brand_no_confiable(self):
        retailers = {c["retailer"] for c in self.result}
        self.assertNotIn("Cafam", retailers)

    def test_carulla_coincide_con_build_insights(self):
        cell = self._find("Carulla")
        self.assertAlmostEqual(cell["share_of_shelf_pct"], 39.6, delta=0.1)
        self.assertAlmostEqual(cell["price_index"], 118.0, delta=0.5)
        self.assertEqual(cell["search_term"], "TODOS")

    def test_coopidrogas_coincide_con_build_insights(self):
        cell = self._find("Coopidrogas")
        self.assertAlmostEqual(cell["share_of_shelf_pct"], 74.3, delta=0.1)
        self.assertEqual(cell["position_rating"], "verde")

    def test_tena_excluida_del_price_index_pero_reportada_aparte(self):
        # Confirmado 2026-09-17 (ver CLIENT_BRANDS_PRICE_EXCLUDED en
        # client_brands.py): TENA es la línea de incontinencia de Essity,
        # sin competencia comparable bajo este término -- se excluye del
        # promedio "cliente" que alimenta price_index, pero su propio
        # precio promedio se reporta aparte, sin índice.
        carulla = self._find("Carulla")
        self.assertEqual(carulla["client_price_excluded_skus"], 8)
        self.assertAlmostEqual(carulla["client_price_excluded_avg_price"], 45025.0, delta=1.0)
        # client_avg_price (el que alimenta price_index) ya NO incluye
        # TENA -- debe ser mucho menor que el promedio combinado viejo.
        self.assertLess(carulla["client_avg_price"], carulla["client_price_excluded_avg_price"])

        coopidrogas = self._find("Coopidrogas")
        self.assertEqual(coopidrogas["client_price_excluded_skus"], 11)
        self.assertAlmostEqual(coopidrogas["client_price_excluded_avg_price"], 31000.0, delta=1.0)

    def test_client_top3_pct_carulla_y_coopidrogas(self):
        # Carulla: 21 SKUs del cliente, ninguno en top 3 (mejor posición
        # #4 -- ver test_alerta_precio_fuera_de_mercado_en_carulla /
        # posicion_no_dominante en build_insights).
        carulla = self._find("Carulla")
        self.assertAlmostEqual(carulla["client_top3_pct"], 0.0, delta=0.1)
        # Coopidrogas: 26 SKUs del cliente, 3 en top 3 (11.5%) -- domina
        # por tener AL MENOS un SKU en top 3 (client_best_position #1),
        # pero client_top3_pct muestra que es una minoría de su propio
        # catálogo, no "todo el catálogo está arriba".
        coopidrogas = self._find("Coopidrogas")
        self.assertAlmostEqual(coopidrogas["client_top3_pct"], 11.5, delta=0.1)

    def test_devuelve_un_retailer_por_entrada_ordenado(self):
        retailers = [c["retailer"] for c in self.result]
        self.assertEqual(retailers, sorted(retailers))
        self.assertEqual(len(retailers), len(set(retailers)))


if __name__ == "__main__":
    unittest.main()
