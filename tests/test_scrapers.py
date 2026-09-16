"""
Pruebas de la corrección de marca (brand) en Cafam y Colsubsidio.

Ambos fixtures son evidencia REAL capturada de cada sitio el 2026-09-15
(no son datos inventados):

- tests/fixtures/cafam_raw_sample_2026-09-15.json: respuesta real del
  endpoint de búsqueda AJAX de PrestaShop -- confirma que
  "manufacturer_name" es la razón social del fabricante, no la marca.
- tests/fixtures/colsubsidio_raw_sample_2026-09-15.json: producto real
  recortado (se quitaron campos irrelevantes como installments/PSE) de
  la respuesta VTEX de Colsubsidio -- confirma que "brand" es la razón
  social y que "Marca Comercial" trae la marca comercial real.

No requiere fastapi/psycopg2 -- ambos módulos bajo prueba son puros.
Correr con: python3 -m unittest tests.test_scrapers -v
"""
import json
import os
import unittest

from app.services.scrapers.cafam_scraper import CafamScraper, _detect_client_brand
from app.services.scrapers.vtex_scraper import _resolve_brand, RETAILER_CONFIGS

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


class CafamBrandDetectionTests(unittest.TestCase):
    """El endpoint de búsqueda de Cafam no expone marca comercial real
    (ver limitación documentada en cafam_scraper.py) -- _detect_client_brand
    debe rescatar "nosotras" a partir del nombre del producto para los 3
    productos del fixture real, a pesar de que manufacturer_name trae
    razones sociales distintas ("PRODUCTOS FAMILIA S.A." y "OPERADOR
    LOGISTICO INT DE MEDI") que no coinciden entre sí."""

    def setUp(self):
        self.products = _load_fixture("cafam_raw_sample_2026-09-15.json")

    def test_detects_client_brand_from_title_for_all_real_samples(self):
        for item in self.products:
            with self.subTest(name=item["name"]):
                self.assertEqual(_detect_client_brand(item["name"]), "nosotras")

    def test_parse_products_uses_client_brand_not_manufacturer_name(self):
        scraper = CafamScraper()
        parsed = scraper._parse_products(self.products, "toallas nosotras", limit=10)

        self.assertEqual(len(parsed), 3)
        for product in parsed:
            self.assertEqual(product.brand, "nosotras")

    def test_detect_client_brand_returns_none_for_competitor_product(self):
        self.assertIsNone(_detect_client_brand("Toallas Higiénicas Kotex Ultrafinas"))


class ColsubsidioBrandResolutionTests(unittest.TestCase):
    """Colsubsidio (VTEX) trae la razón social del fabricante en "brand"
    -- _resolve_brand debe preferir el campo de especificación "Marca
    Comercial" configurado en RETAILER_CONFIGS cuando existe, y solo caer
    de vuelta a "brand" cuando el producto no lo tiene (fixture real:
    2 productos, uno con "Marca Comercial" y uno sin ella)."""

    def setUp(self):
        self.products = _load_fixture("colsubsidio_raw_sample_2026-09-15.json")
        self.config = RETAILER_CONFIGS["colsubsidio"]

    def test_prefers_marca_comercial_over_manufacturer_brand(self):
        nosotras_product = self.products[0]
        self.assertEqual(nosotras_product["brand"], "PRODUCTOS FAMILIA SA")
        self.assertEqual(_resolve_brand(nosotras_product, self.config), "Nosotras")

    def test_falls_back_to_brand_when_no_marca_comercial(self):
        other_product = self.products[1]
        self.assertNotIn("Marca Comercial", other_product)
        self.assertEqual(
            _resolve_brand(other_product, self.config), "COLGATE PALMOLIVE COMPANIA"
        )

    def test_other_vtex_retailers_are_unaffected(self):
        # Ningún otro retailer VTEX tiene brand_specification_field --
        # _resolve_brand debe comportarse exactamente como antes (usar
        # "brand" tal cual) para ellos.
        exito_config = RETAILER_CONFIGS["exito"]
        product = {"brand": "PRODUCTOS FAMILIA SA"}
        self.assertEqual(_resolve_brand(product, exito_config), "PRODUCTOS FAMILIA SA")


if __name__ == "__main__":
    unittest.main()
