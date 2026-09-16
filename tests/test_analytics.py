"""
Pruebas de _price_index_data_quality (app/routers/analytics.py).

Contexto: el Índice de Precio de Colsubsidio se descubrió contaminado
por productos de otra categoría (copa menstrual, kit reutilizable)
mezclados en el buscador VTEX -- confirmado con evidencia real
(2026-09-15, ver nota junto a RETAILERS_WITH_UNRELIABLE_PRICE_INDEX).
Estas pruebas verifican que ese retailer específico fuerza price_index
a "partial" (y por lo tanto None en el endpoint), sin afectar a los
demás retailers ni al Share of Shelf/Disponibilidad.

No requiere base de datos -- _price_index_data_quality es una función
pura sobre un set de nombres de retailer.
"""
import unittest

from app.routers.analytics import (
    RETAILERS_WITH_UNRELIABLE_PRICE_INDEX,
    _price_index_data_quality,
)


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


if __name__ == "__main__":
    unittest.main()
